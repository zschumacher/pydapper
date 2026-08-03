from collections.abc import Sequence
from typing import Any
from typing import Tuple


class PyDapperException(Exception):
    pass


class NoResultException(PyDapperException):
    pass


class MoreThanOneResultException(PyDapperException):
    pass


class MissingParameterException(PyDapperException):
    pass


class InvalidParameterShapeException(PyDapperException):
    pass


class MultipleStatementsError(PyDapperException):
    def __init__(self, sql: str, separator_index: int) -> None:
        self.sql = sql
        self.separator_index = separator_index
        super().__init__(
            f"A command executes exactly one SQL statement, but a statement separator was found at "
            f"character index {separator_index}. A single trailing ';' is allowed. Run scripts and "
            "multi-statement blocks against the DBAPI connection directly."
        )

    def __reduce__(self) -> Tuple[Any, Tuple[Any, ...]]:
        # the default Exception reduction replays __init__ with the built message as its only
        # argument, which this two-argument signature rejects; without this the error cannot cross
        # a process boundary (ProcessPoolExecutor, celery) or survive copy.copy/deepcopy
        return (self.__class__, (self.sql, self.separator_index))


class UnsupportedFeatureError(PyDapperException):
    pass


class RowMappingException(PyDapperException):
    pass


class DuplicateColumnException(RowMappingException):
    def __init__(
        self,
        columns: Sequence[str],
        duplicate_columns: Sequence[str],
        duplicate_indexes: Sequence[int],
    ) -> None:
        self.columns = tuple(columns)
        self.duplicate_columns = tuple(duplicate_columns)
        self.duplicate_indexes = tuple(duplicate_indexes)
        duplicate_names = ", ".join(repr(column) for column in self.duplicate_columns)
        super().__init__(
            f"Duplicate column names are not supported for dict row mapping: {duplicate_names}. "
            "Alias duplicate columns in the query."
        )
