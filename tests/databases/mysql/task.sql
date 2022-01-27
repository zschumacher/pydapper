CREATE TABLE IF NOT EXISTS pydapper.task (
    id          integer AUTO_INCREMENT,
    description text NOT NULL,
    due_date    date NOT NULL,
    owner_id    integer NOT NULL,
    PRIMARY KEY ( id ),
    FOREIGN KEY ( owner_id ) REFERENCES pydapper.owner(id)
);