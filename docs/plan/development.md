# Phased development plan

Each tranche ends with a reviewed change, reproducible evidence and a decision about the next gate. Work within a tranche in small commits with descriptive subjects. Record behavior, validation and known limitations in commit bodies. Keep each commit independently reviewable. Use separate feature branches for implementation and milestone pull requests after repository creation.

| Tranche | Dependencies and implementation sequence | Exit gate and evidence |
| --- | --- | --- |
| **P0 Design and fixtures** | Define scope, source register, module boundaries, graph schema, fixture data, test IDs, release plan and directory layout. | Local cross-references and JSON validate. Wire fixture arithmetic is independently checked. Every product requirement maps to acceptance tests and a tranche. |
| **P1 One live SDC exchange** | Build reproducible Asterisk 22 image and authenticated lab route, stub a direct PCM adapter, implement validated SDC framing and modem, wire ARI and media, then add the headless SIP terminal. Keep the first flow static. | Pass T01 to T09. One dialed call exercises CAS, DTMF A, FSK, D1, a readable screen, one softkey transition and return to voice. Publish sanitized comparative evidence from the Asterisk reference or document the exact comparison still pending. |
| **P2 App runtime and authoring** | Add PostgreSQL migrations and revision pinning, graph interpreter, administration/API, editor, terminal preview, isolated simulator and standalone terminal UI. | Pass T10 to T15. A draft authored in the UI previews, publishes, runs on a new SIP call and rolls back while an existing call stays on its starting revision. |
| **P3 InfoLine and handset qualification** | Implement the bundled demo, number-to-site import, weather adapter, fixtures and optional approved providers. Qualify Vista 350 and Millennium routes independently. | Pass T16 to T20. Public voice and ADSI paths display correctly labeled results. T20 can qualify each handset only from its own capture. Release emulator and individual handset support separately. |
| **P4 Resident features lab** | Pin the Asterisk comparator, define an original resident demo, add bounded download service and terminal storage. Investigate graphics after a successful Millennium SDC gate. | Pass T21 and T22. Record separate emulator and physical results for completion, aborted update, restart and persistence. Keep graphics gated by T23. |
| **P5 Read-only balance access** | Build isolated synthetic flow and administration, connect Bridge demo account, integrate enrolled routing and call-bound web approval, verify handset privacy and credential lifecycle. | Pass T24 to T27 with synthetic or demo data. Activate real accounts only after intended institution, closed route, terminal privacy behavior and revocation pass the live gate. |
| **P6 Optional information assistant** | Add curated questions and sources, model adapter, limits and deterministic fallback. | Pass T28. The public assistant is optional and the same menus work with the feature disabled. |
| **R1 Delivery and pilot** | Bring up checks at repository creation, add image jobs with P1, run restore and load exercises after P2, and qualify the deployment around the public P3 pilot. | Pass T29 to T32. Release by image digest. Publish the support matrix for that release and retain the prior successful deployment for rollback. |

Test definitions and case-to-requirement mappings are in the [verification plan](../test/verification.md).

## P1 implementation work orders

1. Establish the repository license and dependency inventory. Pin the gateway, PJPROJECT and SpanDSP to exact revisions with license and source metadata. Select an Asterisk 22 patch with `chan_websocket`, ARI external media, JSON control and media markers. The upstream external-media guide identifies 22.8.0 as the floor for passing the JSON choice through `transport_data`. Build a separate legacy-ADSI reference image with its deprecated modules explicitly enabled. Add reproducible build and check targets. [Asterisk media sources](../sources.md#s1-asterisk-pjsip-ari-and-media)
2. Implement outer framing and the small SDC parameter set. Compare synthetic bytes for connect, display, key definition, map selection and release against the reference. Run deterministic direct PCM loopback through Bell 202 and digit detection before introducing RTP.
3. Configure one anonymous-disabled lab SIP account and a single information extension. Anchor media, use PCMU, and implement ARI bridge and media attachment. Verify bidirectional audio, `A` through `D`, reliable media-drain markers and teardown. Use the cleanest proven digit carriage as the first published lab profile.
4. Add the headless terminal scenario runner on PJPROJECT. Drive the static `LAB` exchange through actual RTP. Confirm CAS detection and exact decoded bytes against independent reference output. Run no-capability, timeout, corruption, hangup and replay scenarios.
5. Run the same P1 call over an isolated ATA if hardware is available. Log results as candidates until the physical gate. If WebSocket misses a hard test, collect its failing trace and rerun the transport contract against AudioSocket before changing the default.

## Dependencies and decision gates

| Dependency | Owner role | Decision or scope consequence |
| --- | --- | --- |
| Authorization to create an independent repository, selected owner and visibility, repository license | Project owner | Start hosted CI and select image namespace. A local development branch can proceed. |
| Published Bellcore documents or verified carrier specification | Protocol lead | Update profile requirements and qualification limits when acquired. The reference subset can proceed with documented limits. |
| Known ATA and physical endpoints | Lab operator | Record negotiated codecs, digit path, settings and captures per handset. Only emulator support can be asserted while physical rows are pending. |
| Live news, market and ALC data agreements | Operator | Record provider terms and activation settings. Demo or authorized manual data can ship independently. |
| Real SimpleFIN account consent and institution coverage | Subscriber and operator | Demo data and Bridge demo validation can proceed. Eligibility and route privacy are verified before enabling real balances. |
| Public hostname, gateway security, OIDC and deployment destination | Release operator | Start pilot deployment after environment-specific onboarding and smoke testing. |

## Repository extraction

The project directory is designed to become the new repository root. Start from a reviewed commit, extract only its tracked subdirectory with history, and compare the extracted tree against the scoped parent tree. Review files and ancestor commits for public hygiene before the first push. The standalone repository becomes the canonical implementation location after transition. Configure branch protection, runner permissions, Actions environments and packages there. Keeping GitHub workflow configuration at the extracted root allows standard Actions discovery.
