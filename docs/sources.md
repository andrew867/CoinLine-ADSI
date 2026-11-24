# Source and evidence register

The protocol contract names the reference implementation for each initial behavior. The gateway and native reference use Asterisk 22.12.0 with its bundled SIP libraries. The standalone terminal uses PJPROJECT 2.16 and Debian Bookworm SpanDSP 0.0.6+dfsg-2+b1. The Dockerfiles verify the downloaded source archives by SHA-256. Keep public reference links with sanitized evidence. Cite the original source of a waveform or value, and label a synthetic fixture as such.

## S1 Asterisk, PJSIP, ARI and media

- The project release table identifies the 22 series as LTS. The channel driver guide describes binary PCM, bidirectional media, framing and flow-control messages. Its version notes identify the release floor for the required WebSocket options. [Supported series](https://docs.asterisk.org/About-the-Project/Asterisk-Versions/) · [PJSIP configuration](https://docs.asterisk.org/Configuration/Channel-Drivers/SIP/Configuring-res_pjsip/) · [WebSocket driver](https://docs.asterisk.org/Configuration/Channel-Drivers/WebSocket/) · [ARI external media](https://docs.asterisk.org/Latest_API/API_Documentation/Asterisk_REST_Interface/Channels_REST_API/#externalmedia)
- The documented TCP alternative is AudioSocket, with explicit framing and 8 kHz PCM support. RTP media mappings and negotiated telephone events come from their respective RFCs. [AudioSocket](https://docs.asterisk.org/Configuration/Channel-Drivers/AudioSocket/) · [RFC 3551](https://www.rfc-editor.org/rfc/rfc3551.html) · [RFC 4733](https://www.rfc-editor.org/rfc/rfc4733.html)
- Menuselect controls compilation and the module loader controls what loads at runtime. The Asterisk 22 sources declare the direct dependencies of the SIP, Stasis and WebSocket modules. [Menuselect](https://docs.asterisk.org/Getting-Started/Installing-Asterisk/Installing-Asterisk-From-Source/Using-Menuselect-to-Select-Asterisk-Options/) · [Module loader](https://docs.asterisk.org/Configuration/Core-Configuration/Configuring-the-Asterisk-Module-Loader/) · [chan_pjsip](https://github.com/asterisk/asterisk/blob/22/channels/chan_pjsip.c) · [app_stasis](https://github.com/asterisk/asterisk/blob/22/apps/app_stasis.c) · [chan_websocket](https://github.com/asterisk/asterisk/blob/22/channels/chan_websocket.c)

## S2 ADSI server reference

- Asterisk 22 supplies operational source for CAS, message generation, display encoders, DTMF timing and separate SDC and FDM operations. Its ADSI modules are marked deprecated by the project. Use them as compatibility comparators without making the new gateway depend on those modules at runtime. [res_adsi.c](https://github.com/asterisk/asterisk/blob/22/res/res_adsi.c) · [adsi.h](https://github.com/asterisk/asterisk/blob/22/include/asterisk/adsi.h) · [callerid.c](https://github.com/asterisk/asterisk/blob/22/main/callerid.c) · [app_adsiprog.c](https://github.com/asterisk/asterisk/blob/22/apps/app_adsiprog.c) · [Current compiler development](https://github.com/asterisk/asterisk/blob/master/apps/app_adsiprog.c) · [Asterisk sample script](https://github.com/asterisk/asterisk/blob/22/configs/samples/telcordia-1.adsi)
- The AST Tech Labs November 1997 summary covers CLASS and ADSI signalling and is vendor guidance. The ePanorama page supplied with the project describes caller ID and does not establish the SDC preamble. [AST signalling summary](https://siliconpr0n.org/media/camac/1/Cladres3.pdf#page=5) · [Caller ID background](https://www.epanorama.net/documents/telecom/cid_bellcore.html)
- ETSI ES 201 071 V1.1.2, §4.2 and Annexes A and B, identifies SR-INS-002461 and TR-NWT-001273 as the Bellcore baselines and tabulates European changes. EN 300 659-2 V1.3.1, Sections 5 and 6, covers European off-hook data transmission. The full Bellcore documents were unavailable for this baseline. [ETSI SDSS](https://www.etsi.org/deliver/etsi_es/201000_201099/201071/01.01.02_60/es_201071v010102p.pdf) · [European off-hook transmission](https://www.etsi.org/deliver/etsi_en/300600_300699/30065902/01.03.01_60/en_30065902v010301p.pdf)
- Ameritech AM-TR-NIS-000118 is cited as a feature-download and transmission requirement in the bibliography of AM-TR-NIS-000112. A verified full copy of 000118 was unavailable for this baseline. [Ameritech reference, printed p. 6](https://device.report/m/caac3adcbdeb10e107332deb7de3f2cb7af8a32ad180e94301a98383816671da.pdf)

## S3 SpanDSP

The upstream source shows Bell 202 for the CLASS profile and separate configurations for other profiles. Select and test the FSK primitives independently of any built-in caller-ID framing. Review the exact release license, public header use and binary distribution obligations when pinned. [SpanDSP ADSI](https://github.com/freeswitch/spandsp/blob/master/src/adsi.c) · [SpanDSP FSK](https://github.com/freeswitch/spandsp/blob/master/src/fsk.c)

## S4 PJPROJECT

PJSUA2 provides a SIP client and media ports for injecting and receiving audio frames. Confirm linked dependency and distribution compatibility for the terminal executable before distribution. [Audio ports](https://docs.pjsip.org/en/latest/specific-guides/audio/audio_frame_manipulation.html) · [PJPROJECT license](https://docs.pjsip.org/en/latest/overview/license_pjsip.html)

## S5 Authoring and historical deployments

Blueworx documents live server display control and resident overlay authoring. Its Voice Response help indexes the banking server state table, the `adsicb.sdc` sample and FDM statement examples. The supplied direct sample URL failed during source verification. The Sayson configurator reference showed a browser verification gate and serves as a historical lead. [Blueworx ADSI support](https://docs.blueworx.com/BVR/InfoCenter/V6.1/AIX/help/topic/com.ibm.wvraix.geninf.doc/analogdisplayservicesinterface72.html) · [Blueworx help index](https://docs.blueworx.com/BVR/InfoCenter/V6.1/AIX/help/index.jsp) · [Sayson document lead](https://www.yumpu.com/en/document/view/40520732/sayson-390-480-adsi-phones-asterisk-web-configurator)

## S6 Handsets and resident features

- Nortel's Vista 350 guide documents the user interface. NISTIR 5585, printed p. 6-9, identifies the Vista 350 LCD and historical DES capability for the validated product. The latter is historical evidence only. [Nortel user guide](https://telephonecollectors.info/index.php/browse/catalogs-manuals-educational-docs-by-company/northern-electric/14857-nortel-po748074-i2-1994-vista-350-telephone-user-guide/file) · [NISTIR 5585](https://nvlpubs.nist.gov/nistpubs/Legacy/IR/nistir5585.pdf)
- Nortel patents disclose examples of screenphone script storage and processing, resident voicemail event behavior, and receipt of graphical payloads by a payphone. Disclosed designs do not demonstrate the behavior of either target on the planned lab path. [US5615257](https://patents.google.com/patent/US5615257A/en) · [US6337898](https://patents.google.com/patent/US6337898B1/en) · [US6163598](https://www.freepatentsonline.com/6163598.html)

## S7 Weather and numbering

- MSC documents the city forecast dataset, format, site codes, update cadence and access conditions. [MSC City Page Weather](https://eccc-msc.github.io/open-data/msc-data/citypage-weather/readme_citypageweather_en/) · [Datamart XML](https://eccc-msc.github.io/open-data/msc-data/citypage-weather/readme_citypageweather-datamart_en/)
- The Canadian Numbering Administrator publishes code assignments in HTML and CSV. The project derives a site suggestion from the assignment and a separate curated map. [CO code definition](https://www.cnac.ca/co_codes/co_codes.htm) · [Assignment status](https://www.cnac.ca/co_codes/co_code_status.htm)

## S8 News, market and lottery

- Reuters Connect describes a licensable news and API service. Price and usage rights require the actual provider agreement. [Reuters product](https://reutersagency.com/content-delivery-platforms/reuters-connect/)
- TMX distinguishes licensed redistribution and use arrangements. A usable unauthenticated web quote is not evidence of telephone redistribution rights. [TSX market data agreement example](https://www.tsx.com/en/resource/2908/)
- ALC directs users to its published winning numbers and official verification channels. No authorized machine feed was established for this project. [ALC checking and verification](https://www.alc.ca/content/alc/en/corporate/are-you-a-winner/buying-and-checking-your-tickets.html) · [ALC terms](https://www.alc.ca/content/alc/en/legal/terms-and-conditions.html)

## S9 SimpleFIN

The open protocol defines the one-time claim, HTTP Basic credentials, account scoping, `balances-only`, decimal-string amounts, `balance-date`, and optional available balance. Bridge documentation provides a synthetic connection and user revocation. Institutional coverage, quotas and contract terms are installation-specific. [SimpleFIN protocol v2](https://github.com/simplefin/simplefin.github.com/blob/master/protocol.md) · [Bridge developer guide](https://bridge.simplefin.org/info/developers)

## S10 Packaging and delivery

Compose documents health-aware dependency startup. Docker documents how image registry exports retain SBOM and provenance attestations. [Compose startup ordering](https://docs.docker.com/compose/how-tos/startup-order/) · [Docker build attestations](https://docs.docker.com/build/metadata/attestations/) · [GitHub container publishing](https://docs.github.com/en/actions/tutorials/publish-packages/publish-docker-images)
