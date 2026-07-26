"""Pins the mysql-connector-python transaction claims documented in docs/database_support/mysql.md."""

import uuid

import pytest

from pydapper.mysql import MySqlConnectorPythonCommands

pytestmark = pytest.mark.mysql


@pytest.fixture
def scratch_table():
    return f"pydapper_tx_{uuid.uuid4().hex[:8]}"


@pytest.fixture
def admin_conn(server, db_port, database_name):
    import mysql.connector

    conn = mysql.connector.connect(
        host=server, port=db_port, user="pydapper", password="pydapper", database=database_name, autocommit=True
    )
    yield conn
    conn.close()


def _admin_count(admin_conn, table):
    cursor = admin_conn.cursor()
    cursor.execute(f"select count(*) from {table}")
    count = cursor.fetchall()[0][0]
    cursor.close()
    return count


def test_exit_closes_and_discards_uncommitted_insert(server, db_port, database_name, admin_conn, scratch_table):
    import mysql.connector

    try:
        commands = MySqlConnectorPythonCommands(
            mysql.connector.connect(
                host=server, port=db_port, user="pydapper", password="pydapper", database=database_name
            )
        )
        with commands:
            # DDL is implicitly committed by the server the moment it runs
            commands.execute(f"create table {scratch_table} (id integer)")
            commands.execute(f"insert into {scratch_table} (id) values (1)")
        # the context manager only closes — the uncommitted insert is discarded
        assert commands.connection.is_connected() is False
        assert _admin_count(admin_conn, scratch_table) == 0
    finally:
        cursor = admin_conn.cursor()
        cursor.execute(f"drop table if exists {scratch_table}")
        cursor.close()


def test_ddl_implicitly_commits_prior_dml(server, db_port, database_name, admin_conn, scratch_table):
    import mysql.connector

    second_table = f"{scratch_table}_2"
    cursor = admin_conn.cursor()
    cursor.execute(f"create table {scratch_table} (id integer)")
    cursor.close()
    try:
        work = mysql.connector.connect(
            host=server, port=db_port, user="pydapper", password="pydapper", database=database_name
        )
        try:
            work_cursor = work.cursor()
            work_cursor.execute(f"insert into {scratch_table} (id) values (1)")
            # the CREATE TABLE implicitly commits the transaction, including the prior insert
            work_cursor.execute(f"create table {second_table} (id integer)")
            work_cursor.close()
        finally:
            work.close()  # never committed explicitly
        assert _admin_count(admin_conn, scratch_table) == 1
    finally:
        cursor = admin_conn.cursor()
        cursor.execute(f"drop table if exists {scratch_table}")
        cursor.execute(f"drop table if exists {second_table}")
        cursor.close()
