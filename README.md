# CoinLine ADSI

[![Verification](https://github.com/andrew867/CoinLine-ADSI/actions/workflows/ci.yml/badge.svg)](https://github.com/andrew867/CoinLine-ADSI/actions/workflows/ci.yml)

CoinLine ADSI is a lab server for analog display telephones. **CoinLine InfoLine** presents Canadian regional headlines, weather, stock quotes, lottery draw results, airport flight boards, visual directory assistance, cinema showtimes and parcel tracking, with fixture, live or manual provenance as configured. Read-only banking is optional. Operators can build and test call flows in a browser. A standalone PJSUA2 terminal exercises signaling over SIP/RTP.

## Quick start

Install Docker with Compose and Python 3.11 or later. On Windows, run the commands from MSYS2 MINGW64.

```sh
git clone https://github.com/andrew867/CoinLine-ADSI.git
cd CoinLine-ADSI
python deploy/init_lab.py
docker compose --profile verify build
docker compose --profile verify up -d --no-build --wait app gateway reference
python terminal-emu/view.py
```

Open the operator console at `http://127.0.0.1:8080` and sign in with the generated `ADSI_ADMIN_PASSWORD` in the ignored `.env` file. Open the SIP terminal at `http://127.0.0.1:8091` and dial **6501** for InfoLine. The default configuration uses synthetic provider data. Live Canadian feeds, optional SimpleFIN enrollment and the private local calling route are documented in [Run the lab](docs/plan/running.md).

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
| [Extra InfoLine services](docs/plan/extra-services.md) | Airport keypad search, flight boards, directory, optional native voicemail and resident launcher |
| [Screenphone experience and local services](docs/plan/screenphone-experience.md) | Information-first layouts, paging, cinema and parcel tracking, credentials and qualification |
| [CoinLine-emu PSTN integration handoff](docs/plan/millennium-interop.md) | Dedicated 2374 SIP ingress, simulator routing, PCM contract and acceptance gates |
| [Local lab results](docs/status/local-lab.md) | Verified exchanges, recovery drills and qualification status |
| [Canadian InfoLine lab results](docs/status/regional-lab.md) | Provider responses, caller ID, finance and regional lottery verification |
| [Fixtures](fixtures/README.md) | Synthetic wire vectors, application graph and provider examples |
| [Sources](docs/sources.md) | Primary references, implementation evidence and unresolved questions |

The local software lab has verified the gateway and native Asterisk ADSI exchanges over SIP/RTP. Nortel Vista 350 and ADSI-capable Millennium support badges each require a separate physical qualification. Container release publishing requires an explicit project license and the deployment workflows require qualified target environments.
