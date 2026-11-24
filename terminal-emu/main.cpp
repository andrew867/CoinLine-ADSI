#include <pjsua2.hpp>
#include <spandsp.h>
#include <nlohmann/json.hpp>

#include <algorithm>
#include <chrono>
#include <cmath>
#include <cstdlib>
#include <deque>
#include <filesystem>
#include <fstream>
#include <iomanip>
#include <iostream>
#include <mutex>
#include <numbers>
#include <sstream>
#include <string>
#include <vector>
#include <poll.h>
#include <unistd.h>

#include "terminal.hpp"

namespace {
constexpr int rate = 8000;
constexpr double tau = 2 * std::numbers::pi;
using Json = nlohmann::json;
using Clock = std::chrono::steady_clock;

double tonePower(std::span<const int16_t> samples, int frequency)
{
    const double factor = 2 * std::cos(tau * frequency / rate);
    double previous = 0;
    double previous2 = 0;
    for (const int value : samples) {
        const double term = value + factor * previous - previous2;
        previous2 = previous;
        previous = term;
    }
    return previous * previous + previous2 * previous2 - factor * previous * previous2;
}

class AudioPort : public pj::AudioMediaPort {
public:
    explicit AudioPort(std::string scenario, bool attached = true) : scenario_(std::move(scenario)),
                                                                  terminal_(scenario_ == "fdm")
    {
        serial_ = async_rx_init(nullptr, 8, ASYNC_PARITY_NONE, 1, false, &receivedByte, this);
        modem_ = fsk_rx_init(nullptr, &preset_fsk_specs[FSK_BELL202], FSK_FRAME_MODE_ASYNC, &receivedBit, this);
        if (attached) {
            pj::MediaFormatAudio format;
            format.init(PJMEDIA_FORMAT_PCM, rate, 1, 20000, 16);
            createPort("CoinLine terminal", format);
        }
    }

    ~AudioPort() override
    {
        fsk_rx_free(modem_);
        async_rx_free(serial_);
    }

    void onFrameReceived(pj::MediaFrame &frame) override
    {
        std::lock_guard lock(mutex_);
        for (size_t index = 0; index + 1 < frame.buf.size(); index += 2) {
            window_.push_back(static_cast<int16_t>(frame.buf[index] | frame.buf[index+1] << 8));
            if (window_.size() == 160) {
                receiveWindow();
                window_.clear();
            }
        }
    }

    void onFrameRequested(pj::MediaFrame &frame) override
    {
        std::lock_guard lock(mutex_);
        frame.type = PJMEDIA_FRAME_TYPE_AUDIO;
        frame.buf.resize(frame.size);
        for (size_t index = 0; index + 1 < frame.size && !output_.empty(); index += 2) {
            const auto value = static_cast<uint16_t>(output_.front());
            output_.pop_front();
            frame.buf[index] = value & 255;
            frame.buf[index + 1] = value >> 8;
        }
    }

    Json report()
    {
        std::lock_guard lock(mutex_);
        const bool displayExchange = alert_ && lab_ && terminal_.released();
        bool exchange = displayExchange && (scenario_ == "pcm" || (voiceHeard_ &&
            (scenario_ == "reference" || (keySent_ && ok_))));
        if (scenario_ == "fallback") {
            exchange = voiceHeard_ && fallbackReply_;
        } else if (scenario_ == "fdm") {
            exchange = terminal_.residentVersion() && terminal_.released();
        } else if (scenario_ == "interactive") {
            exchange = true;
        }
        return {{"scenario", scenario_}, {"passed", exchange}, {"events", events_},
                {"resident", terminal_.resident()}, {"resident_version", terminal_.residentVersion()}};
    }

    void press(const std::string &input)
    {
        std::lock_guard lock(mutex_);
        if (input.size() == 1 && std::string("0123456789*#ABCD").find(input[0]) != std::string::npos) {
            digit(input[0], false);
        } else if (input.size() == 2 && input[0] == 'k' && input[1] >= '1' && input[1] <= '6') {
            const auto selected = terminal_.key(input[1] - '1');
            if (selected.digit) {
                digit(selected.digit, false);
            }
        }
    }

private:
    void record(Json event)
    {
        event["sample"] = samples_;
        if (scenario_ == "interactive") {
            std::cout << event.dump() << std::endl;
        }
        if (events_.size() < 128) {
            events_.push_back(std::move(event));
        }
    }

    void silence(unsigned milliseconds)
    {
        output_.insert(output_.end(), milliseconds * (rate / 1000), 0);
    }

    void digit(char symbol, bool trace = true)
    {
        const std::string digits = "123A456B789C*0#D";
        const auto slot = digits.find(symbol);
        const int rows[] = {697, 770, 852, 941};
        const int columns[] = {1209, 1336, 1477, 1633};
        if (slot == std::string::npos) {
            return;
        }
        const int duration = trace ? 70 : 110;
        for (int sample = 0; sample < duration * (rate / 1000); ++sample) {
            output_.push_back(static_cast<int16_t>(4800 * (
                std::sin(tau * rows[slot / 4] * sample / rate) +
                std::sin(tau * columns[slot % 4] * sample / rate))));
        }
        silence(trace ? 65 : 100);
        if (trace) {
            record({{"digit", std::string(1, symbol)}});
        }
    }

    void receiveWindow()
    {
        samples_ += window_.size();
        double energy = 0;
        for (const double sample : window_) {
            energy += sample * sample;
        }
        const bool pastRelease = releaseSample_ && samples_ >= releaseSample_ + rate * 4 / 10;
        const bool fallbackAudio = scenario_ == "fallback" && samples_ > rate * 14 / 10;
        if ((fallbackAudio || pastRelease) && energy > 160 * 200.0 * 200.0) {
            if (!voiceHeard_) {
                record({{"signal", "voice"}});
                if (scenario_ == "fallback") {
                    silence(1600);
                    digit('1');
                    waitForReply_ = samples_ + rate * 19 / 10;
                }
            } else if (waitForReply_ && samples_ > waitForReply_ && !fallbackReply_) {
                record({{"signal", "voice-response"}});
                fallbackReply_ = true;
            }
            voiceHeard_ = true;
        }
        const double threshold = energy * window_.size() * 0.12;
        auto cas = energy > 160 * 300.0 * 300.0 &&
            tonePower(window_, 2130) > threshold && tonePower(window_, 2750) > threshold;
        casWindows_ = cas ? casWindows_ + 1 : 0;
        if (casWindows_ == 3 && !alert_) {
            alert_ = true;
            record({{"signal", "CAS"}});
            if (scenario_ != "fallback") {
                silence(80);
                digit('A');
            }
        }
        if (alert_ && scenario_ != "fallback") {
            fsk_rx(modem_, window_.data(), static_cast<int>(window_.size()));
        }
    }

    static void receivedBit(void *user, int bit)
    {
        auto &port = *static_cast<AudioPort *>(user);
        async_rx_put_bit(port.serial_, bit);
    }

    static void receivedByte(void *user, int value)
    {
        auto &port = *static_cast<AudioPort *>(user);
        port.processByte(value);
    }

    void processByte(int value)
    {
        if (value < 0) {
            bytes_.clear();
            return;
        }
        if (bytes_.empty() && value != 0x84 && value != 0x85) {
            return;
        }
        bytes_.push_back(static_cast<uint8_t>(value));
        if (bytes_.size() < 2 || bytes_.size() != static_cast<size_t>(bytes_[1]) + 3) {
            return;
        }
        const bool download = bytes_[0] == 0x85;
        const uint8_t tag = bytes_.size() > 4 ? bytes_[3] : 0;
        Terminal staged = terminal_;
        bool valid = staged.apply(bytes_);
        if (valid && download && tag == 0x84) {
            valid = saveResident(staged);
        }
        if (valid) {
            terminal_ = std::move(staged);
        }
        std::ostringstream hex;
        for (const auto byte : bytes_) {
            hex << std::hex << std::setfill('0') << std::setw(2) << static_cast<int>(byte);
        }
        bytes_.clear();
        silence(150);
        digit('D');
        digit(valid ? '1' : '0');
        if (valid && download && tag == 0x83) {
            digit('B');
        }
        std::array<std::string, 6> labels;
        for (unsigned index = 0; index < labels.size(); ++index) {
            labels[index] = terminal_.key(index).label;
        }
        record({{"frame", hex.str()}, {"valid", valid}, {"line", terminal_.line()},
                {"lines", terminal_.viewport()}, {"softkeys", labels},
                {"mode", terminal_.inDataMode() ? "data" : "voice"}});
        if (valid) {
            if (terminal_.released() && !releaseSample_) {
                releaseSample_ = samples_;
            }
            const auto key = terminal_.key(0);
            lab_ |= terminal_.line() == "LAB";
            ok_ |= terminal_.line() == "OK";
            if (scenario_ == "lab" && !keySent_ && key.label == "Go" && key.digit == '1') {
                silence(230);
                digit(key.digit);
                keySent_ = true;
            }
        }
    }

    static bool saveResident(const Terminal &terminal)
    {
        const char *path = std::getenv("ADSI_FDM_STATE_FILE");
        if (!path) {
            return false;
        }
        const auto temporary = std::string(path) + ".pending";
        std::ofstream stream(temporary, std::ios::trunc);
        stream << Json{{"version", terminal.residentVersion()}, {"idle_display", terminal.resident()}}.dump() << '\n';
        stream.close();
        if (!stream) {
            return false;
        }
        std::error_code error;
        std::filesystem::rename(temporary, path, error);
        return !error;
    }

    std::mutex mutex_;
    const std::string scenario_;
    Terminal terminal_;
    async_rx_state_t *serial_;
    fsk_rx_state_t *modem_;
    std::vector<int16_t> window_;
    std::vector<uint8_t> bytes_;
    std::deque<int16_t> output_;
    Json events_ = Json::array();
    unsigned samples_ = 0;
    unsigned casWindows_ = 0;
    unsigned releaseSample_ = 0;
    unsigned waitForReply_ = 0;
    bool alert_ = false;
    bool lab_ = false;
    bool ok_ = false;
    bool keySent_ = false;
    bool voiceHeard_ = false;
    bool fallbackReply_ = false;
};

class Call : public pj::Call {
public:
    Call(pj::Account &account, AudioPort &port) : pj::Call(account), port_(port) {}

    void onCallState(pj::OnCallStateParam &) override
    {
        lastStatus = getInfo().lastStatusCode;
    }

    void onCallMediaState(pj::OnCallMediaStateParam &) override
    {
        const auto info = getInfo();
        for (const auto &stream : info.media) {
            if (stream.type == PJMEDIA_TYPE_AUDIO && stream.status == PJSUA_CALL_MEDIA_ACTIVE && !connected) {
                auto media = getAudioMedia(stream.index);
                media.startTransmit(port_);
                port_.startTransmit(media);
                connected = true;
            }
        }
    }

    int lastStatus = 0;

private:
    AudioPort &port_;
    bool connected = false;
};

Json runCall(pj::Endpoint &endpoint, pj::Account &account, const std::string &scenario, const std::string &uri)
{
    AudioPort port(scenario);
    Call call(account, port);
    pj::CallOpParam operation(true);
    operation.opt.videoCount = 0;
    call.makeCall(uri, operation);
    const auto limit = Clock::now() + std::chrono::seconds(scenario == "interactive" ? 900 : 16);
    std::string pendingInput;
    bool inputOpen = scenario == "interactive";
    while (call.isActive() && Clock::now() < limit) {
        endpoint.libHandleEvents(20);
        pollfd input {STDIN_FILENO, POLLIN, 0};
        if (!inputOpen || poll(&input, 1, 0) <= 0 || !(input.revents & (POLLIN | POLLHUP))) {
            continue;
        }
        char chunk[128];
        const auto length = read(input.fd, chunk, sizeof(chunk));
        inputOpen = length > 0;
        if (!inputOpen) {
            continue;
        }
        pendingInput.append(chunk, length);
        for (auto end = pendingInput.find('\n'); end != std::string::npos; end = pendingInput.find('\n')) {
            auto text = pendingInput.substr(0, end);
            pendingInput.erase(0, end + 1);
            if (!text.empty() && text.back() == '\r') {
                text.pop_back();
            }
            if (text == "hangup" && call.isActive()) {
                call.hangup(pj::CallOpParam());
                break;
            }
            port.press(text);
        }
        if (pendingInput.size() > sizeof(chunk)) {
            pendingInput.clear();
        }
    }
    const bool ended = !call.isActive();
    Json result = port.report();
    result["ended"] = ended;
    result["sip_status"] = call.lastStatus;
    result["passed"] = ended && call.lastStatus == 200 && result["passed"].get<bool>();
    if (!ended) {
        call.hangup(pj::CallOpParam());
        const auto teardown = Clock::now() + std::chrono::seconds(1);
        while (call.isActive() && Clock::now() < teardown) {
            endpoint.libHandleEvents(20);
        }
    }
    return result;
}
}

int main(int argc, char **argv)
{
    if (argc == 2 && (std::string(argv[1]) == "pcm" || std::string(argv[1]) == "pcm-fdm")) {
        pj::Endpoint endpoint;
        endpoint.libCreate();
        pj::EpConfig options;
        options.logConfig.level = 0;
        options.logConfig.consoleLevel = 0;
        endpoint.libInit(options);
        Json result;
        {
            AudioPort port(std::string(argv[1]) == "pcm" ? "pcm" : "fdm", false);
            std::array<char, 320> buffer;
            while (std::cin.read(buffer.data(), buffer.size()) || std::cin.gcount()) {
                pj::MediaFrame frame;
                frame.buf.assign(buffer.data(), buffer.data() + std::cin.gcount());
                port.onFrameReceived(frame);
            }
            result = port.report();
        }
        endpoint.libDestroy();
        std::cout << result.dump() << '\n';
        return result["passed"].get<bool>() ? 0 : 1;
    }
    if (argc == 2 && std::string(argv[1]) == "resident") {
        const char *path = std::getenv("ADSI_FDM_STATE_FILE");
        if (!path) {
            return 2;
        }
        std::ifstream stream(path);
        if (!stream) {
            return 1;
        }
        std::cout << stream.rdbuf();
        return 0;
    }
    const char *password = std::getenv("ADSI_SIP_PASSWORD");
    if ((argc != 3 && argc != 4) || !password) {
        std::cerr << "Usage: terminal-emu HOST lab|reference|fallback|interactive|fdm [EXTENSION] with ADSI_SIP_PASSWORD set\n";
        return 2;
    }
    const std::string host = argv[1];
    const std::string scenario = argv[2];
    if (scenario != "lab" && scenario != "reference" && scenario != "fallback" &&
        scenario != "interactive" && scenario != "fdm") {
        return 2;
    }
    const std::string extension = argc == 4 ? argv[3] : (scenario == "fdm" ? "6503" : "6500");
    if (extension.empty() || extension.size() > 10 || extension.find_first_not_of("0123456789") != std::string::npos) {
        return 2;
    }
    long repetitions = 1;
    if (const char *count = std::getenv("ADSI_EMULATOR_CALLS")) {
        char *end = nullptr;
        repetitions = std::strtol(count, &end, 10);
        if (scenario != "lab" || *end || repetitions < 1 || repetitions > 100) {
            return 2;
        }
    }
    pj::Endpoint endpoint;
    try {
        endpoint.libCreate();
        pj::EpConfig options;
        options.uaConfig.threadCnt = 0;
        options.logConfig.level = 0;
        options.logConfig.consoleLevel = 0;
        options.medConfig.clockRate = rate;
        options.medConfig.sndClockRate = rate;
        options.medConfig.noVad = true;
        const int playoutDelay = scenario == "lab" ? 160 : 100;
        options.medConfig.jbInit = playoutDelay;
        options.medConfig.jbMinPre = playoutDelay;
        options.medConfig.jbMaxPre = playoutDelay;
        options.medConfig.jbDiscardAlgo = PJMEDIA_JB_DISCARD_NONE;
        endpoint.libInit(options);
        pj::TransportConfig transport;
        transport.port = 0;
        endpoint.transportCreate(PJSIP_TRANSPORT_UDP, transport);
        endpoint.libStart();
        endpoint.audDevManager().setNullDev();
        for (const auto &codec : endpoint.codecEnum2()) {
            endpoint.codecSetPriority(codec.codecId, codec.codecId == "PCMU/8000/1" ? 255 : 0);
        }
        bool passed = true;
        {
            pj::AccountConfig config;
            config.idUri = "sip:lab@" + host;
            config.mediaConfig.transportConfig.port = 0;
            config.sipConfig.authCreds.emplace_back("digest", "*", "lab", 0, password);
            pj::Account account;
            account.create(config);
            for (long index = 0; index < repetitions; ++index) {
                const Json result = runCall(endpoint, account, scenario, "sip:" + extension + "@" + host);
                std::cout << result.dump() << std::endl;
                passed &= result["passed"].get<bool>();
                if (index + 1 < repetitions) {
                    endpoint.libHandleEvents(100);
                }
            }
        }
        endpoint.libDestroy();
        return passed ? 0 : 1;
    } catch (const pj::Error &error) {
        std::cerr << error.reason << '\n';
        return 1;
    }
}
