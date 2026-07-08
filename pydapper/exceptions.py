from collections.abc import Sequence


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
