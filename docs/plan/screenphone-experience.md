# Screenphone experience and local services

## Presentation

The bundled InfoLine revision uses an information viewport with four printable lines of at most 20 characters each. The display body contains the title, content or instructions, not a duplicate menu of the physical softkeys. Numeric alternatives remain available through the voice prompt. The original bundled revisions remain available; the migration promotes this revision only when the existing application draft and published stock revision match.

Multi-page information repeats the title, presents two wrapped content rows and reserves the fourth row for page progress. Empty provider fields are omitted. Prev, Next and Back or Exit occupy physical positions 4, 5 and 6 where applicable, with unassigned positions blank. The numeric aliases for information paging remain 7 and 9 and result-page Back is 0. An operator can select the information layout in the graphical editor; existing custom graphs without that setting retain legacy paging. The console and standalone terminal browser provide side-key and bottom-key presentations without changing the transmitted frame. Banking activity also supports backward navigation, without changing the private approval requirement or access deadline.

The existing ACK and mixed voice/data session rules are unchanged. No physical terminal badge is earned by these changes. On a graphical terminal, verify viewport rows, labels beside the correct keys, key return values, first/middle/last page transitions and release using both keypad and actual softkeys. The standalone terminal fixture separately verifies the blank key-map slots and `*` and `#` return strings.

## Movies

More Services > Movies selects a theatre and film, then presents the show date and local showtimes in pageable information screens. With live cinema enabled, the CNA exchange area is confirmed with the caller, or a provincial capital can be selected manually. The same ECCC city coordinate resolver used for weather provides rounded latitude and longitude. The inference is the number's rate centre, not a caller's physical location or postal code. The application does not invent an FSA. Today and tomorrow use the configured province's default time zone; multi-zone province boundaries may require choosing the intended date explicitly.

The [regional catalogue](../../service/coinline_adsi/regional.json) contains the theatre and showtimes endpoints and province labels/time zones. The server uses `playingnearby`, then `showtimes` with the chosen theatre identifier and date. It filters showtimes by theatre and day, normalizes duplicate start times, omits sessions marked past, and displays local 24-hour times. It lists screenings, not ticket availability or booking. Up to 18 times are presented; a longer list directs callers to the cinema website. Public results are cached for 15 minutes, with no stale fallback beyond that window and a shared request budget. No caller ID is sent to Cineplex.

Set the operator provider setting `cinema` to `true`, enable `ADSI_REGIONAL_ENABLE=1` and set `ADSI_CINEPLEX_API_KEY` to a credential authorized for the Cineplex API. The endpoint returned HTTP 401 without a credential during initial probing; its live response and credentials remain unqualified. JSON shape support is based on the public [showtimes capture](https://github.com/yinbri/cineplex-mcp/blob/master/test/fixtures/showtimes.json) and synthetic theatre/location fixtures, not an official public API contract. The default (`cinema: false`) gives a clearly labelled synthetic theatre, film and showtimes; enabled but unavailable returns an unavailable screen, not demo results.

## Parcel tracking

More Services > Parcels accepts a numeric FedEx tracking number of 12 to 22 digits, with a Submit (`#`) and Erase (`*`) softkey. Erase on an empty entry cancels. Input is collected in one open input interval so a user can enter digits without a new ADSI exchange between each digit. The confirmation shows length and last four digits only, then permits Lookup, Retry or Back. It never echoes the full number on a public terminal.

The supplied public FedEx tracking page is intended for a browser; the service uses the documented [FedEx Basic Integrated Visibility API](https://developer.fedex.com/api/en-ca/catalog/track.html) instead of relying on a dynamically rendered page. The adapter obtains an OAuth token, submits one tracking number over HTTPS, verifies the response corresponds to that number, and presents status, update time and estimated delivery where supplied. It does not display address or signature data, and does not persist tracking numbers or results in the public provider cache. Authenticated Delivery shipments or other rejected responses remain unavailable. The simulator always uses synthetic records.

Set provider setting `parcel` to `true` and configure `ADSI_FEDEX_CLIENT_ID` and `ADSI_FEDEX_CLIENT_SECRET` with authorized developer credentials. `ADSI_FEDEX_SANDBOX=1` uses the FedEx sandbox and labels results accordingly. No keys are embedded in public configuration. Credentials and live provider response acceptance are still required; the default (`parcel: false`) returns a labelled fixture and enabled failures do not fall back to it.

## Validation

- `tests/test_screenphone.py`: content-only menus, four-line wire budget, stable pagination, numeric collection and confirmation, provider normalization, mock authorization and failure handling.
- `tests/test_graph.py`: operator simulator numeric input, confirmation and cancellation.
- `tests/terminal_vectors.cpp`: independent terminal decoding and sparse map softkey return strings.
- `tests/live_extra_services.py`: real standalone terminal SIP route through demo movies, previous/next physical softkeys and parcel entry/submit. This runs in the existing verification workflow.
- Physical screenphone qualification and live Cineplex/FedEx credentials remain separate acceptance gates.

## Additional service candidates

Phone-friendly next additions include regional transit and ferry schedules, road closures and weather alerts, local event listings, and public-service contacts. A public catalogue with text-based search and a human handoff fits the original screenphone concept without requiring an online purchase or collecting payment details. Keep each new external provider individually configurable and separately test fixture and live behavior.
