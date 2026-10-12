# F11 Faz Takibi — GitHub Actions (12 Ekim 2026)

| Faz | Çıktı | Doğrulama |
|---|---|---|
| F11A | İki ESP32 firmware build ve BLE yayın testi | VPS/gerçek donanımda bekliyor |
| F11B | Android APK istemcisi | **GitHub Actions başarılı; APK artifact üretildi** |
| F11C | Windows EXE istemcisi | **GitHub Actions başarılı; EXE artifact üretildi** |
| F11D | Android/Windows → ROTOR/REMOTE dört BLE bağlantısı ve motor komutları | Saha testi bekliyor |
| F11E | İstemciler/ESP32 arasında ayar ve özellik eşdeğerliği | Tamamlanmadı |
| F11F | Kopma koruması, eşleştirme, motor güvenliği ve son kabul | Bekliyor |

## Doğrulanmış Actions çıktıları

- Android: https://github.com/erkanz/esp32-rotator/actions/runs/38307787498 — `RotatorBLE-Android-APK` (GitHub artifact ID 11773411188).
- Windows: https://github.com/erkanz/esp32-rotator/actions/runs/38307613796 — `RotatorBLE-Windows-EXE` (GitHub artifact ID 11773690363).

**Dikkat:** Başarılı istemci derlemesi BLE/GATT saha testi yapıldığı anlamına gelmez. İki cihazın firmware derleme, eşleştirme ve bağlantı kopma testleri ayrıca yapılacaktır.

## GitHub Actions verimliliği

Android ve Windows ayrı dosya yolu filtreleriyle çalışır. Yalnızca kendi istemcisinin kaynak veya workflow dosyaları değiştiğinde ilgili job tetiklenir. Elle başlatma (`workflow_dispatch`) mümkündür. Her platformda bir job, dependency cache, concurrency cancellation ve 14 gün artifact saklama uygulanır. Firmware derlemeleri istemci değişikliklerinden etkilenmez.
