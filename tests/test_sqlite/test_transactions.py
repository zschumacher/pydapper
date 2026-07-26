"""Pins the sqlite3 transaction claims documented in docs/database_support/sqlite.md."""

import sqlite3
import uuid

import pytest

from pydapper.sqlite import Sqlite3Commands

pytestmark = pytest.mark.sqlite


@pytest.fixture
def scratch_table():
    return f"pydapper_tx_{uuid.uuid4().hex[:8]}"


def _row_count(db_path, table):
    conn = sqlite3.connect(db_path)
    try:
        return conn.execute(f"select count(*) from {table}").fetchone()[0]
    finally:
        conn.close()


def _drop(db_path, table):
    conn = sqlite3.connect(db_path)
    try:
        conn.execute(f"drop table if exists {table}")
        conn.commit()
    finally:
        conn.close()


def test_with_block_exit_commits_durably(database_name, scratch_table):
    db_path = f"{database_name}.db"
    commands = Sqlite3Commands(sqlite3.connect(db_path))
    try:
        with commands:
            commands.execute(f"create table {scratch_table} (id integer)")
            commands.execute(f"insert into {scratch_table} (id) values (1)")
        # the connection context manager committed on clean exit
        assert _row_count(db_path, scratch_table) == 1
    finally:
        commands.connection.close()
        _drop(db_path, scratch_table)


def test_with_block_exit_does_not_close_connection(database_name):
    commands = Sqlite3Commands(sqlite3.connect(f"{database_name}.db"))
    with commands:
        pass
    # sqlite3's context manager never closes; the connection is still usable
    assert commands.connection.execute("select 1").fetchone() == (1,)
    commands.connection.close()


def test_with_block_error_rolls_back(database_name, scratch_table):
    db_path = f"{database_name}.db"
    setup = sqlite3.connect(db_path)
    setup.execute(f"create table {scratch_table} (id integer)")
    setup.close()
    try:
        commands = Sqlite3Commands(sqlite3.connect(db_path))
        with pytest.raises(ValueError):
            with commands:
                commands.execute(f"insert into {scratch_table} (id) values (1)")
                raise ValueError("boom")
        # the CM genuinely rolled back: the still-open connection has no transaction in flight
        assert commands.connection.in_transaction is False
        commands.connection.close()
        assert _row_count(db_path, scratch_table) == 0
    finally:
        _drop(db_path, scratch_table)


def test_rolled_back_transaction_block_leaves_ddl_behind(database_name, scratch_table):
    """Legacy isolation_level: DDL issued while no transaction is open runs in autocommit,
    so it survives the rolled-back block (DDL after DML would roll back with it)."""
    db_path = f"{database_name}.db"
    commands = Sqlite3Commands(sqlite3.connect(db_path))
    try:
        with pytest.raises(ValueError):
            with commands.transaction():
                commands.execute(f"create table {scratch_table} (id integer)")
                commands.execute(f"insert into {scratch_table} (id) values (1)")
                raise ValueError("boom")
        table_count = commands.execute_scalar(
            "select count(*) from sqlite_master where type = 'table' and name = ?name?",
            params={"name": scratch_table},
        )
        assert table_count == 1, "the CREATE TABLE must survive the rolled-back block"
        assert commands.execute_scalar(f"select count(*) from {scratch_table}") == 0
    finally:
        commands.connection.execute(f"drop table if exists {scratch_table}")
        commands.connection.commit()
        commands.connection.close()
