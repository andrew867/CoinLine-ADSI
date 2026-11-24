# Run the CoinLine ADSI lab

Use Docker with Compose and Python 3.11 or later. On Windows run the commands from MSYS2 MINGW64 and make the Docker and Python executables available on its path.

```sh
python deploy/init_lab.py
docker compose --profile verify build
docker compose --profile verify up -d --no-build --wait app gateway reference
```

The initializer creates an ignored `.env` with generated lab credentials. The web console listens at `http://127.0.0.1:8080`. Use the value of `ADSI_ADMIN_PASSWORD` to sign in. `ADSI_WEB_PORT` changes the local HTTP port. The lab SIP endpoint uses identity `lab` and `ADSI_SIP_PASSWORD`. SIP and RTP bind to loopback by default, and `ADSI_SIP_PORT` changes the host SIP port. The SIP test client connects over the Compose network, which also avoids restrictions of host-to-container RTP NAT. A physical path requires a verified advertised address, codec, DTMF and FXS profile.

| Extension | Function |
| --- | --- |
| 6500 | Static ADSI interoperability exchange with the `Go` softkey and voice fallback |
| 6501 | Published application. The initial revision is CoinLine InfoLine. |
| 6502 | Synthetic balance demonstration, gated by `ADSI_DEMO_PIN` |
| 6503 | Resident feature lab route, enabled with `ADSI_FDM_ENABLE=1` and a one-shot approval |

```sh
sh tests/check-modules.sh
sh tests/smoke.sh
python tests/live_api.py
python tests/live_sip_app.py
python terminal-emu/view.py
```

Use `PYTHONPATH=service python -m coinline_adsi.pcm` to generate signed 16-bit little-endian mono PCM at 8 kHz. Pipe it through `docker compose --profile verify run --rm -T --no-deps terminal-emu pcm` for an independent SpanDSP decode without SIP.

Install the service requirements to run the Python verification scripts outside Docker. Use `PYTHONPATH=service python tests/check_pcm.py` for seeded noise, clipping and missing-frame checks. `python tests/load_lab.py` exercises the clean SIP profile with 100 calls and 10 persistent clients by default. `python tests/live_capacity.py` holds ten sessions to check that the next caller receives a controlled busy response. Keep the stack otherwise idle during these runs. Call traces from `tests/smoke.sh` are retained in its local ignored run directory.

Run `sh tests/rtp-impairments.sh` on an idle, isolated reference service with Linux traffic-control support. Its helper applies seeded jitter and deterministic spill packet drops to the reference container's outgoing RTP port range, then restores its default queue. The helper needs `NET_ADMIN` in the reference container's network namespace.

Open `http://127.0.0.1:8091` for the separate SIP terminal UI. Its dial, keypad, softkeys and trace control a new PJSUA2 call. The authoring console simulator instead exercises the graph with fixed fixtures. In the console, save a valid draft and publish it to apply the revision for new calls on extension 6501. Application history provides rollback to an older revision. The graph editor supports focusable nodes and explicit transition fields.

## Provider configuration

Fixture content is labeled `DEMO`. In Setup, an operator may define ECCC Datamart sites using `place`, `province`, `code` and `zone`. The `prefixes` map keys six-digit CNA assignments to site identifiers. The caller can confirm or change the suggested city. The optional `manual` catalogue accepts attributed news, quotes and draw results after the operator confirms the intended use is permitted. See the [data contract](../spec/data-and-access.md) for field and freshness rules.

For example, set `sites` to `{"st-johns":{"place":"St. John's","province":"NL","code":"s0000280","zone":"America/St_Johns"}}` to add the verified ECCC catalogue site to the location menu. [ECCC site catalogue](https://dd.weather.gc.ca/today/citypage_weather/docs/site_list_en.csv)

Download a CO-code CSV or ZIP from the Canadian Numbering Administrator. Supply a curated exchange-area map such as `{"NL":{"St. John's":"st-johns"}}` to `python deploy/import_cna.py <snapshot.csv> <exchange-map.json>`. The output contains the `prefixes` object for Setup and a CSV checksum for the import record. [CNA assignments](https://www.cnac.ca/co_codes/co_code_status.htm)

Use `feeds` to enable individual approved operations. Supply the corresponding HTTPS `ADSI_FEED_NEWS_URL`, `ADSI_FEED_MARKET_URL` or `ADSI_FEED_LOTTERY_URL` to the app container, with an optional matching `_KEY` for bearer authentication. The news adapter accepts RSS. The market and lottery adapters accept a JSON object keyed by the configured instrument or game, using the manual catalogue fields for each record.

The glossary is enabled by setting `assistant` to true. An optional HTTPS Chat Completions endpoint can be supplied with `ADSI_MODEL_URL`, `ADSI_MODEL_NAME` and `ADSI_MODEL_KEY` in the app container environment. It receives a question from the public glossary and public reference text. The available deployment modes and source constraints are in the [data contract](../spec/data-and-access.md).

## Controlled resident and private labs

Resident download uses the optional 6503 route. Enable it on an isolated lab deployment, then save a printable display and version in the authenticated `/api/v1/features` endpoint using its current ETag. Set `approved` to true to allow one attempt. The standalone terminal accepts the disposable slot only in its `fdm` scenario and persists the committed active display. Run `terminal-emu resident` with the same state file to read it after a restart. With this route enabled and no pending approval, run `python tests/live_resident.py` for the verification exchange. The synthetic balance check uses `python tests/live_balance_demo.py`.

Private enrollment requires a HTTPS origin, a configured OIDC provider and a deployment-specific encrypted data key. Set `ADSI_WEB_ORIGIN`, `ADSI_OIDC_DISCOVERY`, `ADSI_OIDC_CLIENT`, `ADSI_OIDC_SECRET` and `ADSI_DATA_KEY` in the app environment. The callback is `/auth/callback` and the enrollment page is `/bank`. A private, authenticated SIP route mapped by the administrator to `private-balance` is required. Enable `ADSI_PRIVATE_BALANCES=1` only after the route, endpoint display retention and institution pass their qualification. The lab dialplan offers the synthetic balance route by default.

An OIDC-enabled console uses `ADSI_OIDC_OPERATOR_SUBJECTS` as a JSON map of provider subjects to `administrator`, `publisher`, `author` or `viewer`. Authors manage their own drafts. Publishers control active revisions and administrators control provider and resident-feature configuration.

## Recovery and GitHub

Use `bash deploy/backup.sh <new-backup.age> <recipient>` with an installed `age` CLI. Run `bash deploy/restore-check.sh <backup.age> <identity-file>` to restore into a newly created verification database. Protect the database backup and the private enrollment encryption key independently.

Run `bash tests/rehearse-promotion.sh` with a Docker Engine using the containerd image store and the lab images already built. The rehearsal creates a separate Compose project and database. It promotes local images by digest, induces a failed SIP canary, restores the earlier digest pair and checks another real call.

The workflow files are located at the future repository root. The release workflow requires a repository license, builds candidate images with SBOM and provenance, and qualifies those exact digests in the lab. It attaches the qualified digest pair to the GitHub release. Promotion selects that release and expects a dedicated Linux deployment runner with Docker, GitHub CLI, jq, a provisioned lab smoke client and environment protection. See [delivery requirements](operations.md) for hosted setup.
