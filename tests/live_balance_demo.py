"""Verify the guarded synthetic balance and terminal clearing over SIP."""

import time

from live_api import lab_value
from live_sip_app import terminal


def main():
    code = lab_value("ADSI_DEMO_PIN", "")
    assert len(code) == 8 and code.isdecimal()
    with terminal("6502") as call:
        call.display("DEMO BALANCE", lines=["DEMO BALANCE", "Enter lab code", "", ""])
        wrong = "0" if code[0] != "0" else "1"
        for digit in wrong + code[1:]:
            call.press(digit)
        for digit in code:
            call.press(digit)
        call.display("DEMO BALANCE", lines=["DEMO BALANCE", "CAD 1234.56", "As of 07 Feb 2026", "0 Exit"])
        call.press("0")
        call.display("GOODBYE", lines=["GOODBYE", "", "", ""])
        assert call.process.wait(timeout=10) == 0
        assert [event["digit"] for event in call.trace if "digit" in event] == list("AD1D1D1D1D1")
    print("Verified the synthetic balance accepts a valid code after a wrong attempt and clears the terminal on exit.")
    with terminal("6501") as call:
        call.display("COINLINE INFOLINE")
        time.sleep(0.8)
        call.press("3")
        call.display("FINANCE")
        time.sleep(0.8)
        call.press("4")
        call.display("BANKING")
        time.sleep(0.8)
        call.press("1")
        call.display("DEMO BALANCE", lines=["DEMO BALANCE", "Enter lab code", "", ""])
        time.sleep(0.8)
        for digit in code:
            call.press(digit)
        call.display("DEMO BALANCE", lines=["DEMO BALANCE", "CAD 1234.56", "As of 07 Feb 2026", "1 Trans  0 Exit"])
        time.sleep(0.8)
        call.press("1")
        call.display("ACTIVITY 1/2")
        time.sleep(0.8)
        call.press("9")
        call.display("ACTIVITY 2/2")
        time.sleep(0.8)
        call.press("0")
        call.display("GOODBYE")
        assert call.process.wait(timeout=10) == 0
    print("Verified the Finance Banking menu, access-code prompts, and synthetic posted transactions.")


if __name__ == "__main__":
    main()
