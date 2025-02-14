from abc import abstractmethod
import typing as t
from ..types import SingleParamType
from .enums import ParamStyle

OutputParamType = t.TypeVar("OutputParamType")

class ParamAdapter(t.Generic[OutputParamType]):
    def __init__(self, query: str, input_params: SingleParamType):

        self.query = query
        self.input_params = input_params
        self.query_style = ParamStyle.detect(query)

    @abstractmethod
    def _convert_from_qmark(self) -> tuple[str, OutputParamType]: ...

    @abstractmethod
    def _convert_from_named(self) -> tuple[str, OutputParamType]: ...

    @abstractmethod
    def _convert_from_format(self) -> tuple[str, OutputParamType]: ...

    @abstractmethod
    def _convert_from_numeric(self) -> tuple[str, OutputParamType]: ...

    @abstractmethod
    def _convert_from_pyformat(self) -> tuple[str, OutputParamType]: ...

    def normalize(self) -> tuple[str, dict | tuple]:
        from .enums import ParamStyle

        if self.query_style == ParamStyle.QMARK:
            if not self.query_style.param_object_type.validate(self.input_params):
                raise ValueError("Input query is using qmark paramstyle, but didn't pass params as a tuple")
            return self._convert_from_qmark()

        elif self.query_style == ParamStyle.NAMED:
            if not self.query_style.param_object_type.validate(self.input_params):
                raise ValueError(
                    "Input query is using named paramstyle, but didn't pass params as a dict or object with attr access"
                )
            return self._convert_from_named()

        elif self.query_style == ParamStyle.FORMAT:
            if not self.query_style.param_object_type.validate(self.input_params):
                raise ValueError("Input query is using format paramstyle, but didn't pass params as a tuple")
            return self._convert_from_format()

        elif self.query_style == ParamStyle.NUMERIC:
            if not self.query_style.param_object_type.validate(self.input_params):
                raise ValueError("Input query is using numeric paramstyle, but didn't pass params as a tuple")
            return self._convert_from_numeric()

        elif self.query_style == ParamStyle.PYFORMAT:
            if not self.query_style.param_object_type.validate(self.input_params):
                raise ValueError("Input query is using pyformat paramstyle, but didn't pass params as a tuple")
            return self._convert_from_pyformat()

        else:
            raise ValueError(f"Unsupported parameter style: {self.query_style}")
