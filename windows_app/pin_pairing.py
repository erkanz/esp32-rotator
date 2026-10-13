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


def default_pin(name):
    return DEFAULT_PINS.get((name or "").upper(), "")


def valid_pin(pin):
    return isinstance(pin, str) and len(pin) == 6 and pin.isascii() and pin.isdecimal()


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
        required = DevicePairingProtectionLevel.ENCRYPTION_AND_AUTHENTICATION

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

        def pairing_requested(_sender, args):
            seen.append(args.pairing_kind)
            if args.pairing_kind == DevicePairingKinds.PROVIDE_PIN:
                args.accept(pin)
            else:
                logger.error("Refusing unauthenticated BLE pairing ceremony %s", args.pairing_kind)

        token = custom.add_pairing_requested(pairing_requested)
        try:
            result = await asyncio.wait_for(
                custom.pair_with_protection_level_async(
                    DevicePairingKinds.PROVIDE_PIN, required
                ),
                timeout=35.0,
            )
        finally:
            custom.remove_pairing_requested(token)
        if result.status not in (
            DevicePairingResultStatus.PAIRED,
            DevicePairingResultStatus.ALREADY_PAIRED,
        ):
            raise RuntimeError("BLE PIN pairing failed: " + result.status.name)

        fresh = await DeviceInformation.create_from_id_async(device_id)
        if not fresh.pairing.is_paired or fresh.pairing.protection_level != required:
            raise RuntimeError("Windows did not confirm authenticated (MITM) bonding")
        logger.info("Windows MITM/PIN bonding confirmed; ceremonies=%d", len(seen))
    finally:
        requester.close()
