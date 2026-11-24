# CoinLine ADSI

CoinLine ADSI is a lab server for analog display telephones. **CoinLine InfoLine** presents Canadian regional headlines, weather, stock quotes and lottery draw results, with fixture, live or manual provenance as configured. Read-only banking is optional. Operators can build and test call flows in a browser. A standalone PJSUA2 terminal exercises signaling over SIP/RTP.

## Design package

| Document | Contents |
| --- | --- |
| [Product and engineering requirements](docs/spec/requirements.md) | Scope, requirement IDs, architecture, boundaries and release targets |
| [ADSI interoperability](docs/spec/adsi-protocol.md) | Media profiles, wire formats, SDC, FDM and handset evidence |
| [Application platform](docs/spec/application-platform.md) | Call flow, graph editor, versioning, API and emulator contracts |
| [Data and access](docs/spec/data-and-access.md) | InfoLine screens, feeds, location selection, SimpleFIN and the information assistant |
| [Canadian provider catalogue](docs/spec/regional-providers.md) | Source contracts, quota limits, regional routing and coverage gaps |
| [Verification plan](docs/test/verification.md) | Test cases, required evidence and requirements traceability |
| [Phased development plan](docs/plan/development.md) | Tranches, first implementation tasks and acceptance gates |
| [Packaging and delivery](docs/plan/operations.md) | Compose topology, operations, repository split and GitHub Actions |
| [Run the lab](docs/plan/running.md) | Build, provision and test the local service, console and emulator |
| [Local lab results](docs/status/local-lab.md) | Verified exchanges, recovery drills and qualification status |
| [Canadian InfoLine lab results](docs/status/regional-lab.md) | Provider responses, caller ID, finance and regional lottery verification |
| [Fixtures](fixtures/README.md) | Synthetic wire vectors, application graph and provider examples |
| [Sources](docs/sources.md) | Primary references, implementation evidence and unresolved questions |

The local software lab has verified the gateway and native Asterisk ADSI exchanges over SIP/RTP. Nortel Vista 350 and ADSI-capable Millennium support badges each require a separate physical qualification.

This directory is organized to become the root of an independent repository.
