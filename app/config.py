from pathlib import Path

from pydantic_settings import BaseSettings, SettingsConfigDict

ROOT = Path(__file__).resolve().parent.parent


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=ROOT / ".env", extra="ignore")

    llm_base_url: str = "https://api.deepseek.com"
    llm_api_key: str = ""
    llm_model: str = "deepseek-chat"
    llm_timeout_sec: float = 20
    llm_max_tokens: int = 400
    llm_input_price_per_1m: float = 0.14
    llm_output_price_per_1m: float = 0.28

    @property
    def llm_enabled(self) -> bool:
        return bool(self.llm_api_key.strip())


settings = Settings()
DATA_DIR = ROOT / "data"
STATIC_DIR = Path(__file__).resolve().parent / "static"
