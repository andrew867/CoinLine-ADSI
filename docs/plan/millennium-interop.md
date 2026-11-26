# CoinLine-emu PSTN integration handoff

The server can now accept a direct local SIP call to InfoLine without a registrar. The emulated telephone must experience an ordinary answered analogue call; there is no ADSI-specific application RPC between the simulator and the server. The terminal under test is a Millennium running user supplied ADSI compatible terminal firmware.

## Start the optional service

Run these commands from the CoinLine ADSI repository, using MSYS2 MINGW64 on Windows:

```sh
python deploy/init_lab.py
docker compose -p coinline-adsi-emu -f compose.yaml -f compose.emu.yaml --profile verify build gateway app terminal-emu
docker compose -p coinline-adsi-emu -f compose.yaml -f compose.emu.yaml --profile verify up -d --no-build --wait gateway app
```

The overlay uses a separate Compose project named `coinline-adsi-emu`, its own database volume and image tags, and host-loopback ports. It replaces the standard gateway port publications instead of adding a second public ingress to an authenticated deployment. It requires Compose 2.24.4 or later. Do not combine this overlay with the native voicemail overlay. The original service on UDP 5060 and its database can continue running independently.

| Contract | Value |
| --- | --- |
| Dialled number | `2374` (ADSI) |
| Request URI | `sip:2374@127.0.0.1:5069` |
| SIP transport | UDP, no REGISTER or Digest authentication |
| SIP From user | `co` (for example `From: <sip:co@127.0.0.1>` with a dialog tag) |
| RTP | G.711 PCMU, payload type 0, 8000 samples/s, mono, 160 samples per 20 ms packet |
| Gateway RTP / RTCP range | UDP `18100-18139`, published on host loopback, use the negotiated SDP port |
| App console | `http://127.0.0.1:8089`, generated console access code in the ignored local `.env` |
| First alert | Default 1000 ms after the gateway bridges media; adjustable via `ADSI_EMU_ALERT_DELAY_MS` (250 to 5000) |
| Test caller ID | Configured synthetic ten-digit number via `ADSI_EMU_CALLER_ID`; default `7095550100` |

The `co` endpoint is intentionally named, not a catch-all anonymous SIP module. Its only dialplan destination is 2374; it cannot access the management, private banking, FDM, reference or native voicemail extensions. The overlay disables private balance enrollment and calls, OIDC and ShadyBank, and creates a separate database. The dedicated gateway image adds only `res_pjsip_nat` to the standard gateway allowlist; this is necessary for host-reachable SIP Contact rewriting and return-path handling. The app resolves the emulator alias to the published InfoLine revision while retaining a distinct route identity and first-alert delay. Ordinary authenticated route timing is unchanged. The generated caller ID is for location selection, not identity verification.

The Setup page of the optional instance displays the URI, peer identity and first-alert delay under Incoming routes.

The dedicated PJSIP transport advertises UDP 5069 and the host loopback address for signalling; the endpoint advertises host loopback for SDP while binding its RTP sockets in the container. The RTP ports are mapped without translation. The CO must include `;rport` in its topmost SIP Via and preserve the host port in the Request-URI. It must bind a real RTP receive socket, advertise its actual port in SDP, send media from that socket and handle the peer's negotiated address and port. Symmetric RTP and contact rewriting handle the observed host/container NAT mapping. Start sending PCMU silence as soon as the call is answered so the media path is established before CAS. For a CO running in another container, loopback has a different meaning; run the CO on the same host or use a separately qualified container-network profile.

## Central office routing contract

Add an exact route for digits `2374` to this host-local URI. The following is an illustrative CO routing configuration, not an existing emulator configuration format:

```ini
[route.2374]
destination = sip:2374@127.0.0.1:5069
from_user = co
registration = false
transport = udp
codec = PCMU
```

Keep the existing NCC management and PSTN routes intact. Do not send the management test frame on this voice route. Prefer the existing SIP library integration; do not extend the old hard-coded local management INVITE implementation into another SIP stack. Route only once, then explicitly switch the collected digits to post-answer signalling. Follow SIP dialog Contact, Via and routing semantics, and propagate hangup in both directions.

The line jack already carries `C1`/`C0` loop current, `V0`/`V1`/`V` polarity reversal, `S`/`X` loop seizure/release, `H1`/`H0` handset state, `D<digit>` outpulsing and `W<hex>`/`M<hex>` for signed little-endian 8 kHz PCM. Apply answer supervision at the successful SIP answer and keep 20 ms audio delivery paced throughout the connected call. Do not use a faster polling loop to enqueue 160-sample blocks independently of the RTP clock: that can accumulate silence ahead of the terminal's acknowledgements. Prefer a monotonic 20 ms schedule or pull samples directly at the codec/RTP callback, with bounded queues and explicit underrun accounting. The existing CO reversal sequence takes 150 + 200 ms; the initial server delay leaves time for that and firmware transition. Measure the actual media arrival rather than stretching the ADSI reply deadlines. On remote hangup remove loop current and restore it using the existing CO disconnect behavior.

## Terminal hardware integration

The current emulator audio callback delivers received PCM to the handset speaker path. Confirm that the graphical terminal's actual CAS and Bell 202 receiver sees the same line samples via its emulated circuitry and register/interrupt interface. Hearing the burst is not proof of decode. Implement or extend the required receiver behavior against public protocol evidence and the user supplied ADSI compatible terminal firmware. Do not take a shortcut that writes decoded text directly to the graphical display.

On transmit, distinguish dialling DTMF from connected-call DTMF. Existing `D<digit>` events are collected for dial routing, but are not automatically delivered as connected-call audio. Ensure firmware-generated DTMF including the extended `A`, `B`, `C`, `D` symbols is supported. If the emulated hardware emits digits as events rather than PCM, render the corresponding tones into the line audio once, with appropriate duration and spacing. If the hardware already produces the tones in PCM, do not render them a second time. Do not synthesize `A` or `D1` automatically in the CO, infer success from receipt of bytes, or inject a synthetic NCC frame. Use 8 kHz PCMU with no VAD, lossy codec switching, echo cancellation, AGC or noise suppression during ADSI. Avoid underruns, clipped audio and stale queued media between calls.

## Acceptance evidence

| Gate | Required observation |
| --- | --- |
| SIP | The CO sends the 2374 INVITE, receives answer, completes the dialog and negotiates PCMU. The correct RTP ports carry media in both directions. |
| Supervision | The emulator observes answer polarity and enters its connected-call state before the first CAS. |
| Capability | The server sends an 85 ms CAS (2130 and 2750 Hz); the terminal's own receiver detects it and the terminal produces DTMF A. |
| Data | The server sends Bell 202 FSK at 1200 bit/s; the receiver delivers bytes to the terminal, checks framing and renders the InfoLine welcome screen. The terminal returns D1. |
| Selection | A real keypad/softkey input selects News, then Back. The server sends and the terminal acknowledges the matching screens. |
| Teardown | Exit restores voice, SIP BYE and loop release/current interruption work, and the next call starts cleanly. |
| Isolation | An unauthenticated `co` call to 6500, 6501, 6503, 6504 or 6505 is rejected. |

The standalone terminal test is independent of the graphical emulator. On a Linux Docker host run `python tests/live_emu_ingress.py` after starting the overlay. It uses the published loopback port via Docker host networking, decodes real ADSI frames with the standalone PJSUA2 receiver, navigates a menu, checks voice release and checks rejected destinations. Docker Desktop host networking is optional; a network-namespace test may instead use `ADSI_EMU_TEST_NETWORK=container:coinline-adsi-emu-gateway-1` but that does not by itself prove Windows host port forwarding. Test the actual CO on the host as well. Physical handset qualification and graphical terminal integration remain distinct from the standalone lab.

An opt-in interaction profile, `ADSI_EMU_INTERACTION_PROFILE=voice-between-screens`, restores voice at each acknowledged interactive screen while retaining the SDC session. Set it in the dedicated emulator Compose environment and recreate only that app when no active calls are present. The default is `continuous-data`, including all other service routes. The new profile re-alerts from voice before the next FSK and fails closed if the exchange cannot be confirmed. The authenticated telephony status reports `interactionProfile` under `emulatorIngress`. Test the changed profile in a separate namespace with `python tests/live_mixed_profile.py --network container:<isolated-gateway> --image <terminal-image> --profile voice-between-screens`; it checks keypad and softkey selections, repeated CAS/A, and final release. The hardware gate still requires actual terminal-generated selection and the matching next display.

The [voice profile lab milestone](../status/voice-profile-lab.md) records the successful firmware-in-emulator welcome, News, Back and Exit call. Physical handset qualification is separate.

References: [ADSI protocol](../spec/adsi-protocol.md), [Asterisk 22 PJSIP media configuration](https://docs.asterisk.org/Asterisk_22_Documentation/API_Documentation/Module_Configuration/res_pjsip/), [Docker Compose override semantics](https://docs.docker.com/reference/compose-file/merge/), [Docker loopback port publishing](https://docs.docker.com/engine/network/port-publishing/).
