"""Keep even a bare `pytest` invocation away from real app data and UI."""
import os
import sys
import tempfile
from pathlib import Path

_test_data = tempfile.TemporaryDirectory(prefix="shengjian-pytest-")
os.environ["DOUBAO_BRIDGE_DATA_DIR"] = _test_data.name
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
