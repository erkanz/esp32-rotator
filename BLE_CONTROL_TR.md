# R5.12 BLE GATT

Service `df8268c0-4cc2-4eaa-85dd-3a6159fe0001`
Command WRITE `df8268c0-4cc2-4eaa-85dd-3a6159fe0002`
Status READ `df8268c0-4cc2-4eaa-85dd-3a6159fe0003`
Reply READ `df8268c0-4cc2-4eaa-85dd-3a6159fe0004`

Commands: AZ 0..359, STOP, HOME, JOG -1/0/1, CURRENT 500..1800, SPEED 200..6000, ACCEL 300..4000, CLEAR. Use secured BLE bonding; command write only after pairing. Jog commands repeated while held; ESP32 watchdog must stop after ~550 ms without renewal.

BLE initially disabled; enable via physical device settings.
