"""F09/F10 SDR azimuth scanner (Windows). Direct, authenticated ROTATOR BLE control.

- SDR++: its built-in IQ Exporter in Float32/TCP Server/VFO mode.
- SDR#: optional companion VisualSNR bridge plugin -> localhost UDP.
- Demo: explicit simulation, never moves hardware.
- No firmware, ESP-NOW or existing F11 GUI changes.

Do not use this to point an antenna at a nonstationary signal. Metric is relative
in SDR++ mode, not an RF-calibrated SNR or absolute signal strength.
"""
from __future__ import annotations

import argparse
import asyncio
import csv
import json
import logging
import math
import statistics
import sys
import time
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path

SERVICE = "df8268c0-4cc2-4eaa-85dd-3a6159fe0001"
CMD = "df8268c0-4cc2-4eaa-85dd-3a6159fe0002"
STATUS = "df8268c0-4cc2-4eaa-85dd-3a6159fe0003"
REPLY = "df8268c0-4cc2-4eaa-85dd-3a6159fe0004"
LOG = logging.getLogger("f09_f10")


@dataclass(frozen=True)
class Metric:
    received: float  # monotonic clock
    db: float
    frequency_hz: int | None = None


@dataclass(frozen=True)
class Sample:
    az: int
    median_db: float
    stdev_db: float
    count: int
    frequency_hz: int | None


def angles(start: int, stop: int, step: int) -> list[int]:
    """Deliberately forbid wrap-through; motor firmware owns safe travel limits."""
    if not (0 <= start <= stop <= 359):
        raise ValueError("Require 0 <= start <= stop <= 359. Split wraparound scans.")
    if not 1 <= step <= 90:
        raise ValueError("STEP must be 1..90 degrees")
    out = list(range(start, stop + 1, step))
    if out[-1] != stop:
        out.append(stop)
    if len(out) > 180:
        raise ValueError("Too many positions (max 180)")
    return out


def circular_distance(a: float, b: float) -> float:
    return abs((a - b + 180) % 360 - 180)


def relative_snr_from_iq(iq, sample_rate: int, channel_hz: int) -> float:
    """Relative excess in-channel PSD versus off-channel PSD (not calibrated).

    Signals must be stable/continuous. Keep SDR source gain, AGC, squelch,
    frequency, VFO bandwidth and center offset fixed through the sweep.
    """
    import numpy as np
    n = len(iq)
    if n < 2048 or channel_hz < 100 or channel_hz >= sample_rate * 0.45:
        raise ValueError("Need >=2048 complex samples, valid VFO rate/channel bandwidth")
    window = np.hanning(n)
    psd = np.abs(np.fft.fftshift(np.fft.fft(iq * window))) ** 2
    freqs = np.fft.fftshift(np.fft.fftfreq(n, d=1 / sample_rate))
    abs_freqs = np.abs(freqs)
    inside = (abs_freqs > sample_rate * 3.0 / n) & (abs_freqs < channel_hz / 2)
    outside = (abs_freqs > channel_hz * 0.8) & (abs_freqs < sample_rate * 0.45)
    if inside.sum() < 8 or outside.sum() < 32:
        raise ValueError("Insufficient FFT bins for selected bandwidth")
    # Median out-of-channel bin suppresses occasional adjacent strong stations.
    noise_per_bin = float(np.median(psd[outside]))
    inband_power = float(psd[inside].sum())
    baseline = max(1e-24, noise_per_bin * int(inside.sum()))
    excess = max(1e-6, (inband_power - baseline) / baseline)
    return max(-60.0, min(100.0, 10.0 * math.log10(excess)))


class IQTcpSource:
    """Always read IQ in background: avoids sampling buffered pre-rotation data."""
    def __init__(self, host: str, port: int, sample_rate: int, channel_hz: int):
        self.host, self.port = host, port
        self.sample_rate, self.channel_hz = sample_rate, channel_hz
        self.latest: Metric | None = None
        self.error: Exception | None = None
        self._writer = None
        self._task = None

    async def start(self):
        reader, self._writer = await asyncio.wait_for(
            asyncio.open_connection(self.host, self.port), 7.0
        )
        self._task = asyncio.create_task(self._read(reader))

    async def _read(self, reader):
        import numpy as np
        try:
            while True:
                # SDR++ Float32: little-endian interleaved I,Q; 8192 complex samples.
                raw = await asyncio.wait_for(reader.readexactly(8192 * 8), 3.5)
                interleaved = np.frombuffer(raw, dtype="<f4")
                if not np.isfinite(interleaved).all():
                    continue
                iq = interleaved[0::2] + 1j * interleaved[1::2]
                db = relative_snr_from_iq(iq, self.sample_rate, self.channel_hz)
                self.latest = Metric(time.monotonic(), db)
        except asyncio.CancelledError:
            raise
        except Exception as exc:
            self.error = exc

    async def close(self):
        if self._task is not None:
            self._task.cancel()
            try:
                await self._task
            except asyncio.CancelledError:
                pass
        if self._writer is not None:
            self._writer.close()
            await self._writer.wait_closed()


class _SNRDatagram(asyncio.DatagramProtocol):
    def __init__(self, parent):
        self.parent = parent

    def datagram_received(self, data, addr):
        if addr[0] not in ("127.0.0.1", "::1") or len(data) > 512:
            return
        try:
            obj = json.loads(data)
            if obj.get("playing") is False:
                return
            db = float(obj["snr_db"])
            if not math.isfinite(db) or not -60 <= db <= 120:
                return
            f = obj.get("frequency_hz")
            if f is not None:
                f = int(f)
                if not 1000 <= f <= 100_000_000_000:
                    return
            self.parent.latest = Metric(time.monotonic(), db, f)
        except (ValueError, TypeError, KeyError, json.JSONDecodeError, OverflowError):
            return


class SDRSharpUDPSource:
    """Receives read-only current VisualSNR from the companion SDR# plugin."""
    def __init__(self, port):
        self.port = port
        self.latest: Metric | None = None
        self.error = None
        self._transport = None

    async def start(self):
        loop = asyncio.get_running_loop()
        self._transport, _ = await loop.create_datagram_endpoint(
            lambda: _SNRDatagram(self), local_addr=("127.0.0.1", self.port)
        )

    async def close(self):
        if self._transport:
            self._transport.close()


class RotorBLE:
    """Fail-closed: WinRT MITM bond + authenticated GATT STATUS write required."""
    def __init__(self, pin):
        self.pin = pin
        self.client = None

    async def start(self):
        if sys.platform != "win32":
            raise RuntimeError("Real BLE control uses secure Windows WinRT pairing; use Windows")
        from bleak import BleakScanner, BleakClient
        root = Path(__file__).resolve().parents[1] / "windows_app"
        sys.path.insert(0, str(root))
        from pin_pairing import ensure_authenticated_bond, valid_pin
        if not valid_pin(self.pin):
            raise ValueError("Enter the six-digit ROTATOR-BLE PIN")
        device = await BleakScanner.find_device_by_name("ROTATOR-BLE", timeout=12.0)
        if device is None:
            raise RuntimeError("ROTATOR-BLE not found; enable ROTOR BLE in SETTINGS")
        await ensure_authenticated_bond(device, self.pin, LOG)
        self.client = BleakClient(
            device, pair=False, timeout=25,
            winrt={"use_cached_services": False}
        )
        await self.client.connect()
        if self.client.services.get_service(SERVICE) is None:
            raise RuntimeError("R5.12 BLE control service missing")
        # STATUS read is public. The no-motion STATUS command WRITE proves MITM.
        await self.command("STATUS")
        await self.status()

    async def status(self) -> dict:
        if not self.client or not self.client.is_connected:
            raise RuntimeError("BLE connection lost")
        obj = json.loads((await self.client.read_gatt_char(STATUS)).decode())
        if obj.get("role", "").upper() not in ("ROTATOR", "ROTOR"):
            raise RuntimeError("Connected to REMOTE, not the physical ROTOR")
        if obj.get("fault"):
            raise RuntimeError(f"ROTOR reported fault {obj['fault']}")
        return obj

    async def command(self, name: str):
        if not self.client or not self.client.is_connected:
            raise RuntimeError("BLE disconnected")
        if name != "STATUS" and name != "STOP" and not name.startswith("AZ "):
            raise ValueError("Only STATUS, STOP and AZ movement are permitted")
        await self.client.write_gatt_char(CMD, name.encode("ascii"), response=True)
        reply = (await self.client.read_gatt_char(REPLY)).decode(errors="replace").strip()
        if not reply.upper().startswith("OK"):
            raise RuntimeError(f"ROTOR rejected {name}: {reply}")
        return reply

    async def move_to(self, az: int, timeout: float, tolerance=2.0):
        initial = await self.status()
        if circular_distance(float(initial["az"]), az) > tolerance:
            await self.command(f"AZ {az}")
        deadline = time.monotonic() + timeout
        steady = 0
        while time.monotonic() < deadline:
            s = await self.status()
            if circular_distance(float(s["az"]), az) <= tolerance and not s.get("moving"):
                steady += 1
                if steady >= 2:
                    return
            else:
                steady = 0
            await asyncio.sleep(0.3)
        raise TimeoutError(f"AZ {az} did not settle within {timeout}s; STOP required")

    async def stop(self):
        if self.client and self.client.is_connected:
            try:
                await self.command("STOP")
            except Exception as exc:
                LOG.error("ROTOR STOP failed: %s", exc)

    async def close(self):
        if self.client:
            try:
                await self.client.disconnect()
            finally:
                self.client = None


class DemoRotor:
    """Simulation only. No BLE or physical movement."""
    def __init__(self):
        self.az = 90
    async def start(self): pass
    async def move_to(self, az, timeout, tolerance=2):
        self.az = az
        await asyncio.sleep(.01)
    async def stop(self): pass
    async def close(self): pass


class DemoMetric:
    def __init__(self, rotor):
        self.rotor = rotor
        self.latest = None
        self.error = None
        self._task = None
    async def start(self):
        self._task = asyncio.create_task(self._produce())
    async def _produce(self):
        while True:
            delta = circular_distance(self.rotor.az, 137)
            self.latest = Metric(time.monotonic(), 17 - .015 * delta * delta)
            await asyncio.sleep(.04)
    async def close(self):
        self._task.cancel()
        try:
            await self._task
        except asyncio.CancelledError:
            pass


async def measure(source, seconds: float, min_samples=3) -> tuple[float, float, int, int | None]:
    """Use only measurements generated after the settle interval begins."""
    start = time.monotonic()
    end = start + seconds
    seen_time = start
    values = []
    frequency = None
    while time.monotonic() < end:
        if source.error:
            raise RuntimeError(f"SDR metric stream failed: {source.error}")
        sample = source.latest
        if sample and sample.received > seen_time:
            if time.monotonic() - sample.received > 1.0:
                raise RuntimeError("SDR signal measurement is stale")
            seen_time = sample.received
            if frequency is None:
                frequency = sample.frequency_hz
            elif sample.frequency_hz is not None and sample.frequency_hz != frequency:
                raise RuntimeError("SDR frequency changed during measurement")
            values.append(sample.db)
        await asyncio.sleep(.035)
    if len(values) < min_samples:
        raise RuntimeError(f"No fresh SDR samples ({len(values)}/{min_samples}); scan stopped")
    return statistics.median(values), (statistics.pstdev(values) if len(values) > 1 else 0.0), len(values), frequency


async def perform_scan(rotor, source, azimuths: list[int], *,
                       settle: float, dwell: float, timeout: float,
                       output: Path, min_db: float):
    if dwell < .4 or settle < 0 or timeout < 1:
        raise ValueError("Dwell >=0.4s, settle >=0s, timeout >=1s required")
    output.parent.mkdir(parents=True, exist_ok=True)
    started = datetime.now(timezone.utc).isoformat()
    rows: list[Sample] = []
    completed = False
    try:
        await rotor.start()
        await source.start()
        # Enforce stream health without starting movement yet.
        await measure(source, max(dwell, 1.0))
        with output.open("w", newline="", encoding="utf-8") as fh:
            writer = csv.writer(fh)
            writer.writerow(["utc_start", "az", "median_snr_db", "spread_db", "samples", "freq_hz"])
            for i, az in enumerate(azimuths, 1):
                LOG.info("[%d/%d] Moving to AZ %d", i, len(azimuths), az)
                await rotor.move_to(az, timeout=timeout)
                await asyncio.sleep(settle)
                snr, stdev, samples, freq = await measure(source, dwell)
                row = Sample(az, snr, stdev, samples, freq)
                rows.append(row)
                writer.writerow([started, az, f"{snr:.3f}", f"{stdev:.3f}", samples, freq or ""])
                fh.flush()
                LOG.info("AZ %3d -> relative SNR %6.2f dB (%d samples)", az, snr, samples)
        best = max(rows, key=lambda v: v.median_db)
        if best.median_db < min_db:
            raise RuntimeError(f"No trustworthy peak: best {best.median_db:.1f} dB < {min_db:.1f} dB")
        if any(row.frequency_hz is not None and row.frequency_hz != best.frequency_hz for row in rows):
            raise RuntimeError("SDR frequency changed during sweep; samples incomparable")
        LOG.info("Best AZ=%d, relative SNR=%.2f dB", best.az, best.median_db)
        await rotor.move_to(best.az, timeout=timeout)
        completed = True
        return best, rows
    finally:
        if not completed:
            # Abort may be BLE loss; attempt STOP and never issue further motion.
            await rotor.stop()
        await source.close()
        await rotor.close()


def build_parser():
    p = argparse.ArgumentParser(description="F09/F10 BLE azimuth sweep by SDR signal metric")
    p.add_argument("--source", choices=["sdrpp-iq", "sdrsharp-udp", "demo"], required=True)
    p.add_argument("--pin", help="ROTOR BLE PIN (6 digits); prompt if omitted")
    p.add_argument("--start", type=int, default=0)
    p.add_argument("--stop", type=int, default=350)
    p.add_argument("--step", type=int, default=10)
    p.add_argument("--settle", type=float, default=1.0)
    p.add_argument("--dwell", type=float, default=2.0)
    p.add_argument("--move-timeout", type=float, default=45.0)
    p.add_argument("--min-snr", type=float, default=1.0)
    p.add_argument("--host", default="127.0.0.1")
    p.add_argument("--port", type=int, help="IQ TCP port (default 1234), or SDR# UDP port (default 47291)")
    p.add_argument("--sample-rate", type=int, default=96000)
    p.add_argument("--channel-hz", type=int, default=12500)
    p.add_argument("--csv", default="sdr_scan_results.csv")
    return p


async def run(args):
    positions = angles(args.start, args.stop, args.step)
    if args.source == "demo":
        rotor = DemoRotor()
        source = DemoMetric(rotor)
        LOG.warning("DEMO SIMULATION — NO RADIO/ROTOR HARDWARE")
    else:
        pin = args.pin
        if pin is None:
            from getpass import getpass
            pin = getpass("ROTATOR-BLE PIN (6 digits): ")
        rotor = RotorBLE(pin)
        if args.source == "sdrpp-iq":
            source = IQTcpSource(args.host, args.port or 1234, args.sample_rate, args.channel_hz)
        else:
            source = SDRSharpUDPSource(args.port or 47291)
    best, _ = await perform_scan(
        rotor, source, positions, settle=args.settle, dwell=args.dwell,
        timeout=args.move_timeout, output=Path(args.csv), min_db=args.min_snr
    )
    print(f"BEST AZ={best.az:03d}, relative SNR={best.median_db:.2f} dB; saved {args.csv}")


def main():
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    args = build_parser().parse_args()
    try:
        asyncio.run(run(args))
    except (Exception, KeyboardInterrupt) as exc:
        LOG.error("Sweep aborted safely: %s", exc)
        sys.exit(1)


if __name__ == "__main__":
    main()
