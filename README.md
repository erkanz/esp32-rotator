# ESP32 Antenna Rotator — Unified Windows Control

**One Windows graphical program:** `RotatorControl.exe`. It includes the existing
ROTOR/REMOTE BLE controls, SDR# / SDR++ receiver connections, live SNR, automatic
azimuth scans and CSV results. **No Windows terminal is needed** to operate it.

## Windows download

GitHub [Actions](https://github.com/erkanz/esp32-rotator/actions) →
**Rotator Control Unified Windows EXE** → successful run →
Artifacts → **RotatorControl-Windows-EXE** → `RotatorControl.exe`.

The old separately packaged `RotatorBLE.exe` and `RotatorSDRScanner.exe` are
superseded. Their historical Actions artifacts do not indicate that two programs
are needed now.

## Use

1. Open `RotatorControl.exe`, select **Control** → Scan → choose
   **ROTATOR-BLE**, enter its six-digit PIN and Connect.
2. Open **SDR# / SNR Scan** → Source **SDR# (VisualSNR UDP)** → port `47291` →
   **Connect SDR**. This binds a local receive-only UDP socket. It shows
   **SDR ACTIVE** only once real metric packets arrive.
3. SDR# must run with its [VisualSNR bridge plugin](sdr_scan/SDRSharpSnrBridge.cs)
   enabled; the single EXE does **not** inject itself into SDR# or create metrics.
   Plugin compilation/installation depends on the user's SDR# SDK version; see
   [setup instructions](sdr_scan/README_TR.md). There is **no second EXE**.
4. Wait for live SNR, set safe from/to/step and measurement duration, then click
   **START SNR SCAN**. The scan moves the rotor via the **existing authenticated
   BLE session** and returns to the best measured direction. Click
   **STOP SCAN / STOP MOTOR** for emergency release.
5. Or select **SDR++ (IQ TCP)**; configure its IQ Exporter as documented.

Automatic scanning is limited to a directly connected physical ROTATOR, never
a REMOTE relay. No movement if SNR is stale/absent, BLE is unauthenticated,
or the rotor reports a fault. Motor commands and HOME are blocked during a scan,
STOP remains available.

**Status:** Host tests and Windows package build are automated. Actual SDR#
plugin compatibility and end-to-end receiver/rotor tests must be done on
the target Windows setup.

The ESP32 firmware and BLE protocol are unchanged; continue using the
working R5.12.6 ROTOR firmware. [Android client](android_app/) remains separate
as a mobile app.
