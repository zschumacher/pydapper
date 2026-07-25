"""Case execution contexts and framework-owned assertion helpers.

Every behavioral assertion lives in the framework: case implementations call
:meth:`check`/:meth:`fail`/:meth:`expect_raises`, which raise
:class:`~pydapper.testing.adapter_conformance._results.CaseCheckError` converted by
the runner into failed results. Harness- or adapter-provided code has no channel to
declare a case passed.

``create_commands`` additionally wraps the harness's *own* factory call — and only
that call, never the framework's own validation or bookkeeping around it — in
:class:`~pydapper.testing.adapter_conformance._results.HarnessSetupError`, so a
harness that cannot build a connection or seed the canonical dataset is reported as a
broken harness instead of as many identical-looking adapter failures.
"""

from typing import TYPE_CHECKING
from typing import Any
from typing import List
from typing import Mapping
from typing import NoReturn
from typing import Optional
from typing import Sequence
from typing import Tuple
from typing import Type
from typing import Union
from typing import cast

from pydapper.capabilities import AdapterCapability
from pydapper.commands import Commands
from pydapper.commands import CommandsAsync

from ._harness import AsyncAdapterHarness
from ._harness import SyncAdapterHarness
from ._instrumentation import CursorScript
from ._instrumentation import RecordedEvent
from ._instrumentation import RecordingAsyncConnection
from ._instrumentation import RecordingConnection
from ._instrumentation import RecordingLog
from ._instrumentation import SynchronousCursorRecordingAsyncConnection
from ._results import CaseCheckError
from ._results import HarnessDefinitionError
from ._results import HarnessSetupError
from ._sqlspec import expected_column
from ._sqlspec import expected_row_dict
from ._sqlspec import render_statement
from ._sqlspec import seed_rows

if TYPE_CHECKING:
    from pydapper.types import AsyncConnectionType
    from pydapper.types import ConnectionType

    from ._profiles import ConformanceProfile


class ExpectedRaise:
    """Context manager asserting that a block raises one of the expected types.

    The caught exception is exposed as :attr:`exception` for structured-attribute
    assertions. A missing exception fails the case; an unexpected exception type
    propagates and the runner records it as the case's cause.
    """

    def __init__(self, exc_types: Tuple[Type[BaseException], ...], description: str) -> None:
        self._exc_types = exc_types
        self._description = description
        self.exception: Optional[BaseException] = None

    def __enter__(self) -> "ExpectedRaise":
        return self

    def __exit__(self, exc_type: Any, exc_val: Any, exc_tb: Any) -> bool:
        if exc_type is None:
            names = ", ".join(t.__name__ for t in self._exc_types)
            raise CaseCheckError(f"{self._description}: expected {names} to be raised, but nothing was raised")
        if issubclass(exc_type, self._exc_types):
            self.exception = exc_val
            return True
        return False


class _BaseCaseContext:
    """State and helpers shared by the sync and async case contexts."""

    def __init__(self, profile_id: str, case_id: str, catalog: Mapping[AdapterCapability, "ConformanceProfile"]):
        self.profile_id = profile_id
        self.case_id = case_id
        self.capability_catalog = catalog

    # -- framework-owned assertions -------------------------------------------------

    def check(self, condition: bool, message: str) -> None:
        if not condition:
            raise CaseCheckError(message)

    def fail(self, message: str, cause: Optional[BaseException] = None) -> NoReturn:
        raise CaseCheckError(message, cause=cause)

    def expect_raises(self, *exc_types: Type[BaseException], description: str = "") -> ExpectedRaise:
        return ExpectedRaise(exc_types, description or f"case {self.case_id!r}")

    def check_event_order(self, log: RecordingLog, expected_kinds: Sequence[str]) -> None:
        self.check(
            log.kinds() == tuple(expected_kinds),
            f"expected driver interaction order {tuple(expected_kinds)!r}, observed {log.kinds()!r}",
        )

    def check_single_cursor_lifecycle(self, connection: Any) -> None:
        self.check(
            connection.cursor_calls == 1, f"expected exactly one cursor acquisition, saw {connection.cursor_calls}"
        )
        recorder = connection.recorders[0]
        cleanup_calls = recorder.exit_calls + recorder.close_calls
        self.check(cleanup_calls == 1, f"expected exactly one cursor cleanup, saw {cleanup_calls}")

    def missing_field(self, field_name: str) -> HarnessDefinitionError:
        return HarnessDefinitionError(self.profile_id, self.case_id, field_name)

    # -- harness field access -------------------------------------------------------

    def _require_attr(self, harness: Any, name: str) -> Any:
        value = getattr(harness, name, None)
        if value is None:
            raise self.missing_field(name)
        return value

    def _require_override(self, harness: Any, base_class: type, name: str) -> None:
        if getattr(type(harness), name, None) is getattr(base_class, name):
            raise self.missing_field(name)


class SyncCaseContext(_BaseCaseContext):
    """Execution context handed to every ``core-sync`` case implementation."""

    def __init__(
        self,
        harness: SyncAdapterHarness,
        profile_id: str,
        case_id: str,
        catalog: Mapping[AdapterCapability, "ConformanceProfile"],
    ) -> None:
        super().__init__(profile_id, case_id, catalog)
        self.harness = harness
        self.created_commands: List[Commands] = []

    # -- harness surface ------------------------------------------------------------

    @property
    def adapter_name(self) -> str:
        return self._require_attr(self.harness, "adapter_name")

    @property
    def command_class(self) -> Type[Commands]:
        return self._require_attr(self.harness, "command_class")

    @property
    def connect_dsn(self) -> str:
        return self._require_attr(self.harness, "connect_dsn")

    def create_commands(self) -> Commands:
        self._require_override(self.harness, SyncAdapterHarness, "create_commands")
        self._require_override(self.harness, SyncAdapterHarness, "teardown_commands")
        try:
            commands = self.harness.create_commands()
        except Exception as error:  # noqa: BLE001 - re-raised as a structured harness setup failure
            raise HarnessSetupError(self.profile_id, self.case_id, error) from error
        self.created_commands.append(commands)
        return commands

    def recover(self, commands: Commands) -> None:
        self.harness.recover_after_error(commands)

    # -- canonical SQL and data -----------------------------------------------------

    def sql(self, statement_id: str) -> str:
        return render_statement(statement_id, self.harness.table_name, self.harness.sql_overrides)

    def col(self, name: str) -> str:
        return expected_column(name, self.harness.column_case)

    def seeded_rows(self) -> Tuple[Tuple[Any, ...], ...]:
        return seed_rows(self.harness.supports_empty_strings)

    def expected_row(self, row: Tuple[Any, ...]) -> Mapping[str, Any]:
        return expected_row_dict(row, self.harness.column_case)

    # -- instrumentation ------------------------------------------------------------

    def recording_connection(
        self,
        scripts: Union[CursorScript, Sequence[CursorScript], None] = None,
        cursor_style: str = "context",
        commit_error: Optional[BaseException] = None,
        rollback_error: Optional[BaseException] = None,
    ) -> RecordingConnection:
        return RecordingConnection(
            scripts, cursor_style=cursor_style, commit_error=commit_error, rollback_error=rollback_error
        )

    def instrumented_commands(self, connection: RecordingConnection) -> Commands:
        return self.command_class(cast("ConnectionType", connection))  # type: ignore[abstract]

    def install_hook_recorder(self, commands: Commands, log: RecordingLog) -> None:
        original_prepare_cursor = type(commands)._prepare_cursor
        original_prepare_command = type(commands)._prepare_command

        def prepare_cursor(cursor: Any, *, options: Any) -> None:
            log.add(RecordedEvent(kind="prepare_cursor", detail=(cursor, options)))
            original_prepare_cursor(commands, cursor, options=options)

        def prepare_command(cursor: Any, handler: Any, *, options: Any) -> None:
            log.add(RecordedEvent(kind="prepare_command", detail=(cursor, handler, options)))
            original_prepare_command(commands, cursor, handler, options=options)

        # instance attributes shadow the class methods for this command object only,
        # so the concrete class's own hook implementations still run via delegation
        commands._prepare_cursor = prepare_cursor  # type: ignore[method-assign]
        commands._prepare_command = prepare_command  # type: ignore[method-assign]


class AsyncCaseContext(_BaseCaseContext):
    """Execution context handed to every ``core-async`` case implementation."""

    def __init__(
        self,
        harness: AsyncAdapterHarness,
        profile_id: str,
        case_id: str,
        catalog: Mapping[AdapterCapability, "ConformanceProfile"],
    ) -> None:
        super().__init__(profile_id, case_id, catalog)
        self.harness = harness
        self.created_commands: List[CommandsAsync] = []

    # -- harness surface ------------------------------------------------------------

    @property
    def adapter_name(self) -> str:
        return self._require_attr(self.harness, "adapter_name")

    @property
    def command_class(self) -> Type[CommandsAsync]:
        return self._require_attr(self.harness, "command_class")

    @property
    def connect_dsn(self) -> str:
        return self._require_attr(self.harness, "connect_dsn")

    async def create_commands(self) -> CommandsAsync:
        self._require_override(self.harness, AsyncAdapterHarness, "create_commands")
        self._require_override(self.harness, AsyncAdapterHarness, "teardown_commands")
        try:
            commands = await self.harness.create_commands()
        except Exception as error:  # noqa: BLE001 - re-raised as a structured harness setup failure
            raise HarnessSetupError(self.profile_id, self.case_id, error) from error
        self.created_commands.append(commands)
        return commands

    async def recover(self, commands: CommandsAsync) -> None:
        await self.harness.recover_after_error(commands)

    # -- canonical SQL and data -----------------------------------------------------

    def sql(self, statement_id: str) -> str:
        return render_statement(statement_id, self.harness.table_name, self.harness.sql_overrides)

    def col(self, name: str) -> str:
        return expected_column(name, self.harness.column_case)

    def seeded_rows(self) -> Tuple[Tuple[Any, ...], ...]:
        return seed_rows(self.harness.supports_empty_strings)

    def expected_row(self, row: Tuple[Any, ...]) -> Mapping[str, Any]:
        return expected_row_dict(row, self.harness.column_case)

    # -- instrumentation ------------------------------------------------------------

    def recording_connection(
        self,
        scripts: Union[CursorScript, Sequence[CursorScript], None] = None,
        cursor_style: str = "context",
        close_style: str = "sync",
    ) -> RecordingAsyncConnection:
        if self.harness.cursor_factory_style == "synchronous":
            return SynchronousCursorRecordingAsyncConnection(
                scripts, cursor_style=cursor_style, close_style=close_style
            )
        return RecordingAsyncConnection(scripts, cursor_style=cursor_style, close_style=close_style)

    def instrumented_commands(self, connection: RecordingAsyncConnection) -> CommandsAsync:
        return self.command_class(cast("AsyncConnectionType", connection))  # type: ignore[abstract]

    def install_hook_recorder(self, commands: CommandsAsync, log: RecordingLog) -> None:
        original_prepare_cursor = type(commands)._prepare_cursor_async
        original_prepare_command = type(commands)._prepare_command_async

        async def prepare_cursor_async(cursor: Any, *, options: Any) -> None:
            log.add(RecordedEvent(kind="prepare_cursor", detail=(cursor, options)))
            await original_prepare_cursor(commands, cursor, options=options)

        async def prepare_command_async(cursor: Any, handler: Any, *, options: Any) -> None:
            log.add(RecordedEvent(kind="prepare_command", detail=(cursor, handler, options)))
            await original_prepare_command(commands, cursor, handler, options=options)

        commands._prepare_cursor_async = prepare_cursor_async  # type: ignore[method-assign]
        commands._prepare_command_async = prepare_command_async  # type: ignore[method-assign]
