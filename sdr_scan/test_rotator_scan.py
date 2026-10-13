"""F09/F10 no-hardware regression tests: motor moves only for fresh, valid metrics."""
import asyncio
import math
import tempfile
import time
import unittest
from pathlib import Path

from rotator_scan import (
    Metric, DemoMetric, DemoRotor, SDRSharpUDPSource, _SNRDatagram,
    angles, circular_distance, measure, perform_scan, relative_snr_from_iq,
)


class ScanTests(unittest.IsolatedAsyncioTestCase):
    def test_angles_and_wrap_rejection(self):
        self.assertEqual(angles(0, 20, 7), [0, 7, 14, 20])
        self.assertEqual(circular_distance(359.0, 1.0), 2)
        with self.assertRaises(ValueError):
            angles(350, 10, 5)
        with self.assertRaises(ValueError):
            angles(0, 359, 1)

    def test_iq_signal_metric_direction(self):
        import numpy as np
        rng = np.random.default_rng(5)
        n, rate = 8192, 96000
        noise = (rng.standard_normal(n) + 1j * rng.standard_normal(n)) * .025
        t = np.arange(n)
        tone = 0.4 * np.exp(2j * np.pi * 1500 * t / rate)
        signal_snr = relative_snr_from_iq(noise + tone, rate, 12500)
        noise_snr = relative_snr_from_iq(noise, rate, 12500)
        self.assertGreater(signal_snr, noise_snr + 15)
        self.assertTrue(math.isfinite(noise_snr))
        with self.assertRaises(ValueError):
            relative_snr_from_iq(noise[:100], rate, 12500)

    async def test_demo_sweep_peak_and_csv(self):
        rotor = DemoRotor()
        source = DemoMetric(rotor)
        with tempfile.TemporaryDirectory() as td:
            out = Path(td, "data.csv")
            best, rows = await perform_scan(
                rotor, source, [90, 125, 135, 145, 165],
                settle=0.015, dwell=0.42, timeout=1.0,
                output=out, min_db=0,
            )
            self.assertEqual(best.az, 135)
            self.assertEqual(rotor.az, 135)
            self.assertEqual(len(rows), 5)
            self.assertTrue(out.read_text().startswith("utc_start,az"))
            self.assertTrue(all(v.count >= 3 for v in rows))

    async def test_no_source_data_must_not_move(self):
        class DeadSource:
            latest = None
            error = None
            async def start(self): pass
            async def close(self): pass
        class RecorderRotor(DemoRotor):
            def __init__(self):
                super().__init__()
                self.moves = []
                self.stopped = False
            async def move_to(self, az, timeout, tolerance=2):
                self.moves.append(az)
            async def stop(self):
                self.stopped = True
        rotor = RecorderRotor()
        with tempfile.TemporaryDirectory() as td:
            with self.assertRaises(RuntimeError):
                await perform_scan(
                    rotor, DeadSource(), [90, 100],
                    settle=0, dwell=0.4, timeout=1,
                    output=Path(td, "no.csv"), min_db=0,
                )
        self.assertEqual(rotor.moves, [])
        self.assertTrue(rotor.stopped)

    async def test_stale_source_must_abort(self):
        class Source:
            error = None
            latest = Metric(time.monotonic() - 5.0, 99)
        with self.assertRaises(RuntimeError):
            await measure(Source(), 0.45)

    def test_reject_invalid_snr_udp(self):
        class Parent:
            latest = None
        p = Parent()
        handler = _SNRDatagram(p)
        handler.datagram_received(b'{"snr_db":22,"frequency_hz":144390000}', ("127.0.0.1", 111))
        self.assertEqual(p.latest.frequency_hz, 144390000)
        good = p.latest
        handler.datagram_received(b'{"snr_db":"nan"}', ("127.0.0.1", 111))
        handler.datagram_received(b'{"snr_db":40}', ("203.0.113.5", 111))
        handler.datagram_received(b'{"snr_db":40,"playing":false}', ("127.0.0.1", 111))
        self.assertIs(p.latest, good)


if __name__ == "__main__":
    unittest.main()
