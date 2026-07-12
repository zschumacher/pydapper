from collections.abc import Mapping
from dataclasses import dataclass
from types import MappingProxyType
from typing import TYPE_CHECKING
from typing import Any
from typing import Callable
from typing import Dict
from typing import List
from typing import Optional
from typing import Sequence
from typing import Tuple
from typing import TypeAlias
from typing import TypeVar
from typing import Union
from typing import overload

from .exceptions import DuplicateColumnException

_MapperT = TypeVar("_MapperT")

Mapper: TypeAlias = Callable[["RawRow"], _MapperT]


@dataclass(frozen=True)
class RawRow:
    columns: Tuple[str, ...]
    values: Tuple[Any, ...]

    if TYPE_CHECKING:
        _column_indexes: Optional[Mapping[str, Tuple[int, ...]]]

    def __init__(self, columns: Sequence[str], values: Sequence[Any]) -> None:
        column_tuple = tuple(columns)
        value_tuple = tuple(values)
        if len(column_tuple) != len(value_tuple):
            raise ValueError("RawRow columns and values must have the same length.")

        object.__setattr__(self, "columns", column_tuple)
        object.__setattr__(self, "values", value_tuple)
        object.__setattr__(self, "_column_indexes", None)

    def __getstate__(self) -> Dict[str, Any]:
        return {"columns": self.columns, "values": self.values}

    def __setstate__(self, state: Dict[str, Any]) -> None:
        object.__setattr__(self, "columns", state["columns"])
        object.__setattr__(self, "values", state["values"])
        object.__setattr__(self, "_column_indexes", None)

    def as_dict(self) -> Dict[str, Any]:
        column_indexes = self._get_column_indexes()
        duplicate_columns = tuple(column for column, indexes in column_indexes.items() if len(indexes) > 1)
        if duplicate_columns:
            duplicate_indexes = tuple(
                index for index, column in enumerate(self.columns) if len(column_indexes[column]) > 1
            )
            raise DuplicateColumnException(
                columns=self.columns,
                duplicate_columns=duplicate_columns,
                duplicate_indexes=duplicate_indexes,
            )
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
        indexes = self._get_column_indexes().get(key)
        if not indexes:
            raise KeyError(key)
        if len(indexes) > 1:
            raise DuplicateColumnException(
                columns=self.columns,
                duplicate_columns=(key,),
                duplicate_indexes=indexes,
            )
        return self.values[indexes[0]]

    def _get_column_indexes(self) -> Mapping[str, Tuple[int, ...]]:
        column_indexes = self._column_indexes
        if column_indexes is None:
            index_lists: Dict[str, List[int]] = {}
            for index, column in enumerate(self.columns):
                index_lists.setdefault(column, []).append(index)
            column_indexes = MappingProxyType({column: tuple(indexes) for column, indexes in index_lists.items()})
            object.__setattr__(self, "_column_indexes", column_indexes)
        return column_indexes
