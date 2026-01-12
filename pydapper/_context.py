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


class CoroContextManager(Coroutine[Any, Any, _TObj], Generic[_TObj]):

    __slots__ = ("_coro", "_obj")

    def __init__(
        self,
        coro: Coroutine[Any, Any, _TObj],
        obj: _TObj = None,
    ):
        self._coro = coro
        self._obj = obj

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
        if hasattr(self._obj, "__aenter__"):  # pragma: no branch
            await self._obj.__aenter__()  # type: ignore
        assert self._obj
        return self._obj

    async def __aexit__(self, exc_type, exc_val, exc_tb):
        if hasattr(self._obj, "__aexit__"):  # pragma: no branch
            await self._obj.__aexit__(exc_type, exc_val, exc_tb)  # type: ignore
