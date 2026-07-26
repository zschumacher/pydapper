"""Pins the oracledb transaction claims documented in docs/database_support/oracle.md."""

import uuid

import pytest

from pydapper.oracle import OracledbCommands

pytestmark = pytest.mark.oracle


@pytest.fixture
def scratch_table():
    return f"pydapper_tx_{uuid.uuid4().hex[:8]}"


def _connect(server, db_port, database_name):
    import oracledb

    return oracledb.connect(password="pydapper", user="pydapper", dsn=f"{server}:{db_port}/{database_name}")


def _admin_execute(server, db_port, database_name, sql):
    conn = _connect(server, db_port, database_name)
    try:
        cursor = conn.cursor()
        cursor.execute(sql)
        conn.commit()
    finally:
        conn.close()


def _admin_drop(server, db_port, database_name, table):
    # idempotent drop: the table may not exist if the test failed before creating it
    _admin_execute(
        server,
        db_port,
        database_name,
        f"BEGIN EXECUTE IMMEDIATE 'DROP TABLE {table}'; EXCEPTION WHEN OTHERS THEN NULL; END;",
    )


def _admin_count(server, db_port, database_name, table):
    conn = _connect(server, db_port, database_name)
    try:
        cursor = conn.cursor()
        cursor.execute(f"select count(*) from {table}")
        return cursor.fetchone()[0]
    finally:
        conn.close()


def test_exit_rolls_back_uncommitted_and_closes(server, db_port, database_name, scratch_table):
    import oracledb

    _admin_execute(server, db_port, database_name, f"create table {scratch_table} (id number)")
    try:
        commands = OracledbCommands(_connect(server, db_port, database_name))
        with commands:
            commands.execute(f"insert into {scratch_table} (id) values (1)")
        # oracledb's context manager rolls back uncommitted work and closes — it never commits
        assert _admin_count(server, db_port, database_name, scratch_table) == 0
        with pytest.raises(oracledb.InterfaceError):
            commands.connection.ping()
    finally:
        _admin_drop(server, db_port, database_name, scratch_table)


def test_ddl_implicitly_commits_prior_dml(server, db_port, database_name, scratch_table):
    second_table = f"{scratch_table}_2"
    _admin_execute(server, db_port, database_name, f"create table {scratch_table} (id number)")
    try:
        work = _connect(server, db_port, database_name)
        try:
            cursor = work.cursor()
            cursor.execute(f"insert into {scratch_table} (id) values (1)")
            # the CREATE TABLE implicitly commits the transaction, including the prior insert
            cursor.execute(f"create table {second_table} (id number)")
        finally:
            work.close()  # never committed explicitly
        assert _admin_count(server, db_port, database_name, scratch_table) == 1
    finally:
        _admin_drop(server, db_port, database_name, scratch_table)
        _admin_drop(server, db_port, database_name, second_table)
