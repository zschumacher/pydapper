# [Google BigQuery](https://cloud.google.com/bigquery)

Supported drivers:

| dbapi                                                                                              | default    | driver            | connection class                         |
|----------------------------------------------------------------------------------------------------|------------|-------------------|------------------------------------------|
| [google-cloud-bigquery](https://cloud.google.com/python/docs/reference/bigquery/latest/index.html) | :thumbsup: | `bigquery+google` | `google.cloud.bigquery.dbapi.Connection` |

## google-cloud-bigquery

`google-cloud-bigquery` is the default dbapi driver for Google BigQuery in *pydapper*.

### Installation

=== "pip"
    ```console
    pip install pydapper[google-cloud-bigquery]
    ```

=== "poetry"
    ```console
    poetry add pydapper -E google-cloud-bigquery
    ```

### Google cloud storage alternate installation
* `google-cloud-bigquery` also has support for a more performant read api using pyarrow and remote procedure calls (RPC).
* In order to get the performance benefits, no config is required, you simply install the `google-cloud-bigquery-storage` extra as well.
* Read more about it in the [`google docs`](https://cloud.google.com/bigquery/docs/reference/storage/).

=== "pip"
    ```console
    pip install pydapper[google-cloud-bigquery, google-cloud-bigquery-storage]
    ```

=== "poetry"
    ```console
    poetry add pydapper -E google-cloud-bigquery -E google-cloud-bigquery-storage
    ```

### DSN format
For bigquery, config is not actually passed through the dsn, so the dsn is extremely easy to define.  The dsn simply
tells pydapper what driver to use.  Please see the `connect` and `using` examples below on how to pass config.

=== "Example"
    ```python
    dsn = "bigquery+google:////"
    ```

=== "Example (Default Driver)"
    ```python
    dsn = "bigquery:////"
    ```

### Example - `connect`
By default the google client 
[will look for the `GOOGLE_APPLICATION_CREDENTIALS` environment var](https://cloud.google.com/docs/authentication/application-default-credentials)

```python
{!docs/../docs_src/connections/google_cloud_bigquery_connect_env_var.py!}
```

Alternatively, you can construct a [client](https://googleapis.dev/python/google-api-core/latest/auth.html#client-provided-authentication) 
yourself and pass it into [connect](https://cloud.google.com/python/docs/reference/bigquery/latest/dbapi)...

```python
{!docs/../docs_src/connections/google_cloud_bigquery_connect_kwargs.py!}
```

### Example - `using`
You might want to use a connection object that you constructed from some factory function or connection pool.  In that
case, you can pass that object directly into using...

```python
{!docs/../docs_src/connections/google_cloud_bigquery_using.py!}
```

### Transactions {#bigquery-transactions}

BigQuery has **no connection-level transactions**, and the DBAPI reflects that:

* `Connection.commit()` is a documented no-op, and there is no `rollback()` method at all.
* The connection has **no `__enter__`/`__exit__`** — `with pydapper.connect("bigquery:////")` works only
  because pydapper's context-manager proxying is conditional, and exiting the block performs no driver call
  (nothing is committed, rolled back, or closed).
* `GoogleBigqueryClientCommands` does **not** declare `AdapterCapability.TRANSACTIONS`, so pydapper's
  `commit()`, `rollback()`, and `transaction()` raise `UnsupportedFeatureError` before the connection is
  touched.

Every statement runs as its own BigQuery job and is effectively committed on completion.

See [Transactions](../transactions.md) and
[Context manager semantics](intro.md#context-manager-semantics) for the cross-driver picture.
