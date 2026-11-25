"""Transactional application revisions, routes and operator configuration."""

import asyncio
import json
import os
from pathlib import Path
from uuid import UUID, uuid4

import psycopg
from psycopg.rows import dict_row
from psycopg.types.json import Jsonb
from psycopg_pool import AsyncConnectionPool


DEMO_ID = UUID("320b5017-1d86-4be4-98ca-df9aaff08031")
LEGACY_DEMO_REVISION = UUID("9ff5ef31-0439-4723-9aea-cf778f4ec36d")
DEMO_REVISION = UUID("558c2930-05ea-44e9-997c-2b17880edfea")
SERVICES_REVISION = UUID("d24a5017-450a-4c92-b477-87b1403ce424")
HERE = Path(__file__).resolve().parent


class StoreError(RuntimeError):
    def __init__(self, status, message):
        super().__init__(message)
        self.status = status


def connection_string():
    return psycopg.conninfo.make_conninfo(
        host=os.environ["ADSI_DB_HOST"],
        dbname="coinline",
        user="coinline",
        password=os.environ["ADSI_DATABASE_PASSWORD"],
        connect_timeout=3,
    )


async def migrate():
    async with await psycopg.AsyncConnection.connect(connection_string()) as connection:
        async with connection.transaction():
            await connection.execute("SELECT pg_advisory_xact_lock(728143082)")
            for migration in sorted((HERE / "migrations").glob("*.sql")):
                await connection.execute(migration.read_text(encoding="utf-8"))
            graph = Jsonb(json.loads((HERE / "infoline-services.json").read_text(encoding="utf-8")))
            seeded = await connection.execute(
                "INSERT INTO applications(id, name, draft) VALUES (%s, %s, %s) "
                "ON CONFLICT DO NOTHING RETURNING id", (DEMO_ID, "CoinLine InfoLine", graph))
            if await seeded.fetchone():
                await connection.execute(
                    "INSERT INTO revisions(id, app_id, generation, graph) VALUES (%s, %s, 1, %s)",
                    (SERVICES_REVISION, DEMO_ID, graph))
                await connection.execute("UPDATE routes SET revision_id=%s WHERE name='infoline'", (SERVICES_REVISION,))
            else:
                # Upgrade only the original, unedited sample and keep its published revision.
                changed = await connection.execute(
                    "UPDATE applications AS a SET draft=%s, generation=a.generation+1, updated_at=now() "
                    "FROM revisions AS r JOIN routes ON routes.revision_id=r.id "
                    "WHERE a.id=%s AND NOT a.archived AND r.app_id=a.id "
                    "AND a.generation=r.generation AND a.draft=r.graph "
                    "AND routes.name='infoline' AND r.id IN (%s,%s) "
                    "AND NOT EXISTS(SELECT 1 FROM revisions WHERE id=%s) "
                    "RETURNING a.generation", (graph, DEMO_ID, LEGACY_DEMO_REVISION, DEMO_REVISION, SERVICES_REVISION))
                row = await changed.fetchone()
                if row:
                    await connection.execute("INSERT INTO revisions(id,app_id,generation,graph) VALUES (%s,%s,%s,%s)",
                                             (SERVICES_REVISION, DEMO_ID, row[0], graph))
                    await connection.execute("UPDATE routes SET revision_id=%s WHERE name='infoline'", (SERVICES_REVISION,))


class Store:
    def __init__(self):
        self.pool = AsyncConnectionPool(
            connection_string(), min_size=1, max_size=8, open=False, kwargs={"row_factory": dict_row})

    async def _one(self, sql, parameters=()):
        async with self.pool.connection() as connection:
            return await (await connection.execute(sql, parameters)).fetchone()

    async def _all(self, sql, parameters=()):
        async with self.pool.connection() as connection:
            return await (await connection.execute(sql, parameters)).fetchall()

    async def applications(self, owner=None):
        query = "SELECT id, name, generation, archived, updated_at FROM applications"
        if owner is not None:
            return await self._all(query + " WHERE owner=%s ORDER BY name, id", (owner,))
        return await self._all(query + " ORDER BY name, id")

    async def application(self, identifier):
        row = await self._one("SELECT * FROM applications WHERE id=%s", (identifier,))
        if not row:
            raise StoreError(404, "Application not found.")
        return row

    async def create(self, name, graph, owner):
        return await self._one("INSERT INTO applications(id, name, draft, owner) VALUES (%s,%s,%s,%s) RETURNING *",
                               (uuid4(), name, Jsonb(graph), owner))

    async def edit(self, identifier, generation, *, graph=None, name=None):
        async with self.pool.connection() as connection:
            row = await self._editable(connection, identifier, generation)
            return await (await connection.execute(
                "UPDATE applications SET draft=%s, name=%s, generation=generation+1, updated_at=now() "
                "WHERE id=%s RETURNING *",
                (Jsonb(graph if graph is not None else row["draft"]), name if name is not None else row["name"],
                 identifier))).fetchone()

    @staticmethod
    async def _editable(connection, identifier, generation=None, *, archived=False):
        row = await (await connection.execute("SELECT * FROM applications WHERE id=%s FOR UPDATE",
                                              (identifier,))).fetchone()
        if not row:
            raise StoreError(404, "Application not found.")
        if generation is not None and generation != row["generation"]:
            raise StoreError(412, "This draft changed. Refresh before saving.")
        if row["archived"] != archived:
            raise StoreError(409, "Application is in a different lifecycle state.")
        return row

    @staticmethod
    async def _route(connection, name, revision):
        updated = await connection.execute("UPDATE routes SET revision_id=%s WHERE name=%s", (revision, name))
        if updated.rowcount != 1:
            raise StoreError(422, "Unknown route.")

    @staticmethod
    async def _log(connection, action, scope):
        await connection.execute("INSERT INTO audit(action, scope) VALUES (%s,%s)", (action, str(scope)))

    async def revisions(self, identifier):
        return await self._all("SELECT id, generation, created_at FROM revisions WHERE app_id=%s "
                               "ORDER BY generation DESC", (identifier,))

    async def publish(self, identifier, generation, routes, validate):
        async with self.pool.connection() as connection:
            row = await self._editable(connection, identifier, generation)
            validate(row["draft"])
            revision = await (await connection.execute(
                "INSERT INTO revisions(id, app_id, generation, graph) VALUES (%s,%s,%s,%s) "
                "ON CONFLICT (app_id, generation) DO UPDATE SET app_id=EXCLUDED.app_id "
                "RETURNING id, generation, created_at",
                (uuid4(), identifier, generation, Jsonb(row["draft"])))).fetchone()
            for route in sorted(set(routes)):
                await self._route(connection, route, revision["id"])
            await self._log(connection, "publish", identifier)
            return revision

    async def export(self, identifier, revision=None):
        if revision is None:
            return (await self.application(identifier))["draft"]
        row = await self._one("SELECT graph FROM revisions WHERE app_id=%s AND id=%s", (identifier, revision))
        if not row:
            raise StoreError(404, "Revision not found.")
        return row["graph"]

    async def activate(self, identifier, revision, routes):
        async with self.pool.connection() as connection:
            await self._editable(connection, identifier)
            found = await (await connection.execute("SELECT id FROM revisions WHERE app_id=%s AND id=%s",
                                                    (identifier, revision))).fetchone()
            if not found:
                raise StoreError(404, "Revision not found.")
            for route in sorted(set(routes)):
                await self._route(connection, route, revision)
            await self._log(connection, "activate", identifier)

    async def archive(self, identifier, disable_routes):
        async with self.pool.connection() as connection:
            await self._editable(connection, identifier)
            rows = await (await connection.execute(
                "SELECT routes.name FROM routes JOIN revisions ON revisions.id=routes.revision_id "
                "WHERE revisions.app_id=%s ORDER BY routes.name FOR UPDATE OF routes", (identifier,))).fetchall()
            if rows and not disable_routes:
                raise StoreError(409, "Disable or move this application's active routes first.")
            for row in rows:
                await self._route(connection, row["name"], None)
            await connection.execute("UPDATE applications SET archived=true WHERE id=%s", (identifier,))
            await self._log(connection, "archive", identifier)

    async def restore(self, identifier):
        async with self.pool.connection() as connection:
            await self._editable(connection, identifier, archived=True)
            await connection.execute("UPDATE applications SET archived=false, generation=generation+1 WHERE id=%s",
                                     (identifier,))
            await self._log(connection, "restore", identifier)

    async def route(self, name):
        row = await self._one("SELECT revisions.id, revisions.graph FROM routes "
                              "JOIN revisions ON revisions.id=routes.revision_id WHERE routes.name=%s", (name,))
        return row

    async def routes(self):
        return await self._all("SELECT name, revision_id FROM routes ORDER BY name")

    async def setting(self, name):
        row = await self._one("SELECT value, generation FROM settings WHERE name=%s", (name,))
        return row or {"value": {}, "generation": 0}

    async def set_setting(self, name, generation, value):
        async with self.pool.connection() as connection:
            if generation == 0:
                query = "INSERT INTO settings(name, value) VALUES (%s,%s) ON CONFLICT DO NOTHING RETURNING generation"
                parameters = (name, Jsonb(value))
            else:
                query = "UPDATE settings SET value=%s, generation=generation+1 WHERE name=%s AND generation=%s RETURNING generation"
                parameters = (Jsonb(value), name, generation)
            updated = await (await connection.execute(query, parameters)).fetchone()
            if not updated:
                raise StoreError(412, "Configuration changed. Refresh before saving.")
            await self._log(connection, "configure", name)
            return updated

    async def take_download(self):
        async with self.pool.connection() as connection:
            row = await (await connection.execute(
                "UPDATE settings SET value=value - 'approved', generation=generation+1 "
                "WHERE name='fdm' AND value->>'approved'='true' RETURNING value")).fetchone()
            if row:
                await self._log(connection, "download_claimed", "fdm")
                return row["value"]
            return None


if __name__ == "__main__":
    asyncio.run(migrate())
