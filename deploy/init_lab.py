"""Create local lab configuration without printing credentials."""

import secrets
from pathlib import Path


root = Path(__file__).resolve().parents[1]
path = root / ".env"
values = {
    **{f"ADSI_{name}": secrets.token_hex(32) for name in
       ("SIP_PASSWORD", "ARI_PASSWORD", "ADMIN_PASSWORD", "DATABASE_PASSWORD", "DATABASE_ADMIN_PASSWORD", "DATA_KEY")},
    "ADSI_DEMO_PIN": f"{secrets.randbelow(10**8):08d}",
    "ADSI_NATIVE_MAIL_PIN": f"{secrets.randbelow(10**8):08d}",
}
try:
    with path.open("x", encoding="utf-8") as target:
        for name, value in values.items():
            target.write(f"{name}={value}\n")
except FileExistsError:
    existing = path.read_text(encoding="utf-8")
    known = {line.partition("=")[0].strip() for line in existing.splitlines() if "=" in line}
    missing = values.keys() - known
    if missing:
        with path.open("a", encoding="utf-8") as target:
            if existing and not existing.endswith("\n"):
                target.write("\n")
            for name in sorted(missing):
                target.write(f"{name}={values[name]}\n")
    print("Existing lab settings preserved.")
else:
    path.chmod(0o600)
    print("Created local lab configuration.")
