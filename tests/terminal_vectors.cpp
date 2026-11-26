#include "terminal.hpp"

#include <cassert>
#include <numeric>
#include <vector>

std::vector<uint8_t> packet(uint8_t kind, uint8_t tag, std::vector<uint8_t> payload)
{
    std::vector<uint8_t> result {kind, static_cast<uint8_t>(3 + payload.size()), 1, tag,
                                 static_cast<uint8_t>(payload.size())};
    result.insert(result.end(), payload.begin(), payload.end());
    result.push_back(static_cast<uint8_t>(-std::accumulate(result.begin(), result.end(), 0)));
    return result;
}

int main()
{
    Terminal mixed;
    assert(mixed.apply(packet(0x84, 0x8e, {})));
    assert(mixed.apply(packet(0x84, 0x86, {})));
    assert(mixed.sessionOpen() && mixed.inDataMode());
    assert(mixed.apply(packet(0x84, 0x84, {0xf4, 0})));
    assert((mixed.informationFlags() == std::array<uint8_t, 2>{0xf4, 0}));
    assert(!mixed.apply(packet(0x84, 0x84, {0xf4})));
    assert(mixed.apply(packet(0x84, 0x87, {0})));
    assert(mixed.sessionOpen() && !mixed.inDataMode() && !mixed.released());
    assert(mixed.apply(packet(0x84, 0x85, {})));
    assert(mixed.apply(packet(0x84, 0x87, {0})));
    assert(!mixed.sessionOpen() && mixed.released());

    Terminal controls;
    assert(controls.apply(packet(0x84, 0x80, {19,'E','r','a','s','e',255,'E','r','a','s','e',255,'*'})));
    assert(controls.apply(packet(0x84, 0x80, {20,'S','u','b','m','i','t',255,'S','u','b','m','i','t',255,'#'})));
    assert(controls.apply(packet(0x84, 0x81, {1,1,1,19,20,1})));
    assert(!controls.key(0).digit && controls.key(3).digit == '*' && controls.key(4).digit == '#');

    Terminal terminal(true);
    const std::vector<uint8_t> lab {0x84, 0x0d, 0x01, 0x82, 0x07, 0x01, 0x40, 0xff, 0x4c, 0x41,
                                   0x42, 0xff, 0x83, 0x01, 0x01, 0x52};
    assert(terminal.apply(lab));
    assert(terminal.line() == "LAB");
    auto corrupt = lab;
    corrupt[8] = 'G';
    assert(!terminal.apply(corrupt));
    auto short_frame = lab;
    short_frame.pop_back();
    assert(!terminal.apply(short_frame));
    auto extra = lab;
    extra.push_back(0);
    assert(!terminal.apply(extra));
    auto truncated = lab;
    truncated[13] = 2;
    truncated[15] = 0x51;
    assert(!terminal.apply(truncated));
    auto unknown = lab;
    unknown[12] = 0xfe;
    unknown[15] = 0xd7;
    assert(!terminal.apply(unknown));
    assert(terminal.line() == "LAB");
    assert(terminal.apply(packet(0x84, 0x86, {})));
    std::vector<uint8_t> connect {'L',0xff,'C','L','0','1',0,0,0,0,1};
    const auto key = packet(0x85, 0x80, {2,'I','n','f','o',255,'I','n','f','o',255,152,193,8});
    const auto screen = packet(0x85, 0x81, {0x81,0,255,'T','E','S','T',255});
    const auto script = packet(0x85, 0x82, {0,1,6,2,255,3,193,8,255,2,1,2,255});
    const auto commit = packet(0x85, 0x84, {});
    assert(terminal.apply(packet(0x85, 0x83, connect)));
    assert(!terminal.apply(screen));
    assert(terminal.apply(key));
    assert(terminal.apply(screen));
    assert(terminal.resident().empty());
    assert(terminal.apply(script));
    assert(terminal.apply(commit));
    assert(terminal.apply(commit));
    assert(terminal.resident() == "TEST" && terminal.residentVersion() == 1);
    assert(!terminal.residentLaunch());
    connect.back() = 2;
    assert(terminal.apply(packet(0x85, 0x83, connect)));
    assert(terminal.apply(key));
    assert(terminal.apply(packet(0x85, 0x81, {0x81,0,255,'N','E','W',255})));
    assert(terminal.apply(packet(0x84, 0x85, {})));
    assert(!terminal.apply(commit));
    assert(terminal.resident() == "TEST" && terminal.residentVersion() == 1);
    assert(!terminal.residentLaunch());
    assert(terminal.apply(packet(0x84, 0x86, {})));
    assert(terminal.apply(packet(0x85, 0x83, connect)));
    auto launchKey = packet(0x85, 0x80, {2,'I','n','f','o',255,'I','n','f','o',255,0x82,0x84,'6','5','0','1'});
    auto invalidKey = packet(0x85, 0x80, {2,'I','n','f','o',255,'I','n','f','o',255,0x82,0x84,'6','5','0','2'});
    assert(!terminal.apply(invalidKey));
    assert(terminal.apply(launchKey));
    assert(terminal.apply(screen));
    assert(terminal.apply(script));
    assert(!terminal.residentLaunch());
    assert(terminal.apply(commit));
    assert(terminal.residentLaunch() && terminal.residentVersion() == 2);
}
