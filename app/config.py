from pathlib import Path

from pydantic_settings import BaseSettings, SettingsConfigDict

BASE_DIR = Path(__file__).resolve().parent.parent
DATA_DIR = BASE_DIR / "data"


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=str(BASE_DIR / ".env"),
        env_file_encoding="utf-8",
        extra="ignore",
    )

    feishu_webhook_url: str = "REPLACE_ME"
    database_url: str = f"sqlite:///{DATA_DIR / 'edge_task_hub.db'}"
    default_timezone: str = "Asia/Shanghai"
    host: str = "0.0.0.0"
    port: int = 8000

    enable_openclaw: bool = False
    enable_ollama: bool = False
    enable_anomaly_model: bool = True
    anomaly_sample_interval_seconds: int = 300

    news_summary_mode: str = "auto"
    news_summary_model: str = "qwen3:1.7b"
    news_summary_timeout_seconds: int = 300
    news_summary_max_tokens: int = 160
    model_speed_target_seconds: int = 30
    ollama_candidate_models: str = "qwen3:1.7b,qwen3:0.6b,qwen3.5:0.8b,qwen2.5:0.5b-instruct,tinyllama,llama3.2:1b"

    ollama_url: str = "http://127.0.0.1:11434/api/generate"
    ollama_model: str = "qwen3:0.6b"
    ollama_num_ctx: int = 1024
    ollama_keep_alive: str = "0"
    openclaw_cli: str = "/home/pi3/.npm-global/bin/openclaw"
    openclaw_gateway_url: str = "ws://127.0.0.1:18789"

    feishu_inbound_enabled: bool = False
    feishu_app_id: str = ""
    feishu_app_secret: str = ""
    feishu_verification_token: str = ""
    feishu_allowed_open_ids: str = ""
    feishu_allowed_chat_ids: str = ""

    document_summary_model: str = "qwen2.5:0.5b-instruct"
    document_summary_timeout_seconds: int = 180
    document_summary_max_tokens: int = 160
    document_summary_max_chars: int = 4000
    document_summary_max_file_bytes: int = 8 * 1024 * 1024


settings = Settings()
