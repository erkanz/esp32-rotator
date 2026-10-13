# F09 / F10 — SDR++ ve SDR# anten yönü / SNR taraması

**Durum:** PC kaynak kodu + testler hazır. Gerçek SDR / motor donanımıyla doğrulanmadı.
R5.12.6 ROTOR / REMOTE firmware, hotspot, ESP-NOW, mevcut web ve F11 Windows
arayüzleri değiştirilmedi.

## Sistem

- ROTOR'a doğrudan PIN+MITM doğrulanmış BLE bağlanır. Yalnızca AZ, STATUS, STOP.
- SDR++: yerleşik IQ Exporter'ın Float32/TCP/VFO örneklerine FFT uygulanır.
  Kanal içi / yan bant gücüyle **göreli SNR** hesaplanır; kalibre RF/dBm değildir.
- SDR#: eşlik eden C# kaynak eklentisi VisualSNR'ı localhost UDP olarak aktarır.
- Her açıdan önce motorun durması ve sensör hedefe ulaşması beklenir.
- Metreler motor durduktan sonra alınır; eski/stale veri kullanılmaz.
- BLE bağlantı kesilmesi, fault, hareket timeout, değişen SDR frekansı ve eksik
  sinyal ölçümü güvenli STOP ile taramayı iptal eder.
- CSV sonuçları her adım sonunda yazılır. Tamamlanınca en iyi açıya döner.

## SDR++ — Windows

1. SDR++'da sabit bir frekansa ayarla; mümkünse kesintisiz sinyal seç.
2. Module Manager -> IQ Exporter ekle:
   Mode=VFO, Sample Type=Float32, Protocol=TCP Server,
   VFO sample rate=96000, host=127.0.0.1, port=1234.
   Exporter'ı ve SDR alımını başlat. (Menü isimleri SDR++ sürümüne bağlı.)
3. Windows Python 3.12+ kuruluysa:

   py -m pip install -r windows_app/requirements.txt numpy

4. Donanımsız demo:

   py sdr_scan/rotator_scan.py --source demo --start 90 --stop 170 --step 10 --dwell 0.5

5. Gerçek tarama:

   py sdr_scan/rotator_scan.py --source sdrpp-iq --start 90 --stop 180 --step 10 --settle 1.5 --dwell 3 --sample-rate 96000 --channel-hz 12500 --csv scan_sdrpp.csv

Uygulama ROTOR BLE PIN'ini sorar. Gerçek antenna/montaj için yalnızca
güvenli bir açı aralığı belirle. Tüm çevreyi otomatik taratmaz; HOME yapmaz.
SDR++ VFO sample rate değeri ile komut satırındaki --sample-rate aynı olmalı.
RF gain/AGC/squelch ayarını ve frekansı tarama sırasında değiştirme.

## SDR# (SDRSharp)

Kaynak dosya: SDRSharpSnrBridge.cs. Bu dosya ISharpPlugin ve SDR#'ın
VisualSNR özelliği üzerinden çalışır, UDP 127.0.0.1:47291'e metric yollar.

SDR# plugin SDK dosyasını kendi SDR# sürümüne uygun biçimde edin;
SDRSharp.Common referanslı WinForms Class Library olarak derle, sonra o SDK'nın
plugin yükleme adımlarını uygula. Sürüm uyumluluğu nedeniyle hazır evrensel DLL
mevcut değil. VisualSNR bulunmazsa UDP gönderimi olmaz ve tarama başlamaz.

Gerçek tarama:

   py sdr_scan/rotator_scan.py --source sdrsharp-udp --start 90 --stop 180 --step 10 --settle 1.5 --dwell 3 --csv scan_sdrsharp.csv

## Parametreler

- --start / --stop / --step : 0..359 arasında artan azimutlar, wraparound yok.
- --settle : hedefe ulaşınca ekstra sabitlenme süresi (s).
- --dwell : her açıdaki taze SNR ölçümü (s), varsayılan 2.
- --move-timeout : hedefe ulaşma sınırı (s), varsayılan 45.
- --min-snr : tüm ölçümler bu eşikten düşükse en iyi açıya gitme.
- --csv : her adımda kalıcı kayıt.
- --source demo : sahte rotor/sinyal, gerçek fiziksel motor kullanılmaz.

## Sınırlamalar / kabul

FFT tabanlı ölçüm **göreli spektral kontrast** verir. SDR++ ve SDR# sayıları
aynı kalibrasyonda değildir. Bir tekrarlayıcı yalnızca arada bir yayın yapıyorsa
sessiz periyotlarda otomatik anten tepe araması güvenilir değildir.
Üretim amaçlı tam kabul için Windows, SDR++ IQ Exporter, SDR# SDK eklentisi
ve gerçek ROTOR BLE/motor testi gereklidir.

Mevcut F11 Windows uygulaması ve firmware değişmedi. Bu ilk F09/F10 PC
prototipidir; gerçek SDR üzerinde doğrulanmadan fazları tamamlandı saymayacağız.
