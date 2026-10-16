import shutil
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parent.parent
TASKS_DIR = REPO / "tasks"


@pytest.fixture
def tasks_pack(tmp_path: Path) -> Path:
    shutil.copytree(TASKS_DIR, tmp_path / "tasks")
    return tmp_path / "tasks"
