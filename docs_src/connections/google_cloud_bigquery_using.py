import pydapper
import pathlib
from google.cloud.bigquery import Client
from google.cloud.bigquery.dbapi import connect
import json

credentials = pathlib.Path(
    "~", "src", "pydapper", "tests", "test_bigquery", "auth", "key.json"
).expanduser().read_text()

client = Client.from_service_account_info(json.loads(credentials))
dbapi_connection = connect(client=client)

commands = pydapper.using(dbapi_connection)
print(type(commands))
# <class 'pydapper.bigquery.google_bigquery_client.GoogleBigqueryClientCommands'>

print(type(commands.connection))
# <class 'google.cloud.bigquery.dbapi.connection.Connection'>

raw_cursor = commands.cursor()
print(type(raw_cursor))
# <class 'google.cloud.bigquery.dbapi.cursor.Cursor'>
