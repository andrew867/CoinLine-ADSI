"""Build the compact scheduled-airport index from OurAirports' public-domain CSV."""

import argparse
import csv
import json
import re
from pathlib import Path


def build(source):
    rows = []
    for row in csv.DictReader(source):
        iata, icao = row['iata_code'], row['icao_code']
        if (row['scheduled_service'] != 'yes' or row['type'] in ('closed', 'heliport')
                or not re.fullmatch(r'[A-Z]{3}', iata)):
            continue
        if not re.fullmatch(r'[A-Z]{4}', icao):
            icao = ''
        rows.append([iata, icao, row['municipality'] or row['name'], row['iso_country']])
    return sorted(rows, key=lambda row: (row[3] != 'CA', row[0], row[1]))


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('csv', type=Path)
    parser.add_argument('output', type=Path)
    args = parser.parse_args()
    with args.csv.open(encoding='utf-8-sig', newline='') as source:
        rows = build(source)
    args.output.write_text('[\n' + ',\n'.join(
        '  ' + json.dumps(row, ensure_ascii=False, separators=(',', ':')) for row in rows) + '\n]\n', encoding='utf-8')
    print(f'Indexed {len(rows)} scheduled airports.')
