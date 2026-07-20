# Adapter registration

`pydapper.register_adapter()` is the single registration primitive for a DB-API adapter. An adapter registration
provides the command implementation for one or both modes and a synchronous `using_connection_predicate` used only
for automatic adapter selection of externally supplied connections through `using()` and `using_async()`.

There are two supported ways for a registration to happen, and both end in the same `register_adapter()` call:

* **Runtime registration** — application code calls `pydapper.register_adapter()` directly, as shown below. This
  remains fully supported and is process-local.
* **Installed entry points** — an installed distribution declares a `pydapper.adapters` entry point whose callback
  calls `register_adapter()`. pydapper discovers and invokes these callbacks lazily; see
  [Installing adapters as entry points](#installing-adapters-as-entry-points) below. pydapper's own eight
  first-party adapters are declared this way, so a plain `import pydapper` no longer initializes any adapter.

A runtime registration always takes precedence over an installed entry point of the same name for the rest of the
process; entry points are never the only legal way to register an adapter.

The example below is a complete third-party adapter: sync and async command classes, explicit capability
declarations, optional preparation hooks, and one `register_adapter()` call.

```python
from typing import ClassVar

import pydapper
from pydapper.capabilities import AdapterCapability
from pydapper.command_options import CommandOptions
from pydapper.commands import BaseSqlParamHandler
from pydapper.commands import Commands
from pydapper.commands import CommandsAsync
from pydapper.types import AsyncCursorType
from pydapper.types import CursorType


class AcmeCommands(Commands):
    # declare only capabilities this command class actually implements; empty is valid
    capabilities: ClassVar[frozenset[AdapterCapability]] = frozenset()

    @classmethod
    def connect(cls, parsed_dsn, **connect_kwargs):
        raise NotImplementedError

    def _prepare_cursor(self, cursor: CursorType, *, options: CommandOptions) -> None:
        ...  # configure the entered cursor once per command, e.g. driver-specific cursor state

    def _prepare_command(
        self, cursor: CursorType, handler: BaseSqlParamHandler, *, options: CommandOptions
    ) -> None:
        ...  # inspect handler.prepared_sql / handler.ordered_param_values before it executes


class AcmeCommandsAsync(CommandsAsync):
    capabilities: ClassVar[frozenset[AdapterCapability]] = frozenset()

    @classmethod
    async def connect_async(cls, parsed_dsn, **connect_kwargs):
        raise NotImplementedError

    async def _prepare_cursor_async(self, cursor: AsyncCursorType, *, options: CommandOptions) -> None:
        ...

    async def _prepare_command_async(
        self, cursor: AsyncCursorType, handler: BaseSqlParamHandler, *, options: CommandOptions
    ) -> None:
        ...


def is_acme_connection(connection: object) -> bool:
    module = type(connection).__module__
    return module == "acmedb" or module.startswith("acmedb.")


pydapper.register_adapter(
    "acmedb",
    commands=AcmeCommands,
    async_commands=AcmeCommandsAsync,
    using_connection_predicate=is_acme_connection,
)
```

`commands` must be a `Commands` subclass and `async_commands` must be a `CommandsAsync` subclass. Using the classes
and using connection predicate above, supply either one for a sync-only or async-only adapter, or both when the driver
supports both modes:

```python
pydapper.register_adapter(
    "acmedb-sync",
    commands=AcmeCommands,
    using_connection_predicate=is_acme_connection,
)

pydapper.register_adapter(
    "acmedb-async",
    async_commands=AcmeCommandsAsync,
    using_connection_predicate=is_acme_connection,
)
```

The using connection predicate receives the externally supplied connection object. Return `True` to make the adapter
eligible for automatic `using()` or `using_async()` selection, or `False` to leave it out. It is not a connection
health check and is not used by explicit `adapter=` selection or DSN-based `connect()` / `connect_async()` calls.

The registration name is exact and case-sensitive. It is also the DB-API part of a DSN, so registering `"acmedb"`
allows `connect()` to route an `acme+acmedb://...` DSN to that adapter. Names must be non-empty strings without
leading or trailing whitespace. A predicate is required and must be callable.

Registration is atomic and permanent for the process: supplying no command class, an invalid command class, an
invalid predicate, or an invalid capability declaration raises an error without changing the registry. When both
modes are supplied, both declarations are validated before the registry is touched, so an invalid declaration in
either mode fails the entire registration. A second registration of the same exact name always raises `ValueError`,
even if it appears identical. There is no replacement, priority, alias, or unregister API.

## Installing adapters as entry points

An installed distribution makes an adapter available without any application-side import or registration call by
declaring an entry point in the exact group:

```text
pydapper.adapters
```

pydapper's first-party adapters (`sqlite3`, `psycopg2`, `psycopg`, `aiopg`, `mysql`, `pymssql`, `oracledb`,
`google`) are declared through this same group by the `pydapper` distribution itself and satisfy the same callback
contract as a third-party adapter.

### Package metadata

A minimal, buildable third-party adapter package declares one entry point per adapter name. A complete
`pyproject.toml` for a package named `pydapper-acmedb`:

```toml
[build-system]
requires = ["setuptools>=61"]
build-backend = "setuptools.build_meta"

[project]
name = "pydapper-acmedb"
version = "1.0.0"
description = "AcmeDB adapter for pydapper"
requires-python = ">=3.10"
dependencies = ["pydapper"]

[project.entry-points."pydapper.adapters"]
acmedb = "pydapper_acmedb.plugin:register"
```

The entry-point *name* (`acmedb`) is the adapter name. The entry-point *value*
(`pydapper_acmedb.plugin:register`) must resolve to a synchronous, zero-argument callable.

### The registration callback

The value above points at a `register()` function in the package's `pydapper_acmedb/plugin.py` module:

```python
import pydapper

from .commands import AcmeCommands
from .commands import AcmeCommandsAsync


def is_acme_connection(connection: object) -> bool:
    module = type(connection).__module__
    return module == "acmedb" or module.startswith("acmedb.")


def register() -> None:
    pydapper.register_adapter(
        "acmedb",
        commands=AcmeCommands,
        async_commands=AcmeCommandsAsync,
        using_connection_predicate=is_acme_connection,
    )
```

`AcmeCommands` and `AcmeCommandsAsync` are ordinary command classes exactly like the runtime-registration example
above, defined in the package's `pydapper_acmedb/commands.py` module. The callback must:

* be synchronous and take zero arguments;
* call `pydapper.register_adapter()` exactly once, registering exactly the entry-point name;
* return `None`;
* not register at import time — pydapper invokes the callable explicitly, and importing the module must have no
  registration side effect; and
* not open a connection, perform network I/O, touch credentials, or start any async initialization. Command
  classes should keep importing their database driver lazily inside `connect()` / `connect_async()`, as the
  first-party adapters do, so loading a provider never imports an optional driver.

### Exact names

The entry-point name, the `register_adapter()` name, the explicit `adapter=` argument, and the DB-API component of
a DSN (`acme+acmedb://...`) are all the same exact, case-sensitive string. Nothing is normalized: case, hyphens,
and underscores are significant, so `AcmeDB`, `acmedb`, `acme-db`, and `acme_db` are four distinct adapter names.
The callback must register exactly the entry-point name.

A provider that breaks the contract fails with a clear `ValueError` identifying the adapter name and the provider
distribution: a non-callable entry-point value, a callback that requires arguments, an async callback, a non-`None`
return value, and a callback that registers zero names, more than one name, or a different name are all failures,
not near-misses.

### Loading behavior

Providers load lazily, and the two selection styles intentionally load differently:

* **DSN and explicit `adapter=` selection load only the requested provider.** `connect()`, `connect_async()`,
  `using(..., adapter=name)`, and `using_async(..., adapter=name)` resolve the exact name and load at most that one
  entry point. Explicit selection never calls any `using_connection_predicate`. A broken *unrelated* provider
  cannot affect these paths, because it is never loaded on them.
* **Automatic `using()` / `using_async()` selection loads every installed provider.** Without a name, pydapper
  cannot know which unloaded provider's predicate would match, so it loads all installed providers first — for
  both modes, regardless of the requested one — and only then filters by requested mode and evaluates predicates
  under the existing exactly-one-match rule. Automatic selection is therefore affected by an unrelated broken
  provider: it fails fast with an error identifying that provider rather than silently pretending the provider
  did not match.

The requested sync/async mode is checked *after* the provider loads: a provider owns its exact name even when it
supplies only one mode, so a mode mismatch raises the ordinary mode error and never falls back to a different
same-name provider.

### Precedence and duplicates

Name collisions resolve deterministically. Metadata enumeration order, package versions, and alphabetical order
never choose a winner:

1. An adapter already registered through `register_adapter()` at runtime wins for the process. The same-name entry
   point is never loaded.
2. When the name is not registered and the `pydapper` distribution itself declares it, the first-party provider
   wins over any external distribution using the same name. The ignored external distributions are recorded in a
   debug log without ever being imported.
3. When two or more *external* distributions declare the same otherwise-unregistered name, resolution raises
   `ValueError` before loading either candidate, names the adapter and every conflicting distribution, and asks
   you to remove the conflict.
4. Two first-party entries with the same name are a `pydapper` packaging error and fail deterministically.

### Failures, rollback, and caching

* Provider import, callback, and postcondition-validation failures raise `ValueError` identifying the adapter name
  and the provider distribution, with the original exception preserved as `__cause__` where one exists.
* A failed provider load rolls back its registry mutations: the private registry is restored to its pre-load
  state, so a broken provider never leaves a partial registration behind.
* A successfully loaded callback runs at most once per process — including under concurrent resolution of the same
  name — and later resolutions reuse its registration. A *failed* provider is not cached and remains retryable.
* The installed entry-point catalog is discovered lazily and cached for the process. Installed distributions are
  treated as static: installing a new adapter package after discovery has run requires a new process to be seen.
* All of this state is private. There is no public discover, refresh, reload, unload, list, or registry-access
  API, and no public adapter descriptor or plugin object.
* Provider errors and debug logs never include entry-point values, DSN credentials, or connection representations
  that could carry credentials.

## Declaring capabilities

Every command class carries an immutable class-level declaration of the optional behaviors it implements:

```python
capabilities: ClassVar[frozenset[AdapterCapability]] = frozenset()
```

`AdapterCapability` is a string enum exported from the package root (`pydapper.AdapterCapability`). A declaration
must be a `frozenset` whose members are all `AdapterCapability` values. `register_adapter()` rejects anything else
with `TypeError`: mutable sets, tuples, lists, raw strings, sets mixing enum members with other values, and
unrelated objects are all invalid. Arbitrary strings are not an extension mechanism; new capabilities are added to
the enum by pydapper when the corresponding feature ships.

Declare a capability only when the command class actually implements and tests the behavior. Native driver
potential is not sufficient. All first-party declarations are currently empty because no optional capability is
implemented yet; the feature tickets that implement transactions, timeouts, and the other optional behaviors own
enabling their flags.

Users inspect a selected command object with `supports()`:

```python
commands = pydapper.using(connection)
commands.supports(pydapper.AdapterCapability.TRANSACTIONS)  # False for every first-party adapter today
commands.supports("transactions")  # TypeError: not an AdapterCapability
```

Capabilities are declared per command class, so one adapter may declare different sync and async sets. Sync/async
mode support itself is intentionally **not** a capability flag: it is already represented unambiguously by which of
`commands` and `async_commands` a registration supplies, and duplicating it as a flag would allow contradictory
registrations.

### First-party adapters

| Registration name | Command class | Mode | Declared optional capabilities |
|---|---|---|---|
| `sqlite3` | `Sqlite3Commands` | sync | *(empty)* |
| `psycopg2` | `Psycopg2Commands` | sync | *(empty)* |
| `psycopg` | `Psycopg3Commands` | sync | *(empty)* |
| `psycopg` | `Psycopg3CommandsAsync` | async | *(empty)* |
| `aiopg` | `AiopgCommands` | async | *(empty)* |
| `mysql` | `MySqlConnectorPythonCommands` | sync | *(empty)* |
| `pymssql` | `PymssqlCommands` | sync | *(empty)* |
| `oracledb` | `OracledbCommands` | sync | *(empty)* |
| `google` | `GoogleBigqueryClientCommands` | sync | *(empty)* |

Empty sets are honest: they mean no optional capability is implemented yet, not that the underlying database lacks
the feature.

Adapters prove these contracts — the mandatory per-mode core behavior and, once implemented, each declared
capability — with the reusable conformance suite; see [Adapter conformance](adapter_conformance.md).

## Preparation hooks

Command classes may override four protected, documented adapter-author hooks. They are extension points for
adapter authors, not ordinary query APIs, and application code should never call them directly. Although their
names begin with an underscore, they are documented public extension points and are compatibility-sensitive under
the [compatibility policy](compatibility.md).

```python
def _prepare_cursor(self, cursor: CursorType, *, options: CommandOptions) -> None: ...

def _prepare_command(
    self, cursor: CursorType, handler: BaseSqlParamHandler, *, options: CommandOptions
) -> None: ...


async def _prepare_cursor_async(self, cursor: AsyncCursorType, *, options: CommandOptions) -> None: ...

async def _prepare_command_async(
    self, cursor: AsyncCursorType, handler: BaseSqlParamHandler, *, options: CommandOptions
) -> None: ...
```

The base implementations are no-ops. Every public command method — `execute`, `execute_scalar`, buffered and
unbuffered `query`, `query_multiple`, `query_first`, `query_first_or_default`, `query_single`,
`query_single_or_default`, and their async equivalents — invokes them in exactly this order for one acquired
cursor:

1. Options, parameter aliases, parameter shape, and placeholders are resolved and validated before any cursor is
   acquired.
2. The command acquires and enters exactly one cursor through the shared command-owned cursor lifecycle.
3. `_prepare_cursor*()` runs exactly once with the entered cursor.
4. For each SQL handler executed on that cursor, `_prepare_command*()` runs exactly once immediately before that
   handler executes, then the handler executes and results are fetched, validated, and mapped.
5. The cursor exits or closes through the shared lifecycle.

Cursor preparation runs once per acquired cursor; command preparation runs once per executed handler. For the
tuple-query `query_multiple()` API that means one `_prepare_cursor*()` call and one `_prepare_command*()` call per
query in the tuple. `execute()` with an empty parameter list performs no cursor or driver work, so neither hook
runs.

Both hooks always receive a normalized `CommandOptions` instance — never `None` — including when the caller omitted
`options=`. Unsupported non-default options still fail before cursor acquisition, so the hooks never observe them.

Hook restrictions and error behavior:

* Hooks may configure the entered cursor or driver command state, and may inspect the handler's `prepared_sql` and
  `ordered_param_values`.
* Hooks must not acquire, replace, enter, close, execute with, or fetch from a cursor.
* Hooks must not mutate `CommandOptions`; it is immutable.
* A hook may raise. A preparation failure is an active command error: the cursor is cleaned up through the shared
  lifecycle exactly once, command preparation and execution do not run after a cursor-preparation failure, and the
  original preparation exception propagates even if cleanup also fails or a native cursor `__exit__` returns a
  truthy value.

Drivers with unusual cursor-factory shapes should normalize the cursor factory by overriding `cursor()`, as the
psycopg3 async commands already do, rather than replacing cursor ownership inside a preparation hook.

## Selecting an adapter for an existing connection

When no adapter is named, `using()` and `using_async()` automatically consider the registrations that support the
requested mode and run every eligible using connection predicate. Exactly one matching predicate selects the adapter.

```python
commands = pydapper.using(connection)
async_commands = pydapper.using_async(async_connection)
```

No matching predicate raises `ValueError` with guidance to register an adapter or pass `adapter=`. More than one
match also raises `ValueError`, names the matching adapters, and asks the caller to choose explicitly. Registration
order never resolves an ambiguous match. If a predicate raises an exception, selection raises `ValueError` identifying
the adapter and preserves the original exception as its cause.

Using connection predicates should be synchronous and side-effect-free. In particular, they should inspect connection
metadata without importing optional drivers. Built-in predicates inspect the class MRO so ordinary driver subclasses
work, but arbitrary wrappers and proxies are intentionally not inferred.

## Explicit selection

For the `connection` and `async_connection` objects in the preceding example, pass a registered name to override
automatic selection directly:

```python
commands = pydapper.using(connection, adapter="acmedb")
async_commands = pydapper.using_async(async_connection, adapter="acmedb")
```

`adapter` is keyword-only. Explicit selection looks up the exact registration name, never calls its using connection
predicate, and returns the command class for the requested mode. It is the supported escape hatch for wrappers,
proxies, ambiguous connections, and objects automatic detection cannot recognize. An unknown name or a registered
adapter without the requested sync/async mode raises `ValueError`.

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

In v1, register the `AcmeCommands`, `AcmeCommandsAsync`, and `is_acme_connection` names defined above in one call:

```python
pydapper.register_adapter(
    "acmedb",
    commands=AcmeCommands,
    async_commands=AcmeCommandsAsync,
    using_connection_predicate=is_acme_connection,
)
```

This single call makes the adapter name, both supported modes, and its detection rule explicit.
