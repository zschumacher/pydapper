from typing import List
from typing import Optional
from typing import Tuple

PlaceholderSpan = Tuple[int, int, str]


def _is_placeholder_name_start(char: str) -> bool:
    return ("A" <= char <= "Z") or ("a" <= char <= "z") or char == "_"


def _is_placeholder_name_char(char: str) -> bool:
    return _is_placeholder_name_start(char) or ("0" <= char <= "9")


def _skip_quoted_sql_text(sql: str, start: int, quote: str) -> int:
    index = start + 1
    while index < len(sql):
        if sql[index] == "\\" and index + 1 < len(sql):
            index += 2
            continue

        if sql[index] == quote:
            if index + 1 < len(sql) and sql[index + 1] == quote:
                index += 2
                continue
            return index + 1
        index += 1
    return len(sql)


def _skip_line_comment(sql: str, start: int) -> int:
    index = start + 2
    while index < len(sql) and sql[index] not in "\r\n":
        index += 1
    return index


def _skip_block_comment(sql: str, start: int) -> int:
    index = start + 2
    while index + 1 < len(sql):
        if sql[index] == "*" and sql[index + 1] == "/":
            return index + 2
        index += 1
    return len(sql)


#: Whitespace allowed after a trailing ``;``. Deliberately much narrower than ``str.isspace()``:
#: SQLite treats a trailing ``U+000B`` and every Unicode space as the start of a *second* statement,
#: so counting those as whitespace would let one through. This is exactly SQLite's and PostgreSQL's
#: set; MySQL additionally allows ``U+000B``, which is refused here. Erring narrow is the safe
#: direction -- anything outside this set ends the continuation scan, i.e. refuses rather than admits.
_SQL_WHITESPACE = " \t\n\r\f"


def _skip_whitespace_and_comments(sql: str, start: int) -> int:
    index = start
    while index < len(sql):
        char = sql[index]

        if char in _SQL_WHITESPACE:
            index += 1
            continue

        if char == "-" and index + 1 < len(sql) and sql[index + 1] == "-":
            index = _skip_line_comment(sql, index)
            continue

        if char == "/" and index + 1 < len(sql) and sql[index + 1] == "*":
            index = _skip_block_comment(sql, index)
            continue

        break
    return index


def _is_malformed_placeholder_boundary(char: str) -> bool:
    return char.isspace() or char in "',;()[]{}:=<>+*/|&~!@#%^"


def _skip_question_mark_run(sql: str, start: int) -> int:
    index = start
    while index < len(sql) and sql[index] == "?":
        index += 1
    return index


def _skip_malformed_placeholder(sql: str, start: int) -> int:
    index = start
    while index < len(sql):
        if sql[index] == '"':
            return index

        if sql[index] == "-" and index + 1 < len(sql) and sql[index + 1] == "-":
            return index

        if sql[index] == "/" and index + 1 < len(sql) and sql[index + 1] == "*":
            return index

        if _is_malformed_placeholder_boundary(sql[index]):
            return index

        if sql[index] == "?":
            return index + 1

        index += 1
    return len(sql)


def scan_placeholder_spans(sql: str) -> Tuple[PlaceholderSpan, ...]:
    spans: List[PlaceholderSpan] = []
    index = 0
    sql_length = len(sql)

    while index < sql_length:
        char = sql[index]

        if char == "'":
            index = _skip_quoted_sql_text(sql, index, "'")
            continue

        if char == '"':
            index = _skip_quoted_sql_text(sql, index, '"')
            continue

        if char == "-" and index + 1 < sql_length and sql[index + 1] == "-":
            index = _skip_line_comment(sql, index)
            continue

        if char == "/" and index + 1 < sql_length and sql[index + 1] == "*":
            index = _skip_block_comment(sql, index)
            continue

        if char == "?":
            name_start = index + 1
            if name_start < sql_length and sql[name_start] == "?":
                index = _skip_question_mark_run(sql, index)
                continue

            if name_start < sql_length and _is_placeholder_name_start(sql[name_start]):
                name_end = name_start + 1
                while name_end < sql_length and _is_placeholder_name_char(sql[name_end]):
                    name_end += 1

                if name_end < sql_length and sql[name_end] == "?":
                    placeholder_end = name_end + 1
                    if placeholder_end == sql_length or not _is_placeholder_name_char(sql[placeholder_end]):
                        spans.append((index, placeholder_end, sql[name_start:name_end]))
                        index = placeholder_end
                        continue

                    index = _skip_malformed_placeholder(sql, placeholder_end)
                    continue

                index = _skip_malformed_placeholder(sql, name_end)
                continue

            index += 1
            continue

        index += 1

    return tuple(spans)


def find_statement_separator(sql: str) -> Optional[int]:
    """Return the index of the first statement separator that starts a second statement.

    A single trailing ``;`` followed only by whitespace and comments terminates one statement and
    returns ``None``. Semicolons inside quoted text or comments are ordinary characters, using the
    same skip set as :func:`scan_placeholder_spans`.
    """
    index = 0
    sql_length = len(sql)

    while index < sql_length:
        char = sql[index]

        if char == "'":
            index = _skip_quoted_sql_text(sql, index, "'")
            continue

        if char == '"':
            index = _skip_quoted_sql_text(sql, index, '"')
            continue

        if char == "-" and index + 1 < sql_length and sql[index + 1] == "-":
            index = _skip_line_comment(sql, index)
            continue

        if char == "/" and index + 1 < sql_length and sql[index + 1] == "*":
            index = _skip_block_comment(sql, index)
            continue

        if char == ";":
            if _skip_whitespace_and_comments(sql, index + 1) == sql_length:
                return None
            return index

        index += 1

    return None
