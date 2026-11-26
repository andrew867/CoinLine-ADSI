# Newfoundland and Labrador travel information

## Menus and scope

More Services > Travel contains Roads, Ferries and Transit. Existing Flights, Directory, Movies and Parcels numeric selections remain unchanged. The optional information assistant moves into the Travel menu, and Weather gains Alerts. Newly seeded applications use the updated immutable revision; unedited built-in applications upgrade, while operator-edited drafts and published revisions are preserved.

All screens use the information viewport and fixed paging controls. The caller selects a report, reads the source and observation timestamp, then returns or selects another report. Device protocol, session authentication, native Asterisk comparison and physical qualification gates are unchanged.

## NL511

The [official developer documentation](https://511nl.ca/developers/doc) describes the following read-only APIs:

| Service | Endpoint | Selection |
| --- | --- | --- |
| [Road conditions](https://511nl.ca/help/endpoint/winterroads) | `api/v3/get/winterroads` | Region, area, road segment |
| [Events](https://511nl.ca/help/endpoint/event) | `api/v2/get/event` | All NL, or events within 100 km of an inferred NL city |
| [Advisories](https://511nl.ca/help/endpoint/alerts) | `api/v2/get/alerts` | Select report; distinguish an empty valid response from an unavailable feed |
| [Ferries](https://511nl.ca/help/endpoint/ferryterminals) | `api/v2/get/ferryterminals` | Ferry service, terminal, reported status and vessel |

Set `ADSI_REGIONAL_ENABLE=1` and `ADSI_NL511_KEY` in the ignored deployment environment. The presence of a credential enables NL511 by default; the operator setting `nl511` can explicitly override it. The feed limits requests to ten per 60 seconds. InfoLine uses a shared eight-per-minute budget and caches normalized reports for five minutes, with no fallback to older cached reports when an update fails. Provider geometry and URLs are omitted from cached handset records. Source timestamps are presented in UTC; reports older than 48 hours are marked as older reports rather than interpreted as current driving conditions. An empty events feed is not evidence that all roads are safe.

The ferry feed includes Marine Atlantic crossings and provincial terminals. It reports operational status, vessel, and provider schedule name where available. It does not establish exact scheduled sailing times. The separate Marine Atlantic booking/sailing integration is deferred; no bearer token or booking information is used or stored. Camera image delivery and undocumented wind-warning endpoints are also deferred.

## Weather alerts

The [ECCC GeoMet weather-alerts feature collection](https://eccc-msc.github.io/open-data/msc-data/alerts/readme_alerts-geomet_en/) is queried for alerts intersecting the confirmed city's coordinates. The location is a city point resolved through ECCC, not the caller's physical position. Filter expired and ended records, retain the published event name and risk colour, display source/expiry where supplied, and select individual active alerts. A provider failure is not described as no alerts. Long alert text is bounded for a telephone display and explicitly directs the caller to the source website for the full text. Cache lifetime is two minutes; do not present expired cached alerts.

Weather alerts are enabled with regional feeds by default, with the `weatherAlerts` operator override. The service is an informational supplement to official alert channels, not a replacement for emergency notifications.

## Metrobus Transit

The operator's public service-bulletin feed returns JSON without authentication. Service reports show their post date, headline and details. The live vehicle, route-stop and stop-departure endpoints returned HTTP 403 during direct server probes and remain unintegrated. No browser session material is used.

The [official Metrobus GTFS download and data terms](https://www.metrobus.com/gtfs.asp) offer scheduled transit data. The operator must accept the licence before enabling automatic downloads. The adapter implements the [GTFS schedule reference](https://gtfs.org/documentation/schedule/reference/) for stops, short route names, trips, stop times, service calendars/exceptions and departures after midnight. It uses Newfoundland local time, rejects unsupported frequency services, and distinguishes scheduled departures from real-time predictions.

The required source notice is available in the handset Transit > About screen:

> Data used in this product or service is provided by Metrobus Transit, however Metrobus Transit assumes no responsibility for the accuracy or currency of the Data used in this product or service.

Enable `ADSI_METROBUS_ENABLE=1` and, once the operator accepts the licence, `ADSI_METROBUS_GTFS_ACCEPTED=1`. The application uses the official schedule URL in the regional catalogue. It downloads into the provider cache (`metrobus.zip`), validates the entire archive and current service range before atomically replacing the prior file, and refreshes after six days to meet the weekly update requirement. Failed refreshes are retried at most hourly; a file older than seven days is unavailable. An operator-managed `ADSI_METROBUS_GTFS_PATH` can instead point to a local accepted archive. No raw schedule archives are tracked in Git. `metrobus` in the provider settings overrides live activation.

The stop-input screen accepts the public numeric stop code and Submit. Route selection accepts a numeric route or a paged route list, then a stop code served by that route or a paged stop list. The next six scheduled departures are displayed, including the local time and destination. An expired feed is unavailable, not a fabricated timetable. Demo mode uses synthetic route 9 and stop 9000. Public or paid deployment must remain consistent with the provider's data licence.

## Acceptance

- Verify normalized NL511 road, event, advisory, and ferry records; empty versus unavailable; shared request budget; and source timestamps.
- Verify ECCC point intersection, expiration, stable alert identity and incomplete-feed rejection.
- Verify Metrobus bulletin response, GTFS ZIP validation, calendar exceptions, no-pickup stops, route-stop binding, overnight service, stale file rejection and automatic refresh.
- Verify stop input in the fixture simulator, continuous SIP, and voice-between-screens integration without changing ACK deadlines.
- Requalify the graphical terminal profile separately; these software tests do not establish a physical handset badge.

On 26 November 2026, the read-only live probes returned 156 road sections, 26 road events, an empty advisory list, 49 ferry terminals and five transit bulletins. The ECCC point query for St. John's returned no active alerts. With operator consent, the published Metrobus GTFS archive was downloaded and parsed: 923 stop records, 23 route records, 1,808 trips and 65,257 stop-time records. Stop 1150 and route 21 selection, and scheduled departures for that stop, were verified using that archive. These are observations from that probe, not permanent network or timetable counts.
