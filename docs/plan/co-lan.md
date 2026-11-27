# Dedicated central office LAN laboratory

The optional `compose.co-lan.yaml` instance admits one directly connected central office SIP peer by its exact private IPv4 source address. It is independent of the existing authenticated lab and loopback-only 2374 overlay. The named peer does not register or supply Digest credentials. This is a controlled laboratory, not a PSTN trunk or a public service. Do not combine the overlays.

Run `python deploy/init_lab.py` in a separate checkout/configuration directory. In the ignored `.env`, set `ADSI_CO_LAN_BIND` to the Linux host's private IPv4 address and `ADSI_CO_LAN_PEER` to the authorized CO's exact private IPv4 address. These are required, not CIDR ranges or wildcards. Use Compose 2.24.4 or later:

```sh
docker compose -f compose.yaml -f compose.co-lan.yaml --profile verify build gateway app terminal-emu
docker compose -f compose.yaml -f compose.co-lan.yaml --profile verify up -d --no-build --wait gateway app
```

The separate gateway includes the native voicemail and directory modules, NAT handling and the PJSIP IP identifier. Standard gateway and loopback emulator images are unchanged. The LAN profile advertises its configured host address in SIP and SDP, with UDP 5070 and RTP/RTCP 18200-18239 bound to that address. The operator console remains host-loopback TCP 8090. The CO must use its configured source IPv4 address, From user `co`, a live RTP socket, G.711 PCMU at 8000 samples/s, 20 ms packets and in-band DTMF. Use the SDP-negotiated port. No REGISTER or public PSTN fallback is needed. The default ADSI profile restores voice between interactive screens and sends fresh CAS before subsequent FSK; FDM stays in continuous data mode.

| Dial exactly | Service |
| --- | --- |
| 2374 or 6501 | Published InfoLine |
| 6500 | ADSI lab `LAB` / `Go` exchange |
| 6502 | Synthetic balance demonstration, generated lab PIN |
| 6503 | Resident feature lab, one-use approval required |
| 6505 | Native synthetic voicemail access, generated mailbox PIN |
| 6506 | Native visual directory for the synthetic mailbox |
| 6507 | Leave a message in the synthetic mailbox |
| 6508 | ShadyBank demo with synthetic accounts only |

6504, live SimpleFIN, live ShadyBank, arbitrary destinations and all other dial strings are excluded. The CO may translate explicitly provisioned local test numbers to these SIP extensions; keep those aliases free or locally rated without a PSTN fallback. Native voicemail/directory and resident-download behavior require a separate terminal qualification. The `ADSI_CO_LAN_FDM_ENABLE=1` setting permits resident downloads; the operator must then approve one specific download in Setup before dialing 6503. The approval is consumed on an attempt and must not be automatically recreated. Asterisk's native voicemail may offer its own resident service; use only the synthetic test mailbox and a disposable test terminal.

Use separate credentials and persistent database and mail volumes. The source IP restriction is not a substitute for encrypted or authenticated telephony on an untrusted network. Keep the web console private and do not enable real financial accounts in this profile.
