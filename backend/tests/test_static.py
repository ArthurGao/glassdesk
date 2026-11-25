from pathlib import Path

from fastapi.testclient import TestClient

from glassdesk.app import create_app
from glassdesk.config import Settings
from glassdesk.db import Deps


def test_spa_fallback_serves_index_for_unknown_paths_but_not_api(
    settings: Settings, deps: Deps, tmp_path: Path
) -> None:
    (tmp_path / "assets").mkdir()
    (tmp_path / "index.html").write_text("<html>glassdesk spa</html>")
    (tmp_path / "assets" / "app.js").write_text("console.log(1)")
    client = TestClient(create_app(settings.model_copy(update={"static_dir": tmp_path}), deps=deps))
    for path in ("/", "/knowledge", "/login"):
        page = client.get(path)
        assert page.status_code == 200
        assert page.text == "<html>glassdesk spa</html>"
    asset = client.get("/assets/app.js")
    assert (asset.status_code, asset.text) == (200, "console.log(1)")
    missing = client.get("/api/nope")
    assert missing.status_code == 404
    assert missing.headers["content-type"].startswith("application/json")
    assert client.get("/assets/nope.js").status_code == 404


def test_without_static_dir_unknown_paths_are_404(settings: Settings, deps: Deps) -> None:
    assert TestClient(create_app(settings, deps=deps)).get("/knowledge").status_code == 404
