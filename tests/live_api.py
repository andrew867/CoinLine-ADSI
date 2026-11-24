"""Exercise publishing, rollback and simulator isolation against the Compose lab."""

import json
import os
from pathlib import Path
from uuid import uuid4

import httpx


ROOT = Path(__file__).resolve().parents[1]
DATA = json.loads((ROOT / "fixtures/apps/weather.graph.json").read_text(encoding="utf-8"))


def lab_value(name, default=None):
    if name in os.environ:
        return os.environ[name]
    for raw in (ROOT / ".env").read_text(encoding="utf-8").splitlines():
        key, _, value = raw.partition("=")
        if key == name:
            return value
    return default


def main():
    port = lab_value("ADSI_WEB_PORT", "8080")
    with httpx.Client(base_url=f"http://127.0.0.1:{port}/api/v1", timeout=8,
                      headers={"X-Coinline-CSRF": "request"}, trust_env=False) as client:
        client.post("/session", json={"password": lab_value("ADSI_ADMIN_PASSWORD")}).raise_for_status()
        active = client.get("/routes").raise_for_status().json()[0]["revision_id"]
        original = None
        for item in client.get("/apps").raise_for_status().json():
            revisions = client.get(f"/apps/{item['id']}/revisions").raise_for_status().json()
            if any(revision["id"] == active for revision in revisions):
                original = item["id"]
                break
        assert original, "Run this test with a seeded active lab route."
        response = client.post("/apps", json={"name": f"Verification {uuid4().hex[:8]}", "graph": DATA}).raise_for_status()
        base = f"/apps/{response.json()['id']}"
        previous_generation = response.headers["etag"]
        first = client.post(base + "/revisions", headers={"If-Match": previous_generation},
                            json={"routes": ["infoline"]}).raise_for_status().json()
        try:
            changed = json.loads(json.dumps(DATA))
            changed["nodes"][0]["lines"][0] = "REVISED"
            write = {"graph": changed}
            response = client.put(base + "/draft", headers={"If-Match": previous_generation}, json=write)
            response.raise_for_status()
            generation = response.headers["etag"]
            assert client.put(base + "/draft", headers={"If-Match": previous_generation}, json=write).status_code == 412
            second = client.post(base + "/revisions", headers={"If-Match": generation},
                                 json={"routes": ["infoline"]}).raise_for_status().json()
            assert second["id"] != first["id"]
            client.post(base + "/activate", json={"revision": first["id"], "routes": ["infoline"]}).raise_for_status()
            assert client.get("/routes").raise_for_status().json()[0]["revision_id"] == first["id"]
            assert client.get(base + "/export", params={"revision": first["id"]}).raise_for_status().json() == DATA
            assert client.post(base + "/archive", json={"disable_routes": False}).status_code == 409
            session = client.post("/simulations", json={"graph": changed, "fault": "stale"}).raise_for_status().json()
            assert session["lines"][0] == "REVISED"
            endpoint = f"/simulations/{session['id']}/events"
            session = client.post(endpoint, json={"digit": "1"}).raise_for_status().json()
            assert session["lines"][0] == "STALE DEMO WX"
        finally:
            client.post(f"/apps/{original}/activate", json={"revision": active, "routes": ["infoline"]}).raise_for_status()
            client.post(base + "/archive", json={"disable_routes": False}).raise_for_status()
        print("Verified revision publish, stale edit rejection, rollback, archive routing, export and simulator.")


if __name__ == "__main__":
    main()
