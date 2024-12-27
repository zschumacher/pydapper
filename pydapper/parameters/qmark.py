from .base import ParamAdapter
from .enums import ParamStyle
import re


class QmarkAdapter(ParamAdapter[tuple]):
    def _convert_from_qmark(self) -> tuple[str, tuple]:
        return self.query, self.params

    def _convert_from_named(self) -> tuple[str, tuple]:
        placeholders = re.findall(ParamStyle.NAMED.pattern, self.query)
        normalized_query = self.query
        normalized_params = tuple(self.params[name.strip(":")] for name in placeholders)

        for placeholder in placeholders:
            normalized_query = normalized_query.replace(placeholder, "?", 1)

        return normalized_query, normalized_params

    def _convert_from_format(self) -> tuple[str, tuple]:
        normalized_query = re.sub(ParamStyle.FORMAT.pattern, "?", self.query)
        return normalized_query, self.params

    def _convert_from_numeric(self) -> tuple[str, tuple]:
        normalized_query = re.sub(ParamStyle.NUMERIC.pattern, "?", self.query)
        return normalized_query, self.params

    def _convert_from_pyformat(self) -> tuple[str, tuple]:
        normalized_query = re.sub(ParamStyle.PYFORMAT.pattern, "?", self.query)
        return normalized_query, tuple(self.params.values())
