import logging
import unittest
from unittest.mock import Mock
from winrt.windows.devices.enumeration import DevicePairingKinds, DevicePairingProtectionLevel
from pin_pairing import respond_to_pairing_event, SUPPORTED_KINDS, REQUIRED_LEVEL, default_pin, valid_pin

class TestPairingHandler(unittest.TestCase):
    def setUp(self):
        self.log = logging.getLogger("pairing-test")

    def test_pin(self):
        args = Mock(pairing_kind=DevicePairingKinds.PROVIDE_PIN)
        self.assertTrue(respond_to_pairing_event(args, "639272", self.log))
        args.accept.assert_called_once_with("639272")

    def test_confirm(self):
        args = Mock(pairing_kind=DevicePairingKinds.CONFIRM_ONLY)
        self.assertTrue(respond_to_pairing_event(args, "639272", self.log))
        args.accept.assert_called_once_with()
        self.assertEqual(REQUIRED_LEVEL, DevicePairingProtectionLevel.ENCRYPTION_AND_AUTHENTICATION)

    def test_unsupported_kinds(self):
        for kind in (DevicePairingKinds.DISPLAY_PIN, DevicePairingKinds.CONFIRM_PIN_MATCH):
            args = Mock(pairing_kind=kind)
            self.assertFalse(respond_to_pairing_event(args, "639272", self.log))
            args.accept.assert_not_called()

    def test_flags_and_pins(self):
        self.assertTrue(SUPPORTED_KINDS & DevicePairingKinds.PROVIDE_PIN)
        self.assertTrue(SUPPORTED_KINDS & DevicePairingKinds.CONFIRM_ONLY)
        self.assertEqual(default_pin("ROTATOR-BLE"), "639271")
        self.assertEqual(default_pin("ROTATOR-REMOTE-BLE"), "639272")
        self.assertTrue(valid_pin("639272"))
        self.assertFalse(valid_pin("63927"))

if __name__=="__main__":
    unittest.main()
