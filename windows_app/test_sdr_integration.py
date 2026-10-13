"""Single-EXE SDR UI safety tests: parser and shared secure BLE rotor adapter."""
import asyncio
import json
import logging
import unittest

from sdr_panel import SharedRotor, parse_sweep, SDRSHARP
from rotator_scan import CMD, STATUS, REPLY


class FakeClient:
    is_connected = True
    def __init__(self, role="ROTATOR", fault=0):
        self.role, self.fault = role, fault
        self.az = 120
        self.sent = []
    async def read_gatt_char(self, uuid):
        if uuid == STATUS:
            return json.dumps({"role": self.role,"az": self.az,"fault": self.fault,
                               "online": True,"moving": False}).encode()
        if uuid == REPLY:
            return b"OK accepted"
        raise AssertionError(uuid)
    async def write_gatt_char(self, uuid, payload, response=True):
        self.sent.append(bytes(payload))
        if bytes(payload).startswith(b"AZ "):
            self.az=int(bytes(payload)[3:])


class FakeApp:
    def __init__(self, client):
        self.client=client
        self.paired=True
        self.gatt_lock=asyncio.Lock()
        self.logger=logging.getLogger("sdr-integration-test")
        self.sdr=type("Sdr",(),{"cancel_requested":False})()


class SafetyTests(unittest.IsolatedAsyncioTestCase):
    def test_sweep_configuration(self):
        cfg=parse_sweep("90","180","10","1.5","3.0","45","1.0","47291","96000","12500")
        self.assertEqual(cfg[0][0],90)
        self.assertEqual(cfg[0][-1],180)
        self.assertEqual(len(cfg[0]),10)
        for start,end,step in [("350","5","5"),("0","359","1")]:
            with self.assertRaises(ValueError):
                parse_sweep(start,end,step,"1.5","3","45","1","47291","96000","12500")

    async def test_requires_direct_physical_rotor(self):
        remote=FakeClient(role="REMOTE")
        r=SharedRotor(FakeApp(remote))
        with self.assertRaisesRegex(RuntimeError,"direct ROTATOR"):
            await r.start()
        self.assertEqual(remote.sent,[])

    async def test_requires_fault_free_rotor(self):
        rotor=FakeClient(fault=8)
        with self.assertRaisesRegex(RuntimeError,"fault"):
            await SharedRotor(FakeApp(rotor)).start()
        self.assertEqual(rotor.sent,[])

    async def test_shared_ble_and_az_scan_commands(self):
        client=FakeClient()
        app=FakeApp(client)
        rotor=SharedRotor(app)
        await rotor.start()
        await rotor.move_to(130,timeout=2)
        self.assertEqual(client.az,130)
        self.assertEqual(client.sent,[b"AZ 130"])
        await rotor.stop()
        self.assertEqual(client.sent[-1],b"STOP")
        await rotor.close()
        self.assertTrue(client.is_connected)

    async def test_disconnection_during_scan_fails_closed(self):
        client=FakeClient()
        app=FakeApp(client)
        rotor=SharedRotor(app)
        app.paired=False
        with self.assertRaisesRegex(RuntimeError,"session lost|Connect"):
            await rotor.start()
        self.assertEqual(client.sent,[])

    async def test_no_arbitrary_commands(self):
        client=FakeClient()
        with self.assertRaises(ValueError):
            await SharedRotor(FakeApp(client)).command("HOME")
        self.assertEqual(client.sent,[])


if __name__=="__main__":
    unittest.main()
