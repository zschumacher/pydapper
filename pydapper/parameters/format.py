from .base import ParamAdapter
from .enums import ParamStyle
import re


class FormatAdapter(ParamAdapter[tuple]):
    def _convert_from_qmark(self) -> tuple[str, tuple]:
        normalized_query = re.sub(ParamStyle.QMARK.pattern, "%s", self.query)
        return normalized_query, self.input_params

    def _convert_from_named(self) -> tuple[str, tuple]:
        placeholders = re.findall(ParamStyle.NAMED.pattern, self.query)
        normalized_query = self.query
        if isinstance(self.input_params, dict):
            normalized_params = tuple(self.input_params[name.strip(":")] for name in placeholders)
        else:
            normalized_params = tuple(getattr(self.input_params, name.strip(":")) for name in placeholders)

        for placeholder in placeholders:
            normalized_query = normalized_query.replace(placeholder, "%s", 1)

        return normalized_query, normalized_params

    def _convert_from_format(self) -> tuple[str, tuple]:
        return self.query, self.input_params

    def _convert_from_numeric(self) -> tuple[str, tuple]:
        normalized_query = re.sub(ParamStyle.NUMERIC.pattern, "%s", self.query)
        return normalized_query, self.input_params

    def _convert_from_pyformat(self) -> tuple[str, tuple]:
        placeholders = re.findall(ParamStyle.PYFORMAT.pattern, self.query)
        normalized_query = self.query
        if isinstance(self.input_params, dict):
            normalized_params = tuple(self.input_params[name.lstrip("%(").rstrip(")s")] for name in placeholders)
        else:
            normalized_params = tuple(getattr(self.input_params, name.lstrip("%(").rstrip(")s")) for name in placeholders)

        for placeholder in placeholders:
            normalized_query = normalized_query.replace(placeholder, "%s", 1)

        return normalized_query, normalized_params
