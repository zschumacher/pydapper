# Command options

Normal command methods accept a keyword-only `options=` argument. SQL, `params=`
(`param=` remains a compatibility alias), `model=`, `mapper=`, and `buffered=`
remain direct method arguments.

```python
rows = db.query("select id, description from task", options=pydapper.CommandOptions())
```

`CommandOptions` is immutable and has these fields:

| field | default | meaning |
|---|---|---|
| `timeout` | `None` | Per-command timeout in seconds. |
| `command_kind` | `CommandKind.TEXT` | Text SQL or a stored procedure. |
| `readonly` | `None` | Per-command read-only request. |
| `max_rows` | `None` | Positive maximum number of returned rows. |

`CommandOptions()` is currently the supported option set and is equivalent to
`options=None`. Valid non-default values are modeled for the v1 API but are not
yet implemented. They raise `UnsupportedFeatureError` loudly instead of being
ignored. Timeout enforcement belongs to [#482](https://github.com/zschumacher/pydapper/issues/482);
read-only and row-limit enforcement belong to [#475](https://github.com/zschumacher/pydapper/issues/475);
stored procedures belong to [#481](https://github.com/zschumacher/pydapper/issues/481).

```python
db.query("select 1", options=pydapper.CommandOptions(timeout=5))
# raises UnsupportedFeatureError until timeout support lands
```

Python async callers use normal task cancellation. pydapper does not add a
.NET-style cancellation token. `asyncio.timeout()` may be used on Python 3.11+
and newer; pydapper continues to support Python 3.10.
