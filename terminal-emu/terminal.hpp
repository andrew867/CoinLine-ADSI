#pragma once

#include <array>
#include <cstdint>
#include <span>
#include <string>
#include <unordered_map>
#include <vector>

struct Softkey {
    std::string label;
    char digit = 0;
};

class Terminal {
public:
    explicit Terminal(bool download = false) : downloadEnabled_(download) {}
    bool apply(std::span<const uint8_t> frame);
    std::string line() const;
    std::array<std::string, 4> viewport() const;
    Softkey key(unsigned slot) const;
    bool inDataMode() const { return dataMode_; }
    bool released() const { return released_; }
    const std::string &resident() const { return resident_; }
    unsigned residentVersion() const { return residentVersion_; }
    bool residentLaunch() const { return residentLaunch_; }

private:
    bool parameter(uint8_t tag, std::span<const uint8_t> payload);
    bool download(std::span<const uint8_t> frame);

    bool downloadEnabled_;
    bool dataMode_ = false;
    bool released_ = false;
    unsigned selectedLine_ = 1;
    std::unordered_map<unsigned, std::string> lines_;
    std::unordered_map<unsigned, Softkey> keys_;
    std::array<uint8_t, 6> keyMap_{};
    std::vector<uint8_t> previousDownload_;
    unsigned phase_ = 0;
    unsigned pendingVersion_ = 0;
    unsigned residentVersion_ = 0;
    bool pendingLaunch_ = false;
    bool residentLaunch_ = false;
    std::string pendingDisplay_;
    std::string resident_;
};
