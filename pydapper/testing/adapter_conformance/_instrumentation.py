"""Framework-owned, driver-neutral recording and fault-injection instrumentation.

Interaction-level conformance cases instantiate the adapter's real concrete command
class around these connections so lifecycle behavior — cursor acquisition counts,
enter/exit pairing, ``close()``/``aclose()``, call ordering, bounded fetches, error
precedence, and absence of driver work — is observed rather than inferred from
returned values.

Everything here is standard library only and embeds no first-party fixtures. The
event log is owned by the framework; adapter- or harness-provided code has no API to
mark a case as passed.
"""

from dataclasses import dataclass
from dataclasses import field
from typing import Any
from typing import List
from typing import Optional
from typing import Sequence
from typing import Tuple
from typing import Union


@dataclass(frozen=True)
class RecordedEvent:
    """One observed interaction between a command class and the instrumented driver."""

    kind: str
    sql: Optional[str] = None
    params: Optional[Any] = None
    size: Optional[int] = None
    on_entered: Optional[bool] = None
    exc_type: Optional[type] = None
    exc_value: Optional[BaseException] = field(default=None, repr=False)
    tb_is_active: Optional[bool] = None
    detail: Optional[Any] = field(default=None, repr=False)


class RecordingLog:
    """An append-only, framework-owned timeline shared by one instrumented run."""

    def __init__(self) -> None:
        self.events: List[RecordedEvent] = []

    def add(self, event: RecordedEvent) -> None:
        self.events.append(event)

    def kinds(self) -> Tuple[str, ...]:
        return tuple(event.kind for event in self.events)

    def count(self, kind: str) -> int:
        return sum(1 for event in self.events if event.kind == kind)

    def first(self, kind: str) -> Optional[RecordedEvent]:
        for event in self.events:
            if event.kind == kind:
                return event
        return None

    def of_kind(self, kind: str) -> Tuple[RecordedEvent, ...]:
        return tuple(event for event in self.events if event.kind == kind)


@dataclass
class CursorScript:
    """Scripted results and fault injection for one instrumented cursor.

    ``rows``/``columns`` describe the result set every ``execute`` produces.
    ``*_error`` fields inject a failure at the named interaction. ``exit_result``
    probes truthy context-manager exits. ``supports_fetchmany`` controls whether the
    cursor exposes ``fetchmany`` (which changes the bounded single-row fetch path).
    """

    columns: Tuple[str, ...] = ("id", "label")
    rows: Tuple[Tuple[Any, ...], ...] = ((1, "alpha"), (2, "beta"))
    rowcount: int = 1
    rowcount_from_executemany_length: bool = True
    execute_error: Optional[BaseException] = None
    executemany_error: Optional[BaseException] = None
    fetchone_error: Optional[BaseException] = None
    fetchall_error: Optional[BaseException] = None
    fetchmany_error: Optional[BaseException] = None
    close_error: Optional[BaseException] = None
    exit_error: Optional[BaseException] = None
    exit_result: Any = False
    supports_fetchmany: bool = True


class CursorRecorder:
    """Shared recording core behind every instrumented cursor facade."""

    def __init__(self, script: CursorScript, log: RecordingLog) -> None:
        self.script = script
        self.log = log
        self.pending_rows: List[Tuple[Any, ...]] = []
        self.rowcount = -1
        self.close_calls = 0
        self.enter_calls = 0
        self.exit_calls = 0
        self.exit_args: List[Tuple[Any, Any, Any]] = []

    @property
    def description(self) -> Tuple[Tuple[Any, ...], ...]:
        return tuple((name, None, None, None, None, None, None) for name in self.script.columns)

    def _record(self, kind: str, on_entered: Optional[bool], **payload: Any) -> None:
        self.log.add(RecordedEvent(kind=kind, on_entered=on_entered, **payload))

    def do_execute(self, sql: str, parameters: Any, on_entered: bool) -> None:
        self._record("execute", on_entered, sql=sql, params=parameters)
        if self.script.execute_error is not None:
            raise self.script.execute_error
        self.pending_rows = list(self.script.rows)
        self.rowcount = self.script.rowcount

    def do_executemany(self, sql: str, seq_of_parameters: Any, on_entered: bool) -> None:
        params = list(seq_of_parameters) if seq_of_parameters is not None else []
        self._record("executemany", on_entered, sql=sql, params=params)
        if self.script.executemany_error is not None:
            raise self.script.executemany_error
        self.pending_rows = []
        if self.script.rowcount_from_executemany_length:
            self.rowcount = len(params)
        else:
            self.rowcount = self.script.rowcount

    def do_fetchone(self, on_entered: bool) -> Optional[Tuple[Any, ...]]:
        self._record("fetchone", on_entered)
        if self.script.fetchone_error is not None:
            raise self.script.fetchone_error
        if not self.pending_rows:
            return None
        return self.pending_rows.pop(0)

    def do_fetchall(self, on_entered: bool) -> Tuple[Tuple[Any, ...], ...]:
        self._record("fetchall", on_entered)
        if self.script.fetchall_error is not None:
            raise self.script.fetchall_error
        rows = tuple(self.pending_rows)
        self.pending_rows = []
        return rows

    def do_fetchmany(self, size: int, on_entered: bool) -> Tuple[Tuple[Any, ...], ...]:
        self._record("fetchmany", on_entered, size=size)
        if self.script.fetchmany_error is not None:
            raise self.script.fetchmany_error
        rows = tuple(self.pending_rows[:size])
        del self.pending_rows[:size]
        return rows

    def do_close(self, on_entered: bool = False) -> None:
        self.close_calls += 1
        self._record("close", on_entered)
        if self.script.close_error is not None:
            raise self.script.close_error

    def do_enter(self) -> None:
        self.enter_calls += 1
        self._record("enter", None)

    def do_exit(self, exc_type: Any, exc_val: Any, exc_tb: Any) -> Any:
        self.exit_calls += 1
        self.exit_args.append((exc_type, exc_val, exc_tb))
        tb_is_active = None
        if exc_val is not None:
            tb_is_active = exc_tb is getattr(exc_val, "__traceback__", None)
        self._record("exit", None, exc_type=exc_type, exc_value=exc_val, tb_is_active=tb_is_active)
        if self.script.exit_error is not None:
            raise self.script.exit_error
        return self.script.exit_result


class _SyncCursorFacade:
    """Sync DBAPI surface over a :class:`CursorRecorder`."""

    _entered = False

    def __init__(self, recorder: CursorRecorder) -> None:
        self.recorder = recorder

    @property
    def description(self) -> Tuple[Tuple[Any, ...], ...]:
        return self.recorder.description

    @property
    def rowcount(self) -> int:
        return self.recorder.rowcount

    def execute(self, sql: str, parameters: Any = None) -> None:
        self.recorder.do_execute(sql, parameters, self._entered)

    def executemany(self, sql: str, seq_of_parameters: Any = None) -> None:
        self.recorder.do_executemany(sql, seq_of_parameters, self._entered)

    def fetchone(self) -> Optional[Tuple[Any, ...]]:
        return self.recorder.do_fetchone(self._entered)

    def fetchall(self) -> Tuple[Tuple[Any, ...], ...]:
        return self.recorder.do_fetchall(self._entered)

    def fetchmany(self, size: int = 1) -> Tuple[Tuple[Any, ...], ...]:
        return self.recorder.do_fetchmany(size, self._entered)

    def close(self) -> None:
        self.recorder.do_close(self._entered)


class EnteredRecordingCursor(_SyncCursorFacade):
    """The distinct object a context-managed cursor's ``__enter__`` returns.

    Sharing the recorder while being a different object lets the framework prove
    commands operate on the *entered* cursor rather than the raw one.
    """

    _entered = True


class _NoFetchmanyEnteredRecordingCursor(EnteredRecordingCursor):
    fetchmany = None  # type: ignore[assignment]


class PlainRecordingCursor(_SyncCursorFacade):
    """A cursor with no context-manager protocol; cleanup must go through ``close()``."""


class _NoFetchmanyPlainRecordingCursor(PlainRecordingCursor):
    fetchmany = None  # type: ignore[assignment]


class ContextRecordingCursor(_SyncCursorFacade):
    """A native context-manager cursor whose ``__enter__`` returns a distinct object."""

    def __init__(self, recorder: CursorRecorder) -> None:
        super().__init__(recorder)
        entered_class = (
            EnteredRecordingCursor if recorder.script.supports_fetchmany else _NoFetchmanyEnteredRecordingCursor
        )
        self.entered_cursor = entered_class(recorder)

    def __enter__(self) -> EnteredRecordingCursor:
        self.recorder.do_enter()
        return self.entered_cursor

    def __exit__(self, exc_type: Any, exc_val: Any, exc_tb: Any) -> Any:
        return self.recorder.do_exit(exc_type, exc_val, exc_tb)


class _NoFetchmanyContextRecordingCursor(ContextRecordingCursor):
    fetchmany = None  # type: ignore[assignment]


class _AsyncCursorFacade:
    """Async DBAPI surface over a :class:`CursorRecorder`."""

    _entered = False

    def __init__(self, recorder: CursorRecorder) -> None:
        self.recorder = recorder

    @property
    def description(self) -> Tuple[Tuple[Any, ...], ...]:
        return self.recorder.description

    @property
    def rowcount(self) -> int:
        return self.recorder.rowcount

    async def execute(self, sql: str, parameters: Any = None) -> None:
        self.recorder.do_execute(sql, parameters, self._entered)

    async def executemany(self, sql: str, seq_of_parameters: Any = None) -> None:
        self.recorder.do_executemany(sql, seq_of_parameters, self._entered)

    async def fetchone(self) -> Optional[Tuple[Any, ...]]:
        return self.recorder.do_fetchone(self._entered)

    async def fetchall(self) -> Tuple[Tuple[Any, ...], ...]:
        return self.recorder.do_fetchall(self._entered)

    async def fetchmany(self, size: int = 1) -> Tuple[Tuple[Any, ...], ...]:
        return self.recorder.do_fetchmany(size, self._entered)


class EnteredRecordingAsyncCursor(_AsyncCursorFacade):
    """Distinct entered object shared-state proxy for async context-manager cursors."""

    _entered = True


class _NoFetchmanyEnteredRecordingAsyncCursor(EnteredRecordingAsyncCursor):
    fetchmany = None  # type: ignore[assignment]


class PlainRecordingAsyncCursor(_AsyncCursorFacade):
    """An async cursor with no context-manager protocol.

    ``close_style`` selects whether ``close()`` completes synchronously or returns an
    awaitable, covering both plain-cursor cleanup shapes.
    """

    def __init__(self, recorder: CursorRecorder, close_style: str = "sync") -> None:
        super().__init__(recorder)
        self._close_style = close_style

    def close(self) -> Any:
        if self._close_style == "awaitable":

            async def _aclose() -> None:
                self.recorder.do_close(self._entered)

            return _aclose()
        self.recorder.do_close(self._entered)
        return None


class _NoFetchmanyPlainRecordingAsyncCursor(PlainRecordingAsyncCursor):
    fetchmany = None  # type: ignore[assignment]


class ContextRecordingAsyncCursor(_AsyncCursorFacade):
    """A native async context-manager cursor; ``__aenter__`` returns a distinct object."""

    def __init__(self, recorder: CursorRecorder) -> None:
        super().__init__(recorder)
        entered_class = (
            EnteredRecordingAsyncCursor
            if recorder.script.supports_fetchmany
            else _NoFetchmanyEnteredRecordingAsyncCursor
        )
        self.entered_cursor = entered_class(recorder)

    async def __aenter__(self) -> EnteredRecordingAsyncCursor:
        self.recorder.do_enter()
        return self.entered_cursor

    async def __aexit__(self, exc_type: Any, exc_val: Any, exc_tb: Any) -> Any:
        return self.recorder.do_exit(exc_type, exc_val, exc_tb)


class _NoFetchmanyContextRecordingAsyncCursor(ContextRecordingAsyncCursor):
    fetchmany = None  # type: ignore[assignment]


class RecordingConnection:
    """A sync DBAPI-shaped connection serving instrumented cursors from scripts.

    ``scripts`` supplies one :class:`CursorScript` per acquired cursor; the last
    script repeats if more cursors are acquired than scripts were given.
    ``cursor_style`` selects the cursor shape: ``"context"`` (native context manager)
    or ``"plain"`` (close-only). ``commit_error``/``rollback_error`` inject a failure
    at the named connection-level transaction interaction.
    """

    def __init__(
        self,
        scripts: Union[CursorScript, Sequence[CursorScript], None] = None,
        cursor_style: str = "context",
        commit_error: Optional[BaseException] = None,
        rollback_error: Optional[BaseException] = None,
    ) -> None:
        if scripts is None:
            scripts = CursorScript()
        if isinstance(scripts, CursorScript):
            scripts = [scripts]
        self._scripts = list(scripts)
        self._cursor_style = cursor_style
        self._commit_error = commit_error
        self._rollback_error = rollback_error
        self.log = RecordingLog()
        self.cursor_calls = 0
        self.commit_calls = 0
        self.rollback_calls = 0
        self.recorders: List[CursorRecorder] = []
        self.cursors: List[_SyncCursorFacade] = []

    def commit(self) -> None:
        self.commit_calls += 1
        self.log.add(RecordedEvent(kind="commit"))
        if self._commit_error is not None:
            raise self._commit_error

    def rollback(self) -> None:
        self.rollback_calls += 1
        self.log.add(RecordedEvent(kind="rollback"))
        if self._rollback_error is not None:
            raise self._rollback_error

    def cursor(self, *args: Any, **kwargs: Any) -> _SyncCursorFacade:
        self.cursor_calls += 1
        self.log.add(RecordedEvent(kind="cursor"))
        script = self._scripts[min(self.cursor_calls - 1, len(self._scripts) - 1)]
        recorder = CursorRecorder(script, self.log)
        self.recorders.append(recorder)
        cursor: _SyncCursorFacade
        if self._cursor_style == "plain":
            plain_class = PlainRecordingCursor if script.supports_fetchmany else _NoFetchmanyPlainRecordingCursor
            cursor = plain_class(recorder)
        else:
            context_class = ContextRecordingCursor if script.supports_fetchmany else _NoFetchmanyContextRecordingCursor
            cursor = context_class(recorder)
        self.cursors.append(cursor)
        return cursor


class RecordingAsyncConnection:
    """An async connection whose ``cursor()`` returns an awaitable (the base contract).

    ``cursor_style`` is ``"context"`` or ``"plain"``; ``close_style`` selects sync vs
    awaitable ``close()`` for plain cursors.
    """

    def __init__(
        self,
        scripts: Union[CursorScript, Sequence[CursorScript], None] = None,
        cursor_style: str = "context",
        close_style: str = "sync",
    ) -> None:
        if scripts is None:
            scripts = CursorScript()
        if isinstance(scripts, CursorScript):
            scripts = [scripts]
        self._scripts = list(scripts)
        self._cursor_style = cursor_style
        self._close_style = close_style
        self.log = RecordingLog()
        self.cursor_calls = 0
        self.recorders: List[CursorRecorder] = []
        self.cursors: List[_AsyncCursorFacade] = []

    def _build_cursor(self) -> _AsyncCursorFacade:
        self.cursor_calls += 1
        self.log.add(RecordedEvent(kind="cursor"))
        script = self._scripts[min(self.cursor_calls - 1, len(self._scripts) - 1)]
        recorder = CursorRecorder(script, self.log)
        self.recorders.append(recorder)
        cursor: _AsyncCursorFacade
        if self._cursor_style == "plain":
            plain_class = (
                PlainRecordingAsyncCursor if script.supports_fetchmany else _NoFetchmanyPlainRecordingAsyncCursor
            )
            cursor = plain_class(recorder, close_style=self._close_style)
        else:
            context_class = (
                ContextRecordingAsyncCursor if script.supports_fetchmany else _NoFetchmanyContextRecordingAsyncCursor
            )
            cursor = context_class(recorder)
        self.cursors.append(cursor)
        return cursor

    async def cursor(self, *args: Any, **kwargs: Any) -> _AsyncCursorFacade:
        return self._build_cursor()


class SynchronousCursorRecordingAsyncConnection(RecordingAsyncConnection):
    """An async connection whose ``cursor()`` returns the cursor directly.

    This is the psycopg3-async shape: the command class is responsible for
    normalizing the synchronous cursor factory (by overriding ``cursor()``), and the
    conformance suite exercises that normalization through the real class.
    """

    def cursor(self, *args: Any, **kwargs: Any) -> _AsyncCursorFacade:  # type: ignore[override]
        return self._build_cursor()
