"""Exercise durable card reservations against the isolated lab's actual PostgreSQL database."""

import asyncio
import os

from coinline_adsi.shadybank import PostgresPinGate, PIN_ATTEMPTS, Rejected, card_key
from coinline_adsi.store import Store


async def main():
    store = Store()
    await store.pool.open(wait=True, timeout=5)
    key = os.urandom(32)
    card = '9000000000000099'
    other = '9000000000000098'
    first = PostgresPinGate(store, key)
    second = PostgresPinGate(store, key)
    try:
        # Separate gate objects emulate independent calls or restarted app processes.
        results = await asyncio.gather(*(first.reserve(card) if i % 2 else second.reserve(card)
                                         for i in range(8)), return_exceptions=True)
        assert sum(isinstance(result, Rejected) for result in results) == 8 - PIN_ATTEMPTS
        row = await store._one('SELECT attempts, expires_at FROM shadybank_pin_attempts WHERE card_key=%s',
                               (card_key(key, card),))
        assert row['attempts'] == PIN_ATTEMPTS
        expiry = row['expires_at']
        try:
            await second.reserve(card)
            raise AssertionError('Locked card was accepted')
        except Rejected:
            pass
        assert (await store._one('SELECT expires_at FROM shadybank_pin_attempts WHERE card_key=%s',
                                 (card_key(key, card),)))['expires_at'] == expiry
        reservation = await second.reserve(other)
        await second.clear(other, reservation)
        # Expire only the uniquely keyed test row, not any other application's data.
        await store._one("UPDATE shadybank_pin_attempts SET expires_at=clock_timestamp()-interval '1 second' "
                         "WHERE card_key=%s RETURNING attempts", (card_key(key, card),))
        older = await first.reserve(card)
        newer = await second.reserve(card)
        await first.clear(card, older)
        assert (await store._one('SELECT reservation FROM shadybank_pin_attempts WHERE card_key=%s',
                                 (card_key(key, card),)))['reservation'] == newer
        await second.clear(card, newer)
        assert await store._one('SELECT reservation FROM shadybank_pin_attempts WHERE card_key=%s',
                                (card_key(key, card),)) is None
    finally:
        async with store.pool.connection() as connection:
            await connection.execute('DELETE FROM shadybank_pin_attempts WHERE card_key IN (%s,%s)',
                                     (card_key(key, card), card_key(key, other)))
        await store.pool.close()
    print('Verified atomic persistent card lockout, cooldown expiry, independent card, and reservation ordering.')


if __name__ == '__main__':
    asyncio.run(main())
