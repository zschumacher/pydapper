import asyncio
import logging

import pytest

from pydapper._context import _AwaitableAsyncContextManager

pytestmark = pytest.mark.core


def debug_records(caplog):
    return [record for record in caplog.records if record.levelno == logging.DEBUG]


class ContextObject:
    def __init__(self, exit_result=False, exit_error=None):
        self.exit_result = exit_result
        self.exit_error = exit_error
        self.entered = object()
        self.enter_calls = 0
        self.exit_calls = 0
        self.exit_args = None

    async def __aenter__(self):
        self.enter_calls += 1
        return self.entered

    async def __aexit__(self, exc_type, exc_val, exc_tb):
        self.exit_calls += 1
        self.exit_args = exc_type, exc_val, exc_tb
        if self.exit_error:
            raise self.exit_error
        return self.exit_result


class PlainObject:
    def __init__(self, close_result=None, close_error=None):
        self.closed = 0
        self.close_result = close_result
        self.close_error = close_error

    def close(self):
        self.closed += 1
        if self.close_error:
            raise self.close_error
        return self.close_result


async def resolve_after(event, value):
    await event.wait()
    return value


@pytest.mark.asyncio
async def test_await_resolves_once_and_returns_identical_object():
    calls = 0

    async def source():
        nonlocal calls
        calls += 1
        return []

    wrapper = _AwaitableAsyncContextManager(source())
    first = await wrapper
    second = await wrapper

    assert first is second
    assert calls == 1


@pytest.mark.asyncio
async def test_concurrent_awaits_share_one_resolution():
    event = asyncio.Event()
    calls = 0

    async def source():
        nonlocal calls
        calls += 1
        return await resolve_after(event, object())

    wrapper = _AwaitableAsyncContextManager(source())

    async def wait_for_wrapper():
        return await wrapper

    first = asyncio.create_task(wait_for_wrapper())
    second = asyncio.create_task(wait_for_wrapper())
    await asyncio.sleep(0)
    event.set()

    first_result, second_result = await asyncio.gather(first, second)
    assert first_result is second_result
    assert calls == 1


@pytest.mark.asyncio
async def test_await_then_async_with_reuses_resolved_object():
    calls = 0

    async def source():
        nonlocal calls
        calls += 1
        return PlainObject()

    wrapper = _AwaitableAsyncContextManager(source())
    obj = await wrapper
    async with wrapper as entered:
        assert entered is obj
    assert calls == 1
    assert obj.closed == 1


@pytest.mark.asyncio
async def test_async_with_returns_entry_value_and_exits_original_object():
    obj = ContextObject()
    async with _AwaitableAsyncContextManager(asyncio.sleep(0, result=obj)) as entered:
        assert entered is obj.entered
    assert obj.exit_calls == 1


@pytest.mark.asyncio
@pytest.mark.parametrize("exit_result, suppresses", [(True, True), (False, False)])
async def test_exit_result_is_propagated(exit_result, suppresses):
    obj = ContextObject(exit_result=exit_result)
    caught = False
    try:
        async with _AwaitableAsyncContextManager(asyncio.sleep(0, result=obj), preserve_active_error=False):
            raise ValueError("body")
    except ValueError:
        caught = True
    assert caught is not suppresses


@pytest.mark.asyncio
async def test_preserve_active_error_ignores_truthy_native_exit():
    calls = 0
    obj = ContextObject(exit_result=True)

    async def source():
        nonlocal calls
        calls += 1
        return obj

    body_error = ValueError("body")
    wrapper = _AwaitableAsyncContextManager(source(), preserve_active_error=True)
    with pytest.raises(ValueError) as exc_info:
        async with wrapper:
            raise body_error

    assert exc_info.value is body_error
    assert calls == 1
    assert obj.enter_calls == 1
    assert obj.exit_calls == 1
    exc_type, exc_val, exc_tb = obj.exit_args
    assert exc_type is ValueError
    assert exc_val is body_error
    assert exc_tb is body_error.__traceback__


@pytest.mark.asyncio
async def test_preserve_active_error_wins_over_native_exit_failure():
    body_error = ValueError("body")
    obj = ContextObject(exit_error=RuntimeError("cleanup"))

    with pytest.raises(ValueError) as exc_info:
        async with _AwaitableAsyncContextManager(asyncio.sleep(0, result=obj), preserve_active_error=True):
            raise body_error

    assert exc_info.value is body_error
    assert obj.enter_calls == 1
    assert obj.exit_calls == 1


@pytest.mark.asyncio
async def test_preserve_active_error_propagates_native_exit_failure_after_success():
    cleanup_error = RuntimeError("cleanup")
    obj = ContextObject(exit_error=cleanup_error)

    with pytest.raises(RuntimeError) as exc_info:
        async with _AwaitableAsyncContextManager(asyncio.sleep(0, result=obj), preserve_active_error=True):
            pass

    assert exc_info.value is cleanup_error
    assert obj.exit_calls == 1
    assert obj.exit_args == (None, None, None)


@pytest.mark.asyncio
async def test_preserve_active_error_passes_through_native_exit_result_without_active_error():
    # async with discards __aexit__'s return value when no exception is active, so drive the
    # protocol directly to observe that the native result passes through unchanged
    marker = object()
    obj = ContextObject(exit_result=marker)
    wrapper = _AwaitableAsyncContextManager(asyncio.sleep(0, result=obj), preserve_active_error=True)

    entered = await wrapper.__aenter__()
    result = await wrapper.__aexit__(None, None, None)

    assert entered is obj.entered
    assert result is marker
    assert obj.exit_calls == 1


@pytest.mark.asyncio
async def test_plain_object_is_closed_and_awaitable_close_is_awaited():
    closed = False

    async def close():
        nonlocal closed
        closed = True

    obj = PlainObject(close_result=close())
    async with _AwaitableAsyncContextManager(asyncio.sleep(0, result=obj)):
        pass
    assert obj.closed == 1
    assert closed


@pytest.mark.asyncio
@pytest.mark.parametrize("value", [None, False, 0, ""])
async def test_falsey_resolved_values_are_cached(value):
    calls = 0

    async def source():
        nonlocal calls
        calls += 1
        return value

    wrapper = _AwaitableAsyncContextManager(source())
    assert await wrapper is value
    assert await wrapper is value
    assert calls == 1


@pytest.mark.asyncio
@pytest.mark.parametrize("preserve, active", [(False, False), (False, True), (True, True)])
async def test_cleanup_failure_behavior(preserve, active):
    body_error = ValueError("body")
    cleanup_error = RuntimeError("cleanup")
    obj = PlainObject(close_error=cleanup_error)

    with pytest.raises(type(body_error if active and preserve else cleanup_error)) as exc_info:
        async with _AwaitableAsyncContextManager(asyncio.sleep(0, result=obj), preserve_active_error=preserve):
            if active:
                raise body_error
    if active and preserve:
        assert exc_info.value is body_error


@pytest.mark.asyncio
async def test_source_failure_is_not_swallowed_or_retried():
    calls = 0
    error = RuntimeError("source")

    async def source():
        nonlocal calls
        calls += 1
        raise error

    wrapper = _AwaitableAsyncContextManager(source())
    with pytest.raises(RuntimeError, match="source") as first:
        await wrapper
    with pytest.raises(RuntimeError, match="source") as second:
        await wrapper
    assert first.value is second.value is error
    assert calls == 1


@pytest.mark.asyncio
async def test_context_entry_failure_is_not_swallowed():
    class FailingEntry:
        async def __aenter__(self):
            raise RuntimeError("entry")

        async def __aexit__(self, exc_type, exc_val, exc_tb):
            raise AssertionError("exit should not run")

    with pytest.raises(RuntimeError, match="entry"):
        async with _AwaitableAsyncContextManager(asyncio.sleep(0, result=FailingEntry())):
            pass


class FailingEntryObject:
    """A pydapper-owned resource whose ``__aenter__`` fails after the object already exists."""

    def __init__(self, close_error=None, awaitable_close=False):
        self.close_calls = 0
        self.exit_calls = 0
        self.close_error = close_error
        self.awaitable_close = awaitable_close

    async def __aenter__(self):
        raise RuntimeError("entry")

    async def __aexit__(self, exc_type, exc_val, exc_tb):
        self.exit_calls += 1

    def close(self):
        self.close_calls += 1
        if self.close_error:
            raise self.close_error
        return asyncio.sleep(0) if self.awaitable_close else None


@pytest.mark.asyncio
@pytest.mark.parametrize("awaitable_close", [False, True])
@pytest.mark.parametrize("preserve", [False, True])
async def test_entry_failure_closes_the_owned_object_without_exiting_it(awaitable_close, preserve):
    # pydapper created the wrapped object, so a failed __aenter__ may not leak it; __aexit__ stays
    # unbound for an object that never entered, so it is cleaned up exactly once
    obj = FailingEntryObject(awaitable_close=awaitable_close)

    with pytest.raises(RuntimeError, match="entry"):
        async with _AwaitableAsyncContextManager(asyncio.sleep(0, result=obj), preserve_active_error=preserve):
            raise AssertionError("body must not run")

    assert obj.close_calls == 1
    assert obj.exit_calls == 0


@pytest.mark.asyncio
async def test_entry_failure_survives_a_failing_close(caplog):
    obj = FailingEntryObject(close_error=ValueError("close failed"))

    with caplog.at_level(logging.DEBUG, logger="pydapper._context"):
        with pytest.raises(RuntimeError, match="entry"):
            async with _AwaitableAsyncContextManager(asyncio.sleep(0, result=obj), preserve_active_error=True):
                raise AssertionError("body must not run")

    assert obj.close_calls == 1
    records = debug_records(caplog)
    assert [record.getMessage() for record in records] == [
        "Discarding ValueError raised while cleaning up a pydapper-owned resource"
    ]
    assert records[0].exc_info[1] is obj.close_error


@pytest.mark.asyncio
async def test_entry_failure_of_an_object_without_close_is_a_no_op():
    class FailingEntryWithoutClose:
        async def __aenter__(self):
            raise RuntimeError("entry")

        async def __aexit__(self, exc_type, exc_val, exc_tb):
            raise AssertionError("exit should not run")

    with pytest.raises(RuntimeError, match="entry"):
        async with _AwaitableAsyncContextManager(
            asyncio.sleep(0, result=FailingEntryWithoutClose()), preserve_active_error=True
        ):
            raise AssertionError("body must not run")


@pytest.mark.asyncio
@pytest.mark.parametrize("base_error", [KeyboardInterrupt, SystemExit, asyncio.CancelledError, GeneratorExit])
@pytest.mark.parametrize("native_aexit", [False, True])
async def test_non_exception_cleanup_failure_is_never_discarded(base_error, native_aexit):
    # a BaseException that is not an Exception is not a resource problem: KeyboardInterrupt/SystemExit
    # are interpreter-level requests to stop and CancelledError/GeneratorExit are the runtime unwinding
    # this code on purpose. Swallowing a Ctrl-C loses it forever and swallowing a CancelledError breaks
    # asyncio.timeout and task cancellation, so all four outrank the active command error, which is not
    # lost either -- it survives as the propagating exception's __context__.
    body_error = ValueError("body")
    obj = ContextObject(exit_error=base_error()) if native_aexit else PlainObject(close_error=base_error())

    with pytest.raises(base_error) as exc_info:
        async with _AwaitableAsyncContextManager(asyncio.sleep(0, result=obj), preserve_active_error=True):
            raise body_error

    assert exc_info.value.__context__ is body_error


async def acquire_via(wrapper, path):
    """Consume ``wrapper`` through the path under test; both routes resolve through ``_resolve``."""
    if path == "await":
        return await wrapper
    async with wrapper as entered:
        return entered


async def parked_on_acquisition(wrapper, path="await"):
    """Start consuming ``wrapper`` and return with the task parked on the pending acquisition.

    Driving acquisition through a future the test completes itself is what makes the
    cancel-after-acquisition window deterministic: the task provably suspends on a pending future
    here, so the test -- not the scheduler -- decides when acquisition finishes and when the cancel
    lands. Nothing depends on how many event loop ticks a given Python version needs.
    """
    task = asyncio.create_task(acquire_via(wrapper, path))
    await asyncio.sleep(0)
    assert not task.done()
    return task


@pytest.mark.asyncio
@pytest.mark.parametrize("path", ["await", "async with"])
async def test_cancel_after_acquisition_completes_closes_the_abandoned_object(path):
    # acquisition runs as an independent future, so cancelling the awaiting task once that future has
    # already completed cannot cancel the acquisition: asyncio cannot cancel a completed future and
    # throws CancelledError in at the resume point instead. The object is therefore fully created and
    # nothing else refers to it -- the raising await binds nothing in the caller and a failed __aenter__
    # is never exited -- so without a best-effort close it leaks for the life of the connection.
    # __await__ shares _resolve with __aenter__, so both paths are exposed and both are covered here.
    obj = PlainObject()
    acquisition = asyncio.get_running_loop().create_future()
    wrapper = _AwaitableAsyncContextManager(acquisition, preserve_active_error=True)
    task = await parked_on_acquisition(wrapper, path)

    acquisition.set_result(obj)  # acquisition completes...
    task.cancel()  # ...and only then is its awaiter cancelled

    with pytest.raises(asyncio.CancelledError):
        await task

    # the cancellation still wins, and the object it stranded is closed exactly once
    assert acquisition.result() is obj
    assert obj.closed == 1


@pytest.mark.asyncio
@pytest.mark.parametrize("path", ["await", "async with"])
async def test_a_discarded_wrapper_never_hands_the_closed_object_out_again(path):
    # the resolution future still holds the closed object, so the wrapper has to refuse to resolve
    # again rather than serve a closed cursor to the next caller
    obj = PlainObject()
    acquisition = asyncio.get_running_loop().create_future()
    wrapper = _AwaitableAsyncContextManager(acquisition, preserve_active_error=True)
    task = await parked_on_acquisition(wrapper)

    acquisition.set_result(obj)
    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await task
    assert obj.closed == 1

    with pytest.raises(RuntimeError, match="spent and cannot resolve again"):
        await acquire_via(wrapper, path)
    assert obj.closed == 1


@pytest.mark.asyncio
@pytest.mark.parametrize("cancel_first", [True, False])
async def test_a_cancelled_awaiter_leaves_a_concurrently_awaited_object_alone(cancel_first):
    # _resolve may be awaited concurrently and only the cancelled awaiter fails, so closing on cancel
    # would trade the leak for a use-after-close. Both resume orders are covered: cancelling the first
    # awaiter leaves the second still pending, and cancelling the second means the first has already
    # resumed and taken ownership.
    obj = PlainObject()
    acquisition = asyncio.get_running_loop().create_future()
    wrapper = _AwaitableAsyncContextManager(acquisition)
    first = asyncio.create_task(acquire_via(wrapper, "await"))
    second = asyncio.create_task(acquire_via(wrapper, "await"))
    await asyncio.sleep(0)
    assert not first.done() and not second.done()

    acquisition.set_result(obj)
    cancelled, survivor = (first, second) if cancel_first else (second, first)
    cancelled.cancel()

    with pytest.raises(asyncio.CancelledError):
        await cancelled
    assert await survivor is obj
    assert obj.closed == 0
    assert await wrapper is obj


@pytest.mark.asyncio
async def test_cancel_before_acquisition_completes_cancels_the_acquisition_itself():
    # nothing was acquired, so there is nothing to close and the wrapper is not spent; the cancelled
    # acquisition future keeps reporting the cancellation to any later caller
    acquisition = asyncio.get_running_loop().create_future()
    wrapper = _AwaitableAsyncContextManager(acquisition, preserve_active_error=True)
    task = await parked_on_acquisition(wrapper)

    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await task

    assert acquisition.cancelled()
    with pytest.raises(asyncio.CancelledError):
        await wrapper


@pytest.mark.asyncio
async def test_discarding_an_abandoned_object_awaits_an_awaitable_close():
    closed = False

    async def close():
        nonlocal closed
        await asyncio.sleep(0)
        closed = True

    obj = PlainObject(close_result=close())
    acquisition = asyncio.get_running_loop().create_future()
    wrapper = _AwaitableAsyncContextManager(acquisition, preserve_active_error=True)
    task = await parked_on_acquisition(wrapper)

    acquisition.set_result(obj)
    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await task

    # the cancellation was already delivered, so a close that suspends still runs to completion before
    # the CancelledError is re-raised
    assert obj.closed == 1
    assert closed


@pytest.mark.asyncio
async def test_discarding_an_abandoned_object_survives_a_failing_close(caplog):
    close_error = ValueError("close failed")
    obj = PlainObject(close_error=close_error)
    acquisition = asyncio.get_running_loop().create_future()
    wrapper = _AwaitableAsyncContextManager(acquisition, preserve_active_error=True)
    task = await parked_on_acquisition(wrapper)

    acquisition.set_result(obj)
    task.cancel()
    with caplog.at_level(logging.DEBUG, logger="pydapper._context"):
        with pytest.raises(asyncio.CancelledError):
            await task

    # cleanup goes through the shared discard policy, so a failing close loses to the cancellation and
    # is recorded at DEBUG instead of vanishing
    assert obj.closed == 1
    records = debug_records(caplog)
    assert [record.getMessage() for record in records] == [
        "Discarding ValueError raised while cleaning up a pydapper-owned resource"
    ]
    assert records[0].exc_info[1] is close_error


@pytest.mark.asyncio
async def test_discarded_cleanup_error_is_recorded_at_debug(caplog):
    body_error = ValueError("body")
    cleanup_error = RuntimeError("cleanup")
    obj = ContextObject(exit_error=cleanup_error)

    with caplog.at_level(logging.DEBUG, logger="pydapper._context"):
        with pytest.raises(ValueError) as exc_info:
            async with _AwaitableAsyncContextManager(asyncio.sleep(0, result=obj), preserve_active_error=True):
                raise body_error

    # the command error is re-raised as the same object, so the cleanup failure is neither chained
    # onto it nor raised; the debug record is the only place it survives
    assert exc_info.value is body_error
    assert exc_info.value.__context__ is None
    records = debug_records(caplog)
    assert [record.getMessage() for record in records] == [
        "Discarding RuntimeError raised while cleaning up a pydapper-owned resource"
    ]
    assert records[0].exc_info[1] is cleanup_error
