"""Check the documentation baseline without a gateway or live feeds."""

import json
import re
from datetime import datetime, timedelta
from pathlib import Path
from urllib.parse import unquote, urlsplit

from jsonschema import Draft202012Validator


ROOT = Path(__file__).resolve().parents[1]
FRAME_TAGS = {
    0x84: {0x80, 0x81, 0x82, 0x83, 0x85, 0x86, 0x87, 0x88, 0x8E, 0x94},
    0x85: {0x80, 0x81, 0x82, 0x83, 0x84},
}


def read_json(path):
    return json.loads((ROOT / path).read_text(encoding="utf-8"))


def check_links():
    pages = [ROOT / "README.md", *ROOT.glob("docs/**/*.md"), *ROOT.glob("fixtures/**/*.md")]
    for page in pages:
        content = page.read_text(encoding="utf-8")
        for link in re.findall(r"\]\(([^)]+)\)", content):
            target = urlsplit(link)
            if target.scheme or target.netloc:
                continue
            linked = page.parent / unquote(target.path) if target.path else page
            assert linked.is_file(), (page.name, link)
            if target.fragment:
                headings = re.findall(r"^#+ (.+)$", linked.read_text(encoding="utf-8"), re.M)
                anchors = {re.sub(r"[^\w -]", "", heading.lower()).replace(" ", "-") for heading in headings}
                assert unquote(target.fragment) in anchors, (page.name, link)


def check_coverage():
    requirements = (ROOT / "docs/spec/requirements.md").read_text(encoding="utf-8")
    tests = (ROOT / "docs/test/verification.md").read_text(encoding="utf-8")
    ids = re.findall(r"^\| ([A-Z]+-\d\d) \|", requirements, re.M)
    rows = re.findall(r"^\| (T\d\d) \| ([^|]+) \|", tests, re.M)
    covered = {item.strip() for _, cells in rows for item in cells.split(",")}
    assert len(ids) == len(set(ids))
    assert set(ids) == covered, (set(ids) - covered, covered - set(ids))
    assert [case for case, _ in rows] == [f"T{index:02}" for index in range(1, 33)]


def wire_lengths(frame):
    if len(frame) < 4 or frame[1] != len(frame) - 3:
        raise ValueError("length")
    if sum(frame) % 256:
        raise ValueError("checksum")
    assert frame[2] == 1
    body = frame[3:-1]
    lengths = []
    while body:
        if len(body) < 2 or len(body) < 2 + body[1]:
            raise ValueError("parameter-length")
        tag, length = body[:2]
        if tag not in FRAME_TAGS[frame[0]]:
            raise ValueError("unsupported-tag")
        lengths.append(length)
        body = body[2 + length :]
    return lengths


def check_wire():
    vectors = read_json("fixtures/wire/vectors.json")
    for vector in vectors["valid"]:
        assert wire_lengths(bytes.fromhex(vector["hex"])) == vector["parameterLengths"], vector["id"]
    for vector in vectors["invalid"]:
        try:
            wire_lengths(bytes.fromhex(vector["hex"]))
        except ValueError as error:
            assert str(error) == vector["reject"], vector["id"]
        else:
            raise AssertionError(f"{vector['id']} was accepted")
    scenario = read_json("fixtures/scenarios/single-softkey.json")
    assert {event["frame"] for event in scenario["expects"] if "frame" in event} <= {
        vector["id"] for vector in vectors["valid"]
    }


def check_graph_and_provider():
    schema = read_json("docs/spec/graph.schema.json")
    graph = read_json("fixtures/apps/weather.graph.json")
    Draft202012Validator.check_schema(schema)
    Draft202012Validator(schema).validate(graph)
    fixture = read_json("fixtures/providers/weather.json")
    clock = datetime.fromisoformat(fixture["testClock"])
    for response in fixture["responses"]:
        assert datetime.fromisoformat(response["fetchedAt"]) <= clock
        if response["status"] == "unavailable":
            assert response["dataTime"] is None and "value" not in response
            continue
        age = clock - datetime.fromisoformat(response["dataTime"])
        expected = "fresh" if age <= timedelta(hours=2) else "stale"
        assert timedelta(0) <= age <= timedelta(hours=6) and response["status"] == expected
        assert "DEMO" in response["value"]["displayTitle"]


if __name__ == "__main__":
    check_links()
    check_coverage()
    check_wire()
    check_graph_and_provider()
    print("Verified documentation links, requirement coverage, wire vectors, graph schema and weather fixture.")
