"""Opt-in operator-supplied directory with synthetic defaults."""

import re

from . import keypad


DEMO = [
    {'name': 'Demo reception', 'number': '7001', 'detail': 'Example only'},
    {'name': 'Demo library', 'number': '7002', 'detail': 'Example only'},
    {'name': 'Demo service desk', 'number': '7003', 'detail': 'Example only'},
]


def validate(entries):
    if not isinstance(entries, list) or len(entries) > 1000:
        raise ValueError('Configure up to 1000 directory entries.')
    numbers = set()
    for item in entries:
        if (not isinstance(item, dict) or set(item) != {'name', 'number', 'detail'}
                or not all(isinstance(value, str) for value in item.values())
                or not 1 <= len(item['name']) <= 60 or not 1 <= len(item['detail']) <= 80
                or not re.fullmatch(r'\+?[0-9]{2,15}', item['number'])
                or not keypad.signature(item['name']) or item['number'] in numbers):
            raise ValueError('Directory entries require a name, a unique number and a short detail.')
        numbers.add(item['number'])


async def choose(link, say, config):
    entries = config.get('directory', DEMO)
    return await keypad.select(link, say, 'Directory', [(item['number'], item['name'],
        (item['name'], *item['name'].split())) for item in entries], maximum=8)


def lookup(config, number):
    entries = config.get('directory', DEMO)
    if number == 'selected':
        item = entries[0] if entries else None
    else:
        item = next((item for item in entries if item['number'] == number), None)
    if item is None:
        return None
    return {**item, 'displayTitle': 'DIRECTORY' if 'directory' in config else 'DEMO DIRECTORY',
            'source': 'Local directory' if 'directory' in config else 'Fixture directory'}
