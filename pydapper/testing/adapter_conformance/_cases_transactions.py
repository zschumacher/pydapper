"""The ``transactions`` capability profile's sync case inventory.

These cases run only for command classes that declare
:attr:`~pydapper.capabilities.AdapterCapability.TRANSACTIONS`. Every ``live`` case
first commits the harness baseline (``create_commands()`` then ``commit()``) so the
scenario starts from a durable, transaction-free state regardless of whether the
harness seeded inside an open transaction. ``instrumented`` cases observe delegation,
ordering, and error precedence directly through recording connections.

The async inventory lives in ``_cases_transactions_async`` with the same case ids.
"""

from typing import Any
from typing import Callable
from typing import Dict
from typing import List
from typing import Tuple

from pydapper.commands import Commands

from ._checks import SyncCaseContext
from ._profiles import SyncCase

_CASES: List[SyncCase] = []


def _case(case_id: str, description: str, kind: str) -> Callable[[Callable[[SyncCaseContext], None]], Callable]:
    def register(fn: Callable[[SyncCaseContext], None]) -> Callable[[SyncCaseContext], None]:
        _CASES.append(SyncCase(case_id=case_id, description=description, kind=kind, run=fn))
        return fn

    return register


def transactions_sync_cases() -> Tuple[SyncCase, ...]:
    """Return the full, ordered, immutable ``transactions`` sync case inventory."""
    return _FROZEN_CASES


class _InjectedTransactionFault(Exception):
    """Framework-injected failure raised inside a transaction block."""


class _InjectedTransactionCleanupFault(Exception):
    """Framework-injected connection commit/rollback failure."""


class _InjectedTransactionInterrupt(BaseException):
    """Framework-injected ``BaseException`` that is deliberately not an ``Exception``.

    It derives straight from :class:`BaseException` rather than from
    :class:`KeyboardInterrupt`, which is all the cases need: the split a ``transaction()``
    block must honour is ``except Exception`` versus everything else, and this takes the
    non-``Exception`` side of it identically.

    Deriving from :class:`KeyboardInterrupt` would additionally hand the adapter under test
    something its own Ctrl-C shutdown path recognises, and the runner propagates real
    interrupts instead of recording them, so an adapter answering one with a plain
    ``KeyboardInterrupt`` would tear down the whole conformance run. A misbehaving adapter
    must fail a case, never take the harness with it.
    """


_TX_ROW: Dict[str, Any] = {"id": 100, "label": "tx", "score": 7, "note": "tx-note"}


def _row_count(ctx: SyncCaseContext, commands: Commands, row_id: int) -> int:
    return len(commands.query(ctx.sql("select_by_id"), params={"id": row_id}))


@_case(
    "transactions.commit-persists",
    "commit() makes a write durable: a later rollback() cannot remove it",
    "live",
)
def _transactions_commit_persists(ctx: SyncCaseContext) -> None:
    commands = ctx.create_commands()
    commands.commit()
    commands.execute(ctx.sql("insert_row"), params=dict(_TX_ROW))
    commands.commit()
    commands.rollback()
    ctx.check(
        _row_count(ctx, commands, _TX_ROW["id"]) == 1,
        "a committed insert must survive a subsequent rollback()",
    )


@_case(
    "transactions.rollback-discards",
    "rollback() discards uncommitted work and leaves committed rows intact",
    "live",
)
def _transactions_rollback_discards(ctx: SyncCaseContext) -> None:
    commands = ctx.create_commands()
    commands.commit()
    commands.execute(ctx.sql("insert_row"), params=dict(_TX_ROW))
    commands.rollback()
    ctx.check(
        _row_count(ctx, commands, _TX_ROW["id"]) == 0,
        "rollback() must discard the uncommitted insert",
    )
    rows = commands.query(ctx.sql("select_all"))
    ctx.check(
        len(rows) == len(ctx.seeded_rows()),
        f"rollback() must leave the {len(ctx.seeded_rows())} committed baseline rows intact, saw {len(rows)}",
    )


@_case(
    "transactions.context-commits-on-exit",
    "A transaction() block commits on clean exit",
    "live",
)
def _transactions_context_commits(ctx: SyncCaseContext) -> None:
    commands = ctx.create_commands()
    commands.commit()
    with commands.transaction():
        commands.execute(ctx.sql("insert_row"), params=dict(_TX_ROW))
    commands.rollback()
    ctx.check(
        _row_count(ctx, commands, _TX_ROW["id"]) == 1,
        "a clean transaction() exit must commit; a later rollback() cannot remove the insert",
    )


@_case(
    "transactions.context-rolls-back-on-error",
    "A transaction() block rolls back on exception and re-raises the same exception",
    "live",
)
def _transactions_context_rolls_back(ctx: SyncCaseContext) -> None:
    commands = ctx.create_commands()
    commands.commit()
    fault = _InjectedTransactionFault("boom")
    with ctx.expect_raises(_InjectedTransactionFault) as caught:
        with commands.transaction():
            commands.execute(ctx.sql("insert_row"), params=dict(_TX_ROW))
            raise fault
    ctx.check(caught.exception is fault, "the block's exception must propagate as the same exception object")
    ctx.check(
        _row_count(ctx, commands, _TX_ROW["id"]) == 0,
        "a transaction() block that raised must roll its insert back",
    )
    # recover runs last so a harness recovery step can never repair the state under test
    ctx.recover(commands)


@_case(
    "transactions.commit-delegates-once",
    "commit() delegates to the connection exactly once, acquires no cursor, and its failure propagates",
    "instrumented",
)
def _transactions_commit_delegates(ctx: SyncCaseContext) -> None:
    connection = ctx.recording_connection()
    commands = ctx.instrumented_commands(connection)
    # a third-party override may return a value; the contract pins None
    result = commands.commit()  # type: ignore[func-returns-value]
    ctx.check(result is None, f"commit() must return None, got {result!r}")
    ctx.check(connection.commit_calls == 1, f"expected exactly one connection commit, saw {connection.commit_calls}")
    ctx.check(connection.rollback_calls == 0, "commit() must not roll back")
    ctx.check(connection.cursor_calls == 0, "commit() must not acquire a cursor")
    ctx.check_event_order(connection.log, ("commit",))

    fault = _InjectedTransactionCleanupFault("commit")
    failing = ctx.recording_connection(commit_error=fault)
    commands = ctx.instrumented_commands(failing)
    with ctx.expect_raises(_InjectedTransactionCleanupFault) as caught:
        commands.commit()
    ctx.check(caught.exception is fault, "a connection commit failure must propagate from commit() unchanged")
    ctx.check(failing.commit_calls == 1, f"expected exactly one commit attempt, saw {failing.commit_calls}")
    ctx.check(failing.rollback_calls == 0, "a failed commit() must not trigger a rollback")


@_case(
    "transactions.rollback-delegates-once",
    "rollback() delegates to the connection exactly once, acquires no cursor, and its failure propagates",
    "instrumented",
)
def _transactions_rollback_delegates(ctx: SyncCaseContext) -> None:
    connection = ctx.recording_connection()
    commands = ctx.instrumented_commands(connection)
    # a third-party override may return a value; the contract pins None
    result = commands.rollback()  # type: ignore[func-returns-value]
    ctx.check(result is None, f"rollback() must return None, got {result!r}")
    ctx.check(
        connection.rollback_calls == 1, f"expected exactly one connection rollback, saw {connection.rollback_calls}"
    )
    ctx.check(connection.commit_calls == 0, "rollback() must not commit")
    ctx.check(connection.cursor_calls == 0, "rollback() must not acquire a cursor")
    ctx.check_event_order(connection.log, ("rollback",))

    fault = _InjectedTransactionCleanupFault("rollback")
    failing = ctx.recording_connection(rollback_error=fault)
    commands = ctx.instrumented_commands(failing)
    with ctx.expect_raises(_InjectedTransactionCleanupFault) as caught:
        commands.rollback()
    ctx.check(caught.exception is fault, "a connection rollback failure must propagate from rollback() unchanged")
    ctx.check(failing.rollback_calls == 1, f"expected exactly one rollback attempt, saw {failing.rollback_calls}")
    ctx.check(failing.commit_calls == 0, "a failed rollback() must not trigger a commit")


@_case(
    "transactions.context-lifecycle-order",
    "A clean transaction() block commits exactly once, after the command's cursor lifecycle",
    "instrumented",
)
def _transactions_context_lifecycle(ctx: SyncCaseContext) -> None:
    connection = ctx.recording_connection()
    commands = ctx.instrumented_commands(connection)
    with commands.transaction():
        commands.execute("UPDATE t SET label = 'x'")
    ctx.check(connection.commit_calls == 1, f"expected exactly one commit, saw {connection.commit_calls}")
    ctx.check(connection.rollback_calls == 0, "a clean transaction() block must not roll back")
    ctx.check_event_order(connection.log, ("cursor", "enter", "execute", "exit", "commit"))


@_case(
    "transactions.context-error-precedence",
    "A transaction() block rolls back on error, re-raises it, and the error wins over a rollback failure",
    "instrumented",
)
def _transactions_context_error_precedence(ctx: SyncCaseContext) -> None:
    fault = _InjectedTransactionFault("boom")
    connection = ctx.recording_connection()
    commands = ctx.instrumented_commands(connection)
    with ctx.expect_raises(_InjectedTransactionFault) as caught:
        with commands.transaction():
            raise fault
    ctx.check(caught.exception is fault, "the block's exception must propagate as the same exception object")
    ctx.check(
        connection.rollback_calls == 1, f"expected exactly one connection rollback, saw {connection.rollback_calls}"
    )
    ctx.check(connection.commit_calls == 0, "a failed transaction() block must not commit")

    rollback_fault = _InjectedTransactionCleanupFault("rollback")
    failing = ctx.recording_connection(rollback_error=rollback_fault)
    commands = ctx.instrumented_commands(failing)
    with ctx.expect_raises(_InjectedTransactionFault) as caught_again:
        with commands.transaction():
            raise fault
    ctx.check(caught_again.exception is fault, "the block's exception must win over a rollback failure")
    ctx.check(failing.rollback_calls == 1, f"expected exactly one rollback attempt, saw {failing.rollback_calls}")


@_case(
    "transactions.commit-failure-propagates",
    "A commit failure on clean transaction() exit propagates unchanged with no rollback attempt",
    "instrumented",
)
def _transactions_commit_failure(ctx: SyncCaseContext) -> None:
    commit_fault = _InjectedTransactionCleanupFault("commit")
    connection = ctx.recording_connection(commit_error=commit_fault)
    commands = ctx.instrumented_commands(connection)
    with ctx.expect_raises(_InjectedTransactionCleanupFault) as caught:
        with commands.transaction():
            pass
    ctx.check(caught.exception is commit_fault, "the commit failure must propagate as the same exception object")
    ctx.check(connection.commit_calls == 1, f"expected exactly one commit attempt, saw {connection.commit_calls}")
    ctx.check(connection.rollback_calls == 0, "no rollback may be attempted after a failed commit")


@_case(
    "transactions.context-base-exception-rollback",
    "A transaction() block rolls back a non-Exception BaseException too, and an interrupted "
    "rollback wins over the block's own error",
    "instrumented",
)
def _transactions_context_base_exception(ctx: SyncCaseContext) -> None:
    interrupt = _InjectedTransactionInterrupt("interrupt")
    connection = ctx.recording_connection()
    commands = ctx.instrumented_commands(connection)
    with ctx.expect_raises(_InjectedTransactionInterrupt) as caught:
        with commands.transaction():
            raise interrupt
    ctx.check(
        caught.exception is interrupt,
        "a BaseException that is not an Exception must propagate as the same exception object",
    )
    ctx.check(
        connection.rollback_calls == 1,
        f"a block abandoned by a BaseException must roll back exactly once, saw {connection.rollback_calls}",
    )
    ctx.check(connection.commit_calls == 0, "a block abandoned by a BaseException must not commit")

    # an interrupt raised by the rollback itself is an interpreter-level request to stop, so it
    # beats the block's ordinary error rather than being discarded like a failed cleanup
    rollback_interrupt = _InjectedTransactionInterrupt("rollback")
    failing = ctx.recording_connection(rollback_error=rollback_interrupt)
    commands = ctx.instrumented_commands(failing)
    fault = _InjectedTransactionFault("boom")
    with ctx.expect_raises(_InjectedTransactionInterrupt) as interrupted:
        with commands.transaction():
            raise fault
    ctx.check(
        interrupted.exception is rollback_interrupt,
        "an interrupt raised by rollback must win over the block's ordinary error",
    )
    # winning must not mean erasing: the block's own error is what says *what was being done*
    # when the interrupt arrived, and implicit chaining is the only place it survives
    ctx.check(
        getattr(interrupted.exception, "__context__", None) is fault,
        "the block's error must survive as the interrupt's __context__",
    )
    ctx.check(failing.commit_calls == 0, "a block whose rollback was interrupted must not commit")


@_case(
    "transactions.context-not-reentrant",
    "transaction() blocks do not nest on one instance, and the guard clears for the next block",
    "instrumented",
)
def _transactions_context_not_reentrant(ctx: SyncCaseContext) -> None:
    connection = ctx.recording_connection()
    commands = ctx.instrumented_commands(connection)
    with ctx.expect_raises(RuntimeError):
        with commands.transaction():
            with commands.transaction():
                ctx.fail("a nested transaction() block on the same Commands instance must not be entered")
    ctx.check(connection.commit_calls == 0, "a block abandoned by a nesting error must not commit")
    ctx.check(
        connection.rollback_calls == 1,
        f"a block abandoned by a nesting error must roll back exactly once, saw {connection.rollback_calls}",
    )

    # the guard belongs to the block, not to the instance's lifetime
    try:
        with commands.transaction():
            commands.execute("UPDATE t SET label = 'x'")
    except RuntimeError as error:
        ctx.fail(
            "the nesting guard must clear when a block exits: a later sequential transaction() block "
            "on the same Commands instance must be enterable",
            cause=error,
        )
    ctx.check(
        connection.commit_calls == 1,
        f"a sequential transaction() block must commit on clean exit, saw {connection.commit_calls} commits",
    )
    ctx.check(
        connection.rollback_calls == 1,
        "a clean sequential transaction() block must not roll back again, saw "
        f"{connection.rollback_calls} rollbacks (1 expected, from the nesting error above)",
    )


#: The production inventory is frozen once at import; later mutation of the private
#: registration list cannot alter what the runner executes.
_FROZEN_CASES: Tuple[SyncCase, ...] = tuple(_CASES)
