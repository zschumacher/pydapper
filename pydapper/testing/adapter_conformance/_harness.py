"""Typed harness base classes adapter authors implement to run conformance profiles.

A harness supplies factories, per-case dataset isolation, and the narrow, documented
dialect knobs. It never owns behavioral assertions and has no channel to declare a
case passed: every assertion belongs to the framework runner.

Sync-only adapters implement :class:`SyncAdapterHarness` only; async-only adapters
implement :class:`AsyncAdapterHarness` only. Neither base requires fields from the
other mode. A dual-mode adapter implements both and must pass both mandatory
profiles independently.
"""

from typing import Any
from typing import ClassVar
from typing import Literal
from typing import Mapping
from typing import Optional
from typing import Type

from pydapper.commands import Commands
from pydapper.commands import CommandsAsync

#: Documented per-mode dialect knobs shared by both harness bases:
#:
#: ``table_name``
#:     Name (optionally schema/dataset qualified) of the canonical conformance table.
#: ``column_case``
#:     ``"lower"`` (default) or ``"upper"`` for dialects that fold unquoted
#:     identifiers to uppercase (for example Oracle).
#: ``supports_empty_strings``
#:     ``False`` only for dialects that cannot store an empty string distinctly from
#:     SQL NULL (for example Oracle). Row 2's label then seeds as ``"blank"`` and the
#:     empty-string sub-assertion is replaced by the documented fallback value.
#: ``strict_rowcounts``
#:     ``False`` only for drivers/emulators whose DML rowcount reporting is
#:     documented as unreliable (for example the BigQuery emulator). Rowcount cases
#:     still execute and must return an ``int``; only exact-count equality is relaxed.
#: ``sql_overrides``
#:     Statement-id -> SQL overrides for the narrow cases where portable SQL is
#:     insufficient. Overrides still use pydapper ``?name?`` placeholders.


class SyncAdapterHarness:
    """Harness contract for running ``core-sync`` against one concrete sync adapter.

    Required class attributes / overrides:

    * ``adapter_name`` — the registered adapter name (exact, case-sensitive).
    * ``command_class`` — the declared concrete :class:`~pydapper.commands.Commands`
      subclass for the sync mode.
    * ``connect_dsn`` — a DSN that safely reaches an isolated test database through
      ``pydapper.connect()``.
    * :meth:`create_commands` — return a fresh command instance over a fresh
      connection with the canonical dataset freshly seeded (see
      ``pydapper.testing.adapter_conformance.CONFORMANCE_ROWS`` /
      ``seed_rows()``). Called once per case; cases never share state.
    * :meth:`teardown_commands` — release everything :meth:`create_commands` built.
    """

    adapter_name: ClassVar[Optional[str]] = None
    command_class: ClassVar[Optional[Type[Commands]]] = None
    connect_dsn: ClassVar[Optional[str]] = None
    connect_kwargs: ClassVar[Mapping[str, Any]] = {}
    table_name: ClassVar[str] = "pydapper_conformance"
    column_case: ClassVar[Literal["lower", "upper"]] = "lower"
    supports_empty_strings: ClassVar[bool] = True
    strict_rowcounts: ClassVar[bool] = True
    sql_overrides: ClassVar[Mapping[str, str]] = {}

    def create_commands(self) -> Commands:
        """Return a fresh, isolated command instance with the dataset freshly seeded."""
        raise NotImplementedError

    def teardown_commands(self, commands: Commands) -> None:
        """Release the connection and any per-case resources behind ``commands``."""
        raise NotImplementedError

    def recover_after_error(self, commands: Commands) -> None:
        """Perform backend recovery required after an intentionally failed command.

        Called by the runner after cases that intentionally fail a command, before
        the same command instance is reused. The default is a no-op.
        """


class AsyncAdapterHarness:
    """Harness contract for running ``core-async`` against one concrete async adapter.

    Required class attributes / overrides mirror :class:`SyncAdapterHarness` with
    awaitable factories. ``cursor_factory_style`` additionally tells the framework
    which instrumented connection shape the adapter's ``cursor()`` contract expects:

    * ``"awaitable"`` — ``connection.cursor()`` returns an awaitable (the
      :class:`~pydapper.commands.CommandsAsync` base contract, e.g. aiopg).
    * ``"synchronous"`` — ``connection.cursor()`` returns the cursor directly and the
      command class normalizes it (e.g. psycopg3 async).
    """

    adapter_name: ClassVar[Optional[str]] = None
    command_class: ClassVar[Optional[Type[CommandsAsync]]] = None
    connect_dsn: ClassVar[Optional[str]] = None
    connect_kwargs: ClassVar[Mapping[str, Any]] = {}
    table_name: ClassVar[str] = "pydapper_conformance"
    column_case: ClassVar[Literal["lower", "upper"]] = "lower"
    supports_empty_strings: ClassVar[bool] = True
    strict_rowcounts: ClassVar[bool] = True
    sql_overrides: ClassVar[Mapping[str, str]] = {}
    cursor_factory_style: ClassVar[Literal["awaitable", "synchronous"]] = "awaitable"

    async def create_commands(self) -> CommandsAsync:
        """Return a fresh, isolated async command instance with the dataset freshly seeded."""
        raise NotImplementedError

    async def teardown_commands(self, commands: CommandsAsync) -> None:
        """Release the connection and any per-case resources behind ``commands``."""
        raise NotImplementedError

    async def recover_after_error(self, commands: CommandsAsync) -> None:
        """Perform backend recovery required after an intentionally failed command."""
