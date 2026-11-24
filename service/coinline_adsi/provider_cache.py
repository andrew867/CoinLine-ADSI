"""Durable shared public-feed snapshots and provider request budgets."""

import asyncio
import json
import sqlite3
import time
from pathlib import Path


class ProviderCache:
    def __init__(self, directory):
        if directory:
            Path(directory).mkdir(parents=True, exist_ok=True)
        self.db = sqlite3.connect(str(Path(directory) / "feeds.sqlite3") if directory else ":memory:")
        self.db.execute("PRAGMA busy_timeout=3000")
        self.db.executescript("""
            CREATE TABLE IF NOT EXISTS snapshots (
                key TEXT PRIMARY KEY, value TEXT, fetched REAL, retry REAL NOT NULL
            );
            CREATE TABLE IF NOT EXISTS budgets (
                provider TEXT, period TEXT, used INTEGER NOT NULL,
                PRIMARY KEY(provider, period)
            );
        """)
        self.locks = {}
        self.memory = {}

    def quota(self, provider, daily, minute=None, cost=1):
        now = int(time.time())
        windows = [(f"d{now // 86400}", daily)]
        if minute is not None:
            windows.append((f"m{now // 60}", minute))
        with self.db:
            self.db.execute("BEGIN IMMEDIATE")
            for period, limit in windows:
                row = self.db.execute("SELECT used FROM budgets WHERE provider=? AND period=?",
                                      (provider, period)).fetchone()
                if (row[0] if row else 0) + cost > limit:
                    return False
            for period, _ in windows:
                self.db.execute("INSERT INTO budgets VALUES (?,?,?) ON CONFLICT(provider,period) "
                                "DO UPDATE SET used=used+excluded.used", (provider, period, cost))
            self.db.execute("DELETE FROM budgets WHERE provider=? AND period NOT IN (?,?)",
                            (provider, f"d{now // 86400}", f"m{now // 60}"))
        return True

    def _snapshot(self, key):
        row = self.db.execute("SELECT value,fetched,retry FROM snapshots WHERE key=?", (key,)).fetchone()
        if row is None:
            return None, 0, 0
        encoded, fetched, retry = row
        return json.loads(encoded) if encoded is not None else None, fetched or 0, retry

    async def get(self, key, ttl, fetch, *, max_age=None):
        lock = self.locks.setdefault(key, asyncio.Lock())
        async with lock:
            value, fetched, retry = self.memory.get(key, (None, 0, 0))
            now = time.time()
            if value is not None and fetched and now - fetched < ttl:
                return value if max_age is None or now - fetched <= max_age else None
            # Reserve a retry window before sending, including unsuccessful requests.
            with self.db:
                self.db.execute("BEGIN IMMEDIATE")
                value, fetched, retry = self._snapshot(key)
                if (fetched and now - fetched < ttl) or retry > now:
                    self.memory[key] = value, fetched, retry
                    return value if max_age is None or now - fetched <= max_age else None
                self.db.execute("INSERT INTO snapshots(key,retry) VALUES (?,?) "
                                "ON CONFLICT(key) DO UPDATE SET retry=excluded.retry", (key, now + 120))
            self.memory[key] = value, fetched, now + 120
            result = await fetch()
            if result is not None:
                with self.db:
                    self.db.execute("UPDATE snapshots SET value=?,fetched=?,retry=0 WHERE key=?",
                                    (json.dumps(result, ensure_ascii=False), now, key))
                self.memory[key] = result, now, 0
                return result
            return value if max_age is None or now - fetched <= max_age else None

    def close(self):
        self.db.close()
