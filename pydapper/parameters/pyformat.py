from .base import ParamAdapter
from .enums import ParamStyle
import re


class PyformatAdapter(ParamAdapter[dict]):
    def _convert_from_qmark(self) -> tuple[str, dict]:
        placeholders = re.findall(ParamStyle.QMARK.pattern, self.query)
        normalized_query = self.query
        normalized_params = {}

        for idx, placeholder in enumerate(placeholders):
            param_name = f"param_{idx}"
            normalized_query = normalized_query.replace(placeholder, f"%({param_name})s", 1)
            normalized_params[param_name] = self.params[idx]

        return normalized_query, normalized_params

    def _convert_from_named(self) -> tuple[str, dict]:
        normalized_query = re.sub(
            ParamStyle.NAMED.pattern,
            lambda m: f"%({m.group(0).strip(':')})s",
            self.query,
        )
        return normalized_query, self.params

    def _convert_from_format(self) -> tuple[str, dict]:
        placeholders = re.findall(ParamStyle.FORMAT.pattern, self.query)
        normalized_query = self.query
        normalized_params = {}

        for idx, placeholder in enumerate(placeholders):
            param_name = f"param_{idx}"
            normalized_query = normalized_query.replace(placeholder, f"%({param_name})s", 1)
            normalized_params[param_name] = self.params[idx]

        return normalized_query, normalized_params

    def _convert_from_numeric(self) -> tuple[str, dict]:
        placeholders = re.findall(ParamStyle.NUMERIC.pattern, self.query)
        normalized_query = self.query
        normalized_params = {}

        for idx, placeholder in enumerate(placeholders):
            param_name = f"param_{idx}"
            normalized_query = normalized_query.replace(placeholder, f"%({param_name})s", 1)
            normalized_params[param_name] = self.params[idx]

        return normalized_query, normalized_params

    def _convert_from_pyformat(self) -> tuple[str, dict]:
        return self.query, self.params  # Already in pyformat style
