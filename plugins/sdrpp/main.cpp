// SDR++ native module: relative spectral SNR for localhost RotatorControl.
// Uses the official SDR++ ModuleManager + WaterFall FFT API, no IQ Exporter.
#ifdef _WIN32
#ifndef WIN32_LEAN_AND_MEAN
#define WIN32_LEAN_AND_MEAN
#endif
#include <winsock2.h>
#include <ws2tcpip.h>
#pragma comment(lib, "ws2_32.lib")
#endif
#include <module.h>
#include <gui/gui.h>
#include <gui/style.h>
#include <algorithm>
#include <atomic>
#include <chrono>
#include <cmath>
#include <cstdio>
#include <string>
#include <thread>
#include <vector>
SDRPP_MOD_INFO{
    "zenlab_rotator_snr",
    "Relative SNR bridge to RotatorControl (localhost UDP 47291)",
    "Zenlabworks",
    0, 1, 0, 1
};

class RotatorSnrBridge : public ModuleManager::Instance {
public:
    explicit RotatorSnrBridge(std::string n) : name(std::move(n)) {
        gui::menu.registerEntry(name, menuHandler, this, nullptr);
#ifdef _WIN32
        WSADATA wsa;
        netReady = WSAStartup(MAKEWORD(2, 2), &wsa) == 0;
        if (netReady) {
            sock = socket(AF_INET, SOCK_DGRAM, IPPROTO_UDP);
            if (sock == INVALID_SOCKET) {
                WSACleanup();
                netReady = false;
            }
        }
#endif
        worker = std::thread([this] { loop(); });
    }
    ~RotatorSnrBridge() override {
        running = false;
        if (worker.joinable()) worker.join();
        gui::menu.removeEntry(name);
#ifdef _WIN32
        if (netReady) {
            closesocket(sock);
            WSACleanup();
        }
#endif
    }
    void postInit() override {}
    void enable() override { enabled = true; }
    void disable() override { enabled = false; }
    bool isEnabled() override { return enabled; }

private:
    static void menuHandler(void* ctx) {
        auto* self = static_cast<RotatorSnrBridge*>(ctx);
        ImGui::TextUnformatted("Rotator SNR Bridge");
        ImGui::TextUnformatted("Sends relative FFT SNR to 127.0.0.1:47291");
        ImGui::TextUnformatted("Center signal in SDR++ waterfall for measurement.");
        ImGui::Text("Latest relative SNR: %.1f dB", self->snr.load());
        ImGui::Text("Packets sent: %u", self->sent.load());
        if (!self->netReady) ImGui::TextUnformatted("Windows UDP socket unavailable");
    }

    void loop() {
#ifdef _WIN32
        sockaddr_in addr{};
        addr.sin_family = AF_INET;
        addr.sin_port = htons(47291);
        addr.sin_addr.s_addr = htonl(INADDR_LOOPBACK);
#endif
        while (running.load()) {
            std::this_thread::sleep_for(std::chrono::milliseconds(200));
            if (!enabled.load() || !netReady) continue;
            // The SDR++ scanner uses this API to read a locked waterfall FFT.
            int n = 0;
            float* data = gui::waterfall.acquireLatestFFT(n);
            if (!data) continue;
            if (n < 128) {
                gui::waterfall.releaseLatestFFT();
                continue;
            }
            // Central passband: max of bins near DC, noise: median of side bins.
            // This is a *relative spectral contrast*, NOT calibrated RF SNR.
            const int center = n / 2;
            const int half = std::max(4, n / 160);
            float signal = -10000.0f;
            std::vector<float> noise;
            noise.reserve(n / 2);
            for (int i = n / 8; i < 7 * n / 8; ++i) {
                const float x = data[i];
                if (!std::isfinite(x)) continue;
                if (std::abs(i - center) <= half) signal = std::max(signal, x);
                else if (std::abs(i - center) > half * 3) noise.push_back(x);
            }
            gui::waterfall.releaseLatestFFT();
            if (signal < -5000 || noise.size() < 24) continue;
            const size_t m = noise.size() / 2;
            std::nth_element(noise.begin(), noise.begin() + m, noise.end());
            const float level = signal - noise[m];
            if (!std::isfinite(level) || level < -60 || level > 120) continue;
            const double hz = gui::waterfall.getCenterFrequency() + gui::waterfall.getViewOffset();
            if (!std::isfinite(hz) || hz < 1000 || hz > 100000000000.0) continue;
            snr = level;
#ifdef _WIN32
            char payload[192];
            const int bytes = std::snprintf(payload, sizeof(payload),
                "{\"snr_db\":%.3f,\"frequency_hz\":%.0f,\"playing\":true}", level, hz);
            if (bytes > 0 && bytes < (int)sizeof(payload)) {
                int rc = sendto(sock, payload, bytes, 0,
                                reinterpret_cast<sockaddr*>(&addr), sizeof(addr));
                if (rc == bytes) ++sent;
            }
#endif
        }
    }
    std::string name;
    std::atomic<bool> running{true}, enabled{true};
    std::atomic<float> snr{0.0f};
    std::atomic<unsigned> sent{0};
    std::thread worker;
    bool netReady = false;
#ifdef _WIN32
    SOCKET sock = INVALID_SOCKET;
#endif
};

MOD_EXPORT void _INIT_() {}
MOD_EXPORT void* _CREATE_INSTANCE_(std::string name) { return new RotatorSnrBridge(std::move(name)); }
MOD_EXPORT void _DELETE_INSTANCE_(void* instance) { delete static_cast<RotatorSnrBridge*>(instance); }
MOD_EXPORT void _END_() {}
