
`query` can execute a query and serialize the results to a model.

## Parameters
| name  | type        | description                                                                                   | optional     | default |
|-------|-------------|-----------------------------------------------------------------------------------------------|--------------|---------|
| sql   | `str`       | the sql query str to execute                                                                  | :thumbsdown: |         |
| param | `ParamType` | params to substitute in the query                                                             | :thumbsup:   | `None`  |
 | model | `Any`       | the callable to serialize the model;  callable must be able to accept column names as kwargs. | :thumbsup:   | `dict`  |

## Example - Serialize to a dataclass
The raw sql query can be executed using the `query` method and map the results to a list of dataclasses.
```python
{!docs/../docs_src/methods/query/basic_query.py!}
```
(*This script is complete, it should run "as is"*)

### Example - Serialize a one to one relationship
You can get creative with what you pass in to the model kwarg of `query`
```python
{!docs/../docs_src/methods/query/one_to_one_query.py!}
```
(This script is complete, it should run "as is")
