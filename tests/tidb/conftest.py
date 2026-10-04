"""Load TIDB_* settings from the repo-root .env so integration tests can run."""
from pathlib import Path

try:
    from dotenv import load_dotenv
except ImportError:
    load_dotenv = None

if load_dotenv:
    # Real environment variables win over .env.
    load_dotenv(Path(__file__).resolve().parents[2] / ".env", override=False)
