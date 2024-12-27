from .base import ParamAdapter
from .enums import ParamStyle
import re


class NamedAdapter(ParamAdapter[dict]):
    def _convert_from_qmark(self) -> tuple[str, dict]:
        placeholders = re.findall(ParamStyle.QMARK.pattern, self.query)
        normalized_query = self.query
        normalized_params = {}

        for idx, placeholder in enumerate(placeholders):
            param_name = f"param_{idx}"
            normalized_query = normalized_query.replace(placeholder, f":{param_name}", 1)
            normalized_params[param_name] = self.params[idx]

        return normalized_query, normalized_params

    def _convert_from_named(self) -> tuple[str, dict]:
        return self.query, self.params  # Already in named style

    def _convert_from_format(self) -> tuple[str, dict]:
        placeholders = re.findall(ParamStyle.FORMAT.pattern, self.query)
        normalized_query = self.query
        normalized_params = {}

        for idx, placeholder in enumerate(placeholders):
            param_name = f"param_{idx}"
            normalized_query = normalized_query.replace(placeholder, f":{param_name}", 1)
            normalized_params[param_name] = self.params[idx]

        return normalized_query, normalized_params

    def _convert_from_numeric(self) -> tuple[str, dict]:
        placeholders = re.findall(ParamStyle.NUMERIC.pattern, self.query)
        normalized_query = self.query
        normalized_params = {}

        for idx, placeholder in enumerate(placeholders):
            param_name = f"param_{idx}"
            normalized_query = normalized_query.replace(placeholder, f":{param_name}", 1)
            normalized_params[param_name] = self.params[idx]

        return normalized_query, normalized_params

    def _convert_from_pyformat(self) -> tuple[str, dict]:
        def grab_param_name(m):
            pattern = r"%\(([a-zA-Z_][a-zA-Z0-9_]*)\)"
            value = m.group(0)
            extracted = re.match(pattern, value)
            if not extracted:  # pragma: no cover
                raise ValueError(f"Invalid pyformat placeholder: {m.group(0)}")
            return f":{extracted.group(1)}"

        normalized_query = re.sub(
            ParamStyle.PYFORMAT.pattern,
            grab_param_name,
            self.query,
        )
        return normalized_query, self.params
