# Local lab results

## Clean software exchanges

- The CoinLine SIP path carried PCMU with in-band DTMF. The standalone terminal received CAS, sent `A`, acknowledged the connect, `LAB` with `Go`, `OK` and release frames, then received voice audio. Withholding `A` selected the voice and keypad flow.
- The T09 comparison decoded the native Asterisk 22.12.0 connect, `LAB` and release frames as `8405018e00860062`, `840d0182070140ff4c4142ff83010152` and `840601850087010068` over SIP/RTP. The terminal sent `A` and three `D1` replies and received post-release audio. Seeded downlink jitter and a deterministic spill packet drop preserved validated delivery in the recorded runs. The native harness pads partial PCMU writes with silence before RTP packetization.
- The compiled union and packaged and running module inventories matched their allowlists. The gateway loads 33 modules and the isolated native reference loads 18.
- The uplink test delivered all 16 DTMF symbols exactly once. Asterisk reported zero remaining channels after hangup. The lab also rejected invalid authentication and an unassigned destination.
- The stale `D1` regression withheld the first acknowledgment, confirmed the retry and then injected the old reply. The server ended the ambiguous exchange without sending a new map or accepting an action.
- The independent PCM decoder verified the expected display bytes with seeded noise and clipping. It withheld the display when given an invalid checksum or a missing 20 ms media frame.
- The console browser test imported and edited a graph, exercised its simulated weather and hangup, and archived the test application. The PostgreSQL API checks covered stale-generation rejection, publish, rollback, archive, export and fixture errors. Two real SIP calls verified that the first stayed on its original revision after the second received a new one.
- The separate terminal controller dialed over SIP, displayed `LAB` and its active `Go` key, displayed `OK` after the key was pressed and cleared the key map.
- The ECCC adapter parsed a live observation using the official site catalogue. SimpleFIN Bridge's synthetic backend returned balances through the balances-only adapter.
- The synthetic SIP balance required a valid PIN after an incorrect entry and cleared the display on exit. Input digits were excluded from the terminal trace.
- The standalone terminal accepted and acknowledged the resident records in order, committed the slot and read the same slot after restarting. A direct-PCM incomplete replacement preserved the earlier committed feature.
- A backup encrypted with age restored six synthetic revisions and one route to a separate verification database. The restore check took 11 seconds on the local lab.

## Capacity and recovery

The local Docker Engine 29.9.2 exposed eight CPUs and 16,573,423,616 bytes of memory. Ten persistent standalone SIP clients made ten consecutive calls each using PCMU and in-band DTMF. The gateway admitted and closed all 100 calls, the terminal verified every exchange and zero calls remained active. The 100 measured menu-to-service-dispatch samples had a nearest-rank p95 of 1.1 ms.

The overload exercise held ten InfoLine calls. Call eleven received SIP 486 Busy and the ten admitted sessions stayed connected.

The app and PostgreSQL restarted with the same published route. In a separate Compose stack, digest promotion passed a SIP canary, a deliberately failing candidate triggered rollback, and a new SIP call passed on the restored image pair.

## External qualification

Vista 350 and ADSI-capable Millennium each require a separate T20 physical result. Physical resident features and Millennium graphics remain unqualified. Live news, market and lottery feeds require approved sources. Real balance access requires an enrolled private route, the institution and a terminal retention check.

The public repository has GitHub verification, release and promotion workflows. Release publication and staging or production qualification require provisioned target environments.
