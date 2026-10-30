from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """All required — fail loudly if compose injection is incomplete."""

    database_url: str
    framework_key: str

    model_config = SettingsConfigDict(env_file=".env", case_sensitive=False, extra="ignore")


settings = Settings()
