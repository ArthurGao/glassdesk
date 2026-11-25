"""Runtime settings, read from environment variables with the GLASSDESK_ prefix."""

from pathlib import Path

from lite_model import ModelsConfig
from pydantic import Field, SecretStr, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

DEFAULT_DB_SCHEMA = "glassdesk"
DEFAULT_AGENT_SCHEMA = "lite_agent"


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_prefix="GLASSDESK_", env_file=".env", env_nested_delimiter="__", extra="ignore"
    )

    database_url: str
    db_schema: str = DEFAULT_DB_SCHEMA
    agent_schema: str = DEFAULT_AGENT_SCHEMA
    steward_url: str = "http://127.0.0.1:8600"
    steward_api_key: SecretStr  # scopes read, write and review (design §5, §7)
    steward_collection: str = "company"
    # steward's Admin API (insights: KB gaps and counts); both unset: insights show "未配置"
    steward_admin_token: SecretStr | None = None
    steward_namespace: str | None = None
    timezone: str = "Asia/Shanghai"  # the deployment's local days, for insights
    session_secret: SecretStr = Field(min_length=32)
    brand_name: str = "glassdesk"
    brand_color: str = Field(default="#0f172a", pattern=r"^#[0-9a-fA-F]{6}$")  # only a colour
    brand_welcome: str = ""  # shown above an empty chat
    brand_examples: list[str] = Field(default_factory=list)  # example questions (JSON in env)
    static_dir: Path | None = None
    # lite-model's configuration (GLASSDESK_LLM__BACKEND, GLASSDESK_LLM__MODEL, GLASSDESK_LLM__ROLES
    # …). None: no model is configured, and asking a question fails at startup of the run.
    llm: ModelsConfig | None = None

    @field_validator("db_schema", "agent_schema")
    @classmethod
    def _not_a_test_schema(cls, value: str) -> str:
        # Test fixtures drop *_test schemas: the app must never keep its data in one.
        if value.endswith("_test"):
            raise ValueError("a *_test schema is reserved for the test suite")
        return value
