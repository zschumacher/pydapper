import importlib
from collections.abc import Mapping
from typing import TYPE_CHECKING
from typing import Any
from typing import Callable
from typing import Dict
from typing import List
from typing import Sequence
from typing import Tuple
from typing import Type
from typing import TypeVar
from typing import Union
from typing import overload

from .exceptions import DuplicateColumnException

if TYPE_CHECKING:
    _T = TypeVar("_T")


def safe_getattr(obj: Any, key: str) -> Any:
    try:
        if isinstance(obj, Mapping):
            return obj[key]
        return getattr(obj, key)
    except AttributeError:
        raise AttributeError(f"Attribute {key!r} can not be accessed on {obj!r} or does not exist")
    except KeyError:
        raise KeyError(f"Key {key!r} can not be accessed on {obj!r} or does not exist")


def _get_duplicate_column_data(col_names: Sequence[str]) -> Tuple[Tuple[str, ...], Tuple[int, ...]]:
    column_indexes: Dict[str, List[int]] = {}
    for index, col_name in enumerate(col_names):
        column_indexes.setdefault(col_name, []).append(index)

    duplicate_columns = tuple(col_name for col_name, indexes in column_indexes.items() if len(indexes) > 1)
    duplicate_column_set = set(duplicate_columns)
    duplicate_indexes = tuple(index for index, col_name in enumerate(col_names) if col_name in duplicate_column_set)
    return duplicate_columns, duplicate_indexes


def validate_no_duplicate_columns(col_names: Sequence[str]) -> None:
    duplicate_columns, duplicate_indexes = _get_duplicate_column_data(col_names)
    if duplicate_columns:
        raise DuplicateColumnException(
            columns=tuple(col_names),
            duplicate_columns=duplicate_columns,
            duplicate_indexes=duplicate_indexes,
        )


def database_row_to_dict(col_names: List[str], row: Tuple[Any]) -> Dict[str, Any]:
    return dict(zip(col_names, row))


@overload
def serialize_dict_row(model: Type[Dict], row: Dict[str, Any]) -> Dict[str, Any]: ...


@overload
def serialize_dict_row(model: Union[Type["_T"], Callable[..., "_T"]], row: Dict[str, Any]) -> "_T": ...


def serialize_dict_row(model, row):
    if model == dict:
        return row
    return model(**row)


def get_col_names(cursor: Any) -> List[str]:
    return [i[0] for i in cursor.description]


def import_dbapi_module(dbapi_name: str):
    try:
        dbapi = importlib.import_module(dbapi_name)
    except ImportError:
        raise ImportError(f"Could not import module {dbapi_name}.  Try `pip install pydapper[{dbapi_name}]`")
    return dbapi


def import_module_obj_path(module_obj_path: str):
    if ":" not in module_obj_path:
        raise ValueError("Must specify object to import from module using colon ':'")
    module_name, obj_name = module_obj_path.split(":")
    module = importlib.import_module(module_name)
    return getattr(module, obj_name)
