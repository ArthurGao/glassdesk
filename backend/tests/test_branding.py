from fastapi.testclient import TestClient

from glassdesk.app import create_app
from glassdesk.config import Settings
from glassdesk.db import Deps


def test_branding_is_public_and_comes_from_settings(settings: Settings, deps: Deps) -> None:
    branded = settings.model_copy(
        update={
            "brand_name": "Acme 知识台",
            "brand_color": "#0f766e",
            "brand_welcome": "问我公司制度、流程和常见问题。",
            "brand_examples": ["出差住宿上限是多少？", "年假怎么请？"],
        }
    )
    response = TestClient(create_app(branded, deps=deps)).get("/api/branding")
    assert response.status_code == 200  # no login: the login page shows it
    assert response.json() == {
        "name": "Acme 知识台",
        "locale": "zh",
        "color": "#0f766e",
        "welcome": "问我公司制度、流程和常见问题。",
        "examples": ["出差住宿上限是多少？", "年假怎么请？"],
    }


def test_a_brand_color_that_is_not_a_hex_color_is_refused() -> None:
    import pytest
    from pydantic import ValidationError

    with pytest.raises(ValidationError):
        Settings(
            database_url="postgresql+psycopg://u:p@h/d",
            steward_api_key="k",  # type: ignore[arg-type]
            steward_review_key="r",  # type: ignore[arg-type]
            session_secret="s" * 32,  # type: ignore[arg-type]
            brand_color="red; background: url(x)",
            _env_file=None,  # type: ignore[call-arg]
        )
