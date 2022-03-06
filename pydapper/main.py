from __future__ import annotations

import logging
import os
from typing import TYPE_CHECKING
from typing import Dict
from typing import Optional
from typing import Type
from typing import Union
from typing import cast

from coro_context_manager import CoroContextManager

from .commands import Commands
from .commands import CommandsAsync
from .dsn_parser import PydapperParseResult

if TYPE_CHECKING:
    from .commands import Commands
    from .commands import CommandsAsync
    from .types import AsyncConnectionType
    from .types import ConnectionType

logger = logging.getLogger(__name__)


def parse_dsn(dsn: Optional[str]) -> PydapperParseResult:
    dsn = dsn or os.getenv("PYDAPPER_DSN")
    if dsn is None:  # pragma: no cover
        raise ValueError("dsn must be passed to connect or env var `PYDAPPER_DSN` must be set.")
    return PydapperParseResult(dsn)


def find_command_class_in_registry_by_connection(
    connection: Union["ConnectionType", "AsyncConnectionType"],
    registry: Union[Dict[str, Type["Commands"]], Dict[str, Type["CommandsAsync"]]],
) -> Union[Type["Commands"], Type["CommandsAsync"]]:
    connection_base_modules = {str(klass.__module__).split(".")[0] for klass in connection.__class__.__bases__}
    # this will happen if you have a connection that doesn't inherit from anything
    if connection_base_modules == {"builtins"}:  # pragma: no branch
        connection_base_modules = {connection.__class__.__module__.split(".")[0]}
    registered_dbapi_modules = set(registry.keys())
    intersection = connection_base_modules.intersection(registered_dbapi_modules)

    if not intersection:
        raise ValueError(f"No command support registered for {connection}")

    return registry[intersection.pop()]


class CommandFactory:
    sync_registry: Dict[str, Type["Commands"]] = dict()
    async_registry: Dict[str, Type["CommandsAsync"]] = dict()

    @classmethod
    def from_dsn(cls, dsn: str = None, **connect_kwargs) -> "Commands":
        parsed_dsn = parse_dsn(dsn)
        return cls.sync_registry[parsed_dsn.dbapi].connect(parsed_dsn, **connect_kwargs)

    @classmethod
    def from_dsn_async(cls, dsn: str = None, **connect_kwargs) -> CoroContextManager["CommandsAsync"]:
        parsed_dsn = parse_dsn(dsn)
        return CoroContextManager(cls.async_registry[parsed_dsn.dbapi].connect_async(parsed_dsn, **connect_kwargs))

    @classmethod
    def from_connection(cls, connection: ConnectionType) -> "Commands":
        commands_class = cast(
            Type["Commands"], find_command_class_in_registry_by_connection(connection, cls.sync_registry)
        )
        return commands_class(connection)

    @classmethod
    def from_connection_async(cls, connection: AsyncConnectionType) -> "CommandsAsync":
        commands_class = cast(
            Type["CommandsAsync"],
            find_command_class_in_registry_by_connection(connection, cls.async_registry),
        )
        return commands_class(connection)

    @classmethod
    def register(cls, name: str):
        def inner_wrapper(wrapped_class: Type["Commands"]):
            CommandFactory.sync_registry[name] = wrapped_class
            return wrapped_class

        return inner_wrapper

    @classmethod
    def register_async(cls, name: str):
        def inner_wrapper(wrapped_class: Type["CommandsAsync"]):
            CommandFactory.async_registry[name] = wrapped_class
            return wrapped_class

        return inner_wrapper


register = CommandFactory.register
register_async = CommandFactory.register_async
using = CommandFactory.from_connection
using_async = CommandFactory.from_connection_async
connect = CommandFactory.from_dsn
connect_async = CommandFactory.from_dsn_async
