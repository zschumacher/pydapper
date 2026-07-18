"""Service-free coverage for the cursor/command preparation seams added by #467.

Every public sync and async command family must enter exactly one command-owned cursor, run
``_prepare_cursor*`` once per cursor and ``_prepare_command*`` once per executed handler in
order, and clean the cursor through the existing lifecycle when preparation fails.
"""

import pytest

import pydapper
from pydapper.exceptions import InvalidParameterShapeException
from pydapper.exceptions import MissingParameterException
from pydapper.exceptions import UnsupportedFeatureError
from pydapper.mysql import MySqlConnectorPythonCommands
from pydapper.postgresql import Psycopg3Commands
from pydapper.postgresql import Psycopg3CommandsAsync
from tests.mocks import MockAsyncCommands
from tests.mocks import MockCommands

pytestmark = pytest.mark.core


class _EnteredRecordingCursor:
    """Distinct object returned by cursor entry so identity assertions can prove the hooks
    receive the entered cursor rather than the raw one."""

    def __init__(self, raw_cursor):
        self._raw_cursor = raw_cursor

    def __getattr__(self, name):
        return getattr(self._raw_cursor, name)


class RecordingCursor:
    description = ("id", "int"), ("name", "text")

    def __init__(self, log, rows=((1, "zach"),), exit_error=None, exit_result=False):
        self.log = log
        self.rowcount = 0
        self._rows_template = tuple(rows)
        self.rows = []
        self.exit_error = exit_error
        self.exit_result = exit_result
        self.exit_args = []
        self.exit_tb_matches = []
        self.entered = _EnteredRecordingCursor(self)

    def __enter__(self):
        self.log.append("enter")
        return self.entered

    def __exit__(self, exc_type, exc_val, exc_tb):
        self.log.append(("exit", exc_type))
        self.exit_args.append((exc_type, exc_val, exc_tb))
        self.exit_tb_matches.append(exc_val is not None and exc_tb is exc_val.__traceback__)
        if self.exit_error is not None:
            raise self.exit_error
        return self.exit_result

    def execute(self, sql, parameters=None):
        self.log.append(("execute", sql))
        self.rowcount = 1
        self.rows = list(self._rows_template)

    def executemany(self, sql, seq_of_parameters=None):
        self.log.append(("executemany", sql))
        self.rowcount = len(seq_of_parameters)
        self.rows = []

    def fetchone(self):
        self.log.append("fetchone")
        return self.rows.pop(0) if self.rows else None

    def fetchmany(self, size=None):
        self.log.append("fetchmany")
        taken, self.rows = self.rows[:size], self.rows[size:]
        return tuple(taken)

    def fetchall(self):
        self.log.append("fetchall")
        remaining, self.rows = self.rows, []
        return tuple(remaining)


class RecordingAsyncCursor:
    description = ("id", "int"), ("name", "text")

    def __init__(self, log, rows=((1, "zach"),), exit_error=None, exit_result=False):
        self.log = log
        self.rowcount = 0
        self._rows_template = tuple(rows)
        self.rows = []
        self.exit_error = exit_error
        self.exit_result = exit_result
        self.exit_args = []
        self.exit_tb_matches = []
        self.entered = _EnteredRecordingCursor(self)

    async def __aenter__(self):
        self.log.append("enter")
        return self.entered

    async def __aexit__(self, exc_type, exc_val, exc_tb):
        self.log.append(("exit", exc_type))
        self.exit_args.append((exc_type, exc_val, exc_tb))
        self.exit_tb_matches.append(exc_val is not None and exc_tb is exc_val.__traceback__)
        if self.exit_error is not None:
            raise self.exit_error
        return self.exit_result

    async def execute(self, sql, parameters=None):
        self.log.append(("execute", sql))
        self.rowcount = 1
        self.rows = list(self._rows_template)

    async def executemany(self, sql, seq_of_parameters=None):
        self.log.append(("executemany", sql))
        self.rowcount = len(seq_of_parameters)
        self.rows = []

    async def fetchone(self):
        self.log.append("fetchone")
        return self.rows.pop(0) if self.rows else None

    async def fetchmany(self, size=None):
        self.log.append("fetchmany")
        taken, self.rows = self.rows[:size], self.rows[size:]
        return tuple(taken)

    async def fetchall(self):
        self.log.append("fetchall")
        remaining, self.rows = self.rows, []
        return tuple(remaining)


class RecordingConnection:
    def __init__(self, cursor):
        self.cursor_instance = cursor
        self.cursor_calls = 0

    def cursor(self, *args, **kwargs):
        self.cursor_calls += 1
        return self.cursor_instance


class RecordingAsyncConnection:
    def __init__(self, cursor):
        self.cursor_instance = cursor
        self.cursor_calls = 0

    async def cursor(self, *args, **kwargs):
        self.cursor_calls += 1
        return self.cursor_instance


class _SyncHookRecorderMixin:
    def _prepare_cursor(self, cursor, *, options):
        self.log.append(("prepare_cursor", cursor, options))
        if self.prepare_cursor_error is not None:
            raise self.prepare_cursor_error
        super()._prepare_cursor(cursor, options=options)

    def _prepare_command(self, cursor, handler, *, options):
        self.log.append(("prepare_command", cursor, handler, options))
        if self.prepare_command_error is not None:
            raise self.prepare_command_error
        super()._prepare_command(cursor, handler, options=options)


class _AsyncHookRecorderMixin:
    async def _prepare_cursor_async(self, cursor, *, options):
        self.log.append(("prepare_cursor", cursor, options))
        if self.prepare_cursor_error is not None:
            raise self.prepare_cursor_error
        await super()._prepare_cursor_async(cursor, options=options)

    async def _prepare_command_async(self, cursor, handler, *, options):
        self.log.append(("prepare_command", cursor, handler, options))
        if self.prepare_command_error is not None:
            raise self.prepare_command_error
        await super()._prepare_command_async(cursor, handler, options=options)


class RecordingHookCommands(_SyncHookRecorderMixin, MockCommands):
    def __init__(self, connection, log):
        super().__init__(connection)
        self.log = log
        self.prepare_cursor_error = None
        self.prepare_command_error = None


class RecordingHookCommandsAsync(_AsyncHookRecorderMixin, MockAsyncCommands):
    def __init__(self, connection, log):
        super().__init__(connection)
        self.log = log
        self.prepare_cursor_error = None
        self.prepare_command_error = None


def _event_kinds(log):
    return [event[0] if isinstance(event, tuple) else event for event in log]


def _canonical_events(log):
    """Object-free view of the full event sequence so sync and async logs are directly comparable."""
    canonical = []
    for event in log:
        if not isinstance(event, tuple):
            canonical.append(event)
        elif event[0] in ("execute", "executemany", "exit"):
            canonical.append((event[0], event[1]))
        elif event[0] == "prepare_command":
            canonical.append((event[0], event[2].prepared_sql))
        else:
            canonical.append(event[0])
    return canonical


def _assert_prepared_once_in_order(log, cursor):
    kinds = _event_kinds(log)
    assert kinds[:3] == ["enter", "prepare_cursor", "prepare_command"]
    assert kinds[3] in ("execute", "executemany")
    assert kinds[-1] == "exit"
    assert kinds.count("enter") == 1
    assert kinds.count("prepare_cursor") == 1
    assert kinds.count("prepare_command") == 1
    assert kinds.count("exit") == 1

    _, prepared_cursor, cursor_options = log[1]
    _, command_cursor, handler, command_options = log[2]
    assert prepared_cursor is cursor.entered
    assert prepared_cursor is not cursor
    assert command_cursor is cursor.entered
    assert command_cursor is not cursor
    assert handler.prepared_sql == log[3][1]
    assert cursor_options is not None
    assert command_options is not None
    assert cursor_options == pydapper.CommandOptions()
    assert command_options == pydapper.CommandOptions()


SYNC_FAMILY_CALLS = [
    pytest.param(
        lambda commands, **kw: commands.execute("insert into task (id) values (?id?)", params={"id": 1}, **kw),
        id="execute",
    ),
    pytest.param(
        lambda commands, **kw: commands.execute(
            "insert into task (id) values (?id?)", params=[{"id": 1}, {"id": 2}], **kw
        ),
        id="execute-executemany",
    ),
    pytest.param(lambda commands, **kw: commands.execute_scalar("select id from task", **kw), id="execute_scalar"),
    pytest.param(lambda commands, **kw: commands.query("select id, name from task", **kw), id="query-buffered"),
    pytest.param(
        lambda commands, **kw: list(commands.query("select id, name from task", buffered=False, **kw)),
        id="query-unbuffered",
    ),
    pytest.param(
        lambda commands, **kw: commands.query_multiple(("select id, name from task",), **kw), id="query_multiple"
    ),
    pytest.param(lambda commands, **kw: commands.query_first("select id, name from task", **kw), id="query_first"),
    pytest.param(
        lambda commands, **kw: commands.query_first_or_default("select id, name from task", None, **kw),
        id="query_first_or_default",
    ),
    pytest.param(lambda commands, **kw: commands.query_single("select id, name from task", **kw), id="query_single"),
    pytest.param(
        lambda commands, **kw: commands.query_single_or_default("select id, name from task", None, **kw),
        id="query_single_or_default",
    ),
]


async def _consume_unbuffered_async(commands, **kw):
    generator = await commands.query_async("select id, name from task", buffered=False, **kw)
    return [row async for row in generator]


ASYNC_FAMILY_CALLS = [
    pytest.param(
        lambda commands, **kw: commands.execute_async("insert into task (id) values (?id?)", params={"id": 1}, **kw),
        id="execute_async",
    ),
    pytest.param(
        lambda commands, **kw: commands.execute_async(
            "insert into task (id) values (?id?)", params=[{"id": 1}, {"id": 2}], **kw
        ),
        id="execute_async-executemany",
    ),
    pytest.param(
        lambda commands, **kw: commands.execute_scalar_async("select id from task", **kw), id="execute_scalar_async"
    ),
    pytest.param(
        lambda commands, **kw: commands.query_async("select id, name from task", **kw), id="query_async-buffered"
    ),
    pytest.param(_consume_unbuffered_async, id="query_async-unbuffered"),
    pytest.param(
        lambda commands, **kw: commands.query_multiple_async(("select id, name from task",), **kw),
        id="query_multiple_async",
    ),
    pytest.param(
        lambda commands, **kw: commands.query_first_async("select id, name from task", **kw), id="query_first_async"
    ),
    pytest.param(
        lambda commands, **kw: commands.query_first_or_default_async("select id, name from task", None, **kw),
        id="query_first_or_default_async",
    ),
    pytest.param(
        lambda commands, **kw: commands.query_single_async("select id, name from task", **kw), id="query_single_async"
    ),
    pytest.param(
        lambda commands, **kw: commands.query_single_or_default_async("select id, name from task", None, **kw),
        id="query_single_or_default_async",
    ),
]


def _sync_commands():
    log = []
    cursor = RecordingCursor(log)
    connection = RecordingConnection(cursor)
    return log, cursor, connection, RecordingHookCommands(connection, log)


def _async_commands():
    log = []
    cursor = RecordingAsyncCursor(log)
    connection = RecordingAsyncConnection(cursor)
    return log, cursor, connection, RecordingHookCommandsAsync(connection, log)


@pytest.mark.parametrize("call", SYNC_FAMILY_CALLS)
def test_sync_families_prepare_cursor_and_command_once_in_order(call):
    log, cursor, _, commands = _sync_commands()

    call(commands)

    _assert_prepared_once_in_order(log, cursor)


@pytest.mark.asyncio
@pytest.mark.parametrize("call", ASYNC_FAMILY_CALLS)
async def test_async_families_prepare_cursor_and_command_once_in_order(call):
    log, cursor, _, commands = _async_commands()

    await call(commands)

    _assert_prepared_once_in_order(log, cursor)


SYNC_ASYNC_FAMILY_PAIRS = [
    pytest.param(sync_param.values[0], async_param.values[0], id=async_param.id)
    for sync_param, async_param in zip(SYNC_FAMILY_CALLS, ASYNC_FAMILY_CALLS)
]


@pytest.mark.asyncio
@pytest.mark.parametrize(("sync_call", "async_call"), SYNC_ASYNC_FAMILY_PAIRS)
async def test_sync_and_async_families_produce_identical_event_sequences(sync_call, async_call):
    sync_log, _, _, sync_commands = _sync_commands()
    async_log, _, _, async_commands = _async_commands()

    sync_call(sync_commands)
    await async_call(async_commands)

    assert _canonical_events(sync_log) == _canonical_events(async_log)


@pytest.mark.asyncio
@pytest.mark.parametrize("failing_hook", ["prepare_cursor_error", "prepare_command_error"])
@pytest.mark.parametrize(("sync_call", "async_call"), SYNC_ASYNC_FAMILY_PAIRS)
async def test_sync_and_async_preparation_failures_produce_identical_event_sequences(
    sync_call, async_call, failing_hook
):
    sync_log, _, _, sync_commands = _sync_commands()
    async_log, _, _, async_commands = _async_commands()
    setattr(sync_commands, failing_hook, RuntimeError("preparation failed"))
    setattr(async_commands, failing_hook, RuntimeError("preparation failed"))

    with pytest.raises(RuntimeError):
        sync_call(sync_commands)
    with pytest.raises(RuntimeError):
        await async_call(async_commands)

    assert _canonical_events(sync_log) == _canonical_events(async_log)


@pytest.mark.parametrize("call", SYNC_FAMILY_CALLS)
def test_sync_families_pass_provided_options_instance_to_both_hooks(call):
    log, _, _, commands = _sync_commands()
    options = pydapper.CommandOptions()

    call(commands, options=options)

    assert log[1][2] is options
    assert log[2][3] is options


@pytest.mark.asyncio
@pytest.mark.parametrize("call", ASYNC_FAMILY_CALLS)
async def test_async_families_pass_provided_options_instance_to_both_hooks(call):
    log, _, _, commands = _async_commands()
    options = pydapper.CommandOptions()

    await call(commands, options=options)

    assert log[1][2] is options
    assert log[2][3] is options


@pytest.mark.parametrize("call", SYNC_FAMILY_CALLS)
def test_sync_unsupported_options_fail_before_cursor_acquisition_and_hooks(call):
    log, _, connection, commands = _sync_commands()

    with pytest.raises(UnsupportedFeatureError):
        call(commands, options=pydapper.CommandOptions(timeout=1))

    assert log == []
    assert connection.cursor_calls == 0


@pytest.mark.asyncio
@pytest.mark.parametrize("call", ASYNC_FAMILY_CALLS)
async def test_async_unsupported_options_fail_before_cursor_acquisition_and_hooks(call):
    log, _, connection, commands = _async_commands()

    with pytest.raises(UnsupportedFeatureError):
        await call(commands, options=pydapper.CommandOptions(timeout=1))

    assert log == []
    assert connection.cursor_calls == 0


@pytest.mark.parametrize(
    ("call", "expected_exception"),
    [
        pytest.param(
            lambda commands: commands.query("select 1", param={"id": 1}, params={"id": 1}),
            ValueError,
            id="param-alias-conflict",
        ),
        pytest.param(
            lambda commands: commands.query("select 1", model=dict, mapper=lambda row: row),
            ValueError,
            id="model-and-mapper",
        ),
        pytest.param(lambda commands: commands.query("select ?id?"), MissingParameterException, id="missing-param"),
        pytest.param(
            lambda commands: commands.query_first("select 1", params=[{"id": 1}]),
            InvalidParameterShapeException,
            id="list-params-for-read",
        ),
        pytest.param(
            lambda commands: commands.query_multiple(("select 1", "select ?id?")),
            MissingParameterException,
            id="query_multiple-later-missing-param",
        ),
    ],
)
def test_sync_validation_fails_before_cursor_acquisition_and_hooks(call, expected_exception):
    log, _, connection, commands = _sync_commands()

    with pytest.raises(expected_exception):
        call(commands)

    assert log == []
    assert connection.cursor_calls == 0


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("call", "expected_exception"),
    [
        pytest.param(
            lambda commands: commands.query_async("select 1", param={"id": 1}, params={"id": 1}),
            ValueError,
            id="param-alias-conflict",
        ),
        pytest.param(
            lambda commands: commands.query_async("select 1", model=dict, mapper=lambda row: row),
            ValueError,
            id="model-and-mapper",
        ),
        pytest.param(
            lambda commands: commands.query_async("select ?id?"), MissingParameterException, id="missing-param"
        ),
        pytest.param(
            lambda commands: commands.query_first_async("select 1", params=[{"id": 1}]),
            InvalidParameterShapeException,
            id="list-params-for-read",
        ),
        pytest.param(
            lambda commands: commands.query_multiple_async(("select 1", "select ?id?")),
            MissingParameterException,
            id="query_multiple-later-missing-param",
        ),
    ],
)
async def test_async_validation_fails_before_cursor_acquisition_and_hooks(call, expected_exception):
    log, _, connection, commands = _async_commands()

    with pytest.raises(expected_exception):
        await call(commands)

    assert log == []
    assert connection.cursor_calls == 0


def test_sync_execute_empty_executemany_fast_path_skips_cursor_and_hooks():
    log, _, connection, commands = _sync_commands()

    assert commands.execute("insert into task (id) values (?id?)", params=[]) == 0

    assert log == []
    assert connection.cursor_calls == 0


@pytest.mark.asyncio
async def test_async_execute_empty_executemany_fast_path_skips_cursor_and_hooks():
    log, _, connection, commands = _async_commands()

    assert await commands.execute_async("insert into task (id) values (?id?)", params=[]) == 0

    assert log == []
    assert connection.cursor_calls == 0


def test_sync_query_multiple_prepares_cursor_once_and_each_handler_once():
    log, cursor, _, commands = _sync_commands()
    queries = ("select id from task", "select name from task")

    commands.query_multiple(queries)

    assert _event_kinds(log) == [
        "enter",
        "prepare_cursor",
        "prepare_command",
        "execute",
        "fetchall",
        "prepare_command",
        "execute",
        "fetchall",
        "exit",
    ]
    prepared = [event for event in log if isinstance(event, tuple) and event[0] == "prepare_command"]
    assert [event[2].prepared_sql for event in prepared] == list(queries)
    assert len({id(event[2]) for event in prepared}) == 2
    assert all(event[1] is cursor.entered for event in prepared)


@pytest.mark.asyncio
async def test_async_query_multiple_prepares_cursor_once_and_each_handler_once():
    log, cursor, _, commands = _async_commands()
    queries = ("select id from task", "select name from task")

    await commands.query_multiple_async(queries)

    assert _event_kinds(log) == [
        "enter",
        "prepare_cursor",
        "prepare_command",
        "execute",
        "fetchall",
        "prepare_command",
        "execute",
        "fetchall",
        "exit",
    ]
    prepared = [event for event in log if isinstance(event, tuple) and event[0] == "prepare_command"]
    assert [event[2].prepared_sql for event in prepared] == list(queries)
    assert len({id(event[2]) for event in prepared}) == 2
    assert all(event[1] is cursor.entered for event in prepared)


def test_sync_unbuffered_query_defers_hooks_until_iteration_and_cleans_up_on_close():
    log, _, _, commands = _sync_commands()

    generator = commands.query("select id, name from task", buffered=False)
    assert log == []

    next(generator)
    assert _event_kinds(log)[:4] == ["enter", "prepare_cursor", "prepare_command", "execute"]
    assert "exit" not in _event_kinds(log)

    generator.close()
    assert _event_kinds(log)[-1] == "exit"
    assert _event_kinds(log).count("exit") == 1


@pytest.mark.asyncio
async def test_async_unbuffered_query_defers_hooks_until_iteration_and_cleans_up_on_aclose():
    log, _, _, commands = _async_commands()

    generator = await commands.query_async("select id, name from task", buffered=False)
    assert log == []

    await generator.__anext__()
    assert _event_kinds(log)[:4] == ["enter", "prepare_cursor", "prepare_command", "execute"]
    assert "exit" not in _event_kinds(log)

    await generator.aclose()
    assert _event_kinds(log)[-1] == "exit"
    assert _event_kinds(log).count("exit") == 1


@pytest.mark.parametrize("call", SYNC_FAMILY_CALLS)
def test_sync_cursor_preparation_failure_exits_once_and_prevents_command_preparation(call):
    log, cursor, _, commands = _sync_commands()
    error = RuntimeError("cursor preparation failed")
    commands.prepare_cursor_error = error

    with pytest.raises(RuntimeError) as exc_info:
        call(commands)

    assert exc_info.value is error
    assert _event_kinds(log) == ["enter", "prepare_cursor", "exit"]
    [(exc_type, exc_val, _)] = cursor.exit_args
    assert exc_type is RuntimeError
    assert exc_val is error
    assert cursor.exit_tb_matches == [True]


@pytest.mark.asyncio
@pytest.mark.parametrize("call", ASYNC_FAMILY_CALLS)
async def test_async_cursor_preparation_failure_exits_once_and_prevents_command_preparation(call):
    log, cursor, _, commands = _async_commands()
    error = RuntimeError("cursor preparation failed")
    commands.prepare_cursor_error = error

    with pytest.raises(RuntimeError) as exc_info:
        await call(commands)

    assert exc_info.value is error
    assert _event_kinds(log) == ["enter", "prepare_cursor", "exit"]
    [(exc_type, exc_val, _)] = cursor.exit_args
    assert exc_type is RuntimeError
    assert exc_val is error
    assert cursor.exit_tb_matches == [True]


@pytest.mark.parametrize("call", SYNC_FAMILY_CALLS)
def test_sync_command_preparation_failure_exits_once_and_prevents_execution(call):
    log, cursor, _, commands = _sync_commands()
    error = RuntimeError("command preparation failed")
    commands.prepare_command_error = error

    with pytest.raises(RuntimeError) as exc_info:
        call(commands)

    assert exc_info.value is error
    assert _event_kinds(log) == ["enter", "prepare_cursor", "prepare_command", "exit"]
    [(exc_type, exc_val, _)] = cursor.exit_args
    assert exc_type is RuntimeError
    assert exc_val is error
    assert cursor.exit_tb_matches == [True]


@pytest.mark.asyncio
@pytest.mark.parametrize("call", ASYNC_FAMILY_CALLS)
async def test_async_command_preparation_failure_exits_once_and_prevents_execution(call):
    log, cursor, _, commands = _async_commands()
    error = RuntimeError("command preparation failed")
    commands.prepare_command_error = error

    with pytest.raises(RuntimeError) as exc_info:
        await call(commands)

    assert exc_info.value is error
    assert _event_kinds(log) == ["enter", "prepare_cursor", "prepare_command", "exit"]
    [(exc_type, exc_val, _)] = cursor.exit_args
    assert exc_type is RuntimeError
    assert exc_val is error
    assert cursor.exit_tb_matches == [True]


@pytest.mark.parametrize("failing_hook", ["prepare_cursor_error", "prepare_command_error"])
def test_sync_preparation_error_wins_over_cleanup_failure(failing_hook):
    log = []
    cursor = RecordingCursor(log, exit_error=OSError("cleanup failed"))
    commands = RecordingHookCommands(RecordingConnection(cursor), log)
    error = RuntimeError("preparation failed")
    setattr(commands, failing_hook, error)

    with pytest.raises(RuntimeError) as exc_info:
        commands.query("select id, name from task")

    assert exc_info.value is error
    assert _event_kinds(log).count("exit") == 1
    [(exc_type, exc_val, _)] = cursor.exit_args
    assert exc_type is RuntimeError
    assert exc_val is error
    assert cursor.exit_tb_matches == [True]


@pytest.mark.asyncio
@pytest.mark.parametrize("failing_hook", ["prepare_cursor_error", "prepare_command_error"])
async def test_async_preparation_error_wins_over_cleanup_failure(failing_hook):
    log = []
    cursor = RecordingAsyncCursor(log, exit_error=OSError("cleanup failed"))
    commands = RecordingHookCommandsAsync(RecordingAsyncConnection(cursor), log)
    error = RuntimeError("preparation failed")
    setattr(commands, failing_hook, error)

    with pytest.raises(RuntimeError) as exc_info:
        await commands.query_async("select id, name from task")

    assert exc_info.value is error
    assert _event_kinds(log).count("exit") == 1
    [(exc_type, exc_val, _)] = cursor.exit_args
    assert exc_type is RuntimeError
    assert exc_val is error
    assert cursor.exit_tb_matches == [True]


@pytest.mark.parametrize("failing_hook", ["prepare_cursor_error", "prepare_command_error"])
def test_sync_truthy_cursor_exit_does_not_suppress_preparation_error(failing_hook):
    log = []
    cursor = RecordingCursor(log, exit_result=True)
    commands = RecordingHookCommands(RecordingConnection(cursor), log)
    error = RuntimeError("preparation failed")
    setattr(commands, failing_hook, error)

    with pytest.raises(RuntimeError) as exc_info:
        commands.query("select id, name from task")

    assert exc_info.value is error


@pytest.mark.asyncio
@pytest.mark.parametrize("failing_hook", ["prepare_cursor_error", "prepare_command_error"])
async def test_async_truthy_cursor_exit_does_not_suppress_preparation_error(failing_hook):
    log = []
    cursor = RecordingAsyncCursor(log, exit_result=True)
    commands = RecordingHookCommandsAsync(RecordingAsyncConnection(cursor), log)
    error = RuntimeError("preparation failed")
    setattr(commands, failing_hook, error)

    with pytest.raises(RuntimeError) as exc_info:
        await commands.query_async("select id, name from task")

    assert exc_info.value is error


def test_sync_cleanup_failure_after_successful_command_propagates():
    log = []
    cleanup_error = OSError("cleanup failed")
    cursor = RecordingCursor(log, exit_error=cleanup_error)
    commands = RecordingHookCommands(RecordingConnection(cursor), log)

    with pytest.raises(OSError) as exc_info:
        commands.query("select id, name from task")

    assert exc_info.value is cleanup_error
    assert _event_kinds(log)[:4] == ["enter", "prepare_cursor", "prepare_command", "execute"]
    assert cursor.exit_args == [(None, None, None)]


@pytest.mark.asyncio
async def test_async_cleanup_failure_after_successful_command_propagates():
    log = []
    cleanup_error = OSError("cleanup failed")
    cursor = RecordingAsyncCursor(log, exit_error=cleanup_error)
    commands = RecordingHookCommandsAsync(RecordingAsyncConnection(cursor), log)

    with pytest.raises(OSError) as exc_info:
        await commands.query_async("select id, name from task")

    assert exc_info.value is cleanup_error
    assert _event_kinds(log)[:4] == ["enter", "prepare_cursor", "prepare_command", "execute"]
    assert cursor.exit_args == [(None, None, None)]


class RecordingMySqlCommands(_SyncHookRecorderMixin, MySqlConnectorPythonCommands):
    def __init__(self, connection, log):
        super().__init__(connection)
        self.log = log
        self.prepare_cursor_error = None
        self.prepare_command_error = None


def test_mysql_query_first_reaches_hooks_and_keeps_unread_result_drain():
    log = []
    cursor = RecordingCursor(log, rows=((1, "zach"), (2, "sam")))
    commands = RecordingMySqlCommands(RecordingConnection(cursor), log)
    options = pydapper.CommandOptions()

    result = commands.query_first("select id, name from task", options=options)

    assert result == {"id": 1, "name": "zach"}
    assert _event_kinds(log) == [
        "enter",
        "prepare_cursor",
        "prepare_command",
        "execute",
        "fetchone",
        "fetchall",
        "exit",
    ]
    assert log[1][1] is cursor.entered
    assert log[1][2] is options
    assert log[2][3] is options


def test_mysql_query_first_unsupported_options_fail_before_cursor_acquisition_and_hooks():
    log = []
    connection = RecordingConnection(RecordingCursor(log))
    commands = RecordingMySqlCommands(connection, log)

    with pytest.raises(UnsupportedFeatureError):
        commands.query_first("select id, name from task", options=pydapper.CommandOptions(timeout=1))

    assert log == []
    assert connection.cursor_calls == 0


def test_mysql_query_first_cursor_preparation_failure_prevents_execution_and_drain():
    log = []
    cursor = RecordingCursor(log, rows=((1, "zach"), (2, "sam")))
    commands = RecordingMySqlCommands(RecordingConnection(cursor), log)
    error = RuntimeError("cursor preparation failed")
    commands.prepare_cursor_error = error

    with pytest.raises(RuntimeError) as exc_info:
        commands.query_first("select id, name from task")

    assert exc_info.value is error
    assert _event_kinds(log) == ["enter", "prepare_cursor", "exit"]


class RecordingPsycopg3Commands(_SyncHookRecorderMixin, Psycopg3Commands):
    def __init__(self, connection, log):
        super().__init__(connection)
        self.log = log
        self.prepare_cursor_error = None
        self.prepare_command_error = None


class RecordingPsycopg3CommandsAsync(_AsyncHookRecorderMixin, Psycopg3CommandsAsync):
    def __init__(self, connection, log):
        super().__init__(connection)
        self.log = log
        self.prepare_cursor_error = None
        self.prepare_command_error = None


def test_psycopg3_sync_commands_reach_hooks():
    log = []
    cursor = RecordingCursor(log)
    commands = RecordingPsycopg3Commands(RecordingConnection(cursor), log)

    result = commands.query_first("select id, name from task")

    assert result == {"id": 1, "name": "zach"}
    _assert_prepared_once_in_order(log, cursor)


@pytest.mark.asyncio
async def test_psycopg3_async_sync_returning_cursor_factory_does_not_bypass_hooks():
    log = []
    cursor = RecordingAsyncCursor(log)
    connection = RecordingConnection(cursor)

    commands = RecordingPsycopg3CommandsAsync(connection, log)

    result = await commands.query_first_async("select id, name from task")

    assert result == {"id": 1, "name": "zach"}
    _assert_prepared_once_in_order(log, cursor)
    assert connection.cursor_calls == 1
