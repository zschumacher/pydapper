import datetime

import pytest
import pytest_asyncio

from pydapper import connect
from pydapper import connect_async
from pydapper import using
from pydapper import using_async
from pydapper.postgresql.psycopg3 import Psycopg3Commands
from pydapper.postgresql.psycopg3 import Psycopg3CommandsAsync
from tests.test_suites.commands import ExecuteAsyncTestSuite
from tests.test_suites.commands import ExecuteScalarAsyncTestSuite
from tests.test_suites.commands import ExecuteScalarTestSuite
from tests.test_suites.commands import ExecuteTestSuite
from tests.test_suites.commands import QueryAsyncTestSuite
from tests.test_suites.commands import QueryFirstAsyncTestSuite
from tests.test_suites.commands import QueryFirstOrDefaultAsyncTestSuite
from tests.test_suites.commands import QueryFirstOrDefaultTestSuite
from tests.test_suites.commands import QueryFirstTestSuite
from tests.test_suites.commands import QueryMultipleAsyncTestSuite
from tests.test_suites.commands import QueryMultipleTestSuite
from tests.test_suites.commands import QuerySingleAsyncTestSuite
from tests.test_suites.commands import QuerySingleOrDefaultAsyncTestSuite
from tests.test_suites.commands import QuerySingleOrDefaultTestSuite
from tests.test_suites.commands import QuerySingleTestSuite
from tests.test_suites.commands import QueryTestSuite

pytestmark = pytest.mark.postgresql


@pytest.fixture(scope="function")
def commands(server, database_name, db_port) -> Psycopg3Commands:
    import psycopg

    with Psycopg3Commands(
        psycopg.connect(f"postgresql://pydapper:pydapper@{server}:{db_port}/{database_name}")
    ) as commands:
        yield commands
        commands.connection.rollback()


@pytest_asyncio.fixture(scope="function")
async def commands_async(server, database_name, db_port) -> Psycopg3CommandsAsync:
    import psycopg

    conn = await psycopg.AsyncConnection.connect(f"postgresql://pydapper:pydapper@{server}:{db_port}/{database_name}")
    with Psycopg3CommandsAsync(conn) as commands_async:
        yield commands_async
        await commands_async.connection.rollback()


def test_using(server, database_name, db_port):
    import psycopg

    with using(psycopg.connect(f"postgresql://pydapper:pydapper@{server}:{db_port}/{database_name}")) as commands:
        assert isinstance(commands, Psycopg3Commands)


@pytest.mark.asyncio
async def test_using_async(server, database_name, db_port):
    import psycopg

    conn = await psycopg.AsyncConnection.connect(f"postgresql://pydapper:pydapper@{server}:{db_port}/{database_name}")
    async with using_async(conn) as commands_async:
        assert isinstance(commands_async, Psycopg3CommandsAsync)


@pytest.mark.parametrize("driver", ["postgresql+psycopg"])
def test_connect(driver, server, database_name, db_port):
    with connect(f"{driver}://pydapper:pydapper@{server}:{db_port}/{database_name}") as commands:
        assert isinstance(commands, Psycopg3Commands)


@pytest.mark.parametrize("driver", ["postgresql+psycopg"])
@pytest.mark.asyncio
async def test_connect_async(driver, server, database_name, db_port):
    async with connect_async(f"{driver}://pydapper:pydapper@{server}:{db_port}/{database_name}") as commands_async:
        assert isinstance(commands_async, Psycopg3CommandsAsync)


class TestExecute(ExecuteTestSuite):
    def test_multiple(self, commands):
        assert (
            commands.execute(
                "INSERT INTO task (id, description, due_date, owner_id) "
                "VALUES (?id?, ?description?, ?due_date?, ?owner_id?)",
                [
                    {"id": 4, "description": "new task", "due_date": datetime.date(2022, 1, 1), "owner_id": 1},
                    {"id": 5, "description": "another new task", "due_date": datetime.date(2022, 1, 1), "owner_id": 1},
                ],
            )
            == 2
        )


class TestQuery(QueryTestSuite): ...


class TestQueryMultiple(QueryMultipleTestSuite): ...


class TestQueryFirst(QueryFirstTestSuite): ...


class TestQueryFirstOrDefault(QueryFirstOrDefaultTestSuite): ...


class TestQuerySingle(QuerySingleTestSuite): ...


class TestQuerySingleOrDefault(QuerySingleOrDefaultTestSuite): ...


class TestExecuteScalar(ExecuteScalarTestSuite): ...
