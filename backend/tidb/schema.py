"""Table definitions.

`embedding` is a generated column: TiDB Auto Embedding calls the embedding
model itself when a row is inserted or `content` changes, so the application
never computes or sends vectors. Auto Embedding is only available on TiDB Cloud
Starter clusters hosted on AWS.
"""
from sqlalchemy import Engine, text

EMBEDDING_MODEL = "tidbcloud_free/amazon/titan-embed-text-v2"
EMBEDDING_DIMENSIONS = 1024

MEMORIES_TABLE = "memories"
EXPOSURES_TABLE = "memory_exposures"

CREATE_MEMORIES = f"""
CREATE TABLE IF NOT EXISTS {MEMORIES_TABLE} (
    id          BIGINT PRIMARY KEY AUTO_RANDOM,
    user_id     VARCHAR(64)  NOT NULL,
    kind        VARCHAR(32)  NOT NULL,
    content     TEXT         NOT NULL,
    context     TEXT,
    note        TEXT,
    source_lang VARCHAR(16),
    target_lang VARCHAR(16),
    metadata    JSON,
    status      VARCHAR(16)  NOT NULL DEFAULT 'active',
    created_at  DATETIME(6)  NOT NULL DEFAULT CURRENT_TIMESTAMP(6),
    updated_at  DATETIME(6)  NOT NULL DEFAULT CURRENT_TIMESTAMP(6)
                             ON UPDATE CURRENT_TIMESTAMP(6),
    embedding   VECTOR({EMBEDDING_DIMENSIONS}) GENERATED ALWAYS AS (
                    EMBED_TEXT('{EMBEDDING_MODEL}', content)
                ) STORED,
    KEY idx_memories_user (user_id, status, kind)
)
"""

# How many times each user has met each saved concept since they last asked about it.
CREATE_EXPOSURES = f"""
CREATE TABLE IF NOT EXISTS {EXPOSURES_TABLE} (
    user_id      VARCHAR(64) NOT NULL,
    memory_id    BIGINT      NOT NULL,
    exposures    INT         NOT NULL DEFAULT 0,
    last_seen_at DATETIME(6) NOT NULL DEFAULT CURRENT_TIMESTAMP(6)
                             ON UPDATE CURRENT_TIMESTAMP(6),
    PRIMARY KEY (user_id, memory_id)
)
"""


def init_schema(engine: Engine) -> None:
    with engine.begin() as conn:
        conn.execute(text(CREATE_MEMORIES))
        conn.execute(text(CREATE_EXPOSURES))


def drop_schema(engine: Engine) -> None:
    with engine.begin() as conn:
        conn.execute(text(f"DROP TABLE IF EXISTS {EXPOSURES_TABLE}"))
        conn.execute(text(f"DROP TABLE IF EXISTS {MEMORIES_TABLE}"))
