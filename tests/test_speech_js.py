"""Runs the plain-Node tests for frontend/speech.js (sentence splitting incl. Japanese, echo guard,
playback queue / Stop). Skipped when Node.js is not installed."""
import shutil
import subprocess
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]


@pytest.mark.skipif(shutil.which("node") is None, reason="Node.js is not installed")
def test_speech_js():
    result = subprocess.run(["node", str(ROOT / "tests/js/speech.test.js")],
                            capture_output=True, text=True, timeout=60)
    assert result.returncode == 0, result.stdout + result.stderr
