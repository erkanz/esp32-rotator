# SDR# ve SDR++ için iki ayrı plugin DLL

**Windows kontrol yazılımı hâlâ tek EXE:** `RotatorControl.exe`.
İki SDR uygulaması farklı modül ABI'si kullandığı için SDR tarafında iki **ayrı DLL**
üretilir. **Bu DLL'ler motoru yönetmez**; yerel bilgisayarda UDP
`127.0.0.1:47291` adresine SNR ölçümü yollar.

## SDR# (.NET 9)

- Kaynak: `sdr_scan/SDRSharpSnrBridge.cs`
- Build: `plugins/sdrsharp/RotatorSNR.csproj` (resmî Airspy SDK)
- GitHub Actions: **SDRSharp SNR Plugin DLL**
- Artifact: `SDRSharp-RotatorSNR-Plugin-DLL`
- Çıktı: `Zenlabworks.RotatorSNR.SDRSharp.dll`

SDR# x64/.NET 9 sürümünde kapalı SDR# ile DLL'yi SDR#'ın `Plugins`
klasörüne koy. Sürümün plugin keşif mekanizmasını/ayarlarını kontrol et;
farklı SDK sürümlerinde plugin yükleme davranışı değişebilir.

Bu plugin `ISharpPlugin` ve `VisualSNR` okumasını kullanır; SDR# API'si
VisualSNR sağlamıyorsa veri üretmez, uydurma SNR göstermez.

## SDR++ (native C++)

- Kaynak: `plugins/sdrpp/main.cpp`
- Build: `plugins/sdrpp/CMakeLists.txt` (upstream SDR++ core SDK)
- GitHub Actions: **SDRPlusPlus Rotator SNR Plugin DLL**
- Artifact: `SDRPlusPlus-RotatorSNR-Plugin-DLL`
- Çıktı: `zenlab_rotator_snr.dll`

SDR++ kapalıyken DLL'yi SDR++ modüller klasörüne yerleştir, Module Manager
altında `zenlab_rotator_snr` için instance oluştur ve etkinleştir.
SDR++ derleme/ABI sürümü uyumlu olmalıdır. SDR++'ın spektrum FFT'sinden
**merkez bant sinyali ile yan bant gürültüsü farkını** hesaplar.
Ölçüm görece spektral kontrasttır; RF cihazı tarafından kalibre edilmiş
mutlak SNR değildir. Ölçülecek dar band sinyali SDR++ waterfall merkezine
getir. Sinyal tarama boyunca aynı frekansta ve kesintisiz olmalıdır.

## RotatorControl.exe

`SDR# / SNR Scan` sekmesinde SDR# için **SDR# (VisualSNR UDP)** veya
SDR++ native eklentisi için **SDR++ (SNR Plugin UDP)** seç, port `47291`,
**Connect SDR** tıkla. **SDR ACTIVE** ve taze SNR/frekans gelmeden
otomatik anten taramasını başlatma. Her iki plugin aynı UDP formatını
kullanır: `snr_db`, `frequency_hz`, `playing`.

Aynı portu iki SDR uygulamasında aynı anda aktif bırakma; taramaya
başlamadan diğer programın plugin'ini kapat.

### Doğrulama sınırları

GitHub build başarısı yalnızca belirtilen SDK/derleyiciye karşı DLL
oluşturulduğunu kanıtlar. Gerçek SDR# ve SDR++ üzerinde modülün yüklendiği,
SDR verisi gönderdiği ve anten tepe taramasını tamamladığı ayrı test
gerektirir. Windows EXE/F11 firmware değişmedi.
