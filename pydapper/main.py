from __future__ import annotations

import inspect
import logging
import os
import threading
from collections.abc import Callable
from dataclasses import dataclass

from ._adapter_discovery import _AdapterProviderDescriptor
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


def _validate_registration_contents(
    commands: type[Commands] | None,
    async_commands: type[CommandsAsync] | None,
    using_connection_predicate: Callable[[object], bool],
) -> None:
    """Validate registration contents without touching the registry.

    Shared by register_adapter() and provider-load postcondition checks so both
    paths enforce one definition of a valid registration. Check order and
    exception types are part of register_adapter()'s public behavior.
    """
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
    if commands is not None:
        _validate_capability_declaration(commands, "commands")
    if async_commands is not None:
        _validate_capability_declaration(async_commands, "async_commands")


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
    # the provider load lock is reentrant, so provider callbacks registering from inside a
    # serialized load attempt re-enter it; a direct registration on another thread instead waits
    # for the attempt to finish and cannot be clobbered by its snapshot rollback
    with _provider_load_lock:
        if name in _adapter_registry:
            raise ValueError(f"Adapter {name!r} is already registered")
        # everything validates before the registry mutates so an invalid registration never leaves a
        # partially registered adapter behind
        _validate_registration_contents(commands, async_commands, using_connection_predicate)

        _adapter_registry[name] = _AdapterRegistration(
            name=name,
            commands=commands,
            async_commands=async_commands,
            using_connection_predicate=using_connection_predicate,
        )


# provider loading is serialized by one private reentrant lock so concurrent loads of the same
# provider cannot invoke a callback twice, observe partial registry state, or corrupt the success
# cache. register_adapter() serializes registry mutation on the same lock (reentrantly, since
# provider callbacks call it inside the loader's critical section), so a direct registration on
# another thread during a provider load waits for the attempt to finish instead of racing the
# snapshot and being silently dropped by rollback. Successful loads are cached per exact provider
# identity (name, distribution, entry-point value), never normalized, and failed attempts are never
# cached so they stay retryable. The registry, the success cache, and this lock binding are all
# restored by object identity after every attempt so a hostile callback cannot corrupt loader state
# by rebinding or mutating these module globals; the loader itself only ever acquires the lock
# bound in at definition time and never reads this global at call time. (A callback that rewrites
# this module's functions is beyond any in-process defense.)
_provider_load_lock = threading.RLock()
_loaded_provider_registrations: dict[tuple[str, str, str], _AdapterRegistration] = {}


def _provider_load_state_key(descriptor: _AdapterProviderDescriptor) -> tuple[str, str, str]:
    return (descriptor.name, descriptor.distribution, descriptor.entry_point.value)


def _provider_error_context(descriptor: _AdapterProviderDescriptor) -> str:
    return f"adapter provider {descriptor.name!r} (distribution {descriptor.distribution!r})"


def _restore_registry(registry: dict[str, _AdapterRegistration], snapshot: dict[str, _AdapterRegistration]) -> None:
    global _adapter_registry
    _adapter_registry = registry
    registry.clear()
    registry.update(snapshot)


def _restore_provider_cache(
    cache: dict[tuple[str, str, str], _AdapterRegistration],
    snapshot: dict[tuple[str, str, str], _AdapterRegistration],
) -> None:
    global _loaded_provider_registrations
    _loaded_provider_registrations = cache
    cache.clear()
    cache.update(snapshot)


def _restore_load_lock_binding(lock: threading.RLock) -> None:
    global _provider_load_lock
    _provider_load_lock = lock


def _verify_provider_registration_effect(
    descriptor: _AdapterProviderDescriptor,
    registry: dict[str, _AdapterRegistration],
    snapshot: dict[str, _AdapterRegistration],
) -> _AdapterRegistration:
    context = _provider_error_context(descriptor)
    if _adapter_registry is not registry:
        raise ValueError(f"Callback for {context} replaced the adapter registry itself")
    removed = [name for name in snapshot if name not in registry]
    replaced = [name for name in snapshot if name in registry and registry[name] is not snapshot[name]]
    if removed or replaced:
        raise ValueError(
            f"Callback for {context} removed or replaced existing adapter registrations "
            f"(removed: {removed!r}, replaced: {replaced!r})"
        )
    added = [name for name in registry if name not in snapshot]
    if not added:
        raise ValueError(
            f"Callback for {context} registered no adapter; expected exactly one registration named {descriptor.name!r}"
        )
    if added != [descriptor.name]:
        raise ValueError(
            f"Callback for {context} registered {added!r}; expected exactly one registration named {descriptor.name!r}"
        )
    if list(registry) != list(snapshot) + [descriptor.name]:
        raise ValueError(f"Callback for {context} reordered existing adapter registrations")
    registration = registry[descriptor.name]
    if not isinstance(registration, _AdapterRegistration):
        raise ValueError(
            f"Callback for {context} left an invalid registry record of type {type(registration).__name__} "
            f"for adapter {descriptor.name!r}"
        )
    if registration.name != descriptor.name:
        raise ValueError(
            f"Callback for {context} left a registration named {registration.name!r} "
            f"under adapter name {descriptor.name!r}"
        )
    try:
        _validate_registration_contents(
            registration.commands, registration.async_commands, registration.using_connection_predicate
        )
    except Exception as exc:
        raise ValueError(f"Callback for {context} produced an invalid registration for {descriptor.name!r}") from exc
    return registration


def _load_adapter_provider(
    descriptor: _AdapterProviderDescriptor,
    *,
    _lock: threading.RLock = _provider_load_lock,
) -> _AdapterRegistration:
    """Load one already-selected provider entry point and return its registration.

    The caller (a later resolution slice) is responsible for choosing the
    descriptor; this helper never consults the discovery catalog. The whole
    attempt — registry snapshot, EntryPoint.load(), callback invocation,
    postcondition validation, rollback, and success caching — is one serialized
    operation, so a concurrent caller observes either the completed success or
    the completed rollback. Any failure restores the registry and the loader
    success cache to their exact pre-attempt bindings and contents and stays
    retryable; a success is cached so the callback runs at most once per
    process, discarding any loader-state tampering by the callback.

    ``_lock`` defaults to the module lock captured at definition time — it is
    never read from the module global at call time — and exists as a parameter
    only so tests can inject an instrumented lock deterministically.
    """
    context = _provider_error_context(descriptor)
    key = _provider_load_state_key(descriptor)
    with _lock:
        registry = _adapter_registry
        cache = _loaded_provider_registrations
        cached = cache.get(key)
        if cached is not None:
            if registry.get(descriptor.name) is not cached:
                raise ValueError(f"Previously loaded {context} no longer matches the adapter registry")
            return cached

        if descriptor.name in registry:
            raise ValueError(
                f"Adapter {descriptor.name!r} is already registered; "
                f"refusing to load {context} over the existing registration"
            )

        lock_binding = _provider_load_lock
        snapshot = dict(registry)
        cache_snapshot = dict(cache)
        try:
            try:
                callback = descriptor.entry_point.load()
            except Exception as exc:
                raise ValueError(f"Failed to load {context}") from exc
            if not callable(callback):
                raise ValueError(f"Entry point for {context} must resolve to a callable, got {type(callback).__name__}")
            if inspect.iscoroutinefunction(callback) or inspect.isasyncgenfunction(callback):
                raise ValueError(f"Callback for {context} must be synchronous; async callbacks are not supported")
            try:
                result = callback()
            except Exception as exc:
                raise ValueError(f"Callback for {context} failed") from exc
            if inspect.isawaitable(result):
                close = getattr(result, "close", None)
                if callable(close):
                    close()
                raise ValueError(
                    f"Callback for {context} returned an awaitable; async provider initialization is not supported"
                )
            if result is not None:
                raise ValueError(f"Callback for {context} must return None, got {type(result).__name__}")
            registration = _verify_provider_registration_effect(descriptor, registry, snapshot)
        except BaseException:
            _restore_registry(registry, snapshot)
            _restore_provider_cache(cache, cache_snapshot)
            _restore_load_lock_binding(lock_binding)
            raise
        _restore_provider_cache(cache, cache_snapshot)
        _restore_load_lock_binding(lock_binding)
        cache[key] = registration
        return registration


def _reset_provider_load_state_for_tests(*, _lock: threading.RLock = _provider_load_lock) -> None:
    # clears only private loader success state; callers are responsible for separately
    # snapshotting/restoring the adapter registry itself. The lock is captured at definition
    # time for the same rebinding defense as _load_adapter_provider.
    with _lock:
        _loaded_provider_registrations.clear()


def parse_dsn(dsn: str | None) -> PydapperParseResult:
    if dsn is None:
        dsn = os.getenv("PYDAPPER_DSN")
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
