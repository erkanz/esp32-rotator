# F09/F10 — Windows arayüzünde SDR# / SDR++ SNR taraması

Artık iki ayrı Windows uygulaması yok. **RotatorControl.exe** içinde üç sekme var:
**Control**, **Logs** ve **SDR# / SNR Scan**. Terminal kullanılması gerekmiyor.

## Programı açma

1. [GitHub Actions](https://github.com/erkanz/esp32-rotator/actions)
   → **Rotator Control Unified Windows EXE** → son başarılı derleme
   → **RotatorControl-Windows-EXE** artefact dosyasını indir.
2. Tek `RotatorControl.exe` dosyasını çalıştır.
3. **Control** sekmesinden **ROTATOR-BLE** (REMOTE değil) seçerek PIN ve
   authenticated BLE bağlantısını kur.

## SDR# bağlantısı

1. SDR# alıcını aç, sabit frekansa getir ve dinlemeyi başlat.
2. SDR# içinde `SDRSharpSnrBridge.cs` kaynak kodundan, **kullandığın SDR# sürümüyle
   uyumlu SDRSharp plugin SDK'sına karşı derlenmiş** VisualSNR eklentisini
   etkinleştir. Eklenti kendi DLL dosyasıdır; ikinci Windows kontrol EXE'si
   değildir. Evrensel hazır DLL henüz yayımlanmadı.
3. `SDR# / SNR Scan` → Source `SDR# (VisualSNR UDP)` → port `47291`
   → **Connect SDR**.
4. `Waiting for live SDR# VisualSNR frames` yalnızca portun dinlendiği
   anlamına gelir. **SDR ACTIVE** ve ölçülen dB/frekans görünmeden
   tarama başlatılamaz.
5. Başlangıç/bitiş açısı, adım, ölçüm süresi ve CSV dosyasını seç →
   **START SNR SCAN**. İstediğinde **STOP SCAN / STOP MOTOR**.

**Önemli:** SDR# içine doğru SDK eklentisi kurulmadıysa bu program kendi
başına SDR#'ın içindeki VisualSNR değerini okuyamaz; "Connect SDR" sadece yerel
UDP dinleyicisini açar. Bilinmeyen SDR# sürümü için çalışan plugin DLL'si
üretilmiş gibi davranmıyoruz.

## SDR++ bağlantısı

1. SDR++ → Module Manager → IQ Exporter → VFO, Float32, TCP Server,
   localhost `127.0.0.1:1234`, 96000 Hz → akışı başlat.
2. Birleşik uygulamada Source `SDR++ (IQ TCP)`, port `1234`,
   IQ rate `96000`, channel BW `12500` → **Connect SDR**.
3. Canlı relatif SNR dB görünmesini bekle; taramayı arayüzden yönet.

## Güvenlik / sınırlamalar

- BLE fiziksel ROTOR'a doğrudan bağlanmış ve MITM doğrulanmış olmalı.
- Aynı BLE oturumu kullanılır, ikinci eşleştirme veya bağlantı açılmaz.
- Arıza, bağlantı kaybı, süre aşımı ve stale SDR ölçümünde tarama kesilir
  ve STOP gönderilmeye çalışılır; ESP32'nin kendi limitleri geçerlidir.
- Tarama sırasında manuel GO/HOME/JOG engellenir; STOP serbest.
- SDR++ FFT ölçümü göreli spektral kontrasttır, mutlak RF ölçümü değildir.
  SDR# VisualSNR ve SDR++ sonuçları aynı ölçeğe sahip olmayabilir.
- Sinyal kesintiliyse otomatik tepe arama yanıltıcıdır. SDR frekans,
  AGC, gain ve filter ayarlarını tarama sırasında değiştirme.
- Bu sürümün donanımsız testleri gerçek SDR# DLL uyumluluğunun
  ve gerçek motor/SDR taramasının yerine geçmez.

Önceki `rotator_scan.py` CLI geliştirme/test aracı olarak kaynakta durabilir,
ancak artık ayrı bir Windows EXE üretmiyoruz.
