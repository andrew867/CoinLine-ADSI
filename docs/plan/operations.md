# Packaging, operations and delivery

## Compose topology

Provide a Linux `compose.yaml` at the repository root with a default synthetic lab configuration. Use service health checks, deliberate startup and dependency reconnect rather than using startup timing as readiness. Use a pinned build manifest and OCI image digests for releases. Windows developers invoke Compose through MSYS2 MINGW64. [Packaging sources](../sources.md#s10-packaging-and-delivery)

| Service or job | Default configuration |
| --- | --- |
| `gateway` | Releases Asterisk SIP/RTP on the configured lab interface only. ARI and media WebSocket stay on the private network. Deny unknown endpoints and outbound dialing by default. |
| `app` | Serves API, UI artifacts, call coordination and scheduled providers. Ready after schema compatibility and gateway availability. Public health returns only coarse readiness. |
| `db` | Private PostgreSQL with persistent volume, readiness check and least-privilege service credentials. |
| `migrate` | One-shot schema migration job, serialized with an advisory lock. Run it before readiness checks. Schema changes require a documented rollback or restored backup. |
| `terminal-emu` | Optional headless software terminal on the lab network. Desktop/Web UI mode runs separately with a loopback listener. Use its own SIP identity. |
| `fixtures` | Optional local deterministic fixture server for provider failures and seeded default data. Used in CI without live credentials. |

The web console binds to loopback in the default profile. A pilot sits behind a configured TLS reverse proxy and managed OIDC. Expose SIP and the declared narrow RTP range only where needed. Validate gateway address mappings through a two-way RTP test, including NAT if present. Keep Postgres, ARI and media sockets private. Use mounted secrets, controlled route enrollment and distinct credentials for gateway, app and admin. Give each container only the access it needs. The browser setup wizard configures applications, routes, profiles and providers using typed resource contracts, with a dry-run before applying changes.

## Health, backups and release evidence

- Monitor call attempts and outcomes, ADSI negotiation and retry counts, bridge lifetime, provider age/failure, queue overflow, concurrent sessions and API errors. Group by low-cardinality profile and version. Use short-lived opaque session correlation. Keep high-cardinality caller and provider values out of logs and metrics.
- Retain sanitized operational events for 30 days by default and audit events for 90, subject to deployment policy. Record audio only on an explicitly enabled synthetic lab route. Keep user recordings, unredacted media captures and provider responses out of released artifacts.
- Back up revisions, routing, bindings and database state on a schedule to encrypted storage. Protect the recovery key separately. Prove restoration in an isolated stack, rotate a test secret and confirm deleted/revoked credentials do not silently reactivate. Pilot recovery objectives are a 24-hour recovery point and 4-hour recovery time measured in the drill.
- Deploy database-compatible releases with a canary call. Drain or end active calls predictably before replacing the gateway. Preserve the last known-good image digests and configuration. If smoke fails, restore the previous compatible app/gateway pair and re-run the canary. If schema compatibility fails, use the rehearsed restore plan with its recorded data-loss window.

## GitHub Actions

| Event | Required jobs and outputs |
| --- | --- |
| Pull request | Verify Markdown, schema, fixtures and requirement mapping. Check dependency locks, lint/build the components, run unit and contract tests, start the isolated Compose stack and run emulator and browser scenarios. Run dependency and secret scanning with read-only token permissions. Store sanitized logs and test results. |
| Default branch | Repeat required checks and build release candidates. Run scheduled extended media and regression cases with fixed seeds, a pinned gateway and a bounded artifact lifetime. |
| Release tag | Build or promote tested images tied to the exact commit and pin digests. Generate SBOMs, scan dependency and image policy, attach provenance and publish to GHCR with release notes and the qualifying test matrix. Grant package write and attestation permissions only to release jobs. |
| Environment promotion | Deploy by digest to staging, run health and a real SIP emulator smoke call, and record the exact versions. Production uses environment approval, scoped secrets and the same digest. Run the same smoke test and capture deployment and rollback outcomes. |

Lock action references to reviewed commit SHAs. Use branch protection and required checks on the default branch. Give untrusted pull requests no deployment secrets and no publish credentials. Hardware qualification and live-provider activation are documented approvals with their own evidence, independent of the green fixture workflow. Set up hosted workflows as soon as the independent repository exists. Release publishing and deployment require their respective target environments to be provisioned.

## Implementation layout

| Directory | Future contents |
| --- | --- |
| `service/` | Python call runtime, adapters, native DSP boundary, API and database migrations |
| `web/` | React administration and browser simulator interface |
| `terminal-emu/` | Standalone terminal executable, local UI and scenario runner |
| `deploy/asterisk/` | Gateway image, dialplan and synthetic media profiles |
| `tests/` | Executable test suites organized by protocol, component, SIP end-to-end and browser |
| `fixtures/` | Original wire, graph and provider inputs, expected results and provenance |
| `.github/workflows/` | Verification, release and deployment workflows |
