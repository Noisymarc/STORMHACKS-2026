"""Runs the plain-Node tests for frontend/glossary-order.js and checks the page serves and uses it.
The Node part is skipped when Node.js is not installed."""
import shutil
import subprocess
import sys
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from backend import live_app


@pytest.mark.skipif(shutil.which("node") is None, reason="Node.js is not installed")
def test_glossary_order_js():
    result = subprocess.run(["node", str(ROOT / "tests/js/glossary-order.test.js")],
                            capture_output=True, text=True, timeout=60)
    assert result.returncode == 0, result.stdout + result.stderr


def test_page_loads_and_uses_the_ordering_script():
    client = TestClient(live_app.app)
    page = client.get("/")
    assert page.status_code == 200
    assert '<script src="glossary-order.js"></script>' in page.text
    assert "GlossaryOrder.orderGlossary" in page.text and "GlossaryOrder.lastSeenFromSpans" in page.text
    script = client.get("/glossary-order.js")
    assert script.status_code == 200 and "javascript" in script.headers["content-type"]
    assert "orderGlossary" in script.text
