from __future__ import annotations

import logging
import os
from collections.abc import Callable
from dataclasses import dataclass

from ._context import _AwaitableAsyncContextManager
from .capabilities import AdapterCapability
from .commands import BaseCommands
from .commands import Commands
from .commands import CommandsAsync
from .dsn_parser import PydapperParseResult
from .types import AsyncConnectionType
from .types import ConnectionType

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class _AdapterRegistration:
    name: str
    commands: type[Commands] | None
    async_commands: type[CommandsAsync] | None
    using_connection_predicate: Callable[[object], bool]


_adapter_registry: dict[str, _AdapterRegistration] = {}


def _validate_capability_declaration(command_class: type[BaseCommands], argument_name: str) -> None:
    declared = command_class.capabilities
    if not isinstance(declared, frozenset):
        raise TypeError(
            f"{argument_name}.capabilities must be a frozenset of AdapterCapability members, "
            f"got {type(declared).__name__}"
        )
    for member in declared:
        if not isinstance(member, AdapterCapability):
            raise TypeError(
                f"{argument_name}.capabilities must contain only AdapterCapability members, "
                f"got {type(member).__name__}"
            )


def register_adapter(
    name: str,
    *,
    commands: type[Commands] | None = None,
    async_commands: type[CommandsAsync] | None = None,
    using_connection_predicate: Callable[[object], bool],
) -> None:
    """Register command implementations for a DB-API adapter.

    Registration is intentionally one-way: an adapter name may only be registered
    once so import order cannot silently replace a command implementation. The
    using_connection_predicate is used only for automatic connection selection.

    Each supplied command class must declare ``capabilities`` as a frozenset of
    AdapterCapability members. Declarations are validated per mode before the
    registry is touched, so an invalid declaration fails the whole registration
    without mutating the registry.
    """
    if not isinstance(name, str):
        raise TypeError("Adapter name must be a string")
    if not name or name != name.strip():
        raise ValueError("Adapter name must be non-empty and have no surrounding whitespace")
    if name in _adapter_registry:
        raise ValueError(f"Adapter {name!r} is already registered")
    if commands is None and async_commands is None:
        raise ValueError("At least one sync or async command class is required")
    if commands is not None and (not isinstance(commands, type) or not issubclass(commands, Commands)):
        raise TypeError("commands must be a Commands subclass")
    if async_commands is not None and (
        not isinstance(async_commands, type) or not issubclass(async_commands, CommandsAsync)
    ):
        raise TypeError("async_commands must be a CommandsAsync subclass")
    if not callable(using_connection_predicate):
        raise TypeError("using_connection_predicate must be callable")
    # both declarations must validate before the registry mutates so an invalid mode never leaves a
    # partially registered adapter behind
    if commands is not None:
        _validate_capability_declaration(commands, "commands")
    if async_commands is not None:
        _validate_capability_declaration(async_commands, "async_commands")

    _adapter_registry[name] = _AdapterRegistration(
        name=name,
        commands=commands,
        async_commands=async_commands,
        using_connection_predicate=using_connection_predicate,
    )


def parse_dsn(dsn: str | None) -> PydapperParseResult:
    dsn = dsn or os.getenv("PYDAPPER_DSN")
    if dsn is None:  # pragma: no cover
        raise ValueError("dsn must be passed to connect or env var `PYDAPPER_DSN` must be set.")
    return PydapperParseResult(dsn)


def _get_registration(name: str, mode: str) -> _AdapterRegistration:
    try:
        return _adapter_registry[name]
    except KeyError:
        raise ValueError(f"No adapter named {name!r} is registered for {mode} mode") from None


def _get_sync_commands_class(name: str) -> type[Commands]:
    registration = _get_registration(name, "sync")
    if registration.commands is None:
        raise ValueError(f"Adapter {name!r} does not support sync mode")
    return registration.commands


def _get_async_commands_class(name: str) -> type[CommandsAsync]:
    registration = _get_registration(name, "async")
    if registration.async_commands is None:
        raise ValueError(f"Adapter {name!r} does not support async mode")
    return registration.async_commands


def _select_registration(connection: object, mode: str) -> _AdapterRegistration:
    matches: list[_AdapterRegistration] = []

    for registration in sorted(_adapter_registry.values(), key=lambda item: item.name):
        if mode == "sync" and registration.commands is None:
            continue
        if mode == "async" and registration.async_commands is None:
            continue

        try:
            matches_connection = registration.using_connection_predicate(connection)
        except Exception as exc:
            raise ValueError(
                f"Adapter {registration.name!r} failed while checking a connection for {mode} mode"
            ) from exc

        if matches_connection:
            matches.append(registration)

    if len(matches) == 1:
        return matches[0]
    if not matches:
        raise ValueError(
            f"No registered {mode} adapter can handle {connection!r}; "
            "register an adapter or pass adapter= explicitly"
        )

    matching_names = ", ".join(registration.name for registration in matches)
    raise ValueError(
        f"Multiple registered {mode} adapters can handle {connection!r}: {matching_names}. Pass adapter= explicitly"
    )


def _select_sync_commands_class(connection: object) -> type[Commands]:
    registration = _select_registration(connection, "sync")
    assert registration.commands is not None
    return registration.commands


def _select_async_commands_class(connection: object) -> type[CommandsAsync]:
    registration = _select_registration(connection, "async")
    assert registration.async_commands is not None
    return registration.async_commands


class CommandFactory:
    @classmethod
    def from_dsn(cls, dsn: str | None = None, **connect_kwargs) -> Commands:
        parsed_dsn = parse_dsn(dsn)
        return _get_sync_commands_class(parsed_dsn.dbapi).connect(parsed_dsn, **connect_kwargs)

    @classmethod
    def from_dsn_async(
        cls, dsn: str | None = None, **connect_kwargs
    ) -> _AwaitableAsyncContextManager[CommandsAsync, CommandsAsync]:
        parsed_dsn = parse_dsn(dsn)
        commands_class = _get_async_commands_class(parsed_dsn.dbapi)
        return _AwaitableAsyncContextManager(commands_class.connect_async(parsed_dsn, **connect_kwargs))

    @classmethod
    def from_connection(cls, connection: ConnectionType, *, adapter: str | None = None) -> Commands:
        commands_class = (
            _get_sync_commands_class(adapter) if adapter is not None else _select_sync_commands_class(connection)
        )
        return commands_class(connection)

    @classmethod
    def from_connection_async(cls, connection: AsyncConnectionType, *, adapter: str | None = None) -> CommandsAsync:
        commands_class = (
            _get_async_commands_class(adapter) if adapter is not None else _select_async_commands_class(connection)
        )
        return commands_class(connection)


def connect(dsn: str | None = None, **connect_kwargs) -> Commands:
    return CommandFactory.from_dsn(dsn, **connect_kwargs)


def connect_async(
    dsn: str | None = None, **connect_kwargs
) -> _AwaitableAsyncContextManager[CommandsAsync, CommandsAsync]:
    return CommandFactory.from_dsn_async(dsn, **connect_kwargs)


def using(connection: ConnectionType, *, adapter: str | None = None) -> Commands:
    return CommandFactory.from_connection(connection, adapter=adapter)


def using_async(connection: AsyncConnectionType, *, adapter: str | None = None) -> CommandsAsync:
    return CommandFactory.from_connection_async(connection, adapter=adapter)
