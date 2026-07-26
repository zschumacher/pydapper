"""The ``transactions`` capability profile's async case inventory.

The async twin of ``_cases_transactions`` — same nine case ids, order, and kinds, so
sync and async declaring adapters are held to one contract. These cases run only for
async command classes that declare
:attr:`~pydapper.capabilities.AdapterCapability.TRANSACTIONS`. Every ``live`` case
first commits the harness baseline (``create_commands()`` then ``commit()``) so the
scenario starts from a durable, transaction-free state regardless of whether the
harness seeded inside an open transaction. ``instrumented`` cases observe delegation,
ordering, and error precedence directly through recording connections.
"""

from typing import Callable
from typing import List
from typing import Tuple

from pydapper.commands import CommandsAsync

from ._cases_transactions import _TX_ROW
from ._checks import AsyncCaseContext
from ._profiles import AsyncCase

_CASES: List[AsyncCase] = []


def _case(case_id: str, description: str, kind: str) -> Callable[[Callable], Callable]:
    def register(fn: Callable) -> Callable:
        _CASES.append(AsyncCase(case_id=case_id, description=description, kind=kind, run=fn))
        return fn

    return register


def transactions_async_cases() -> Tuple[AsyncCase, ...]:
    """Return the full, ordered, immutable async ``transactions`` case inventory."""
    return _FROZEN_CASES


class _InjectedTransactionFault(Exception):
    """Framework-injected failure raised inside a transaction block."""


class _InjectedTransactionCleanupFault(Exception):
    """Framework-injected connection commit/rollback failure."""


async def _row_count(ctx: AsyncCaseContext, commands: CommandsAsync, row_id: int) -> int:
    return len(await commands.query_async(ctx.sql("select_by_id"), params={"id": row_id}))


@_case(
    "transactions.commit-persists",
    "commit() makes a write durable: a later rollback() cannot remove it",
    "live",
)
async def _transactions_commit_persists(ctx: AsyncCaseContext) -> None:
    commands = await ctx.create_commands()
    await commands.commit()
    await commands.execute_async(ctx.sql("insert_row"), params=dict(_TX_ROW))
    await commands.commit()
    await commands.rollback()
    ctx.check(
        await _row_count(ctx, commands, _TX_ROW["id"]) == 1,
        "a committed insert must survive a subsequent rollback()",
    )


@_case(
    "transactions.rollback-discards",
    "rollback() discards uncommitted work and leaves committed rows intact",
    "live",
)
async def _transactions_rollback_discards(ctx: AsyncCaseContext) -> None:
    commands = await ctx.create_commands()
    await commands.commit()
    await commands.execute_async(ctx.sql("insert_row"), params=dict(_TX_ROW))
    await commands.rollback()
    ctx.check(
        await _row_count(ctx, commands, _TX_ROW["id"]) == 0,
        "rollback() must discard the uncommitted insert",
    )
    rows = await commands.query_async(ctx.sql("select_all"))
    ctx.check(
        len(rows) == len(ctx.seeded_rows()),
        f"rollback() must leave the {len(ctx.seeded_rows())} committed baseline rows intact, saw {len(rows)}",
    )


@_case(
    "transactions.context-commits-on-exit",
    "A transaction() block commits on clean exit",
    "live",
)
async def _transactions_context_commits(ctx: AsyncCaseContext) -> None:
    commands = await ctx.create_commands()
    await commands.commit()
    async with commands.transaction():
        await commands.execute_async(ctx.sql("insert_row"), params=dict(_TX_ROW))
    await commands.rollback()
    ctx.check(
        await _row_count(ctx, commands, _TX_ROW["id"]) == 1,
        "a clean transaction() exit must commit; a later rollback() cannot remove the insert",
    )


@_case(
    "transactions.context-rolls-back-on-error",
    "A transaction() block rolls back on exception and re-raises the same exception",
    "live",
)
async def _transactions_context_rolls_back(ctx: AsyncCaseContext) -> None:
    commands = await ctx.create_commands()
    await commands.commit()
    fault = _InjectedTransactionFault("boom")
    with ctx.expect_raises(_InjectedTransactionFault) as caught:
        async with commands.transaction():
            await commands.execute_async(ctx.sql("insert_row"), params=dict(_TX_ROW))
            raise fault
    ctx.check(caught.exception is fault, "the block's exception must propagate as the same exception object")
    ctx.check(
        await _row_count(ctx, commands, _TX_ROW["id"]) == 0,
        "a transaction() block that raised must roll its insert back",
    )
    # recover runs last so a harness recovery step can never repair the state under test
    await ctx.recover(commands)


@_case(
    "transactions.commit-delegates-once",
    "commit() delegates to the connection exactly once, acquires no cursor, and its failure propagates",
    "instrumented",
)
async def _transactions_commit_delegates(ctx: AsyncCaseContext) -> None:
    connection = ctx.recording_connection()
    commands = ctx.instrumented_commands(connection)
    # a third-party override may return a value; the contract pins None
    result = await commands.commit()  # type: ignore[func-returns-value]
    ctx.check(result is None, f"commit() must return None, got {result!r}")
    ctx.check(connection.commit_calls == 1, f"expected exactly one connection commit, saw {connection.commit_calls}")
    ctx.check(connection.rollback_calls == 0, "commit() must not roll back")
    ctx.check(connection.cursor_calls == 0, "commit() must not acquire a cursor")
    ctx.check_event_order(connection.log, ("commit",))

    fault = _InjectedTransactionCleanupFault("commit")
    failing = ctx.recording_connection(commit_error=fault)
    commands = ctx.instrumented_commands(failing)
    with ctx.expect_raises(_InjectedTransactionCleanupFault) as caught:
        await commands.commit()
    ctx.check(caught.exception is fault, "a connection commit failure must propagate from commit() unchanged")
    ctx.check(failing.commit_calls == 1, f"expected exactly one commit attempt, saw {failing.commit_calls}")
    ctx.check(failing.rollback_calls == 0, "a failed commit() must not trigger a rollback")


@_case(
    "transactions.rollback-delegates-once",
    "rollback() delegates to the connection exactly once, acquires no cursor, and its failure propagates",
    "instrumented",
)
async def _transactions_rollback_delegates(ctx: AsyncCaseContext) -> None:
    connection = ctx.recording_connection()
    commands = ctx.instrumented_commands(connection)
    # a third-party override may return a value; the contract pins None
    result = await commands.rollback()  # type: ignore[func-returns-value]
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
        await commands.rollback()
    ctx.check(caught.exception is fault, "a connection rollback failure must propagate from rollback() unchanged")
    ctx.check(failing.rollback_calls == 1, f"expected exactly one rollback attempt, saw {failing.rollback_calls}")
    ctx.check(failing.commit_calls == 0, "a failed rollback() must not trigger a commit")


@_case(
    "transactions.context-lifecycle-order",
    "A clean transaction() block commits exactly once, after the command's cursor lifecycle",
    "instrumented",
)
async def _transactions_context_lifecycle(ctx: AsyncCaseContext) -> None:
    connection = ctx.recording_connection()
    commands = ctx.instrumented_commands(connection)
    async with commands.transaction():
        await commands.execute_async("UPDATE t SET label = 'x'")
    ctx.check(connection.commit_calls == 1, f"expected exactly one commit, saw {connection.commit_calls}")
    ctx.check(connection.rollback_calls == 0, "a clean transaction() block must not roll back")
    ctx.check_event_order(connection.log, ("cursor", "enter", "execute", "exit", "commit"))


@_case(
    "transactions.context-error-precedence",
    "A transaction() block rolls back on error, re-raises it, and the error wins over a rollback failure",
    "instrumented",
)
async def _transactions_context_error_precedence(ctx: AsyncCaseContext) -> None:
    fault = _InjectedTransactionFault("boom")
    connection = ctx.recording_connection()
    commands = ctx.instrumented_commands(connection)
    with ctx.expect_raises(_InjectedTransactionFault) as caught:
        async with commands.transaction():
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
        async with commands.transaction():
            raise fault
    ctx.check(caught_again.exception is fault, "the block's exception must win over a rollback failure")
    ctx.check(failing.rollback_calls == 1, f"expected exactly one rollback attempt, saw {failing.rollback_calls}")


@_case(
    "transactions.commit-failure-propagates",
    "A commit failure on clean transaction() exit propagates unchanged with no rollback attempt",
    "instrumented",
)
async def _transactions_commit_failure(ctx: AsyncCaseContext) -> None:
    commit_fault = _InjectedTransactionCleanupFault("commit")
    connection = ctx.recording_connection(commit_error=commit_fault)
    commands = ctx.instrumented_commands(connection)
    with ctx.expect_raises(_InjectedTransactionCleanupFault) as caught:
        async with commands.transaction():
            pass
    ctx.check(caught.exception is commit_fault, "the commit failure must propagate as the same exception object")
    ctx.check(connection.commit_calls == 1, f"expected exactly one commit attempt, saw {connection.commit_calls}")
    ctx.check(connection.rollback_calls == 0, "no rollback may be attempted after a failed commit")


#: The production inventory is frozen once at import; later mutation of the private
#: registration list cannot alter what the runner executes.
_FROZEN_CASES: Tuple[AsyncCase, ...] = tuple(_CASES)
