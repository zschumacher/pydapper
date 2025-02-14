from typing import TypeVar, Generic, Sequence
from ..parameters.enums import ParamStyle

CursorType = TypeVar("CursorType")


class CursorProxy(Generic[CursorType]):
    supported_param_styles: list[ParamStyle] = ...

    def __init__(self, cursor: CursorType):
        self.cursor = cursor

    def __init_subclass__(cls, **kwargs):
        assert hasattr(
            cls, "supported_param_styles"
        ), "CursorProxy subclass must declare supported_param_styles"

    @property
    def description(self):
        return self.cursor.description

    @property
    def rowcount(self):
        return self.cursor.rowcount

    def callproc(self, procname: str, parameters: dict | Sequence[str]):
        return self.cursor.callproc(procname, parameters)

    def close(self):
        return self.cursor.close()

    def execute(self, operation: str, parameters: dict | Sequence[str]):
        if parameters:
            return self.cursor.execute(operation, parameters)
        return self.cursor.execute(operation)

    def executemany(self, operation: str, parameters: dict | Sequence[str] = None):
        return self.cursor.executemany(operation, parameters)

    def fetchone(self):
        return self.cursor.fetchone()

    def fetchall(self):
        return self.cursor.fetchall()

    def fetchmany(self, size: int | None = None):
        return self.cursor.fetchmany(size)

    def __enter__(self): ...

    def __exit__(self, exc_type, exc_val, exc_tb): ...
