 
`query_single_or_default_async` can execute a query and serialize the first result, or return a default value if the result
set is empty; this method throws an exception if there is more than one element in the result set.

## Parameters
All command methods also accept keyword-only `options=`; see [Command options](../command_options.md).

| name    | type        | description                                                                                   | optional     | default |
|---------|-------------|-----------------------------------------------------------------------------------------------|--------------|---------|
| sql     | `str`       | the sql query str to execute                                                                  | :thumbsdown: |         |
 | default | `Any`       | any object to return if the result set is empty                                               | :thumbsdown: |
| params   | `ParamType` | params to substitute in the query                                                             | :thumbsup:   | `None`  |
 | model   | `Any`       | the callable to serialize the model;  callable must be able to accept column names as kwargs. | :thumbsup:   | `dict`  |
 | mapper  | `Callable[[RawRow], Any]` | callable that receives a `RawRow` and returns a projected value. Mutually exclusive with `model`. | :thumbsup: | `None` |


`param=` remains accepted as a 1.x compatibility alias for `params=`. Pass only one of the two names.

{!docs/.parameter_shapes_read.md!}

{!docs/.row_mapping.md!}

## First, Single and Default
{!docs/.first_single_default.md!}

## Example
Execute a query and map the result to a dataclass.
```python
{!docs/../docs_src/async_methods/query_single_or_default/example.py!}
```
(This script is complete, it should run "as is")
