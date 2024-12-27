from enum import Enum
import re
from functools import lru_cache


class ParamStyle(Enum):
    QMARK = ("qmark", r"\?")
    NAMED = ("named", r":[a-zA-Z_]\w*")
    FORMAT = ("format", r"%s")
    NUMERIC = ("numeric", r":\d+")
    PYFORMAT = ("pyformat", r"%\([a-zA-Z_][a-zA-Z0-9_]*\)s")

    def __init__(self, style_name: str, pattern: str):
        self.style_name = style_name
        self.pattern = pattern

    @staticmethod
    @lru_cache(maxsize=128)
    def detect(query: str) -> "ParamStyle | None":
        for style in ParamStyle:
            if re.search(style.pattern, query):
                return style
        return None
