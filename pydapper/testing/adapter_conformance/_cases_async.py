"""The complete ``core-async`` case inventory.

Mirrors the ``core-sync`` inventory for every behavior the async mode supports,
plus async-only lifecycle shapes: ``aclose()`` cleanup, awaitable versus synchronous
plain-cursor ``close()``, and the harness-declared async cursor-factory style
(awaitable-returning versus synchronous-returning ``connection.cursor()``).
"""

import inspect
from dataclasses import dataclass
from types import SimpleNamespace
from typing import Any
from typing import Awaitable
from typing import Callable
from typing import List
from typing import Tuple

import pydapper
from pydapper.capabilities import AdapterCapability
from pydapper.command_options import CommandKind
from pydapper.command_options import CommandOptions
from pydapper.exceptions import DuplicateColumnException
from pydapper.exceptions import InvalidParameterShapeException
from pydapper.exceptions import MissingParameterException
from pydapper.exceptions import MoreThanOneResultException
from pydapper.exceptions import NoResultException
from pydapper.exceptions import UnsupportedFeatureError
from pydapper.rows import RawRow

from ._checks import AsyncCaseContext
from ._instrumentation import CursorScript
from ._profiles import AsyncCase
from ._profiles import capability_profiles

_CASES: List[AsyncCase] = []


def _case(
    case_id: str, description: str, kind: str
) -> Callable[[Callable[[AsyncCaseContext], Awaitable[None]]], Callable]:
    def register(fn: Callable[[AsyncCaseContext], Awaitable[None]]) -> Callable[[AsyncCaseContext], Awaitable[None]]:
        _CASES.append(AsyncCase(case_id=case_id, description=description, kind=kind, run=fn))
        return fn

    return register


def async_core_cases() -> Tuple[AsyncCase, ...]:
    """Return the full, ordered, immutable ``core-async`` case inventory."""
    return _FROZEN_CASES


class _InjectedExecuteFault(Exception):
    """Framework-injected execution failure."""


class _InjectedFetchFault(Exception):
    """Framework-injected fetch failure."""


class _InjectedCleanupFault(Exception):
    """Framework-injected cursor cleanup failure."""


class _InjectedMapperFault(Exception):
    """Framework-injected row mapper failure."""


@dataclass
class _ParamRecord:
    id: int


_UNSUPPORTED_OPTION_PROBES: Tuple[Tuple[AdapterCapability, CommandOptions], ...] = (
    (AdapterCapability.COMMAND_TIMEOUT, CommandOptions(timeout=1.5)),
    (AdapterCapability.STORED_PROCEDURES, CommandOptions(command_kind=CommandKind.STORED_PROCEDURE)),
    (AdapterCapability.READONLY, CommandOptions(readonly=True)),
    (AdapterCapability.READONLY, CommandOptions(readonly=False)),
    (AdapterCapability.MAX_ROWS, CommandOptions(max_rows=5)),
)


def _probe_is_implemented(ctx: "AsyncCaseContext", capability: AdapterCapability) -> bool:
    """An option probe is waived only for a capability the adapter declares AND whose
    reusable profile exists in the *production* catalog for this mode.

    Until the owning feature ships a real production profile, a declaration alone
    never waives the probe, so a falsely declared capability cannot silently accept
    the option it pretends to implement.
    """
    if capability not in _declared_capabilities(ctx):
        return False
    profile = capability_profiles().get(capability)
    return profile is not None and bool(profile.async_cases)


def _declared_capabilities(ctx: AsyncCaseContext) -> frozenset:
    declared: Any = getattr(ctx.command_class, "capabilities", frozenset())
    if isinstance(declared, frozenset) and all(isinstance(member, AdapterCapability) for member in declared):
        return declared
    return frozenset()


async def _close_connection(connection: Any) -> None:
    close = getattr(connection, "close", None)
    if callable(close):
        try:
            result = close()
            if inspect.isawaitable(result):
                await result
        except Exception:
            pass


# --------------------------------------------------------------------------------------
# registration
# --------------------------------------------------------------------------------------


@_case(
    "registration.explicit-adapter-selection",
    "Explicit adapter selection through using_async(adapter=...) returns the declared concrete class",
    "live",
)
async def _registration_explicit(ctx: AsyncCaseContext) -> None:
    commands = await ctx.create_commands()
    selected = pydapper.using_async(commands.connection, adapter=ctx.adapter_name)
    ctx.check(
        type(selected) is ctx.command_class,
        f"using_async(adapter={ctx.adapter_name!r}) returned {type(selected).__name__}, "
        f"expected {ctx.command_class.__name__}",
    )


@_case(
    "registration.supplied-connection",
    "A supplied connection works through the documented public selection path",
    "live",
)
async def _registration_supplied_connection(ctx: AsyncCaseContext) -> None:
    commands = await ctx.create_commands()
    selected = pydapper.using_async(commands.connection, adapter=ctx.adapter_name)
    rows = await selected.query_async(ctx.sql("select_all"))
    ctx.check(len(rows) == len(ctx.seeded_rows()), f"expected {len(ctx.seeded_rows())} rows, got {len(rows)}")


@_case(
    "registration.dsn-connect",
    "The documented connect_async() path works with the harness-supplied DSN",
    "live",
)
async def _registration_dsn_connect(ctx: AsyncCaseContext) -> None:
    connected = await pydapper.connect_async(ctx.connect_dsn, **dict(ctx.harness.connect_kwargs))
    try:
        ctx.check(
            type(connected) is ctx.command_class,
            f"connect_async() returned {type(connected).__name__}, expected {ctx.command_class.__name__}",
        )
        value = await connected.execute_scalar_async(ctx.sql("select_literal"))
        ctx.check(value == 1, f"connect_async()-built commands failed a trivial scalar query, got {value!r}")
    finally:
        await _close_connection(connected.connection)


# --------------------------------------------------------------------------------------
# lifecycle (instrumented)
# --------------------------------------------------------------------------------------


@_case(
    "lifecycle.context-cursor-success",
    "An async context-manager cursor is acquired once, entered, used via the entered object, and exited once",
    "instrumented",
)
async def _lifecycle_context_success(ctx: AsyncCaseContext) -> None:
    connection = ctx.recording_connection(CursorScript(rows=((1, "alpha"), (2, "beta"))))
    commands = ctx.instrumented_commands(connection)
    rows = await commands.query_async("SELECT id, label FROM t")
    ctx.check(rows == [{"id": 1, "label": "alpha"}, {"id": 2, "label": "beta"}], f"unexpected projection {rows!r}")
    ctx.check_single_cursor_lifecycle(connection)
    recorder = connection.recorders[0]
    ctx.check(recorder.enter_calls == 1, "native cursor __aenter__ must run exactly once")
    ctx.check(recorder.exit_calls == 1, "native cursor __aexit__ must run exactly once")
    ctx.check(recorder.exit_args[-1] == (None, None, None), "successful exit must receive a clean exception triple")
    for event in connection.log.of_kind("execute") + connection.log.of_kind("fetchall"):
        ctx.check(event.on_entered is True, f"driver work must go through the entered cursor, saw {event!r}")


@_case(
    "lifecycle.plain-cursor-close",
    "A plain async cursor is closed exactly once on success and failure, with sync and awaitable close()",
    "instrumented",
)
async def _lifecycle_plain_cursor(ctx: AsyncCaseContext) -> None:
    for close_style in ("sync", "awaitable"):
        connection = ctx.recording_connection(cursor_style="plain", close_style=close_style)
        commands = ctx.instrumented_commands(connection)
        await commands.query_async("SELECT id, label FROM t")
        ctx.check(
            connection.recorders[0].close_calls == 1,
            f"plain cursor with {close_style} close() must be closed exactly once after success",
        )

        fault = _InjectedExecuteFault("boom")
        failing = ctx.recording_connection(
            CursorScript(execute_error=fault), cursor_style="plain", close_style=close_style
        )
        commands = ctx.instrumented_commands(failing)
        with ctx.expect_raises(_InjectedExecuteFault) as caught:
            await commands.query_async("SELECT id, label FROM t")
        ctx.check(caught.exception is fault, "the active command error must propagate as the same exception object")
        ctx.check(
            failing.recorders[0].close_calls == 1,
            f"plain cursor with {close_style} close() must be closed exactly once after failure",
        )


@_case(
    "lifecycle.cleanup-after-failure",
    "Async cursor cleanup runs after an active command failure and receives the real exception triple",
    "instrumented",
)
async def _lifecycle_cleanup_after_failure(ctx: AsyncCaseContext) -> None:
    fault = _InjectedExecuteFault("boom")
    connection = ctx.recording_connection(CursorScript(execute_error=fault))
    commands = ctx.instrumented_commands(connection)
    with ctx.expect_raises(_InjectedExecuteFault) as caught:
        await commands.query_async("SELECT id, label FROM t")
    ctx.check(caught.exception is fault, "the active command error must propagate as the same exception object")
    recorder = connection.recorders[0]
    ctx.check(recorder.exit_calls == 1, "cursor cleanup must run exactly once after failure")
    exit_event = connection.log.first("exit")
    ctx.check(exit_event is not None and exit_event.exc_value is fault, "native exit must receive the active error")
    ctx.check(exit_event is not None and exit_event.tb_is_active is True, "native exit must receive the live traceback")


@_case(
    "lifecycle.active-error-precedence",
    "An active command error is not replaced by an async cursor cleanup failure",
    "instrumented",
)
async def _lifecycle_error_precedence(ctx: AsyncCaseContext) -> None:
    fault = _InjectedExecuteFault("boom")
    cleanup = _InjectedCleanupFault("cleanup")
    connection = ctx.recording_connection(CursorScript(execute_error=fault, exit_error=cleanup))
    commands = ctx.instrumented_commands(connection)
    with ctx.expect_raises(_InjectedExecuteFault) as caught:
        await commands.query_async("SELECT id, label FROM t")
    ctx.check(caught.exception is fault, "the active command error must win over an __aexit__ failure")

    for close_style in ("sync", "awaitable"):
        plain = ctx.recording_connection(
            CursorScript(execute_error=fault, close_error=cleanup),
            cursor_style="plain",
            close_style=close_style,
        )
        commands = ctx.instrumented_commands(plain)
        with ctx.expect_raises(_InjectedExecuteFault) as caught:
            await commands.query_async("SELECT id, label FROM t")
        ctx.check(
            caught.exception is fault,
            f"the active command error must win over a plain {close_style} close() failure",
        )


@_case(
    "lifecycle.truthy-exit-not-suppressing",
    "A truthy async cursor exit cannot suppress an active command error or fabricate a return value",
    "instrumented",
)
async def _lifecycle_truthy_exit(ctx: AsyncCaseContext) -> None:
    fault = _InjectedExecuteFault("boom")
    connection = ctx.recording_connection(CursorScript(execute_error=fault, exit_result=True))
    commands = ctx.instrumented_commands(connection)
    with ctx.expect_raises(_InjectedExecuteFault) as caught:
        await commands.query_first_async("SELECT id, label FROM t")
    ctx.check(
        caught.exception is fault,
        "a truthy cursor exit must not suppress the command error or produce a fabricated result",
    )

    fetch_fault = _InjectedFetchFault("fetch")
    connection = ctx.recording_connection(CursorScript(fetchall_error=fetch_fault, exit_result=True))
    commands = ctx.instrumented_commands(connection)
    with ctx.expect_raises(_InjectedFetchFault) as caught_fetch:
        await commands.query_async("SELECT id, label FROM t")
    ctx.check(caught_fetch.exception is fetch_fault, "a truthy cursor exit must not suppress a fetch error")


@_case(
    "lifecycle.cleanup-error-after-success",
    "An async cursor cleanup failure with no active command error propagates",
    "instrumented",
)
async def _lifecycle_cleanup_error_after_success(ctx: AsyncCaseContext) -> None:
    cleanup = _InjectedCleanupFault("cleanup")
    connection = ctx.recording_connection(CursorScript(exit_error=cleanup))
    commands = ctx.instrumented_commands(connection)
    with ctx.expect_raises(_InjectedCleanupFault) as caught:
        await commands.query_async("SELECT id, label FROM t")
    ctx.check(caught.exception is cleanup, "with no active error the cleanup failure itself must propagate")


@_case(
    "lifecycle.fetch-error-precedence",
    "An async fetch failure is the active error and wins over cursor cleanup failures",
    "instrumented",
)
async def _lifecycle_fetch_error(ctx: AsyncCaseContext) -> None:
    fault = _InjectedFetchFault("fetch")
    cleanup = _InjectedCleanupFault("cleanup")
    connection = ctx.recording_connection(CursorScript(fetchall_error=fault, exit_error=cleanup))
    commands = ctx.instrumented_commands(connection)
    with ctx.expect_raises(_InjectedFetchFault) as caught:
        await commands.query_async("SELECT id, label FROM t")
    ctx.check(caught.exception is fault, "the fetch error must propagate unchanged")
    exit_event = connection.log.first("exit")
    ctx.check(exit_event is not None and exit_event.exc_value is fault, "native exit must receive the fetch error")


@_case(
    "lifecycle.mapper-error-cleanup",
    "An async mapper failure propagates and the cursor is still cleaned up with the mapper error active",
    "instrumented",
)
async def _lifecycle_mapper_error(ctx: AsyncCaseContext) -> None:
    fault = _InjectedMapperFault("mapper")

    def broken_mapper(row: RawRow) -> Any:
        raise fault

    connection = ctx.recording_connection(CursorScript(exit_result=True))
    commands = ctx.instrumented_commands(connection)
    with ctx.expect_raises(_InjectedMapperFault) as caught:
        await commands.query_async("SELECT id, label FROM t", mapper=broken_mapper)
    ctx.check(caught.exception is fault, "the mapper error must propagate as the same exception object")
    recorder = connection.recorders[0]
    ctx.check(recorder.exit_calls == 1, "cursor cleanup must still run after a mapper failure")
    exit_event = connection.log.first("exit")
    ctx.check(exit_event is not None and exit_event.exc_value is fault, "native exit must receive the mapper error")


@_case(
    "lifecycle.model-error-cleanup",
    "An async model construction failure propagates and the cursor is still cleaned up",
    "instrumented",
)
async def _lifecycle_model_error(ctx: AsyncCaseContext) -> None:
    class ExplodingModel:
        def __init__(self, **kwargs: Any) -> None:
            raise _InjectedMapperFault("model")

    connection = ctx.recording_connection()
    commands = ctx.instrumented_commands(connection)
    with ctx.expect_raises(_InjectedMapperFault):
        await commands.query_async("SELECT id, label FROM t", model=ExplodingModel)
    ctx.check(connection.recorders[0].exit_calls == 1, "cursor cleanup must still run after a model failure")


@_case(
    "lifecycle.unbuffered-exhaustion-cleanup",
    "Async unbuffered results acquire lazily and clean up the cursor on exhaustion",
    "instrumented",
)
async def _lifecycle_unbuffered_exhaustion(ctx: AsyncCaseContext) -> None:
    connection = ctx.recording_connection(CursorScript(rows=((1, "alpha"), (2, "beta"))))
    commands = ctx.instrumented_commands(connection)
    generator = await commands.query_async("SELECT id, label FROM t", buffered=False)
    ctx.check(connection.cursor_calls == 0, "an unconsumed unbuffered query must not acquire a cursor")
    values = [row async for row in generator]
    ctx.check(len(values) == 2, f"unbuffered query yielded {len(values)} rows, expected 2")
    ctx.check(connection.recorders[0].exit_calls == 1, "exhaustion must clean up the cursor exactly once")


@_case(
    "lifecycle.unbuffered-explicit-aclose",
    "Async unbuffered results clean up the cursor exactly once on explicit aclose()",
    "instrumented",
)
async def _lifecycle_unbuffered_aclose(ctx: AsyncCaseContext) -> None:
    connection = ctx.recording_connection(CursorScript(rows=((1, "alpha"), (2, "beta"), (3, "gamma"))))
    commands = ctx.instrumented_commands(connection)
    generator = await commands.query_async("SELECT id, label FROM t", buffered=False)
    first = await generator.__anext__()
    ctx.check(first == {"id": 1, "label": "alpha"}, f"unexpected first unbuffered row {first!r}")
    await generator.aclose()
    recorder = connection.recorders[0]
    ctx.check(recorder.exit_calls == 1, "explicit aclose() must clean up the cursor exactly once")


@_case(
    "lifecycle.hook-order",
    "Async preparation hooks run once per cursor/handler, in order, on the entered cursor, with normalized options",
    "instrumented",
)
async def _lifecycle_hook_order(ctx: AsyncCaseContext) -> None:
    connection = ctx.recording_connection(CursorScript(rowcount=1))
    commands = ctx.instrumented_commands(connection)
    ctx.install_hook_recorder(commands, connection.log)
    await commands.execute_async("UPDATE t SET label = ?label? WHERE id = ?id?", params={"label": "x", "id": 1})
    kinds = connection.log.kinds()
    ctx.check(
        kinds == ("cursor", "enter", "prepare_cursor", "prepare_command", "execute", "exit"),
        f"hook order must be cursor/enter/prepare_cursor/prepare_command/execute/exit, observed {kinds!r}",
    )
    prepare_cursor_event = connection.log.first("prepare_cursor")
    if prepare_cursor_event is None or prepare_cursor_event.detail is None:
        ctx.fail("the prepare-cursor hook was never observed")
    hook_cursor, hook_options = prepare_cursor_event.detail
    context_cursor = connection.cursors[0]
    entered = getattr(context_cursor, "entered_cursor", None)
    ctx.check(
        hook_cursor is entered,
        "the prepare-cursor hook must receive the entered cursor object",
    )
    ctx.check(hook_options == CommandOptions(), "hooks must receive normalized default CommandOptions")

    explicit = CommandOptions()
    connection = ctx.recording_connection(CursorScript(rowcount=1))
    commands = ctx.instrumented_commands(connection)
    ctx.install_hook_recorder(commands, connection.log)
    await commands.execute_async(
        "UPDATE t SET label = ?label? WHERE id = ?id?", params={"label": "x", "id": 1}, options=explicit
    )
    prepare_command_event = connection.log.first("prepare_command")
    if prepare_command_event is None or prepare_command_event.detail is None:
        ctx.fail("the prepare-command hook was never observed")
    _, handler, hook_options = prepare_command_event.detail
    ctx.check(hook_options is explicit, "hooks must receive the caller's normalized CommandOptions instance")
    execute_event = connection.log.first("execute")
    if execute_event is None:
        ctx.fail("no execute reached the driver after the preparation hooks")
    ctx.check(
        getattr(handler, "prepared_sql", None) == execute_event.sql,
        "the prepare-command hook must observe the handler whose prepared SQL is executed",
    )


# --------------------------------------------------------------------------------------
# parameters and execution
# --------------------------------------------------------------------------------------


@_case("params.params-keyword", "The preferred params= spelling binds values", "live")
async def _params_keyword(ctx: AsyncCaseContext) -> None:
    commands = await ctx.create_commands()
    row = await commands.query_first_async(ctx.sql("select_by_id"), params={"id": 1})
    ctx.check(row[ctx.col("id")] == 1, f"params= lookup returned the wrong row: {row!r}")


@_case("params.param-alias", "The compatibility param= spelling binds values", "live")
async def _params_alias(ctx: AsyncCaseContext) -> None:
    commands = await ctx.create_commands()
    row = await commands.query_first_async(ctx.sql("select_by_id"), param={"id": 1})
    ctx.check(row[ctx.col("id")] == 1, f"param= lookup returned the wrong row: {row!r}")


@_case(
    "params.both-rejected-before-driver-work",
    "Supplying both params= and param= fails before cursor acquisition or driver work",
    "instrumented",
)
async def _params_both_rejected(ctx: AsyncCaseContext) -> None:
    connection = ctx.recording_connection()
    commands = ctx.instrumented_commands(connection)
    with ctx.expect_raises(ValueError):
        await commands.query_async("SELECT id, label FROM t WHERE id = ?id?", params={"id": 1}, param={"id": 2})  # type: ignore[call-overload]
    ctx.check(connection.cursor_calls == 0, "the params/param conflict must fail before any cursor is acquired")


@_case(
    "params.repeated-placeholders",
    "Repeated placeholders preserve occurrence order and reuse the correct value",
    "live",
)
async def _params_repeated(ctx: AsyncCaseContext) -> None:
    commands = await ctx.create_commands()
    row = await commands.query_first_async(ctx.sql("select_repeated_placeholder"), params={"id": 1})
    ctx.check(row[ctx.col("id")] == 1, f"repeated placeholder query returned the wrong row: {row!r}")


@_case(
    "params.repeated-placeholders-binding",
    "Repeated placeholders bind the same value once per occurrence, in order",
    "instrumented",
)
async def _params_repeated_binding(ctx: AsyncCaseContext) -> None:
    connection = ctx.recording_connection()
    commands = ctx.instrumented_commands(connection)
    await commands.query_async("SELECT id, label FROM t WHERE id = ?id? AND ?id? = id", params={"id": 7})
    execute_event = connection.log.first("execute")
    if execute_event is None:
        ctx.fail("execute must reach the driver")
    ctx.check(
        tuple(execute_event.params or ()) == (7, 7),
        f"repeated placeholders must bind (7, 7); driver saw {execute_event.params!r}",
    )


@_case(
    "params.missing-raises",
    "A missing parameter raises MissingParameterException before driver work",
    "instrumented",
)
async def _params_missing(ctx: AsyncCaseContext) -> None:
    connection = ctx.recording_connection()
    commands = ctx.instrumented_commands(connection)
    with ctx.expect_raises(MissingParameterException):
        await commands.query_async("SELECT id, label FROM t WHERE id = ?id?", params={"other": 1})
    with ctx.expect_raises(MissingParameterException):
        await commands.query_async("SELECT id, label FROM t WHERE id = ?id?")
    ctx.check(connection.cursor_calls == 0, "missing parameters must fail before any cursor is acquired")


@_case(
    "params.invalid-shape-raises",
    "Invalid parameter record and list shapes raise InvalidParameterShapeException before driver work",
    "instrumented",
)
async def _params_invalid_shape(ctx: AsyncCaseContext) -> None:
    connection = ctx.recording_connection()
    commands = ctx.instrumented_commands(connection)
    with ctx.expect_raises(InvalidParameterShapeException):
        await commands.execute_async("UPDATE t SET label = ?label? WHERE id = ?id?", params=42)
    with ctx.expect_raises(InvalidParameterShapeException):
        await commands.execute_async("UPDATE t SET label = ?label? WHERE id = ?id?", params=[42])
    with ctx.expect_raises(InvalidParameterShapeException):
        await commands.query_async("SELECT id, label FROM t WHERE id = ?id?", params=[{"id": 1}])
    ctx.check(connection.cursor_calls == 0, "invalid parameter shapes must fail before any cursor is acquired")


@_case(
    "params.record-representations",
    "Mappings, attribute objects, and dataclass instances all work as parameter records",
    "live",
)
async def _params_representations(ctx: AsyncCaseContext) -> None:
    commands = await ctx.create_commands()
    sql = ctx.sql("select_by_id")
    for record in ({"id": 1}, SimpleNamespace(id=1), _ParamRecord(id=1)):
        row = await commands.query_first_async(sql, params=record)
        ctx.check(
            row[ctx.col("id")] == 1,
            f"parameter record {type(record).__name__} returned the wrong row: {row!r}",
        )


@_case("execute.rowcount", "execute_async() returns the affected row count", "live")
async def _execute_rowcount(ctx: AsyncCaseContext) -> None:
    commands = await ctx.create_commands()
    count = await commands.execute_async(ctx.sql("update_label"), params={"label": "delta", "id": 1})
    ctx.check(isinstance(count, int), f"execute_async() must return an int row count, got {type(count).__name__}")
    if ctx.harness.strict_rowcounts:
        ctx.check(count == 1, f"expected an affected row count of 1, got {count}")


@_case(
    "execute.executemany-rowcount",
    "executemany through execute_async() returns the total affected row count",
    "live",
)
async def _execute_executemany(ctx: AsyncCaseContext) -> None:
    commands = await ctx.create_commands()
    # every bound value is non-NULL: some drivers derive a parameter's type from its
    # Python value and cannot bind an untyped None (see the docs' NULL parameter note).
    count = await commands.execute_async(
        ctx.sql("insert_row"),
        params=[
            {"id": 10, "label": "ten", "score": 1, "note": "tenth"},
            {"id": 11, "label": "eleven", "score": 2, "note": "eleventh"},
        ],
    )
    ctx.check(isinstance(count, int), f"executemany must return an int row count, got {type(count).__name__}")
    if ctx.harness.strict_rowcounts:
        ctx.check(count == 2, f"expected an affected row count of 2, got {count}")


@_case(
    "execute.executemany-empty-noop",
    "An empty executemany list is a no-op returning 0 without cursor acquisition",
    "instrumented",
)
async def _execute_empty_noop(ctx: AsyncCaseContext) -> None:
    connection = ctx.recording_connection()
    commands = ctx.instrumented_commands(connection)
    result = await commands.execute_async("UPDATE t SET label = ?label? WHERE id = ?id?", params=[])
    ctx.check(result == 0, f"empty executemany must return 0, got {result!r}")
    ctx.check(connection.cursor_calls == 0, "empty executemany must not acquire a cursor")


@_case(
    "execute.executemany-mixed-records",
    "Mixed supported executemany record representations work together",
    "live",
)
async def _execute_mixed_records(ctx: AsyncCaseContext) -> None:
    commands = await ctx.create_commands()

    @dataclass
    class Row:
        id: int
        label: str
        score: int
        note: Any

    count = await commands.execute_async(
        ctx.sql("insert_row"),
        params=[
            {"id": 20, "label": "twenty", "score": 1, "note": "twentieth"},
            Row(id=21, label="twentyone", score=2, note="twentyfirst"),
        ],
    )
    ctx.check(isinstance(count, int), f"mixed executemany must return an int, got {type(count).__name__}")
    if ctx.harness.strict_rowcounts:
        ctx.check(count == 2, f"expected an affected row count of 2, got {count}")


@_case(
    "execute.nested-list-single-value",
    "A nested list parameter stays one bound value and is not expanded before LIST_EXPANSION lands",
    "instrumented",
)
async def _execute_nested_list(ctx: AsyncCaseContext) -> None:
    connection = ctx.recording_connection()
    commands = ctx.instrumented_commands(connection)
    await commands.execute_async(
        "UPDATE t SET label = ?label? WHERE id = ?ids?", params={"label": "x", "ids": [1, 2, 3]}
    )
    execute_event = connection.log.first("execute")
    if execute_event is None:
        ctx.fail("execute must reach the driver")
    bound = tuple(execute_event.params or ())
    ctx.check(
        len(bound) == 2 and bound[1] == [1, 2, 3],
        f"a nested list must bind as one value; driver saw {bound!r}",
    )


# --------------------------------------------------------------------------------------
# rows, mapping, cardinality, scalars
# --------------------------------------------------------------------------------------


@_case("rows.query-buffered", "Buffered query returns ordered dict rows matching the dataset", "live")
async def _rows_buffered(ctx: AsyncCaseContext) -> None:
    commands = await ctx.create_commands()
    rows = await commands.query_async(ctx.sql("select_all"))
    expected = [dict(ctx.expected_row(row)) for row in ctx.seeded_rows()]
    ctx.check(rows == expected, f"buffered query returned {rows!r}, expected {expected!r}")
    first_keys = tuple(rows[0].keys())
    expected_keys = tuple(ctx.col(name) for name in ("id", "label", "score", "note"))
    ctx.check(first_keys == expected_keys, f"dict rows must preserve column order; got {first_keys!r}")


@_case("rows.query-unbuffered", "Unbuffered query yields the same rows lazily", "live")
async def _rows_unbuffered(ctx: AsyncCaseContext) -> None:
    commands = await ctx.create_commands()
    generator = await commands.query_async(ctx.sql("select_all"), buffered=False)
    rows = [row async for row in generator]
    expected = [dict(ctx.expected_row(row)) for row in ctx.seeded_rows()]
    ctx.check(rows == expected, f"unbuffered query returned {rows!r}, expected {expected!r}")


@_case("rows.mapper-receives-raw-row", "mapper= receives RawRow instances in driver order", "live")
async def _rows_mapper(ctx: AsyncCaseContext) -> None:
    commands = await ctx.create_commands()
    seen: List[Any] = []

    def mapper(row: RawRow) -> int:
        seen.append(row)
        return row[ctx.col("id")]

    ids = await commands.query_async(ctx.sql("select_all"), mapper=mapper)
    ctx.check(all(isinstance(row, RawRow) for row in seen), "mapper must receive RawRow instances")
    ctx.check(ids == [1, 2, 3], f"mapper results out of order: {ids!r}")


@_case("rows.model-mapper-exclusive", "model= and mapper= are mutually exclusive", "instrumented")
async def _rows_model_mapper_exclusive(ctx: AsyncCaseContext) -> None:
    connection = ctx.recording_connection()
    commands = ctx.instrumented_commands(connection)
    with ctx.expect_raises(ValueError):
        await commands.query_async("SELECT id, label FROM t", model=dict, mapper=lambda row: row)  # type: ignore[call-overload]
    ctx.check(connection.cursor_calls == 0, "the model/mapper conflict must fail before any cursor is acquired")


@_case(
    "rows.duplicate-columns-raise",
    "Duplicate columns raise DuplicateColumnException with structured attributes during dict mapping",
    "live",
)
async def _rows_duplicate_columns(ctx: AsyncCaseContext) -> None:
    commands = await ctx.create_commands()
    with ctx.expect_raises(DuplicateColumnException) as caught:
        await commands.query_async(ctx.sql("select_duplicate_columns"), params={"id": 1})
    error = caught.exception
    if not isinstance(error, DuplicateColumnException):
        ctx.fail(f"expected a DuplicateColumnException, captured {error!r}")
    duplicate = ctx.col("id")
    ctx.check(error.columns == (duplicate, duplicate), f"structured columns attribute wrong: {error.columns!r}")
    ctx.check(
        error.duplicate_columns == (duplicate,),
        f"structured duplicate_columns attribute wrong: {error.duplicate_columns!r}",
    )
    ctx.check(
        error.duplicate_indexes == (0, 1),
        f"structured duplicate_indexes attribute wrong: {error.duplicate_indexes!r}",
    )
    await ctx.recover(commands)


@_case("rows.mapper-receives-duplicates", "An explicit mapper intentionally receives duplicate columns", "live")
async def _rows_mapper_duplicates(ctx: AsyncCaseContext) -> None:
    commands = await ctx.create_commands()

    def mapper(row: RawRow) -> Tuple[Any, ...]:
        return row.values

    values = await commands.query_async(ctx.sql("select_duplicate_columns"), params={"id": 1}, mapper=mapper)
    ctx.check(values == [(1, 1)], f"mapper must receive both duplicate column values, got {values!r}")


@_case("cardinality.first-returns-first", "query_first_async returns the first of many rows", "live")
async def _cardinality_first(ctx: AsyncCaseContext) -> None:
    commands = await ctx.create_commands()
    row = await commands.query_first_async(ctx.sql("select_two"), params={"score": 10})
    ctx.check(row[ctx.col("id")] == 1, f"query_first_async must return the first row; got {row!r}")


@_case("cardinality.first-zero-raises", "query_first_async raises NoResultException on zero rows", "live")
async def _cardinality_first_zero(ctx: AsyncCaseContext) -> None:
    commands = await ctx.create_commands()
    with ctx.expect_raises(NoResultException):
        await commands.query_first_async(ctx.sql("select_by_id"), params={"id": 999})
    await ctx.recover(commands)


@_case(
    "cardinality.first-or-default",
    "query_first_or_default_async returns the row when present and the default on zero rows",
    "live",
)
async def _cardinality_first_or_default(ctx: AsyncCaseContext) -> None:
    commands = await ctx.create_commands()
    sentinel = object()
    row: Any = await commands.query_first_or_default_async(ctx.sql("select_by_id"), default=sentinel, params={"id": 1})
    ctx.check(row is not sentinel and row[ctx.col("id")] == 1, f"expected row 1, got {row!r}")
    missing = await commands.query_first_or_default_async(ctx.sql("select_by_id"), default=sentinel, params={"id": 999})
    ctx.check(missing is sentinel, "query_first_or_default_async must return the default on zero rows")


@_case("cardinality.single-one", "query_single_async returns the only matching row", "live")
async def _cardinality_single(ctx: AsyncCaseContext) -> None:
    commands = await ctx.create_commands()
    row = await commands.query_single_async(ctx.sql("select_by_id"), params={"id": 1})
    ctx.check(row[ctx.col("id")] == 1, f"query_single_async returned the wrong row: {row!r}")


@_case("cardinality.single-zero-raises", "query_single_async raises NoResultException on zero rows", "live")
async def _cardinality_single_zero(ctx: AsyncCaseContext) -> None:
    commands = await ctx.create_commands()
    with ctx.expect_raises(NoResultException):
        await commands.query_single_async(ctx.sql("select_by_id"), params={"id": 999})
    await ctx.recover(commands)


@_case(
    "cardinality.single-many-raises",
    "query_single_async raises MoreThanOneResultException on many rows",
    "live",
)
async def _cardinality_single_many(ctx: AsyncCaseContext) -> None:
    commands = await ctx.create_commands()
    with ctx.expect_raises(MoreThanOneResultException):
        await commands.query_single_async(ctx.sql("select_two"), params={"score": 10})
    await ctx.recover(commands)


@_case(
    "cardinality.single-or-default",
    "query_single_or_default_async handles zero, one, and many rows",
    "live",
)
async def _cardinality_single_or_default(ctx: AsyncCaseContext) -> None:
    commands = await ctx.create_commands()
    sentinel = object()
    missing = await commands.query_single_or_default_async(
        ctx.sql("select_by_id"), default=sentinel, params={"id": 999}
    )
    ctx.check(missing is sentinel, "query_single_or_default_async must return the default on zero rows")
    row: Any = await commands.query_single_or_default_async(ctx.sql("select_by_id"), default=sentinel, params={"id": 1})
    ctx.check(row is not sentinel and row[ctx.col("id")] == 1, f"expected row 1, got {row!r}")
    with ctx.expect_raises(MoreThanOneResultException):
        await commands.query_single_or_default_async(ctx.sql("select_two"), default=sentinel, params={"score": 10})
    await ctx.recover(commands)


@_case(
    "cardinality.single-bounded-fetch",
    "Single-row cardinality checks consume at most two rows before deciding",
    "instrumented",
)
async def _cardinality_bounded_fetch(ctx: AsyncCaseContext) -> None:
    many_rows = ((1, "a"), (2, "b"), (3, "c"), (4, "d"))
    connection = ctx.recording_connection(CursorScript(rows=many_rows))
    commands = ctx.instrumented_commands(connection)
    with ctx.expect_raises(MoreThanOneResultException):
        await commands.query_single_async("SELECT id, label FROM t")
    fetchmany_events = connection.log.of_kind("fetchmany")
    ctx.check(
        len(fetchmany_events) == 1 and fetchmany_events[0].size == 2,
        f"with fetchmany available, exactly one fetchmany(2) is expected; saw {fetchmany_events!r}",
    )

    fallback = ctx.recording_connection(CursorScript(rows=many_rows, supports_fetchmany=False))
    commands = ctx.instrumented_commands(fallback)
    with ctx.expect_raises(MoreThanOneResultException):
        await commands.query_single_async("SELECT id, label FROM t")
    exit_index = fallback.log.kinds().index("exit")
    fetchone_before_decision = sum(1 for kind in fallback.log.kinds()[:exit_index] if kind == "fetchone")
    ctx.check(
        fetchone_before_decision <= 2,
        f"without fetchmany, at most two fetchone calls may precede the cardinality decision; "
        f"saw {fetchone_before_decision}",
    )


@_case("cardinality.falsey-row-is-result", "Falsey rows and values are results, never defaults", "live")
async def _cardinality_falsey_row(ctx: AsyncCaseContext) -> None:
    commands = await ctx.create_commands()
    sentinel = object()
    row: Any = await commands.query_first_or_default_async(ctx.sql("select_by_id"), default=sentinel, params={"id": 2})
    ctx.check(row is not sentinel, "a falsey row must not be replaced by the default")
    ctx.check(row[ctx.col("score")] == 0, f"expected the falsey score row, got {row!r}")


@_case("scalar.value", "execute_scalar_async returns the first column of the first row", "live")
async def _scalar_value(ctx: AsyncCaseContext) -> None:
    commands = await ctx.create_commands()
    value = await commands.execute_scalar_async(ctx.sql("scalar_label"), params={"id": 3})
    ctx.check(value == "gamma", f"execute_scalar_async returned {value!r}, expected 'gamma'")


@_case(
    "scalar.no-row-raises",
    "execute_scalar_async distinguishes no returned row by raising NoResultException",
    "live",
)
async def _scalar_no_row(ctx: AsyncCaseContext) -> None:
    commands = await ctx.create_commands()
    with ctx.expect_raises(NoResultException):
        await commands.execute_scalar_async(ctx.sql("scalar_label"), params={"id": 999})
    await ctx.recover(commands)


@_case("scalar.null-returns-none", "execute_scalar_async returns None for a returned SQL NULL", "live")
async def _scalar_null(ctx: AsyncCaseContext) -> None:
    commands = await ctx.create_commands()
    value = await commands.execute_scalar_async(ctx.sql("scalar_note"), params={"id": 1})
    ctx.check(value is None, f"a SQL NULL scalar must return None, got {value!r}")


@_case("scalar.falsey-preserved", "Falsey first-column values are not treated as no result", "live")
async def _scalar_falsey(ctx: AsyncCaseContext) -> None:
    commands = await ctx.create_commands()
    score = await commands.execute_scalar_async(ctx.sql("scalar_score"), params={"id": 2})
    ctx.check(score is not None and score == 0, f"a falsey 0 scalar must be preserved, got {score!r}")
    label = await commands.execute_scalar_async(ctx.sql("scalar_label"), params={"id": 2})
    if ctx.harness.supports_empty_strings:
        ctx.check(label == "", f"a falsey empty-string scalar must be preserved, got {label!r}")
    else:
        ctx.check(label == "blank", f"the documented empty-string fallback value must round-trip, got {label!r}")


# --------------------------------------------------------------------------------------
# options and capability honesty
# --------------------------------------------------------------------------------------


@_case(
    "options.default-equivalence",
    "Omitted options, options=None, and CommandOptions() behave identically",
    "live",
)
async def _options_default_equivalence(ctx: AsyncCaseContext) -> None:
    commands = await ctx.create_commands()
    sql = ctx.sql("select_by_id")
    omitted = await commands.query_async(sql, params={"id": 1})
    explicit_none = await commands.query_async(sql, params={"id": 1}, options=None)
    default_options = await commands.query_async(sql, params={"id": 1}, options=CommandOptions())
    ctx.check(
        omitted == explicit_none == default_options,
        "omitted options, options=None, and CommandOptions() must behave identically",
    )


@_case(
    "options.unsupported-raises",
    "Valid non-default options for unimplemented capabilities raise UnsupportedFeatureError",
    "live",
)
async def _options_unsupported(ctx: AsyncCaseContext) -> None:
    commands = await ctx.create_commands()
    for capability, options in _UNSUPPORTED_OPTION_PROBES:
        if _probe_is_implemented(ctx, capability):
            continue
        with ctx.expect_raises(UnsupportedFeatureError):
            await commands.query_async(ctx.sql("select_all"), options=options)


@_case(
    "options.unsupported-before-driver-work",
    "Unsupported options fail before cursor acquisition or driver work",
    "instrumented",
)
async def _options_unsupported_no_driver_work(ctx: AsyncCaseContext) -> None:
    for capability, options in _UNSUPPORTED_OPTION_PROBES:
        if _probe_is_implemented(ctx, capability):
            continue
        connection = ctx.recording_connection()
        commands = ctx.instrumented_commands(connection)
        with ctx.expect_raises(UnsupportedFeatureError):
            await commands.query_async("SELECT id, label FROM t", options=options)
        ctx.check(
            connection.cursor_calls == 0,
            f"options for undeclared capability {capability.value!r} must fail before any cursor is acquired",
        )


@_case("options.invalid-rejected", "Invalid options objects fail clearly with TypeError", "instrumented")
async def _options_invalid(ctx: AsyncCaseContext) -> None:
    connection = ctx.recording_connection()
    commands = ctx.instrumented_commands(connection)
    bad_options: Any = object()
    with ctx.expect_raises(TypeError):
        await commands.query_async("SELECT id, label FROM t", options=bad_options)
    ctx.check(connection.cursor_calls == 0, "invalid options must fail before any cursor is acquired")


@_case(
    "capabilities.declaration-valid",
    "The concrete class declares capabilities as a frozenset of AdapterCapability members",
    "instrumented",
)
async def _capabilities_declaration_valid(ctx: AsyncCaseContext) -> None:
    declared = getattr(ctx.command_class, "capabilities", None)
    if not isinstance(declared, frozenset):
        ctx.fail(
            f"{ctx.command_class.__name__}.capabilities must be a frozenset of AdapterCapability members, "
            f"got {type(declared).__name__}"
        )
    for member in declared:
        if not isinstance(member, AdapterCapability):
            ctx.fail(f"{ctx.command_class.__name__}.capabilities contains a non-AdapterCapability member: {member!r}")


@_case(
    "capabilities.supports-matches-declaration",
    "supports() exactly matches the class declaration and rejects non-enum arguments",
    "instrumented",
)
async def _capabilities_supports(ctx: AsyncCaseContext) -> None:
    connection = ctx.recording_connection()
    commands = ctx.instrumented_commands(connection)
    declared = _declared_capabilities(ctx)
    for member in AdapterCapability:
        ctx.check(
            commands.supports(member) == (member in declared),
            f"supports({member.value!r}) must match the class declaration",
        )
    with ctx.expect_raises(TypeError):
        commands.supports("transactions")  # type: ignore[arg-type]


@_case(
    "capabilities.declared-profile-populated",
    "Every declared capability has a populated conformance profile for this mode",
    "instrumented",
)
async def _capabilities_profiles_populated(ctx: AsyncCaseContext) -> None:
    declared: Any = getattr(ctx.command_class, "capabilities", frozenset())
    if not isinstance(declared, frozenset):
        ctx.fail(f"cannot evaluate capability profiles: invalid declaration {declared!r}")
    for member in declared:
        if not isinstance(member, AdapterCapability):
            ctx.fail(f"cannot evaluate capability profiles: non-enum member {member!r}")
        # authoritative check against the production catalog: an injected catalog can
        # add profiles to run, but it can never make a declaration look covered
        profile = capability_profiles().get(member)
        if profile is None:
            ctx.fail(
                f"declared capability {member.value!r} has no production conformance profile; "
                "a capability may only be declared once its reusable profile exists"
            )
        if not profile.async_cases:
            ctx.fail(
                f"declared capability {member.value!r} has no async conformance cases; "
                "a declared capability must be covered in every declared mode"
            )


#: The production inventory is frozen once at import; later mutation of the private
#: registration list cannot alter what the runner executes.
_FROZEN_CASES: Tuple[AsyncCase, ...] = tuple(_CASES)
