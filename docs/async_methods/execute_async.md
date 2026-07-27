
`execute_async` can execute a command one or multiple times and return the number of affected rows. This method is usually used
to execute insert, update or delete operations.

!!! warning "`execute_async` does not commit"
    A non-zero return value means the statement affected that many rows, not that the write is durable.
    Whether the examples below persist depends entirely on your driver: `aiopg` is autocommit-only so every
    statement is already durable, while `psycopg` commits when the `connect_async(...)` block exits. See
    [Transactions](../transactions.md) for the per-driver table and for `commit()` / `transaction()`.

## Parameters
All command methods also accept keyword-only `options=`; see [Command options](../command_options.md).

| name  | type                       | description                       | optional     | default |
|-------|----------------------------|-----------------------------------|--------------|---------|
 | sql   | `str`                      | the sql query str to execute      | :thumbsdown: |         |
 | params | `ListParamType, ParamType` | params to substitute in the query | :thumbsup:   | `None`  |

`param=` remains accepted as a 1.x compatibility alias for `params=`. Pass only one of the two names.

{!docs/.parameter_shapes_execute.md!}

## Example - Execute Insert
### Single
Execute the INSERT statement a single time.

```python
{!docs/../docs_src/async_methods/execute/insert_single.py!}
```
(*This script is complete, it should run "as is"*)

### Multiple
Execute the INSERT statement multiple times, one for each object in the params list.

```python
{!docs/../docs_src/async_methods/execute/insert_multiple.py!}
```
(*This script is complete, it should run "as is"*)

## Example - Execute Update
### Single
Execute the UPDATE statement a single time.

```python
{!docs/../docs_src/async_methods/execute/update_single.py!}
```
(*This script is complete, it should run "as is"*)

### Multiple
Execute the UPDATE statement multiple times, one for each object in the params list.

```python
{!docs/../docs_src/async_methods/execute/update_multiple.py!}
```
(*This script is complete, it should run "as is"*)

## Example - Execute Delete
### Single
Execute the DELETE statement a single time.

```python
{!docs/../docs_src/async_methods/execute/delete_single.py!}
```
(*This script is complete, it should run "as is"*)

### Multiple
Execute the DELETE statement multiple times, one for each object in the params list.

```python
{!docs/../docs_src/async_methods/execute/delete_multiple.py!}
```
(*This script is complete, it should run "as is"*)
