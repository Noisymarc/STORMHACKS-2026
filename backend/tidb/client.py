"""Connection to TiDB Cloud Starter.

Settings come from environment variables (the values shown in the TiDB Cloud
"Connect" dialog):

    TIDB_HOST, TIDB_PORT (default 4000), TIDB_USER, TIDB_PASSWORD,
    TIDB_DB_NAME (default "test"), TIDB_CA_PATH (optional; system CAs otherwise)

TiDB Cloud requires TLS, so the connection always verifies the server
certificate and hostname.
"""
import os
import ssl

from sqlalchemy import Engine, create_engine
from sqlalchemy.engine import URL


def create_tidb_engine(
    host: str,
    user: str,
    password: str,
    database: str = "test",
    port: int = 4000,
    ca_path: str | None = None,
) -> Engine:
    url = URL.create(
        "mysql+pymysql",
        username=user,
        password=password,
        host=host,
        port=port,
        database=database,
    )
    ssl_ctx = ssl.create_default_context(cafile=ca_path)
    return create_engine(
        url,
        connect_args={"ssl": ssl_ctx, "connect_timeout": 10, "read_timeout": 15, "write_timeout": 15},
        pool_pre_ping=True,
        # TiDB Cloud Starter closes idle connections; recycle well before that.
        pool_recycle=300,
    )


def engine_from_env() -> Engine:
    missing = [k for k in ("TIDB_HOST", "TIDB_USER", "TIDB_PASSWORD") if not os.getenv(k)]
    if missing:
        raise RuntimeError(f"Missing TiDB settings: {', '.join(missing)}")
    return create_tidb_engine(
        host=os.environ["TIDB_HOST"],
        user=os.environ["TIDB_USER"],
        password=os.environ["TIDB_PASSWORD"],
        database=os.getenv("TIDB_DB_NAME", "test"),
        port=int(os.getenv("TIDB_PORT", "4000")),
        ca_path=os.getenv("TIDB_CA_PATH") or None,
    )
