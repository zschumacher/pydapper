import asyncio
import logging
from collections import UserDict
from dataclasses import FrozenInstanceError
from dataclasses import asdict
from dataclasses import dataclass
from types import MappingProxyType
from types import SimpleNamespace

import pytest

import pydapper
from pydapper import RawRow
from pydapper._context import _AwaitableAsyncContextManager
from pydapper.capabilities import AdapterCapability
from pydapper.command_options import CommandKind
from pydapper.exceptions import DuplicateColumnException
from pydapper.exceptions import InvalidParameterShapeException
from pydapper.exceptions import MissingParameterException
from pydapper.exceptions import MoreThanOneResultException
from pydapper.exceptions import NoResultException
from pydapper.exceptions import PyDapperException
from pydapper.exceptions import RowMappingException
from pydapper.exceptions import UnsupportedFeatureError
from tests.mocks import MockAsyncCommands
from tests.mocks import MockAsyncConnection
from tests.mocks import MockAsyncCursor
from tests.mocks import MockCommands
from tests.mocks import MockConnection
from tests.mocks import MockCursor
from tests.mocks import MockParamHandler

pytestmark = pytest.mark.core


def _debug_records(caplog):
    return [record for record in caplog.records if record.levelno == logging.DEBUG]


# a cleanup failure that is a BaseException but not an Exception is never discarded by the shared
# cursor lifecycle: KeyboardInterrupt/SystemExit are interpreter-level requests to stop and
# CancelledError/GeneratorExit are the runtime unwinding the command on purpose
_NON_EXCEPTION_CLEANUP_FAILURES = [KeyboardInterrupt, SystemExit, asyncio.CancelledError, GeneratorExit]


class FalsyRow(tuple):
    def __bool__(self):
        return False


@dataclass
class TaskParams:
    id: int
    active: bool = True
    name: str = "task"
    ids: list[int] | None = None


class _QuerySingleFetchOneCursor:
    rowcount = 0
    description = ("id", "int"), ("name", "text")

    def __init__(self, rows):
        self.fetchall_calls = 0
        self.fetchone_calls = 0
        self.rows = list(rows)

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        pass

    def execute(self, sql, parameters=None):
        pass

    def fetchall(self):
        self.fetchall_calls += 1
        return tuple()

    def fetchone(self):
        self.fetchone_calls += 1
        return self.rows.pop(0) if self.rows else None


class _QuerySingleFetchManyCursor(_QuerySingleFetchOneCursor):
    def __init__(self, rows):
        super().__init__(rows)
        self.fetchmany_calls = []

    def fetchmany(self, size=None):
        self.fetchmany_calls.append(size)
        return tuple(self.rows[:size])


class _QuerySingleConnection:
    def __init__(self, cursor):
        self.cursor_instance = cursor

    def cursor(self, *args, **kwargs):
        return self.cursor_instance


class _DuplicateColumnCursor:
    rowcount = 0
    description = ("id", "int"), ("name", "text"), ("id", "int")

    def __init__(self, rows=((1, "Zach", 2),)):
        self.rows = list(rows)

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        pass

    def execute(self, sql, parameters=None):
        pass

    def fetchall(self):
        return tuple(self.rows)

    def fetchmany(self, size=None):
        return tuple(self.rows[:size])

    def fetchone(self):
        return self.rows.pop(0) if self.rows else None


class _CursorConnection:
    def __init__(self, cursor):
        self.cursor_instance = cursor

    def cursor(self, *args, **kwargs):
        return self.cursor_instance


class _PlainQueryCursor:
    description = ("id", "int"), ("name", "text")
    rowcount = 0

    def __init__(self, rows=((1, "Zach"), (2, "Bob"))):
        self.rows = list(rows)
        self.close_calls = 0
        self.execute_error = None
        self.fetchall_error = None
        self.fetchone_error = None
        self.close_error = None

    def execute(self, sql, parameters=None):
        if self.execute_error:
            raise self.execute_error

    def fetchall(self):
        if self.fetchall_error:
            raise self.fetchall_error
        return tuple(self.rows)

    def fetchone(self):
        if self.fetchone_error:
            raise self.fetchone_error
        return self.rows.pop(0) if self.rows else None

    def close(self):
        self.close_calls += 1
        if self.close_error:
            raise self.close_error


class _PlainAsyncQueryCursor:
    description = ("id", "int"), ("name", "text")
    rowcount = 0

    def __init__(self, rows=((1, "Zach"), (2, "Bob"))):
        self.rows = list(rows)
        self.close_calls = 0
        self.execute_error = None
        self.fetchall_error = None
        self.fetchone_error = None
        self.close_error = None

    async def execute(self, sql, parameters=None):
        if self.execute_error:
            raise self.execute_error

    async def fetchall(self):
        if self.fetchall_error:
            raise self.fetchall_error
        return tuple(self.rows)

    async def fetchone(self):
        if self.fetchone_error:
            raise self.fetchone_error
        return self.rows.pop(0) if self.rows else None

    async def close(self):
        self.close_calls += 1
        if self.close_error:
            raise self.close_error


class _PlainAsyncQueryConnection:
    def __init__(self, cursor):
        self.cursor_instance = cursor

    async def cursor(self, *args, **kwargs):
        return self.cursor_instance


class _TrackingContextCursor:
    rowcount = 0
    description = ("id", "int"), ("name", "text")

    def __init__(self):
        self.entered = False
        self.exited = False
        self.rows = [(1, "Zach")]

    def __enter__(self):
        self.entered = True
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        self.exited = True

    def execute(self, sql, parameters=None):
        pass

    def fetchall(self):
        return tuple(self.rows)

    def fetchone(self):
        return self.rows.pop(0) if self.rows else None


class _AsyncQuerySingleFetchOneCursor:
    rowcount = 0
    description = ("id", "int"), ("name", "text")

    def __init__(self, rows):
        self.fetchall_calls = 0
        self.fetchone_calls = 0
        self.rows = list(rows)

    async def __aenter__(self):
        return self

    async def __aexit__(self, exc_type, exc_val, exc_tb):
        pass

    async def execute(self, sql, parameters=None):
        pass

    async def fetchall(self):
        self.fetchall_calls += 1
        return tuple()

    async def fetchone(self):
        self.fetchone_calls += 1
        return self.rows.pop(0) if self.rows else None


class _AsyncQuerySingleFetchManyCursor(_AsyncQuerySingleFetchOneCursor):
    def __init__(self, rows):
        super().__init__(rows)
        self.fetchmany_calls = []

    async def fetchmany(self, size=None):
        self.fetchmany_calls.append(size)
        return tuple(self.rows[:size])


class _AsyncQuerySingleConnection:
    def __init__(self, cursor):
        self.cursor_instance = cursor

    async def cursor(self, *args, **kwargs):
        return self.cursor_instance


class _AsyncDuplicateColumnCursor:
    rowcount = 0
    description = ("id", "int"), ("name", "text"), ("id", "int")

    def __init__(self, rows=((1, "Zach", 2),)):
        self.rows = list(rows)

    async def __aenter__(self):
        return self

    async def __aexit__(self, exc_type, exc_val, exc_tb):
        pass

    async def execute(self, sql, parameters=None):
        pass

    async def fetchall(self):
        return tuple(self.rows)

    async def fetchmany(self, size=None):
        return tuple(self.rows[:size])

    async def fetchone(self):
        return self.rows.pop(0) if self.rows else None


class _AsyncCursorConnection:
    def __init__(self, cursor):
        self.closed = 0
        self.cursor_instance = cursor

    async def __aenter__(self):
        return self

    async def __aexit__(self, exc_type, exc_val, exc_tb):
        await self.close()

    async def cursor(self, *args, **kwargs):
        return self.cursor_instance

    async def close(self):
        self.closed = 1


class _MultiQueryExitCursor:
    """Scripts per-query outcomes for query_multiple and records the native cursor lifecycle."""

    rowcount = 0

    def __init__(
        self,
        fetch_results=(((1, "Zach"),), ((2, "Bob"),)),
        *,
        execute_errors=(),
        descriptions=None,
        exit_error=None,
        exit_return=None,
    ):
        self.events = []
        self.exit_calls = 0
        self.exit_args = None
        self._fetch_results = tuple(fetch_results)
        self._execute_errors = tuple(execute_errors)
        self._descriptions = descriptions
        self._exit_error = exit_error
        self._exit_return = exit_return
        self._query_index = -1

    @property
    def description(self):
        if self._descriptions is not None:
            return self._descriptions[self._query_index]
        return ("id", "int"), ("name", "text")

    def __enter__(self):
        self.events.append("enter")
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        self.exit_calls += 1
        self.exit_args = exc_type, exc_val, exc_tb
        self.exit_tb_was_active = exc_val is not None and exc_tb is exc_val.__traceback__
        self.events.append(("exit", exc_type))
        if self._exit_error is not None:
            raise self._exit_error
        return self._exit_return

    def execute(self, sql, parameters=None):
        self._query_index += 1
        self.events.append(("execute", self._query_index))
        if self._query_index < len(self._execute_errors):
            error = self._execute_errors[self._query_index]
            if error is not None:
                raise error

    def fetchall(self):
        self.events.append(("fetchall", self._query_index))
        result = self._fetch_results[self._query_index]
        if isinstance(result, BaseException):
            raise result
        return result


class _AsyncMultiQueryExitCursor:
    """Scripts per-query outcomes for query_multiple_async and records the native cursor lifecycle."""

    rowcount = 0

    def __init__(
        self,
        fetch_results=(((1, "Zach"),), ((2, "Bob"),)),
        *,
        execute_errors=(),
        descriptions=None,
        exit_error=None,
        exit_return=None,
    ):
        self.events = []
        self.exit_calls = 0
        self.exit_args = None
        self._fetch_results = tuple(fetch_results)
        self._execute_errors = tuple(execute_errors)
        self._descriptions = descriptions
        self._exit_error = exit_error
        self._exit_return = exit_return
        self._query_index = -1

    @property
    def description(self):
        if self._descriptions is not None:
            return self._descriptions[self._query_index]
        return ("id", "int"), ("name", "text")

    async def __aenter__(self):
        self.events.append("enter")
        return self

    async def __aexit__(self, exc_type, exc_val, exc_tb):
        self.exit_calls += 1
        self.exit_args = exc_type, exc_val, exc_tb
        self.exit_tb_was_active = exc_val is not None and exc_tb is exc_val.__traceback__
        self.events.append(("exit", exc_type))
        if self._exit_error is not None:
            raise self._exit_error
        return self._exit_return

    async def execute(self, sql, parameters=None):
        self._query_index += 1
        self.events.append(("execute", self._query_index))
        if self._query_index < len(self._execute_errors):
            error = self._execute_errors[self._query_index]
            if error is not None:
                raise error

    async def fetchall(self):
        self.events.append(("fetchall", self._query_index))
        result = self._fetch_results[self._query_index]
        if isinstance(result, BaseException):
            raise result
        return result


def _assert_duplicate_column_exception(exc_info):
    assert exc_info.value.columns == ("id", "name", "id")
    assert exc_info.value.duplicate_columns == ("id",)
    assert exc_info.value.duplicate_indexes == (0, 2)


class TestRawRow:
    def test_mapper_alias_resolves_runtime_type_hints_without_raw_row_import(self):
        namespace = {}

        exec(
            "import pydapper\n"
            "from typing import get_type_hints\n"
            "def f(mapper: pydapper.Mapper[int]) -> None:\n"
            "    pass\n"
            "hints = get_type_hints(f)\n",
            namespace,
        )

        assert namespace["hints"]["mapper"] == pydapper.Mapper[int]

    def test_columns_and_values_are_tuples_in_driver_order(self):
        row = RawRow(["id", "name"], [1, "Zach"])

        assert row.columns == ("id", "name")
        assert row.values == (1, "Zach")

    def test_duplicate_columns_are_preserved(self):
        row = RawRow(("id", "name", "id"), (1, "Zach", 2))

        assert row.columns == ("id", "name", "id")
        assert row.values == (1, "Zach", 2)

    def test_as_dict_returns_dict_for_unique_columns(self):
        row = RawRow(("id", "name"), (1, "Zach"))

        assert row.as_dict() == {"id": 1, "name": "Zach"}

    def test_as_dict_raises_duplicate_column_exception_for_duplicate_columns(self):
        row = RawRow(("id", "name", "id"), (1, "Zach", 2))

        with pytest.raises(DuplicateColumnException) as exc_info:
            row.as_dict()

        _assert_duplicate_column_exception(exc_info)

    def test_positional_and_name_access(self):
        row = RawRow(("id", "name"), (1, "Zach"))

        assert row[0] == 1
        assert row["name"] == "Zach"

    def test_column_indexes_are_lazily_created_and_reused(self):
        row = RawRow(("id", "name"), (1, "Zach"))

        assert row._column_indexes is None
        assert row[0] == 1
        assert row._column_indexes is None

        assert row["name"] == "Zach"
        column_indexes = row._column_indexes
        assert isinstance(column_indexes, MappingProxyType)
        assert column_indexes == {"id": (0,), "name": (1,)}
        assert row.as_dict() == {"id": 1, "name": "Zach"}
        assert asdict(row) == {"columns": ("id", "name"), "values": (1, "Zach")}
        assert row._column_indexes is column_indexes

        with pytest.raises(TypeError):
            column_indexes["id"] = (2,)

    def test_slice_access_returns_values_slice(self):
        row = RawRow(("id", "name"), (1, "Zach"))

        assert row[0:1] == (1,)

    def test_name_access_raises_for_duplicate_column_name(self):
        row = RawRow(("id", "name", "id"), (1, "Zach", 2))

        with pytest.raises(DuplicateColumnException) as exc_info:
            row["id"]

        _assert_duplicate_column_exception(exc_info)

    def test_as_dict_duplicate_indexes_are_globally_ordered(self):
        row = RawRow(("a", "b", "a", "b"), (1, 2, 3, 4))

        with pytest.raises(DuplicateColumnException) as exc_info:
            row.as_dict()

        assert exc_info.value.columns == ("a", "b", "a", "b")
        assert exc_info.value.duplicate_columns == ("a", "b")
        assert exc_info.value.duplicate_indexes == (0, 1, 2, 3)

    def test_name_access_raises_key_error_for_missing_column_name(self):
        row = RawRow(("id", "name"), (1, "Zach"))

        with pytest.raises(KeyError, match="missing"):
            row["missing"]

    def test_row_is_immutable(self):
        row = RawRow(("id",), (1,))

        with pytest.raises(FrozenInstanceError):
            row.columns = ("other",)

    def test_columns_and_values_must_have_same_length(self):
        with pytest.raises(ValueError, match="same length"):
            RawRow(("id",), ())


@pytest.fixture
def captured_handler_params(monkeypatch):
    captured = []
    original_init = MockParamHandler.__init__

    def capture_init(self, sql, param=None):
        captured.append(param)
        original_init(self, sql, param)

    monkeypatch.setattr(MockParamHandler, "__init__", capture_init)
    return captured


SYNC_PARAMS_CALLS = [
    pytest.param(
        lambda commands, params: commands.execute("insert into some_table (id) values (?id?)", params=params),
        1,
        id="execute",
    ),
    pytest.param(
        lambda commands, params: commands.query("select id, name from some_table where id = ?id?", params=params),
        1,
        id="query",
    ),
    pytest.param(
        lambda commands, params: commands.query_multiple(
            (
                "select id, name from some_table where id = ?id?",
                "select id, name from another_table where id = ?id?",
            ),
            params=params,
        ),
        2,
        id="query_multiple",
    ),
    pytest.param(
        lambda commands, params: commands.query_first("select id, name from some_table where id = ?id?", params=params),
        1,
        id="query_first",
    ),
    pytest.param(
        lambda commands, params: commands.query_first_or_default(
            "select id, name from some_table where id = ?id?", None, params=params
        ),
        1,
        id="query_first_or_default",
    ),
    pytest.param(
        lambda commands, params: commands.query_single(
            "select id, name from some_table where id = ?id?", params=params
        ),
        1,
        id="query_single",
    ),
    pytest.param(
        lambda commands, params: commands.query_single_or_default(
            "select id, name from some_table where id = ?id?", None, params=params
        ),
        1,
        id="query_single_or_default",
    ),
    pytest.param(
        lambda commands, params: commands.execute_scalar("select id from some_table where id = ?id?", params=params),
        1,
        id="execute_scalar",
    ),
]

SYNC_ALIAS_CONFLICT_CALLS = [
    pytest.param(
        lambda commands, params: commands.execute(
            "insert into some_table (id) values (?id?)", param=params, params=params
        ),
        id="execute",
    ),
    pytest.param(
        lambda commands, params: commands.query(
            "select id, name from some_table where id = ?id?", param=params, params=params
        ),
        id="query",
    ),
    pytest.param(
        lambda commands, params: commands.query_multiple(
            ("select id, name from some_table where id = ?id?",), param=params, params=params
        ),
        id="query_multiple",
    ),
    pytest.param(
        lambda commands, params: commands.query_first(
            "select id, name from some_table where id = ?id?", param=params, params=params
        ),
        id="query_first",
    ),
    pytest.param(
        lambda commands, params: commands.query_first_or_default(
            "select id, name from some_table where id = ?id?", None, param=params, params=params
        ),
        id="query_first_or_default",
    ),
    pytest.param(
        lambda commands, params: commands.query_single(
            "select id, name from some_table where id = ?id?", param=params, params=params
        ),
        id="query_single",
    ),
    pytest.param(
        lambda commands, params: commands.query_single_or_default(
            "select id, name from some_table where id = ?id?", None, param=params, params=params
        ),
        id="query_single_or_default",
    ),
    pytest.param(
        lambda commands, params: commands.execute_scalar(
            "select id from some_table where id = ?id?", param=params, params=params
        ),
        id="execute_scalar",
    ),
]

ASYNC_PARAMS_CALLS = [
    pytest.param(
        lambda commands, params: commands.execute_async("insert into some_table (id) values (?id?)", params=params),
        1,
        id="execute_async",
    ),
    pytest.param(
        lambda commands, params: commands.query_async("select id, name from some_table where id = ?id?", params=params),
        1,
        id="query_async",
    ),
    pytest.param(
        lambda commands, params: commands.query_multiple_async(
            (
                "select id, name from some_table where id = ?id?",
                "select id, name from another_table where id = ?id?",
            ),
            params=params,
        ),
        2,
        id="query_multiple_async",
    ),
    pytest.param(
        lambda commands, params: commands.query_first_async(
            "select id, name from some_table where id = ?id?", params=params
        ),
        1,
        id="query_first_async",
    ),
    pytest.param(
        lambda commands, params: commands.query_first_or_default_async(
            "select id, name from some_table where id = ?id?", None, params=params
        ),
        1,
        id="query_first_or_default_async",
    ),
    pytest.param(
        lambda commands, params: commands.query_single_async(
            "select id, name from some_table where id = ?id?", params=params
        ),
        1,
        id="query_single_async",
    ),
    pytest.param(
        lambda commands, params: commands.query_single_or_default_async(
            "select id, name from some_table where id = ?id?", None, params=params
        ),
        1,
        id="query_single_or_default_async",
    ),
    pytest.param(
        lambda commands, params: commands.execute_scalar_async(
            "select id from some_table where id = ?id?", params=params
        ),
        1,
        id="execute_scalar_async",
    ),
]

ASYNC_ALIAS_CONFLICT_CALLS = [
    pytest.param(
        lambda commands, params: commands.execute_async(
            "insert into some_table (id) values (?id?)", param=params, params=params
        ),
        id="execute_async",
    ),
    pytest.param(
        lambda commands, params: commands.query_async(
            "select id, name from some_table where id = ?id?", param=params, params=params
        ),
        id="query_async",
    ),
    pytest.param(
        lambda commands, params: commands.query_multiple_async(
            ("select id, name from some_table where id = ?id?",), param=params, params=params
        ),
        id="query_multiple_async",
    ),
    pytest.param(
        lambda commands, params: commands.query_first_async(
            "select id, name from some_table where id = ?id?", param=params, params=params
        ),
        id="query_first_async",
    ),
    pytest.param(
        lambda commands, params: commands.query_first_or_default_async(
            "select id, name from some_table where id = ?id?", None, param=params, params=params
        ),
        id="query_first_or_default_async",
    ),
    pytest.param(
        lambda commands, params: commands.query_single_async(
            "select id, name from some_table where id = ?id?", param=params, params=params
        ),
        id="query_single_async",
    ),
    pytest.param(
        lambda commands, params: commands.query_single_or_default_async(
            "select id, name from some_table where id = ?id?", None, param=params, params=params
        ),
        id="query_single_or_default_async",
    ),
    pytest.param(
        lambda commands, params: commands.execute_scalar_async(
            "select id from some_table where id = ?id?", param=params, params=params
        ),
        id="execute_scalar_async",
    ),
]


SYNC_READ_LIST_PARAMS_CALLS = [
    pytest.param(
        lambda commands: commands.query("select id, name from some_table where id = ?id?", params=[]),
        id="query",
    ),
    pytest.param(
        lambda commands: commands.query_multiple(("select id, name from some_table where id = ?id?",), params=[]),
        id="query_multiple",
    ),
    pytest.param(
        lambda commands: commands.query_first("select id, name from some_table where id = ?id?", params=[]),
        id="query_first",
    ),
    pytest.param(
        lambda commands: commands.query_first_or_default(
            "select id, name from some_table where id = ?id?", None, params=[]
        ),
        id="query_first_or_default",
    ),
    pytest.param(
        lambda commands: commands.query_single("select id, name from some_table where id = ?id?", params=[]),
        id="query_single",
    ),
    pytest.param(
        lambda commands: commands.query_single_or_default(
            "select id, name from some_table where id = ?id?", None, params=[]
        ),
        id="query_single_or_default",
    ),
    pytest.param(
        lambda commands: commands.execute_scalar("select id from some_table where id = ?id?", params=[]),
        id="execute_scalar",
    ),
]


ASYNC_READ_LIST_PARAMS_CALLS = [
    pytest.param(
        lambda commands: commands.query_async("select id, name from some_table where id = ?id?", params=[]),
        id="query_async",
    ),
    pytest.param(
        lambda commands: commands.query_multiple_async(("select id, name from some_table where id = ?id?",), params=[]),
        id="query_multiple_async",
    ),
    pytest.param(
        lambda commands: commands.query_first_async("select id, name from some_table where id = ?id?", params=[]),
        id="query_first_async",
    ),
    pytest.param(
        lambda commands: commands.query_first_or_default_async(
            "select id, name from some_table where id = ?id?", None, params=[]
        ),
        id="query_first_or_default_async",
    ),
    pytest.param(
        lambda commands: commands.query_single_async("select id, name from some_table where id = ?id?", params=[]),
        id="query_single_async",
    ),
    pytest.param(
        lambda commands: commands.query_single_or_default_async(
            "select id, name from some_table where id = ?id?", None, params=[]
        ),
        id="query_single_or_default_async",
    ),
    pytest.param(
        lambda commands: commands.execute_scalar_async("select id from some_table where id = ?id?", params=[]),
        id="execute_scalar_async",
    ),
]


class TestPublicExceptions:
    @pytest.mark.parametrize(
        "exception_type",
        [
            DuplicateColumnException,
            NoResultException,
            MoreThanOneResultException,
            MissingParameterException,
            InvalidParameterShapeException,
            UnsupportedFeatureError,
            RowMappingException,
        ],
    )
    def test_public_exceptions_subclass_pydapper_exception(self, exception_type):
        assert issubclass(exception_type, PyDapperException)

    def test_duplicate_column_exception_subclasses_row_mapping_exception(self):
        assert issubclass(DuplicateColumnException, RowMappingException)


class TestParamHandler:
    @pytest.mark.parametrize("param", [1, "task", ("id", 1), {"id"}, object(), [1], TaskParams])
    def test__init__rejects_invalid_param_shapes(self, param):
        with pytest.raises(InvalidParameterShapeException):
            MockParamHandler("select * from table where id = ?id?", param=param)

    def test__init__allows_mixed_executemany_record_types(self):
        handler = MockParamHandler(
            "insert into table (id) values (?id?)",
            [SimpleNamespace(id=1), {"id": 2}, TaskParams(id=3)],
        )

        assert handler.ordered_param_values == [(1,), (2,), (3,)]

    def test_default_param_handler_get_param_placeholder(self):
        from pydapper.commands import DefaultSqlParamHandler

        handler = DefaultSqlParamHandler("sup", None)
        assert handler.get_param_placeholder("sup") == "%s"

    def test_get_param_placeholder(self):
        handler = MockParamHandler("sup", None)
        assert handler.get_param_placeholder("sup") == "%s"

    def test_param_alias_unset_repr_matches_legacy_default_display(self):
        from pydapper.commands import _MODEL_UNSET
        from pydapper.commands import _PARAM_ALIAS_UNSET

        assert repr(_PARAM_ALIAS_UNSET) == "None"
        assert repr(_MODEL_UNSET) == "dict"

    def test_ordered_param_names(self):
        handler = MockParamHandler(
            "?sup? ?hello? ?world? ?foo? ?bar?",
            {"sup": 1, "hello": 2, "world": 3, "foo": 4, "bar": 5},
        )
        assert handler.ordered_param_names == ("sup", "hello", "world", "foo", "bar")

    def test_ordered_param_values(self):
        handler = MockParamHandler(
            "?sup? ?hello? ?world? ?foo? ?bar?",
            {"sup": "dude", "hello": "world", "world": "hello", "foo": "bar", "bar": "foo"},
        )
        assert handler.ordered_param_values == ("dude", "world", "hello", "bar", "foo")

    def test_ordered_param_values_supports_mapping_subclasses(self):
        handler = MockParamHandler("?id? ?name?", UserDict({"id": 1, "name": "Zach"}))

        assert handler.ordered_param_values == (1, "Zach")

    def test_ordered_param_values_supports_attribute_objects(self):
        handler = MockParamHandler("?id? ?name?", SimpleNamespace(id=1, name="Zach"))

        assert handler.ordered_param_values == (1, "Zach")

    def test_ordered_param_values_supports_dataclass_instances_and_falsey_values(self):
        handler = MockParamHandler(
            "?id? ?active? ?name? ?ids?",
            TaskParams(id=0, active=False, name="", ids=[]),
        )

        assert handler.ordered_param_values == (0, False, "", [])

    def test_ordered_param_values_are_resolved_once_for_single_record(self):
        class LazyParams:
            def __init__(self):
                self.id_calls = 0

            @property
            def id(self):
                self.id_calls += 1
                return 1

        params = LazyParams()
        handler = MockParamHandler("?id?", params)

        assert params.id_calls == 1
        assert handler.ordered_param_values == (1,)
        assert handler.ordered_param_values == (1,)
        assert params.id_calls == 1

    def test_ordered_param_values_are_resolved_once_for_executemany_records(self):
        class LazyParams:
            def __init__(self, id_):
                self._id = id_
                self.id_calls = 0

            @property
            def id(self):
                self.id_calls += 1
                return self._id

        params = [LazyParams(1), LazyParams(2)]
        handler = MockParamHandler("?id?", params)

        assert [param.id_calls for param in params] == [1, 1]
        assert handler.ordered_param_values == [(1,), (2,)]
        assert handler.ordered_param_values == [(1,), (2,)]
        assert [param.id_calls for param in params] == [1, 1]

    @pytest.mark.parametrize("param", [None, {}, SimpleNamespace()])
    def test_missing_params_raise_missing_parameter_exception(self, param):
        with pytest.raises(MissingParameterException, match="'id'"):
            MockParamHandler("select * from table where id = ?id?", param)

    def test_ordered_param_values_empty_top_level_list_is_executemany_input(self):
        handler = MockParamHandler("insert into table (id) values (?id?)", [])
        assert handler.ordered_param_values == []

    def test_list_inside_mapping_is_single_parameter_value(self):
        handler = MockParamHandler("select * from table where id in ?ids?", {"ids": []})
        assert handler.ordered_param_names == ("ids",)
        assert handler.ordered_param_values == ([],)
        assert handler.prepared_sql == "select * from table where id in %s"

    def test_non_empty_list_inside_mapping_is_single_parameter_value(self):
        handler = MockParamHandler("select * from table where id in ?ids?", {"ids": [1, 2, 3]})
        assert handler.ordered_param_names == ("ids",)
        assert handler.ordered_param_values == ([1, 2, 3],)
        assert handler.prepared_sql == "select * from table where id in %s"

    def test_prepared_sql(self):
        handler = MockParamHandler("select * from table where id = ?id? and name = ?name?", {"id": 1, "name": "Zach"})
        assert handler.prepared_sql == "select * from table where id = %s and name = %s"

    def test_prepared_sql_no_matching_param(self):
        handler = MockParamHandler("select * from table", {"id": 1, "name": "Zach"})
        assert handler.prepared_sql == "select * from table"

    @pytest.mark.parametrize("param", [None, {}, []])
    def test_prepared_sql_with_falsey_params_and_no_placeholders_preserves_original_sql(self, param):
        handler = MockParamHandler("select * from table", param)
        assert handler.prepared_sql == "select * from table"

    def test_prepared_sql_ignores_placeholders_inside_quoted_text(self):
        sql = """select '?ignored?', 'it''s ?still_ignored?', "?quoted?", "a "" ?still_quoted? "" b", ?active?"""
        handler = MockParamHandler(sql, {"active": 1})

        assert handler.ordered_param_names == ("active",)
        assert (
            handler.prepared_sql
            == """select '?ignored?', 'it''s ?still_ignored?', "?quoted?", "a "" ?still_quoted? "" b", %s"""
        )

    def test_prepared_sql_ignores_placeholders_inside_backslash_escaped_quoted_text(self):
        sql = r"select 'it\'s ?ignored?' as value, ?id?"
        handler = MockParamHandler(sql, {"id": 1})

        assert handler.ordered_param_names == ("id",)
        assert handler.prepared_sql == r"select 'it\'s ?ignored?' as value, %s"

    def test_prepared_sql_ignores_unclosed_quoted_text_at_eof(self):
        sql = "select '?ignored? as value, ?also_ignored?"
        handler = MockParamHandler(sql, {"also_ignored": 1})

        assert handler.ordered_param_names == ()
        assert handler.prepared_sql == sql

    def test_prepared_sql_ignores_placeholders_inside_comments(self):
        sql = "select ?active? -- ?ignored?\n, ?next? /* ?block_ignored? */ ?after_block? -- ?eof_ignored?"
        handler = MockParamHandler(sql, {"active": 1, "next": 2, "after_block": 3})

        assert handler.ordered_param_names == ("active", "next", "after_block")
        assert handler.prepared_sql == "select %s -- ?ignored?\n, %s /* ?block_ignored? */ %s -- ?eof_ignored?"

    def test_prepared_sql_ignores_unclosed_block_comment_at_eof(self):
        sql = "select ?active? /* ?ignored?"
        handler = MockParamHandler(sql, {"active": 1})

        assert handler.ordered_param_names == ("active",)
        assert handler.prepared_sql == "select %s /* ?ignored?"

    def test_active_and_ignored_placeholders_with_same_name_are_distinct(self):
        sql = "select '?id?' as literal, ?id? as id -- ?id?\n, ?id? as next_id"
        handler = MockParamHandler(sql, {"id": 1})

        assert handler.ordered_param_names == ("id", "id")
        assert handler.ordered_param_values == (1, 1)
        assert handler.prepared_sql == "select '?id?' as literal, %s as id -- ?id?\n, %s as next_id"

    def test_duplicate_placeholders_bind_in_occurrence_order(self):
        handler = MockParamHandler(
            "select * from table where id = ?id? or parent_id = ?id?",
            {"id": 1},
        )

        assert handler.ordered_param_names == ("id", "id")
        assert handler.ordered_param_values == (1, 1)
        assert handler.prepared_sql == "select * from table where id = %s or parent_id = %s"

    def test_placeholder_names_allow_uppercase_and_digits_after_first_character(self):
        handler = MockParamHandler("select * from table where id = ?TaskID1?", {"TaskID1": 1})

        assert handler.ordered_param_names == ("TaskID1",)
        assert handler.ordered_param_values == (1,)
        assert handler.prepared_sql == "select * from table where id = %s"

    def test_invalid_placeholder_forms_are_ignored(self):
        sql = "select ??, ??id?, ? id?, ?first-name?, ?first-?id?, ?bad?valid?, ?table.column?, ?1id?, ?_valid?"
        handler = MockParamHandler(sql, {"_valid": 1})

        assert handler.ordered_param_names == ("_valid",)
        assert (
            handler.prepared_sql
            == "select ??, ??id?, ? id?, ?first-name?, ?first-?id?, ?bad?valid?, ?table.column?, ?1id?, %s"
        )

    def test_invalid_placeholder_does_not_swallow_later_valid_placeholder(self):
        sql = "select ? as native_param, ?bad, ?id?"
        handler = MockParamHandler(sql, {"id": 1})

        assert handler.ordered_param_names == ("id",)
        assert handler.prepared_sql == "select ? as native_param, ?bad, %s"

    def test_postgresql_question_mark_operators_do_not_swallow_placeholders(self):
        sql = "select * from table where data ? 'key' and tags ?| ?keys? and id = ?id?"
        handler = MockParamHandler(sql, {"keys": ["urgent"], "id": 1})

        assert handler.ordered_param_names == ("keys", "id")
        assert handler.prepared_sql == "select * from table where data ? 'key' and tags ?| %s and id = %s"

    def test_unspaced_question_mark_operator_does_not_swallow_later_placeholder(self):
        sql = "select * from table where data?key_col::text=?expected?"
        handler = MockParamHandler(sql, {"expected": "value"})

        assert handler.ordered_param_names == ("expected",)
        assert handler.prepared_sql == "select * from table where data?key_col::text=%s"

    def test_malformed_placeholder_recovery_respects_comments_and_quotes(self):
        sql = "select ?bad -- ?comment? ?id?\n, '?ignored? ?id?', ?next?"
        handler = MockParamHandler(sql, {"next": 1})

        assert handler.ordered_param_names == ("next",)
        assert handler.prepared_sql == "select ?bad -- ?comment? ?id?\n, '?ignored? ?id?', %s"

    @pytest.mark.parametrize(
        "sql, expected_prepared_sql",
        [
            ('select ?bad"?ignored?", ?id?', 'select ?bad"?ignored?", %s'),
            ("select ?bad-- ?ignored?\n, ?id?", "select ?bad-- ?ignored?\n, %s"),
            ("select ?bad/* ?ignored? */, ?id?", "select ?bad/* ?ignored? */, %s"),
        ],
    )
    def test_malformed_placeholder_recovery_stops_at_sql_boundaries(self, sql, expected_prepared_sql):
        handler = MockParamHandler(sql, {"id": 1})

        assert handler.ordered_param_names == ("id",)
        assert handler.prepared_sql == expected_prepared_sql

    def test_malformed_placeholder_at_eof_is_ignored(self):
        handler = MockParamHandler("select ?bad", {"bad": 1})

        assert handler.ordered_param_names == ()
        assert handler.prepared_sql == "select ?bad"

    def test_get_param_placeholder_runs_once_per_active_occurrence(self):
        class TrackingParamHandler(MockParamHandler):
            def __init__(self, sql, param=None):
                self.placeholder_calls = []
                super().__init__(sql, param)

            def get_param_placeholder(self, param_name):
                self.placeholder_calls.append(param_name)
                return f"${len(self.placeholder_calls)}"

        handler = TrackingParamHandler("?id?, '?name?', ?name?, ?id? -- ?name?", {"id": 1, "name": "Zach"})

        assert handler.prepared_sql == "$1, '?name?', $2, $3 -- ?name?"
        assert handler.placeholder_calls == ["id", "name", "id"]

    def test_execute_with_empty_top_level_list_returns_zero_without_cursor_calls(self):
        class NoCallCursor:
            rowcount = 123

            def execute(self, *args, **kwargs):
                raise AssertionError("execute should not be called")

            def executemany(self, *args, **kwargs):
                raise AssertionError("executemany should not be called")

        handler = MockParamHandler("insert into table (id) values (?id?)", [])

        assert handler.execute(NoCallCursor()) == 0

    def test_execute_with_no_params_executes_once(self):
        class TrackingCursor:
            rowcount = 0

            def __init__(self):
                self.calls = []

            def execute(self, sql, parameters=None):
                self.calls.append(("execute", sql, parameters))
                self.rowcount = 1

            def executemany(self, *args, **kwargs):
                raise AssertionError("executemany should not be called")

        cursor = TrackingCursor()
        handler = MockParamHandler("insert into table default values", None)

        assert handler.execute(cursor) == 1
        assert cursor.calls == [("execute", "insert into table default values", None)]

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

    @pytest.mark.asyncio
    async def test_execute_async_with_empty_top_level_list_returns_zero_without_cursor_calls(self):
        class NoCallCursor:
            rowcount = 123

            async def execute(self, *args, **kwargs):
                raise AssertionError("execute should not be called")

            async def executemany(self, *args, **kwargs):
                raise AssertionError("executemany should not be called")

        handler = MockParamHandler("insert into table (id) values (?id?)", [])

        assert await handler.execute_async(NoCallCursor()) == 0

    @pytest.mark.asyncio
    async def test_execute_async_with_no_params_executes_once(self):
        class TrackingCursor:
            rowcount = 0

            def __init__(self):
                self.calls = []

            async def execute(self, sql, parameters=None):
                self.calls.append(("execute", sql, parameters))
                self.rowcount = 1

            async def executemany(self, *args, **kwargs):
                raise AssertionError("executemany should not be called")

        cursor = TrackingCursor()
        handler = MockParamHandler("insert into table default values", None)

        assert await handler.execute_async(cursor) == 1
        assert cursor.calls == [("execute", "insert into table default values", None)]

    @pytest.mark.asyncio
    async def test_aiopg_param_handler_executes_no_param_sql_without_empty_tuple(self):
        from pydapper.postgresql.aiopg import AiopgCommands

        class TrackingCursor:
            rowcount = 1

            def __init__(self):
                self.calls = []

            async def execute(self, sql, parameters=None):
                self.calls.append((sql, parameters))

        cursor = TrackingCursor()
        handler = AiopgCommands.SqlParamHandler("select 1", None)

        assert await handler.execute_async(cursor) == 1
        assert cursor.calls == [("select 1", None)]


class TestCommands:
    @pytest.fixture
    def connection(self):
        return MockConnection()

    @pytest.fixture
    def set_fetchone_to_return_none(self, monkeypatch):
        monkeypatch.setattr(MockCursor, "fetchone", lambda self_: None)

    @pytest.fixture
    def set_fetchone_to_return_null_first_column(self, monkeypatch):
        monkeypatch.setattr(MockCursor, "fetchone", lambda self_: FalsyRow((None,)))

    @pytest.fixture
    def set_fetchone_to_return_falsy_row(self, monkeypatch):
        monkeypatch.setattr(MockCursor, "fetchone", lambda self_: FalsyRow((None, "nullable")))

    @pytest.fixture
    def set_fetchall_return_one(self, faker, monkeypatch):
        monkeypatch.setattr(MockCursor, "fetchall", lambda self_: ((1, faker.name()),))

        rows = [(1, faker.name()), None]

        def fetchone(self_):
            return rows.pop(0) if rows else None

        monkeypatch.setattr(MockCursor, "fetchone", fetchone)

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

    def test_context_manager_methods_allow_plain_connection(self):
        class PlainConnection:
            pass

        commands = MockCommands(PlainConnection())

        assert commands.__enter__() is commands
        assert commands.__exit__(None, None, None) is None

    def test_cursor(self, connection):
        assert isinstance(MockCommands(connection).cursor(), MockCursor)

    def test_cursor_context_proxy_supports_cursor_without_context_manager(self):
        class PlainCursor:
            rowcount = 0
            description = ("id", "int"), ("name", "text")

            def execute(self, sql, parameters=None):
                pass

            def fetchall(self):
                return (1, "Zach"), (2, "Bob")

        class PlainCursorConnection:
            def __init__(self):
                self.cursor_instance = PlainCursor()
                self.cursor_calls = 0

            def cursor(self, *args, **kwargs):
                self.cursor_calls += 1
                return self.cursor_instance

        connection = PlainCursorConnection()

        records = MockCommands(connection).query("select id, name from some_table")

        assert records == [{"id": 1, "name": "Zach"}, {"id": 2, "name": "Bob"}]
        assert connection.cursor_calls == 1

    def test_cursor_context_proxy_ignores_cursor_exit_suppression(self):
        class SuppressingCursor:
            def __init__(self):
                self.exit_args = None

            def __enter__(self):
                return self

            def __exit__(self, exc_type, exc_val, exc_tb):
                self.exit_args = exc_type, exc_val, exc_tb
                return True

        cursor = SuppressingCursor()
        command_error = RuntimeError("query failed")

        with pytest.raises(RuntimeError) as exc_info:
            with MockCommands(_CursorConnection(cursor))._cursor_context_proxy():
                raise command_error

        assert exc_info.value is command_error
        assert cursor.exit_args[0] is RuntimeError

    def test_cursor_context_proxy_preserves_error_when_cursor_exit_fails(self):
        class FailingExitCursor:
            def __enter__(self):
                return self

            def __exit__(self, exc_type, exc_val, exc_tb):
                raise RuntimeError("close failed")

        with pytest.raises(ValueError, match="query failed"):
            with MockCommands(_CursorConnection(FailingExitCursor()))._cursor_context_proxy():
                raise ValueError("query failed")

    def test_cursor_context_proxy_closes_the_cursor_when_entry_fails(self):
        class FailingEnterCursor:
            def __init__(self):
                self.close_calls = 0
                self.exit_calls = 0

            def __enter__(self):
                raise RuntimeError("entry failed")

            def __exit__(self, exc_type, exc_val, exc_tb):
                self.exit_calls += 1

            def close(self):
                self.close_calls += 1

        cursor = FailingEnterCursor()

        with pytest.raises(RuntimeError, match="entry failed"):
            with MockCommands(_CursorConnection(cursor))._cursor_context_proxy():
                raise AssertionError("the body must not run")

        # the command created and solely owns this cursor, so a failed __enter__ closes it exactly
        # once instead of leaking it, and never exits a cursor that never entered
        assert cursor.close_calls == 1
        assert cursor.exit_calls == 0

    def test_cursor_context_proxy_entry_error_survives_a_failing_close(self, caplog):
        entry_error = RuntimeError("entry failed")

        class FailingEnterAndCloseCursor:
            def __enter__(self):
                raise entry_error

            def __exit__(self, exc_type, exc_val, exc_tb):
                raise AssertionError("__exit__ must not run for a cursor that never entered")

            def close(self):
                raise ValueError("close failed")

        with caplog.at_level(logging.DEBUG, logger="pydapper._context"):
            with pytest.raises(RuntimeError) as exc_info:
                with MockCommands(_CursorConnection(FailingEnterAndCloseCursor()))._cursor_context_proxy():
                    raise AssertionError("the body must not run")

        assert exc_info.value is entry_error
        assert [record.getMessage() for record in _debug_records(caplog)] == [
            "Discarding ValueError raised while cleaning up a pydapper-owned resource"
        ]

    def test_cursor_context_proxy_entry_failure_without_close_propagates(self):
        class FailingEnterCursorWithoutClose:
            def __enter__(self):
                raise RuntimeError("entry failed")

            def __exit__(self, exc_type, exc_val, exc_tb):
                raise AssertionError("__exit__ must not run for a cursor that never entered")

        with pytest.raises(RuntimeError, match="entry failed"):
            with MockCommands(_CursorConnection(FailingEnterCursorWithoutClose()))._cursor_context_proxy():
                raise AssertionError("the body must not run")

    @pytest.mark.parametrize("base_error", _NON_EXCEPTION_CLEANUP_FAILURES)
    def test_cursor_exit_non_exception_during_cleanup_beats_the_command_error(self, base_error):
        command_error = ValueError("query failed")

        class InterruptingExitCursor:
            def __enter__(self):
                return self

            def __exit__(self, exc_type, exc_val, exc_tb):
                raise base_error()

        with pytest.raises(base_error) as exc_info:
            with MockCommands(_CursorConnection(InterruptingExitCursor()))._cursor_context_proxy():
                raise command_error

        # a BaseException that is not an Exception is never a resource problem, so it is never
        # discarded; the command error survives as its implicit context
        assert exc_info.value.__context__ is command_error

    @pytest.mark.parametrize("base_error", _NON_EXCEPTION_CLEANUP_FAILURES)
    def test_plain_cursor_close_non_exception_during_cleanup_beats_the_command_error(self, base_error):
        command_error = ValueError("query failed")
        cursor = _PlainQueryCursor()
        cursor.close_error = base_error()

        with pytest.raises(base_error) as exc_info:
            with MockCommands(_CursorConnection(cursor))._cursor_context_proxy():
                raise command_error

        assert exc_info.value.__context__ is command_error
        assert cursor.close_calls == 1

    def test_discarded_cursor_exit_error_is_recorded_at_debug(self, caplog):
        command_error = ValueError("query failed")
        cleanup_error = RuntimeError("cleanup failed")

        class FailingExitCursor:
            def __enter__(self):
                return self

            def __exit__(self, exc_type, exc_val, exc_tb):
                raise cleanup_error

        with caplog.at_level(logging.DEBUG, logger="pydapper._context"):
            with pytest.raises(ValueError) as exc_info:
                with MockCommands(_CursorConnection(FailingExitCursor()))._cursor_context_proxy():
                    raise command_error

        # the command error is re-raised as the same object and is never chained to the cleanup
        # failure, so the debug record is the only place the discarded error survives
        assert exc_info.value is command_error
        assert exc_info.value.__context__ is None
        records = _debug_records(caplog)
        assert [record.getMessage() for record in records] == [
            "Discarding RuntimeError raised while cleaning up a pydapper-owned resource"
        ]
        assert records[0].exc_info[1] is cleanup_error

    def test_execute_error_wins_over_native_cursor_exit_error(self):
        command_error = ValueError("execute failed")

        class ExplodingCursor:
            def __init__(self):
                self.enter_calls = 0
                self.exit_calls = 0
                self.exit_args = None

            def __enter__(self):
                self.enter_calls += 1
                return self

            def __exit__(self, exc_type, exc_val, exc_tb):
                self.exit_calls += 1
                self.exit_args = exc_type, exc_val, exc_tb
                self.exit_tb_was_active = exc_tb is exc_val.__traceback__
                raise RuntimeError("cleanup failed")

            def execute(self, sql, parameters=None):
                raise command_error

        class ExplodingCursorConnection:
            def __init__(self, cursor):
                self.cursor_instance = cursor
                self.cursor_calls = 0

            def cursor(self, *args, **kwargs):
                self.cursor_calls += 1
                return self.cursor_instance

        cursor = ExplodingCursor()
        connection = ExplodingCursorConnection(cursor)

        with pytest.raises(ValueError) as exc_info:
            MockCommands(connection).execute("insert into some_table (id) values (1)")

        assert exc_info.value is command_error
        assert connection.cursor_calls == 1
        assert cursor.enter_calls == 1
        assert cursor.exit_calls == 1
        exc_type, exc_val, exc_tb = cursor.exit_args
        assert exc_type is ValueError
        assert exc_val is command_error
        assert cursor.exit_tb_was_active

    def test_execute_error_wins_over_truthy_native_cursor_exit(self):
        command_error = ValueError("execute failed")

        class SuppressingCursor:
            def __init__(self):
                self.exit_calls = 0
                self.exit_args = None

            def __enter__(self):
                return self

            def __exit__(self, exc_type, exc_val, exc_tb):
                self.exit_calls += 1
                self.exit_args = exc_type, exc_val, exc_tb
                self.exit_tb_was_active = exc_tb is exc_val.__traceback__
                return True

            def execute(self, sql, parameters=None):
                raise command_error

        cursor = SuppressingCursor()

        with pytest.raises(ValueError) as exc_info:
            MockCommands(_CursorConnection(cursor)).execute("insert into some_table (id) values (1)")

        assert exc_info.value is command_error
        assert cursor.exit_calls == 1
        exc_type, exc_val, exc_tb = cursor.exit_args
        assert exc_type is ValueError
        assert exc_val is command_error
        assert cursor.exit_tb_was_active

    def test_execute_error_propagates_with_falsey_native_cursor_exit(self):
        command_error = ValueError("execute failed")

        class NonSuppressingCursor:
            def __init__(self):
                self.exit_calls = 0
                self.exit_args = None

            def __enter__(self):
                return self

            def __exit__(self, exc_type, exc_val, exc_tb):
                self.exit_calls += 1
                self.exit_args = exc_type, exc_val, exc_tb
                self.exit_tb_was_active = exc_tb is exc_val.__traceback__
                return None

            def execute(self, sql, parameters=None):
                raise command_error

        cursor = NonSuppressingCursor()

        with pytest.raises(ValueError) as exc_info:
            MockCommands(_CursorConnection(cursor)).execute("insert into some_table (id) values (1)")

        assert exc_info.value is command_error
        assert cursor.exit_calls == 1
        exc_type, exc_val, exc_tb = cursor.exit_args
        assert exc_type is ValueError
        assert exc_val is command_error
        assert cursor.exit_tb_was_active

    def test_execute_propagates_native_cursor_exit_error_after_success(self):
        cleanup_error = RuntimeError("cleanup failed")

        class FailingExitCursor:
            rowcount = 1

            def __init__(self):
                self.exit_calls = 0
                self.exit_args = None

            def __enter__(self):
                return self

            def __exit__(self, exc_type, exc_val, exc_tb):
                self.exit_calls += 1
                self.exit_args = exc_type, exc_val, exc_tb
                raise cleanup_error

            def execute(self, sql, parameters=None):
                pass

        cursor = FailingExitCursor()

        with pytest.raises(RuntimeError) as exc_info:
            MockCommands(_CursorConnection(cursor)).execute("insert into some_table (id) values (1)")

        assert exc_info.value is cleanup_error
        assert cursor.exit_calls == 1
        assert cursor.exit_args == (None, None, None)

    def test_execute_error_wins_over_plain_cursor_close_error(self):
        command_error = ValueError("execute failed")

        class PlainExplodingCursor:
            def __init__(self):
                self.close_calls = 0

            def execute(self, sql, parameters=None):
                raise command_error

            def close(self):
                self.close_calls += 1
                raise RuntimeError("close failed")

        cursor = PlainExplodingCursor()

        with pytest.raises(ValueError) as exc_info:
            MockCommands(_CursorConnection(cursor)).execute("insert into some_table (id) values (1)")

        assert exc_info.value is command_error
        assert cursor.close_calls == 1

    def test_execute_propagates_plain_cursor_close_error_after_success(self):
        close_error = RuntimeError("close failed")

        class PlainFailingCloseCursor:
            rowcount = 1

            def __init__(self):
                self.close_calls = 0

            def execute(self, sql, parameters=None):
                pass

            def close(self):
                self.close_calls += 1
                raise close_error

        cursor = PlainFailingCloseCursor()

        with pytest.raises(RuntimeError) as exc_info:
            MockCommands(_CursorConnection(cursor)).execute("insert into some_table (id) values (1)")

        assert exc_info.value is close_error
        assert cursor.close_calls == 1

    def test_execute(self, connection):
        with MockCommands(connection) as commands:
            affected_rows = commands.execute(
                "insert into some_table (id, name), (?id?, ?name?)", param={"id": 1, "name": "Zach"}
            )
        assert affected_rows == 1

    def test_execute_sends_prepared_sql_and_ordered_values_to_cursor(self):
        class RecordingCursor:
            rowcount = 1

            def __init__(self):
                self.calls = []

            def __enter__(self):
                return self

            def __exit__(self, exc_type, exc_val, exc_tb):
                pass

            def execute(self, sql, parameters=None):
                self.calls.append((sql, parameters))

            def executemany(self, *args, **kwargs):
                raise AssertionError("executemany should not be called")

        class RecordingConnection(MockConnection):
            def __init__(self):
                super().__init__()
                self.cursor_instance = RecordingCursor()

            def cursor(self, *args, **kwargs):
                return self.cursor_instance

        connection = RecordingConnection()

        with MockCommands(connection) as commands:
            affected_rows = commands.execute(
                "update task set note = '?ignored?' where id = ?id? -- ?id?",
                params={"id": 1},
            )

        assert affected_rows == 1
        assert connection.cursor_instance.calls == [("update task set note = '?ignored?' where id = %s -- ?id?", (1,))]

    def test_execute_with_empty_top_level_list_params_returns_zero_without_opening_cursor(self):
        class NoCursorConnection(MockConnection):
            def cursor(self, *args, **kwargs):
                raise AssertionError("cursor should not be opened")

        with MockCommands(NoCursorConnection()) as commands:
            assert commands.execute("insert into some_table (id) values (?id?)", params=[]) == 0

    def test_execute_uses_executemany_for_mixed_record_list_params(self):
        class RecordingCursor:
            rowcount = 2

            def __init__(self):
                self.calls = []

            def __enter__(self):
                return self

            def __exit__(self, exc_type, exc_val, exc_tb):
                pass

            def execute(self, *args, **kwargs):
                raise AssertionError("execute should not be called")

            def executemany(self, sql, params):
                self.calls.append((sql, params))

        class RecordingConnection(MockConnection):
            def __init__(self):
                super().__init__()
                self.cursor_instance = RecordingCursor()

            def cursor(self, *args, **kwargs):
                return self.cursor_instance

        connection = RecordingConnection()

        with MockCommands(connection) as commands:
            affected_rows = commands.execute(
                "insert into some_table (id) values (?id?)",
                params=[{"id": 1}, SimpleNamespace(id=2)],
            )

        assert affected_rows == 2
        assert connection.cursor_instance.calls == [
            ("insert into some_table (id) values (%s)", [(1,), (2,)]),
        ]

    @pytest.mark.parametrize(
        "params, exception_type",
        [
            ([{"id": 1}, 2], InvalidParameterShapeException),
            ([{"id": 1}, {}], MissingParameterException),
        ],
    )
    def test_execute_rejects_invalid_executemany_records_before_opening_cursor(self, params, exception_type):
        class NoCursorConnection(MockConnection):
            def cursor(self, *args, **kwargs):
                raise AssertionError("cursor should not be opened")

        with MockCommands(NoCursorConnection()) as commands, pytest.raises(exception_type):
            commands.execute("insert into some_table (id) values (?id?)", params=params)

    @pytest.mark.parametrize("call", SYNC_READ_LIST_PARAMS_CALLS)
    def test_read_methods_reject_top_level_list_params_before_opening_cursor(self, call):
        class NoCursorConnection(MockConnection):
            def cursor(self, *args, **kwargs):
                raise AssertionError("cursor should not be opened")

        with MockCommands(NoCursorConnection()) as commands, pytest.raises(InvalidParameterShapeException):
            call(commands)

    @pytest.mark.parametrize("call", SYNC_READ_LIST_PARAMS_CALLS)
    def test_read_methods_reject_top_level_list_params(self, connection, call):
        with MockCommands(connection) as commands, pytest.raises(InvalidParameterShapeException):
            call(commands)

    @pytest.mark.parametrize("call, expected_handler_count", SYNC_PARAMS_CALLS)
    def test_public_methods_accept_params(
        self, connection, captured_handler_params, set_fetchall_return_one, call, expected_handler_count
    ):
        params = {"id": 1}

        with MockCommands(connection) as commands:
            call(commands, params)

        assert captured_handler_params == [params] * expected_handler_count

    @pytest.mark.parametrize("call", SYNC_ALIAS_CONFLICT_CALLS)
    def test_public_methods_reject_param_and_params(self, connection, call):
        params = {"id": 1}

        with MockCommands(connection) as commands, pytest.raises(ValueError, match="Pass either 'params' or 'param'"):
            call(commands, params)

    def test_or_default_methods_delegate_param_spelling_and_normalized_options(self, connection):
        received = []

        class ParamSpellingOverrideCommands(MockCommands):
            def query_first(self, sql, model=dict, param=None, *, options=None):
                received.append(("first", param, options))
                raise NoResultException

            def query_single(self, sql, model=dict, param=None, *, options=None):
                received.append(("single", param, options))
                raise NoResultException

        default = object()

        with ParamSpellingOverrideCommands(connection) as commands:
            assert (
                commands.query_first_or_default("select * from some_table where id = ?id?", default, params={"id": 1})
                is default
            )
            assert (
                commands.query_single_or_default("select * from some_table where id = ?id?", default, params={"id": 1})
                is default
            )

        assert received == [
            ("first", {"id": 1}, pydapper.CommandOptions()),
            ("single", {"id": 1}, pydapper.CommandOptions()),
        ]

    def test_mysql_query_first_accepts_params(self, connection, captured_handler_params):
        from pydapper.mysql import MySqlConnectorPythonCommands

        class MockMySqlConnectorPythonCommands(MySqlConnectorPythonCommands):
            SqlParamHandler = MockParamHandler

        params = {"id": 1}

        with MockMySqlConnectorPythonCommands(connection) as commands:
            commands.query_first("select id, name from some_table where id = ?id?", params=params)

        assert captured_handler_params == [params]

    def test_mysql_query_first_accepts_mapper(self, connection):
        from pydapper.mysql import MySqlConnectorPythonCommands

        class MockMySqlConnectorPythonCommands(MySqlConnectorPythonCommands):
            SqlParamHandler = MockParamHandler

        with MockMySqlConnectorPythonCommands(connection) as commands:
            data = commands.query_first("select id, name from some_table", mapper=lambda row: row["id"])

        assert data == 1

    def test_mysql_query_first_or_default_accepts_mapper(self, connection):
        from pydapper.mysql import MySqlConnectorPythonCommands

        class MockMySqlConnectorPythonCommands(MySqlConnectorPythonCommands):
            SqlParamHandler = MockParamHandler

        with MockMySqlConnectorPythonCommands(connection) as commands:
            data = commands.query_first_or_default(
                "select id, name from some_table",
                default=None,
                mapper=lambda row: row["id"],
            )

        assert data == 1

    def test_mysql_query_first_treats_only_none_as_no_result(self, connection, set_fetchone_to_return_falsy_row):
        from pydapper.mysql import MySqlConnectorPythonCommands

        class MockMySqlConnectorPythonCommands(MySqlConnectorPythonCommands):
            SqlParamHandler = MockParamHandler

        with MockMySqlConnectorPythonCommands(connection) as commands:
            data = commands.query_first("select id, name from some_table")

        assert data == {"id": None, "name": "nullable"}

    def test_mysql_query_first_raises_on_none_result(self, connection, set_fetchone_to_return_none):
        from pydapper.mysql import MySqlConnectorPythonCommands

        class MockMySqlConnectorPythonCommands(MySqlConnectorPythonCommands):
            SqlParamHandler = MockParamHandler

        with MockMySqlConnectorPythonCommands(connection) as commands, pytest.raises(NoResultException):
            commands.query_first("select id, name from some_table")

    def test_mysql_query_first_rejects_top_level_list_params(self, connection):
        from pydapper.mysql import MySqlConnectorPythonCommands

        class MockMySqlConnectorPythonCommands(MySqlConnectorPythonCommands):
            SqlParamHandler = MockParamHandler

        with MockMySqlConnectorPythonCommands(connection) as commands, pytest.raises(InvalidParameterShapeException):
            commands.query_first("select id, name from some_table where id = ?id?", params=[])

    def test_mysql_query_first_rejects_duplicate_columns(self):
        from pydapper.mysql import MySqlConnectorPythonCommands

        class MockMySqlConnectorPythonCommands(MySqlConnectorPythonCommands):
            SqlParamHandler = MockParamHandler

        with MockMySqlConnectorPythonCommands(_CursorConnection(_DuplicateColumnCursor())) as commands:
            with pytest.raises(DuplicateColumnException) as exc_info:
                commands.query_first("select id, name, id from some_table")

        _assert_duplicate_column_exception(exc_info)

    def test_mysql_query_unbuffered_duplicate_columns_are_not_masked_by_unread_result_cleanup(self):
        from pydapper.mysql import MySqlConnectorPythonCommands

        class UnreadResultCursor:
            rowcount = 0
            description = ("id", "int"), ("name", "text"), ("id", "int")

            def __init__(self):
                self.fetchall_calls = 0
                self.unread_result = False

            def __enter__(self):
                return self

            def __exit__(self, exc_type, exc_val, exc_tb):
                assert not self.unread_result

            def execute(self, sql, parameters=None):
                self.unread_result = True

            def fetchall(self):
                self.fetchall_calls += 1
                self.unread_result = False
                return tuple()

            def fetchone(self):
                self.unread_result = True
                return 1, "Zach", 2

        class MockMySqlConnectorPythonCommands(MySqlConnectorPythonCommands):
            SqlParamHandler = MockParamHandler

        cursor = UnreadResultCursor()

        with MockMySqlConnectorPythonCommands(_CursorConnection(cursor)) as commands:
            generator = commands.query("select id, name, id from some_table", buffered=False)
            with pytest.raises(DuplicateColumnException) as exc_info:
                list(generator)

        _assert_duplicate_column_exception(exc_info)
        assert cursor.fetchall_calls == 1

    def test_mysql_query_single_accepts_params(self, connection, captured_handler_params, set_fetchall_return_one):
        from pydapper.mysql import MySqlConnectorPythonCommands

        class MockMySqlConnectorPythonCommands(MySqlConnectorPythonCommands):
            SqlParamHandler = MockParamHandler

        params = {"id": 1}

        with MockMySqlConnectorPythonCommands(connection) as commands:
            commands.query_single("select id, name from some_table where id = ?id?", params=params)

        assert captured_handler_params == [params]

    def test_mysql_query_single_discards_unread_result_before_many_result_exception(self):
        from pydapper.mysql import MySqlConnectorPythonCommands

        class UnreadResultCursor:
            rowcount = 0
            description = ("id", "int"), ("name", "text")

            def __init__(self):
                self.fetchall_calls = 0
                self.fetchmany_calls = []
                self.reset_calls = 0
                self.unread_result = False

            def __enter__(self):
                return self

            def __exit__(self, exc_type, exc_val, exc_tb):
                assert not self.unread_result

            def execute(self, sql, parameters=None):
                pass

            def fetchall(self):
                self.fetchall_calls += 1
                return tuple()

            def fetchmany(self, size=None):
                self.fetchmany_calls.append(size)
                self.unread_result = True
                return [(1, "Zach"), (2, "Bob")]

            def reset(self):
                self.reset_calls += 1
                self.unread_result = False

        class UnreadResultConnection:
            def __init__(self):
                self.cursor_instance = UnreadResultCursor()

            def cursor(self, *args, **kwargs):
                return self.cursor_instance

        class MockMySqlConnectorPythonCommands(MySqlConnectorPythonCommands):
            SqlParamHandler = MockParamHandler

        connection = UnreadResultConnection()

        with MockMySqlConnectorPythonCommands(connection) as commands, pytest.raises(MoreThanOneResultException):
            commands.query_single("select id, name from some_table")

        assert connection.cursor_instance.fetchmany_calls == [2]
        assert connection.cursor_instance.reset_calls == 1
        assert connection.cursor_instance.fetchall_calls == 0

    def test_mysql_query_single_drains_when_reset_does_not_clear_unread_result(self):
        from pydapper.mysql import MySqlConnectorPythonCommands

        class UnreadResultState:
            def __init__(self):
                self.close_calls = 0
                self.consume_results_calls = 0
                self.unread_result = False

            def close(self):
                self.close_calls += 1
                raise AssertionError("connection close should not be called")

            def consume_results(self):
                raise AssertionError("consume_results should not be called")

        class UnreadResultCursor:
            rowcount = 0
            description = ("id", "int"), ("name", "text")

            def __init__(self):
                self.connection_state = UnreadResultState()
                self._connection = self.connection_state
                self.close_calls = 0
                self.fetchall_calls = 0
                self.fetchmany_calls = []

            def __enter__(self):
                return self

            def __exit__(self, exc_type, exc_val, exc_tb):
                self.close()

            def close(self):
                self.close_calls += 1
                if self._connection is not None and self._connection.unread_result:
                    raise AssertionError("unread result found")

            def execute(self, sql, parameters=None):
                pass

            def fetchall(self):
                self.fetchall_calls += 1
                self._connection.unread_result = False
                return tuple()

            def fetchmany(self, size=None):
                self.fetchmany_calls.append(size)
                self._connection.unread_result = True
                return [(1, "Zach"), (2, "Bob")]

            def reset(self):
                pass

        class UnreadResultConnection:
            def __init__(self):
                self.cursor_instance = UnreadResultCursor()

            def cursor(self, *args, **kwargs):
                return self.cursor_instance

        class MockMySqlConnectorPythonCommands(MySqlConnectorPythonCommands):
            SqlParamHandler = MockParamHandler

        connection = UnreadResultConnection()

        with MockMySqlConnectorPythonCommands(connection) as commands, pytest.raises(MoreThanOneResultException):
            commands.query_single("select id, name from some_table")

        assert connection.cursor_instance.fetchmany_calls == [2]
        assert connection.cursor_instance.connection_state.close_calls == 0
        assert connection.cursor_instance.connection_state.consume_results_calls == 0
        assert connection.cursor_instance._connection is connection.cursor_instance.connection_state
        assert connection.cursor_instance.close_calls == 1
        assert connection.cursor_instance.fetchall_calls == 1

    def test_mysql_query_single_cleanup_errors_do_not_mask_many_result_exception(self):
        from pydapper.mysql import MySqlConnectorPythonCommands

        class UnreadResultState:
            def __init__(self):
                self.consume_results_calls = 0
                self.unread_result = True

            def consume_results(self):
                self.consume_results_calls += 1
                raise RuntimeError("cleanup failed")

        class UnreadResultCursor:
            rowcount = 0
            description = ("id", "int"), ("name", "text")

            def __init__(self):
                self._connection = UnreadResultState()
                self.fetchall_calls = 0
                self.fetchmany_calls = []

            def close(self):
                raise RuntimeError("cursor close failed")

            def execute(self, sql, parameters=None):
                pass

            def fetchall(self):
                self.fetchall_calls += 1
                raise RuntimeError("fetchall failed")

            def fetchmany(self, size=None):
                self.fetchmany_calls.append(size)
                return [(1, "Zach"), (2, "Bob")]

            def reset(self):
                raise RuntimeError("reset failed")

        class UnreadResultConnection:
            def __init__(self):
                self.cursor_instance = UnreadResultCursor()

            def cursor(self, *args, **kwargs):
                return self.cursor_instance

        class MockMySqlConnectorPythonCommands(MySqlConnectorPythonCommands):
            SqlParamHandler = MockParamHandler

        connection = UnreadResultConnection()

        with MockMySqlConnectorPythonCommands(connection) as commands, pytest.raises(MoreThanOneResultException):
            commands.query_single("select id, name from some_table")

        assert connection.cursor_instance.fetchmany_calls == [2]
        assert connection.cursor_instance.fetchall_calls == 1
        assert connection.cursor_instance._connection.consume_results_calls == 1

    def test_mysql_query_single_missing_cleanup_hooks_do_not_mask_many_result_exception(self):
        from pydapper.mysql import MySqlConnectorPythonCommands

        class UnreadResultCursor:
            rowcount = 0
            description = ("id", "int"), ("name", "text")

            def __init__(self):
                self.fetchall_calls = 0
                self.fetchmany_calls = []
                self.unread_result = False

            def execute(self, sql, parameters=None):
                pass

            def fetchall(self):
                self.fetchall_calls += 1
                raise RuntimeError("fetchall failed")

            def fetchmany(self, size=None):
                self.fetchmany_calls.append(size)
                self.unread_result = True
                return [(1, "Zach"), (2, "Bob")]

        class UnreadResultConnection:
            def __init__(self):
                self.cursor_instance = UnreadResultCursor()

            def cursor(self, *args, **kwargs):
                return self.cursor_instance

        class MockMySqlConnectorPythonCommands(MySqlConnectorPythonCommands):
            SqlParamHandler = MockParamHandler

        connection = UnreadResultConnection()

        with MockMySqlConnectorPythonCommands(connection) as commands, pytest.raises(MoreThanOneResultException):
            commands.query_single("select id, name from some_table")

        assert connection.cursor_instance.fetchmany_calls == [2]
        assert connection.cursor_instance.fetchall_calls == 1

    def test_mysql_query_single_drains_cursor_without_connection_reference(self):
        from pydapper.mysql import MySqlConnectorPythonCommands

        class UnreadResultCursor:
            rowcount = 0
            description = ("id", "int"), ("name", "text")

            def __init__(self):
                self.fetchall_calls = 0
                self.fetchmany_calls = []
                self.unread_result = False

            def __enter__(self):
                return self

            def __exit__(self, exc_type, exc_val, exc_tb):
                assert not self.unread_result

            def execute(self, sql, parameters=None):
                pass

            def fetchall(self):
                self.fetchall_calls += 1
                self.unread_result = False
                return tuple()

            def fetchmany(self, size=None):
                self.fetchmany_calls.append(size)
                self.unread_result = True
                return [(1, "Zach"), (2, "Bob")]

        class UnreadResultConnection:
            def __init__(self):
                self.cursor_instance = UnreadResultCursor()

            def cursor(self, *args, **kwargs):
                return self.cursor_instance

        class MockMySqlConnectorPythonCommands(MySqlConnectorPythonCommands):
            SqlParamHandler = MockParamHandler

        connection = UnreadResultConnection()

        with MockMySqlConnectorPythonCommands(connection) as commands, pytest.raises(MoreThanOneResultException):
            commands.query_single("select id, name from some_table")

        assert connection.cursor_instance.fetchmany_calls == [2]
        assert connection.cursor_instance.fetchall_calls == 1

    def test_query(self, connection):
        with MockCommands(connection) as commands:
            data = commands.query("select id, name from some_table", model=SimpleNamespace)
        assert len(data) == 2
        assert all(isinstance(row, SimpleNamespace) for row in data)

    def test_query_mapper_receives_raw_rows(self, connection):
        seen_rows = []

        def mapper(row):
            seen_rows.append(row)
            return row.columns, row.values, row[0], row["name"]

        with MockCommands(connection) as commands:
            data = commands.query("select id, name from some_table", mapper=mapper)

        assert len(data) == 2
        assert data[0][0] == ("id", "name")
        assert data[0][1][0] == 1
        assert data[0][2] == 1
        assert seen_rows
        assert all(isinstance(row, RawRow) for row in seen_rows)

    def test_query_mapper_can_handle_duplicate_columns(self):
        with MockCommands(_CursorConnection(_DuplicateColumnCursor())) as commands:
            data = commands.query(
                "select id, name, id from some_table",
                mapper=lambda row: (row.columns, row.values[0], row.values[2]),
            )

        assert data == [(("id", "name", "id"), 1, 2)]

    def test_query_unbuffered_mapper_can_handle_duplicate_columns(self):
        with MockCommands(_CursorConnection(_DuplicateColumnCursor())) as commands:
            generator = commands.query(
                "select id, name, id from some_table",
                mapper=lambda row: row.values,
                buffered=False,
            )

            assert list(generator) == [(1, "Zach", 2)]

    def test_query_unbuffered_mapper_yields_multiple_rows(self):
        connection = _CursorConnection(_QuerySingleFetchOneCursor([(1, "Zach"), (2, "Bob")]))

        with MockCommands(connection) as commands:
            generator = commands.query(
                "select id, name from some_table",
                mapper=lambda row: row[0],
                buffered=False,
            )

            assert list(generator) == [1, 2]

    @pytest.mark.parametrize("buffered", [True, False])
    def test_query_mapper_exceptions_are_not_masked_by_cursor_context_proxy(self, buffered):
        cursor = _TrackingContextCursor()

        with pytest.raises(AttributeError, match="missing"):
            result = MockCommands(_CursorConnection(cursor)).query(
                "select id, name from some_table",
                mapper=lambda row: row.missing,
                buffered=buffered,
            )
            if not buffered:
                list(result)

        assert cursor.entered is True
        assert cursor.exited is True

    def test_plain_cursor_is_closed_after_buffered_query(self):
        cursor = _PlainQueryCursor()

        assert MockCommands(_CursorConnection(cursor)).query("select id, name from some_table") == [
            {"id": 1, "name": "Zach"},
            {"id": 2, "name": "Bob"},
        ]
        assert cursor.close_calls == 1

    def test_plain_cursor_cleanup_preserves_buffered_failure(self):
        cursor = _PlainQueryCursor()
        cursor.fetchall_error = RuntimeError("fetch failed")

        with pytest.raises(RuntimeError, match="fetch failed"):
            MockCommands(_CursorConnection(cursor)).query("select id, name from some_table")

        assert cursor.close_calls == 1

    def test_plain_cursor_cleanup_failure_does_not_mask_buffered_failure(self):
        cursor = _PlainQueryCursor()
        cursor.fetchall_error = RuntimeError("fetch failed")
        cursor.close_error = RuntimeError("close failed")

        with pytest.raises(RuntimeError, match="fetch failed"):
            MockCommands(_CursorConnection(cursor)).query("select id, name from some_table")

    def test_plain_cursor_is_closed_when_projection_fails(self):
        cursor = _PlainQueryCursor()

        with pytest.raises(RuntimeError, match="projection failed"):
            MockCommands(_CursorConnection(cursor)).query(
                "select id, name from some_table",
                mapper=lambda row: (_ for _ in ()).throw(RuntimeError("projection failed")),
            )

        assert cursor.close_calls == 1

    def test_plain_cursor_is_closed_by_unbuffered_generator_close(self):
        cursor = _PlainQueryCursor()
        rows = MockCommands(_CursorConnection(cursor)).query("select id, name from some_table", buffered=False)

        assert next(rows) == {"id": 1, "name": "Zach"}
        rows.close()
        assert cursor.close_calls == 1

    def test_plain_cursor_is_closed_after_unbuffered_exhaustion(self):
        cursor = _PlainQueryCursor()
        rows = MockCommands(_CursorConnection(cursor)).query("select id, name from some_table", buffered=False)

        assert list(rows) == [{"id": 1, "name": "Zach"}, {"id": 2, "name": "Bob"}]
        assert cursor.close_calls == 1

    def test_plain_cursor_cleanup_preserves_unbuffered_failure(self):
        cursor = _PlainQueryCursor()
        cursor.fetchone_error = RuntimeError("fetch failed")
        rows = MockCommands(_CursorConnection(cursor)).query("select id, name from some_table", buffered=False)

        with pytest.raises(RuntimeError, match="fetch failed"):
            next(rows)

        assert cursor.close_calls == 1

    def test_cursor_context_error_is_not_mistaken_for_plain_cursor(self):
        class FailingContextCursor(_PlainQueryCursor):
            def __init__(self):
                super().__init__()
                self.exit_calls = 0

            def __enter__(self):
                raise AttributeError("query context failed")

            def __exit__(self, exc_type, exc_val, exc_tb):
                self.exit_calls += 1
                self.close()

        cursor = FailingContextCursor()

        with pytest.raises(AttributeError, match="query context failed"):
            MockCommands(_CursorConnection(cursor)).query("select id, name from some_table")

        # the entry failure propagates instead of falling through to the plain-cursor branch, so the
        # command body never runs and __exit__ is never called for a cursor that never entered; the
        # command-owned cursor is still closed exactly once by the best-effort entry cleanup
        assert cursor.exit_calls == 0
        assert cursor.close_calls == 1

    def test_query_rejects_model_and_mapper(self, connection):
        with MockCommands(connection) as commands:
            with pytest.raises(ValueError, match="Pass either 'model' or 'mapper'"):
                commands.query("select id, name from some_table", model=SimpleNamespace, mapper=lambda row: row)

    def test_query_rejects_duplicate_columns(self):
        with MockCommands(_CursorConnection(_DuplicateColumnCursor())) as commands:
            with pytest.raises(DuplicateColumnException) as exc_info:
                commands.query("select id, name, id from some_table")

        _assert_duplicate_column_exception(exc_info)

    def test_query_rejects_duplicate_columns_with_no_rows(self):
        with MockCommands(_CursorConnection(_DuplicateColumnCursor(rows=()))) as commands:
            with pytest.raises(DuplicateColumnException) as exc_info:
                commands.query("select id, name, id from some_table")

        _assert_duplicate_column_exception(exc_info)

    def test_query_returns_empty_list_on_no_results(self, connection, set_fetchall_return_empty):
        with MockCommands(connection) as commands:
            data = commands.query("select id, name from some_table")
        assert data == []

    def test_query_unbuffered_yields_no_rows_on_no_results(self, connection, set_fetchone_to_return_none):
        with MockCommands(connection) as commands:
            generator = commands.query("select id, name from some_table", buffered=False)
            assert list(generator) == []

    def test_query_unbuffered_rejects_duplicate_columns(self):
        with MockCommands(_CursorConnection(_DuplicateColumnCursor())) as commands:
            generator = commands.query("select id, name, id from some_table", buffered=False)
            with pytest.raises(DuplicateColumnException) as exc_info:
                list(generator)

        _assert_duplicate_column_exception(exc_info)

    def test_query_unbuffered_rejects_duplicate_columns_with_no_rows(self):
        with MockCommands(_CursorConnection(_DuplicateColumnCursor(rows=()))) as commands:
            generator = commands.query("select id, name, id from some_table", buffered=False)
            with pytest.raises(DuplicateColumnException) as exc_info:
                list(generator)

        _assert_duplicate_column_exception(exc_info)

    def test_query_unbuffered_yields_rows_until_none(self):
        class OneRowCursor(MockCursor):
            def __init__(self):
                super().__init__()
                self.rows = [(1, "Zach"), None]

            def fetchone(self):
                return self.rows.pop(0)

        class OneRowConnection(MockConnection):
            def __init__(self):
                super().__init__()
                self.cursor_instance = OneRowCursor()

            def cursor(self, *args, **kwargs):
                return self.cursor_instance

        with MockCommands(OneRowConnection()) as commands:
            generator = commands.query("select id, name from some_table", buffered=False)
            assert list(generator) == [{"id": 1, "name": "Zach"}]

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

    def test_query_multiple_mapper(self, connection):
        with MockCommands(connection) as commands:
            data1, data2 = commands.query_multiple(
                ("select id, name from some_table", "select id, name from another_table"),
                mapper=(lambda row: row["id"], lambda row: row["name"]),
            )

        assert data1 == [1, 2]
        assert len(data2) == 2
        assert all(isinstance(name, str) for name in data2)

    def test_query_multiple_single_mapper_applies_to_each_result_set(self, connection):
        with MockCommands(connection) as commands:
            data1, data2 = commands.query_multiple(
                ("select id, name from some_table", "select id, name from another_table"),
                mapper=lambda row: row.columns,
            )

        assert data1 == [("id", "name"), ("id", "name")]
        assert data2 == [("id", "name"), ("id", "name")]

    def test_query_multiple_mapper_can_handle_duplicate_columns(self):
        with MockCommands(_CursorConnection(_DuplicateColumnCursor())) as commands:
            (data,) = commands.query_multiple(
                ("select id, name, id from some_table",),
                mapper=lambda row: row.values,
            )

        assert data == [(1, "Zach", 2)]

    def test_query_multiple_rejects_models_and_mapper(self, connection):
        with MockCommands(connection) as commands:
            with pytest.raises(ValueError, match="Pass either 'models' or 'mapper'"):
                commands.query_multiple(
                    ("select id, name from some_table",),
                    models=(dict,),
                    mapper=lambda row: row,
                )

    def test_query_multiple_rejects_mapper_count_mismatch(self, connection):
        with MockCommands(connection) as commands:
            with pytest.raises(ValueError, match="Number of queries must equal number of mappers"):
                commands.query_multiple(
                    ("select id, name from some_table", "select id, name from another_table"),
                    mapper=(lambda row: row,),
                )

    def test_query_multiple_rejects_duplicate_columns(self):
        with MockCommands(_CursorConnection(_DuplicateColumnCursor())) as commands:
            with pytest.raises(DuplicateColumnException) as exc_info:
                commands.query_multiple(("select id, name, id from some_table",))

        _assert_duplicate_column_exception(exc_info)

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

    @pytest.mark.parametrize(
        "queries",
        [
            pytest.param(
                (
                    "select id, name from some_table where id = ?missing?",
                    "select id, name from another_table",
                ),
                id="first_query",
            ),
            pytest.param(
                (
                    "select id, name from some_table",
                    "select id, name from another_table where id = ?missing?",
                ),
                id="later_query",
            ),
        ],
    )
    def test_query_multiple_missing_param_fails_before_cursor_acquisition(self, queries):
        class NoCursorConnection(MockConnection):
            def cursor(self, *args, **kwargs):
                raise AssertionError("cursor should not be opened")

        with MockCommands(NoCursorConnection()) as commands:
            with pytest.raises(MissingParameterException, match="missing"):
                commands.query_multiple(queries, params={})

    def test_query_multiple_missing_param_in_later_query_makes_no_dbapi_calls(self):
        events = []

        class RecordingCursor(MockCursor):
            def execute(self, sql, parameters=None):
                events.append("execute")

            def executemany(self, sql, params):
                events.append("executemany")

            def fetchone(self):
                events.append("fetchone")

            def fetchall(self):
                events.append("fetchall")

        class RecordingConnection(MockConnection):
            def cursor(self, *args, **kwargs):
                events.append("cursor")
                return RecordingCursor()

        with MockCommands(RecordingConnection()) as commands:
            with pytest.raises(MissingParameterException, match="missing"):
                commands.query_multiple(
                    (
                        "select id, name from some_table",
                        "select id, name from another_table where id = ?missing?",
                    ),
                    params={},
                )

        assert events == []

    def test_query_multiple_missing_attribute_param_record_fails_before_cursor_acquisition(self):
        class NoCursorConnection(MockConnection):
            def cursor(self, *args, **kwargs):
                raise AssertionError("cursor should not be opened")

        with MockCommands(NoCursorConnection()) as commands:
            with pytest.raises(MissingParameterException, match="missing"):
                commands.query_multiple(
                    (
                        "select id, name from some_table where id = ?id?",
                        "select id, name from another_table where id = ?missing?",
                    ),
                    params=SimpleNamespace(id=1),
                )

    @pytest.mark.parametrize(
        "mapper",
        [
            pytest.param(lambda row: row.values, id="single_mapper"),
            pytest.param((lambda row: row.values, lambda row: row.values), id="mapper_tuple"),
        ],
    )
    def test_query_multiple_missing_param_with_mapper_fails_before_cursor_acquisition(self, mapper):
        class NoCursorConnection(MockConnection):
            def cursor(self, *args, **kwargs):
                raise AssertionError("cursor should not be opened")

        with MockCommands(NoCursorConnection()) as commands:
            with pytest.raises(MissingParameterException, match="missing"):
                commands.query_multiple(
                    (
                        "select id, name from some_table",
                        "select id, name from another_table where id = ?missing?",
                    ),
                    mapper=mapper,
                    params={},
                )

    def test_query_multiple_constructs_all_handlers_before_cursor_entry_and_reuses_them(self):
        events = []

        class SpyParamHandler(MockParamHandler):
            def __init__(self, sql, param=None):
                events.append(("construct", self))
                super().__init__(sql, param)

            def execute(self, cursor):
                events.append(("execute", self))
                return super().execute(cursor)

        class SpyConnection(MockConnection):
            def cursor(self, *args, **kwargs):
                events.append(("cursor", None))
                return super().cursor(*args, **kwargs)

        class SpyCommands(MockCommands):
            SqlParamHandler = SpyParamHandler

        queries = ("select id, name from some_table", "select id, name from another_table")
        with SpyCommands(SpyConnection()) as commands:
            results = commands.query_multiple(queries)

        assert [name for name, _ in events] == ["construct", "construct", "cursor", "execute", "execute"]
        constructed = [handler for name, handler in events if name == "construct"]
        executed = [handler for name, handler in events if name == "execute"]
        assert all(used is created for used, created in zip(executed, constructed))
        assert [handler._sql for handler in executed] == list(queries)
        assert isinstance(results, tuple)
        assert [len(rows) for rows in results] == [2, 2]
        assert all(isinstance(row, dict) for rows in results for row in rows)

    def test_query_multiple_later_execute_error_wins_over_failing_cursor_exit(self):
        execute_error = RuntimeError("second execute failed")
        cursor = _MultiQueryExitCursor(
            execute_errors=(None, execute_error),
            exit_error=RuntimeError("cleanup failed"),
        )
        mapped = []

        def mapper(row):
            mapped.append(tuple(row.values))
            return tuple(row.values)

        # the first query's work is not rolled back (execution is not transactional), but raising here
        # guarantees no partial tuple containing the first result can be returned
        with pytest.raises(RuntimeError) as exc_info:
            MockCommands(_CursorConnection(cursor)).query_multiple(
                ("select id, name from some_table", "select id, name from another_table"),
                mapper=mapper,
            )

        assert exc_info.value is execute_error
        assert mapped == [(1, "Zach")]
        assert cursor.exit_calls == 1
        exc_type, exc_val, _ = cursor.exit_args
        assert exc_type is RuntimeError
        assert exc_val is execute_error
        assert cursor.exit_tb_was_active
        assert cursor.events == ["enter", ("execute", 0), ("fetchall", 0), ("execute", 1), ("exit", RuntimeError)]

    @pytest.mark.parametrize("exit_behavior", ["raises", "truthy"])
    def test_query_multiple_later_fetch_error_wins_over_native_cursor_exit(self, exit_behavior):
        fetch_error = RuntimeError("second fetch failed")
        cursor = _MultiQueryExitCursor(
            fetch_results=(((1, "Zach"),), fetch_error),
            exit_error=RuntimeError("cleanup failed") if exit_behavior == "raises" else None,
            exit_return=True if exit_behavior == "truthy" else None,
        )
        mapped = []

        def mapper(row):
            mapped.append(tuple(row.values))
            return tuple(row.values)

        with pytest.raises(RuntimeError) as exc_info:
            MockCommands(_CursorConnection(cursor)).query_multiple(
                ("select id, name from some_table", "select id, name from another_table"),
                mapper=mapper,
            )

        assert exc_info.value is fetch_error
        assert mapped == [(1, "Zach")]
        assert cursor.exit_calls == 1
        exc_type, exc_val, _ = cursor.exit_args
        assert exc_type is RuntimeError
        assert exc_val is fetch_error
        assert cursor.exit_tb_was_active

    def test_query_multiple_later_mapper_error_wins_over_failing_cursor_exit(self):
        mapper_error = ValueError("second mapper failed")
        cursor = _MultiQueryExitCursor(exit_error=RuntimeError("cleanup failed"))
        mapped = []

        def first_mapper(row):
            mapped.append(tuple(row.values))
            return tuple(row.values)

        def second_mapper(row):
            raise mapper_error

        with pytest.raises(ValueError) as exc_info:
            MockCommands(_CursorConnection(cursor)).query_multiple(
                ("select id, name from some_table", "select id, name from another_table"),
                mapper=(first_mapper, second_mapper),
            )

        assert exc_info.value is mapper_error
        assert mapped == [(1, "Zach")]
        assert cursor.exit_calls == 1
        exc_type, exc_val, _ = cursor.exit_args
        assert exc_type is ValueError
        assert exc_val is mapper_error
        assert cursor.exit_tb_was_active
        # the second mapper ran inside the cursor lifecycle: its failure reached the native exit
        assert cursor.events == [
            "enter",
            ("execute", 0),
            ("fetchall", 0),
            ("execute", 1),
            ("fetchall", 1),
            ("exit", ValueError),
        ]

    @pytest.mark.parametrize("exit_behavior", ["raises", "truthy"])
    def test_query_multiple_later_no_result_error_wins_over_native_cursor_exit(self, exit_behavior):
        cursor = _MultiQueryExitCursor(
            fetch_results=(((1, "Zach"),), tuple()),
            exit_error=RuntimeError("cleanup failed") if exit_behavior == "raises" else None,
            exit_return=True if exit_behavior == "truthy" else None,
        )
        mapped = []

        def mapper(row):
            mapped.append(tuple(row.values))
            return tuple(row.values)

        with pytest.raises(NoResultException) as exc_info:
            MockCommands(_CursorConnection(cursor)).query_multiple(
                ("select id, name from some_table", "select id, name from another_table"),
                mapper=mapper,
            )

        assert mapped == [(1, "Zach")]
        assert cursor.exit_calls == 1
        exc_type, exc_val, _ = cursor.exit_args
        assert exc_type is NoResultException
        assert exc_val is exc_info.value
        assert cursor.exit_tb_was_active

    @pytest.mark.parametrize("exit_behavior", ["raises", "truthy"])
    def test_query_multiple_later_duplicate_column_error_wins_over_native_cursor_exit(self, exit_behavior):
        cursor = _MultiQueryExitCursor(
            fetch_results=(((1, "Zach"),), ((1, "Zach", 2),)),
            descriptions=(
                (("id", "int"), ("name", "text")),
                (("id", "int"), ("name", "text"), ("id", "int")),
            ),
            exit_error=RuntimeError("cleanup failed") if exit_behavior == "raises" else None,
            exit_return=True if exit_behavior == "truthy" else None,
        )
        projected = []

        def first_model(**row):
            projected.append(row)
            return row

        with pytest.raises(DuplicateColumnException) as exc_info:
            MockCommands(_CursorConnection(cursor)).query_multiple(
                ("select id, name from some_table", "select id, name, id from another_table"),
                models=(first_model, dict),
            )

        _assert_duplicate_column_exception(exc_info)
        assert projected == [{"id": 1, "name": "Zach"}]
        assert cursor.exit_calls == 1
        exc_type, exc_val, _ = cursor.exit_args
        assert exc_type is DuplicateColumnException
        assert exc_val is exc_info.value
        assert cursor.exit_tb_was_active
        assert cursor.events == [
            "enter",
            ("execute", 0),
            ("fetchall", 0),
            ("execute", 1),
            ("fetchall", 1),
            ("exit", DuplicateColumnException),
        ]

    def test_query_multiple_mapper_still_receives_later_duplicate_columns(self):
        cursor = _MultiQueryExitCursor(
            fetch_results=(((1, "Zach"),), ((1, "Zach", 2),)),
            descriptions=(
                (("id", "int"), ("name", "text")),
                (("id", "int"), ("name", "text"), ("id", "int")),
            ),
        )

        data1, data2 = MockCommands(_CursorConnection(cursor)).query_multiple(
            ("select id, name from some_table", "select id, name, id from another_table"),
            mapper=lambda row: (row.columns, row.values),
        )

        assert data1 == [(("id", "name"), (1, "Zach"))]
        assert data2 == [(("id", "name", "id"), (1, "Zach", 2))]
        assert cursor.exit_args == (None, None, None)

    def test_query_multiple_propagates_native_cursor_exit_error_after_successful_batch(self):
        cleanup_error = RuntimeError("cleanup failed")
        cursor = _MultiQueryExitCursor(exit_error=cleanup_error)
        mapped = []

        def mapper(row):
            mapped.append(tuple(row.values))
            return tuple(row.values)

        with pytest.raises(RuntimeError) as exc_info:
            MockCommands(_CursorConnection(cursor)).query_multiple(
                ("select id, name from some_table", "select id, name from another_table"),
                mapper=mapper,
            )

        assert exc_info.value is cleanup_error
        assert mapped == [(1, "Zach"), (2, "Bob")]
        assert cursor.exit_calls == 1
        assert cursor.exit_args == (None, None, None)

    def test_query_multiple_runs_all_queries_on_one_cursor_lifecycle(self):
        cursor = _MultiQueryExitCursor()

        data1, data2 = MockCommands(_CursorConnection(cursor)).query_multiple(
            ("select id, name from some_table", "select id, name from another_table")
        )

        assert data1 == [{"id": 1, "name": "Zach"}]
        assert data2 == [{"id": 2, "name": "Bob"}]
        assert cursor.exit_calls == 1
        assert cursor.exit_args == (None, None, None)
        assert cursor.events == [
            "enter",
            ("execute", 0),
            ("fetchall", 0),
            ("execute", 1),
            ("fetchall", 1),
            ("exit", None),
        ]

    def test_query_first(self, connection):
        with MockCommands(connection) as commands:
            record = commands.query_first("select id, name from some_table", model=SimpleNamespace)
        assert isinstance(record, SimpleNamespace)
        assert record.id
        assert record.name

    def test_query_first_mapper(self, connection):
        with MockCommands(connection) as commands:
            record = commands.query_first("select id, name from some_table", mapper=lambda row: row["id"])

        assert record == 1

    def test_query_first_mapper_can_handle_duplicate_columns(self):
        with MockCommands(_CursorConnection(_DuplicateColumnCursor())) as commands:
            record = commands.query_first("select id, name, id from some_table", mapper=lambda row: row.values)

        assert record == (1, "Zach", 2)

    def test_query_first_rejects_model_and_mapper(self, connection):
        with MockCommands(connection) as commands:
            with pytest.raises(ValueError, match="Pass either 'model' or 'mapper'"):
                commands.query_first("select id, name from some_table", model=dict, mapper=lambda row: row)

    def test_query_first_rejects_duplicate_columns(self):
        with MockCommands(_CursorConnection(_DuplicateColumnCursor())) as commands:
            with pytest.raises(DuplicateColumnException) as exc_info:
                commands.query_first("select id, name, id from some_table")

        _assert_duplicate_column_exception(exc_info)

    def test_query_first_raises_on_no_result(self, connection, set_fetchone_to_return_none):
        with MockCommands(connection) as commands, pytest.raises(NoResultException):
            commands.query_first("select * from some_table")

    @pytest.mark.parametrize("exit_behavior", ["raises", "truthy"])
    def test_query_first_mapper_error_wins_over_native_cursor_exit(self, exit_behavior):
        mapper_error = ValueError("mapper failed")

        class RecordingExitCursor:
            rowcount = 0
            description = ("id", "int"), ("name", "text")

            def __init__(self):
                self.exit_calls = 0
                self.exit_args = None

            def __enter__(self):
                return self

            def __exit__(self, exc_type, exc_val, exc_tb):
                self.exit_calls += 1
                self.exit_args = exc_type, exc_val, exc_tb
                self.exit_tb_was_active = exc_tb is exc_val.__traceback__
                if exit_behavior == "raises":
                    raise RuntimeError("cleanup failed")
                return True

            def execute(self, sql, parameters=None):
                pass

            def fetchone(self):
                return 1, "Zach"

        def mapper(row):
            raise mapper_error

        cursor = RecordingExitCursor()

        with pytest.raises(ValueError) as exc_info:
            MockCommands(_CursorConnection(cursor)).query_first("select id, name from some_table", mapper=mapper)

        assert exc_info.value is mapper_error
        assert cursor.exit_calls == 1
        exc_type, exc_val, exc_tb = cursor.exit_args
        assert exc_type is ValueError
        assert exc_val is mapper_error
        assert cursor.exit_tb_was_active

    def test_query_first_propagates_native_cursor_exit_error_after_successful_mapping(self):
        cleanup_error = RuntimeError("cleanup failed")

        class FailingExitCursor:
            rowcount = 0
            description = ("id", "int"), ("name", "text")

            def __init__(self):
                self.exit_calls = 0
                self.exit_args = None

            def __enter__(self):
                return self

            def __exit__(self, exc_type, exc_val, exc_tb):
                self.exit_calls += 1
                self.exit_args = exc_type, exc_val, exc_tb
                raise cleanup_error

            def execute(self, sql, parameters=None):
                pass

            def fetchone(self):
                return 1, "Zach"

        cursor = FailingExitCursor()

        with pytest.raises(RuntimeError) as exc_info:
            MockCommands(_CursorConnection(cursor)).query_first(
                "select id, name from some_table", mapper=lambda row: row["id"]
            )

        assert exc_info.value is cleanup_error
        assert cursor.exit_calls == 1
        assert cursor.exit_args == (None, None, None)

    def test_query_first_or_default(self, connection, set_fetchone_to_return_none):
        default = SimpleNamespace(id=10, name="default")
        with MockCommands(connection) as commands:
            data = commands.query_first_or_default("select * from some_table", default=default)
        assert data is default

    def test_query_first_or_default_calls_callable_default_on_no_result(self, connection, set_fetchone_to_return_none):
        sentinel = object()
        calls = []

        def default():
            calls.append(None)
            return sentinel

        with MockCommands(connection) as commands:
            data = commands.query_first_or_default("select * from some_table", default=default)

        assert data is sentinel
        assert calls == [None]

    def test_query_first_or_default_calls_builtin_default_factory_on_no_result(
        self, connection, set_fetchone_to_return_none
    ):
        with MockCommands(connection) as commands:
            data = commands.query_first_or_default("select * from some_table", default=dict)

        assert data == {}

    def test_query_first_or_default_returns_callable_default_that_requires_args(
        self, connection, set_fetchone_to_return_none
    ):
        def default(row):
            return row

        with MockCommands(connection) as commands:
            data = commands.query_first_or_default("select * from some_table", default=default)

        assert data is default

    def test_query_first_or_default_propagates_uninspectable_callable_default_error(
        self, connection, set_fetchone_to_return_none, mocker
    ):
        calls = []
        error = TypeError("factory failed")

        def default():
            calls.append(None)
            raise error

        mocker.patch("pydapper.commands.signature", side_effect=ValueError("no signature"))

        with MockCommands(connection) as commands, pytest.raises(TypeError) as exc_info:
            commands.query_first_or_default("select * from some_table", default=default)

        assert exc_info.value is error
        assert calls == [None]

    def test_query_first_or_default_calls_uninspectable_callable_default(
        self, connection, set_fetchone_to_return_none, mocker
    ):
        sentinel = object()
        calls = []

        def default():
            calls.append(None)
            return sentinel

        mocker.patch("pydapper.commands.signature", side_effect=ValueError("no signature"))

        with MockCommands(connection) as commands:
            data = commands.query_first_or_default("select * from some_table", default=default)

        assert data is sentinel
        assert calls == [None]

    def test_query_first_or_default_returns_first_row(self, connection):
        calls = []

        def default():
            calls.append(None)
            return object()

        with MockCommands(connection) as commands:
            data = commands.query_first_or_default("select * from some_table", default=default)

        assert data["id"] == 1
        assert calls == []

    def test_query_first_or_default_model_returns_first_row(self, connection):
        with MockCommands(connection) as commands:
            data = commands.query_first_or_default("select * from some_table", default=None, model=SimpleNamespace)

        assert isinstance(data, SimpleNamespace)
        assert data.id == 1

    def test_query_first_or_default_mapper_returns_first_row(self, connection):
        with MockCommands(connection) as commands:
            data = commands.query_first_or_default("select * from some_table", default=None, mapper=lambda row: row[0])

        assert data == 1

    def test_query_first_or_default_rejects_model_and_mapper_before_default(
        self, connection, set_fetchone_to_return_none
    ):
        with MockCommands(connection) as commands:
            with pytest.raises(ValueError, match="Pass either 'model' or 'mapper'"):
                commands.query_first_or_default(
                    "select * from some_table",
                    default=None,
                    model=dict,
                    mapper=lambda row: row,
                )

    def test_query_single(self, connection, set_fetchall_return_one):
        with MockCommands(connection) as commands:
            record = commands.query_single("select * from some_table")
        assert isinstance(record, dict)
        assert record["id"]
        assert record["name"]

    def test_query_single_mapper(self, connection, set_fetchall_return_one):
        with MockCommands(connection) as commands:
            record = commands.query_single("select * from some_table", mapper=lambda row: row["id"])

        assert record == 1

    def test_query_single_mapper_can_handle_duplicate_columns(self):
        with MockCommands(_CursorConnection(_DuplicateColumnCursor())) as commands:
            record = commands.query_single("select id, name, id from some_table", mapper=lambda row: row.values)

        assert record == (1, "Zach", 2)

    def test_query_single_rejects_model_and_mapper(self, connection, set_fetchall_return_one):
        with MockCommands(connection) as commands:
            with pytest.raises(ValueError, match="Pass either 'model' or 'mapper'"):
                commands.query_single("select * from some_table", model=dict, mapper=lambda row: row)

    def test_query_single_rejects_duplicate_columns(self):
        with MockCommands(_CursorConnection(_DuplicateColumnCursor())) as commands:
            with pytest.raises(DuplicateColumnException) as exc_info:
                commands.query_single("select id, name, id from some_table")

        _assert_duplicate_column_exception(exc_info)

    def test_query_single_raises_on_no_result(self, connection, set_fetchone_to_return_none):
        with MockCommands(connection) as commands, pytest.raises(NoResultException):
            commands.query_single("select * from some_table")

    def test_query_single_raises_on_many_results(self, connection):
        with MockCommands(connection) as commands, pytest.raises(MoreThanOneResultException):
            commands.query_single("select * from some_table")

    def test_query_single_no_result_precedes_duplicate_column_mapping(self):
        connection = _CursorConnection(_DuplicateColumnCursor(rows=()))

        with pytest.raises(NoResultException):
            MockCommands(connection).query_single("select id, name, id from some_table")

    def test_query_single_many_results_precede_duplicate_column_mapping(self):
        connection = _CursorConnection(_DuplicateColumnCursor(rows=((1, "Zach", 2), (3, "Bob", 4))))

        with pytest.raises(MoreThanOneResultException):
            MockCommands(connection).query_single("select id, name, id from some_table")

    def test_query_single_uses_fetchmany_when_available(self):
        connection = _QuerySingleConnection(_QuerySingleFetchManyCursor([(1, "Zach")]))

        record = MockCommands(connection).query_single("select * from some_table")

        assert record == {"id": 1, "name": "Zach"}
        assert connection.cursor_instance.fetchmany_calls == [2]
        assert connection.cursor_instance.fetchone_calls == 0
        assert connection.cursor_instance.fetchall_calls == 0

    def test_query_single_fetchmany_raises_on_no_result(self):
        connection = _QuerySingleConnection(_QuerySingleFetchManyCursor([]))

        with pytest.raises(NoResultException):
            MockCommands(connection).query_single("select * from some_table")

        assert connection.cursor_instance.fetchmany_calls == [2]
        assert connection.cursor_instance.fetchone_calls == 0
        assert connection.cursor_instance.fetchall_calls == 0

    def test_query_single_fetchmany_consumes_at_most_two_rows_before_raising(self):
        connection = _QuerySingleConnection(_QuerySingleFetchManyCursor([(1, "Zach"), (2, "Bob"), (3, "Alice")]))

        with pytest.raises(MoreThanOneResultException):
            MockCommands(connection).query_single("select * from some_table")

        assert connection.cursor_instance.fetchmany_calls == [2]
        assert connection.cursor_instance.fetchall_calls == 0

    def test_query_single_fetchone_fallback_consumes_at_most_two_rows_before_raising(self):
        connection = _QuerySingleConnection(_QuerySingleFetchOneCursor([(1, "Zach"), (2, "Bob"), (3, "Alice")]))

        with pytest.raises(MoreThanOneResultException):
            MockCommands(connection).query_single("select * from some_table")

        assert connection.cursor_instance.fetchone_calls == 2
        assert connection.cursor_instance.fetchall_calls == 0

    def test_query_single_calls_more_than_one_hook_before_raising(self):
        calls = []

        class HookedCommands(MockCommands):
            def _on_query_single_more_than_one_result(self, cursor):
                calls.append(cursor)

        connection = _QuerySingleConnection(_QuerySingleFetchOneCursor([(1, "Zach"), (2, "Bob")]))

        with pytest.raises(MoreThanOneResultException):
            HookedCommands(connection).query_single("select * from some_table")

        assert calls == [connection.cursor_instance]

    @pytest.mark.parametrize("exit_behavior", ["raises", "truthy"])
    def test_query_single_mapper_error_wins_over_native_cursor_exit(self, exit_behavior):
        mapper_error = ValueError("mapper failed")

        class RecordingExitCursor:
            rowcount = 0
            description = ("id", "int"), ("name", "text")

            def __init__(self):
                self.exit_calls = 0
                self.exit_args = None

            def __enter__(self):
                return self

            def __exit__(self, exc_type, exc_val, exc_tb):
                self.exit_calls += 1
                self.exit_args = exc_type, exc_val, exc_tb
                self.exit_tb_was_active = exc_tb is exc_val.__traceback__
                if exit_behavior == "raises":
                    raise RuntimeError("cleanup failed")
                return True

            def execute(self, sql, parameters=None):
                pass

            def fetchmany(self, size):
                return [(1, "Zach")]

        def mapper(row):
            raise mapper_error

        cursor = RecordingExitCursor()

        with pytest.raises(ValueError) as exc_info:
            MockCommands(_CursorConnection(cursor)).query_single("select id, name from some_table", mapper=mapper)

        assert exc_info.value is mapper_error
        assert cursor.exit_calls == 1
        exc_type, exc_val, exc_tb = cursor.exit_args
        assert exc_type is ValueError
        assert exc_val is mapper_error
        assert cursor.exit_tb_was_active

    def test_query_single_propagates_native_cursor_exit_error_after_successful_mapping(self):
        cleanup_error = RuntimeError("cleanup failed")

        class FailingExitCursor:
            rowcount = 0
            description = ("id", "int"), ("name", "text")

            def __init__(self):
                self.exit_calls = 0
                self.exit_args = None

            def __enter__(self):
                return self

            def __exit__(self, exc_type, exc_val, exc_tb):
                self.exit_calls += 1
                self.exit_args = exc_type, exc_val, exc_tb
                raise cleanup_error

            def execute(self, sql, parameters=None):
                pass

            def fetchmany(self, size):
                return [(1, "Zach")]

        cursor = FailingExitCursor()

        with pytest.raises(RuntimeError) as exc_info:
            MockCommands(_CursorConnection(cursor)).query_single(
                "select id, name from some_table", mapper=lambda row: row["id"]
            )

        assert exc_info.value is cleanup_error
        assert cursor.exit_calls == 1
        assert cursor.exit_args == (None, None, None)

    @pytest.mark.parametrize(
        "rows, expected_exception",
        [
            ([], NoResultException),
            ([(1, "Zach"), (2, "Bob")], MoreThanOneResultException),
        ],
    )
    def test_query_single_cardinality_error_wins_over_native_cursor_exit_error(self, rows, expected_exception):
        hook_calls = []

        class FailingExitCursor:
            rowcount = 0
            description = ("id", "int"), ("name", "text")

            def __init__(self):
                self.exit_calls = 0
                self.exit_args = None

            def __enter__(self):
                return self

            def __exit__(self, exc_type, exc_val, exc_tb):
                self.exit_calls += 1
                self.exit_args = exc_type, exc_val, exc_tb
                raise RuntimeError("cleanup failed")

            def execute(self, sql, parameters=None):
                pass

            def fetchmany(self, size):
                return list(rows)

        class HookedCommands(MockCommands):
            def _on_query_single_more_than_one_result(self, cursor):
                hook_calls.append(cursor)

        cursor = FailingExitCursor()

        with pytest.raises(expected_exception) as exc_info:
            HookedCommands(_CursorConnection(cursor)).query_single("select id, name from some_table")

        assert cursor.exit_calls == 1
        exc_type, exc_val, exc_tb = cursor.exit_args
        assert exc_type is expected_exception
        assert exc_val is exc_info.value
        if expected_exception is MoreThanOneResultException:
            assert hook_calls == [cursor]
        else:
            assert hook_calls == []

    def test_query_single_duplicate_column_error_wins_over_native_cursor_exit_error(self):
        class FailingExitCursor:
            rowcount = 0
            description = ("id", "int"), ("name", "text"), ("id", "int")

            def __init__(self):
                self.exit_calls = 0
                self.exit_args = None

            def __enter__(self):
                return self

            def __exit__(self, exc_type, exc_val, exc_tb):
                self.exit_calls += 1
                self.exit_args = exc_type, exc_val, exc_tb
                raise RuntimeError("cleanup failed")

            def execute(self, sql, parameters=None):
                pass

            def fetchmany(self, size):
                return [(1, "Zach", 2)]

        cursor = FailingExitCursor()

        with pytest.raises(DuplicateColumnException) as exc_info:
            MockCommands(_CursorConnection(cursor)).query_single("select id, name, id from some_table")

        assert cursor.exit_calls == 1
        exc_type, exc_val, exc_tb = cursor.exit_args
        assert exc_type is DuplicateColumnException
        assert exc_val is exc_info.value

    def test_query_single_or_default(self, connection, set_fetchone_to_return_none):
        default = SimpleNamespace(id=10, name="default")
        with MockCommands(connection) as commands:
            record = commands.query_single_or_default("select * from some_table", default=default)
        assert record is default

    def test_query_single_or_default_calls_callable_default_on_no_result(self, connection, set_fetchone_to_return_none):
        sentinel = object()
        calls = []

        def default():
            calls.append(None)
            return sentinel

        with MockCommands(connection) as commands:
            record = commands.query_single_or_default("select * from some_table", default=default)

        assert record is sentinel
        assert calls == [None]

    def test_query_single_or_default_calls_builtin_default_factory_on_no_result(
        self, connection, set_fetchone_to_return_none
    ):
        with MockCommands(connection) as commands:
            record = commands.query_single_or_default("select * from some_table", default=set)

        assert record == set()

    def test_query_single_or_default_returns_callable_default_that_requires_args(
        self, connection, set_fetchone_to_return_none
    ):
        def default(row):
            return row

        with MockCommands(connection) as commands:
            record = commands.query_single_or_default("select * from some_table", default=default)

        assert record is default

    def test_query_single_or_default_returns_single_row(self, connection, set_fetchall_return_one):
        calls = []

        def default():
            calls.append(None)
            return object()

        with MockCommands(connection) as commands:
            record = commands.query_single_or_default("select * from some_table", default=default)

        assert record["id"] == 1
        assert calls == []

    def test_query_single_or_default_model_returns_single_row(self, connection, set_fetchall_return_one):
        with MockCommands(connection) as commands:
            record = commands.query_single_or_default("select * from some_table", default=None, model=SimpleNamespace)

        assert isinstance(record, SimpleNamespace)
        assert record.id == 1

    def test_query_single_or_default_mapper_returns_single_row(self, connection, set_fetchall_return_one):
        with MockCommands(connection) as commands:
            record = commands.query_single_or_default(
                "select * from some_table", default=None, mapper=lambda row: row[0]
            )

        assert record == 1

    def test_query_single_or_default_rejects_model_and_mapper_before_default(
        self, connection, set_fetchone_to_return_none
    ):
        with MockCommands(connection) as commands:
            with pytest.raises(ValueError, match="Pass either 'model' or 'mapper'"):
                commands.query_single_or_default(
                    "select * from some_table",
                    default=None,
                    model=dict,
                    mapper=lambda row: row,
                )

    def test_query_single_or_default_raises_on_many_results(self, connection):
        with MockCommands(connection) as commands, pytest.raises(MoreThanOneResultException):
            commands.query_single_or_default("select * from some_table", default=None)

    def test_execute_scalar(self, connection):
        with MockCommands(connection) as commands:
            id_ = commands.execute_scalar("select id, name from some_table")
        assert id_ == 1

    def test_execute_scalar_ignores_duplicate_columns(self):
        with MockCommands(_CursorConnection(_DuplicateColumnCursor())) as commands:
            assert commands.execute_scalar("select id, name, id from some_table") == 1

    def test_execute_scalar_raises_on_no_result(self, connection, set_fetchone_to_return_none):
        with MockCommands(connection) as commands, pytest.raises(NoResultException):
            commands.execute_scalar("select * from some_table")

    def test_execute_scalar_returns_none_for_null_first_column(
        self, connection, set_fetchone_to_return_null_first_column
    ):
        with MockCommands(connection) as commands:
            assert commands.execute_scalar("select nullable_column from some_table") is None

    @pytest.mark.parametrize("value", [0, False, ""], ids=["zero", "false", "empty-string"])
    def test_execute_scalar_preserves_falsey_first_column_values(self, value):
        cursor = _PlainQueryCursor(rows=[(value,)])
        with MockCommands(_CursorConnection(cursor)) as commands:
            assert commands.execute_scalar("select flag from some_table") == value

    @pytest.mark.parametrize("exit_behavior", ["raises", "truthy"])
    def test_execute_scalar_no_result_error_wins_over_native_cursor_exit(self, exit_behavior):
        class RecordingExitCursor:
            rowcount = 0

            def __init__(self):
                self.exit_calls = 0
                self.exit_args = None

            def __enter__(self):
                return self

            def __exit__(self, exc_type, exc_val, exc_tb):
                self.exit_calls += 1
                self.exit_args = exc_type, exc_val, exc_tb
                self.exit_tb_was_active = exc_tb is exc_val.__traceback__
                if exit_behavior == "raises":
                    raise RuntimeError("cleanup failed")
                return True

            def execute(self, sql, parameters=None):
                pass

            def fetchone(self):
                return None

        cursor = RecordingExitCursor()

        with pytest.raises(NoResultException) as exc_info:
            MockCommands(_CursorConnection(cursor)).execute_scalar("select id from some_table")

        assert cursor.exit_calls == 1
        exc_type, exc_val, exc_tb = cursor.exit_args
        assert exc_type is NoResultException
        assert exc_val is exc_info.value
        assert cursor.exit_tb_was_active

    def test_execute_scalar_propagates_native_cursor_exit_error_after_successful_fetch(self):
        cleanup_error = RuntimeError("cleanup failed")

        class FailingExitCursor:
            rowcount = 0

            def __init__(self):
                self.exit_calls = 0
                self.exit_args = None

            def __enter__(self):
                return self

            def __exit__(self, exc_type, exc_val, exc_tb):
                self.exit_calls += 1
                self.exit_args = exc_type, exc_val, exc_tb
                raise cleanup_error

            def execute(self, sql, parameters=None):
                pass

            def fetchone(self):
                return (42,)

        cursor = FailingExitCursor()

        with pytest.raises(RuntimeError) as exc_info:
            MockCommands(_CursorConnection(cursor)).execute_scalar("select id from some_table")

        assert exc_info.value is cleanup_error
        assert cursor.exit_calls == 1
        assert cursor.exit_args == (None, None, None)

    def test_execute_scalar_extraction_error_wins_over_native_cursor_exit_error(self):
        class MalformedRowCursor:
            rowcount = 0

            def __init__(self):
                self.exit_calls = 0
                self.exit_args = None

            def __enter__(self):
                return self

            def __exit__(self, exc_type, exc_val, exc_tb):
                self.exit_calls += 1
                self.exit_args = exc_type, exc_val, exc_tb
                raise RuntimeError("cleanup failed")

            def execute(self, sql, parameters=None):
                pass

            def fetchone(self):
                return ()

        cursor = MalformedRowCursor()

        with pytest.raises(IndexError) as exc_info:
            MockCommands(_CursorConnection(cursor)).execute_scalar("select id from some_table")

        assert cursor.exit_calls == 1
        exc_type, exc_val, exc_tb = cursor.exit_args
        assert exc_type is IndexError
        assert exc_val is exc_info.value


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
    def set_fetchone_to_return_null_first_column(self, mocker):
        async def fetchone(s):
            return FalsyRow((None,))

        mocker.patch("tests.mocks.MockAsyncCursor.fetchone", fetchone)

    @pytest.fixture
    def set_fetchall_return_one(self, faker, mocker):
        async def fetchall(s):
            return ((1, faker.name()),)

        mocker.patch("tests.mocks.MockAsyncCursor.fetchall", fetchall)

        rows = [(1, faker.name()), None]

        async def fetchone(s):
            return rows.pop(0) if rows else None

        mocker.patch("tests.mocks.MockAsyncCursor.fetchone", fetchone)

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
    async def test_execute_async_sends_prepared_sql_and_ordered_values_to_cursor(self):
        class RecordingCursor:
            rowcount = 1

            def __init__(self):
                self.calls = []

            async def __aenter__(self):
                return self

            async def __aexit__(self, exc_type, exc_val, exc_tb):
                pass

            async def execute(self, sql, parameters=None):
                self.calls.append((sql, parameters))

            async def executemany(self, *args, **kwargs):
                raise AssertionError("executemany should not be called")

        class RecordingConnection(MockAsyncConnection):
            def __init__(self):
                super().__init__()
                self.cursor_instance = RecordingCursor()

            async def cursor(self, *args, **kwargs):
                return self.cursor_instance

        connection = RecordingConnection()

        async with MockAsyncCommands(connection) as commands:
            affected_rows = await commands.execute_async(
                "update task set note = '?ignored?' where id = ?id? -- ?id?",
                params={"id": 1},
            )

        assert affected_rows == 1
        assert connection.cursor_instance.calls == [("update task set note = '?ignored?' where id = %s -- ?id?", (1,))]

    @pytest.mark.asyncio
    async def test_execute_async_with_empty_top_level_list_params_returns_zero_without_opening_cursor(self):
        class NoCursorConnection(MockAsyncConnection):
            async def cursor(self, *args, **kwargs):
                raise AssertionError("cursor should not be opened")

        async with MockAsyncCommands(NoCursorConnection()) as commands:
            assert await commands.execute_async("insert into some_table (id) values (?id?)", params=[]) == 0

    @pytest.mark.asyncio
    async def test_execute_async_uses_executemany_for_mixed_record_list_params(self):
        class RecordingCursor:
            rowcount = 2

            def __init__(self):
                self.calls = []

            async def __aenter__(self):
                return self

            async def __aexit__(self, exc_type, exc_val, exc_tb):
                pass

            async def execute(self, *args, **kwargs):
                raise AssertionError("execute should not be called")

            async def executemany(self, sql, params):
                self.calls.append((sql, params))

        class RecordingConnection(MockAsyncConnection):
            def __init__(self):
                super().__init__()
                self.cursor_instance = RecordingCursor()

            async def cursor(self, *args, **kwargs):
                return self.cursor_instance

        connection = RecordingConnection()

        async with MockAsyncCommands(connection) as commands:
            affected_rows = await commands.execute_async(
                "insert into some_table (id) values (?id?)",
                params=[{"id": 1}, SimpleNamespace(id=2)],
            )

        assert affected_rows == 2
        assert connection.cursor_instance.calls == [
            ("insert into some_table (id) values (%s)", [(1,), (2,)]),
        ]

    @pytest.mark.asyncio
    async def test_execute_async_error_wins_over_native_cursor_exit_error(self):
        command_error = ValueError("execute failed")

        class ExplodingAsyncCursor:
            def __init__(self):
                self.enter_calls = 0
                self.exit_calls = 0
                self.exit_args = None

            async def __aenter__(self):
                self.enter_calls += 1
                return self

            async def __aexit__(self, exc_type, exc_val, exc_tb):
                self.exit_calls += 1
                self.exit_args = exc_type, exc_val, exc_tb
                self.exit_tb_was_active = exc_tb is exc_val.__traceback__
                raise RuntimeError("cleanup failed")

            async def execute(self, sql, parameters=None):
                raise command_error

        class CountingAsyncCursorConnection:
            def __init__(self, cursor):
                self.cursor_instance = cursor
                self.cursor_calls = 0

            async def cursor(self, *args, **kwargs):
                self.cursor_calls += 1
                return self.cursor_instance

        cursor = ExplodingAsyncCursor()
        connection = CountingAsyncCursorConnection(cursor)

        with pytest.raises(ValueError) as exc_info:
            await MockAsyncCommands(connection).execute_async("insert into some_table (id) values (1)")

        assert exc_info.value is command_error
        assert connection.cursor_calls == 1
        assert cursor.enter_calls == 1
        assert cursor.exit_calls == 1
        exc_type, exc_val, exc_tb = cursor.exit_args
        assert exc_type is ValueError
        assert exc_val is command_error
        assert cursor.exit_tb_was_active

    @pytest.mark.asyncio
    async def test_execute_async_error_wins_over_truthy_native_cursor_exit(self):
        command_error = ValueError("execute failed")

        class SuppressingAsyncCursor:
            def __init__(self):
                self.exit_calls = 0
                self.exit_args = None

            async def __aenter__(self):
                return self

            async def __aexit__(self, exc_type, exc_val, exc_tb):
                self.exit_calls += 1
                self.exit_args = exc_type, exc_val, exc_tb
                self.exit_tb_was_active = exc_tb is exc_val.__traceback__
                return True

            async def execute(self, sql, parameters=None):
                raise command_error

        cursor = SuppressingAsyncCursor()

        with pytest.raises(ValueError) as exc_info:
            await MockAsyncCommands(_PlainAsyncQueryConnection(cursor)).execute_async(
                "insert into some_table (id) values (1)"
            )

        assert exc_info.value is command_error
        assert cursor.exit_calls == 1
        exc_type, exc_val, exc_tb = cursor.exit_args
        assert exc_type is ValueError
        assert exc_val is command_error
        assert cursor.exit_tb_was_active

    @pytest.mark.asyncio
    async def test_execute_async_propagates_native_cursor_exit_error_after_success(self):
        cleanup_error = RuntimeError("cleanup failed")

        class FailingExitCursor:
            rowcount = 3

            def __init__(self):
                self.exit_calls = 0
                self.exit_args = None
                self.execute_calls = 0

            async def __aenter__(self):
                return self

            async def __aexit__(self, exc_type, exc_val, exc_tb):
                self.exit_calls += 1
                self.exit_args = exc_type, exc_val, exc_tb
                raise cleanup_error

            async def execute(self, sql, parameters=None):
                self.execute_calls += 1

        cursor = FailingExitCursor()

        with pytest.raises(RuntimeError) as exc_info:
            await MockAsyncCommands(_PlainAsyncQueryConnection(cursor)).execute_async(
                "insert into some_table (id) values (1)"
            )

        assert exc_info.value is cleanup_error
        assert cursor.execute_calls == 1
        assert cursor.exit_calls == 1
        assert cursor.exit_args == (None, None, None)

    @pytest.mark.asyncio
    async def test_execute_async_error_wins_over_plain_cursor_sync_close_error(self):
        command_error = ValueError("execute failed")

        class SyncClosePlainCursor:
            rowcount = 0

            def __init__(self):
                self.close_calls = 0

            async def execute(self, sql, parameters=None):
                raise command_error

            def close(self):
                self.close_calls += 1
                raise RuntimeError("close failed")

        cursor = SyncClosePlainCursor()

        with pytest.raises(ValueError) as exc_info:
            await MockAsyncCommands(_PlainAsyncQueryConnection(cursor)).execute_async(
                "insert into some_table (id) values (1)"
            )

        assert exc_info.value is command_error
        assert cursor.close_calls == 1

    @pytest.mark.asyncio
    async def test_execute_async_error_wins_over_plain_cursor_awaitable_close_error(self):
        command_error = ValueError("execute failed")
        cursor = _PlainAsyncQueryCursor()
        cursor.execute_error = command_error
        cursor.close_error = RuntimeError("close failed")

        with pytest.raises(ValueError) as exc_info:
            await MockAsyncCommands(_PlainAsyncQueryConnection(cursor)).execute_async(
                "insert into some_table (id) values (1)"
            )

        assert exc_info.value is command_error
        assert cursor.close_calls == 1

    @pytest.mark.asyncio
    @pytest.mark.parametrize("close_style", ["sync", "awaitable"])
    async def test_execute_async_propagates_plain_cursor_close_error_after_success(self, close_style):
        cleanup_error = RuntimeError("close failed")

        class SyncClosePlainCursor:
            rowcount = 1

            def __init__(self):
                self.close_calls = 0

            async def execute(self, sql, parameters=None):
                pass

            def close(self):
                self.close_calls += 1
                raise cleanup_error

        if close_style == "sync":
            cursor = SyncClosePlainCursor()
        else:
            cursor = _PlainAsyncQueryCursor()
            cursor.close_error = cleanup_error

        with pytest.raises(RuntimeError) as exc_info:
            await MockAsyncCommands(_PlainAsyncQueryConnection(cursor)).execute_async(
                "insert into some_table (id) values (1)"
            )

        assert exc_info.value is cleanup_error
        assert cursor.close_calls == 1

    @pytest.mark.asyncio
    async def test_connection_wrapper_still_honors_truthy_connection_exit(self):
        class SuppressingAsyncConnection(MockAsyncConnection):
            def __init__(self):
                super().__init__()
                self.exit_calls = 0

            async def __aexit__(self, exc_type, exc_val, exc_tb):
                self.exit_calls += 1
                return True

        connection = SuppressingAsyncConnection()

        async def connect():
            return MockAsyncCommands(connection)

        # mirrors CommandFactory.from_dsn_async, which wraps the connection without preserve_active_error
        async with _AwaitableAsyncContextManager(connect()) as commands:
            assert commands.connection is connection
            raise ValueError("body")

        assert connection.exit_calls == 1

    @pytest.mark.asyncio
    @pytest.mark.parametrize(
        "params, exception_type",
        [
            ([{"id": 1}, 2], InvalidParameterShapeException),
            ([{"id": 1}, {}], MissingParameterException),
        ],
    )
    async def test_execute_async_rejects_invalid_executemany_records_before_opening_cursor(
        self, params, exception_type
    ):
        class NoCursorConnection(MockAsyncConnection):
            async def cursor(self, *args, **kwargs):
                raise AssertionError("cursor should not be opened")

        async with MockAsyncCommands(NoCursorConnection()) as commands:
            with pytest.raises(exception_type):
                await commands.execute_async("insert into some_table (id) values (?id?)", params=params)

    @pytest.mark.asyncio
    @pytest.mark.parametrize("call", ASYNC_READ_LIST_PARAMS_CALLS)
    async def test_read_methods_reject_top_level_list_params_before_opening_cursor(self, call):
        class NoCursorConnection(MockAsyncConnection):
            async def cursor(self, *args, **kwargs):
                raise AssertionError("cursor should not be opened")

        async with MockAsyncCommands(NoCursorConnection()) as commands:
            with pytest.raises(InvalidParameterShapeException):
                await call(commands)

    @pytest.mark.asyncio
    @pytest.mark.parametrize("call", ASYNC_READ_LIST_PARAMS_CALLS)
    async def test_read_methods_reject_top_level_list_params(self, connection, call):
        async with MockAsyncCommands(connection) as commands:
            with pytest.raises(InvalidParameterShapeException):
                await call(commands)

    @pytest.mark.asyncio
    @pytest.mark.parametrize("call, expected_handler_count", ASYNC_PARAMS_CALLS)
    async def test_public_methods_accept_params(
        self, connection, captured_handler_params, set_fetchall_return_one, call, expected_handler_count
    ):
        params = {"id": 1}

        async with MockAsyncCommands(connection) as commands:
            await call(commands, params)

        assert captured_handler_params == [params] * expected_handler_count

    @pytest.mark.asyncio
    @pytest.mark.parametrize("call", ASYNC_ALIAS_CONFLICT_CALLS)
    async def test_public_methods_reject_param_and_params(self, connection, call):
        params = {"id": 1}

        async with MockAsyncCommands(connection) as commands:
            with pytest.raises(ValueError, match="Pass either 'params' or 'param'"):
                await call(commands, params)

    @pytest.mark.asyncio
    async def test_or_default_methods_delegate_param_spelling_and_normalized_options(self, connection):
        received = []

        class ParamSpellingOverrideCommands(MockAsyncCommands):
            async def query_first_async(self, sql, model=dict, param=None, *, options=None):
                received.append(("first", param, options))
                raise NoResultException

            async def query_single_async(self, sql, model=dict, param=None, *, options=None):
                received.append(("single", param, options))
                raise NoResultException

        default = object()

        async with ParamSpellingOverrideCommands(connection) as commands:
            assert (
                await commands.query_first_or_default_async(
                    "select * from some_table where id = ?id?", default, params={"id": 1}
                )
                is default
            )
            assert (
                await commands.query_single_or_default_async(
                    "select * from some_table where id = ?id?", default, params={"id": 1}
                )
                is default
            )

        assert received == [
            ("first", {"id": 1}, pydapper.CommandOptions()),
            ("single", {"id": 1}, pydapper.CommandOptions()),
        ]

    @pytest.mark.asyncio
    async def test_query(self, connection):
        async with MockAsyncCommands(connection) as commands:
            data = await commands.query_async("select id, name from some_table", model=SimpleNamespace)
        assert len(data) == 2
        assert all(isinstance(row, SimpleNamespace) for row in data)

    @pytest.mark.asyncio
    async def test_query_mapper_receives_raw_rows(self, connection):
        seen_rows = []

        def mapper(row):
            seen_rows.append(row)
            return row.columns, row.values, row[0], row["name"]

        async with MockAsyncCommands(connection) as commands:
            data = await commands.query_async("select id, name from some_table", mapper=mapper)

        assert len(data) == 2
        assert data[0][0] == ("id", "name")
        assert data[0][1][0] == 1
        assert data[0][2] == 1
        assert seen_rows
        assert all(isinstance(row, RawRow) for row in seen_rows)

    @pytest.mark.asyncio
    async def test_query_mapper_can_handle_duplicate_columns(self):
        async with MockAsyncCommands(_AsyncCursorConnection(_AsyncDuplicateColumnCursor())) as commands:
            data = await commands.query_async(
                "select id, name, id from some_table",
                mapper=lambda row: (row.columns, row.values[0], row.values[2]),
            )

        assert data == [(("id", "name", "id"), 1, 2)]

    @pytest.mark.asyncio
    async def test_query_unbuffered_mapper_can_handle_duplicate_columns(self):
        async with MockAsyncCommands(_AsyncCursorConnection(_AsyncDuplicateColumnCursor())) as commands:
            generator = await commands.query_async(
                "select id, name, id from some_table",
                mapper=lambda row: row.values,
                buffered=False,
            )

            assert [row async for row in generator] == [(1, "Zach", 2)]

    @pytest.mark.asyncio
    async def test_query_unbuffered_mapper_yields_multiple_rows(self):
        connection = _AsyncCursorConnection(_AsyncQuerySingleFetchOneCursor([(1, "Zach"), (2, "Bob")]))

        async with MockAsyncCommands(connection) as commands:
            generator = await commands.query_async(
                "select id, name from some_table",
                mapper=lambda row: row[0],
                buffered=False,
            )

            assert [row async for row in generator] == [1, 2]

    @pytest.mark.asyncio
    async def test_plain_cursor_is_closed_after_buffered_query(self):
        cursor = _PlainAsyncQueryCursor()

        assert await MockAsyncCommands(_PlainAsyncQueryConnection(cursor)).query_async(
            "select id, name from some_table"
        ) == [{"id": 1, "name": "Zach"}, {"id": 2, "name": "Bob"}]
        assert cursor.close_calls == 1

    @pytest.mark.asyncio
    async def test_plain_cursor_cleanup_preserves_buffered_failure(self):
        cursor = _PlainAsyncQueryCursor()
        cursor.fetchall_error = RuntimeError("fetch failed")

        with pytest.raises(RuntimeError, match="fetch failed"):
            await MockAsyncCommands(_PlainAsyncQueryConnection(cursor)).query_async("select id, name from some_table")

        assert cursor.close_calls == 1

    @pytest.mark.asyncio
    async def test_plain_cursor_cleanup_failure_does_not_mask_buffered_failure(self):
        cursor = _PlainAsyncQueryCursor()
        cursor.fetchall_error = RuntimeError("fetch failed")
        cursor.close_error = RuntimeError("close failed")

        with pytest.raises(RuntimeError, match="fetch failed"):
            await MockAsyncCommands(_PlainAsyncQueryConnection(cursor)).query_async("select id, name from some_table")

    @pytest.mark.asyncio
    async def test_context_managed_cursor_cleanup_failure_does_not_mask_buffered_failure(self):
        class FailingExitCursor(MockAsyncCursor):
            async def __aexit__(self, exc_type, exc_val, exc_tb):
                raise RuntimeError("close failed")

        cursor = FailingExitCursor()

        with pytest.raises(RuntimeError, match="projection failed"):
            await MockAsyncCommands(_AsyncCursorConnection(cursor)).query_async(
                "select id, name from some_table",
                mapper=lambda row: (_ for _ in ()).throw(RuntimeError("projection failed")),
            )

    @pytest.mark.asyncio
    async def test_plain_cursor_is_closed_when_projection_fails(self):
        cursor = _PlainAsyncQueryCursor()

        with pytest.raises(RuntimeError, match="projection failed"):
            await MockAsyncCommands(_PlainAsyncQueryConnection(cursor)).query_async(
                "select id, name from some_table",
                mapper=lambda row: (_ for _ in ()).throw(RuntimeError("projection failed")),
            )

        assert cursor.close_calls == 1

    @pytest.mark.asyncio
    async def test_plain_cursor_is_closed_by_unbuffered_generator_aclose(self):
        cursor = _PlainAsyncQueryCursor()
        rows = await MockAsyncCommands(_PlainAsyncQueryConnection(cursor)).query_async(
            "select id, name from some_table", buffered=False
        )

        assert await rows.__anext__() == {"id": 1, "name": "Zach"}
        await rows.aclose()
        assert cursor.close_calls == 1

    @pytest.mark.asyncio
    async def test_plain_cursor_is_closed_after_unbuffered_exhaustion(self):
        cursor = _PlainAsyncQueryCursor()
        rows = await MockAsyncCommands(_PlainAsyncQueryConnection(cursor)).query_async(
            "select id, name from some_table", buffered=False
        )

        assert [row async for row in rows] == [{"id": 1, "name": "Zach"}, {"id": 2, "name": "Bob"}]
        assert cursor.close_calls == 1

    @pytest.mark.asyncio
    async def test_plain_cursor_cleanup_preserves_unbuffered_failure(self):
        cursor = _PlainAsyncQueryCursor()
        cursor.fetchone_error = RuntimeError("fetch failed")
        rows = await MockAsyncCommands(_PlainAsyncQueryConnection(cursor)).query_async(
            "select id, name from some_table", buffered=False
        )

        with pytest.raises(RuntimeError, match="fetch failed"):
            await rows.__anext__()

        assert cursor.close_calls == 1

    @pytest.mark.asyncio
    async def test_query_rejects_model_and_mapper(self, connection):
        async with MockAsyncCommands(connection) as commands:
            with pytest.raises(ValueError, match="Pass either 'model' or 'mapper'"):
                await commands.query_async(
                    "select id, name from some_table", model=SimpleNamespace, mapper=lambda row: row
                )

    @pytest.mark.asyncio
    async def test_query_rejects_duplicate_columns(self):
        async with MockAsyncCommands(_AsyncCursorConnection(_AsyncDuplicateColumnCursor())) as commands:
            with pytest.raises(DuplicateColumnException) as exc_info:
                await commands.query_async("select id, name, id from some_table")

        _assert_duplicate_column_exception(exc_info)

    @pytest.mark.asyncio
    async def test_query_rejects_duplicate_columns_with_no_rows(self):
        async with MockAsyncCommands(_AsyncCursorConnection(_AsyncDuplicateColumnCursor(rows=()))) as commands:
            with pytest.raises(DuplicateColumnException) as exc_info:
                await commands.query_async("select id, name, id from some_table")

        _assert_duplicate_column_exception(exc_info)

    @pytest.mark.asyncio
    async def test_query_returns_empty_list_on_no_results(self, connection, set_fetchall_return_empty):
        async with MockAsyncCommands(connection) as commands:
            data = await commands.query_async("select id, name from some_table")
        assert data == []

    @pytest.mark.asyncio
    async def test_query_unbuffered_yields_no_rows_on_no_results(self, connection, set_fetchone_to_return_none):
        async with MockAsyncCommands(connection) as commands:
            generator = await commands.query_async("select id, name from some_table", buffered=False)
            assert [row async for row in generator] == []

    @pytest.mark.asyncio
    async def test_query_unbuffered_rejects_duplicate_columns(self):
        async with MockAsyncCommands(_AsyncCursorConnection(_AsyncDuplicateColumnCursor())) as commands:
            generator = await commands.query_async("select id, name, id from some_table", buffered=False)
            with pytest.raises(DuplicateColumnException) as exc_info:
                [row async for row in generator]

        _assert_duplicate_column_exception(exc_info)

    @pytest.mark.asyncio
    async def test_query_unbuffered_rejects_duplicate_columns_with_no_rows(self):
        async with MockAsyncCommands(_AsyncCursorConnection(_AsyncDuplicateColumnCursor(rows=()))) as commands:
            generator = await commands.query_async("select id, name, id from some_table", buffered=False)
            with pytest.raises(DuplicateColumnException) as exc_info:
                [row async for row in generator]

        _assert_duplicate_column_exception(exc_info)

    @pytest.mark.asyncio
    async def test_query_unbuffered_yields_rows_until_none(self):
        class OneRowAsyncCursor(MockAsyncCursor):
            def __init__(self):
                super().__init__()
                self.rows = [(1, "Zach"), None]

            async def fetchone(self):
                return self.rows.pop(0)

        class OneRowAsyncConnection(MockAsyncConnection):
            def __init__(self):
                super().__init__()
                self.cursor_instance = OneRowAsyncCursor()

            async def cursor(self, *args, **kwargs):
                return self.cursor_instance

        async with MockAsyncCommands(OneRowAsyncConnection()) as commands:
            generator = await commands.query_async("select id, name from some_table", buffered=False)
            records = [record async for record in generator]

        assert records == [{"id": 1, "name": "Zach"}]

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
    async def test_query_multiple_mapper(self, connection):
        async with MockAsyncCommands(connection) as commands:
            data1, data2 = await commands.query_multiple_async(
                ("select id, name from some_table", "select id, name from another_table"),
                mapper=(lambda row: row["id"], lambda row: row["name"]),
            )

        assert data1 == [1, 2]
        assert len(data2) == 2
        assert all(isinstance(name, str) for name in data2)

    @pytest.mark.asyncio
    async def test_query_multiple_single_mapper_applies_to_each_result_set(self, connection):
        async with MockAsyncCommands(connection) as commands:
            data1, data2 = await commands.query_multiple_async(
                ("select id, name from some_table", "select id, name from another_table"),
                mapper=lambda row: row.columns,
            )

        assert data1 == [("id", "name"), ("id", "name")]
        assert data2 == [("id", "name"), ("id", "name")]

    @pytest.mark.asyncio
    async def test_query_multiple_mapper_can_handle_duplicate_columns(self):
        async with MockAsyncCommands(_AsyncCursorConnection(_AsyncDuplicateColumnCursor())) as commands:
            (data,) = await commands.query_multiple_async(
                ("select id, name, id from some_table",),
                mapper=lambda row: row.values,
            )

        assert data == [(1, "Zach", 2)]

    @pytest.mark.asyncio
    async def test_query_multiple_rejects_models_and_mapper(self, connection):
        async with MockAsyncCommands(connection) as commands:
            with pytest.raises(ValueError, match="Pass either 'models' or 'mapper'"):
                await commands.query_multiple_async(
                    ("select id, name from some_table",),
                    models=(dict,),
                    mapper=lambda row: row,
                )

    @pytest.mark.asyncio
    async def test_query_multiple_rejects_mapper_count_mismatch(self, connection):
        async with MockAsyncCommands(connection) as commands:
            with pytest.raises(ValueError, match="Number of queries must equal number of mappers"):
                await commands.query_multiple_async(
                    ("select id, name from some_table", "select id, name from another_table"),
                    mapper=(lambda row: row,),
                )

    @pytest.mark.asyncio
    async def test_query_multiple_rejects_duplicate_columns(self):
        async with MockAsyncCommands(_AsyncCursorConnection(_AsyncDuplicateColumnCursor())) as commands:
            with pytest.raises(DuplicateColumnException) as exc_info:
                await commands.query_multiple_async(("select id, name, id from some_table",))

        _assert_duplicate_column_exception(exc_info)

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
    @pytest.mark.parametrize(
        "queries",
        [
            pytest.param(
                (
                    "select id, name from some_table where id = ?missing?",
                    "select id, name from another_table",
                ),
                id="first_query",
            ),
            pytest.param(
                (
                    "select id, name from some_table",
                    "select id, name from another_table where id = ?missing?",
                ),
                id="later_query",
            ),
        ],
    )
    async def test_query_multiple_missing_param_fails_before_cursor_acquisition(self, queries):
        class NoCursorAsyncConnection(MockAsyncConnection):
            async def cursor(self, *args, **kwargs):
                raise AssertionError("cursor should not be opened")

        async with MockAsyncCommands(NoCursorAsyncConnection()) as commands:
            with pytest.raises(MissingParameterException, match="missing"):
                await commands.query_multiple_async(queries, params={})

    @pytest.mark.asyncio
    async def test_query_multiple_missing_param_in_later_query_makes_no_dbapi_calls(self):
        events = []

        class RecordingAsyncCursor(MockAsyncCursor):
            async def execute(self, sql, parameters=None):
                events.append("execute")

            async def executemany(self, sql, params=None):
                events.append("executemany")

            async def fetchone(self):
                events.append("fetchone")

            async def fetchall(self):
                events.append("fetchall")

        class RecordingAsyncConnection(MockAsyncConnection):
            async def cursor(self, *args, **kwargs):
                events.append("cursor")
                return RecordingAsyncCursor()

        async with MockAsyncCommands(RecordingAsyncConnection()) as commands:
            with pytest.raises(MissingParameterException, match="missing"):
                await commands.query_multiple_async(
                    (
                        "select id, name from some_table",
                        "select id, name from another_table where id = ?missing?",
                    ),
                    params={},
                )

        assert events == []

    @pytest.mark.asyncio
    @pytest.mark.parametrize(
        "mapper",
        [
            pytest.param(lambda row: row.values, id="single_mapper"),
            pytest.param((lambda row: row.values, lambda row: row.values), id="mapper_tuple"),
        ],
    )
    async def test_query_multiple_missing_param_with_mapper_fails_before_cursor_acquisition(self, mapper):
        class NoCursorAsyncConnection(MockAsyncConnection):
            async def cursor(self, *args, **kwargs):
                raise AssertionError("cursor should not be opened")

        async with MockAsyncCommands(NoCursorAsyncConnection()) as commands:
            with pytest.raises(MissingParameterException, match="missing"):
                await commands.query_multiple_async(
                    (
                        "select id, name from some_table",
                        "select id, name from another_table where id = ?missing?",
                    ),
                    mapper=mapper,
                    params={},
                )

    @pytest.mark.asyncio
    async def test_query_multiple_constructs_all_handlers_before_cursor_entry_and_reuses_them(self):
        events = []

        class SpyParamHandler(MockParamHandler):
            def __init__(self, sql, param=None):
                events.append(("construct", self))
                super().__init__(sql, param)

            async def execute_async(self, cursor):
                events.append(("execute", self))
                return await super().execute_async(cursor)

        class SpyAsyncConnection(MockAsyncConnection):
            async def cursor(self, *args, **kwargs):
                events.append(("cursor", None))
                return await super().cursor(*args, **kwargs)

        class SpyAsyncCommands(MockAsyncCommands):
            SqlParamHandler = SpyParamHandler

        queries = ("select id, name from some_table", "select id, name from another_table")
        async with SpyAsyncCommands(SpyAsyncConnection()) as commands:
            results = await commands.query_multiple_async(queries)

        assert [name for name, _ in events] == ["construct", "construct", "cursor", "execute", "execute"]
        constructed = [handler for name, handler in events if name == "construct"]
        executed = [handler for name, handler in events if name == "execute"]
        assert all(used is created for used, created in zip(executed, constructed))
        assert [handler._sql for handler in executed] == list(queries)
        assert isinstance(results, tuple)
        assert [len(rows) for rows in results] == [2, 2]
        assert all(isinstance(row, dict) for rows in results for row in rows)

    @pytest.mark.asyncio
    async def test_query_multiple_async_later_execute_error_wins_over_failing_cursor_exit(self):
        execute_error = RuntimeError("second execute failed")
        cursor = _AsyncMultiQueryExitCursor(
            execute_errors=(None, execute_error),
            exit_error=RuntimeError("cleanup failed"),
        )
        mapped = []

        def mapper(row):
            mapped.append(tuple(row.values))
            return tuple(row.values)

        # the first query's work is not rolled back (execution is not transactional), but raising here
        # guarantees no partial tuple containing the first result can be returned
        with pytest.raises(RuntimeError) as exc_info:
            await MockAsyncCommands(_PlainAsyncQueryConnection(cursor)).query_multiple_async(
                ("select id, name from some_table", "select id, name from another_table"),
                mapper=mapper,
            )

        assert exc_info.value is execute_error
        assert mapped == [(1, "Zach")]
        assert cursor.exit_calls == 1
        exc_type, exc_val, _ = cursor.exit_args
        assert exc_type is RuntimeError
        assert exc_val is execute_error
        assert cursor.exit_tb_was_active
        assert cursor.events == ["enter", ("execute", 0), ("fetchall", 0), ("execute", 1), ("exit", RuntimeError)]

    @pytest.mark.asyncio
    @pytest.mark.parametrize("exit_behavior", ["raises", "truthy"])
    async def test_query_multiple_async_later_fetch_error_wins_over_native_cursor_exit(self, exit_behavior):
        fetch_error = RuntimeError("second fetch failed")
        cursor = _AsyncMultiQueryExitCursor(
            fetch_results=(((1, "Zach"),), fetch_error),
            exit_error=RuntimeError("cleanup failed") if exit_behavior == "raises" else None,
            exit_return=True if exit_behavior == "truthy" else None,
        )
        mapped = []

        def mapper(row):
            mapped.append(tuple(row.values))
            return tuple(row.values)

        with pytest.raises(RuntimeError) as exc_info:
            await MockAsyncCommands(_PlainAsyncQueryConnection(cursor)).query_multiple_async(
                ("select id, name from some_table", "select id, name from another_table"),
                mapper=mapper,
            )

        assert exc_info.value is fetch_error
        assert mapped == [(1, "Zach")]
        assert cursor.exit_calls == 1
        exc_type, exc_val, _ = cursor.exit_args
        assert exc_type is RuntimeError
        assert exc_val is fetch_error
        assert cursor.exit_tb_was_active

    @pytest.mark.asyncio
    async def test_query_multiple_async_later_mapper_error_wins_over_failing_cursor_exit(self):
        mapper_error = ValueError("second mapper failed")
        cursor = _AsyncMultiQueryExitCursor(exit_error=RuntimeError("cleanup failed"))
        mapped = []

        def first_mapper(row):
            mapped.append(tuple(row.values))
            return tuple(row.values)

        def second_mapper(row):
            raise mapper_error

        with pytest.raises(ValueError) as exc_info:
            await MockAsyncCommands(_PlainAsyncQueryConnection(cursor)).query_multiple_async(
                ("select id, name from some_table", "select id, name from another_table"),
                mapper=(first_mapper, second_mapper),
            )

        assert exc_info.value is mapper_error
        assert mapped == [(1, "Zach")]
        assert cursor.exit_calls == 1
        exc_type, exc_val, _ = cursor.exit_args
        assert exc_type is ValueError
        assert exc_val is mapper_error
        assert cursor.exit_tb_was_active
        # the second mapper ran inside the cursor lifecycle: its failure reached the native exit
        assert cursor.events == [
            "enter",
            ("execute", 0),
            ("fetchall", 0),
            ("execute", 1),
            ("fetchall", 1),
            ("exit", ValueError),
        ]

    @pytest.mark.asyncio
    @pytest.mark.parametrize("exit_behavior", ["raises", "truthy"])
    async def test_query_multiple_async_later_no_result_error_wins_over_native_cursor_exit(self, exit_behavior):
        cursor = _AsyncMultiQueryExitCursor(
            fetch_results=(((1, "Zach"),), tuple()),
            exit_error=RuntimeError("cleanup failed") if exit_behavior == "raises" else None,
            exit_return=True if exit_behavior == "truthy" else None,
        )
        mapped = []

        def mapper(row):
            mapped.append(tuple(row.values))
            return tuple(row.values)

        with pytest.raises(NoResultException) as exc_info:
            await MockAsyncCommands(_PlainAsyncQueryConnection(cursor)).query_multiple_async(
                ("select id, name from some_table", "select id, name from another_table"),
                mapper=mapper,
            )

        assert mapped == [(1, "Zach")]
        assert cursor.exit_calls == 1
        exc_type, exc_val, _ = cursor.exit_args
        assert exc_type is NoResultException
        assert exc_val is exc_info.value
        assert cursor.exit_tb_was_active

    @pytest.mark.asyncio
    @pytest.mark.parametrize("exit_behavior", ["raises", "truthy"])
    async def test_query_multiple_async_later_duplicate_column_error_wins_over_native_cursor_exit(self, exit_behavior):
        cursor = _AsyncMultiQueryExitCursor(
            fetch_results=(((1, "Zach"),), ((1, "Zach", 2),)),
            descriptions=(
                (("id", "int"), ("name", "text")),
                (("id", "int"), ("name", "text"), ("id", "int")),
            ),
            exit_error=RuntimeError("cleanup failed") if exit_behavior == "raises" else None,
            exit_return=True if exit_behavior == "truthy" else None,
        )
        projected = []

        def first_model(**row):
            projected.append(row)
            return row

        with pytest.raises(DuplicateColumnException) as exc_info:
            await MockAsyncCommands(_PlainAsyncQueryConnection(cursor)).query_multiple_async(
                ("select id, name from some_table", "select id, name, id from another_table"),
                models=(first_model, dict),
            )

        _assert_duplicate_column_exception(exc_info)
        assert projected == [{"id": 1, "name": "Zach"}]
        assert cursor.exit_calls == 1
        exc_type, exc_val, _ = cursor.exit_args
        assert exc_type is DuplicateColumnException
        assert exc_val is exc_info.value
        assert cursor.exit_tb_was_active
        assert cursor.events == [
            "enter",
            ("execute", 0),
            ("fetchall", 0),
            ("execute", 1),
            ("fetchall", 1),
            ("exit", DuplicateColumnException),
        ]

    @pytest.mark.asyncio
    async def test_query_multiple_async_mapper_still_receives_later_duplicate_columns(self):
        cursor = _AsyncMultiQueryExitCursor(
            fetch_results=(((1, "Zach"),), ((1, "Zach", 2),)),
            descriptions=(
                (("id", "int"), ("name", "text")),
                (("id", "int"), ("name", "text"), ("id", "int")),
            ),
        )

        data1, data2 = await MockAsyncCommands(_PlainAsyncQueryConnection(cursor)).query_multiple_async(
            ("select id, name from some_table", "select id, name, id from another_table"),
            mapper=lambda row: (row.columns, row.values),
        )

        assert data1 == [(("id", "name"), (1, "Zach"))]
        assert data2 == [(("id", "name", "id"), (1, "Zach", 2))]
        assert cursor.exit_args == (None, None, None)

    @pytest.mark.asyncio
    async def test_query_multiple_async_propagates_native_cursor_exit_error_after_successful_batch(self):
        cleanup_error = RuntimeError("cleanup failed")
        cursor = _AsyncMultiQueryExitCursor(exit_error=cleanup_error)
        mapped = []

        def mapper(row):
            mapped.append(tuple(row.values))
            return tuple(row.values)

        with pytest.raises(RuntimeError) as exc_info:
            await MockAsyncCommands(_PlainAsyncQueryConnection(cursor)).query_multiple_async(
                ("select id, name from some_table", "select id, name from another_table"),
                mapper=mapper,
            )

        assert exc_info.value is cleanup_error
        assert mapped == [(1, "Zach"), (2, "Bob")]
        assert cursor.exit_calls == 1
        assert cursor.exit_args == (None, None, None)

    @pytest.mark.asyncio
    async def test_query_multiple_async_runs_all_queries_on_one_cursor_lifecycle(self):
        cursor = _AsyncMultiQueryExitCursor()

        data1, data2 = await MockAsyncCommands(_PlainAsyncQueryConnection(cursor)).query_multiple_async(
            ("select id, name from some_table", "select id, name from another_table")
        )

        assert data1 == [{"id": 1, "name": "Zach"}]
        assert data2 == [{"id": 2, "name": "Bob"}]
        assert cursor.exit_calls == 1
        assert cursor.exit_args == (None, None, None)
        assert cursor.events == [
            "enter",
            ("execute", 0),
            ("fetchall", 0),
            ("execute", 1),
            ("fetchall", 1),
            ("exit", None),
        ]

    @pytest.mark.asyncio
    async def test_query_first(self, connection):
        async with MockAsyncCommands(connection) as commands:
            record = await commands.query_first_async("select id, name from some_table", model=SimpleNamespace)
        assert isinstance(record, SimpleNamespace)
        assert record.id
        assert record.name

    @pytest.mark.asyncio
    async def test_query_first_mapper(self, connection):
        async with MockAsyncCommands(connection) as commands:
            record = await commands.query_first_async("select id, name from some_table", mapper=lambda row: row["id"])

        assert record == 1

    @pytest.mark.asyncio
    async def test_query_first_mapper_can_handle_duplicate_columns(self):
        async with MockAsyncCommands(_AsyncCursorConnection(_AsyncDuplicateColumnCursor())) as commands:
            record = await commands.query_first_async(
                "select id, name, id from some_table",
                mapper=lambda row: row.values,
            )

        assert record == (1, "Zach", 2)

    @pytest.mark.asyncio
    async def test_query_first_rejects_model_and_mapper(self, connection):
        async with MockAsyncCommands(connection) as commands:
            with pytest.raises(ValueError, match="Pass either 'model' or 'mapper'"):
                await commands.query_first_async("select id, name from some_table", model=dict, mapper=lambda row: row)

    @pytest.mark.asyncio
    async def test_query_first_rejects_duplicate_columns(self):
        async with MockAsyncCommands(_AsyncCursorConnection(_AsyncDuplicateColumnCursor())) as commands:
            with pytest.raises(DuplicateColumnException) as exc_info:
                await commands.query_first_async("select id, name, id from some_table")

        _assert_duplicate_column_exception(exc_info)

    @pytest.mark.asyncio
    async def test_query_first_treats_falsy_row_as_result(self, connection, mocker):
        async def fetchone(s):
            return FalsyRow((None, "nullable"))

        mocker.patch("tests.mocks.MockAsyncCursor.fetchone", fetchone)

        async with MockAsyncCommands(connection) as commands:
            record = await commands.query_first_async("select id, name from some_table")

        assert record == {"id": None, "name": "nullable"}

    @pytest.mark.asyncio
    async def test_query_first_raises_on_no_result(self, connection, set_fetchone_to_return_none):
        async with MockAsyncCommands(connection) as commands:
            with pytest.raises(NoResultException):
                await commands.query_first_async("select * from some_table")

    @pytest.mark.asyncio
    @pytest.mark.parametrize("exit_behavior", ["raises", "truthy"])
    async def test_query_first_async_mapper_error_wins_over_native_cursor_exit(self, exit_behavior):
        mapper_error = ValueError("mapper failed")

        class RecordingExitAsyncCursor:
            rowcount = 0
            description = ("id", "int"), ("name", "text")

            def __init__(self):
                self.exit_calls = 0
                self.exit_args = None

            async def __aenter__(self):
                return self

            async def __aexit__(self, exc_type, exc_val, exc_tb):
                self.exit_calls += 1
                self.exit_args = exc_type, exc_val, exc_tb
                self.exit_tb_was_active = exc_tb is exc_val.__traceback__
                if exit_behavior == "raises":
                    raise RuntimeError("cleanup failed")
                return True

            async def execute(self, sql, parameters=None):
                pass

            async def fetchone(self):
                return 1, "Zach"

        def mapper(row):
            raise mapper_error

        cursor = RecordingExitAsyncCursor()

        with pytest.raises(ValueError) as exc_info:
            await MockAsyncCommands(_PlainAsyncQueryConnection(cursor)).query_first_async(
                "select id, name from some_table", mapper=mapper
            )

        assert exc_info.value is mapper_error
        assert cursor.exit_calls == 1
        exc_type, exc_val, exc_tb = cursor.exit_args
        assert exc_type is ValueError
        assert exc_val is mapper_error
        assert cursor.exit_tb_was_active

    @pytest.mark.asyncio
    async def test_query_first_async_propagates_native_cursor_exit_error_after_successful_mapping(self):
        cleanup_error = RuntimeError("cleanup failed")

        class FailingExitAsyncCursor:
            rowcount = 0
            description = ("id", "int"), ("name", "text")

            def __init__(self):
                self.exit_calls = 0
                self.exit_args = None

            async def __aenter__(self):
                return self

            async def __aexit__(self, exc_type, exc_val, exc_tb):
                self.exit_calls += 1
                self.exit_args = exc_type, exc_val, exc_tb
                raise cleanup_error

            async def execute(self, sql, parameters=None):
                pass

            async def fetchone(self):
                return 1, "Zach"

        cursor = FailingExitAsyncCursor()

        with pytest.raises(RuntimeError) as exc_info:
            await MockAsyncCommands(_PlainAsyncQueryConnection(cursor)).query_first_async(
                "select id, name from some_table", mapper=lambda row: row["id"]
            )

        assert exc_info.value is cleanup_error
        assert cursor.exit_calls == 1
        assert cursor.exit_args == (None, None, None)

    @pytest.mark.asyncio
    async def test_query_first_or_default(self, connection, set_fetchone_to_return_none):
        default = SimpleNamespace(id=10, name="default")
        async with MockAsyncCommands(connection) as commands:
            data = await commands.query_first_or_default_async("select * from some_table", default=default)
        assert data is default

    @pytest.mark.asyncio
    async def test_query_first_or_default_calls_uninspectable_callable_default_on_no_result(
        self, connection, set_fetchone_to_return_none, mocker
    ):
        sentinel = object()
        calls = []

        def default():
            calls.append(None)
            return sentinel

        mocker.patch("pydapper.commands.signature", side_effect=ValueError("no signature"))

        async with MockAsyncCommands(connection) as commands:
            data = await commands.query_first_or_default_async("select * from some_table", default=default)

        assert data is sentinel
        assert calls == [None]

    @pytest.mark.asyncio
    async def test_query_first_or_default_calls_builtin_default_factory_on_no_result(
        self, connection, set_fetchone_to_return_none
    ):
        async with MockAsyncCommands(connection) as commands:
            data = await commands.query_first_or_default_async("select * from some_table", default=dict)

        assert data == {}

    @pytest.mark.asyncio
    async def test_query_first_or_default_returns_callable_default_that_requires_args(
        self, connection, set_fetchone_to_return_none
    ):
        def default(row):
            return row

        async with MockAsyncCommands(connection) as commands:
            data = await commands.query_first_or_default_async("select * from some_table", default=default)

        assert data is default

    @pytest.mark.asyncio
    async def test_query_first_or_default_returns_first_row(self, connection):
        calls = []

        def default():
            calls.append(None)
            return object()

        async with MockAsyncCommands(connection) as commands:
            data = await commands.query_first_or_default_async("select * from some_table", default=default)

        assert data["id"] == 1
        assert calls == []

    @pytest.mark.asyncio
    async def test_query_first_or_default_model_returns_first_row(self, connection):
        async with MockAsyncCommands(connection) as commands:
            data = await commands.query_first_or_default_async(
                "select * from some_table",
                default=None,
                model=SimpleNamespace,
            )

        assert isinstance(data, SimpleNamespace)
        assert data.id == 1

    @pytest.mark.asyncio
    async def test_query_first_or_default_mapper_returns_first_row(self, connection):
        async with MockAsyncCommands(connection) as commands:
            data = await commands.query_first_or_default_async(
                "select * from some_table",
                default=None,
                mapper=lambda row: row[0],
            )

        assert data == 1

    @pytest.mark.asyncio
    async def test_query_first_or_default_rejects_model_and_mapper_before_default(
        self, connection, set_fetchone_to_return_none
    ):
        async with MockAsyncCommands(connection) as commands:
            with pytest.raises(ValueError, match="Pass either 'model' or 'mapper'"):
                await commands.query_first_or_default_async(
                    "select * from some_table",
                    default=None,
                    model=dict,
                    mapper=lambda row: row,
                )

    @pytest.mark.asyncio
    async def test_query_single(self, connection, set_fetchall_return_one):
        async with MockAsyncCommands(connection) as commands:
            record = await commands.query_single_async("select * from some_table")
        assert isinstance(record, dict)
        assert record["id"]
        assert record["name"]

    @pytest.mark.asyncio
    async def test_query_single_mapper(self, connection, set_fetchall_return_one):
        async with MockAsyncCommands(connection) as commands:
            record = await commands.query_single_async("select * from some_table", mapper=lambda row: row["id"])

        assert record == 1

    @pytest.mark.asyncio
    async def test_query_single_mapper_can_handle_duplicate_columns(self):
        async with MockAsyncCommands(_AsyncCursorConnection(_AsyncDuplicateColumnCursor())) as commands:
            record = await commands.query_single_async(
                "select id, name, id from some_table",
                mapper=lambda row: row.values,
            )

        assert record == (1, "Zach", 2)

    @pytest.mark.asyncio
    async def test_query_single_rejects_model_and_mapper(self, connection, set_fetchall_return_one):
        async with MockAsyncCommands(connection) as commands:
            with pytest.raises(ValueError, match="Pass either 'model' or 'mapper'"):
                await commands.query_single_async("select * from some_table", model=dict, mapper=lambda row: row)

    @pytest.mark.asyncio
    async def test_query_single_rejects_duplicate_columns(self):
        async with MockAsyncCommands(_AsyncCursorConnection(_AsyncDuplicateColumnCursor())) as commands:
            with pytest.raises(DuplicateColumnException) as exc_info:
                await commands.query_single_async("select id, name, id from some_table")

        _assert_duplicate_column_exception(exc_info)

    @pytest.mark.asyncio
    async def test_query_single_raises_on_no_result(self, connection, set_fetchone_to_return_none):
        async with MockAsyncCommands(connection) as commands:
            with pytest.raises(NoResultException):
                await commands.query_single_async("select * from some_table")

    @pytest.mark.asyncio
    async def test_query_single_raises_on_many_results(self, connection):
        async with MockAsyncCommands(connection) as commands:
            with pytest.raises(MoreThanOneResultException):
                await commands.query_single_async("select * from some_table")

    @pytest.mark.asyncio
    async def test_query_single_no_result_precedes_duplicate_column_mapping(self):
        connection = _AsyncCursorConnection(_AsyncDuplicateColumnCursor(rows=()))

        with pytest.raises(NoResultException):
            await MockAsyncCommands(connection).query_single_async("select id, name, id from some_table")

    @pytest.mark.asyncio
    async def test_query_single_many_results_precede_duplicate_column_mapping(self):
        connection = _AsyncCursorConnection(_AsyncDuplicateColumnCursor(rows=((1, "Zach", 2), (3, "Bob", 4))))

        with pytest.raises(MoreThanOneResultException):
            await MockAsyncCommands(connection).query_single_async("select id, name, id from some_table")

    @pytest.mark.asyncio
    async def test_query_single_async_uses_fetchmany_when_available(self):
        connection = _AsyncQuerySingleConnection(_AsyncQuerySingleFetchManyCursor([(1, "Zach")]))

        record = await MockAsyncCommands(connection).query_single_async("select * from some_table")

        assert record == {"id": 1, "name": "Zach"}
        assert connection.cursor_instance.fetchmany_calls == [2]
        assert connection.cursor_instance.fetchone_calls == 0
        assert connection.cursor_instance.fetchall_calls == 0

    @pytest.mark.asyncio
    async def test_query_single_async_fetchmany_raises_on_no_result(self):
        connection = _AsyncQuerySingleConnection(_AsyncQuerySingleFetchManyCursor([]))

        with pytest.raises(NoResultException):
            await MockAsyncCommands(connection).query_single_async("select * from some_table")

        assert connection.cursor_instance.fetchmany_calls == [2]
        assert connection.cursor_instance.fetchone_calls == 0
        assert connection.cursor_instance.fetchall_calls == 0

    @pytest.mark.asyncio
    async def test_query_single_async_fetchmany_consumes_at_most_two_rows_before_raising(self):
        connection = _AsyncQuerySingleConnection(
            _AsyncQuerySingleFetchManyCursor([(1, "Zach"), (2, "Bob"), (3, "Alice")])
        )

        with pytest.raises(MoreThanOneResultException):
            await MockAsyncCommands(connection).query_single_async("select * from some_table")

        assert connection.cursor_instance.fetchmany_calls == [2]
        assert connection.cursor_instance.fetchall_calls == 0

    @pytest.mark.asyncio
    async def test_query_single_async_fetchone_fallback_consumes_at_most_two_rows_before_raising(self):
        connection = _AsyncQuerySingleConnection(
            _AsyncQuerySingleFetchOneCursor([(1, "Zach"), (2, "Bob"), (3, "Alice")])
        )

        with pytest.raises(MoreThanOneResultException):
            await MockAsyncCommands(connection).query_single_async("select * from some_table")

        assert connection.cursor_instance.fetchone_calls == 2
        assert connection.cursor_instance.fetchall_calls == 0

    @pytest.mark.asyncio
    @pytest.mark.parametrize("exit_behavior", ["raises", "truthy"])
    async def test_query_single_async_mapper_error_wins_over_native_cursor_exit(self, exit_behavior):
        mapper_error = ValueError("mapper failed")

        class RecordingExitAsyncCursor:
            rowcount = 0
            description = ("id", "int"), ("name", "text")

            def __init__(self):
                self.exit_calls = 0
                self.exit_args = None

            async def __aenter__(self):
                return self

            async def __aexit__(self, exc_type, exc_val, exc_tb):
                self.exit_calls += 1
                self.exit_args = exc_type, exc_val, exc_tb
                self.exit_tb_was_active = exc_tb is exc_val.__traceback__
                if exit_behavior == "raises":
                    raise RuntimeError("cleanup failed")
                return True

            async def execute(self, sql, parameters=None):
                pass

            async def fetchmany(self, size=None):
                return ((1, "Zach"),)

        def mapper(row):
            raise mapper_error

        cursor = RecordingExitAsyncCursor()

        with pytest.raises(ValueError) as exc_info:
            await MockAsyncCommands(_PlainAsyncQueryConnection(cursor)).query_single_async(
                "select id, name from some_table", mapper=mapper
            )

        assert exc_info.value is mapper_error
        assert cursor.exit_calls == 1
        exc_type, exc_val, exc_tb = cursor.exit_args
        assert exc_type is ValueError
        assert exc_val is mapper_error
        assert cursor.exit_tb_was_active

    @pytest.mark.asyncio
    async def test_query_single_async_propagates_native_cursor_exit_error_after_successful_mapping(self):
        cleanup_error = RuntimeError("cleanup failed")

        class FailingExitAsyncCursor:
            rowcount = 0
            description = ("id", "int"), ("name", "text")

            def __init__(self):
                self.exit_calls = 0
                self.exit_args = None

            async def __aenter__(self):
                return self

            async def __aexit__(self, exc_type, exc_val, exc_tb):
                self.exit_calls += 1
                self.exit_args = exc_type, exc_val, exc_tb
                raise cleanup_error

            async def execute(self, sql, parameters=None):
                pass

            async def fetchmany(self, size=None):
                return ((1, "Zach"),)

        cursor = FailingExitAsyncCursor()

        with pytest.raises(RuntimeError) as exc_info:
            await MockAsyncCommands(_PlainAsyncQueryConnection(cursor)).query_single_async(
                "select id, name from some_table", mapper=lambda row: row["id"]
            )

        assert exc_info.value is cleanup_error
        assert cursor.exit_calls == 1
        assert cursor.exit_args == (None, None, None)

    @pytest.mark.asyncio
    @pytest.mark.parametrize(
        "rows, expected_exception",
        [
            ([], NoResultException),
            ([(1, "Zach"), (2, "Bob"), (3, "Alice")], MoreThanOneResultException),
        ],
    )
    async def test_query_single_async_cardinality_error_wins_over_native_cursor_exit_error(
        self, rows, expected_exception
    ):
        class FailingExitAsyncCursor:
            rowcount = 0
            description = ("id", "int"), ("name", "text")

            def __init__(self):
                self.exit_calls = 0
                self.exit_args = None
                self.fetchmany_calls = []

            async def __aenter__(self):
                return self

            async def __aexit__(self, exc_type, exc_val, exc_tb):
                self.exit_calls += 1
                self.exit_args = exc_type, exc_val, exc_tb
                raise RuntimeError("cleanup failed")

            async def execute(self, sql, parameters=None):
                pass

            async def fetchmany(self, size=None):
                self.fetchmany_calls.append(size)
                return tuple(rows[:size])

        cursor = FailingExitAsyncCursor()

        with pytest.raises(expected_exception) as exc_info:
            await MockAsyncCommands(_PlainAsyncQueryConnection(cursor)).query_single_async(
                "select id, name from some_table"
            )

        assert cursor.fetchmany_calls == [2]
        assert cursor.exit_calls == 1
        exc_type, exc_val, exc_tb = cursor.exit_args
        assert exc_type is expected_exception
        assert exc_val is exc_info.value

    @pytest.mark.asyncio
    async def test_query_single_async_duplicate_column_error_wins_over_native_cursor_exit_error(self):
        class FailingExitAsyncCursor:
            rowcount = 0
            description = ("id", "int"), ("name", "text"), ("id", "int")

            def __init__(self):
                self.exit_calls = 0
                self.exit_args = None

            async def __aenter__(self):
                return self

            async def __aexit__(self, exc_type, exc_val, exc_tb):
                self.exit_calls += 1
                self.exit_args = exc_type, exc_val, exc_tb
                self.exit_tb_was_active = exc_tb is exc_val.__traceback__
                raise RuntimeError("cleanup failed")

            async def execute(self, sql, parameters=None):
                pass

            async def fetchmany(self, size=None):
                return ((1, "Zach", 2),)

        cursor = FailingExitAsyncCursor()

        with pytest.raises(DuplicateColumnException) as exc_info:
            await MockAsyncCommands(_PlainAsyncQueryConnection(cursor)).query_single_async(
                "select id, name, id from some_table"
            )

        assert cursor.exit_calls == 1
        exc_type, exc_val, exc_tb = cursor.exit_args
        assert exc_type is DuplicateColumnException
        assert exc_val is exc_info.value
        assert cursor.exit_tb_was_active

    @pytest.mark.asyncio
    async def test_query_single_async_enters_and_exits_cursor_exactly_once_on_success(self):
        class RecordingAsyncCursor:
            rowcount = 0
            description = ("id", "int"), ("name", "text")

            def __init__(self):
                self.enter_calls = 0
                self.exit_calls = 0
                self.fetchmany_calls = []

            async def __aenter__(self):
                self.enter_calls += 1
                return self

            async def __aexit__(self, exc_type, exc_val, exc_tb):
                self.exit_calls += 1

            async def execute(self, sql, parameters=None):
                pass

            async def fetchmany(self, size=None):
                self.fetchmany_calls.append(size)
                return ((1, "Zach"),)

        cursor = RecordingAsyncCursor()

        record = await MockAsyncCommands(_PlainAsyncQueryConnection(cursor)).query_single_async(
            "select id, name from some_table"
        )

        assert record == {"id": 1, "name": "Zach"}
        assert cursor.enter_calls == 1
        assert cursor.exit_calls == 1
        assert cursor.fetchmany_calls == [2]

    @pytest.mark.asyncio
    async def test_query_single_async_calls_more_than_one_hook_before_raising(self):
        # async twin of TestCommands.test_query_single_calls_more_than_one_hook_before_raising: an
        # async adapter that must drain unread rows gets the same drain seam, at the same point
        calls = []

        class HookedAsyncCommands(MockAsyncCommands):
            async def _on_query_single_more_than_one_result_async(self, cursor):
                calls.append(cursor)

        connection = _AsyncQuerySingleConnection(_AsyncQuerySingleFetchOneCursor([(1, "Zach"), (2, "Bob")]))

        with pytest.raises(MoreThanOneResultException):
            await HookedAsyncCommands(connection).query_single_async("select * from some_table")

        assert calls == [connection.cursor_instance]

    @pytest.mark.asyncio
    async def test_query_single_async_more_than_one_hook_runs_before_the_cursor_exits(self):
        calls = []

        class RecordingExitAsyncCursor(_AsyncQuerySingleFetchOneCursor):
            async def __aexit__(self, exc_type, exc_val, exc_tb):
                calls.append("exit")

        class HookedAsyncCommands(MockAsyncCommands):
            async def _on_query_single_more_than_one_result_async(self, cursor):
                calls.append("drain")

        connection = _AsyncQuerySingleConnection(RecordingExitAsyncCursor([(1, "Zach"), (2, "Bob")]))

        with pytest.raises(MoreThanOneResultException):
            await HookedAsyncCommands(connection).query_single_async("select * from some_table")

        assert calls == ["drain", "exit"]

    @pytest.mark.asyncio
    async def test_query_single_async_more_than_one_hook_is_not_called_for_other_outcomes(self):
        calls = []

        class HookedAsyncCommands(MockAsyncCommands):
            async def _on_query_single_more_than_one_result_async(self, cursor):
                calls.append(cursor)

        connection = _AsyncQuerySingleConnection(_AsyncQuerySingleFetchOneCursor([]))

        with pytest.raises(NoResultException):
            await HookedAsyncCommands(connection).query_single_async("select * from some_table")

        record = await HookedAsyncCommands(
            _AsyncQuerySingleConnection(_AsyncQuerySingleFetchOneCursor([(1, "Zach")]))
        ).query_single_async("select * from some_table")

        assert record == {"id": 1, "name": "Zach"}
        assert calls == []

    @pytest.mark.asyncio
    async def test_async_cursor_entry_failure_closes_the_command_owned_cursor(self):
        class FailingEnterAsyncCursor:
            def __init__(self):
                self.close_calls = 0
                self.exit_calls = 0

            async def __aenter__(self):
                raise RuntimeError("entry failed")

            async def __aexit__(self, exc_type, exc_val, exc_tb):
                self.exit_calls += 1

            async def close(self):
                self.close_calls += 1

        cursor = FailingEnterAsyncCursor()

        with pytest.raises(RuntimeError, match="entry failed"):
            await MockAsyncCommands(_PlainAsyncQueryConnection(cursor)).query_async("select id, name from some_table")

        assert cursor.close_calls == 1
        assert cursor.exit_calls == 0

    @pytest.mark.asyncio
    async def test_async_cursor_entry_error_survives_a_failing_close(self, caplog):
        entry_error = RuntimeError("entry failed")

        class FailingEnterAndCloseAsyncCursor:
            async def __aenter__(self):
                raise entry_error

            async def __aexit__(self, exc_type, exc_val, exc_tb):
                raise AssertionError("__aexit__ must not run for a cursor that never entered")

            async def close(self):
                raise ValueError("close failed")

        with caplog.at_level(logging.DEBUG, logger="pydapper._context"):
            with pytest.raises(RuntimeError) as exc_info:
                await MockAsyncCommands(_PlainAsyncQueryConnection(FailingEnterAndCloseAsyncCursor())).execute_async(
                    "insert into some_table values (1)"
                )

        assert exc_info.value is entry_error
        assert [record.getMessage() for record in _debug_records(caplog)] == [
            "Discarding ValueError raised while cleaning up a pydapper-owned resource"
        ]

    @pytest.mark.asyncio
    @pytest.mark.parametrize("base_error", _NON_EXCEPTION_CLEANUP_FAILURES)
    async def test_async_cursor_exit_non_exception_during_cleanup_beats_the_command_error(self, base_error):
        command_error = ValueError("mapper failed")

        class InterruptingExitAsyncCursor:
            rowcount = 0
            description = ("id", "int"), ("name", "text")

            async def __aenter__(self):
                return self

            async def __aexit__(self, exc_type, exc_val, exc_tb):
                raise base_error()

            async def execute(self, sql, parameters=None):
                pass

            async def fetchall(self):
                return ((1, "Zach"),)

        def mapper(row):
            raise command_error

        with pytest.raises(base_error) as exc_info:
            await MockAsyncCommands(_PlainAsyncQueryConnection(InterruptingExitAsyncCursor())).query_async(
                "select id, name from some_table", mapper=mapper
            )

        assert exc_info.value.__context__ is command_error

    @pytest.mark.asyncio
    async def test_query_single_or_default(self, connection, set_fetchone_to_return_none):
        default = SimpleNamespace(id=10, name="default")
        async with MockAsyncCommands(connection) as commands:
            record = await commands.query_single_or_default_async("select * from some_table", default=default)
        assert record is default

    @pytest.mark.asyncio
    async def test_query_single_or_default_calls_callable_default_on_no_result(
        self, connection, set_fetchone_to_return_none
    ):
        sentinel = object()
        calls = []

        def default():
            calls.append(None)
            return sentinel

        async with MockAsyncCommands(connection) as commands:
            record = await commands.query_single_or_default_async("select * from some_table", default=default)

        assert record is sentinel
        assert calls == [None]

    @pytest.mark.asyncio
    async def test_query_single_or_default_calls_builtin_default_factory_on_no_result(
        self, connection, set_fetchone_to_return_none
    ):
        async with MockAsyncCommands(connection) as commands:
            record = await commands.query_single_or_default_async("select * from some_table", default=set)

        assert record == set()

    @pytest.mark.asyncio
    async def test_query_single_or_default_returns_callable_default_that_requires_args(
        self, connection, set_fetchone_to_return_none
    ):
        def default(row):
            return row

        async with MockAsyncCommands(connection) as commands:
            record = await commands.query_single_or_default_async("select * from some_table", default=default)

        assert record is default

    @pytest.mark.asyncio
    async def test_query_single_or_default_returns_single_row(self, connection, set_fetchall_return_one):
        calls = []

        def default():
            calls.append(None)
            return object()

        async with MockAsyncCommands(connection) as commands:
            record = await commands.query_single_or_default_async("select * from some_table", default=default)

        assert record["id"] == 1
        assert calls == []

    @pytest.mark.asyncio
    async def test_query_single_or_default_model_returns_single_row(self, connection, set_fetchall_return_one):
        async with MockAsyncCommands(connection) as commands:
            record = await commands.query_single_or_default_async(
                "select * from some_table",
                default=None,
                model=SimpleNamespace,
            )

        assert isinstance(record, SimpleNamespace)
        assert record.id == 1

    @pytest.mark.asyncio
    async def test_query_single_or_default_mapper_returns_single_row(self, connection, set_fetchall_return_one):
        async with MockAsyncCommands(connection) as commands:
            record = await commands.query_single_or_default_async(
                "select * from some_table",
                default=None,
                mapper=lambda row: row[0],
            )

        assert record == 1

    @pytest.mark.asyncio
    async def test_query_single_or_default_rejects_model_and_mapper_before_default(
        self, connection, set_fetchone_to_return_none
    ):
        async with MockAsyncCommands(connection) as commands:
            with pytest.raises(ValueError, match="Pass either 'model' or 'mapper'"):
                await commands.query_single_or_default_async(
                    "select * from some_table",
                    default=None,
                    model=dict,
                    mapper=lambda row: row,
                )

    @pytest.mark.asyncio
    async def test_query_single_or_default_raises_on_many_results(self, connection):
        async with MockAsyncCommands(connection) as commands:
            with pytest.raises(MoreThanOneResultException):
                await commands.query_single_or_default_async("select * from some_table", default=None)

    @pytest.mark.asyncio
    async def test_execute_scalar(self, connection):
        async with MockAsyncCommands(connection) as commands:
            id_ = await commands.execute_scalar_async("select id, name from some_table")
        assert id_ == 1

    @pytest.mark.asyncio
    async def test_execute_scalar_ignores_duplicate_columns(self):
        async with MockAsyncCommands(_AsyncCursorConnection(_AsyncDuplicateColumnCursor())) as commands:
            assert await commands.execute_scalar_async("select id, name, id from some_table") == 1

    @pytest.mark.asyncio
    async def test_execute_scalar_raises_on_no_result(self, connection, set_fetchone_to_return_none):
        async with MockAsyncCommands(connection) as commands:
            with pytest.raises(NoResultException):
                await commands.execute_scalar_async("select * from some_table")

    @pytest.mark.asyncio
    async def test_execute_scalar_returns_none_for_null_first_column(
        self, connection, set_fetchone_to_return_null_first_column
    ):
        async with MockAsyncCommands(connection) as commands:
            assert await commands.execute_scalar_async("select nullable_column from some_table") is None

    @pytest.mark.asyncio
    @pytest.mark.parametrize("value", [0, False, ""], ids=["zero", "false", "empty-string"])
    async def test_execute_scalar_preserves_falsey_first_column_values(self, value):
        cursor = _PlainAsyncQueryCursor(rows=[(value,)])
        commands = MockAsyncCommands(_PlainAsyncQueryConnection(cursor))
        assert await commands.execute_scalar_async("select flag from some_table") == value

    @pytest.mark.asyncio
    @pytest.mark.parametrize("exit_behavior", ["raises", "truthy"])
    async def test_execute_scalar_async_no_result_error_wins_over_native_cursor_exit(self, exit_behavior):
        class RecordingExitAsyncCursor:
            rowcount = 0

            def __init__(self):
                self.exit_calls = 0
                self.exit_args = None

            async def __aenter__(self):
                return self

            async def __aexit__(self, exc_type, exc_val, exc_tb):
                self.exit_calls += 1
                self.exit_args = exc_type, exc_val, exc_tb
                self.exit_tb_was_active = exc_tb is exc_val.__traceback__
                if exit_behavior == "raises":
                    raise RuntimeError("cleanup failed")
                return True

            async def execute(self, sql, parameters=None):
                pass

            async def fetchone(self):
                return None

        cursor = RecordingExitAsyncCursor()

        with pytest.raises(NoResultException) as exc_info:
            await MockAsyncCommands(_PlainAsyncQueryConnection(cursor)).execute_scalar_async(
                "select id from some_table"
            )

        assert cursor.exit_calls == 1
        exc_type, exc_val, exc_tb = cursor.exit_args
        assert exc_type is NoResultException
        assert exc_val is exc_info.value
        assert cursor.exit_tb_was_active

    @pytest.mark.asyncio
    async def test_execute_scalar_async_propagates_native_cursor_exit_error_after_successful_fetch(self):
        cleanup_error = RuntimeError("cleanup failed")

        class FailingExitAsyncCursor:
            rowcount = 0

            def __init__(self):
                self.exit_calls = 0
                self.exit_args = None

            async def __aenter__(self):
                return self

            async def __aexit__(self, exc_type, exc_val, exc_tb):
                self.exit_calls += 1
                self.exit_args = exc_type, exc_val, exc_tb
                raise cleanup_error

            async def execute(self, sql, parameters=None):
                pass

            async def fetchone(self):
                return (42,)

        cursor = FailingExitAsyncCursor()

        with pytest.raises(RuntimeError) as exc_info:
            await MockAsyncCommands(_PlainAsyncQueryConnection(cursor)).execute_scalar_async(
                "select id from some_table"
            )

        assert exc_info.value is cleanup_error
        assert cursor.exit_calls == 1
        assert cursor.exit_args == (None, None, None)

    @pytest.mark.asyncio
    async def test_execute_scalar_async_extraction_error_wins_over_native_cursor_exit_error(self):
        class MalformedRowAsyncCursor:
            rowcount = 0

            def __init__(self):
                self.exit_calls = 0
                self.exit_args = None

            async def __aenter__(self):
                return self

            async def __aexit__(self, exc_type, exc_val, exc_tb):
                self.exit_calls += 1
                self.exit_args = exc_type, exc_val, exc_tb
                raise RuntimeError("cleanup failed")

            async def execute(self, sql, parameters=None):
                pass

            async def fetchone(self):
                return ()

        cursor = MalformedRowAsyncCursor()

        with pytest.raises(IndexError) as exc_info:
            await MockAsyncCommands(_PlainAsyncQueryConnection(cursor)).execute_scalar_async(
                "select id from some_table"
            )

        assert cursor.exit_calls == 1
        exc_type, exc_val, exc_tb = cursor.exit_args
        assert exc_type is IndexError
        assert exc_val is exc_info.value


class TestAdapterCapabilities:
    EXPECTED_VALUES = {
        "TRANSACTIONS": "transactions",
        "LIST_EXPANSION": "list_expansion",
        "RESULT_GRIDS": "result_grids",
        "RAW_READER": "raw_reader",
        "COMMAND_TIMEOUT": "command_timeout",
        "STORED_PROCEDURES": "stored_procedures",
        "OUTPUT_PARAMETERS": "output_parameters",
        "SCHEMA_INSPECTION": "schema_inspection",
        "SQL_VALIDATION": "sql_validation",
        "EXPLAIN": "explain",
        "READONLY": "readonly",
        "MAX_ROWS": "max_rows",
    }

    def test_enum_members_and_values(self):
        assert {member.name: member.value for member in AdapterCapability} == self.EXPECTED_VALUES

    def test_importable_from_package_root(self):
        assert pydapper.AdapterCapability is AdapterCapability

    def test_default_declaration_is_immutable_frozenset(self):
        assert MockCommands.capabilities == frozenset()
        assert MockAsyncCommands.capabilities == frozenset()
        assert isinstance(MockCommands.capabilities, frozenset)
        assert not hasattr(MockCommands.capabilities, "add")

    @pytest.fixture
    def sync_commands(self):
        class CapableCommands(MockCommands):
            capabilities = frozenset({AdapterCapability.TRANSACTIONS})

        return CapableCommands(MockConnection())

    @pytest.fixture
    def async_commands(self):
        class CapableAsyncCommands(MockAsyncCommands):
            capabilities = frozenset({AdapterCapability.RAW_READER})

        return CapableAsyncCommands(MockAsyncConnection())

    @pytest.fixture(params=["sync", "async"])
    def commands_with_declared(self, request, sync_commands, async_commands):
        """(commands, its declared capability, the other mode's capability) — the sets differ per mode so
        the tests prove declarations are per class rather than leaked across classes."""
        if request.param == "sync":
            return sync_commands, AdapterCapability.TRANSACTIONS, AdapterCapability.RAW_READER
        return async_commands, AdapterCapability.RAW_READER, AdapterCapability.TRANSACTIONS

    @pytest.fixture
    def commands(self, commands_with_declared):
        return commands_with_declared[0]

    def test_supports_declared_capability(self, commands_with_declared):
        commands, declared, other_modes = commands_with_declared
        assert commands.supports(declared) is True
        assert commands.supports(other_modes) is False
        assert commands.supports(AdapterCapability.EXPLAIN) is False

    @pytest.mark.parametrize("bad", ["transactions", 1, None, object(), CommandKind.TEXT])
    def test_supports_rejects_non_enum_arguments(self, commands, bad):
        with pytest.raises(TypeError):
            commands.supports(bad)

    def test_require_capability_returns_none_when_supported(self, commands_with_declared):
        commands, declared, _ = commands_with_declared
        assert commands._require_capability(declared) is None

    def test_require_capability_raises_when_unsupported(self, commands_with_declared):
        commands, _, other_modes = commands_with_declared
        with pytest.raises(UnsupportedFeatureError) as exc_info:
            commands._require_capability(AdapterCapability.MAX_ROWS)
        assert "max_rows" in str(exc_info.value)
        with pytest.raises(UnsupportedFeatureError):
            commands._require_capability(other_modes)

    @pytest.mark.parametrize("bad", ["transactions", 1, None, object()])
    def test_require_capability_rejects_non_enum_arguments(self, commands, bad):
        with pytest.raises(TypeError):
            commands._require_capability(bad)
