"""Pins the per-driver transaction claims documented in docs/database_support/postgresql.md."""

import uuid

import pytest

from pydapper.exceptions import UnsupportedFeatureError
from pydapper.postgresql import AiopgCommands
from pydapper.postgresql import Psycopg2Commands
from pydapper.postgresql import Psycopg3Commands
from pydapper.postgresql import Psycopg3CommandsAsync

pytestmark = pytest.mark.postgresql


@pytest.fixture
def scratch_table():
    return f"pydapper_tx_{uuid.uuid4().hex[:8]}"


@pytest.fixture
def url(server, db_port, database_name):
    return f"postgresql://pydapper:pydapper@{server}:{db_port}/{database_name}"


def _admin_execute(url, sql):
    """Run one statement on a fresh autocommit psycopg2 connection."""
    import psycopg2

    conn = psycopg2.connect(url)
    conn.autocommit = True
    try:
        with conn.cursor() as cursor:
            cursor.execute(sql)
    finally:
        conn.close()


def _admin_count(url, table):
    import psycopg2

    conn = psycopg2.connect(url)
    conn.autocommit = True
    try:
        with conn.cursor() as cursor:
            cursor.execute(f"select count(*) from {table}")
            return cursor.fetchone()[0]
    finally:
        conn.close()


class TestPsycopg2:
    def test_with_block_exit_commits_and_does_not_close(self, url, scratch_table):
        import psycopg2

        _admin_execute(url, f"create table {scratch_table} (id integer)")
        commands = Psycopg2Commands(psycopg2.connect(url))
        try:
            with commands:
                commands.execute(f"insert into {scratch_table} (id) values (1)")
            assert commands.connection.closed == 0, "psycopg2's context manager must not close the connection"
            assert _admin_count(url, scratch_table) == 1
        finally:
            commands.connection.close()
            _admin_execute(url, f"drop table if exists {scratch_table}")

    def test_with_block_error_rolls_back(self, url, scratch_table):
        import psycopg2
        import psycopg2.extensions

        _admin_execute(url, f"create table {scratch_table} (id integer)")
        commands = Psycopg2Commands(psycopg2.connect(url))
        try:
            with pytest.raises(ValueError):
                with commands:
                    commands.execute(f"insert into {scratch_table} (id) values (1)")
                    raise ValueError("boom")
            # the CM genuinely rolled back: the still-open connection is idle, not in-transaction
            assert commands.connection.info.transaction_status == psycopg2.extensions.TRANSACTION_STATUS_IDLE
            assert _admin_count(url, scratch_table) == 0
        finally:
            commands.connection.close()
            _admin_execute(url, f"drop table if exists {scratch_table}")


class TestPsycopg3Sync:
    def test_with_block_exit_commits_and_closes(self, url, scratch_table):
        import psycopg

        _admin_execute(url, f"create table {scratch_table} (id integer)")
        commands = Psycopg3Commands(psycopg.connect(url))
        try:
            with commands:
                commands.execute(f"insert into {scratch_table} (id) values (1)")
            assert commands.connection.closed is True, "psycopg's context manager closes after committing"
            assert _admin_count(url, scratch_table) == 1
        finally:
            if not commands.connection.closed:
                commands.connection.close()
            _admin_execute(url, f"drop table if exists {scratch_table}")

    def test_with_block_error_rolls_back_then_closes(self, url, scratch_table):
        import psycopg

        _admin_execute(url, f"create table {scratch_table} (id integer)")
        commands = Psycopg3Commands(psycopg.connect(url))
        try:
            with pytest.raises(ValueError):
                with commands:
                    commands.execute(f"insert into {scratch_table} (id) values (1)")
                    raise ValueError("boom")
            assert commands.connection.closed is True
            assert _admin_count(url, scratch_table) == 0
        finally:
            if not commands.connection.closed:
                commands.connection.close()
            _admin_execute(url, f"drop table if exists {scratch_table}")


class TestPsycopg3Async:
    @pytest.mark.asyncio
    async def test_with_block_exit_commits_and_closes(self, url, scratch_table):
        import psycopg

        _admin_execute(url, f"create table {scratch_table} (id integer)")
        commands = Psycopg3CommandsAsync(await psycopg.AsyncConnection.connect(url))
        try:
            async with commands:
                await commands.execute_async(f"insert into {scratch_table} (id) values (1)")
            assert commands.connection.closed is True
            assert _admin_count(url, scratch_table) == 1
        finally:
            if not commands.connection.closed:
                await commands.connection.close()
            _admin_execute(url, f"drop table if exists {scratch_table}")

    @pytest.mark.asyncio
    async def test_with_block_error_rolls_back_then_closes(self, url, scratch_table):
        import psycopg

        _admin_execute(url, f"create table {scratch_table} (id integer)")
        commands = Psycopg3CommandsAsync(await psycopg.AsyncConnection.connect(url))
        try:
            with pytest.raises(ValueError):
                async with commands:
                    await commands.execute_async(f"insert into {scratch_table} (id) values (1)")
                    raise ValueError("boom")
            assert commands.connection.closed is True
            assert _admin_count(url, scratch_table) == 0
        finally:
            if not commands.connection.closed:
                await commands.connection.close()
            _admin_execute(url, f"drop table if exists {scratch_table}")


class TestAiopg:
    @pytest.mark.asyncio
    async def test_statements_are_durable_immediately(self, url, scratch_table):
        import aiopg

        commands = AiopgCommands(await aiopg.connect(url))
        try:
            await commands.execute_async(f"create table {scratch_table} (id integer)")
            await commands.execute_async(f"insert into {scratch_table} (id) values (1)")
            # visible from a separate connection with no commit anywhere: autocommit-only
            assert _admin_count(url, scratch_table) == 1
        finally:
            commands.connection.close()
            _admin_execute(url, f"drop table if exists {scratch_table}")

    @pytest.mark.asyncio
    async def test_pydapper_transaction_apis_raise_unsupported(self, url):
        import aiopg

        commands = AiopgCommands(await aiopg.connect(url))
        try:
            with pytest.raises(UnsupportedFeatureError):
                commands.transaction()
            with pytest.raises(UnsupportedFeatureError):
                await commands.commit()
            with pytest.raises(UnsupportedFeatureError):
                await commands.rollback()
        finally:
            commands.connection.close()

    @pytest.mark.asyncio
    async def test_async_context_exit_closes_connection(self, url):
        import aiopg

        commands = AiopgCommands(await aiopg.connect(url))
        async with commands:
            pass
        # aiopg's context manager closes on exit; everything was already durable
        assert commands.connection.closed

    @pytest.mark.asyncio
    async def test_driver_commit_and_rollback_raise(self, url):
        import aiopg
        import psycopg2

        commands = AiopgCommands(await aiopg.connect(url))
        try:
            with pytest.raises(psycopg2.ProgrammingError):
                await commands.connection.commit()
            with pytest.raises(psycopg2.ProgrammingError):
                await commands.connection.rollback()
        finally:
            commands.connection.close()
