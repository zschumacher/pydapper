from .base import ParamAdapter
from .enums import ParamStyle
import re


class NumericAdapter(ParamAdapter[tuple]):
    def _convert_from_qmark(self) -> tuple[str, tuple]:
        placeholder_index = 0

        def new_placeholder(_):
            nonlocal placeholder_index
            placeholder_index += 1
            return f":{placeholder_index}"

        normalized_query = re.sub(
            ParamStyle.QMARK.pattern,
            new_placeholder,
            self.query,
        )
        placeholder_index += self.query.count("?")
        return normalized_query, self.params

    def _convert_from_named(self) -> tuple[str, tuple]:
        placeholders = re.findall(ParamStyle.NAMED.pattern, self.query)
        normalized_query = self.query
        normalized_params = []

        for idx, placeholder in enumerate(placeholders):
            normalized_query = normalized_query.replace(placeholder, f":{idx + 1}", 1)
            normalized_params.append(self.params[placeholder.strip(":")])

        return normalized_query, tuple(normalized_params)

    def _convert_from_format(self) -> tuple[str, tuple]:
        placeholder_index = 0

        def new_placeholder(_):
            nonlocal placeholder_index
            placeholder_index += 1
            return f":{placeholder_index}"

        normalized_query = re.sub(
            ParamStyle.FORMAT.pattern,
            new_placeholder,
            self.query,
        )
        return normalized_query, self.params

    def _convert_from_numeric(self) -> tuple[str, tuple]:
        return self.query, self.params

    def _convert_from_pyformat(self) -> tuple[str, tuple]:
        placeholders = re.findall(ParamStyle.PYFORMAT.pattern, self.query)
        normalized_query = self.query
        normalized_params = []

        for idx, placeholder in enumerate(placeholders):
            normalized_query = normalized_query.replace(placeholder, f":{idx + 1}", 1)
            normalized_params.append(self.params[placeholder.strip("%()s")])

        return normalized_query, tuple(normalized_params)
