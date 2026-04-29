from pydantic_settings import BaseSettings


class Settings(BaseSettings):
    gemini_api_key: str
    database_url: str = "postgresql+asyncpg://dke:dke@localhost:5432/dke"
    wiki_dir: str = "wiki"

    model_config = {"env_file": ".env"}


settings = Settings()
