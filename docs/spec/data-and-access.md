# InfoLine data and access

## Public information service

The bundled travel revision welcomes the caller with `COINLINE INFOLINE`. Its softkeys are `1 News`, `2 Weather`, `3 Finance`, `4 Lotto`, `5 More` and `0 Exit`. More opens `1 Flights`, `2 Dir` (Directory), `3 Travel`, `4 Movies` and `5 Parcels`; `0 Back` returns. Travel contains road reports, ferry status, transit and the optional information assistant. Weather includes current conditions, forecast and alerts. Finance contains stocks, financial and biotech news and banking. Weather and lottery use location selection; detail screens use paging and a return path. Private banking has a dedicated entry route and authentication flow.

| Operation | Initial output | Source and activation |
| --- | --- | --- |
| `weather.current` and `weather.forecast` | City, temperature and observation time, or forecast period and issuance time. Keep warnings distinct from routine forecasts and preserve their issue/expiry state. | ECCC MSC City Page Weather via Datamart, English XML and a configured site catalogue. |
| `news.headlines` | Paged publisher-attributed headlines with publication times. | Synthetic, manual or configured regional and HTTPS feeds. Approve text display, audio reading and cache rights before activation. |
| `market.quote` | Allowlisted symbol, exchange, price, currency, source quote timestamp and feed delay or EOD status. | Synthetic watchlist, manual records or configured regional feeds. Record the provider's claimed delay independently of the computed age. |
| `lottery.draw` | Operator, game, draw date, numbers and separately labeled bonus fields. Informational results only; verify against the official lottery operator. | Synthetic, manual or supported Canadian regional feeds. See the [provider catalogue](regional-providers.md) for coverage. |

[Weather and numbering](../sources.md#s7-weather-and-numbering) · [News, market and lottery](../sources.md#s8-news-market-and-lottery)

Normalize allowed NANP caller identity from the admitted route to an NPA-NXX string. Use the Canadian Numbering Administrator assignment snapshot with an operator-curated exchange-to-weather-site and province map. Resolution precedence is caller choice in the current call, existing authorized subscriber preference where available, confirmed prefix suggestion, then manual selection. Present `Weather for <city>?` before using a suggested location. Handle withheld, foreign, non-geographic, unassigned and ambiguous prefixes through a configured region and city menu. Number portability and VoIP mean a prefix identifies a numbering assignment and can be wrong for the caller's physical location. Never resolve or log the subscriber's individual line number in the public provider layer.

Provider adapters return a validated result with `status` (`fresh`, `stale` or `unavailable`), `mode` (`live`, `manual` or `demo`), `source`, `dataTime`, `fetchedAt` and a bounded typed `value` on success. Observation, issuance and publication times come from the source. Express times as RFC 3339 instants, and keep an original draw date as a date with the draw's documented zone when time is absent. Cache by provider, operation and non-personal arguments. A failed refresh can serve within the configured stale window with a visible/spoken label. Default freshness and maximum age are project choices measured from the relevant provider timestamp, with separate lookup cache refresh intervals.

| Item | Initial age policy |
| --- | --- |
| Weather observation | Fresh up to 2 hours, stale up to 6 hours. |
| Weather forecast | Fresh up to 6 hours from issuance, stale up to 24 hours when a forecast period remains valid. An expired alert is omitted. |
| News | Fresh up to 6 hours, stale up to 24 hours. |
| Intraday quotes | Fresh up to 30 minutes from the quoted time, stale up to 24 hours with delay status. |
| End-of-day quotes | Show the session date and EOD label. The expected latest close comes from the licensed feed or exchange calendar. Use unavailable if the session cannot be established or the last close exceeds 7 calendar days. |
| Lottery | Show an explicit draw date. Use the configured game schedule to label a last confirmed draw if a later result is expected. Validate corrected draws as new revisions, retaining provenance. |

Cache and coalesce provider requests. Keep provider limits, redistribution rights, supported markets/games, source fields and expected update schedule in provider configuration. Normalize content before display, cap size and reject malformed inputs. Use a fixed public message when a source is unavailable. Demo data is labeled on affected screens and voice responses.

### Graph adapter arguments

Each operation takes only the fields listed here. Resolve catalogue identifiers server-side before making a lookup. Use projection fields chosen by the operation for graph interpolation. Structured lists are rendered by typed InfoLine components.

| Operation | Arguments and result fields |
| --- | --- |
| `weather.current` | Required `site`. Return `place`, `temperatureText`, `localTime` and `displayTitle` for interpolation. Attach structured warning data where present. |
| `weather.forecast` | Required `site`. Return the place and forecast periods with start/end instants and concise text. |
| `news.headlines` | Required `topic`. Return headline items with publisher and publication time, with optional approved summaries. |
| `market.quote` | Required `instrument`, a configured exchange-symbol identifier. Return exchange, symbol, price text, currency and delay category alongside the source timestamp. |
| `lottery.draw` | Required `game`, optionally `draw_date` as an ISO calendar date. The game binding selects the operator and region. Return the operator, draw date, zone, ordered numbers and named bonus fields. |
| `assistant.answer` | Required `question`, a curated question identifier. Return answer text and source labels. |

## SimpleFIN balance service

The web-enrolled user connects an account in SimpleFIN Bridge, submits a one-time Setup Token through the authenticated enrollment page and chooses which account aliases may be presented. Claim the token server-side once. Validate both the returned Access URL and the decoded claim URL against configured HTTPS Bridge hosts and path roles. Use explicit TLS verification, fixed egress policy and disabled redirects. Reserve the pending claim before sending it, and durably store the returned Access URL under the deployment encryption key before retrieving the account list. Account selection and its encrypted pending credentials remain recoverable after a process restart. An uncertain claim must be checked or revoked at Bridge before the pending record is discarded and another token generated. Limit requests to the provider budget, recording account-list and account-specific read counters in the private database. [SimpleFIN protocol and Bridge](../sources.md#s9-simplefin)

Use `GET /accounts` with `version=2` and `balances-only=1` on the approved Access URL. Bind selections to subscriber, connection ID and source account ID. Parse amounts as decimal strings, preserve sign and currency, and display the source balance time. Present available balance as a separate field only when supplied. Show its label explicitly. A source-revoked token, partially failed response for the requested account, unexpected account, malformed amount or absent balance timestamp returns a generic unavailable result. By default a balance older than 48 hours is withheld. Show the date on every successful balance screen, paginate as needed and use a short per-subscriber private cache only if provider quotas require it. Synthetic banking uses isolated fixture records and a lab-only access code. It shares neither storage nor credentials with the live mode.

### Caller identity and approval

Canonical caller ID from an enrolled gateway or trunk can resolve a candidate account using a keyed lookup of normalized numbers. It supplies no authentication factor. Public calls, withheld IDs, ambiguous mappings, untrusted routes and calls through shared/payphone terminal profiles are ineligible for real balances. Enroll the phone binding through an authenticated web session. Default deployment exposes private balance access only on an enrolled private SIP route, with protected signaling/media as supported and a controlled wired analog segment.

The opt-in single-operator loopback lab provides an isolated private InfoLine extension using the existing local enrollment and authenticated SIP endpoint. Account selection is restricted to the enrolled local owner and each call requires its own web approval. Its standalone display suppresses signal traces and clears at call termination. Production deployment and physical handset acceptance retain the qualified private route and endpoint requirements.

For real balances, the call presents a short-lived random challenge. The subscriber signs into the web enrollment portal, confirms the challenge and receives an eight-digit, single-use code bound to that subscriber and call. Enter it by handset keypad. Set a 120-second expiry, cap at three attempts per call and apply limits across subject and route. Verify a keyed digest and consume the approval atomically. End the private authorization at hangup, after 60 seconds of inactivity, when leaving the private flow or after 5 minutes, whichever comes first. An expired or revoked enrollment invalidates in-flight authorization before presentation. Clear the screen on exit where media remains available, and require physical verification of terminal retention before allowing real balances. Real balance audio is off by default. Treat all access digits as sensitive and suppress them in ARI debug, packet capture, tracing and support artifacts on that route.

Keep financial payloads out of call history, recordings, public graphs, simulator, exports and the assistant. Administrative views expose link state and audit outcomes. Disable a revoked link promptly and evict cached values. Start live validation with a Bridge demo account, then qualify any intended institution and endpoint with user consent before enabling a real account.

## Optional information assistant

The optional information assistant offers fixed topics and pre-authored questions through the keypad and softkeys, grounded in a curated public glossary. The adapter can use a configured HTTPS Chat Completions endpoint; without a model it presents the glossary text. It has a five-second timeout, bounded answers and shared request limits. The model receives only the chosen public question and vetted excerpt. Weather, market, lottery and banking results continue to use deterministic adapters.
