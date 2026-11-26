#include "terminal.hpp"

#include <algorithm>
#include <numeric>

bool Terminal::apply(std::span<const uint8_t> frame)
{
    if (frame.size() < 4 || (frame[0] != 0x84 && frame[0] != 0x85) ||
        frame[1] != frame.size() - 3 || frame[2] != 1 ||
        (std::accumulate(frame.begin(), frame.end(), 0u) & 255)) {
        return false;
    }
    Terminal staged = *this;
    if (frame[0] == 0x85) {
        if (!downloadEnabled_ || !staged.download(frame)) {
            return false;
        }
        *this = std::move(staged);
        return true;
    }
    auto parameters = frame.subspan(3, frame.size() - 4);
    while (!parameters.empty()) {
        if (parameters.size() < 2 || parameters[1] > parameters.size() - 2 ||
            !staged.parameter(parameters[0], parameters.subspan(2, parameters[1]))) {
            return false;
        }
        parameters = parameters.subspan(2 + parameters[1]);
    }
    *this = std::move(staged);
    return true;
}

bool Terminal::download(std::span<const uint8_t> frame)
{
    if (frame.size() < 6 || frame[4] != frame.size() - 6) {
        return false;
    }
    if (std::equal(frame.begin(), frame.end(), previousDownload_.begin(), previousDownload_.end())) {
        return true;
    }
    const auto payload = frame.subspan(5, frame.size() - 6);
    if (frame[3] == 0x83) {
        const auto serviceEnd = std::find(payload.begin(), payload.end(), 0xff);
        if (!dataMode_ || serviceEnd == payload.end() || serviceEnd - payload.begin() > 18 ||
            payload.end() - serviceEnd != 10 || std::string(serviceEnd + 1, serviceEnd + 5) != "CL01" ||
            !payload.back()) {
            return false;
        }
        pendingVersion_ = payload.back();
        pendingDisplay_.clear();
        pendingLaunch_ = false;
        phase_ = 1;
    } else if (frame[3] == 0x80 && phase_ == 1) {
        constexpr std::array<uint8_t, 14> displayKey = {2,'I','n','f','o',255,'I','n','f','o',255,0x98,0xc1,8};
        constexpr std::array<uint8_t, 17> launchKey = {2,'I','n','f','o',255,'I','n','f','o',255,0x82,0x84,'6','5','0','1'};
        if (std::equal(payload.begin(), payload.end(), launchKey.begin(), launchKey.end())) {
            pendingLaunch_ = true;
        } else if (!std::equal(payload.begin(), payload.end(), displayKey.begin(), displayKey.end())) {
            return false;
        }
        phase_ = 2;
    } else if (frame[3] == 0x81 && phase_ == 2 && payload.size() >= 5 && payload.size() <= 24 &&
               payload[0] == 0x81 && payload[2] == 0xff && payload.back() == 0xff &&
               std::all_of(payload.begin() + 3, payload.end() - 1, [](auto byte) { return byte >= 32 && byte <= 126; })) {
        pendingDisplay_ = std::string(payload.begin() + 3, payload.end() - 1);
        phase_ = 3;
    } else if (frame[3] == 0x82 && phase_ == 3) {
        constexpr std::array<uint8_t, 13> script = {0, 1, 6, 2, 255, 3, 193, 8, 255, 2, 1, 2, 255};
        if (!std::equal(payload.begin(), payload.end(), script.begin(), script.end())) {
            return false;
        }
        phase_ = 4;
    } else if (frame[3] == 0x84 && phase_ == 4 && payload.empty()) {
        resident_ = std::move(pendingDisplay_);
        residentVersion_ = pendingVersion_;
        residentLaunch_ = pendingLaunch_;
        phase_ = 0;
    } else {
        return false;
    }
    previousDownload_.assign(frame.begin(), frame.end());
    return true;
}

std::string Terminal::line() const
{
    auto found = lines_.find(selectedLine_);
    return found == lines_.end() ? "" : found->second;
}

std::array<std::string, 4> Terminal::viewport() const
{
    std::array<std::string, 4> rows;
    for (unsigned index = 0; index < rows.size(); ++index) {
        const auto found = lines_.find(selectedLine_ + index);
        if (found != lines_.end()) {
            rows[index] = found->second;
        }
    }
    return rows;
}

Softkey Terminal::key(unsigned slot) const
{
    if (slot >= keyMap_.size()) {
        return {};
    }
    auto found = keys_.find(keyMap_[slot] & 0x3f);
    return found == keys_.end() ? Softkey{} : found->second;
}

bool Terminal::parameter(uint8_t tag, std::span<const uint8_t> payload)
{
    switch (tag) {
    case 0x80: {
        if (payload.size() < 5) {
            return false;
        }
        auto label = std::find(payload.begin() + 1, payload.end(), 0xff);
        if (label == payload.end()) {
            return false;
        }
        auto action = std::find(label + 1, payload.end(), 0xff);
        if (action == payload.end() || payload.end() - action != 2 ||
            ((action[1] < '0' || action[1] > '9') && action[1] != '*' && action[1] != '#')) {
            return false;
        }
        keys_[payload.front()] = {std::string(payload.begin() + 1, label), static_cast<char>(action[1])};
        return true;
    }
    case 0x81:
        if (payload.size() != keyMap_.size()) {
            return false;
        }
        std::copy(payload.begin(), payload.end(), keyMap_.begin());
        return true;
    case 0x82: {
        if (payload.size() < 4 || payload[2] != 0xff) {
            return false;
        }
        auto separator = std::find(payload.begin() + 3, payload.end(), 0xff);
        if (separator == payload.end()) {
            return false;
        }
        lines_[payload[0] & 0x3f] = std::string(payload.begin() + 3, separator);
        return true;
    }
    case 0x83:
        if (payload.size() != 1) {
            return false;
        }
        selectedLine_ = payload[0] & 0x3f;
        return true;
    case 0x84:
        if (payload.size() != informationFlags_.size()) {
            return false;
        }
        std::copy(payload.begin(), payload.end(), informationFlags_.begin());
        return true;
    case 0x85:
        sessionOpen_ = false;
        phase_ = 0;
        pendingDisplay_.clear();
        previousDownload_.clear();
        keys_.clear();
        keyMap_.fill(0);
        return payload.empty();
    case 0x86:
        dataMode_ = true;
        return payload.empty();
    case 0x87:
        dataMode_ = false;
        released_ = !sessionOpen_;
        return payload.size() == 1;
    case 0x88:
        keys_.clear();
        keyMap_.fill(0);
        return payload.empty();
    case 0x8e:
        sessionOpen_ = true;
        released_ = false;
        return payload.empty();
    case 0x94:
        lines_.clear();
        return payload.empty();
    default:
        return false;
    }
}
