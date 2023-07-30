from types import SimpleNamespace

import pytest

from pydapper.exceptions import MoreThanOneResultException
from pydapper.exceptions import NoResultException
from tests.mocks import MockAsyncCommands
from tests.mocks import MockAsyncConnection
from tests.mocks import MockAsyncCursor
from tests.mocks import MockCommands
from tests.mocks import MockConnection
from tests.mocks import MockCursor
from tests.mocks import MockParamHandler

pytestmark = pytest.mark.core


class TestParamHandler:
    def test__init__validation(self):
        with pytest.raises(ValueError):
            MockParamHandler("sup", param=[SimpleNamespace(), dict()])

    def test_get_param_placeholder(self):
        handler = MockParamHandler("sup", None)
        assert handler.get_param_placeholder("sup") == "%s"

    def test_ordered_param_names(self):
        handler = MockParamHandler("?sup? ?hello? ?world? ?foo? ?bar?", None)
        assert handler.ordered_param_names == ("sup", "hello", "world", "foo", "bar")

    def test_ordered_param_values(self):
        handler = MockParamHandler(
            "?sup? ?hello? ?world? ?foo? ?bar?",
            {"sup": "dude", "hello": "world", "world": "hello", "foo": "bar", "bar": "foo"},
        )
        assert handler.ordered_param_values == ("dude", "world", "hello", "bar", "foo")

    def test_prepared_sql(self):
        handler = MockParamHandler("select * from table where id = ?id? and name = ?name?", {"id": 1, "name": "Zach"})
        assert handler.prepared_sql == "select * from table where id = %s and name = %s"

    def test_prepared_sql_no_matching_param(self):
        handler = MockParamHandler("select * from table", {"id": 1, "name": "Zach"})
        assert handler.prepared_sql == "select * from table"

    @pytest.mark.parametrize(
        "sql, param, expected",
        [
            ("select * from table", None, 0),
            ("select * from table where id = ?id?", {"id": 1}, 0),
            ("insert into table(?id?, ?name?)", [{"id": 1, "name": "Zach"}, {"id": 2, "name": "Bob"}], 2),
        ],
    )
    def test_execute(self, sql, param, expected):
        handler = MockParamHandler(sql, param)
        with MockCursor() as cursor:
            assert handler.execute(cursor) == expected

    @pytest.mark.asyncio
    @pytest.mark.parametrize(
        "sql, param, expected",
        [
            ("select * from table", None, 0),
            ("select * from table where id = ?id?", {"id": 1}, 0),
            ("insert into table(?id?, ?name?)", [{"id": 1, "name": "Zach"}, {"id": 2, "name": "Bob"}], 2),
        ],
    )
    async def test_execute_async(self, sql, param, expected):
        handler = MockParamHandler(sql, param)
        async with MockAsyncCursor() as cursor:
            assert await handler.execute_async(cursor) == expected


class TestCommands:
    @pytest.fixture
    def connection(self):
        return MockConnection()

    @pytest.fixture
    def set_fetchone_to_return_none(self, monkeypatch):
        monkeypatch.setattr(MockCursor, "fetchone", lambda self_: None)

    @pytest.fixture
    def set_fetchall_return_one(self, faker, monkeypatch):
        monkeypatch.setattr(MockCursor, "fetchall", lambda self_: ((1, faker.name()),))

    @pytest.fixture
    def set_fetchall_return_empty(self, monkeypatch):
        monkeypatch.setattr(MockCursor, "fetchall", lambda self_: tuple())

    def test__init__(self, connection):
        commands = MockCommands(connection)
        assert commands.connection is connection

    def test__enter__(self, connection):
        with MockCommands(connection) as commands:
            assert not commands.connection.closed

    def test__exit__(self, connection):
        with MockCommands(connection) as commands:
            pass
        assert commands.connection.closed

    def test_cursor(self, connection):
        assert isinstance(MockCommands(connection).cursor(), MockCursor)

    def test_execute(self, connection):
        with MockCommands(connection) as commands:
            affected_rows = commands.execute(
                "insert into some_table (id, name), (?id?, ?name?)", param={"id": 1, "name": "Zach"}
            )
        assert affected_rows == 1

    def test_query(self, connection):
        with MockCommands(connection) as commands:
            data = commands.query("select id, name from some_table", model=SimpleNamespace)
        assert len(data) == 2
        assert all(isinstance(row, SimpleNamespace) for row in data)

    def test_query_multiple(self, connection):
        with MockCommands(connection) as commands:
            data1, data2 = commands.query_multiple(
                ("select id, name from some_table", "select id, name from another_table"),
                models=(SimpleNamespace, dict),
            )
        assert len(data1) == 2
        assert len(data2) == 2
        assert not data1 == data2
        assert all(isinstance(row, SimpleNamespace) for row in data1)
        assert all(isinstance(row, dict) for row in data2)

    @pytest.mark.parametrize(
        "sql, models",
        [
            (("select * from some_table", "select * from another"), (dict,)),  # more queries than models
            ("select * from some_table;", (dict, dict)),  # more models than queries
        ],
    )
    def test_query_multiple_validation(self, connection, sql, models):
        with MockCommands(connection) as commands, pytest.raises(ValueError):
            commands.query_multiple(sql, models=models)

    def test_query_multiple_raises(self, connection, set_fetchall_return_empty):
        with pytest.raises(NoResultException):
            with MockCommands(connection) as commands:
                commands.query_multiple(("select * from whatever",))

    def test_query_first(self, connection):
        with MockCommands(connection) as commands:
            record = commands.query_first("select id, name from some_table", model=SimpleNamespace)
        assert isinstance(record, SimpleNamespace)
        assert record.id
        assert record.name

    def test_query_first_raises_on_no_result(self, connection, set_fetchone_to_return_none):
        with MockCommands(connection) as commands, pytest.raises(NoResultException):
            commands.query_first("select * from some_table")

    def test_query_first_or_default(self, connection, set_fetchone_to_return_none):
        default = SimpleNamespace(id=10, name="default")
        with MockCommands(connection) as commands:
            data = commands.query_first_or_default("select * from some_table", default=default)
        assert data is default

    def test_query_single(self, connection, set_fetchall_return_one):
        with MockCommands(connection) as commands:
            record = commands.query_single("select * from some_table")
        assert isinstance(record, dict)
        assert record["id"]
        assert record["name"]

    def test_query_single_raises_on_no_result(self, connection, set_fetchall_return_empty):
        with MockCommands(connection) as commands, pytest.raises(NoResultException):
            commands.query_single("select * from some_table")

    def test_query_single_raises_on_many_results(self, connection):
        with MockCommands(connection) as commands, pytest.raises(MoreThanOneResultException):
            commands.query_single("select * from some_table")

    def test_query_single_or_default(self, connection, set_fetchall_return_empty):
        default = SimpleNamespace(id=10, name="default")
        with MockCommands(connection) as commands:
            record = commands.query_single_or_default("select * from some_table", default=default)
        assert record is default

    def test_execute_scalar(self, connection):
        with MockCommands(connection) as commands:
            id_ = commands.execute_scalar("select id, name from some_table")
        assert id_ == 1

    def test_execute_scalar_raises_on_no_result(self, connection, set_fetchone_to_return_none):
        with MockCommands(connection) as commands, pytest.raises(NoResultException):
            commands.execute_scalar("select * from some_table")


class TestCommandsAsync:
    @pytest.fixture
    def connection(self):
        return MockAsyncConnection()

    @pytest.fixture
    def set_fetchone_to_return_none(self, mocker):
        async def fetchone(s):
            return None

        mocker.patch("tests.mocks.MockAsyncCursor.fetchone", fetchone)

    @pytest.fixture
    def set_fetchall_return_one(self, faker, mocker):
        async def fetchall(s):
            return ((1, faker.name()),)

        mocker.patch("tests.mocks.MockAsyncCursor.fetchall", fetchall)

    @pytest.fixture
    def set_fetchall_return_empty(self, mocker):
        async def fetchall(s):
            return tuple()

        mocker.patch("tests.mocks.MockAsyncCursor.fetchall", fetchall)

    @pytest.mark.asyncio
    async def test__aenter__(self, connection):
        async with MockAsyncCommands(connection) as commands:
            assert not commands.connection.closed

    @pytest.mark.asyncio
    async def test__aexit__(self, connection):
        async with MockAsyncCommands(connection) as commands:
            pass
        assert commands.connection.closed

    @pytest.mark.asyncio
    async def test_cursor(self, connection):
        cursor = await MockAsyncCommands(connection).cursor()
        assert isinstance(cursor, MockAsyncCursor)

    @pytest.mark.asyncio
    async def test_execute(self, connection):
        async with MockAsyncCommands(connection) as commands:
            affected_rows = await commands.execute_async(
                "insert into some_table (id, name), (?id?, ?name?)", param={"id": 1, "name": "Zach"}
            )
        assert affected_rows == 1

    @pytest.mark.asyncio
    async def test_query(self, connection):
        async with MockAsyncCommands(connection) as commands:
            data = await commands.query_async("select id, name from some_table", model=SimpleNamespace)
        assert len(data) == 2
        assert all(isinstance(row, SimpleNamespace) for row in data)

    @pytest.mark.asyncio
    async def test_query_multiple(self, connection):
        async with MockAsyncCommands(connection) as commands:
            data1, data2 = await commands.query_multiple_async(
                ("select id, name from some_table", "select id, name from another_table"),
                models=(SimpleNamespace, dict),
            )
        assert len(data1) == 2
        assert len(data2) == 2
        assert not data1 == data2
        assert all(isinstance(row, SimpleNamespace) for row in data1)
        assert all(isinstance(row, dict) for row in data2)

    @pytest.mark.asyncio
    @pytest.mark.parametrize(
        "sql, models",
        [
            (("select * from some_table", "select * from another"), (dict,)),  # more queries than models
            ("select * from some_table;", (dict, dict)),  # more models than queries
        ],
    )
    async def test_query_multiple_validation(self, connection, sql, models):
        async with MockAsyncCommands(connection) as commands:
            with pytest.raises(ValueError):
                await commands.query_multiple_async(sql, models=models)

    @pytest.mark.asyncio
    async def test_query_multiple_raises(self, connection, set_fetchall_return_empty):
        async with MockAsyncCommands(connection) as commands:
            with pytest.raises(NoResultException):
                await commands.query_multiple_async(("select * from whatever",))

    @pytest.mark.asyncio
    async def test_query_first(self, connection):
        async with MockAsyncCommands(connection) as commands:
            record = await commands.query_first_async("select id, name from some_table", model=SimpleNamespace)
        assert isinstance(record, SimpleNamespace)
        assert record.id
        assert record.name

    @pytest.mark.asyncio
    async def test_query_first_raises_on_no_result(self, connection, set_fetchone_to_return_none):
        async with MockAsyncCommands(connection) as commands:
            with pytest.raises(NoResultException):
                await commands.query_first_async("select * from some_table")

    @pytest.mark.asyncio
    async def test_query_first_or_default(self, connection, set_fetchone_to_return_none):
        default = SimpleNamespace(id=10, name="default")
        async with MockAsyncCommands(connection) as commands:
            data = await commands.query_first_or_default_async("select * from some_table", default=default)
        assert data is default

    @pytest.mark.asyncio
    async def test_query_single(self, connection, set_fetchall_return_one):
        async with MockAsyncCommands(connection) as commands:
            record = await commands.query_single_async("select * from some_table")
        assert isinstance(record, dict)
        assert record["id"]
        assert record["name"]

    @pytest.mark.asyncio
    async def test_query_single_raises_on_no_result(self, connection, set_fetchall_return_empty):
        async with MockAsyncCommands(connection) as commands:
            with pytest.raises(NoResultException):
                await commands.query_single_async("select * from some_table")

    @pytest.mark.asyncio
    async def test_query_single_raises_on_many_results(self, connection):
        async with MockAsyncCommands(connection) as commands:
            with pytest.raises(MoreThanOneResultException):
                await commands.query_single_async("select * from some_table")

    @pytest.mark.asyncio
    async def test_query_single_or_default(self, connection, set_fetchall_return_empty):
        default = SimpleNamespace(id=10, name="default")
        async with MockAsyncCommands(connection) as commands:
            record = await commands.query_single_or_default_async("select * from some_table", default=default)
        assert record is default

    @pytest.mark.asyncio
    async def test_execute_scalar(self, connection):
        async with MockAsyncCommands(connection) as commands:
            id_ = await commands.execute_scalar_async("select id, name from some_table")
        assert id_ == 1

    @pytest.mark.asyncio
    async def test_execute_scalar_raises_on_no_result(self, connection, set_fetchone_to_return_none):
        async with MockAsyncCommands(connection) as commands:
            with pytest.raises(NoResultException):
                await commands.execute_scalar_async("select * from some_table")
