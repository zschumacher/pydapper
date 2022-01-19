import importlib
from typing import Any


def safe_getattr(obj: Any, key: str) -> Any:
    try:
        if isinstance(obj, dict):
            return obj[key]
        return getattr(obj, key)
    except AttributeError:
        raise AttributeError(f"Attribute {key!r} can not be accessed on {obj!r} or does not exist")
    except KeyError:
        raise KeyError(f"Key {key!r} can not be accessed on {obj!r} or does not exist")


def database_row_to_dict(col_names: list[str], row: tuple[Any]) -> dict[str, Any]:
    return dict(zip(col_names, row))


def serialize_dict_row(model: Any, row: dict):
    if model == dict:
        return row
    return model(**row)


def get_col_names(cursor: Any) -> list[str]:
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
