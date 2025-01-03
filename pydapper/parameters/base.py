from abc import ABC, abstractmethod
from typing import Generic
from typing import TypeVar
from .enums import ParamStyle

ParamType = TypeVar("ParamType")


class ParamAdapter(Generic[ParamType]):
    def __init__(self, query: str, params: dict | tuple):
        self.query = query
        self.params = params
        self.query_style = ParamStyle.detect(query)

    @abstractmethod
    def _convert_from_qmark(self) -> tuple[str, ParamType]: ...

    @abstractmethod
    def _convert_from_named(self) -> tuple[str, ParamType]: ...

    @abstractmethod
    def _convert_from_format(self) -> tuple[str, ParamType]: ...

    @abstractmethod
    def _convert_from_numeric(self) -> tuple[str, ParamType]: ...

    @abstractmethod
    def _convert_from_pyformat(self) -> tuple[str, ParamType]: ...

    def normalize(self) -> tuple[str, dict | tuple]:
        if self.query_style == ParamStyle.QMARK:
            return self._convert_from_qmark()
        elif self.query_style == ParamStyle.NAMED:
            return self._convert_from_named()
        elif self.query_style == ParamStyle.FORMAT:
            return self._convert_from_format()
        elif self.query_style == ParamStyle.NUMERIC:
            return self._convert_from_numeric()
        elif self.query_style == ParamStyle.PYFORMAT:
            return self._convert_from_pyformat()
        else:
            raise ValueError(f"Unsupported parameter style: {self.query_style}")
