# ADSI interoperability

## Contract and evidence

The first profile reproduces the observable **Asterisk 22 off-hook ADSI subset**. Bellcore SR-INS-002461 and TR-NWT-001273 are baseline references identified by ETSI. The ETSI server and terminal annexes record the European changes and defer unchanged clauses to Bellcore. The ETSI off-hook signalling document describes a different regional profile. Asterisk is implementation evidence, AST Tech Labs is a vendor summary, and each handset result is separately measured. [Protocol sources](../sources.md#s2-adsi-server-reference)

### Link and media

| Item | Baseline and project behavior |
| --- | --- |
| Alert | Server emits CAS only. Asterisk uses 2130 Hz and 2750 Hz for 680 samples at 8000 samples/s, or 85 ms nominal. Mute voice output before the alert and during the spill. |
| Capability | Await DTMF `A` in a 500 ms nominal window from CAS end in the project lab profile. `D` at this step signals no ADSI in the Asterisk reference. Missing or invalid capability response takes the voice path. |
| FSK | Bell 202, 1200 bits/s, mark 1200 Hz, space 2200 Hz, asynchronous 8N1, least significant bit first. Use a 150 ms nominal mark lead-in for first frame of each spill. The off-hook reference sends no channel seizure. |
| Downstream framing | `type, length, message_number, parameter_bytes, checksum`. Length counts message number and parameter bytes. Sum the final wire bytes modulo 256 for a zero checksum result. Carrier and preamble never enter the checksum. |
| Limits | Support one frame per spill, message number `1` and up to 253 parameter bytes in the initial profile. Later multi-frame support requires its own cumulative acknowledgment tests. |
| Message acknowledgment | Follow FSK with an expected `D` and count. In the one-frame profile, `D1` accepts and `D0` reports zero accepted. A missing, malformed or out-of-range reply fails the attempt. Allow one retransmission of the same frame, with an explicit state transition and no duplicate application effects. |
| Timing | Project lab default allows up to 1000 ms for the first acknowledgment digit after FSK drain and 1000 ms between acknowledgment digits. Only the active signaling state consumes protocol digits. Record actual on-wire start and spacing at the receiver for hardware qualification. |
| Mode transitions | Track voice, data and unknown states. Treat mode feedback such as `B`, where emitted by the profile, separately from `D1`, FDM acceptance and user input. Require terminal state confirmation in emulator tests and physical observation in qualification. |
| Analog levels | Gain and impedance are properties of the actual FXS/terminal path. Record measured levels and clipping status. Do not translate a caller-ID level cited for a 900 Ω test load directly into a PCM gain setting. |

The caller-ID SDMF, MDMF and VMWI types and 30-byte on-hook seizure are outside this subset. Lab codec is G.711 PCMU at 8 kHz, mono, with a nominal 20 ms packet interval and media anchored at Asterisk. The service side uses 8 kHz signed linear PCM. Verify silence suppression, gain, echo cancellation, packet loss handling and passthrough settings on the chosen ATA. Start with in-band DTMF detection on the gateway and deliver canonical completed digits from the caller leg through ARI. An RFC 4733 profile may replace that path when negotiation and transport of A through D are demonstrated. Each route uses one digit event source. Use ordered PCM and an independent DTMF detector in the direct diagnostic adapter. [Media sources](../sources.md#s1-asterisk-pjsip-ari-and-media) · [Asterisk wire reference](../sources.md#s2-adsi-server-reference)

### Call state machine

| State | Entry action and transitions |
| --- | --- |
| Answered | Bind the authenticated route, attach its media channel, pin the app revision, and start capability detection after media readiness. |
| Probe | Serialize CAS and await capability. On `A`, send display connect with data mode. On timeout or `D`, release the probe and start voice. |
| Await frame acknowledgment | Await output drain, accept the expected reply, then consume any profile-required mode feedback. Retry once on failure. A second failure enters recovery. After a retry succeeds, establish separation from outstanding replies before sending a different frame. |
| Display interaction | Send a complete screen and key map. Enable the map only after an acknowledgment attributable to that frame. Keep application input disarmed while the displayed key map is unconfirmed. Bind each completed digit to its current input window. Commit a single application transition for each accepted selection. Fetches run with explicit timeout and cancel transitions. |
| Voice or recovery | If display mode may be active and media survives, attempt one bounded voice/disconnect sequence while keeping the channel usable. If state stays uncertain and the handset could remain muted, end the call. On a successful voice transition, use numeric keys and speech prompts. |
| End | Best-effort display disconnect and voice switch when appropriate. Hangup in any state cancels pending work, invalidates caller input and releases the media resources. |

Separate the end of a software write from actual playback. Correlate the WebSocket media marker to the current spill and measure the received playback independently in tests. Enter an acknowledgment state before the expected digit can arrive and use the playback boundary to enforce the deadline. A retry carries the same bytes and belongs to the same logical transaction. A single-frame `D1` carries no transaction identifier. Receiving it inside the next frame's acknowledgment window establishes timing of delivery only.

After retry success, allow the next data frame only when the media profile can separate any outstanding reply from a reply to that frame. Establish separation using a qualified bound on terminal and transport delay with a drain and guard interval, or trustworthy timing evidence that excludes the earlier spill as the cause. A local queue becoming empty is insufficient on its own. If separation cannot be established before sending the next frame, or becomes uncertain while awaiting the reply, keep the next softkey map inactive and enter recovery. Resume voice when the profile can restore it safely, otherwise end the call. Verify these transitions with [T04-A](../test/verification.md#t04-a-stale-d1-in-the-next-frame-acknowledgment-window).

## SDC parameters

Each parameter is a tag, one-byte payload size and payload. Encoders validate ranges before writing. Decoders validate frame size, checksum, and every parameter boundary before applying any state change. Unknown or unsupported parameters in a candidate screen fail it as a unit. Use printable ASCII for the first profile. Convert display text at the presentation layer, before calculating byte sizes. [Encoder reference](../sources.md#s2-adsi-server-reference)

| Outer type | Tags used or reserved by this profile |
| --- | --- |
| Display `0x84` | `0x80` define softkey, `0x81` select softkeys, `0x82` load virtual display, `0x83` select virtual line, `0x85` disconnect, `0x86` data mode, `0x87` voice mode, `0x88` clear keys, `0x8E` connect, `0x94` clear screen. Reserve `0x89` and `0x8A` for profile-qualified input control and format. |
| Download `0x85` | `0x80` resident key, `0x81` predefined display, `0x82` script, `0x83` download connect, `0x84` download disconnect. |

P1 uses connect and data mode, one information-page line, a six-slot key map containing one selectable softkey with a single ordinary digit return, a selectable line, and display disconnect plus voice mode. Reproduce the Asterisk parameter layouts and delimiter rules at the pinned source revision. P2 extends this to paginated text and up to six keys with numerical equivalents. The editor uses a 20-column, four-content-line conservative service preset as a starting point. CPE geometry, softkey label limits and behavior are profile data. A historical Vista 350 listing describes an 8-line by 21-character LCD, which by itself gives no usable SDC viewport. [Vista evidence](../sources.md#s6-handsets-and-resident-features)

### Golden SDC example

```text
84 0D 01 82 07 01 40 FF 4C 41 42 FF 83 01 01 52
```

The parameter lengths are seven and one payload bytes, respectively. Together with both tags and lengths the parameters occupy 12 bytes. Adding the message number yields outer length `0x0D`. The non-checksum bytes sum to `0x04AE`, so the checksum is `0x52`. The display result is `LAB` on information-page line 1, left justified, with wrapping disabled and an empty secondary column. This isolated SDC vector starts after the FSK preamble. It is one part of a call test.

## Resident FDM and graphics

FDM has a separate allowlisted lab route, administrator permission and explicit operator initiation. Use the Asterisk compiler and its sample as a reference for record layout and ordering. The project sample is original, uses a disposable profile slot, and opens a harmless local information screen on a supported event. A published SDC revision does not initiate a resident download.

Keep FDM versions in a separate administration catalogue with service identifier, profile compatibility, artifact digest and approval state. Allow operators to add, retire and replace approved lab artifacts. An FDM editor, if added, uses a separate event/overlay model with validation against the supported resident opcode set.

Load the SDC session, send the download-connect parameter containing service text (up to 18 bytes), delimiter, four-byte feature download number, four-byte security field and version byte. After the link acknowledges and the terminal returns application acceptance `B`, send complete resident key records, display records and script records in that order in batches of at most 253 parameter bytes. Verify each acknowledgment. Finish with download disconnect, then separately unload SDC and restore voice. Store staged and committed terminal features apart. On refusal, hangup or integrity error, discard emulator staging and retain the prior feature; physical terminal behavior must be recorded. Verify restart, replacement and aborted replacement independently. Use distinct opcode tables for frame types, parameters, softkey returns and script operations. The feature security field is unrelated to account authentication. [Asterisk FDM](../sources.md#s2-adsi-server-reference) · [Nortel terminal references](../sources.md#s6-handsets-and-resident-features)

The Millennium target is a unit running **user supplied ADSI compatible terminal firmware**. First verify CAS, FSK, a readable SDC screen, softkey return and usable voice. Record terminal and adapter profiles with neutral lab identifiers. The graphical payphone patent motivates a future capability probe. Enable a graphics adapter only after observing an isolated, repeatable byte layout and verifying monochrome rendering against the named hardware. A text path remains available on every supported profile. [Graphical payphone patent](../sources.md#s6-handsets-and-resident-features)
