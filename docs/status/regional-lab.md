# Canadian InfoLine verification

Local lab qualification, 2026-11-24.

| Gate | Observed result |
| --- | --- |
| R01 | Imported 28,613 in-service Canadian CO-code assignments from the CNA ZIP. The synthetic shared-NPA fixtures resolved separate provinces. |
| R02 | Live ECCC current conditions and forecast returned from the app container. The standalone web terminal supplied a synthetic caller identity, presented the inferred exchange area, and displayed current weather after confirmation. |
| R03 | Global News, NTV, VOCM and Headlinefeed financial and biotech queries returned data. The standalone web terminal displayed financial news, biotech news and VOCM headlines. CBC top stories and Newfoundland RSS timed out from the lab. |
| R04 | Twelve Data returned a quote and Alpha Vantage supplied the end-of-day fallback. The SIP terminal traversed the stock sector and symbol menus and displayed the dated stale quote label. Mocked concurrent requests reused the hourly cache; quota accounting persisted across a cache reopen. |
| R05 | Validated 13 lottery parsing cases using independently retrieved ALC, Loto-Québec, WCLC and PlayNow responses. Live app retrieval succeeded for ALC Lotto Max, 6/49, Daily Grand and Atlantic 49, Loto-Québec 49, Western 649, Western Max, and WCLC national Lotto Max. The SIP terminal displayed national Lotto Max and Atlantic 49. PlayNow regional requests timed out from the Docker environment; parsers were checked against independently retrieved responses. The OLG feed returned HTTP 401. |
| R06 / T09 | Rebuilt the minimal gateway and native reference with `res_pjsip_caller_id`. Installed/loaded module allowlists matched. Native Asterisk and CoinLine exchanges decoded successfully in the standalone emulator over SIP/RTP with voice recovery. The independent reserved-number fixture selected its mapped city through authenticated SIP. |
| R07 | The live SIP test accepted the lab PIN after an incorrect attempt and cleared the terminal. The Finance menu opened the demo balance and two synthetic transaction screens. SimpleFIN account/date filters and connection binding passed mocked tests. Live institution validation is pending. |
| R08 | The existing unedited sample received a new published revision and retained its previous revision. Live revision pinning, publishing, stale-edit rejection, rollback, archive routing, export and simulator checks passed. The public cache persisted across app restarts. |

The source and schema suite passed 34 tests. The documentation link, requirement coverage, graph schema and wire fixture check passed. The regional app and minimal Asterisk images built and the local Compose services reported healthy. The separate terminal web interface returned HTTP 200 and accepted the synthetic caller ID control. A scan of tracked and unignored project files found none of the local provider credential values.

Remaining live gates are CBC and PlayNow network availability, supported OLG access and ENCORE mapping, supplemental lottery products, the territorial catalogue, real-account SimpleFIN enrollment, and the independent physical handset qualification for each supported terminal. Refer to the [provider catalogue](../spec/regional-providers.md) for current integration coverage.

## SimpleFIN enrollment follow-up

The official Bridge demonstration token was claimed through the authenticated local web enrollment endpoint. Three account choices were recovered from encrypted pending storage after an actual app container restart. Account linking and the read-only connection test succeeded, including ten recent posted transactions. The demo balance timestamp was in the future and was explicitly identified by the inspection response. The telephone freshness gate remains unchanged. The demo enrollment was unlinked after testing. The regression suite passed 36 tests, including recovery after an account-discovery failure following a successful claim. Paid-account enrollment and private SIP qualification remain pending.
