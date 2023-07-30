import datetime
from dataclasses import dataclass
from typing import Any
from typing import AsyncGenerator
from typing import Dict
from typing import Generator
from typing import List
from typing import Union

import pytest
from typing_extensions import assert_type

import pydapper

"""This file tests some of the more complex type annotations on the Commands and AsyncCommands classes"""

pytestmark = pytest.mark.core


@dataclass
class Task:
    id: int
    description: str
    due_date: datetime.date
    owner_id: int


def default_callable() -> str:
    return "sup"


class Commands:
    @staticmethod
    def query(query: str) -> None:
        with pydapper.connect() as commands:
            assert_type(commands.query(query, buffered=True), List[Dict[str, Any]])
            assert_type(commands.query(query, buffered=False), Generator[Dict[str, Any], None, None])
            assert_type(commands.query(query, model=Task, buffered=True), List[Task])
            assert_type(commands.query(query, model=Task, buffered=False), Generator[Task, None, None])

    @staticmethod
    def query_first(query: str) -> None:
        with pydapper.connect() as commands:
            assert_type(commands.query_first(query), Dict[str, Any])
            assert_type(commands.query_first(query, model=Task), Task)

    @staticmethod
    def query_first_or_default(query: str) -> None:
        with pydapper.connect() as commands:
            # passing a callable, the return type of the callable is part of the return type
            assert_type(commands.query_first_or_default(query, default_callable, model=Task), Union[str, Task])
            assert_type(commands.query_first_or_default(query, default_callable), Union[str, Dict[str, Any]])
            # passing a non-callable, the return type of the callable is a union of the model + default type
            assert_type(commands.query_first_or_default(query, "hello", model=Task), Union[str, Task])
            assert_type(commands.query_first_or_default(query, "hello"), Union[str, Dict[str, Any]])

    @staticmethod
    def query_single(query: str) -> None:
        with pydapper.connect() as commands:
            assert_type(commands.query_single(query), Dict[str, Any])
            assert_type(commands.query_single(query, model=Task), Task)

    @staticmethod
    def query_single_or_default(query: str) -> None:
        with pydapper.connect() as commands:
            # passing a callable, the return type of the callable is part of the return type
            assert_type(commands.query_single_or_default(query, default_callable, model=Task), Union[str, Task])
            assert_type(commands.query_single_or_default(query, default_callable), Union[str, Dict[str, Any]])
            # passing a non-callable, the return type of the callable is a union of the model + default type
            assert_type(commands.query_single_or_default(query, "hello", model=Task), Union[str, Task])
            assert_type(commands.query_single_or_default(query, "hello"), Union[str, Dict[str, Any]])


class CommandsAsync:
    @staticmethod
    async def query(query: str):
        async with pydapper.connect_async() as commands:
            assert_type(await commands.query_async(query, buffered=True), List[Dict[str, Any]])
            assert_type(await commands.query_async(query, buffered=False), AsyncGenerator[Dict[str, Any], None])
            assert_type(await commands.query_async(query, model=Task, buffered=True), List[Task])
            assert_type(await commands.query_async(query, model=Task, buffered=False), AsyncGenerator[Task, None])

    @staticmethod
    async def query_first(query: str) -> None:
        async with pydapper.connect_async() as commands:
            assert_type(await commands.query_first_async(query), Dict[str, Any])
            assert_type(await commands.query_first_async(query, model=Task), Task)

    @staticmethod
    async def query_first_or_default(query: str) -> None:
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

    @staticmethod
    async def query_single(query: str) -> None:
        async with pydapper.connect_async() as commands:
            assert_type(await commands.query_single_async(query), Dict[str, Any])
            assert_type(await commands.query_single_async(query, model=Task), Task)

    @staticmethod
    async def query_single_or_default(query: str) -> None:
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
