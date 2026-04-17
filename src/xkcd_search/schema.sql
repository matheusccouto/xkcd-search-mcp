CREATE TABLE IF NOT EXISTS comics (
    number       INTEGER PRIMARY KEY,
    title        TEXT NOT NULL,
    url          TEXT NOT NULL,
    image_url    TEXT,
    alt_text     TEXT,
    transcript   TEXT,
    explanation  TEXT,
    explained_at TEXT
);

CREATE VIRTUAL TABLE IF NOT EXISTS chunk_vec USING vec0(
    embedding float[384] distance_metric=cosine
);

CREATE TABLE IF NOT EXISTS chunks (
    rowid   INTEGER PRIMARY KEY,
    number  INTEGER NOT NULL REFERENCES comics(number),
    kind    TEXT NOT NULL,
    text    TEXT NOT NULL
);

CREATE INDEX IF NOT EXISTS chunks_number ON chunks(number);
