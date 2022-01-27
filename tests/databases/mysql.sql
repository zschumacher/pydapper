CREATE TABLE IF NOT EXISTS pydapper.owner (
    id integer NOT NULL AUTO_INCREMENT,
    name text NOT NULL,
    PRIMARY KEY ( id )
);
COMMIT;

CREATE TABLE IF NOT EXISTS pydapper.task (
    id          integer AUTO_INCREMENT,
    description text NOT NULL,
    due_date    date NOT NULL,
    owner_id    integer NOT NULL,
    PRIMARY KEY ( id ),
    FOREIGN KEY ( owner_id ) REFERENCES owner(id)
);
COMMIT;

INSERT IGNORE INTO pydapper.owner (id, name) VALUES
(1, 'Zach Schumacher') ;
COMMIT;

INSERT IGNORE INTO pydapper.task (id, description, due_date, owner_id) VALUES
(1, 'Set up a test database', '2021-12-31', 1),
(2, 'Seed the test database', '2021-12-31', 1),
(3, 'Run the test suite', '2022-01-01', 1)
;
COMMIT ;
