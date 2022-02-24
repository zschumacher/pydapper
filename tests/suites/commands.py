import datetime
from dataclasses import dataclass
from typing import AsyncGenerator

import pytest

from pydapper.commands import Commands
from pydapper.commands import CommandsAsync


class ExecuteTestSuite:
    def test_single(self, commands: Commands):
        assert (
            commands.execute("UPDATE owner SET name = ?new_name? WHERE id = ?id?", {"new_name": "Zachary", "id": "1"})
            == 1
        )

    def test_multiple(self, commands: Commands):
        assert (
            commands.execute(
                "INSERT INTO task (description, due_date, owner_id) " "VALUES (?description?, ?due_date?, ?owner_id?)",
                [
                    {"description": "new task", "due_date": datetime.date(2022, 1, 1), "owner_id": 1},
                    {"description": "another new task", "due_date": datetime.date(2022, 1, 1), "owner_id": 1},
                ],
            )
            == 2
        )


class ExecuteAsyncTestSuite:
    @pytest.mark.asyncio
    async def test_single(self, commands: CommandsAsync):
        assert (
            await commands.execute_async(
                "UPDATE owner SET name = ?new_name? WHERE id = ?id?", {"new_name": "Zachary", "id": "1"}
            )
            == 1
        )

    @pytest.mark.asyncio
    async def test_multiple(self, commands: CommandsAsync):
        assert (
            await commands.execute_async(
                "INSERT INTO task (description, due_date, owner_id) " "VALUES (?description?, ?due_date?, ?owner_id?)",
                [
                    {"description": "new task", "due_date": datetime.date(2022, 1, 1), "owner_id": 1},
                    {"description": "another new task", "due_date": datetime.date(2022, 1, 1), "owner_id": 1},
                ],
            )
            == 2
        )


class QueryTestSuite:
    def test(self, commands: Commands):
        data = commands.query("select * from task")
        assert len(data) == 3
        assert all(isinstance(record, dict) for record in data)

    def test_param(self, commands: Commands):
        data = commands.query(
            "select * from task where due_date = ?due_date?", param={"due_date": datetime.date(2021, 12, 31)}
        )
        assert len(data) == 2
        assert all(isinstance(record, dict) for record in data)

    def test_unbuffered(self, commands: Commands):
        generator = commands.query("select * from task", buffered=False)

        assert next(generator)
        assert next(generator)
        assert next(generator)

        with pytest.raises(StopIteration):
            next(generator)


class QueryAsyncTestSuite:
    @pytest.mark.asyncio
    async def test(self, commands: CommandsAsync):
        data = await commands.query_async("select * from task")
        print(data)
        assert len(data) == 3
        assert all(isinstance(record, dict) for record in data)

    @pytest.mark.asyncio
    async def test_param(self, commands: CommandsAsync):
        data = await commands.query_async(
            "select * from task where due_date = ?due_date?", param={"due_date": datetime.date(2021, 12, 31)}
        )
        assert len(data) == 2
        assert all(isinstance(record, dict) for record in data)

    @pytest.mark.asyncio
    async def test_unbuffered(self, commands: CommandsAsync):
        generator = await commands.query_async("select * from task", buffered=False)
        assert isinstance(generator, AsyncGenerator)

        data = [row async for row in generator]
        assert len(data) == 3


class QueryMultipleTestSuite:
    def test(self, commands: Commands):
        owner, task = commands.query_multiple(("select * from owner", "select * from task"))
        assert len(owner) == 1
        assert len(task) == 3
        assert isinstance(owner[0], dict)
        assert all(isinstance(record, dict) for record in task)

    def test_param(self, commands: Commands):
        owner, task = commands.query_multiple(
            ("select * from owner where id = ?id?", "select * from task where due_date = ?due_date?"),
            param={"id": 1, "due_date": datetime.date(2021, 12, 31)},
        )
        assert len(owner) == 1
        assert len(task) == 2
        assert isinstance(owner[0], dict)
        assert all(isinstance(record, dict) for record in task)

    def test_different_models(self, commands: Commands):
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
                'select id as "id", name as "name" from owner',
                'select id as "id", description as "description", due_date as "due_date", owner_id as "owner_id" '
                "from task",
            ),
            models=(Owner, Task),
        )

        assert len(owner) == 1
        assert len(task) == 3
        assert isinstance(owner[0], Owner)
        assert all(isinstance(record, Task) for record in task)


class QueryMultipleAsyncTestSuite:
    @pytest.mark.asyncio
    async def test(self, commands: CommandsAsync):
        owner, task = await commands.query_multiple_async(("select * from owner", "select * from task"))
        assert len(owner) == 1
        assert len(task) == 3
        assert isinstance(owner[0], dict)
        assert all(isinstance(record, dict) for record in task)

    @pytest.mark.asyncio
    async def test_param(self, commands: CommandsAsync):
        owner, task = await commands.query_multiple_async(
            ("select * from owner where id = ?id?", "select * from task where due_date = ?due_date?"),
            param={"id": 1, "due_date": datetime.date(2021, 12, 31)},
        )
        assert len(owner) == 1
        assert len(task) == 2
        assert isinstance(owner[0], dict)
        assert all(isinstance(record, dict) for record in task)

    @pytest.mark.asyncio
    async def test_different_models(self, commands: CommandsAsync):
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
                'select id as "id", name as "name" from owner',
                'select id as "id", description as "description", due_date as "due_date", owner_id as "owner_id" '
                "from task",
            ),
            models=(Owner, Task),
        )

        assert len(owner) == 1
        assert len(task) == 3
        assert isinstance(owner[0], Owner)
        assert all(isinstance(record, Task) for record in task)


class QueryFirstTestSuite:
    def test(self, commands: Commands):
        task = commands.query_first("select * from task")
        assert isinstance(task, dict)

    def test_param(self, commands: Commands):
        task = commands.query_first('select id as "id" from task where id = ?id?', param={"id": 1})
        assert task["id"] == 1


class QueryFirstAsyncTestSuite:
    @pytest.mark.asyncio
    async def test(self, commands: CommandsAsync):
        task = await commands.query_first_async("select * from task")
        assert isinstance(task, dict)

    @pytest.mark.asyncio
    async def test_param(self, commands: CommandsAsync):
        task = await commands.query_first_async('select id as "id" from task where id = ?id?', param={"id": 1})
        assert task["id"] == 1


class QueryFirstOrDefaultTestSuite:
    def test(self, commands: Commands):
        sentinel = object()
        task = commands.query_first_or_default("select * from task where id = 1000", default=sentinel)
        assert task is sentinel

    def test_param(self, commands: Commands):
        sentinel = object()
        task = commands.query_first_or_default(
            "select * from task where id = ?id?", param={"id": 1000}, default=sentinel
        )
        assert task is sentinel


class QueryFirstOrDefaultAsyncTestSuite:
    @pytest.mark.asyncio
    async def test(self, commands: CommandsAsync):
        sentinel = object()
        task = await commands.query_first_or_default_async("select * from task where id = 1000", default=sentinel)
        assert task is sentinel

    @pytest.mark.asyncio
    async def test_param(self, commands: CommandsAsync):
        sentinel = object()
        task = await commands.query_first_or_default_async(
            "select * from task where id = ?id?", param={"id": 1000}, default=sentinel
        )
        assert task is sentinel


class QuerySingleTestSuite:
    def test(self, commands: Commands):
        task = commands.query_single('select id as "id" from task where id = 1')
        assert task["id"] == 1

    def test_param(self, commands: Commands):
        task = commands.query_single('select id as "id" from task where id = ?id?', param={"id": 1})
        assert task["id"] == 1


class QuerySingleAsyncTestSuite:
    @pytest.mark.asyncio
    async def test(self, commands: CommandsAsync):
        task = await commands.query_single_async('select id as "id" from task where id = 1')
        assert task["id"] == 1

    @pytest.mark.asyncio
    async def test_param(self, commands: CommandsAsync):
        task = await commands.query_single_async('select id as "id" from task where id = ?id?', param={"id": 1})
        assert task["id"] == 1


class QuerySingleOrDefaultTestSuite:
    def test(self, commands: Commands):
        sentinel = object()
        task = commands.query_single_or_default("select * from task where id = 1000", default=sentinel)
        assert task is sentinel

    def test_param(self, commands: Commands):
        sentinel = object()
        task = commands.query_single_or_default(
            "select * from task where id = ?id?", param={"id": 1000}, default=sentinel
        )
        assert task is sentinel


class QuerySingleOrDefaultAsyncTestSuite:
    @pytest.mark.asyncio
    async def test(self, commands: CommandsAsync):
        sentinel = object()
        task = await commands.query_single_or_default_async("select * from task where id = 1000", default=sentinel)
        assert task is sentinel

    @pytest.mark.asyncio
    async def test_param(self, commands: CommandsAsync):
        sentinel = object()
        task = await commands.query_single_or_default_async(
            "select * from task where id = ?id?", param={"id": 1000}, default=sentinel
        )
        assert task is sentinel


class ExecuteScalarTestSuite:
    def test(self, commands: Commands):
        owner_name = commands.execute_scalar("select name from owner")
        assert owner_name == "Zach Schumacher"

    def test_param(self, commands: Commands):
        first_task_description = commands.execute_scalar(
            "select description from task where id = ?id?", param={"id": 1}
        )
        assert first_task_description == "Set up a test database"


class ExecuteScalarAsyncTestSuite:
    @pytest.mark.asyncio
    async def test(self, commands: CommandsAsync):
        owner_name = await commands.execute_scalar_async("select name from owner")
        assert owner_name == "Zach Schumacher"

    @pytest.mark.asyncio
    async def test_param(self, commands: CommandsAsync):
        first_task_description = await commands.execute_scalar_async(
            "select description from task where id = ?id?", param={"id": 1}
        )
        assert first_task_description == "Set up a test database"
