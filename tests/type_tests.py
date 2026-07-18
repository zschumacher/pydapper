import datetime
from dataclasses import dataclass
from types import SimpleNamespace
from typing import Any
from typing import AsyncGenerator
from typing import Dict
from typing import Generator
from typing import List
from typing import Literal
from typing import Tuple
from typing import Union
from typing import cast

import pytest
from typing_extensions import assert_type

import pydapper
from pydapper.commands import BaseSqlParamHandler
from pydapper.commands import Commands as PydapperCommands
from pydapper.commands import CommandsAsync as PydapperCommandsAsync
from pydapper.exceptions import DuplicateColumnException
from pydapper.exceptions import InvalidParameterShapeException
from pydapper.exceptions import MissingParameterException
from pydapper.exceptions import MoreThanOneResultException
from pydapper.exceptions import NoResultException
from pydapper.exceptions import PyDapperException
from pydapper.exceptions import RowMappingException
from pydapper.exceptions import UnsupportedFeatureError
from pydapper.postgresql import Psycopg3CommandsAsync
from pydapper.sqlite import Sqlite3Commands
from pydapper.types import AsyncConnectionType
from pydapper.types import AsyncCursorType
from pydapper.types import ConnectionType
from pydapper.types import CursorType

"""This file tests some of the more complex type annotations on the Commands and AsyncCommands classes"""

pytestmark = pytest.mark.core


@dataclass
class Task:
    id: int
    description: str
    due_date: datetime.date
    owner_id: int


class ParamsDict(dict[str, Any]):
    pass


class Params:
    id: int

    def __init__(self, id: int) -> None:
        self.id = id


class SlottedParams:
    __slots__ = ("id",)

    id: int

    def __init__(self, id: int) -> None:
        self.id = id


def default_callable() -> str:
    return "sup"


def to_task(row: pydapper.RawRow) -> Task:
    return Task(
        id=row.values[0],
        description=row.values[1],
        due_date=row.values[2],
        owner_id=row.values[3],
    )


def to_id(row: pydapper.RawRow) -> int:
    return row[0]


def to_description(row: pydapper.RawRow) -> str:
    return row[1]


task_mapper: pydapper.Mapper[Task] = to_task


def public_exceptions() -> None:
    assert_type(pydapper.CommandKind.TEXT, Literal[pydapper.CommandKind.TEXT])
    assert_type(pydapper.CommandOptions(), pydapper.CommandOptions)
    assert_type(task_mapper, pydapper.Mapper[Task])
    assert_type(pydapper.RawRow(("id",), (1,)), pydapper.RawRow)
    assert_type(pydapper.RawRow(("id",), (1,)).columns, Tuple[str, ...])
    assert_type(pydapper.RawRow(("id",), (1,)).values, Tuple[Any, ...])
    assert_type(pydapper.RawRow(("id", "name"), (1, "task"))[0:1], Tuple[Any, ...])
    assert_type(pydapper.RawRow(("id",), (1,)).as_dict(), Dict[str, Any])
    assert_type(PyDapperException(), PyDapperException)
    assert_type(
        DuplicateColumnException(
            columns=("id", "id"),
            duplicate_columns=("id",),
            duplicate_indexes=(0, 1),
        ),
        DuplicateColumnException,
    )
    assert_type(NoResultException(), NoResultException)
    assert_type(MoreThanOneResultException(), MoreThanOneResultException)
    assert_type(MissingParameterException(), MissingParameterException)
    assert_type(InvalidParameterShapeException(), InvalidParameterShapeException)
    assert_type(UnsupportedFeatureError(), UnsupportedFeatureError)
    assert_type(RowMappingException(), RowMappingException)


def adapter_capability_types() -> None:
    assert_type(pydapper.AdapterCapability.TRANSACTIONS, Literal[pydapper.AdapterCapability.TRANSACTIONS])
    sync_commands = cast(PydapperCommands, object())
    async_commands = cast(PydapperCommandsAsync, object())
    assert_type(sync_commands.capabilities, frozenset[pydapper.AdapterCapability])
    assert_type(async_commands.capabilities, frozenset[pydapper.AdapterCapability])
    assert_type(sync_commands.supports(pydapper.AdapterCapability.TRANSACTIONS), bool)
    assert_type(async_commands.supports(pydapper.AdapterCapability.TRANSACTIONS), bool)
    assert_type(sync_commands._require_capability(pydapper.AdapterCapability.TRANSACTIONS), None)
    assert_type(async_commands._require_capability(pydapper.AdapterCapability.TRANSACTIONS), None)
    # concrete first-party declarations stay typed as frozenset[AdapterCapability]
    assert_type(Sqlite3Commands.capabilities, frozenset[pydapper.AdapterCapability])
    assert_type(Psycopg3CommandsAsync.capabilities, frozenset[pydapper.AdapterCapability])


def preparation_hook_types() -> None:
    sync_commands = cast(PydapperCommands, object())
    cursor = cast(CursorType, object())
    handler = cast(BaseSqlParamHandler, object())
    options = pydapper.CommandOptions()
    assert_type(sync_commands._prepare_cursor(cursor, options=options), None)
    assert_type(sync_commands._prepare_command(cursor, handler, options=options), None)


async def preparation_hook_async_types() -> None:
    async_commands = cast(PydapperCommandsAsync, object())
    async_cursor = cast(AsyncCursorType, object())
    handler = cast(BaseSqlParamHandler, object())
    options = pydapper.CommandOptions()
    assert_type(await async_commands._prepare_cursor_async(async_cursor, options=options), None)
    assert_type(await async_commands._prepare_command_async(async_cursor, handler, options=options), None)


def _cannot_handle_connection(connection: object) -> bool:
    return False


def adapter_registration_types() -> None:
    assert_type(
        pydapper.register_adapter(
            "type-sync",
            commands=PydapperCommands,
            using_connection_predicate=_cannot_handle_connection,
        ),
        None,
    )
    assert_type(
        pydapper.register_adapter(
            "type-async",
            async_commands=PydapperCommandsAsync,
            using_connection_predicate=_cannot_handle_connection,
        ),
        None,
    )
    assert_type(
        pydapper.register_adapter(
            "type-combined",
            commands=PydapperCommands,
            async_commands=PydapperCommandsAsync,
            using_connection_predicate=_cannot_handle_connection,
        ),
        None,
    )

    sync_connection = cast(ConnectionType, object())
    async_connection = cast(AsyncConnectionType, object())
    assert_type(pydapper.using(sync_connection, adapter="type-sync"), PydapperCommands)
    assert_type(pydapper.using_async(async_connection, adapter="type-async"), PydapperCommandsAsync)


class Commands:
    @staticmethod
    def execute(query: str) -> None:
        params = {"id": 1}
        options = pydapper.CommandOptions()
        mapping_subclass_params = ParamsDict({"id": 1})
        dataclass_params = Task(1, "task", datetime.date.today(), 1)
        object_params = SimpleNamespace(id=1)
        attribute_params = Params(1)
        slotted_params = SlottedParams(1)
        batch_params = [{"id": 1}, {"id": 2}]

        with pydapper.connect() as commands:
            assert_type(commands.execute(query, param=params), int)
            assert_type(commands.execute(query, options=pydapper.CommandOptions()), int)
            assert_type(commands.execute(query, params=params), int)
            assert_type(commands.execute(query, params=mapping_subclass_params), int)
            assert_type(commands.execute(query, params=dataclass_params), int)
            assert_type(commands.execute(query, params=object_params), int)
            assert_type(commands.execute(query, params=attribute_params), int)
            assert_type(commands.execute(query, params=slotted_params), int)
            assert_type(commands.execute(query, params=[]), int)
            assert_type(commands.execute(query, params=batch_params), int)
            assert_type(commands.execute_scalar(query, param=params), Any)
            assert_type(commands.execute_scalar(query, params=params), Any)
            assert_type(commands.execute_scalar(query, options=pydapper.CommandOptions()), Any)
            assert_type(commands.query_multiple((query,), param=params), Tuple[List[Any], ...])
            assert_type(commands.query_multiple((query,), params=params), Tuple[List[Any], ...])
            assert_type(commands.query_multiple((query,), mapper=to_task, options=options), Tuple[List[Task]])
            assert_type(
                commands.query_multiple((query,), mapper=to_task, param=params, options=options), Tuple[List[Task]]
            )
            assert_type(
                commands.query_multiple((query,), mapper=to_task, params=params, options=options), Tuple[List[Task]]
            )
            assert_type(
                commands.query_multiple((query, query), mapper=to_task, options=options),
                Tuple[List[Task], List[Task]],
            )
            assert_type(
                commands.query_multiple((query, query, query), mapper=to_task, options=options),
                Tuple[List[Task], List[Task], List[Task]],
            )
            assert_type(
                commands.query_multiple((query, query), mapper=(to_id, to_description), options=options),
                Tuple[List[int], List[str]],
            )
            assert_type(
                commands.query_multiple((query, query), mapper=(to_id, to_description), param=params, options=options),
                Tuple[List[int], List[str]],
            )
            assert_type(commands.query_multiple((query,), mapper=to_task), Tuple[List[Task]])
            assert_type(commands.query_multiple((query, query), mapper=to_task), Tuple[List[Task], List[Task]])
            assert_type(
                commands.query_multiple((query, query), mapper=(to_id, to_description)),
                Tuple[List[int], List[str]],
            )

    @staticmethod
    def query(query: str) -> None:
        params = {"id": 1}
        options = pydapper.CommandOptions()
        mapping_subclass_params = ParamsDict({"id": 1})
        dataclass_params = Task(1, "task", datetime.date.today(), 1)
        object_params = SimpleNamespace(id=1)
        attribute_params = Params(1)
        slotted_params = SlottedParams(1)
        buffered: bool = bool(query)

        with pydapper.connect() as commands:
            assert_type(commands.query(query, buffered=True), List[Dict[str, Any]])
            assert_type(commands.query(query, options=pydapper.CommandOptions()), List[Dict[str, Any]])
            assert_type(commands.query(query, buffered=True, options=options), List[Dict[str, Any]])
            assert_type(commands.query(query, param=params, options=options), List[Dict[str, Any]])
            assert_type(commands.query(query, params=params, options=options), List[Dict[str, Any]])
            assert_type(
                commands.query(query, buffered=buffered, options=options),
                Union[List[Dict[str, Any]], Generator[Dict[str, Any], None, None]],
            )
            assert_type(commands.query(query, buffered=False, options=options), Generator[Dict[str, Any], None, None])
            assert_type(commands.query(query, buffered=False), Generator[Dict[str, Any], None, None])
            assert_type(
                commands.query(query, buffered=buffered),
                Union[List[Dict[str, Any]], Generator[Dict[str, Any], None, None]],
            )
            assert_type(
                commands.query(query, params=params, buffered=buffered),
                Union[List[Dict[str, Any]], Generator[Dict[str, Any], None, None]],
            )
            assert_type(commands.query(query, Task, buffered=True), List[Task])
            assert_type(
                commands.query(query, Task, buffered=buffered),
                Union[List[Task], Generator[Task, None, None]],
            )
            assert_type(
                commands.query(query, Task, params=params, buffered=buffered),
                Union[List[Task], Generator[Task, None, None]],
            )
            assert_type(commands.query(query, model=Task, buffered=True), List[Task])
            assert_type(
                commands.query(query, model=Task, buffered=buffered),
                Union[List[Task], Generator[Task, None, None]],
            )
            assert_type(
                commands.query(query, model=Task, params=params, buffered=buffered),
                Union[List[Task], Generator[Task, None, None]],
            )
            assert_type(commands.query(query, model=lambda **kwargs: Task(**kwargs)), List[Task])
            assert_type(commands.query(query, mapper=to_task), List[Task])
            assert_type(commands.query(query, model=Task, options=pydapper.CommandOptions()), List[Task])
            assert_type(commands.query(query, model=Task, buffered=True, options=options), List[Task])
            assert_type(
                commands.query(query, model=Task, buffered=buffered, options=options),
                Union[List[Task], Generator[Task, None, None]],
            )
            assert_type(commands.query(query, model=Task, buffered=False, options=options), Generator[Task, None, None])
            assert_type(commands.query(query, mapper=to_task, options=options), List[Task])
            assert_type(commands.query(query, mapper=to_task, buffered=True, options=options), List[Task])
            assert_type(
                commands.query(query, mapper=to_task, buffered=buffered, options=options),
                Union[List[Task], Generator[Task, None, None]],
            )
            assert_type(
                commands.query(query, mapper=to_task, buffered=False, options=options), Generator[Task, None, None]
            )
            assert_type(commands.query(query, param=params, mapper=to_task), List[Task])
            assert_type(commands.query(query, params=params, mapper=to_task), List[Task])
            assert_type(
                commands.query(query, mapper=to_task, buffered=buffered),
                Union[List[Task], Generator[Task, None, None]],
            )
            assert_type(
                commands.query(query, model=lambda **kwargs: Task(**kwargs), buffered=False),
                Generator[Task, None, None],
            )
            assert_type(commands.query(query, model=Task, buffered=False), Generator[Task, None, None])
            assert_type(commands.query(query, mapper=to_task, buffered=False), Generator[Task, None, None])
            assert_type(
                commands.query(query, param=params, mapper=to_task, buffered=False),
                Generator[Task, None, None],
            )
            assert_type(
                commands.query(query, params=params, mapper=to_task, buffered=False),
                Generator[Task, None, None],
            )
            assert_type(commands.query(query, param=params), List[Dict[str, Any]])
            assert_type(commands.query(query, params=params), List[Dict[str, Any]])
            assert_type(commands.query(query, params=mapping_subclass_params), List[Dict[str, Any]])
            assert_type(commands.query(query, params=dataclass_params), List[Dict[str, Any]])
            assert_type(commands.query(query, params=object_params), List[Dict[str, Any]])
            assert_type(commands.query(query, params=attribute_params), List[Dict[str, Any]])
            assert_type(commands.query(query, params=slotted_params), List[Dict[str, Any]])
            assert_type(commands.query(query, Task, params=params), List[Task])
            assert_type(commands.query(query, params=params, model=Task), List[Task])

    @staticmethod
    def query_first(query: str) -> None:
        params = {"id": 1}
        options = pydapper.CommandOptions()

        with pydapper.connect() as commands:
            assert_type(commands.query_first(query), Dict[str, Any])
            assert_type(commands.query_first(query, Task), Task)
            assert_type(commands.query_first(query, Task, params), Task)
            assert_type(commands.query_first(query, model=Task), Task)
            assert_type(commands.query_first(query, mapper=to_task), Task)
            assert_type(commands.query_first(query, param=params, mapper=to_task), Task)
            assert_type(commands.query_first(query, param=params), Dict[str, Any])
            assert_type(commands.query_first(query, params=params), Dict[str, Any])
            assert_type(commands.query_first(query, params=params, model=Task), Task)
            assert_type(commands.query_first(query, params=params, mapper=to_task), Task)
            assert_type(commands.query_first(query, options=options), Dict[str, Any])
            assert_type(commands.query_first(query, param=params, options=options), Dict[str, Any])
            assert_type(commands.query_first(query, model=Task, options=options), Task)
            assert_type(commands.query_first(query, mapper=to_task, options=options), Task)

    @staticmethod
    def query_first_or_default(query: str) -> None:
        params = {"id": 1}
        options = pydapper.CommandOptions()

        with pydapper.connect() as commands:
            # passing a callable, the return type of the callable is part of the return type
            assert_type(commands.query_first_or_default(query, default_callable, model=Task), Union[str, Task])
            assert_type(commands.query_first_or_default(query, default_callable, mapper=to_task), Union[str, Task])
            assert_type(commands.query_first_or_default(query, default_callable), Union[str, Dict[str, Any]])
            assert_type(
                commands.query_first_or_default(query, task_mapper, mapper=to_task),
                Union[pydapper.Mapper[Task], Task],
            )
            # passing a non-callable, the return type of the callable is a union of the model + default type
            assert_type(commands.query_first_or_default(query, "hello", Task), Union[str, Task])
            assert_type(commands.query_first_or_default(query, "hello", model=Task), Union[str, Task])
            assert_type(commands.query_first_or_default(query, "hello", mapper=to_task), Union[str, Task])
            assert_type(commands.query_first_or_default(query, "hello"), Union[str, Dict[str, Any]])
            assert_type(commands.query_first_or_default(query, "hello", param=params), Union[str, Dict[str, Any]])
            assert_type(commands.query_first_or_default(query, "hello", params=params), Union[str, Dict[str, Any]])
            assert_type(
                commands.query_first_or_default(query, default_callable, options=options), Union[str, Dict[str, Any]]
            )
            assert_type(commands.query_first_or_default(query, "hello", options=options), Union[str, Dict[str, Any]])
            assert_type(
                commands.query_first_or_default(query, default_callable, model=Task, options=options), Union[str, Task]
            )
            assert_type(
                commands.query_first_or_default(query, "hello", mapper=to_task, options=options), Union[str, Task]
            )

    @staticmethod
    def query_single(query: str) -> None:
        params = {"id": 1}
        options = pydapper.CommandOptions()

        with pydapper.connect() as commands:
            assert_type(commands.query_single(query), Dict[str, Any])
            assert_type(commands.query_single(query, Task), Task)
            assert_type(commands.query_single(query, Task, params), Task)
            assert_type(commands.query_single(query, model=Task), Task)
            assert_type(commands.query_single(query, mapper=to_task), Task)
            assert_type(commands.query_single(query, param=params, mapper=to_task), Task)
            assert_type(commands.query_single(query, param=params), Dict[str, Any])
            assert_type(commands.query_single(query, params=params), Dict[str, Any])
            assert_type(commands.query_single(query, params=params, model=Task), Task)
            assert_type(commands.query_single(query, params=params, mapper=to_task), Task)
            assert_type(commands.query_single(query, options=options), Dict[str, Any])
            assert_type(commands.query_single(query, params=params, options=options), Dict[str, Any])
            assert_type(commands.query_single(query, model=Task, options=options), Task)
            assert_type(commands.query_single(query, mapper=to_task, options=options), Task)

    @staticmethod
    def query_single_or_default(query: str) -> None:
        params = {"id": 1}
        options = pydapper.CommandOptions()

        with pydapper.connect() as commands:
            # passing a callable, the return type of the callable is part of the return type
            assert_type(commands.query_single_or_default(query, default_callable, model=Task), Union[str, Task])
            assert_type(commands.query_single_or_default(query, default_callable, mapper=to_task), Union[str, Task])
            assert_type(commands.query_single_or_default(query, default_callable), Union[str, Dict[str, Any]])
            assert_type(
                commands.query_single_or_default(query, task_mapper, mapper=to_task),
                Union[pydapper.Mapper[Task], Task],
            )
            # passing a non-callable, the return type of the callable is a union of the model + default type
            assert_type(commands.query_single_or_default(query, "hello", Task), Union[str, Task])
            assert_type(commands.query_single_or_default(query, "hello", model=Task), Union[str, Task])
            assert_type(commands.query_single_or_default(query, "hello", mapper=to_task), Union[str, Task])
            assert_type(commands.query_single_or_default(query, "hello"), Union[str, Dict[str, Any]])
            assert_type(commands.query_single_or_default(query, "hello", param=params), Union[str, Dict[str, Any]])
            assert_type(commands.query_single_or_default(query, "hello", params=params), Union[str, Dict[str, Any]])
            assert_type(
                commands.query_single_or_default(query, default_callable, options=options), Union[str, Dict[str, Any]]
            )
            assert_type(commands.query_single_or_default(query, "hello", options=options), Union[str, Dict[str, Any]])
            assert_type(
                commands.query_single_or_default(query, default_callable, model=Task, options=options), Union[str, Task]
            )
            assert_type(
                commands.query_single_or_default(query, "hello", mapper=to_task, options=options), Union[str, Task]
            )


class CommandsAsync:
    @staticmethod
    async def execute(query: str) -> None:
        params = {"id": 1}
        options = pydapper.CommandOptions()
        mapping_subclass_params = ParamsDict({"id": 1})
        dataclass_params = Task(1, "task", datetime.date.today(), 1)
        object_params = SimpleNamespace(id=1)
        attribute_params = Params(1)
        slotted_params = SlottedParams(1)
        batch_params = [{"id": 1}, {"id": 2}]

        assert_type(await pydapper.connect_async(), PydapperCommandsAsync)
        async with pydapper.connect_async() as commands:
            assert_type(commands, PydapperCommandsAsync)
            assert_type(await commands.execute_async(query, param=params), int)
            assert_type(await commands.execute_async(query, params=params), int)
            assert_type(await commands.execute_async(query, params=mapping_subclass_params), int)
            assert_type(await commands.execute_async(query, params=dataclass_params), int)
            assert_type(await commands.execute_async(query, params=object_params), int)
            assert_type(await commands.execute_async(query, params=attribute_params), int)
            assert_type(await commands.execute_async(query, params=slotted_params), int)
            assert_type(await commands.execute_async(query, params=[]), int)
            assert_type(await commands.execute_async(query, params=batch_params), int)
            assert_type(await commands.execute_scalar_async(query, param=params), Any)
            assert_type(await commands.execute_scalar_async(query, params=params), Any)
            assert_type(await commands.query_multiple_async((query,), param=params), Tuple[List[Any], ...])
            assert_type(await commands.query_multiple_async((query,), params=params), Tuple[List[Any], ...])
            assert_type(
                await commands.query_multiple_async((query,), mapper=to_task, options=options), Tuple[List[Task]]
            )
            assert_type(
                await commands.query_multiple_async((query,), mapper=to_task, param=params, options=options),
                Tuple[List[Task]],
            )
            assert_type(
                await commands.query_multiple_async((query,), mapper=to_task, params=params, options=options),
                Tuple[List[Task]],
            )
            assert_type(
                await commands.query_multiple_async((query, query), mapper=to_task, options=options),
                Tuple[List[Task], List[Task]],
            )
            assert_type(
                await commands.query_multiple_async((query, query, query), mapper=to_task, options=options),
                Tuple[List[Task], List[Task], List[Task]],
            )
            assert_type(
                await commands.query_multiple_async((query, query), mapper=(to_id, to_description), options=options),
                Tuple[List[int], List[str]],
            )
            assert_type(
                await commands.query_multiple_async(
                    (query, query), mapper=(to_id, to_description), params=params, options=options
                ),
                Tuple[List[int], List[str]],
            )
            assert_type(await commands.query_multiple_async((query,), mapper=to_task), Tuple[List[Task]])
            assert_type(
                await commands.query_multiple_async((query, query), mapper=to_task),
                Tuple[List[Task], List[Task]],
            )
            assert_type(
                await commands.query_multiple_async((query, query), mapper=(to_id, to_description)),
                Tuple[List[int], List[str]],
            )

    @staticmethod
    async def query(query: str):
        params = {"id": 1}
        options = pydapper.CommandOptions()
        mapping_subclass_params = ParamsDict({"id": 1})
        dataclass_params = Task(1, "task", datetime.date.today(), 1)
        object_params = SimpleNamespace(id=1)
        attribute_params = Params(1)
        slotted_params = SlottedParams(1)
        buffered: bool = bool(query)

        async with pydapper.connect_async() as commands:
            assert_type(await commands.query_async(query, buffered=True), List[Dict[str, Any]])
            assert_type(await commands.query_async(query, options=options), List[Dict[str, Any]])
            assert_type(await commands.query_async(query, buffered=True, options=options), List[Dict[str, Any]])
            assert_type(await commands.query_async(query, param=params, options=options), List[Dict[str, Any]])
            assert_type(await commands.query_async(query, params=params, options=options), List[Dict[str, Any]])
            assert_type(
                await commands.query_async(query, buffered=buffered, options=options),
                Union[List[Dict[str, Any]], AsyncGenerator[Dict[str, Any], None]],
            )
            assert_type(
                await commands.query_async(query, buffered=False, options=options),
                AsyncGenerator[Dict[str, Any], None],
            )
            assert_type(await commands.query_async(query, buffered=False), AsyncGenerator[Dict[str, Any], None])
            assert_type(
                await commands.query_async(query, buffered=buffered),
                Union[List[Dict[str, Any]], AsyncGenerator[Dict[str, Any], None]],
            )
            assert_type(
                await commands.query_async(query, params=params, buffered=buffered),
                Union[List[Dict[str, Any]], AsyncGenerator[Dict[str, Any], None]],
            )
            assert_type(await commands.query_async(query, Task, buffered=True), List[Task])
            assert_type(
                await commands.query_async(query, Task, buffered=buffered),
                Union[List[Task], AsyncGenerator[Task, None]],
            )
            assert_type(
                await commands.query_async(query, Task, params=params, buffered=buffered),
                Union[List[Task], AsyncGenerator[Task, None]],
            )
            assert_type(await commands.query_async(query, model=Task, buffered=True), List[Task])
            assert_type(await commands.query_async(query, model=Task, options=options), List[Task])
            assert_type(await commands.query_async(query, model=Task, buffered=True, options=options), List[Task])
            assert_type(
                await commands.query_async(query, model=Task, buffered=buffered, options=options),
                Union[List[Task], AsyncGenerator[Task, None]],
            )
            assert_type(
                await commands.query_async(query, model=Task, buffered=False, options=options),
                AsyncGenerator[Task, None],
            )
            assert_type(await commands.query_async(query, model=Task, buffered=False), AsyncGenerator[Task, None])
            assert_type(
                await commands.query_async(query, model=Task, buffered=buffered),
                Union[List[Task], AsyncGenerator[Task, None]],
            )
            assert_type(
                await commands.query_async(query, model=Task, params=params, buffered=buffered),
                Union[List[Task], AsyncGenerator[Task, None]],
            )
            assert_type(await commands.query_async(query, mapper=to_task), List[Task])
            assert_type(await commands.query_async(query, mapper=to_task, options=options), List[Task])
            assert_type(await commands.query_async(query, mapper=to_task, buffered=True, options=options), List[Task])
            assert_type(
                await commands.query_async(query, mapper=to_task, buffered=buffered, options=options),
                Union[List[Task], AsyncGenerator[Task, None]],
            )
            assert_type(
                await commands.query_async(query, mapper=to_task, buffered=False, options=options),
                AsyncGenerator[Task, None],
            )
            assert_type(await commands.query_async(query, param=params, mapper=to_task), List[Task])
            assert_type(await commands.query_async(query, params=params, mapper=to_task), List[Task])
            assert_type(await commands.query_async(query, mapper=to_task, buffered=False), AsyncGenerator[Task, None])
            assert_type(
                await commands.query_async(query, mapper=to_task, buffered=buffered),
                Union[List[Task], AsyncGenerator[Task, None]],
            )
            assert_type(
                await commands.query_async(query, param=params, mapper=to_task, buffered=False),
                AsyncGenerator[Task, None],
            )
            assert_type(
                await commands.query_async(query, params=params, mapper=to_task, buffered=False),
                AsyncGenerator[Task, None],
            )
            assert_type(await commands.query_async(query, param=params), List[Dict[str, Any]])
            assert_type(await commands.query_async(query, params=params), List[Dict[str, Any]])
            assert_type(await commands.query_async(query, params=mapping_subclass_params), List[Dict[str, Any]])
            assert_type(await commands.query_async(query, params=dataclass_params), List[Dict[str, Any]])
            assert_type(await commands.query_async(query, params=object_params), List[Dict[str, Any]])
            assert_type(await commands.query_async(query, params=attribute_params), List[Dict[str, Any]])
            assert_type(await commands.query_async(query, params=slotted_params), List[Dict[str, Any]])
            assert_type(await commands.query_async(query, Task, params=params), List[Task])
            assert_type(await commands.query_async(query, params=params, model=Task), List[Task])

    @staticmethod
    async def query_first(query: str) -> None:
        params = {"id": 1}
        options = pydapper.CommandOptions()

        async with pydapper.connect_async() as commands:
            assert_type(await commands.query_first_async(query), Dict[str, Any])
            assert_type(await commands.query_first_async(query, Task), Task)
            assert_type(await commands.query_first_async(query, Task, params), Task)
            assert_type(await commands.query_first_async(query, model=Task), Task)
            assert_type(await commands.query_first_async(query, mapper=to_task), Task)
            assert_type(await commands.query_first_async(query, param=params, mapper=to_task), Task)
            assert_type(await commands.query_first_async(query, param=params), Dict[str, Any])
            assert_type(await commands.query_first_async(query, params=params), Dict[str, Any])
            assert_type(await commands.query_first_async(query, params=params, model=Task), Task)
            assert_type(await commands.query_first_async(query, params=params, mapper=to_task), Task)
            assert_type(await commands.query_first_async(query, options=options), Dict[str, Any])
            assert_type(await commands.query_first_async(query, params=params, options=options), Dict[str, Any])
            assert_type(await commands.query_first_async(query, model=Task, options=options), Task)
            assert_type(await commands.query_first_async(query, mapper=to_task, options=options), Task)

    @staticmethod
    async def query_first_or_default(query: str) -> None:
        params = {"id": 1}
        options = pydapper.CommandOptions()

        async with pydapper.connect_async() as commands:
            # passing a callable, the return type of the callable is part of the return type
            assert_type(
                await commands.query_first_or_default_async(query, default_callable, model=Task), Union[str, Task]
            )
            assert_type(
                await commands.query_first_or_default_async(query, default_callable, mapper=to_task), Union[str, Task]
            )
            assert_type(
                await commands.query_first_or_default_async(query, default_callable), Union[str, Dict[str, Any]]
            )
            assert_type(
                await commands.query_first_or_default_async(query, task_mapper, mapper=to_task),
                Union[pydapper.Mapper[Task], Task],
            )
            # passing a non-callable, the return type of the callable is a union of the model + default type
            assert_type(await commands.query_first_or_default_async(query, "hello", Task), Union[str, Task])
            assert_type(await commands.query_first_or_default_async(query, "hello", model=Task), Union[str, Task])
            assert_type(await commands.query_first_or_default_async(query, "hello", mapper=to_task), Union[str, Task])
            assert_type(await commands.query_first_or_default_async(query, "hello"), Union[str, Dict[str, Any]])
            assert_type(
                await commands.query_first_or_default_async(query, "hello", param=params), Union[str, Dict[str, Any]]
            )
            assert_type(
                await commands.query_first_or_default_async(query, "hello", params=params), Union[str, Dict[str, Any]]
            )
            assert_type(
                await commands.query_first_or_default_async(query, default_callable, options=options),
                Union[str, Dict[str, Any]],
            )
            assert_type(
                await commands.query_first_or_default_async(query, "hello", options=options),
                Union[str, Dict[str, Any]],
            )
            assert_type(
                await commands.query_first_or_default_async(query, default_callable, model=Task, options=options),
                Union[str, Task],
            )
            assert_type(
                await commands.query_first_or_default_async(query, "hello", mapper=to_task, options=options),
                Union[str, Task],
            )

    @staticmethod
    async def query_single(query: str) -> None:
        params = {"id": 1}
        options = pydapper.CommandOptions()

        async with pydapper.connect_async() as commands:
            assert_type(await commands.query_single_async(query), Dict[str, Any])
            assert_type(await commands.query_single_async(query, Task), Task)
            assert_type(await commands.query_single_async(query, Task, params), Task)
            assert_type(await commands.query_single_async(query, model=Task), Task)
            assert_type(await commands.query_single_async(query, mapper=to_task), Task)
            assert_type(await commands.query_single_async(query, param=params, mapper=to_task), Task)
            assert_type(await commands.query_single_async(query, param=params), Dict[str, Any])
            assert_type(await commands.query_single_async(query, params=params), Dict[str, Any])
            assert_type(await commands.query_single_async(query, params=params, model=Task), Task)
            assert_type(await commands.query_single_async(query, params=params, mapper=to_task), Task)
            assert_type(await commands.query_single_async(query, options=options), Dict[str, Any])
            assert_type(await commands.query_single_async(query, param=params, options=options), Dict[str, Any])
            assert_type(await commands.query_single_async(query, model=Task, options=options), Task)
            assert_type(await commands.query_single_async(query, mapper=to_task, options=options), Task)

    @staticmethod
    async def query_single_or_default(query: str) -> None:
        params = {"id": 1}
        options = pydapper.CommandOptions()

        async with pydapper.connect_async() as commands:
            # passing a callable, the return type of the callable is part of the return type
            assert_type(
                await commands.query_single_or_default_async(query, default_callable, model=Task), Union[str, Task]
            )
            assert_type(
                await commands.query_single_or_default_async(query, default_callable, mapper=to_task), Union[str, Task]
            )
            assert_type(
                await commands.query_single_or_default_async(query, default_callable), Union[str, Dict[str, Any]]
            )
            assert_type(
                await commands.query_single_or_default_async(query, task_mapper, mapper=to_task),
                Union[pydapper.Mapper[Task], Task],
            )
            # passing a non-callable, the return type of the callable is a union of the model + default type
            assert_type(await commands.query_single_or_default_async(query, "hello", Task), Union[str, Task])
            assert_type(await commands.query_single_or_default_async(query, "hello", model=Task), Union[str, Task])
            assert_type(await commands.query_single_or_default_async(query, "hello", mapper=to_task), Union[str, Task])
            assert_type(await commands.query_single_or_default_async(query, "hello"), Union[str, Dict[str, Any]])
            assert_type(
                await commands.query_single_or_default_async(query, "hello", param=params), Union[str, Dict[str, Any]]
            )
            assert_type(
                await commands.query_single_or_default_async(query, "hello", params=params), Union[str, Dict[str, Any]]
            )
            assert_type(
                await commands.query_single_or_default_async(query, default_callable, options=options),
                Union[str, Dict[str, Any]],
            )
            assert_type(
                await commands.query_single_or_default_async(query, "hello", options=options),
                Union[str, Dict[str, Any]],
            )
            assert_type(
                await commands.query_single_or_default_async(query, default_callable, model=Task, options=options),
                Union[str, Task],
            )
            assert_type(
                await commands.query_single_or_default_async(query, "hello", mapper=to_task, options=options),
                Union[str, Task],
            )
