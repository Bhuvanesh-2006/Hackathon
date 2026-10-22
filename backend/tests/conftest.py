import os
import sys
from pathlib import Path

import pytest

BACKEND = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(BACKEND))

# Tests always use the deterministic offline provider and never call a paid API.
os.environ["LLM_PROVIDER"] = "offline"


@pytest.fixture(autouse=True)
def isolated_app_db(tmp_path, monkeypatch):
    from app.config import get_settings

    settings = get_settings()
    monkeypatch.setattr(type(settings), "app_db_path", property(lambda self: tmp_path / "app_state.sqlite3"))
    monkeypatch.setattr(type(settings), "datasets_dir", property(lambda self: tmp_path / "datasets"))
    monkeypatch.setattr(type(settings), "uploads_dir", property(lambda self: tmp_path / "uploads"))
    from app.cache import get_cache

    get_cache().clear()
    yield
    from app.database import connection

    # Close imported-dataset connections so tmp files can be removed (keeps the built-in one open).
    for key in [k for k in list(connection._bases) if str(tmp_path) in k]:
        connection.reset_connection(key)


def dataset_loaded() -> bool:
    from app.database.connection import dataset_available

    return dataset_available()


requires_data = pytest.mark.skipif(not dataset_loaded(), reason="DuckDB dataset not prepared")
