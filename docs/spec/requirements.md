# Product and engineering requirements

## Product boundary

An administrator installs and provisions a small voice service. A caller dials its SIP extension through an ordinary analog handset or compatible software terminal. The service answers, determines ADSI support, and presents the published application as display screens with context-sensitive softkeys. The same public menu works through voice prompts and numeric keys when ADSI is unavailable. CoinLine InfoLine is the bundled demonstration, with English as the first supported locale and Atlantic Canada as the initial regional catalogue.

SDC drives the live experience. Resident FDM features are an optional lab capability with a separate release gate. Subscriber management, payphone billing, coin control, emergency calling, PSTN switching and existing CoinLine NCC table downloads are outside the project boundary.

| ID | Release requirement |
| --- | --- |
| TEL-01 | Accept authenticated lab SIP calls via Asterisk/PJSIP and exchange bidirectional 8 kHz media. Support file or PCM loopback as an independent diagnostic adapter. |
| TEL-02 | Render SDC screens and keys, handle selections, release data mode and fall back to voice with bounded negotiation and cleanup. |
| TEL-03 | Maintain separate emulator, Vista 350 and Millennium compatibility records. Each physical qualification is specific to its hardware, media path and profile. |
| TEL-04 | Support an explicitly enabled, profile-qualified FDM lab flow with durable terminal commit and abort verification. Keep graphics experimental until independently qualified. |
| EMU-01 | Provide a standalone terminal client with a visual and headless mode. Both speak SIP and receive actual call audio. |
| EMU-02 | Provide deterministic impairment and terminal behavior controls, independent framing checks, diagnostics and restartable FDM storage. |
| APP-01 | Create, update, import, export, archive, publish and roll back application revisions. Route new calls atomically and pin in-flight calls to their starting revision. |
| APP-02 | Provide a graphical call-flow editor, keyboard-accessible alternatives, handset preview and an isolated simulator with a trace and fault controls. |
| APP-03 | Enforce a bounded, versioned declarative runtime with profile-aware layout and equivalent voice navigation for public flows. |
| DATA-01 | Offer location selection using NPA-NXX as a suggestion. Permit caller override and handle unavailable or unassigned locations. |
| DATA-02 | Offer weather, news, market quotes and ALC draw results with source and observation, publication, quote or draw times as applicable. Label age, delay, manual and demo modes. |
| FIN-01 | Offer a read-only SimpleFIN balance adapter tied to explicitly enrolled accounts and separate call authorization. Synthetic banking is the default. |
| FIN-02 | Protect balances and credentials throughout enrollment, presentation, revocation, logging and recovery. |
| AI-01 | Offer an optional public information assistant with approved context, attribution, bounded costs and an explicit unavailable response. |
| OPS-01 | Package a local Linux service stack with Compose and document provisioning, monitoring, backups, migrations and rollback. |
| OPS-02 | Use required GitHub checks, versioned releases and digest-based delivery once an independent repository and target environment exist. |

## Proposed architecture

| Component | Responsibility |
| --- | --- |
| Asterisk 22 LTS gateway | SIP endpoints and trunks through `res_pjsip`, SDP, RTP, dialplan admission, ARI call lifecycle and a per-call two-leg media bridge. |
| Python service | Async call orchestration, ADSI state machine, flow interpreter, provider adapters, scheduler and a FastAPI HTTP interface. A narrow native binding supplies reusable SpanDSP tone and modem primitives. The application supplies ADSI message semantics. |
| React and TypeScript web client | Same-origin administration and subscriber enrollment, accessible flow editing, profile preview and simulator controls. Browser simulation uses the server interpreter. |
| PostgreSQL | Immutable revisions, routing, provider configuration metadata, operator audit events and enrollment mappings. Credentials use an external key or secret mount. Audio and per-call buffers are ephemeral. |
| Standalone terminal | C++ PJSUA2/PJMEDIA SIP client with CLI and an optional local browser UI served by the client. Independent terminal state, decoder and display logic. |

A physical handset connects to an FXS port on an ATA or equivalent gateway. The ATA places a SIP call to Asterisk and carries CAS and FSK as in-band audio. Asterisk delivers call events over ARI and bidirectional signed linear PCM over `chan_websocket` to the service. The TCP WebSocket is internal to the deployment. The service can also run the SDC engine with a diagnostic PCM adapter. AudioSocket is a documented alternative for an interoperability spike if the primary adapter misses a media requirement. Each live adapter has to pass the same waveform and lifecycle tests. [Asterisk PJSIP](../sources.md#s1-asterisk-pjsip-ari-and-media) · [SpanDSP](../sources.md#s3-spandsp) · [PJSUA2](../sources.md#s4-pjproject)

Use a modular monolith in one service process for the first release. One task owns each call's state and processes an ordered event queue. A provider lookup runs outside the media callback with cancellation and a deadline. Media overflow ends the pending transaction and enters bounded recovery. Incoming sessions have opaque IDs and bridge only their own caller and media legs. Runtime switches distinguish lab, public information and enrolled private service.

## First release targets

These are project acceptance targets, measured in the lab. They do not establish Bellcore timings or public deployment capacity.

| Measure | Target and clock |
| --- | --- |
| Cached response | p95 at most 2 seconds from a completed menu token to first response audio or start of FSK on the service media clock, over 100 calls in the clean local profile. |
| Admission | 10 concurrent information calls on a recorded baseline host. A call over the configured limit receives a controlled busy response. Record gateway/service versions, CPU, memory and test topology. |
| Failed capability probe | Initial voice fallback starts within 2 seconds of the end of the probe on the service media clock in the clean configuration. |
| Teardown | Within 2 seconds of a hangup event reaching the service in the clean profile, the bridge, media leg, task and input state are gone. |
| Provider deadline | 2 seconds per call-bound operation by default. Use a valid cache snapshot or bounded unavailable result. |
| Session bounds | 60 seconds of caller inactivity or 15 minutes total by default. A private flow uses the shorter bounds in the data specification. |

Use monotonic clocks for deadlines, recorded UTC and source timestamps for data, named IANA zones for local display, and measured audio sample offsets for waveform durations. Publish baseline conditions alongside any numeric result. Evaluate codec, DTMF carriage and ATA settings together when making hardware claims.
