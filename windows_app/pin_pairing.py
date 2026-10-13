"""Windows authenticated BLE bonding for the ESP32 rotator.

Bleak 2.1.1 WinRT's default pair=True uses CONFIRM_ONLY and may downgrade
to unauthenticated pairing. The ESP32 motor command characteristic requires
Secure Connections + MITM. Pair BEFORE opening a Bleak GATT session.
"""
import asyncio

from winrt.windows.devices.bluetooth import BluetoothLEDevice
from winrt.windows.devices.enumeration import (
    DeviceInformation,
    DevicePairingKinds,
    DevicePairingProtectionLevel,
    DevicePairingResultStatus,
)

DEFAULT_PINS = {"ROTATOR-BLE": "639271", "ROTATOR-REMOTE-BLE": "639272"}
REQUIRED_LEVEL = DevicePairingProtectionLevel.ENCRYPTION_AND_AUTHENTICATION
SUPPORTED_KINDS = DevicePairingKinds.PROVIDE_PIN | DevicePairingKinds.CONFIRM_ONLY


def default_pin(name):
    return DEFAULT_PINS.get((name or "").upper(), "")


def valid_pin(pin):
    return isinstance(pin, str) and len(pin) == 6 and pin.isascii() and pin.isdecimal()


def respond_to_pairing_event(args, pin, logger):
    """Only accept PIN or confirmation; final MITM verification is mandatory."""
    kind = args.pairing_kind
    logger.info("WinRT PairingRequested kind=%s", getattr(kind, "name", str(kind)))
    if kind == DevicePairingKinds.PROVIDE_PIN:
        args.accept(pin)
        logger.info("PIN ceremony accepted (PIN not logged)")
        return True
    if kind == DevicePairingKinds.CONFIRM_ONLY:
        args.accept()
        logger.info("Confirmation accepted; authenticated pairing still required")
        return True
    logger.error("Unsupported pairing kind=%s (not downgrading security)", kind)
    return False


async def ensure_authenticated_bond(device, pin, logger):
    """Require Windows-reported ENCRYPTION_AND_AUTHENTICATION before motor control."""
    if not valid_pin(pin):
        raise ValueError("Enter a six-digit BLE pairing PIN")

    requester = await BluetoothLEDevice.from_bluetooth_address_async(
        int(device.address.replace(":", ""), 16)
    )
    if requester is None:
        raise RuntimeError("Windows could not open the device for BLE pairing")
    try:
        device_id = requester.device_information.id
        info = await DeviceInformation.create_from_id_async(device_id)
        required = REQUIRED_LEVEL

        if info.pairing.is_paired and info.pairing.protection_level == required:
            logger.info("Windows bond already uses authenticated encryption")
            return

        if info.pairing.is_paired:
            logger.warning("Removing stale unauthenticated BLE bond before PIN pairing")
            outcome = await info.pairing.unpair_async()
            if outcome.status.name not in ("UNPAIRED", "ALREADY_UNPAIRED"):
                raise RuntimeError("Could not remove stale bond: " + outcome.status.name)
            info = await DeviceInformation.create_from_id_async(device_id)

        if not info.pairing.can_pair:
            raise RuntimeError("Windows reports device cannot pair")
        custom = info.pairing.custom
        seen = []
        callback_errors = []

        def pairing_requested(_sender, args):
            try:
                seen.append(getattr(args.pairing_kind, "name", str(args.pairing_kind)))
                respond_to_pairing_event(args, pin, logger)
            except Exception as exc:
                callback_errors.append(f"{type(exc).__name__}: {exc}")
                logger.exception("WinRT PairingRequested callback failed")

        token = custom.add_pairing_requested(pairing_requested)
        try:
            logger.info("Initiating WinRT PIN-capable pairing with MITM protection")
            result = await asyncio.wait_for(
                custom.pair_with_protection_level_async(SUPPORTED_KINDS, required),
                timeout=35.0,
            )
        finally:
            custom.remove_pairing_requested(token)
        logger.info("Pairing result=%s, ceremonies=%s, handler_errors=%s",
                    result.status.name, seen, callback_errors)
        if result.status not in (
            DevicePairingResultStatus.PAIRED,
            DevicePairingResultStatus.ALREADY_PAIRED,
        ):
            raise RuntimeError(
                f"BLE PIN pairing failed: {result.status.name}; ceremonies={seen}; "
                f"handler_errors={callback_errors}"
            )

        fresh = await DeviceInformation.create_from_id_async(device_id)
        if not fresh.pairing.is_paired or fresh.pairing.protection_level != required:
            raise RuntimeError("Windows did not confirm authenticated (MITM) bonding")
        logger.info("Windows MITM/PIN bonding confirmed; ceremonies=%s", seen)
    finally:
        requester.close()
