import datetime
from dataclasses import dataclass
from decimal import Decimal

import pytest
from pymssql import _pymssql

from pydapper import connect
from pydapper import using
from pydapper.mssql.pymssql import PymssqlCommands


class TestExecute:
    def test_single(self, commands):
        assert (
            commands.execute(
                "UPDATE dbo.owner SET name = ?new_name? WHERE id = ?id?", {"new_name": "Zachary", "id": "1"}
            )
            == 1
        )

    def test_multiple(self, commands):
        assert (
            commands.execute(
                "INSERT INTO dbo.task (description, due_date, owner_id) VALUES (?description?, ?due_date?, ?owner_id?)",
                [
                    {"description": "new task", "due_date": "2022-01-01", "owner_id": 1},
                    {"description": "another new task", "due_date": "2022-01-01", "owner_id": 1},
                ],
            )
            == 2
        )


class TestQuery:
    def test(self, commands):
        data = commands.query("select * from task")
        assert len(data) == 3
        assert all(isinstance(record, dict) for record in data)

    def test_param(self, commands):
        data = commands.query("select * from dbo.task where due_date = ?due_date?", param={"due_date": "2021-12-31"})
        assert len(data) == 2
        assert all(isinstance(record, dict) for record in data)


class TestQueryMultiple:
    def test(self, commands):
        owner, task = commands.query_multiple(("select * from owner", "select * from task"))
        assert len(owner) == 1
        assert len(task) == 3
        assert isinstance(owner[0], dict)
        assert all(isinstance(record, dict) for record in task)

    def test_param(self, commands):
        owner, task = commands.query_multiple(
            ("select * from dbo.owner where id = ?id?", "select * from dbo.task where due_date = ?due_date?"),
            param={"id": 1, "due_date": "2021-12-31"},
        )
        assert len(owner) == 1
        assert len(task) == 2
        assert isinstance(owner[0], dict)
        assert all(isinstance(record, dict) for record in task)

    def test_different_models(self, commands):
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

        owner, task = commands.query_multiple(("select * from owner", "select * from task"), models=(Owner, Task))

        assert len(owner) == 1
        assert len(task) == 3
        assert isinstance(owner[0], Owner)
        assert all(isinstance(record, Task) for record in task)


class TestQueryFirst:
    def test(self, commands):
        task = commands.query_first("select * from task")
        assert isinstance(task, dict)

    def test_param(self, commands):
        task = commands.query_first("select * from dbo.task where id = ?id?", param={"id": 1})
        assert task["id"] == 1


class TestQueryFirstOrDefault:
    def test(self, commands):
        sentinel = object()
        task = commands.query_first_or_default("select * from dbo.task where id = 1000", default=sentinel)
        assert task is sentinel

    def test_param(self, commands):
        sentinel = object()
        task = commands.query_first_or_default(
            "select * from dbo.task where id = ?id?", param={"id": 1000}, default=sentinel
        )
        assert task is sentinel


class TestQuerySingle:
    def test(self, commands):
        task = commands.query_single("select * from dbo.task where id = 1")
        assert task["id"] == 1

    def test_param(self, commands):
        task = commands.query_single("select * from dbo.task where id = ?id?", param={"id": 1})
        assert task["id"] == 1


class TestQuerySingleOrDefault:
    def test(self, commands):
        sentinel = object()
        task = commands.query_single_or_default("select * from dbo.task where id = 1000", default=sentinel)
        assert task is sentinel

    def test_param(self, commands):
        sentinel = object()
        task = commands.query_single_or_default(
            "select * from dbo.task where id = ?id?", param={"id": 1000}, default=sentinel
        )
        assert task is sentinel


class TestExecuteScalar:
    def test(self, commands):
        owner_name = commands.execute_scalar("select name from owner")
        assert owner_name == "Zach Schumacher"

    def test_param(self, commands):
        first_task_description = commands.execute_scalar(
            "select description from dbo.task where id = ?id?", param={"id": 1}
        )
        assert first_task_description == "Set up a test database"


def test_using(application_connect_args_kwargs):
    args, kwargs = application_connect_args_kwargs
    with using(_pymssql.connect(*args, **kwargs)) as commands:
        assert isinstance(commands, PymssqlCommands)


def test_connect(application_dsn):
    with connect(application_dsn) as commands:
        assert isinstance(commands, PymssqlCommands)


class TestParamHandler:
    @pytest.mark.parametrize(
        "param, expected",
        [({"test": 1}, "%d"), ({"test": Decimal("5.6750000")}, "%d"), ({"test": datetime.date.today()}, "%s")],
    )
    def test_get_param_value(self, param, expected):
        handler = PymssqlCommands.SqlParamHandler("", param)
        assert handler.get_param_placeholder("test") == expected
