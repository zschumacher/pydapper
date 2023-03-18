CREATE TABLE IF NOT EXISTS {task_table_name} (
    id          integer,
    description string NOT NULL,
    due_date    date NOT NULL,
    owner_id    integer NOT NULL
);