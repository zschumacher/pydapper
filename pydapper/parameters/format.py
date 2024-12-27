from .base import ParamAdapter
from .enums import ParamStyle
import re


class FormatAdapter(ParamAdapter[tuple]):
    def _convert_from_qmark(self) -> tuple[str, tuple]:
        normalized_query = re.sub(ParamStyle.QMARK.pattern, "%s", self.query)
        return normalized_query, self.params

    def _convert_from_named(self) -> tuple[str, tuple]:
        placeholders = re.findall(ParamStyle.NAMED.pattern, self.query)
        normalized_query = self.query
        normalized_params = tuple(self.params[name.strip(":")] for name in placeholders)

        for placeholder in placeholders:
            normalized_query = normalized_query.replace(placeholder, "%s", 1)

        return normalized_query, normalized_params

    def _convert_from_format(self) -> tuple[str, tuple]:
        return self.query, self.params  # Already in format style

    def _convert_from_numeric(self) -> tuple[str, tuple]:
        normalized_query = re.sub(ParamStyle.NUMERIC.pattern, "%s", self.query)
        return normalized_query, self.params

    def _convert_from_pyformat(self) -> tuple[str, tuple]:
        normalized_query = re.sub(ParamStyle.PYFORMAT.pattern, "%s", self.query)
        return normalized_query, tuple(self.params.values())

