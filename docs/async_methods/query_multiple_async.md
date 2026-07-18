
`query_multiple_async` can execute multiple queries with the same cursor and serialize the results. This method
will throw a `ValueError` if you don't supply the same number of queries and models, or if a tuple of mapper functions
does not match the number of queries. A single mapper function applies to every result set.

## Parameters
All command methods also accept keyword-only `options=`; see [Command options](../command_options.md).

| name  | type        | description                                                                                   | optional     | default |
|-------|-------------|-----------------------------------------------------------------------------------------------|--------------|---------|
| queries | `tuple[str, ...]` | the sql query strings to execute in order                                                | :thumbsdown: |         |
| params | `ParamType` | params to substitute in the query                                                             | :thumbsup:   | `None`  |
 | models | `tuple[Any, ...]` | callables to serialize each result set; each callable must accept column names as kwargs. | :thumbsup:   | `dict`  |
 | mapper | `Callable[[RawRow], Any]` or tuple | one mapper for every result set, or a tuple of mapper functions. Mutually exclusive with `models`. | :thumbsup: | `None` |

`param=` remains accepted as a 1.x compatibility alias for `params=`. Pass only one of the two names.

{!docs/.parameter_shapes_read.md!}

{!docs/.row_mapping.md!}

## Batch validation and atomicity

Every query in the tuple is validated client-side before any database work: placeholders are scanned and every
referenced parameter value is resolved for the complete tuple before a cursor is acquired or the first query
executes. A missing parameter in any query raises `MissingParameterException` and no query reaches the database.

This is client-side prevalidation, not transaction atomicity. Once execution begins, the queries run sequentially on
one cursor, and a later query can still fail at runtime (a driver error, no results, duplicate columns, or a mapper
error) after earlier queries have executed. pydapper does not roll back or undo earlier queries in the tuple.

## Example
Query two tables and return the serialized results.
```python
{!docs/../docs_src/async_methods/query_multiple/example.py!}
```
(This script is complete, it should run "as is")


## Example - Mapper Functions
Project each result set with `RawRow` mapper functions.
```python
{!docs/../docs_src/async_methods/query_multiple/mapper.py!}
```
(This script is complete, it should run "as is")
