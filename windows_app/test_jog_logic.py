"""Fake-client test: BLE held JOG is serialized and never floods GATT."""
import asyncio
import logging
import unittest
from rotator_ble import App

class FakeClient:
    is_connected=True
    def __init__(self): self.calls=[]
    async def write_gatt_char(self, uuid, data, response=True):
        await asyncio.sleep(.012)
        self.calls.append((bytes(data),bool(response)))

class JogTests(unittest.IsolatedAsyncioTestCase):
    async def test_heartbeat_stops_on_release(self):
        app=object.__new__(App)
        app.jog=1
        app.jog_token=3
        app.paired=True
        app.fast_jog=True
        app.gatt_lock=asyncio.Lock()
        app.last_status={"online":True,"fault":0}
        app.client=FakeClient()
        app.logger=logging.getLogger("jog-test")
        job=asyncio.create_task(app.jog_worker(3))
        await asyncio.sleep(.32)
        app.jog=0
        app.jog_token+=1
        await asyncio.wait_for(job,1.0)
        calls=list(app.client.calls)
        await asyncio.sleep(.17)
        self.assertEqual(app.client.calls,calls)
        self.assertGreaterEqual(len(calls),2)
        self.assertLessEqual(len(calls),4)
        self.assertTrue(all(x==b"JOG 1" and not resp for x,resp in calls))

    async def test_offline_blocks_jog(self):
        app=object.__new__(App)
        app.jog=-1
        app.jog_token=1
        app.paired=True
        app.fast_jog=True
        app.gatt_lock=asyncio.Lock()
        app.last_status={"online":False,"fault":0}
        app.client=FakeClient()
        app.logger=logging.getLogger("jog-test")
        await app.jog_worker(1)
        self.assertFalse(app.client.calls)
        self.assertEqual(app.jog,0)

if __name__=="__main__":unittest.main()
