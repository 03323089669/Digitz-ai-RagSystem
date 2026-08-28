from pathlib import Path
from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict

ENV_PATH = Path(__file__).resolve().parent.parent / '.env'


class Settings(BaseSettings):
    # Groq
    groq_api_url: str = Field(
        default='https://api.groq.com/openai/v1',
        alias='GROQ_API_URL',
    )
    groq_api_key: str | None = Field(default=None, alias='GROQ_API_KEY')
    groq_model: str = Field(default='openai/gpt-oss-20b', alias='GROQ_MODEL')
    groq_fallback_model: str = Field(default='openai/gpt-oss-120b', alias='GROQ_FALLBACK_MODEL')

    # OpenAI
    openai_api_key: str | None = Field(default=None, alias='OPENAI_API_KEY')
    openai_model: str = Field(default='gpt-4o-mini', alias='OPENAI_MODEL')

    # Gemini
    gemini_api_key: str | None = Field(default=None, alias='GEMINI_API_KEY')
    gemini_model: str = Field(default='gemini-2.5-flash', alias='GEMINI_MODEL')

    # Claude (Anthropic)
    anthropic_api_key: str | None = Field(default=None, alias='ANTHROPIC_API_KEY')
    anthropic_model: str = Field(default='claude-sonnet-4-6', alias='ANTHROPIC_MODEL')

    # DeepSeek
    deepseek_api_key: str | None = Field(default=None, alias='DEEPSEEK_API_KEY')
    deepseek_model: str = Field(default='deepseek-chat', alias='DEEPSEEK_MODEL')

    # Default brand
    default_brand: str | None = Field(default=None, alias='DEFAULT_BRAND')

    model_config = SettingsConfigDict(
        env_file=str(ENV_PATH),
        env_file_encoding='utf-8',
        extra='ignore'
    )


settings = Settings()

