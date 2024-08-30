import asyncio
import datetime

import aioodbc
import pytest
import pytest_asyncio

from pydapper import connect_async
from pydapper import using_async
from pydapper.commands import CommandsAsync
from pydapper.odbc.aioodbc import AioodbcCommands
from tests.test_suites.commands import ExecuteAsyncTestSuite
from tests.test_suites.commands import ExecuteScalarAsyncTestSuite
from tests.test_suites.commands import QueryAsyncTestSuite
from tests.test_suites.commands import QueryFirstAsyncTestSuite
from tests.test_suites.commands import QueryFirstOrDefaultAsyncTestSuite
from tests.test_suites.commands import QueryMultipleAsyncTestSuite
from tests.test_suites.commands import QuerySingleAsyncTestSuite
from tests.test_suites.commands import QuerySingleOrDefaultAsyncTestSuite


@pytest.fixture(scope="function")
def event_loop():
    loop = asyncio.get_event_loop()
    yield loop
    loop.close()


@pytest_asyncio.fixture(scope="function")
async def commands(database_name) -> AioodbcCommands:
    dsn = f"DRIVER={{SQLite3 ODBC Driver}};DATABASE={database_name}.db"
    conn = await aioodbc.connect(dsn=dsn, autocommit=True)
    async with conn:
        c = AioodbcCommands(conn)
        yield c


@pytest.mark.asyncio
async def test_using_async(database_name):
    conn = await aioodbc.connect(dsn=f"DRIVER={{SQLite3 ODBC Driver}};DATABASE={database_name}.db")
    async with using_async(conn) as commands:
        assert isinstance(commands, AioodbcCommands)


@pytest.mark.asyncio
async def test_connect_async(database_name):
    async with connect_async(f"sqlite+aioodbc://{database_name}.db") as commands:
        assert isinstance(commands, AioodbcCommands)


class TestQueryAsync(QueryAsyncTestSuite): ...


class TestQueryMultipleAsync(QueryMultipleAsyncTestSuite): ...


class TestQueryFirstAsync(QueryFirstAsyncTestSuite): ...


class TestQueryFirstOrDefaultAsync(QueryFirstOrDefaultAsyncTestSuite): ...


class TestQuerySingleAsync(QuerySingleAsyncTestSuite): ...


class TestQuerySingleOrDefaultAsync(QuerySingleOrDefaultAsyncTestSuite): ...


class TestExecuteScalarAsync(ExecuteScalarAsyncTestSuite): ...
