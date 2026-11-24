# Synthetic fixture manifest

| Path | Used by | Scenario and oracle |
| --- | --- | --- |
| [Wire vectors](wire/vectors.json) | T01, T02, T06, T21 | Hex bytes derived from the Asterisk encoder layouts. Valid frames carry expected parameter lengths and semantics. Invalid frames distinguish corrupted checksum, outer length, a rechecksummed TLV boundary error and an unsupported tag. |
| [Single-softkey scenario](scenarios/single-softkey.json) | T06 | Required SIP/RTP event order. The sample terminal sends the required capability and link acknowledgments. The softkey returns one digit, the screen changes to `OK`, and voice resumes. A named device profile can require a separate mode callback. |
| [Weather application graph](apps/weather.graph.json) | T11, T12 | A graph-schema example with success, unavailable, return and timeout transitions. Enter `1`, render the provider result, enter `0` to return and enter `0` again to exit. |
| [Weather provider examples](providers/weather.json) | T13, T17 | Fixed-clock fresh, stale and unavailable results for a synthetic site. Temperature, source time and demo labels remain visible across display and voice. |

The source for framing is the [Asterisk 22 server interface](../docs/sources.md#s2-adsi-server-reference). These vectors contain no preamble or analog measurements. The full scenario includes signaling boundaries and illustrative terminal behavior. Hardware tests obtain actual timing and acknowledgment sequences from the device.

Future provider fixtures cover per-game draw formats, delayed/EOD quotes, Bridge demo account schemas and quota responses. Keep source permission records with any attributed provider examples. Use synthetic values for checked-in identity, enrollment, account, quote and draw examples.
