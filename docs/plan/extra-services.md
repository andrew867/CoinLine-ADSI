# Extra InfoLine services

The bundled service revision adds a More menu (5), with airport boards (1), directory assistance (2), and the information desk (3, if enabled). An unchanged active sample is upgraded on migration. An edited, archived or independently published application is left alone, and every previous published revision remains available for rollback. The graphical editor exposes the new provider operations. Its simulator uses fixtures and resolves `selected` to a sample airport or directory entry; the standalone SIP terminal tests the actual interactive search.

## Airport boards

Select Arrivals or Departures, then enter one keypad digit per letter of an IATA (three letters) or ICAO (four letters) code using ABC=2, DEF=3, GHI=4, JKL=5, MNO=6, PQRS=7, TUV=8 and WXYZ=9. For example, YYT is 998 and CYYT is 2998. A 20-column screen shows the number of remaining matches and the first candidate. Wait for each updated screen before entering the next digit. Press 1 or # to list the matches, * to erase a digit or 0 to cancel. In the list, use 1 or 2 to select, 3 or 4 to move forward or backward, or 0 to resume searching.

The bundled index includes 4,078 scheduled-service airports with IATA codes, from the public-domain [OurAirports dataset](https://ourairports.com/data/). The ICAO column is provided where known. Canadian entries are displayed first. Source snapshot retrieved 24 November 2026; CSV SHA-256 `a903f63c4a5fef41acd82ed0876acce0d1efd470849e1a6a1f79d34948b6123b`. To refresh the catalogue, download the source CSV into an ignored build directory and run `python deploy/import_airports.py build/airports-source.csv service/coinline_adsi/airports.json`. Review the resulting changes and run the tests before committing. The index is not a navigation database.

By default the boards display synthetic rows with a DEMO heading. For live real-time flight status, the operator can obtain an [Aviationstack API key](https://aviationstack.com/pricing) for their permitted use and set `ADSI_AVIATIONSTACK_KEY` in the ignored `.env`. In Setup, merge `"flights": true` into the existing provider configuration, then validate and apply it. Recreate only the app container to pick up an environment change. The free personal/non-commercial plan advertises 100 requests per month. The adapter allows at most three real requests per UTC day (93 in a 31-day month) across both directions and all airports, including errors. Shared cache hits consume no quota. Responses are cached for 15 minutes, with a maximum two-hour stale snapshot. A missing key, provider error or exhausted quota without a usable snapshot displays unavailable, never fictional live data. The adapter uses the HTTPS [real-time flights API](https://docs.apilayer.com/aviationstack/docs/api-documentation), not a paid timetable endpoint. Coverage depends on the provider's response; this is not a complete airport schedule.

Five nearest reported flights are shown, ordered by time. Times are UTC, with day of month followed by HH:MM on live rows. Status abbreviations: SCH scheduled, AIR active, LND landed, DLY delayed, CXL cancelled, DIV diverted, INC incident, UNK unknown. The fetch timestamp and source remain visible on later pages. 7 and 9 navigate pages; 0 returns. Cancelled selection returns to the unavailable/back screen. No live key or billable call is necessary for the verification suite.

## Visual directory

Use one keypad digit per letter of a name or word in a name. Search mechanics match the airport selector, with up to eight digits. The result displays the name, number and description. By default these are explicitly synthetic. Merge a `directory` array into the provider configuration to replace the fixtures. Example:

```json
{"directory":[{"name":"Demo reception","number":"7001","detail":"PBX extension"}]}
```

The importer `python deploy/import_directory.py local/voicemail.conf public-directory local/directory.json` creates a configuration fragment from an explicitly selected Asterisk voicemail context. Only simple `mailbox => password,name,...` definitions are supported; the importer ignores hidden entries and never exports passwords or notification addresses. Inspect and merge the fragment into the existing provider settings. Do not use a private subscriber context or commit the generated directory. The local directory is read-only; selecting an entry does not originate an arbitrary outbound call. There is no purchased directory API or scraped private listing service.

## Native Asterisk mail and directory (optional)

For a disposable lab with a native ADSI terminal, run `python deploy/init_lab.py` to generate or append an eight-digit `ADSI_NATIVE_MAIL_PIN` in the ignored configuration. Enable the optional Compose overlay using `docker compose -f compose.yaml -f compose.native.yaml build gateway` and `docker compose -f compose.yaml -f compose.native.yaml up -d --wait`. The base image and base module allowlist remain unchanged. The optional build adds only native directory, voicemail, WAV files and ADSI support and installs English core sound prompts. The synthetic mailbox is 7101, and its messages use a separate persistent volume.

| Extension | Native service |
| --- | --- |
| 6505 | `VoiceMailMain` for mailbox 7101, requiring the generated PIN |
| 6506 | `Directory` with ADSI enabled, searching the synthetic voicemail context and routing a selected listing to its mailbox |
| 6507 | Leave a message in the synthetic mailbox |

The native applications manage their own display sessions. Asterisk's voicemail implementation can attempt a resident download when the corresponding service is absent, so use a disposable test terminal. The native slot is distinct from CL01. The standalone emulator's bounded CL01 and SDC profile is not a complete implementation of Asterisk's native voicemail input controls. Qualification of the native display and physical handset interaction remains separate; do not claim a hardware badge from module inventory tests. See [Asterisk 22.12.0 Directory](https://github.com/asterisk/asterisk/blob/22.12.0/apps/app_directory.c) and [Asterisk 22.12.0 voicemail](https://github.com/asterisk/asterisk/blob/22.12.0/apps/app_voicemail.c).

## Resident InfoLine launcher

Set `ADSI_FDM_ENABLE=1` only in the intended resident lab. In Setup, choose the idle message/version, enable the Info softkey launcher, approve the next download and save. Dial 6503 in the standalone terminal's FDM scenario. The one-use approval is consumed atomically, and the downloaded feature uses the existing disposable CL01 slot. The softkey encodes off-hook, wait for dial tone, and the fixed 6501 digit sequence, based on [Asterisk's public FDM compiler](https://github.com/asterisk/asterisk/blob/22.12.0/apps/app_adsiprog.c). No automatic dial occurs during installation. The display-only feature remains available by clearing the launcher checkbox.

In the standalone terminal web view (run `python terminal-emu/view.py`), select Install approved feature, then InfoLine resident key. The equivalent CLI commands are `docker compose --profile verify run --rm -T terminal-emu gateway fdm` to download, `docker compose --profile verify run --rm -T terminal-emu resident` to inspect persisted state and `docker compose --profile verify run --rm terminal-emu gateway launch` to model pressing the installed key and open an interactive SIP call. The launcher is accepted only after the ordered FDM commit and supports only extension 6501. Real handset launch behavior and persistence require physical qualification.

## Verification

`tests/test_extra_services.py` checks code prefix narrowing, cancellation, voice fallback, frame checksums, graph validation, fixture and live parsing, quota bounds, directory validation, and failure behavior. `tests/live_extra_services.py` tests the ICAO search, airport board and selected directory entry through actual SIP/RTP against the standalone terminal. The resident check also downloads the launcher, restarts the terminal process and opens InfoLine using the installed feature. Native module/dialplan checks are independent from the custom service tests.
