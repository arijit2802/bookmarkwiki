from pydantic_settings import BaseSettings


class Settings(BaseSettings):
    groq_api_key: str
    database_url: str = "postgresql+asyncpg://dke:dke@localhost:5432/dke"
    wiki_dir: str = "wiki"
    groq_model: str = "llama-3.3-70b-versatile"

    model_config = {"env_file": ".env"}


settings = Settings()
