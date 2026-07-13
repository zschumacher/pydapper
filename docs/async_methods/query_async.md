
`query_async` can execute a query and serialize the results to a model.

## Parameters
| name     | type        | description                                                                                   | optional     | default |
|----------|-------------|-----------------------------------------------------------------------------------------------|--------------|---------|
| sql      | `str`       | the sql query str to execute                                                                  | :thumbsdown: |         |
| params    | `ParamType` | params to substitute in the query                                                             | :thumbsup:   | `None`  |
 | model    | `Any`       | the callable to serialize the model;  callable must be able to accept column names as kwargs. | :thumbsup:   | `dict`  |
 | mapper   | `Callable[[RawRow], Any]` | callable that receives a `RawRow` and returns a projected value. Mutually exclusive with `model`. | :thumbsup: | `None` |
| buffered | `bool`      | whether to buffer reading the results of the query                                            | :thumbsup:   | `True`  |
| options  | `CommandOptions | None` | command execution options; see [Command options](../command_options.md) | :thumbsup: | `None` |


`param=` remains accepted as a 1.x compatibility alias for `params=`. Pass only one of the two names.

{!docs/.parameter_shapes_read.md!}

{!docs/.row_mapping.md!}

## Cardinality
- 0 rows with unique column names and `buffered=True`: returns an empty list.
- 0 rows with unique column names and `buffered=False`: returns an async generator that yields no rows.

## Example - Serialize to a dataclass
The raw sql query can be executed using the `query_async` method and map the results to a list of dataclasses.
```python
{!docs/../docs_src/async_methods/query/basic_query.py!}
```
(*This script is complete, it should run "as is"*)


### Example - Serialize a one to one relationship
You can get creative with what you pass in to the model kwarg of `query`
```python
{!docs/../docs_src/async_methods/query/one_to_one_query.py!}
```
(This script is complete, it should run "as is")


### Example - Project joined rows with duplicate column names
Use `mapper=` when a join intentionally selects duplicate column names or when projection logic needs positional values.
```python
{!docs/../docs_src/async_methods/query/mapper_join.py!}
```
(This script is complete, it should run "as is")


### Example - Project aliased rows by name
`RawRow.as_dict()` and `row["column_name"]` are available when the referenced column names are unique.
```python
{!docs/../docs_src/async_methods/query/mapper_aliases.py!}
```
(This script is complete, it should run "as is")


### Example - Buffering queries
By default, `query_async` fetches all results and stores them in a list (buffered). By setting `buffered=False`, you can
instead have `query_async` return an async generator that fetches one record from the result set at a time. This may be
useful if querying a large amount of data that would not fit into memory, but note that this keeps both the connection
and cursor open while you're retrieving results. Breaking out of a plain async generator does not by itself guarantee
immediate cleanup while the generator remains referenced, so explicitly close it when stopping early.

```python
rows = await db.query_async(sql, buffered=False)
try:
    async for row in rows:
        break
finally:
    await rows.aclose()
```

```python
{!docs/../docs_src/async_methods/query/query_unbuffered.py!}
```
(This script is complete, it should run "as is")


## Example - Serializing a one-to-many relationship
Using model is nice for simple serialization, but more complex serializations might require more complex logic.  In this
case, it is recommended to return an unbuffered result and serialize it as you iterate.  See the example below:
```python
{!docs/../docs_src/async_methods/query/one_to_many_query.py!}
```
(This script is complete, it should run "as is")
