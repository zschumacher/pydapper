CREATE TABLE IF NOT EXISTS pydapper.task (
    id          integer,
    description string NOT NULL,
    due_date    date NOT NULL,
    owner_id    integer NOT NULL
);