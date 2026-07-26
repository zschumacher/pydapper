"""Pins the pymssql transaction claims documented in docs/database_support/mssql.md.

These are the tests that resolve the confusion behind issue #68: an insert inside a plain
``with connect(...)`` block reported success but was silently rolled back on exit.
"""

import uuid
from contextlib import contextmanager

import pytest

from pydapper.mssql.pymssql import PymssqlCommands

pytestmark = pytest.mark.mssql


@pytest.fixture
def scratch_table():
    return f"pydapper_tx_{uuid.uuid4().hex[:8]}"


@contextmanager
def _admin_conn(server, db_port, database_name):
    from pymssql import _pymssql

    conn = _pymssql.connect(
        server=server, port=str(db_port), password="pydapper!PYDAPPER", user="sa", database=database_name
    )
    conn.autocommit(True)
    try:
        yield conn
    finally:
        conn.close()


def _admin_execute(server, db_port, database_name, sql):
    with _admin_conn(server, db_port, database_name) as conn:
        with conn.cursor() as cursor:
            cursor.execute(sql)


def _admin_count(server, db_port, database_name, table):
    with _admin_conn(server, db_port, database_name) as conn:
        with conn.cursor() as cursor:
            cursor.execute(f"select count(*) from {table}")
            return cursor.fetchone()[0]


@pytest.fixture
def scratch(server, db_port, database_name, scratch_table):
    _admin_execute(server, db_port, database_name, f"create table {scratch_table} (id int)")
    yield scratch_table
    _admin_execute(server, db_port, database_name, f"drop table if exists {scratch_table}")


def _work_commands(server, db_port, database_name):
    from pymssql import _pymssql

    return PymssqlCommands(
        _pymssql.connect(
            server=server, port=str(db_port), password="pydapper!PYDAPPER", user="sa", database=database_name
        )
    )


def test_insert_lost_on_plain_context_exit(server, db_port, database_name, scratch):
    """The #68 repro: execute() reports one affected row, but exit closes the connection
    and pymssql's close() rolls back the always-open transaction."""
    with _work_commands(server, db_port, database_name) as commands:
        rows = commands.execute(f"insert into {scratch} (id) values (1)")
        assert rows == 1
    assert _admin_count(server, db_port, database_name, scratch) == 0


def test_insert_durable_with_commands_commit(server, db_port, database_name, scratch):
    with _work_commands(server, db_port, database_name) as commands:
        commands.execute(f"insert into {scratch} (id) values (1)")
        commands.commit()
    assert _admin_count(server, db_port, database_name, scratch) == 1


def test_insert_durable_with_transaction_context(server, db_port, database_name, scratch):
    with _work_commands(server, db_port, database_name) as commands:
        with commands.transaction():
            commands.execute(f"insert into {scratch} (id) values (1)")
    assert _admin_count(server, db_port, database_name, scratch) == 1


def test_enabling_autocommit_discards_open_transaction(server, db_port, database_name, scratch):
    """autocommit(True) rolls the always-open transaction back — switch modes before working."""
    commands = _work_commands(server, db_port, database_name)
    try:
        commands.execute(f"insert into {scratch} (id) values (1)")
        commands.connection.autocommit(True)
        assert _admin_count(server, db_port, database_name, scratch) == 0
    finally:
        commands.connection.close()
