"""Build a prefix-to-site map from an operator-downloaded CNA assignment snapshot."""

import argparse
import csv
import hashlib
import io
import json
import re
import sys
import zipfile
from pathlib import Path


def extract(path):
    if path.suffix.lower() != ".zip":
        return path.read_bytes()
    with zipfile.ZipFile(path) as archive:
        candidates = [item for item in archive.infolist() if item.filename.lower().endswith(".csv")]
        if len(candidates) != 1 or candidates[0].file_size > 20_000_000:
            raise ValueError("Expected one CNA CSV in the archive.")
        return archive.read(candidates[0])


def assignments(data, places):
    try:
        source = data.decode("utf-8-sig")
    except UnicodeDecodeError:
        source = data.decode("cp1252")
    rows = csv.reader(io.StringIO(source))
    normalize = lambda value: value.strip().casefold()
    header = ["npa", "nxx", "status", "exchange area", "province"]
    for line in rows:
        columns = [normalize(name).replace("co code (nxx)", "nxx") for name in line]
        if set(header) <= set(columns):
            break
    else:
        raise ValueError("The CNA CO-code columns could not be found.")
    indexes = [columns.index(name) for name in header]
    result = {}
    ambiguous = set()
    for row in rows:
        if len(row) <= max(indexes):
            continue
        npa, nxx, state, exchange, province = [row[index].strip() for index in indexes]
        prefix = npa + nxx
        if normalize(state) not in ("in service", "is") or not re.fullmatch(r"[2-9]\d{2}[2-9]\d{2}", prefix):
            continue
        mapped = places.get(province.upper(), {}).get(normalize(exchange))
        if not mapped:
            continue
        if prefix in result and result[prefix] != mapped:
            ambiguous.add(prefix)
        result[prefix] = mapped
    return {prefix: site for prefix, site in sorted(result.items()) if prefix not in ambiguous}


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("snapshot", type=Path)
    parser.add_argument("exchange_map", type=Path)
    args = parser.parse_args()
    catalog = json.loads(args.exchange_map.read_text(encoding="utf-8"))
    places = {province.upper(): {place.strip().casefold(): site for place, site in values.items()}
              for province, values in catalog.items()}
    data = extract(args.snapshot)
    prefixes = assignments(data, places)
    print(json.dumps({"prefixes": prefixes}, indent=2))
    print(f"Imported {len(prefixes)} prefixes. CSV SHA-256 {hashlib.sha256(data).hexdigest()}", file=sys.stderr)


if __name__ == "__main__":
    main()
