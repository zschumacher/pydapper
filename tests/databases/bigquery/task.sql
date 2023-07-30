CREATE TABLE IF NOT EXISTS {task_table_name} (
    id          int64,
    description string NOT NULL,
    due_date    date NOT NULL,
    owner_id    int64 NOT NULL
);