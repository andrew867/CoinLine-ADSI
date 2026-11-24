"""Hold ten real SIP calls and verify a controlled busy response for the next one."""

from contextlib import ExitStack

import httpx

from check_admission import check
from live_api import lab_value
from live_sip_app import terminal


def main():
    port = lab_value("ADSI_WEB_PORT", "8080")
    with httpx.Client(base_url=f"http://127.0.0.1:{port}/api/v1", timeout=8,
                      headers={"X-Coinline-CSRF": "request"}, trust_env=False) as client:
        client.post("/session", json={"password": lab_value("ADSI_ADMIN_PASSWORD")}).raise_for_status()
        status = client.get("/telephony/status").raise_for_status().json()
        assert status["active"] == 0
        with ExitStack() as stack:
            calls = []
            for _ in range(5):
                pair = [stack.enter_context(terminal()) for _ in range(2)]
                for call in pair:
                    call.display("COINLINE INFOLINE", timeout=20)
                calls.extend(pair)
            try:
                before = client.get("/telephony/status").raise_for_status().json()
                assert before["active"] == 10
                check([], "6501", {486})
                after = client.get("/telephony/status").raise_for_status().json()
                assert after["active"] == before["active"]
                assert after["outcomes"]["busy"] == before["outcomes"].get("busy", 0) + 1
            finally:
                for call in calls:
                    call.press("hangup")
    print("Verified ten simultaneous SIP calls and a controlled busy response for call eleven.")


if __name__ == "__main__":
    main()
