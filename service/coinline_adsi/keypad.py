"""Incremental telephone-keypad prefix search, independent of provider requests."""

import asyncio

from . import graph, wire


_KEYS = str.maketrans({letter: str(digit) for digit, letters in enumerate(
    ('', '', 'ABC', 'DEF', 'GHI', 'JKL', 'MNO', 'PQRS', 'TUV', 'WXYZ')) for letter in letters})


def signature(text):
    return ''.join(c for c in graph.handset_text(text).upper().translate(_KEYS) if c in '23456789')


def matches(entries, query):
    """Entries contain (identifier, label, searchable terms); preserve catalogue order."""
    return [entry for entry in entries if any(signature(term).startswith(query) for term in entry[2])]


async def _screen(link, say, lines, choices, prompt):
    if link.data_mode:
        await link.transfer(wire.screen([graph.handset_text(line)[:20] for line in lines], choices), open_input=True)
    else:
        link.open_voice_input()
        await say(prompt)
    return await link.selection(30)


async def select(link, say, title, entries, *, maximum=4):
    """One digit per letter; 1 lists matches, * erases, 0 cancels. No network I/O."""
    query, offset, listing = '', 0, False
    try:
        for _ in range(80):
            found = matches(entries, query)
            if listing:
                batch = found[offset:offset + 2]
                choices = [(f'{i} Select', str(i)) for i in range(1, len(batch) + 1)]
                choices += [('Next', '3')] if offset + 2 < len(found) else []
                choices += [('Prev', '4')] if offset else []
                choices += [('Search', '0')]
                digit = await _screen(link, say, [f'{title} {offset + 1}-{offset + len(batch)}',
                    *(f'{i} {item[1]}' for i, item in enumerate(batch, 1)), '0 Search'], choices,
                    '. '.join([title, *(f'Press {i} for {item[1]}' for i, item in enumerate(batch, 1)),
                               'Press 3 for next, 4 for previous or 0 to search']))
                if digit in ('1', '2') and int(digit) <= len(batch):
                    return batch[int(digit) - 1][0]
                if digit == '3' and offset + 2 < len(found):
                    offset += 2
                elif digit == '4' and offset:
                    offset -= 2
                elif digit == '0':
                    listing = False
                continue
            lines = [f'{title} {query or "?"}', f'{len(found)} match(es)',
                     found[0][1] if found else 'No matches', '1 List * Del 0 Exit']
            digit = await _screen(link, say, lines, [('List', '1'), ('Exit', '0')],
                f'{title}. {len(found)} matches. Enter one keypad digit per letter. '
                'Press 1 or pound to list, star to erase, or zero to cancel.')
            if digit == '0':
                return None
            if digit == '*':
                query = query[:-1]
            elif digit in ('1', '#') and found:
                listing, offset = True, 0
            elif digit in '23456789' and len(query) < maximum:
                query += digit
    except TimeoutError:
        return None
    return None
