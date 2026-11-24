# CoinLine ADSI

CoinLine ADSI is a planned server for analog display telephones. The demo, **CoinLine InfoLine**, brings headlines, weather, market quotes and Atlantic Lottery draw results to a screenphone through a normal voice call. A browser-based editor will let operators build and preview their own call applications. A standalone software terminal will exercise the same telephony path as a physical handset.

## Design package

| Document | Contents |
| --- | --- |
| [Product and engineering requirements](docs/spec/requirements.md) | Scope, requirement IDs, architecture, boundaries and release targets |
| [ADSI interoperability](docs/spec/adsi-protocol.md) | Media profiles, wire formats, SDC, FDM and handset evidence |
| [Application platform](docs/spec/application-platform.md) | Call flow, graph editor, versioning, API and emulator contracts |
| [Data and access](docs/spec/data-and-access.md) | InfoLine screens, feeds, location selection, SimpleFIN and the information assistant |
| [Verification plan](docs/test/verification.md) | Test cases, required evidence and requirements traceability |
| [Phased development plan](docs/plan/development.md) | Tranches, first implementation tasks and acceptance gates |
| [Packaging and delivery](docs/plan/operations.md) | Compose topology, operations, repository split and GitHub Actions |
| [Fixtures](fixtures/README.md) | Synthetic wire vectors, application graph and provider examples |
| [Sources](docs/sources.md) | Primary references, implementation evidence and unresolved questions |

The first milestone is an incoming SIP call that sends a live screen, handles one softkey and returns the standalone terminal to voice. The interoperability gate also requires the standalone terminal to decode a native Asterisk exchange. Nortel Vista 350 and ADSI-capable Millennium support badges each require a separate physical qualification.

This directory is the documentation and fixture baseline. It is organized to become the root of an independent repository.
