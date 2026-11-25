"""Export public-facing entries from an explicitly selected Asterisk voicemail context."""

import argparse
import csv
import json
import re
from pathlib import Path


def entries(lines, context):
    active = False
    for raw in lines:
        line = raw.split(';', 1)[0].strip()
        if line.startswith('['):
            active = line == f'[{context}]'
        elif active and '=>' in line:
            number, spec = (part.strip() for part in line.split('=>', 1))
            if not re.fullmatch(r'[0-9]{2,15}', number):
                continue
            fields = next(csv.reader([spec], skipinitialspace=True))
            if len(fields) < 2 or not fields[1].strip():
                continue
            if re.search(r'\bhidefromdir\s*=\s*(yes|true|1|on)\b', ','.join(fields[4:]), re.I):
                continue
            # Never copy the mailbox password, email address or notification settings.
            yield {'name': fields[1].strip(), 'number': number, 'detail': 'PBX extension'}


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('voicemail_conf', type=Path)
    parser.add_argument('context')
    parser.add_argument('output', type=Path)
    args = parser.parse_args()
    with args.voicemail_conf.open(encoding='utf-8') as source:
        data = list(entries(source, args.context))
    with args.output.open('x', encoding='utf-8') as output:
        json.dump({'directory': data}, output, ensure_ascii=False, indent=2)
