# InfoLine data and access

## Public information service

The welcome screen reads `COINLINE INFOLINE`. Its numerically equivalent softkeys are `1 News`, `2 Wx`, `3 Stocks` and `4 Lotto`; `0 Exit` ends the call. Weather and lottery use a location prompt. Detail screens use paging and a return path. The optional assistant appears on a later menu page when enabled. Private banking has a dedicated entry route and authentication flow.

| Operation | Initial output | Source and activation |
| --- | --- | --- |
| `weather.current` and `weather.forecast` | City, temperature and observation time, or forecast period and issuance time. Keep warnings distinct from routine forecasts and preserve their issue/expiry state. | ECCC MSC City Page Weather via Datamart, English XML and a configured site catalogue. |
| `news.headlines` | Paged publisher-attributed headlines with publication times and optional licensed short descriptions. | Fixture feed at first. Licensed publisher RSS/API or a contracted source such as Reuters Connect. Approve text display, audio reading and cache rights before activation. |
| `market.quote` | Allowlisted symbol, exchange, price, currency, source quote timestamp and feed delay or EOD status. | Fixture watchlist at first. A Canadian-market feed with rights for the selected telephone use. Record the provider's claimed delay independently of the computed age. |
| `lottery.draw` | Operator, game, draw date, ordered numbers and separately labeled bonus fields. Optional digit entry compares a caller's selected numbers against a particular published draw. Treat the result as an informational comparison and direct callers to official ALC verification. | ALC is the initial operator. Use synthetic data or an authorized, attributable manual import until an approved feed exists. Keep tickets, barcodes, identity and claims out of the flow. |

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

Use periodic refresh and request coalescing. Keep provider limits, redistribution rights, supported markets/games, source fields and expected update schedule in provider configuration. Normalize content before display, cap size and reject malformed inputs. Use a fixed public message when a source is unavailable. Demo data is labeled on every affected screen and voice response.

## SimpleFIN balance service

The web-enrolled user connects an account in SimpleFIN Bridge, submits a one-time Setup Token through the authenticated enrollment page and chooses which account aliases may be presented. Claim the token server-side once. Validate both the returned Access URL and the decoded claim URL against configured HTTPS Bridge hosts and path roles. Use explicit TLS verification, fixed egress policy and disabled redirects. Keep access credentials in encrypted storage with a separately managed key. Offer token revocation and re-enrollment. A lost claim response requires a new token where claim success cannot be established. Limit request frequency to the configured provider budget and coalesce overlapping reads. [SimpleFIN protocol and Bridge](../sources.md#s9-simplefin)

Use `GET /accounts` with `version=2` and `balances-only=1` on the approved Access URL. Bind selections to subscriber, connection ID and source account ID. Parse amounts as decimal strings, preserve sign and currency, and display the source balance time. Present available balance as a separate field only when supplied. Show its label explicitly. A source-revoked token, partially failed response for the requested account, unexpected account, malformed amount or absent balance timestamp returns a generic unavailable result. By default a balance older than 48 hours is withheld. Show the date on every successful balance screen, paginate as needed and use a short per-subscriber private cache only if provider quotas require it. Synthetic banking uses isolated fixture records and a lab-only access code. It shares neither storage nor credentials with the live mode.

### Caller identity and approval

Canonical caller ID from an enrolled gateway or trunk can resolve a candidate account using a keyed lookup of normalized numbers. It supplies no authentication factor. Public calls, withheld IDs, ambiguous mappings, untrusted routes and calls through shared/payphone terminal profiles are ineligible for real balances. Enroll the phone binding through an authenticated web session. Default deployment exposes private balance access only on an enrolled private SIP route, with protected signaling/media as supported and a controlled wired analog segment.

For real balances, the call presents a short-lived random challenge. The subscriber signs into the web enrollment portal, confirms the challenge and receives an eight-digit, single-use code bound to that subscriber and call. Enter it by handset keypad. Set a 120-second expiry, cap at three attempts per call and apply limits across subject and route. Verify a keyed digest and consume the approval atomically. End the private authorization at hangup, after 60 seconds of inactivity, when leaving the private flow or after 5 minutes, whichever comes first. An expired or revoked enrollment invalidates in-flight authorization before presentation. Clear the screen on exit where media remains available, and require physical verification of terminal retention before allowing real balances. Real balance audio is off by default. Treat all access digits as sensitive and suppress them in ARI debug, packet capture, tracing and support artifacts on that route.

Keep financial payloads out of call history, recordings, public graphs, simulator, exports and the assistant. Administrative views expose link state and audit outcomes. Disable a revoked link promptly and evict cached values. Start live validation with a Bridge demo account, then qualify any intended institution and endpoint with user consent before enabling a real account.

## Optional information assistant

First implementation offers fixed topics and pre-authored questions through the keypad and softkeys, grounded in a curated public reference set. A provider interface permits local or hosted models. Use a bounded excerpt budget, total timeout of 5 seconds, one in-flight request per call and a deployment-wide quota. Return an answer of at most two terminal pages with a short human-readable source label and a fallback when evidence or the provider is unavailable. The assistant receives the chosen public topic and vetted excerpts. Treat imported content as data, disable tool execution and reject output that fails the response schema or source allowlist. Extend to opted-in speech only after source rights, privacy and transcripts are reviewed. Use deterministic weather, market, lottery and banking adapters for numeric results.
