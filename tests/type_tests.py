import datetime
from dataclasses import dataclass
from types import SimpleNamespace
from typing import Any
from typing import AsyncGenerator
from typing import Dict
from typing import Generator
from typing import List
from typing import Tuple
from typing import Union

import pytest
from typing_extensions import assert_type

import pydapper
from pydapper.exceptions import InvalidParameterShapeException
from pydapper.exceptions import MissingParameterException
from pydapper.exceptions import MoreThanOneResultException
from pydapper.exceptions import NoResultException
from pydapper.exceptions import PyDapperException
from pydapper.exceptions import RowMappingException
from pydapper.exceptions import UnsupportedFeatureError

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


def default_callable() -> str:
    return "sup"


def public_exceptions() -> None:
    assert_type(PyDapperException(), PyDapperException)
    assert_type(NoResultException(), NoResultException)
    assert_type(MoreThanOneResultException(), MoreThanOneResultException)
    assert_type(MissingParameterException(), MissingParameterException)
    assert_type(InvalidParameterShapeException(), InvalidParameterShapeException)
    assert_type(UnsupportedFeatureError(), UnsupportedFeatureError)
    assert_type(RowMappingException(), RowMappingException)


class Commands:
    @staticmethod
    def execute(query: str) -> None:
        params = {"id": 1}
        mapping_subclass_params = ParamsDict({"id": 1})
        dataclass_params = Task(1, "task", datetime.date.today(), 1)
        object_params = SimpleNamespace(id=1)
        batch_params = [{"id": 1}, {"id": 2}]

        with pydapper.connect() as commands:
            assert_type(commands.execute(query, param=params), int)
            assert_type(commands.execute(query, params=params), int)
            assert_type(commands.execute(query, params=mapping_subclass_params), int)
            assert_type(commands.execute(query, params=dataclass_params), int)
            assert_type(commands.execute(query, params=object_params), int)
            assert_type(commands.execute(query, params=[]), int)
            assert_type(commands.execute(query, params=batch_params), int)
            assert_type(commands.execute_scalar(query, param=params), Any)
            assert_type(commands.execute_scalar(query, params=params), Any)
            assert_type(commands.query_multiple((query,), param=params), Tuple[List[Any], ...])
            assert_type(commands.query_multiple((query,), params=params), Tuple[List[Any], ...])

    @staticmethod
    def query(query: str) -> None:
        params = {"id": 1}
        mapping_subclass_params = ParamsDict({"id": 1})
        dataclass_params = Task(1, "task", datetime.date.today(), 1)
        object_params = SimpleNamespace(id=1)

        with pydapper.connect() as commands:
            assert_type(commands.query(query, buffered=True), List[Dict[str, Any]])
            assert_type(commands.query(query, buffered=False), Generator[Dict[str, Any], None, None])
            assert_type(commands.query(query, model=Task, buffered=True), List[Task])
            assert_type(commands.query(query, model=lambda **kwargs: Task(**kwargs)), List[Task])
            assert_type(
                commands.query(query, model=lambda **kwargs: Task(**kwargs), buffered=False),
                Generator[Task, None, None],
            )
            assert_type(commands.query(query, model=Task, buffered=False), Generator[Task, None, None])
            assert_type(commands.query(query, param=params), List[Dict[str, Any]])
            assert_type(commands.query(query, params=params), List[Dict[str, Any]])
            assert_type(commands.query(query, params=mapping_subclass_params), List[Dict[str, Any]])
            assert_type(commands.query(query, params=dataclass_params), List[Dict[str, Any]])
            assert_type(commands.query(query, params=object_params), List[Dict[str, Any]])
            assert_type(commands.query(query, params=params, model=Task), List[Task])

    @staticmethod
    def query_first(query: str) -> None:
        params = {"id": 1}

        with pydapper.connect() as commands:
            assert_type(commands.query_first(query), Dict[str, Any])
            assert_type(commands.query_first(query, model=Task), Task)
            assert_type(commands.query_first(query, param=params), Dict[str, Any])
            assert_type(commands.query_first(query, params=params), Dict[str, Any])
            assert_type(commands.query_first(query, params=params, model=Task), Task)

    @staticmethod
    def query_first_or_default(query: str) -> None:
        params = {"id": 1}

        with pydapper.connect() as commands:
            # passing a callable, the return type of the callable is part of the return type
            assert_type(commands.query_first_or_default(query, default_callable, model=Task), Union[str, Task])
            assert_type(commands.query_first_or_default(query, default_callable), Union[str, Dict[str, Any]])
            # passing a non-callable, the return type of the callable is a union of the model + default type
            assert_type(commands.query_first_or_default(query, "hello", model=Task), Union[str, Task])
            assert_type(commands.query_first_or_default(query, "hello"), Union[str, Dict[str, Any]])
            assert_type(commands.query_first_or_default(query, "hello", param=params), Union[str, Dict[str, Any]])
            assert_type(commands.query_first_or_default(query, "hello", params=params), Union[str, Dict[str, Any]])

    @staticmethod
    def query_single(query: str) -> None:
        params = {"id": 1}

        with pydapper.connect() as commands:
            assert_type(commands.query_single(query), Dict[str, Any])
            assert_type(commands.query_single(query, model=Task), Task)
            assert_type(commands.query_single(query, param=params), Dict[str, Any])
            assert_type(commands.query_single(query, params=params), Dict[str, Any])
            assert_type(commands.query_single(query, params=params, model=Task), Task)

    @staticmethod
    def query_single_or_default(query: str) -> None:
        params = {"id": 1}

        with pydapper.connect() as commands:
            # passing a callable, the return type of the callable is part of the return type
            assert_type(commands.query_single_or_default(query, default_callable, model=Task), Union[str, Task])
            assert_type(commands.query_single_or_default(query, default_callable), Union[str, Dict[str, Any]])
            # passing a non-callable, the return type of the callable is a union of the model + default type
            assert_type(commands.query_single_or_default(query, "hello", model=Task), Union[str, Task])
            assert_type(commands.query_single_or_default(query, "hello"), Union[str, Dict[str, Any]])
            assert_type(commands.query_single_or_default(query, "hello", param=params), Union[str, Dict[str, Any]])
            assert_type(commands.query_single_or_default(query, "hello", params=params), Union[str, Dict[str, Any]])


class CommandsAsync:
    @staticmethod
    async def execute(query: str) -> None:
        params = {"id": 1}
        mapping_subclass_params = ParamsDict({"id": 1})
        dataclass_params = Task(1, "task", datetime.date.today(), 1)
        object_params = SimpleNamespace(id=1)
        batch_params = [{"id": 1}, {"id": 2}]

        async with pydapper.connect_async() as commands:
            assert_type(await commands.execute_async(query, param=params), int)
            assert_type(await commands.execute_async(query, params=params), int)
            assert_type(await commands.execute_async(query, params=mapping_subclass_params), int)
            assert_type(await commands.execute_async(query, params=dataclass_params), int)
            assert_type(await commands.execute_async(query, params=object_params), int)
            assert_type(await commands.execute_async(query, params=[]), int)
            assert_type(await commands.execute_async(query, params=batch_params), int)
            assert_type(await commands.execute_scalar_async(query, param=params), Any)
            assert_type(await commands.execute_scalar_async(query, params=params), Any)
            assert_type(await commands.query_multiple_async((query,), param=params), Tuple[List[Any], ...])
            assert_type(await commands.query_multiple_async((query,), params=params), Tuple[List[Any], ...])

    @staticmethod
    async def query(query: str):
        params = {"id": 1}
        mapping_subclass_params = ParamsDict({"id": 1})
        dataclass_params = Task(1, "task", datetime.date.today(), 1)
        object_params = SimpleNamespace(id=1)

        async with pydapper.connect_async() as commands:
            assert_type(await commands.query_async(query, buffered=True), List[Dict[str, Any]])
            assert_type(await commands.query_async(query, buffered=False), AsyncGenerator[Dict[str, Any], None])
            assert_type(await commands.query_async(query, model=Task, buffered=True), List[Task])
            assert_type(await commands.query_async(query, model=Task, buffered=False), AsyncGenerator[Task, None])
            assert_type(await commands.query_async(query, param=params), List[Dict[str, Any]])
            assert_type(await commands.query_async(query, params=params), List[Dict[str, Any]])
            assert_type(await commands.query_async(query, params=mapping_subclass_params), List[Dict[str, Any]])
            assert_type(await commands.query_async(query, params=dataclass_params), List[Dict[str, Any]])
            assert_type(await commands.query_async(query, params=object_params), List[Dict[str, Any]])
            assert_type(await commands.query_async(query, params=params, model=Task), List[Task])

    @staticmethod
    async def query_first(query: str) -> None:
        params = {"id": 1}

        async with pydapper.connect_async() as commands:
            assert_type(await commands.query_first_async(query), Dict[str, Any])
            assert_type(await commands.query_first_async(query, model=Task), Task)
            assert_type(await commands.query_first_async(query, param=params), Dict[str, Any])
            assert_type(await commands.query_first_async(query, params=params), Dict[str, Any])
            assert_type(await commands.query_first_async(query, params=params, model=Task), Task)

    @staticmethod
    async def query_first_or_default(query: str) -> None:
        params = {"id": 1}

        async with pydapper.connect_async() as commands:
            # passing a callable, the return type of the callable is part of the return type
            assert_type(
                await commands.query_first_or_default_async(query, default_callable, model=Task), Union[str, Task]
            )
            assert_type(
                await commands.query_first_or_default_async(query, default_callable), Union[str, Dict[str, Any]]
            )
            # passing a non-callable, the return type of the callable is a union of the model + default type
            assert_type(await commands.query_first_or_default_async(query, "hello", model=Task), Union[str, Task])
            assert_type(await commands.query_first_or_default_async(query, "hello"), Union[str, Dict[str, Any]])
            assert_type(
                await commands.query_first_or_default_async(query, "hello", param=params), Union[str, Dict[str, Any]]
            )
            assert_type(
                await commands.query_first_or_default_async(query, "hello", params=params), Union[str, Dict[str, Any]]
            )

    @staticmethod
    async def query_single(query: str) -> None:
        params = {"id": 1}

        async with pydapper.connect_async() as commands:
            assert_type(await commands.query_single_async(query), Dict[str, Any])
            assert_type(await commands.query_single_async(query, model=Task), Task)
            assert_type(await commands.query_single_async(query, param=params), Dict[str, Any])
            assert_type(await commands.query_single_async(query, params=params), Dict[str, Any])
            assert_type(await commands.query_single_async(query, params=params, model=Task), Task)

    @staticmethod
    async def query_single_or_default(query: str) -> None:
        params = {"id": 1}

        async with pydapper.connect_async() as commands:
            # passing a callable, the return type of the callable is part of the return type
            assert_type(
                await commands.query_single_or_default_async(query, default_callable, model=Task), Union[str, Task]
            )
            assert_type(
                await commands.query_single_or_default_async(query, default_callable), Union[str, Dict[str, Any]]
            )
            # passing a non-callable, the return type of the callable is a union of the model + default type
            assert_type(await commands.query_single_or_default_async(query, "hello", model=Task), Union[str, Task])
            assert_type(await commands.query_single_or_default_async(query, "hello"), Union[str, Dict[str, Any]])
            assert_type(
                await commands.query_single_or_default_async(query, "hello", param=params), Union[str, Dict[str, Any]]
            )
            assert_type(
                await commands.query_single_or_default_async(query, "hello", params=params), Union[str, Dict[str, Any]]
            )
