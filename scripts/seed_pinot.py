import json
import pathlib
import time

TABLE_TYPE = "OFFLINE"


def create_schema(schema_file_path: pathlib.Path):
    import httpx

    r = httpx.post("http://localhost:9000/schemas", json=json.load(schema_file_path.open()))
    r.raise_for_status()


def create_table(tables_file_path: pathlib.Path):
    import httpx

    payload = json.load(tables_file_path.open())
    tries = 0
    while tries < 10:
        r = httpx.post("http://localhost:9000/tables", json=payload)
        if r.status_code == 400:
            print("Table creation not ready - retrying...")
            tries += 1
            time.sleep(0.5 * tries)
        elif r.status_code == 409:
            print("Table already exists!")
            return
        else:
            r.raise_for_status()
            return


def delete_table(tablename: str):
    import httpx

    r = httpx.delete(f"http://localhost:9000/tables/{tablename}", params={"type": TABLE_TYPE})
    if r.status_code != 404:
        r.raise_for_status()


def load_data_from_file(table_name_with_type: str, file_path: pathlib.Path):
    import httpx

    fp = file_path.open("rb")
    r = httpx.post(
        "http://localhost:9000/ingestFromFile",
        params={
            "tableNameWithType": table_name_with_type,
            "batchConfigMapStr": json.dumps(
                {"inputFormat": "csv", "record.prop.delimiter": ",", "record.prop.header": "true"}
            ),
        },
        files={"file": (file_path.name, fp, "text/csv")},
    )
    fp.close()
    r.raise_for_status()


def check_table_can_be_queried(table_name: str):
    import httpx

    retries = 0
    while retries < 10:
        r = httpx.post("http://localhost:8099/query/sql", json={"sql": f"select * from {table_name}"})
        if r.status_code == 400:
            print(f"{table_name} not ready - retrying...")
            retries += 1
            time.sleep(0.5 * retries)
        else:
            break


if __name__ == "__main__":
    pinot_path = pathlib.Path(__file__).parent.parent / "tests" / "databases" / "pinot"

    print("Creating owner schema...")
    create_schema(pinot_path / "owner.schema.json")
    print("Creating task schema...")
    create_schema(pinot_path / "task.schema.json")

    print("Creating owner table...")
    create_table(pinot_path / "owner.table.json")
    print("Creating task table...")
    create_table(pinot_path / "task.table.json")

    print("Seeding task table...")
    load_data_from_file(f"task_{TABLE_TYPE}", pinot_path / "task.csv")
    print("Seeding owner table...")
    load_data_from_file(f"owner_{TABLE_TYPE}", pinot_path / "owner.csv")

    check_table_can_be_queried("task")
    check_table_can_be_queried("owner")
