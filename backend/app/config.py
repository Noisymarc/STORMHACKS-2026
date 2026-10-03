from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    gemini_api_key: str = ""
    gemini_model: str = "gemini-2.5-flash"

    elevenlabs_api_key: str = ""
    elevenlabs_voice_id: str = "21m00Tcm4TlvDq8ikWAM"
    elevenlabs_model: str = "eleven_flash_v2_5"

    wlk_url: str = "ws://localhost:8000/asr"
    database_url: str = "sqlite:///./stormhacks.db"

    # how many past corrections are injected into each Gemini prompt
    max_examples: int = 6
    # minimum seconds between interim (not yet final) translations
    interim_interval: float = 1.0


settings = Settings()
