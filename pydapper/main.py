from __future__ import annotations

import logging
from typing import TYPE_CHECKING
from typing import Type

from .dsn_parser import PydapperParseResult

if TYPE_CHECKING:
    from .commands import Commands
    from .types import ConnectionType

logger = logging.getLogger(__name__)


class CommandFactory:
    registry: dict[str, "Type[Commands]"] = dict()

    @classmethod
    def from_dsn(cls, dsn: str, **connect_kwargs) -> "Commands":
        parsed_dsn = PydapperParseResult(dsn)
        return cls.registry[parsed_dsn.dbapi].connect(parsed_dsn, **connect_kwargs)

    @classmethod
    def from_connection(cls, connection: ConnectionType):
        connection_base_modules = {str(klass.__module__).split(".")[0] for klass in connection.__class__.__bases__}
        # this will happen if you have a connection that doesn't inherit from anything
        if connection_base_modules == {"builtins"}:
            connection_base_modules = {connection.__class__.__module__.split(".")[0]}
        registered_dbapi_modules = set(cls.registry.keys())
        supported_commands = connection_base_modules.intersection(registered_dbapi_modules)

        if not supported_commands:
            raise ValueError(f"No command support registered for {connection}")

        return cls.registry[supported_commands.pop()](connection)

    @classmethod
    def register(cls, name: str):
        def inner_wrapper(wrapped_class: "Type[Commands]"):
            CommandFactory.registry[name] = wrapped_class
            return wrapped_class

        return inner_wrapper


register = CommandFactory.register
using = CommandFactory.from_connection
connect = CommandFactory.from_dsn
