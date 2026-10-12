# ESP32 Antenna Rotator — BLE Clients

Android APK and Windows EXE clients for the **R5.12 F11** ESP32 ROTATOR / REMOTE BLE control protocol.

The Android and Windows clients both discover either `ROTATOR-BLE` or `ROTATOR-REMOTE-BLE` and share the same GATT command UUIDs.

**Build outputs:** [Actions](https://github.com/erkanz/esp32-rotator/actions) → choose a successful **Android APK** or **Windows EXE** run → **Artifacts**.

Source directories: [android_app](android_app), [windows_app](windows_app). The BLE-controlled firmware must be installed separately on both ESP32 devices; these workflows build client applications only.

See [F11 execution order](F11_EXECUTION_ORDER_TR.md) and [BLE control protocol](BLE_CONTROL_TR.md). Release status is not complete until physical pairing and control tests pass.
