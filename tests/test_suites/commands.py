import datetime
from dataclasses import dataclass
from typing import AsyncGenerator

import pytest

from pydapper.commands import Commands
from pydapper.commands import CommandsAsync


class ExecuteTestSuite:
    def test_single(self, commands: Commands, owner_table_name):
        assert (
            commands.execute(
                f"UPDATE {owner_table_name} SET name = ?new_name? WHERE id = ?id?", {"new_name": "Zachary", "id": 1}
            )
            == 1
        )

    def test_multiple(self, commands: Commands, task_table_name):
        assert (
            commands.execute(
                f"INSERT INTO {task_table_name} (description, due_date, owner_id) "
                "VALUES (?description?, ?due_date?, ?owner_id?)",
                [
                    {"description": "new task", "due_date": datetime.date(2022, 1, 1), "owner_id": 1},
                    {"description": "another new task", "due_date": datetime.date(2022, 1, 1), "owner_id": 1},
                ],
            )
            == 2
        )


class ExecuteAsyncTestSuite:
    @pytest.mark.asyncio
    async def test_single(self, commands: CommandsAsync, owner_table_name):
        assert (
            await commands.execute_async(
                f"UPDATE {owner_table_name} SET name = ?new_name? WHERE id = ?id?", {"new_name": "Zachary", "id": "1"}
            )
            == 1
        )

    @pytest.mark.asyncio
    async def test_multiple(self, commands: CommandsAsync, task_table_name):
        assert (
            await commands.execute_async(
                f"INSERT INTO {task_table_name} (description, due_date, owner_id) "
                "VALUES (?description?, ?due_date?, ?owner_id?)",
                [
                    {"description": "new task", "due_date": datetime.date(2022, 1, 1), "owner_id": 1},
                    {"description": "another new task", "due_date": datetime.date(2022, 1, 1), "owner_id": 1},
                ],
            )
            == 2
        )


class QueryTestSuite:
    def test(self, commands: Commands, task_table_name):
        data = commands.query(f"select * from {task_table_name}")
        assert len(data) == 3
        assert all(isinstance(record, dict) for record in data)

    def test_param(self, commands: Commands, task_table_name):
        data = commands.query(
            f"select * from {task_table_name} where due_date = ?due_date?",
            param={"due_date": datetime.date(2021, 12, 31)},
        )
        assert len(data) == 2
        assert all(isinstance(record, dict) for record in data)

    def test_unbuffered(self, commands: Commands, task_table_name):
        generator = commands.query(f"select * from {task_table_name}", buffered=False)

        assert next(generator)
        assert next(generator)
        assert next(generator)

        with pytest.raises(StopIteration):
            next(generator)


class QueryAsyncTestSuite:
    @pytest.mark.asyncio
    async def test(self, commands: CommandsAsync, task_table_name):
        data = await commands.query_async(f"select * from {task_table_name}")
        assert len(data) == 3
        assert all(isinstance(record, dict) for record in data)

    @pytest.mark.asyncio
    async def test_param(self, commands: CommandsAsync, task_table_name):
        data = await commands.query_async(
            f"select * from {task_table_name} where due_date = ?due_date?",
            param={"due_date": datetime.date(2021, 12, 31)},
        )
        assert len(data) == 2
        assert all(isinstance(record, dict) for record in data)

    @pytest.mark.asyncio
    async def test_unbuffered(self, commands: CommandsAsync, task_table_name):
        generator = await commands.query_async(f"select * from {task_table_name}", buffered=False)
        assert isinstance(generator, AsyncGenerator)

        data = [row async for row in generator]
        assert len(data) == 3


class QueryMultipleTestSuite:
    def test(self, commands: Commands, owner_table_name, task_table_name):
        owner, task = commands.query_multiple((f"select * from {owner_table_name}", f"select * from {task_table_name}"))
        assert len(owner) == 1
        assert len(task) == 3
        assert isinstance(owner[0], dict)
        assert all(isinstance(record, dict) for record in task)

    def test_param(self, commands: Commands, owner_table_name, task_table_name):
        owner, task = commands.query_multiple(
            (
                f"select * from {owner_table_name} where id = ?id?",
                f"select * from {task_table_name} where due_date = ?due_date?",
            ),
            param={"id": 1, "due_date": datetime.date(2021, 12, 31)},
        )
        assert len(owner) == 1
        assert len(task) == 2
        assert isinstance(owner[0], dict)
        assert all(isinstance(record, dict) for record in task)

    def test_different_models(self, commands: Commands, owner_table_name, task_table_name):
        @dataclass
        class Task:
            id: int
            description: str
            due_date: datetime.date
            owner_id: int

        @dataclass
        class Owner:
            id: int
            name: str

        owner, task = commands.query_multiple(
            (
                f"select id, name from {owner_table_name}",
                f"select id, description, due_date, owner_id from {task_table_name}",
            ),
            models=(Owner, Task),
        )

        assert len(owner) == 1
        assert len(task) == 3
        assert isinstance(owner[0], Owner)
        assert all(isinstance(record, Task) for record in task)


class QueryMultipleAsyncTestSuite:
    @pytest.mark.asyncio
    async def test(self, commands: CommandsAsync, owner_table_name, task_table_name):
        owner, task = await commands.query_multiple_async(
            (f"select * from {owner_table_name}", f"select * from {task_table_name}")
        )
        assert len(owner) == 1
        assert len(task) == 3
        assert isinstance(owner[0], dict)
        assert all(isinstance(record, dict) for record in task)

    @pytest.mark.asyncio
    async def test_param(self, commands: CommandsAsync, owner_table_name, task_table_name):
        owner, task = await commands.query_multiple_async(
            (
                f"select * from {owner_table_name} where id = ?id?",
                f"select * from {task_table_name} where due_date = ?due_date?",
            ),
            param={"id": 1, "due_date": datetime.date(2021, 12, 31)},
        )
        assert len(owner) == 1
        assert len(task) == 2
        assert isinstance(owner[0], dict)
        assert all(isinstance(record, dict) for record in task)

    @pytest.mark.asyncio
    async def test_different_models(self, commands: CommandsAsync, owner_table_name, task_table_name):
        @dataclass
        class Task:
            id: int
            description: str
            due_date: datetime.date
            owner_id: int

        @dataclass
        class Owner:
            id: int
            name: str

        owner, task = await commands.query_multiple_async(
            (
                f"select id, name from {owner_table_name}",
                f"select id, description, due_date, owner_id from {task_table_name}",
            ),
            models=(Owner, Task),
        )

        assert len(owner) == 1
        assert len(task) == 3
        assert isinstance(owner[0], Owner)
        assert all(isinstance(record, Task) for record in task)


class QueryFirstTestSuite:
    def test(self, commands: Commands, task_table_name):
        task = commands.query_first(f"select * from {task_table_name}")
        assert isinstance(task, dict)

    def test_param(self, commands: Commands, task_table_name):
        task = commands.query_first(f"select id from {task_table_name} where id = ?id?", param={"id": 1})
        assert task["id"] == 1


class QueryFirstAsyncTestSuite:
    @pytest.mark.asyncio
    async def test(self, commands: CommandsAsync, task_table_name):
        task = await commands.query_first_async(f"select * from {task_table_name}")
        assert isinstance(task, dict)

    @pytest.mark.asyncio
    async def test_param(self, commands: CommandsAsync, task_table_name):
        task = await commands.query_first_async(f"select id from {task_table_name} where id = ?id?", param={"id": 1})
        assert task["id"] == 1


class QueryFirstOrDefaultTestSuite:
    def test(self, commands: Commands, task_table_name):
        sentinel = object()
        task = commands.query_first_or_default(f"select * from {task_table_name} where id = 1000", default=sentinel)
        assert task is sentinel

    def test_param(self, commands: Commands, task_table_name):
        sentinel = object()
        task = commands.query_first_or_default(
            f"select * from {task_table_name} where id = ?id?", param={"id": 1000}, default=sentinel
        )
        assert task is sentinel


class QueryFirstOrDefaultAsyncTestSuite:
    @pytest.mark.asyncio
    async def test(self, commands: CommandsAsync, task_table_name):
        sentinel = object()
        task = await commands.query_first_or_default_async(
            f"select * from {task_table_name} where id = 1000", default=sentinel
        )
        assert task is sentinel

    @pytest.mark.asyncio
    async def test_param(self, commands: CommandsAsync, task_table_name):
        sentinel = object()
        task = await commands.query_first_or_default_async(
            f"select * from {task_table_name} where id = ?id?", param={"id": 1000}, default=sentinel
        )
        assert task is sentinel


class QuerySingleTestSuite:
    def test(self, commands: Commands, task_table_name):
        task = commands.query_single(f"select id from {task_table_name} where id = 1")
        assert task["id"] == 1

    def test_param(self, commands: Commands, task_table_name):
        task = commands.query_single(f"select id from {task_table_name} where id = ?id?", param={"id": 1})
        assert task["id"] == 1


class QuerySingleAsyncTestSuite:
    @pytest.mark.asyncio
    async def test(self, commands: CommandsAsync, task_table_name):
        task = await commands.query_single_async(f"select id from {task_table_name} where id = 1")
        assert task["id"] == 1

    @pytest.mark.asyncio
    async def test_param(self, commands: CommandsAsync, task_table_name):
        task = await commands.query_single_async(f"select id from {task_table_name} where id = ?id?", param={"id": 1})
        assert task["id"] == 1


class QuerySingleOrDefaultTestSuite:
    def test(self, commands: Commands, task_table_name):
        sentinel = object()
        task = commands.query_single_or_default(f"select * from {task_table_name} where id = 1000", default=sentinel)
        assert task is sentinel

    def test_param(self, commands: Commands, task_table_name):
        sentinel = object()
        task = commands.query_single_or_default(
            f"select * from {task_table_name} where id = ?id?", param={"id": 1000}, default=sentinel
        )
        assert task is sentinel


class QuerySingleOrDefaultAsyncTestSuite:
    @pytest.mark.asyncio
    async def test(self, commands: CommandsAsync, task_table_name):
        sentinel = object()
        task = await commands.query_single_or_default_async(
            f"select * from {task_table_name} where id = 1000", default=sentinel
        )
        assert task is sentinel

    @pytest.mark.asyncio
    async def test_param(self, commands: CommandsAsync, task_table_name):
        sentinel = object()
        task = await commands.query_single_or_default_async(
            f"select * from {task_table_name} where id = ?id?", param={"id": 1000}, default=sentinel
        )
        assert task is sentinel


class ExecuteScalarTestSuite:
    def test(self, commands: Commands, owner_table_name):
        owner_name = commands.execute_scalar(f"select name from {owner_table_name}")
        assert owner_name == "Zach Schumacher"

    def test_param(self, commands: Commands, task_table_name):
        first_task_description = commands.execute_scalar(
            f"select description from {task_table_name} where id = ?id?", param={"id": 1}
        )
        assert first_task_description == "Set up a test database"


class ExecuteScalarAsyncTestSuite:
    @pytest.mark.asyncio
    async def test(self, commands: CommandsAsync, owner_table_name):
        owner_name = await commands.execute_scalar_async(f"select name from {owner_table_name}")
        assert owner_name == "Zach Schumacher"

    @pytest.mark.asyncio
    async def test_param(self, commands: CommandsAsync, task_table_name):
        first_task_description = await commands.execute_scalar_async(
            f"select description from {task_table_name} where id = ?id?", param={"id": 1}
        )
        assert first_task_description == "Set up a test database"
