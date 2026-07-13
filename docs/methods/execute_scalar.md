
`execute_scalar` executes the query, and returns the first column of the first row in the result set returned by 
the query.  The additional columns or rows are ignored.


## Parameters
All command methods also accept keyword-only `options=`; see [Command options](../command_options.md).

| name  | type        | description                       | optional     | default |
|-------|-------------|-----------------------------------|--------------|---------|
| sql   | `str`       | the sql query str to execute      | :thumbsdown: |         |
| params | `ParamType` | params to substitute in the query | :thumbsup:   | `None`  |

`param=` remains accepted as a 1.x compatibility alias for `params=`. Pass only one of the two names.

{!docs/.parameter_shapes_read.md!}

## Cardinality
- 0 rows: raises `NoResultException`.
- 1+ rows: returns the first column of the first row.
- SQL `NULL` in the first column is returned as Python `None`.

## Example
Get the name of the first task owner in the database.

```python
{!docs/../docs_src/methods/execute_scalar/example.py!}
```
(*This script is complete, it should run "as is"*)
