"""
Columnas nuevas en tablas que ya existen.

`create_all` solo crea tablas nuevas; no agrega columnas a tablas existentes.
Aquí se agregan (una sola vez, es idempotente) las columnas nuevas del modelo.
"""
import logging

from sqlalchemy import inspect, text

logger = logging.getLogger("jamuywasi.schema")

# (tabla, columna, definición SQL)
NEW_COLUMNS = [
    ("orders", "customer_dni", "VARCHAR(12) NULL"),
]


def _upgrade(sync_conn) -> list:
    insp = inspect(sync_conn)
    added = []
    for table, column, ddl in NEW_COLUMNS:
        if not insp.has_table(table):
            continue
        existing = {c["name"] for c in insp.get_columns(table)}
        if column not in existing:
            sync_conn.execute(text(f"ALTER TABLE {table} ADD COLUMN {column} {ddl}"))
            added.append(f"{table}.{column}")
    return added


async def upgrade_schema(engine) -> None:
    async with engine.begin() as conn:
        added = await conn.run_sync(_upgrade)
    if added:
        logger.info("Columnas agregadas: %s", ", ".join(added))
