# Adapter registration

`pydapper.register_adapter()` is the single way to register a DB-API adapter. An adapter registration provides
the command implementation for one or both modes and a synchronous predicate used to recognize connection objects.

```python
import pydapper
from pydapper.commands import Commands
from pydapper.commands import CommandsAsync


class AcmeCommands(Commands):
    @classmethod
    def connect(cls, parsed_dsn, **connect_kwargs):
        raise NotImplementedError


class AcmeCommandsAsync(CommandsAsync):
    @classmethod
    async def connect_async(cls, parsed_dsn, **connect_kwargs):
        raise NotImplementedError


def can_handle_connection(connection: object) -> bool:
    module = type(connection).__module__
    return module == "acmedb" or module.startswith("acmedb.")


pydapper.register_adapter(
    "acmedb",
    commands=AcmeCommands,
    async_commands=AcmeCommandsAsync,
    can_handle_connection=can_handle_connection,
)
```

`commands` must be a `Commands` subclass and `async_commands` must be a `CommandsAsync` subclass. Using the classes
and predicate above, supply either one for a sync-only or async-only adapter, or both when the driver supports both
modes:

```python
pydapper.register_adapter(
    "acmedb-sync",
    commands=AcmeCommands,
    can_handle_connection=can_handle_connection,
)

pydapper.register_adapter(
    "acmedb-async",
    async_commands=AcmeCommandsAsync,
    can_handle_connection=can_handle_connection,
)
```

The registration name is exact and case-sensitive. It is also the DB-API part of a DSN, so registering `"acmedb"`
allows `connect()` to route an `acme+acmedb://...` DSN to that adapter. Names must be non-empty strings without
leading or trailing whitespace. A predicate is required and must be callable.

Registration is atomic and permanent for the process: supplying no command class, an invalid command class, or an
invalid predicate raises an error without changing the registry. A second registration of the same exact name always
raises `ValueError`, even if it appears identical. There is no replacement, priority, alias, or unregister API.

## Selecting an adapter for an existing connection

When no adapter is named, `using()` and `using_async()` automatically consider the registrations that support the
requested mode and run every eligible `can_handle_connection()` predicate. Exactly one matching predicate selects the
adapter.

```python
commands = pydapper.using(connection)
async_commands = pydapper.using_async(async_connection)
```

No matching predicate raises `ValueError` with guidance to register an adapter or pass `adapter=`. More than one
match also raises `ValueError`, names the matching adapters, and asks the caller to choose explicitly. Registration
order never resolves an ambiguous match. If a predicate raises an exception, selection raises `ValueError` identifying
the adapter and preserves the original exception as its cause.

Predicates should be synchronous and side-effect-free. In particular, they should inspect connection metadata without
importing optional drivers. Built-in predicates inspect the class MRO so ordinary driver subclasses work, but arbitrary
wrappers and proxies are intentionally not inferred.

## Explicit selection

For the `connection` and `async_connection` objects in the preceding example, pass a registered name to override
automatic selection directly:

```python
commands = pydapper.using(connection, adapter="acmedb")
async_commands = pydapper.using_async(async_connection, adapter="acmedb")
```

`adapter` is keyword-only. Explicit selection looks up the exact registration name, never calls its predicate, and
returns the command class for the requested mode. It is the supported escape hatch for wrappers, proxies, ambiguous
connections, and objects automatic detection cannot recognize. An unknown name or a registered adapter without the
requested sync/async mode raises `ValueError`.

## Migrating from decorator registration

The following is the removed v0 decorator pattern, shown only to aid migration. Do not use it in v1:

```python
@register("acmedb")
class AcmeCommands(Commands):
    ...


@register_async("acmedb")
class AcmeCommandsAsync(CommandsAsync):
    ...
```

In v1, register the `AcmeCommands`, `AcmeCommandsAsync`, and `can_handle_connection` names defined above in one call:

```python
pydapper.register_adapter(
    "acmedb",
    commands=AcmeCommands,
    async_commands=AcmeCommandsAsync,
    can_handle_connection=can_handle_connection,
)
```

This single call makes the adapter name, both supported modes, and its detection rule explicit.
