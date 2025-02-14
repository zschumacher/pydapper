from enum import Enum, auto
import re
from functools import lru_cache
import typing as t

def _is_dot_accessible(obj: t.Any) -> bool:
    return hasattr(obj, '__getattr__') or (
        not hasattr(obj, '__getitem__') and hasattr(obj, '__dict__')
    )

class ParamObjectType(Enum):
    POSITIONAL = auto()
    OBJECT = auto()

    def validate(self, params) -> bool:
        if self == ParamObjectType.POSITIONAL:
            return isinstance(params, tuple)

        return isinstance(params, dict) or _is_dot_accessible(params)



class ParamStyle(Enum):
    QMARK = ("qmark", r"\?", ParamObjectType.POSITIONAL)
    NAMED = ("named", r":[a-zA-Z_]\w*", ParamObjectType.OBJECT)
    FORMAT = ("format", r"%s", ParamObjectType.POSITIONAL)
    NUMERIC = ("numeric", r":\d+", ParamObjectType.OBJECT)
    PYFORMAT = ("pyformat", r"%\([a-zA-Z_][a-zA-Z0-9_]*\)s", ParamObjectType.OBJECT)

    def __init__(self, style_name: str, pattern: str, param_object_type: ParamObjectType):
        self.style_name = style_name
        self.pattern = pattern
        self.param_object_type = param_object_type



    @staticmethod
    @lru_cache(maxsize=128)
    def detect(query: str) -> "ParamStyle | None":
        for style in ParamStyle:
            if re.search(style.pattern, query):
                return style
        return None

