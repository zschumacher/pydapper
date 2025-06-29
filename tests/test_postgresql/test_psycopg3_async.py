import datetime

import pytest
import pytest_asyncio

from pydapper import connect_async
from pydapper import using_async
from pydapper.postgresql.psycopg3 import Psycopg3CommandsAsync
from tests.test_suites.commands import ExecuteAsyncTestSuite
from tests.test_suites.commands import ExecuteScalarAsyncTestSuite
from tests.test_suites.commands import QueryAsyncTestSuite
from tests.test_suites.commands import QueryFirstAsyncTestSuite
from tests.test_suites.commands import QueryFirstOrDefaultAsyncTestSuite
from tests.test_suites.commands import QueryMultipleAsyncTestSuite
from tests.test_suites.commands import QuerySingleAsyncTestSuite
from tests.test_suites.commands import QuerySingleOrDefaultAsyncTestSuite

pytestmark = pytest.mark.postgresql


@pytest_asyncio.fixture(scope="function")
async def commands(server, database_name, db_port) -> Psycopg3CommandsAsync:
    import psycopg

    conn = await psycopg.AsyncConnection.connect(f"postgresql://pydapper:pydapper@{server}:{db_port}/{database_name}")
    async with Psycopg3CommandsAsync(conn) as commands_async:
        yield commands_async
        await commands_async.connection.rollback()


@pytest.mark.asyncio
async def test_using_async(server, database_name, db_port):
    import psycopg

    conn = await psycopg.AsyncConnection.connect(f"postgresql://pydapper:pydapper@{server}:{db_port}/{database_name}")
    async with using_async(conn) as commands_async:
        assert isinstance(commands_async, Psycopg3CommandsAsync)


@pytest.mark.parametrize("driver", ["postgresql+psycopg"])
@pytest.mark.asyncio
async def test_connect_async(driver, server, database_name, db_port):
    async with connect_async(f"{driver}://pydapper:pydapper@{server}:{db_port}/{database_name}") as commands_async:
        assert isinstance(commands_async, Psycopg3CommandsAsync)


@pytest.mark.asyncio
class TestExecuteAsync(ExecuteAsyncTestSuite):
    async def test_multiple(self, commands):
        assert (
            await commands.execute_async(
                "INSERT INTO task (id, description, due_date, owner_id) "
                "VALUES (?id?, ?description?, ?due_date?, ?owner_id?)",
                [
                    {"id": 4, "description": "new task", "due_date": datetime.date(2022, 1, 1), "owner_id": 1},
                    {"id": 5, "description": "another new task", "due_date": datetime.date(2022, 1, 1), "owner_id": 1},
                ],
            )
            == 2
        )


class TestQueryAsync(QueryAsyncTestSuite): ...


class TestQueryMultipleAsync(QueryMultipleAsyncTestSuite): ...


class TestQueryFirstAsync(QueryFirstAsyncTestSuite): ...


class TestQueryFirstOrDefaultAsync(QueryFirstOrDefaultAsyncTestSuite): ...


class TestQuerySingleAsync(QuerySingleAsyncTestSuite): ...


class TestQuerySingleOrDefaultAsync(QuerySingleOrDefaultAsyncTestSuite): ...


class TestExecuteScalarAsync(ExecuteScalarAsyncTestSuite): ...
