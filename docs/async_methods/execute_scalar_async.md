
`execute_scalar_async` executes the query, and returns the first column of the first row in the result set returned by 
the query.  The additional columns or rows are ignored.


## Parameters
| name  | type        | description                       | optional     | default |
|-------|-------------|-----------------------------------|--------------|---------|
| sql   | `str`       | the sql query str to execute      | :thumbsdown: |         |
| param | `ParamType` | params to substitute in the query | :thumbsup:   | `None`  |

## Example
Get the name of the first task owner in the database.

```python
{!docs/../docs_src/async_methods/execute_scalar/example.py!}
```
(*This script is complete, it should run "as is"*)