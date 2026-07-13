from inspect import isawaitable
from types import TracebackType
from typing import Any
from typing import Coroutine
from typing import Generator
from typing import Generic
from typing import Optional
from typing import Type
from typing import TypeVar
from typing import Union

_TObj = TypeVar("_TObj")


async def _await_if_needed(value: Any) -> Any:
    return await value if isawaitable(value) else value


class CoroContextManager(Coroutine[Any, Any, _TObj], Generic[_TObj]):
    """Wrap an awaitable resource for use with ``async with``."""

    __slots__ = ("_coro", "_obj", "_entered_obj", "_aexit", "_preserve_active_error")

    def __init__(
        self,
        coro: Coroutine[Any, Any, _TObj],
        obj: _TObj = None,
        *,
        preserve_active_error: bool = False,
    ):
        self._coro = coro
        self._obj = obj
        self._entered_obj = obj
        self._aexit = None
        self._preserve_active_error = preserve_active_error

    def send(self, value: Any) -> "Any":  # pragma: no cover
        return self._coro.send(value)

    def throw(  # type: ignore
        self,
        typ: Type[BaseException],
        val: Optional[Union[BaseException, object]] = None,
        tb: Optional[TracebackType] = None,
    ) -> Any:  # pragma: no cover
        if val is None:
            return self._coro.throw(typ)
        if tb is None:
            return self._coro.throw(typ, val)
        return self._coro.throw(typ, val, tb)

    def close(self) -> None:  # pragma: no cover
        self._coro.close()

    def __await__(self) -> Generator[Any, None, _TObj]:  # pragma: no cover
        return self._coro.__await__()

    async def __aenter__(self) -> _TObj:
        if self._obj is None:  # pragma: no branch
            self._obj = await self._coro

        enter = getattr(type(self._obj), "__aenter__", None)
        aexit = getattr(type(self._obj), "__aexit__", None)
        self._aexit = None
        if callable(enter) and callable(aexit):  # pragma: no branch
            self._entered_obj = await _await_if_needed(enter(self._obj))
            self._aexit = aexit
        else:
            self._entered_obj = self._obj
        return self._entered_obj

    async def __aexit__(self, exc_type, exc_val, exc_tb):
        try:
            if self._aexit is not None:
                return await _await_if_needed(self._aexit(self._obj, exc_type, exc_val, exc_tb))

            close = getattr(self._obj, "close", None)
            if callable(close):
                await _await_if_needed(close())
        except BaseException:
            if self._preserve_active_error and exc_type is not None:
                return False
            raise
