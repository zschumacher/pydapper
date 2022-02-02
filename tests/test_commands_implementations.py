import datetime
from dataclasses import dataclass

import pytest
from pytest_lazyfixture import lazy_fixture

command_fixtures = [
    lazy_fixture("psycopg2_commands"),
    lazy_fixture("pymssql_commands"),
    lazy_fixture("sqlite3_commands"),
    lazy_fixture("mysql_connector_python_commands"),
    lazy_fixture("cx_Oracle_commands"),
]

# NOTE: you may notice some tests write sql like `select id as "id"`.  This is because some rdbms' (like oracle)
# return all column names as upper case in cursor.description, so we have to force lowercase


@pytest.mark.parametrize("commands", command_fixtures)
class TestExecute:
    def test_single(self, commands):
        assert (
            commands.execute("UPDATE owner SET name = ?new_name? WHERE id = ?id?", {"new_name": "Zachary", "id": "1"})
            == 1
        )

    def test_multiple(self, commands):
        assert (
            commands.execute(
                "INSERT INTO task (description, due_date, owner_id) VALUES (?description?, ?due_date?, ?owner_id?)",
                [
                    {"description": "new task", "due_date": datetime.date(2022, 1, 1), "owner_id": 1},
                    {"description": "another new task", "due_date": datetime.date(2022, 1, 1), "owner_id": 1},
                ],
            )
            == 2
        )


@pytest.mark.parametrize("commands", command_fixtures)
class TestQuery:
    def test(self, commands):
        data = commands.query("select * from task")
        assert len(data) == 3
        assert all(isinstance(record, dict) for record in data)

    def test_param(self, commands):
        data = commands.query(
            "select * from task where due_date = ?due_date?", param={"due_date": datetime.date(2021, 12, 31)}
        )
        assert len(data) == 2
        assert all(isinstance(record, dict) for record in data)

    def test_unbuffered(self, commands):
        generator = commands.query("select * from task", buffered=False)

        assert next(generator)
        assert next(generator)
        assert next(generator)

        with pytest.raises(StopIteration):
            next(generator)


@pytest.mark.parametrize("commands", command_fixtures)
class TestQueryMultiple:
    def test(self, commands):
        owner, task = commands.query_multiple(("select * from owner", "select * from task"))
        assert len(owner) == 1
        assert len(task) == 3
        assert isinstance(owner[0], dict)
        assert all(isinstance(record, dict) for record in task)

    def test_param(self, commands):
        owner, task = commands.query_multiple(
            ("select * from owner where id = ?id?", "select * from task where due_date = ?due_date?"),
            param={"id": 1, "due_date": datetime.date(2021, 12, 31)},
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


@pytest.mark.parametrize("commands", command_fixtures)
class TestQueryFirst:
    def test(self, commands):
        task = commands.query_first("select * from task")
        assert isinstance(task, dict)

    def test_param(self, commands):
        task = commands.query_first('select id as "id" from task where id = ?id?', param={"id": 1})
        assert task["id"] == 1


@pytest.mark.parametrize("commands", command_fixtures)
class TestQueryFirstOrDefault:
    def test(self, commands):
        sentinel = object()
        task = commands.query_first_or_default("select * from task where id = 1000", default=sentinel)
        assert task is sentinel

    def test_param(self, commands):
        sentinel = object()
        task = commands.query_first_or_default(
            "select * from task where id = ?id?", param={"id": 1000}, default=sentinel
        )
        assert task is sentinel


@pytest.mark.parametrize("commands", command_fixtures)
class TestQuerySingle:
    def test(self, commands):
        task = commands.query_single('select id as "id" from task where id = 1')
        assert task["id"] == 1

    def test_param(self, commands):
        task = commands.query_single('select id as "id" from task where id = ?id?', param={"id": 1})
        assert task["id"] == 1


@pytest.mark.parametrize("commands", command_fixtures)
class TestQuerySingleOrDefault:
    def test(self, commands):
        sentinel = object()
        task = commands.query_single_or_default("select * from task where id = 1000", default=sentinel)
        assert task is sentinel

    def test_param(self, commands):
        sentinel = object()
        task = commands.query_single_or_default(
            "select * from task where id = ?id?", param={"id": 1000}, default=sentinel
        )
        assert task is sentinel


@pytest.mark.parametrize("commands", command_fixtures)
class TestExecuteScalar:
    def test(self, commands):
        owner_name = commands.execute_scalar("select name from owner")
        assert owner_name == "Zach Schumacher"

    def test_param(self, commands):
        first_task_description = commands.execute_scalar(
            "select description from task where id = ?id?", param={"id": 1}
        )
        assert first_task_description == "Set up a test database"
