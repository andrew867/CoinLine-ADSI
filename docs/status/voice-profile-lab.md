# Voice-between-screens interoperability milestone

The continuous-data profile remains the default. The alternative profile is opt-in and scoped to the dedicated emulator ingress. It restores voice after each acknowledged interactive screen, retains the SDC session and sends fresh CAS before a subsequent FSK spill. The protocol deadlines and uncertain-acknowledgment gate are unchanged.

## Verification

- All 53 Python unit tests, C++ terminal vectors and source/fixture checks passed.
- The standalone terminal decoded the separate explicit INFORMATION fixture and mixed voice/data PCM fixtures. The INFORMATION parameter was not emitted in the live alternative profile.
- Isolated SIP peer calls passed both continuous-data and voice-between-screens, including keypad selection, softkey action, and final release.

## Terminal firmware in emulator

One complete SIP call using user supplied ADSI compatible terminal firmware passed initial CAS/A, CONNECT, welcome display, physical numeric News selection, News screen, physical numeric Back, returned welcome, and physical Exit softkey. Independent wire decoding confirmed four CAS exchanges, five valid display frames, five genuine uplink D1 replies, and the unsolicited voice-mode B notices. The three application selections were distinct from the acknowledgment digits. The final release closed the session, restored voice, and ended the SIP call without retransmission. The dedicated service was healthy and idle after teardown.

The screenshots showed the welcome and News displays with six visible softkey labels. The firmware produced its own selection tones; no keypad bypass or fabricated acknowledgment was used. This establishes interactive firmware-in-emulator acceptance for the tested profile, not qualification of a physical handset, FXS adapter, or other media profile. Those badges require their respective physical tests.
