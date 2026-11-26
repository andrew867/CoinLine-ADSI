# Packaging, operations and delivery

## Compose topology

The root `compose.yaml` provides the Linux lab with synthetic data by default. Services use health checks and explicit startup dependencies. Windows developers invoke Compose through MSYS2 MINGW64. [Packaging sources](../sources.md#s10-packaging-and-delivery)

| Service or job | Default configuration |
| --- | --- |
| `gateway` | Publishes Asterisk SIP/RTP on the configured lab interface only. ARI and media WebSocket stay on the private network. Unknown endpoints and outbound dialing are denied by default. |
| `app` | Serves API, UI artifacts, call coordination and scheduled providers. Ready after schema compatibility and gateway availability. Public health returns only coarse readiness. |
| `db` | Private PostgreSQL with persistent volume, readiness check and least-privilege service credentials. |
| `migrate` | One-shot schema migration job, serialized with an advisory lock. Run it before readiness checks. Schema changes require a documented rollback or restored backup. |
| `terminal-emu` | Optional software SIP handset in the `verify` profile. The local browser UI starts a terminal container on each dial using the `lab` SIP credentials. |
| `reference` | Isolated native Asterisk ADSI comparison gateway in the `verify` profile. |

Fixtures are JSON files under `fixtures/`; they are not a Compose service. The web console binds to loopback by default. The Applications page edits and publishes application revisions and provides a fixture simulator. The Setup page shows incoming routes, validates and saves provider settings, and configures resident features. Shared deployment requires a configured TLS reverse proxy and OIDC. Expose SIP and the declared RTP range only where needed, verify two-way RTP and keep PostgreSQL, ARI and media sockets private. Use distinct credentials for gateway, app and admin.

## Asterisk build and load allowlists

The Dockerfile pins Asterisk 22.12.0 and its archive checksum. Menuselect builds only the declared feature sets and their dependencies. The build selection and runtime module lists are tracked. The gateway uses `autoload=no` with explicit module entries; the module check and SIP tests verify the packaged and loaded sets. [Asterisk build and module sources](../sources.md#s1-asterisk-pjsip-ari-and-media)

| Image | Minimum feature set |
| --- | --- |
| Runtime gateway | `chan_pjsip`, the PJSIP resources needed for the configured endpoint and authentication, PCMU/RTP, a dialplan loader, Stasis and the ARI endpoints used for channel, event and bridge control, the bridge and timing resources, and `chan_websocket` with its dependencies for PCM. CoinLine's service generates ADSI on this path. |
| Native ADSI reference | `chan_pjsip` with the minimum SIP, RTP, codec and dialplan dependencies, `res_adsi`, and a lab-only dialplan trigger that calls the native ADSI routines. Run the reference image on an isolated lab network. |

Omit unused channel drivers, codecs, dialplan applications and connectors. Disable unused built-in services, including AMI. Keep ARI and the WebSocket listeners on the private network. The image check compares compiled, packaged and loaded module inventories against each reviewed allowlist and fails on missing requirements or unexpected additions. Verify SIP admission, media, ADSI signaling, voice fallback and teardown with the runtime gateway. Verify T09 with the reference image.

## Health, backups and release evidence

- Monitor call attempts and outcomes, ADSI negotiation and retry counts, bridge lifetime, provider age/failure, queue overflow, concurrent sessions and API errors. Group by low-cardinality profile and version. Use short-lived opaque session correlation. Keep high-cardinality caller and provider values out of logs and metrics.
- Retain sanitized operational events for 30 days by default and audit events for 90, subject to deployment policy. Record audio only on an explicitly enabled synthetic lab route. Keep user recordings, unredacted media captures and provider responses out of released artifacts.
- Back up revisions, routing, bindings and database state on a schedule to encrypted storage. Protect the recovery key separately. Prove restoration in an isolated stack, rotate a test secret and confirm deleted/revoked credentials do not silently reactivate. Pilot recovery objectives are a 24-hour recovery point and 4-hour recovery time measured in the drill.
- Deploy database-compatible releases with a canary call. Drain or end active calls predictably before replacing the gateway. Preserve the last known-good image digests and configuration. If smoke fails, restore the previous compatible app/gateway pair and re-run the canary. If schema compatibility fails, use the rehearsed restore plan with its recorded data-loss window.

## GitHub Actions

| Event | Workflow and outputs |
| --- | --- |
| Pull request and main | `ci.yml` checks documentation, fixtures, Python and C++ tests, builds the lab, runs SIP and browser scenarios and verifies optional native modules. |
| Scheduled | `ci.yml` repeats verification and runs capacity and resident persistence exercises. |
| Release tag | `release.yml` builds, qualifies and publishes app and gateway images with SBOM and provenance, then records their digests. |
| Environment promotion | `promote.yml` selects a published digest pair, runs a deployment smoke check and provides rollback on failure. The target runner and environment must be provisioned. |

Action references are pinned to reviewed commit SHAs. Use branch protection and required checks on `main`. Give untrusted pull requests no deployment secrets or publish credentials. Hardware qualification and live-provider activation have their own evidence requirements, independent of fixture verification. Release publishing and deployment require their respective target environments to be provisioned.

## Implementation layout

| Directory | Contents |
| --- | --- |
| `service/` | Python call runtime, audio and ADSI generation, provider adapters, API and database migrations |
| `web/` | React administration and browser simulator interface |
| `terminal-emu/` | Standalone terminal executable, local UI and scenario runner |
| `deploy/asterisk/` | Gateway image, dialplan and synthetic media profiles |
| `tests/` | Executable test suites organized by protocol, component, SIP end-to-end and browser |
| `fixtures/` | Original wire, graph and provider inputs, expected results and provenance |
| `.github/workflows/` | Verification, release and deployment workflows |
