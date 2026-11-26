# ShadyBank telephone banking

ShadyBank is a separate ADSI application for ShadyBucks virtual member accounts. It does not use SimpleFIN, the public InfoLine graph or the CoinLine merchant payment interface. Dial **6508** from the authenticated lab SIP endpoint. The public emulator ingress on 2374 cannot reach this extension, and the emulator Compose overlay disables ShadyBank. The default is disabled everywhere.

## Telephone application

The caller enters their ShadyBucks card number and assigned member PIN, followed by Submit (`#`). Erase (`*`) removes the most recent digit or exits an empty entry. The phone displays neither the full card number nor the PIN. After login the member menu assigns the following six-position display softkeys, leaving the unused position blank:

| Key | Service |
| --- | --- |
| 1 | Balance, posted and available |
| 2 | History, up to ten recent posted transactions |
| 3 | Pending, unexpired holds |
| 4 | Send ShadyBucks to another member card |
| 0 | Exit and clear the display |

History and holds use the information area for actual records; Prev, Next, Detail and Back occupy the softkey positions. The transfer flow collects the recipient card and a positive amount in cents (`1250` means `SB 12.50`). The confirmation screen shows the recipient's last four digits and total. Send is a separate, acknowledged input step; Cancel posts nothing. A declined transfer displays a decline, a posted transfer displays its ledger reference, and an uncertain outcome instructs the caller to check activity before attempting another transfer. The client never automatically repeats a mutation.

The application uses the voice-between-screens ADSI profile by default. A screen must be acknowledged before its inputs can authorize an operation. The session is limited to five minutes; hangup, exit or loss of synchronization ends the session. Private emulator traces are hidden and the display clears on hangup. Card and PIN entry is only offered on an ADSI-compatible connection, not a voice fallback. The route is intended for a trusted controlled telephony environment; do not present actual payment-network card or PIN data or enable call recording on this route.

## Configuration and test modes

| Environment | Purpose |
| --- | --- |
| `ADSI_SHADYBANK_MODE` | `disabled` (default), `demo`, or `live` |
| `ADSI_SHADYBANK_URL` | HTTPS base URL of the ShadyBank member service in live mode |
| `ADSI_SHADYBANK_SERVICE_KEY` | Operator-supplied shared member service credential, at least 32 characters; not a merchant credential |
| `ADSI_SHADYBANK_INTERACTION_PROFILE` | `voice-between-screens` (default) or `continuous-data` for a separately qualified terminal |

The console telephony status shows the extension and configured mode, not the service credential. Set local environment values in the ignored `.env` file and recreate the app. For a disposable demonstration, use only the following synthetic accounts:

| Fixture | Card | PIN | Opening balance |
| --- | --- | --- | --- |
| Sender | `9000000000000001` | `123456` | SB 123.45 |
| Recipient | `9000000000000002` | `123456` | SB 42.00 |

The demo ledger is in memory and resets with the app process. It cannot access ShadyBank or any other real account. In an isolated lab, enable demo mode and run `PYTHONPATH=service python tests/live_shadybank.py`. This places an actual SIP call through Asterisk using the standalone emulator and verifies login, balance, cancellation, confirmed transfer, history, holds and exit. The normal verification workflow also rejects anonymous access to 6508.

## Live backend handoff

The upstream [ShadyBank member API proposal](https://github.com/Shadytel/shadybank/pull/7) supplies the dedicated member-service API, not merchant payment endpoints. Initialize a fresh database with the updated schema or, for an existing initialized instance, apply the additive `srv/data/member-services.sql` migration. Provision the same strong service credential as `SHADYBANK_MEMBER_SERVICE_KEY` in the bank and `ADSI_SHADYBANK_SERVICE_KEY` in InfoLine. Use a trusted HTTPS service endpoint. An operator assigns or rotates the member PIN using the bank's `src/provision_member_pin.py` utility with hidden terminal input; the PIN is hashed, and existing plaintext or unprovisioned PINs are not accepted. No bank database credentials are needed by InfoLine.

The bank authenticates the member and issues a short-lived scoped token. The token accesses only the member's balance, posted activity, pending holds and transfers from their own eligible account. The bank validates available and posted balances, locks both accounts, and commits the journal, balances and idempotency receipt together. The separate merchant API remains unchanged for call payment integration.

Before activating a live deployment, apply the migration, verify the service connection and key, provision test-only members, and repeat the balance, cancellation, transfer, recipient credit and history checks against that isolated bank instance. Qualify the terminal and trusted media path separately before serving members, including display clearing, non-recording configuration and actual softkey input. Software fixture and database tests do not constitute live bank or physical handset qualification.
