# Application platform

## Configuration and editing

The console has Applications and Setup pages. Applications edits, simulates, publishes and rolls back application revisions on extension 6501. Setup displays incoming route status, validates and saves provider settings, and configures the resident feature. SIP identities, dialplan and transport details are managed in the gateway configuration.

An application opens as a graph with a node palette, a properties form, focusable nodes and explicit transition fields. The fixture simulator displays the draft's handset screen, paging, softkey placement, prompt and trace. It accepts keypad input and simulated hangup and runs against synthetic data rather than dialing or reaching live adapters.

Use an app UUID, immutable revision UUIDs and an integer draft generation for optimistic concurrency. One draft per app is mutable. Publishing validates that generation, writes an immutable snapshot and switches selected routes transactionally. Rollback selects an older immutable snapshot. Each accepted call pins the app revision, terminal profile version and provider-mode selection. Archiving requires routes to be moved or disabled in the same transaction. Restore keeps the app unrouted until a new routing decision. Imports create a new draft and revalidate graph, templates and profile compatibility. Exports include the versioned graph and optional editor coordinates, with identifiers and references for resolving dependencies. Exclude enrollment, secrets and live data from exports.

## Graph execution contract

A graph defines `schemaVersion`, `entry` and `nodes` with stable IDs. Initial node types are:

| Type | Fields and transitions |
| --- | --- |
| `menu` | `lines`, `prompt`, `choices` with unique digit, key label and target, `onTimeout`. Map each choice to the same digit on the keypad and softkey. |
| `message` | `lines`, `prompt`, one `continue` choice and `onTimeout`. |
| `provider` | Named public `operation`, typed `args`, output `bind`, `onOk`, `onUnavailable`. Failures, timeouts and invalid results follow `onUnavailable`. |
| `end` | Optional `prompt`. Play when present, close the SDC session when active and hang up. |

Use the [graph schema](graph.schema.json) for structural validation. A second validator enforces unique IDs and digits, resolved edges, entry existence, reachability, a reachable exit from each node, and absence of cycles made exclusively of automatic transitions. A flow can loop through nodes that wait for user input. Reject rendering that cannot fit its referenced terminal profile or exceeds its encoded limits. Maximum 128 nodes, 32 automatic transitions per input, and 512 total transitions per call. Reserve keypad digits 7 and 9 for previous/next on generated continuation pages and 0 for the return or exit action when provided. Keep choice actions available on generated pages. A paged screen has at most four choice actions including any return action, leaving room for two paging keys. Align the spoken navigation with the screen.

Use a single-pass interpolation grammar `{{binding.field}}` over whitelisted scalar fields. Treat interpolated content as literal text. Validate referenced bindings and operations before publish. The interpreter accepts typed outputs from the named provider registry, with a bounded value size and explicit null or unavailable handling. It performs no arbitrary expression evaluation and accepts no shell command, dial string, code or URL from an application graph. Protected balance presentation is a fixed built-in internal flow reached through a dedicated private route. Public graph operations cover weather, headlines, quotes, draws, flight boards, directory search, cinema, parcel tracking, road and ferry reports, transit and the optional curated assistant. The bundled travel revision uses typed list and location selection for variable provider entries. See the graph schema for supported operations.

A per-call navigation window opens after the screen acknowledgment or first delivery of the voice menu. Single-digit choices trigger exactly one transition for a completed digit. Invalid digits redisplay the current choices once and leave the original timeout in force. A user-driven pagination action opens a new window after rendering the next page. Provider work is canceled at hangup and discarded on navigation changes. General app call context contains route, profile, app revision, a coarse region or selected place, mode and transient provider outputs. It excludes authentication inputs and financial data.

## Administration API

Prefix routes with `/api/v1`. Require a same-origin session and object-level authorization. State changes use authenticated POST, PUT or PATCH and CSRF protection. Mutation results return a stable error code, a safe message and field diagnostics where applicable. Use HTTP 400 for malformed bodies, 401/403 for authentication/authorization, 404 for absent or concealed resources, 409 for state conflicts, 412 for stale generations and 422 for semantic validation. Use `If-Match` on versioned edits and publish operations.

| Endpoint group | Methods and resource behavior |
| --- | --- |
| `/apps` and `/apps/{appId}` | GET lists or reads metadata, POST creates an app, PATCH renames it. |
| `/apps/{appId}/draft` and `/apps/{appId}/validate` | GET and PUT read and replace a draft, POST validate returns graph and layout diagnostics. |
| `/apps/{appId}/revisions` | GET lists immutable revisions, POST publishes the current draft generation with selected route bindings. |
| `/apps/{appId}/activate`, `/archive` and `/restore` | POST changes route bindings to a named prior revision, archives with route disposition, or restores an app without routing it. The latter two are app subresources. |
| `/apps/import` and `/apps/{appId}/export` | POST creates an imported draft, GET exports a selected revision or draft. |
| `/routes`, `/profiles`, `/telephony/status` | GET route, profile and incoming telephony status. |
| `/providers` and `/providers/test` | GET and PUT provider settings; POST validates the configuration, without calling live feeds. |
| `/features` | GET and PUT resident feature settings and one-use download approval. |
| `/simulations` and `/simulations/{id}/events` | POST creates a fixture-bound simulation, GET reads sanitized state, POST events submits a typed simulator action. |
| `/enrollment`, `/enrollment/bank-link` and `/enrollment/call-approval` | Subscriber-owned enrollment, provider connection and the call-bound approval exchange. Responses carry masked status and opaque IDs. |

Web roles are administrator, publisher, author, viewer and subscriber. Administrators manage routes, profiles, configuration and role bindings. Publishers can publish, activate and archive apps within their scope; authors can edit, import and simulate scoped drafts; viewers see permitted status and history; subscribers manage their own enrollment and approve their own calls. Use a maintained OIDC relying-party library with an external identity provider for shared deployments. Operator and subscriber privileges are assigned explicitly to opaque identity subjects. The local fixture profile uses a development-only identity, restricted to loopback and synthetic data. Audit configuration, publication and authorization outcomes with timestamp, action, result and opaque subject/resource identifiers.

## Standalone terminal emulator

`terminal-emu` runs independently as a SIP client and can dial the service or the reference harness. PJSUA2 handles SIP, RTP and the audio port. The executable supports headless scenarios with structured results. The local browser controller presents the display, keypad, softkeys, call state and trace. Both use the same terminal model. The FDM test mode has isolated persistent storage and tests committed and incomplete downloads. The authoring preview does not participate in this path.

The emulator consumes receive PCM, detects CAS, emits capability DTMF, demodulates Bell 202, and independently checks framing, parameters and state before rendering and acknowledging. It uses SpanDSP for modem reception and sends in-band tones. The service encoder and runtime are independent of the receiver, which is tested with native Asterisk output and documented bytes.

Provide scenarios for unsupported CPE, missing, delayed or malformed acknowledgments, damaged frame bytes, callback starvation, mid-spill hangup, and process restart. Generate synthetic packet impairment in the lab test transport and record its seed and settings. Emit an ordered transcript of media timestamps, signal decisions, frame metadata, screen cells and key mapping. Persist only explicit lab fixtures and sanitize published results. Report a timeout or mismatch with a nonzero exit in headless mode.
