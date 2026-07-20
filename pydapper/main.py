from __future__ import annotations

import inspect
import logging
import os
import re
import threading
from collections import Counter
from collections.abc import Callable
from collections.abc import Iterable
from dataclasses import dataclass

from ._adapter_discovery import _AdapterProviderDescriptor
from ._adapter_discovery import _get_provider_catalog
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


# registry mutation and provider loading are serialized by one private reentrant lock so concurrent
# loads of the same provider cannot invoke a callback twice, observe partial registry state, or
# corrupt the success cache, and a direct register_adapter() on another thread during a provider
# load waits for the attempt to finish instead of racing the snapshot and being silently dropped by
# rollback (reentrancy is required because provider callbacks register from inside the loader's
# critical section). The lock is bound into every acquiring function at definition time and never
# acquired through this global at call time, so a hostile provider callback rebinding it cannot
# hand a concurrent caller a different lock; the loader reads the global only to snapshot it and
# restores the binding after every attempt so it keeps pointing at the real lock for any future
# call-time reader. (A callback that rewrites this module's functions is beyond any in-process
# defense.)
_provider_load_lock = threading.RLock()


def _register_adapter_under_lock(
    name: str,
    commands: type[Commands] | None,
    async_commands: type[CommandsAsync] | None,
    using_connection_predicate: Callable[[object], bool],
    *,
    _lock: threading.RLock = _provider_load_lock,
) -> None:
    with _lock:
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
    _register_adapter_under_lock(name, commands, async_commands, using_connection_predicate)


# successful loads are cached per exact provider identity (name, distribution, entry-point value),
# never normalized; failed attempts are never cached so they stay retryable. The success cache and
# the lock binding are restored by object identity after every load attempt, and the registry after
# every failed one, so a hostile callback cannot corrupt loader state by rebinding or mutating
# these module globals.
_loaded_provider_registrations: dict[tuple[str, str, str], _AdapterRegistration] = {}


def _provider_load_state_key(descriptor: _AdapterProviderDescriptor) -> tuple[str, str, str]:
    return (descriptor.name, descriptor.distribution, descriptor.entry_point.value)


def _provider_error_context(descriptor: _AdapterProviderDescriptor) -> str:
    return f"adapter provider {descriptor.name!r} (distribution {descriptor.distribution!r})"


def _restore_registry(registry: dict[str, _AdapterRegistration], snapshot: dict[str, _AdapterRegistration]) -> None:
    global _adapter_registry
    _adapter_registry = registry
    names = list(registry)
    snapshot_names = list(snapshot)
    if names[: len(snapshot_names)] == snapshot_names and all(
        registry[name] is record for name, record in snapshot.items()
    ):
        # the pre-existing entries are untouched and in order, so drop only what the attempt
        # appended; registry readers run without the load lock, and this path never lets them
        # observe a long-registered adapter as transiently missing
        for name in names[len(snapshot_names) :]:
            del registry[name]
        return
    # pre-existing entries were removed, replaced, or reordered: an exact restore requires a full
    # rebuild, briefly emptying the dict — only hostile callback tampering reaches this path
    registry.clear()
    registry.update(snapshot)


def _restore_provider_cache(
    cache: dict[tuple[str, str, str], _AdapterRegistration],
    snapshot: dict[tuple[str, str, str], _AdapterRegistration],
) -> None:
    global _loaded_provider_registrations
    _loaded_provider_registrations = cache
    if list(cache) == list(snapshot) and all(cache[key] is record for key, record in snapshot.items()):
        return
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
    retryable, so a failed callback may run again on a later attempt; a success
    is cached so a callback that has succeeded never runs again in this
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
                # close unstarted coroutines to avoid unawaited-coroutine warnings; a hostile
                # awaitable whose close attribute or call raises must not escape unwrapped
                cleanup_error: Exception | None = None
                try:
                    close = getattr(result, "close", None)
                    if callable(close):
                        close()
                except Exception as exc:
                    cleanup_error = exc
                raise ValueError(
                    f"Callback for {context} returned an awaitable; async provider initialization is not supported"
                ) from cleanup_error
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


# the pydapper distribution itself is the first-party provider of the stable adapter names
_FIRST_PARTY_DISTRIBUTION = "pydapper"


def _canonicalize_distribution_name(name: str) -> str:
    """Canonicalize a distribution project name the way packaging tools do.

    Applies PEP 503 name normalization with the standard library alone: runs of
    ``-``, ``_``, and ``.`` collapse to a single ``-`` and the result is
    lowercased, so ``PyDapper`` and ``PYDAPPER`` are recognized as the same
    project as ``pydapper``.

    This governs *distribution* identity only. Adapter entry-point names are
    never normalized: they stay exact and case-sensitive, so ``AcmeDB``,
    ``acmedb``, ``acme-db``, and ``acme_db`` remain four distinct adapters.
    """
    return re.sub(r"[-_.]+", "-", name).lower()


_CANONICAL_FIRST_PARTY_DISTRIBUTION = _canonicalize_distribution_name(_FIRST_PARTY_DISTRIBUTION)


def _is_first_party_provider(descriptor: _AdapterProviderDescriptor) -> bool:
    return _canonicalize_distribution_name(descriptor.distribution) == _CANONICAL_FIRST_PARTY_DISTRIBUTION


def _distribution_list(descriptors: Iterable[_AdapterProviderDescriptor]) -> str:
    """Render provider distributions deterministically for errors and debug logs.

    Sorted and de-duplicated so text never depends on metadata enumeration
    order, and annotated with a count whenever one distribution declares the
    same adapter name more than once (duplicate installs), so a conflict is
    never described as if it came from a single declaration.

    Only distribution names are rendered. Entry-point values are arbitrary
    installed metadata pydapper does not control, so they never reach an error
    message or a log record.
    """
    counts = Counter(descriptor.distribution for descriptor in descriptors)
    return ", ".join(
        f"{distribution!r} ({count} declarations)" if count > 1 else repr(distribution)
        for distribution, count in sorted(counts.items())
    )


def _select_provider_descriptor(
    name: str, providers: tuple[_AdapterProviderDescriptor, ...]
) -> _AdapterProviderDescriptor:
    """Choose the single provider that owns an exact adapter name.

    Pure: it reads no registry, loads no entry point, and never lets the order
    of ``providers`` decide a winner — a name is owned by the first-party
    provider, by exactly one external provider, or by nobody. ``providers`` must
    be non-empty; the caller reports unknown names.
    """
    first_party = [descriptor for descriptor in providers if _is_first_party_provider(descriptor)]
    external = [descriptor for descriptor in providers if not _is_first_party_provider(descriptor)]

    # validated before any candidate is handed to the loader, so a broken pydapper installation
    # fails instead of quietly loading one of its colliding entry points
    if len(first_party) > 1:
        raise ValueError(
            f"Adapter {name!r} is declared by {len(first_party)} first-party "
            f"{_FIRST_PARTY_DISTRIBUTION} entry points ({_distribution_list(first_party)}); "
            "this is a pydapper packaging/configuration error"
        )

    if first_party:
        if external:
            # metadata only: the ignored distributions are named but never imported or loaded, and
            # nothing here can carry a DSN, credential, or connection representation
            logger.debug(
                "Adapter %r is provided by the first-party %s distribution; ignoring same-name "
                "external providers from: %s",
                name,
                _FIRST_PARTY_DISTRIBUTION,
                _distribution_list(external),
            )
        return first_party[0]

    if len(external) > 1:
        # counted by declaration rather than by distribution: duplicate installs of one
        # distribution are a real conflict and must not be reported as a single declaration
        raise ValueError(
            f"Adapter {name!r} is declared by {len(external)} installed providers "
            f"({_distribution_list(external)}); uninstall or rename all but one provider "
            "so exactly one declares that adapter name"
        )

    return external[0]


def _resolve_adapter_registration(
    name: str,
    *,
    _lock: threading.RLock = _provider_load_lock,
) -> _AdapterRegistration:
    """Return the registration for an exact adapter name, loading one provider if needed.

    An adapter already present in the registry wins outright: ``register_adapter()``
    stays the highest-precedence, one-way runtime override and no catalog is
    discovered and no entry point is loaded for it. Otherwise the exact
    (case-sensitive, never normalized) name is looked up in the provider catalog,
    exactly one provider is selected by the precedence rules, and only that
    descriptor is loaded.

    The registry check, catalog selection, and load are one serialized operation
    under the same reentrant lock the loader uses, so a concurrent caller cannot
    slip a registration in between the check and the load and invoke a provider
    twice. ``_lock`` defaults to the module lock captured at definition time —
    never read from the module global at call time — and is threaded through to
    the loader so both halves share one lock; it is a parameter only so tests can
    inject an instrumented lock deterministically.
    """
    with _lock:
        if name in _adapter_registry:
            return _adapter_registry[name]

        providers = _get_provider_catalog().get(name)
        if not providers:
            raise ValueError(
                f"No registered or installed adapter has the exact name {name!r}; "
                "adapter names are case-sensitive and are never normalized"
            )

        return _load_adapter_provider(_select_provider_descriptor(name, providers), _lock=_lock)


def _load_all_adapter_providers(*, _lock: threading.RLock = _provider_load_lock) -> None:
    """Load every installed provider that does not already own a registered name.

    Private infrastructure for a later automatic-selection slice, which cannot
    know which unloaded provider's ``using_connection_predicate`` would match a
    connection until every provider has been loaded. Nothing calls this yet: the
    name-based public paths deliberately keep loading only the one provider they
    were asked for, so an unrelated broken provider still cannot break them.

    The pass is deterministic and mode-independent. Catalog names are walked in
    explicitly sorted exact-name order rather than trusting metadata enumeration
    or mapping order, names stay exact and case-sensitive, and sync-only,
    async-only, and dual-mode providers all load alike: nothing here filters by
    capability, evaluates a connection predicate, instantiates a command class,
    or opens a connection. An empty catalog is a successful no-op.

    A name already in the registry is skipped outright, so ``register_adapter()``
    stays the highest-precedence, one-way runtime override: its candidates are
    never selected, and a duplicate-provider conflict or a broken provider for a
    directly registered name therefore cannot fail the pass. Every other name
    goes through _resolve_adapter_registration(), so first-party precedence,
    duplicate detection, transactional rollback, and success caching keep exactly
    one implementation.

    Failure is fail-fast in sorted name order and is never globally rolled back:
    the resolver's ValueError propagates with its original cause intact, names
    that already loaded keep their registrations and loader-cache entries, and
    names sorted after the failure stay unloaded until a later attempt. The
    failing provider stays retryable under the existing loader rules, so
    repairing it and calling again resumes without invoking any already
    successful callback a second time.

    The whole pass — catalog acquisition included — runs under the same reentrant
    lock registration, loading, and exact-name resolution use, and that lock is
    threaded into the resolver so nested acquisition stays reentrant and a
    concurrent direct registration cannot interleave midway through the pass.
    ``_lock`` defaults to the module lock captured at definition time — never
    read from the module global at call time — and is a parameter only so tests
    can inject an instrumented lock deterministically.
    """
    with _lock:
        # materialized and sorted before the pass, so neither metadata enumeration order, mapping
        # insertion order, nor a registration made during the pass can change which names are
        # visited or in what order
        for name in sorted(_get_provider_catalog()):
            if name in _adapter_registry:
                continue
            _resolve_adapter_registration(name, _lock=_lock)


def parse_dsn(dsn: str | None) -> PydapperParseResult:
    if dsn is None:
        dsn = os.getenv("PYDAPPER_DSN")
    if dsn is None:  # pragma: no cover
        raise ValueError("dsn must be passed to connect or env var `PYDAPPER_DSN` must be set.")
    return PydapperParseResult(dsn)


def _get_sync_commands_class(name: str) -> type[Commands]:
    # every name-based public path (connect() via parsed_dsn.dbapi, and using(adapter=)) funnels
    # through here, so resolution is the one place that consults the registry, the catalog,
    # precedence, and the loader. The requested-mode check deliberately runs *after* resolution:
    # a provider owns its exact adapter name even when it supplies only one mode, so a mode
    # mismatch is a mode error, never a reason to look for a different same-name provider. It is
    # also not a failed load — the registration stays, and a later call for the supported mode
    # reuses it without invoking the provider again.
    registration = _resolve_adapter_registration(name)
    if registration.commands is None:
        raise ValueError(f"Adapter {name!r} does not support sync mode")
    return registration.commands


def _get_async_commands_class(name: str) -> type[CommandsAsync]:
    # same post-resolution mode ordering as the sync path
    registration = _resolve_adapter_registration(name)
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
