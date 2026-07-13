import asyncio

import pytest

from pydapper._context import CoroContextManager


class MyObject:
    def __init__(self):
        self.some_value = 0

    async def __aenter__(self):
        await asyncio.sleep(0.1)
        self.some_value = 1
        return self

    async def __aexit__(self, exc_type, exc_val, exc_tb):
        await asyncio.sleep(0.1)
        self.some_value = 0

    @classmethod
    async def async_constructor(cls):
        await asyncio.sleep(0.1)
        return cls()


class PlainObject:
    def __init__(self, close_result=None):
        self.closed = False
        self.close_result = close_result

    def close(self):
        self.closed = True
        return self.close_result


@pytest.mark.asyncio
class TestCoroContextManager:
    async def test__init__(self):
        sentinel = object()
        coro = asyncio.sleep(0.1)
        cm = CoroContextManager(coro, obj=sentinel)
        assert cm._coro is coro
        assert cm._obj is sentinel
        await coro

    async def test_context_manager(self):
        async with CoroContextManager(MyObject.async_constructor()) as myobj:
            assert isinstance(myobj, MyObject)
            assert myobj.some_value == 1
        assert myobj.some_value == 0

    async def test_plain_object_is_closed(self):
        obj = PlainObject()

        async with CoroContextManager(asyncio.sleep(0, result=obj)) as entered:
            assert entered is obj

        assert obj.closed is True

    async def test_plain_object_awaits_close(self):
        closed = False

        async def close():
            nonlocal closed
            closed = True

        obj = PlainObject(close())

        async with CoroContextManager(asyncio.sleep(0, result=obj)):
            pass

        assert obj.closed is True
        assert closed is True
