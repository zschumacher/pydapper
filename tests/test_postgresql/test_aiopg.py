import asyncio
import datetime

import pytest
import pytest_asyncio

from pydapper import connect_async
from pydapper import using_async
from pydapper.commands import CommandsAsync
from pydapper.postgresql import AiopgCommands
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
async def commands(server, database_name, db_port) -> AiopgCommands:
    import aiopg

    async with aiopg.connect(f"postgresql://pydapper:pydapper@{server}:{db_port}/{database_name}") as conn:
        c = AiopgCommands(conn)
        yield c


@pytest.mark.asyncio
async def test_using_async(server, database_name, db_port):
    import aiopg

    conn = await aiopg.connect(f"postgresql://pydapper:pydapper@{server}:{db_port}/{database_name}")
    async with using_async(conn) as commands:
        assert isinstance(commands, AiopgCommands)


@pytest.mark.asyncio
async def test_connect_async(server, database_name, db_port):
    async with connect_async(f"postgresql+aiopg://pydapper:pydapper@{server}:{db_port}/{database_name}") as commands:
        assert isinstance(commands, AiopgCommands)


class TestExecuteAsync(ExecuteAsyncTestSuite):
    """
    aipog always runs in autocommit mode, so need to clean up the data inside the tests.  in the future I'd like
    to add support for Transaction objects
    """

    @pytest.mark.asyncio
    async def test_single(self, commands: CommandsAsync):
        old_name = await commands.execute_scalar_async("select name from owner")
        assert (
            await commands.execute_async(
                "UPDATE owner SET name = ?new_name? WHERE id = ?id?", {"new_name": "Zachary", "id": 1}
            )
            == 1
        )
        await commands.execute_async(
            "UPDATE OWNER SET name = ?old_name? WHERE id = ?id?", {"old_name": old_name, "id": 1}
        )

    @pytest.mark.asyncio
    async def test_multiple(self, commands: CommandsAsync):
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
        await commands.execute_async("delete from task where id in (4, 5)")


class TestQueryAsync(QueryAsyncTestSuite): ...


class TestQueryMultipleAsync(QueryMultipleAsyncTestSuite): ...


class TestQueryFirstAsync(QueryFirstAsyncTestSuite): ...


class TestQueryFirstOrDefaultAsync(QueryFirstOrDefaultAsyncTestSuite): ...


class TestQuerySingleAsync(QuerySingleAsyncTestSuite): ...


class TestQuerySingleOrDefaultAsync(QuerySingleOrDefaultAsyncTestSuite): ...


class TestExecuteScalarAsync(ExecuteScalarAsyncTestSuite): ...
