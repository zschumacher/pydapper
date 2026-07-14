import asyncio

import pytest

from pydapper._context import _AwaitableAsyncContextManager

pytestmark = pytest.mark.core


class ContextObject:
    def __init__(self, exit_result=False, exit_error=None):
        self.exit_result = exit_result
        self.exit_error = exit_error
        self.entered = object()
        self.exit_calls = 0

    async def __aenter__(self):
        return self.entered

    async def __aexit__(self, exc_type, exc_val, exc_tb):
        self.exit_calls += 1
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
        async with _AwaitableAsyncContextManager(asyncio.sleep(0, result=obj)):
            raise ValueError("body")
    except ValueError:
        caught = True
    assert caught is not suppresses


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
