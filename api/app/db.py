"""Acceso a PostgreSQL mediante un pool de conexiones (psycopg 3)."""
from psycopg.rows import dict_row
from psycopg_pool import ConnectionPool

from . import config

pool = ConnectionPool(
    config.dsn(),
    min_size=1,
    max_size=8,
    kwargs={"row_factory": dict_row},
    open=False,
)


def consultar(sql: str, parametros=None) -> list[dict]:
    with pool.connection() as conexion:
        return conexion.execute(sql, parametros).fetchall()


def consultar_uno(sql: str, parametros=None) -> dict | None:
    with pool.connection() as conexion:
        return conexion.execute(sql, parametros).fetchone()
