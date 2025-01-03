from typing import TypeVar, Generic, Sequence
from ..parameters.enums import ParamStyle

CursorType = TypeVar("CursorType")


class CursorProxy(Generic[CursorType]):
    def __init__(self, cursor: CursorType, param_styles: Sequence[ParamStyle]):
        self.cursor = cursor
        self.param_styles = param_styles

    @property
    def description(self):
        return self.cursor.description

    def callproc(self, procname: str, parameters: dict | Sequence[str]):
        return self.cursor.callproc(procname, parameters=parameters)

    def close(self):
        return self.cursor.close()

    def execute(self, operation: str, parameters: dict | Sequence[str]):
        return self.cursor.execute(operation, parameters=parameters)

    def executemany(self, operation: str, parameters: dict | Sequence[str] = None):
        return self.cursor.executemany(operation, parameters=parameters)

    def fetchone(self):
        return self.cursor.fetchone()

    def fetchall(self):
        return self.cursor.fetchall()

    def fetchmany(self, size: int | None = None):
        return self.cursor.fetchmany(size)

    def __enter__(self):
        ...

    def __exit__(self, exc_type, exc_val, exc_tb):
        ...
