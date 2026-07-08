from dataclasses import dataclass
from typing import Any
from typing import Callable
from typing import Dict
from typing import Sequence
from typing import Tuple
from typing import TypeAlias
from typing import TypeVar
from typing import Union
from typing import overload

from .exceptions import DuplicateColumnException
from .utils import validate_no_duplicate_columns

_MapperT = TypeVar("_MapperT")

Mapper: TypeAlias = Callable[["RawRow"], _MapperT]


@dataclass(frozen=True)
class RawRow:
    columns: Tuple[str, ...]
    values: Tuple[Any, ...]

    def __init__(self, columns: Sequence[str], values: Sequence[Any]) -> None:
        column_tuple = tuple(columns)
        value_tuple = tuple(values)
        if len(column_tuple) != len(value_tuple):
            raise ValueError("RawRow columns and values must have the same length.")

        object.__setattr__(self, "columns", column_tuple)
        object.__setattr__(self, "values", value_tuple)

    def as_dict(self) -> Dict[str, Any]:
        validate_no_duplicate_columns(self.columns)
        return dict(zip(self.columns, self.values))

    @overload
    def __getitem__(self, key: int) -> Any: ...

    @overload
    def __getitem__(self, key: str) -> Any: ...

    def __getitem__(self, key: Union[int, str]) -> Any:
        if isinstance(key, str):
            return self._get_by_column_name(key)
        return self.values[key]

    def _get_by_column_name(self, key: str) -> Any:
        indexes = tuple(index for index, column in enumerate(self.columns) if column == key)
        if not indexes:
            raise KeyError(key)
        if len(indexes) > 1:
            raise DuplicateColumnException(
                columns=self.columns,
                duplicate_columns=(key,),
                duplicate_indexes=indexes,
            )
        return self.values[indexes[0]]
