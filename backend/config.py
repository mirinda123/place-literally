import os
import re
from dataclasses import dataclass
from pathlib import Path

from dotenv import load_dotenv
from elasticsearch import Elasticsearch

ROOT = Path(__file__).resolve().parent.parent


@dataclass(frozen=True)
class Settings:
    url: str = "http://localhost:9200"
    index: str = "features-v10"
    feedback_index: str = "place-feedback-v1"
    analyzer: str = "cjk"
    api_key: str | None = None
    username: str | None = None
    password: str | None = None
    ca_certs: str | None = None
    origins: tuple[str, ...] = ("http://localhost:5173", "http://127.0.0.1:5173")

    def __post_init__(self):
        if not re.fullmatch(r"[a-z][a-z0-9_-]{0,180}", self.index):
            raise ValueError("ES_INDEX must be a single lowercase index name, without wildcards")
        if not re.fullmatch(r"[a-z][a-z0-9_-]{0,180}", self.feedback_index) or self.feedback_index == self.index:
            raise ValueError("ES_FEEDBACK_INDEX must be a distinct lowercase index name, without wildcards")
        if self.analyzer not in {"cjk", "smartcn", "ik_smart"}:
            raise ValueError("ES_ANALYZER must be cjk, smartcn, or ik_smart")

    @classmethod
    def from_env(cls):
        load_dotenv(ROOT / "backend" / ".env")
        return cls(
            url=os.getenv("ES_URL", "http://localhost:9200"),
            index=os.getenv("ES_INDEX", "features-v10"),
            feedback_index=os.getenv("ES_FEEDBACK_INDEX", "place-feedback-v1"),
            analyzer=os.getenv("ES_ANALYZER", "cjk"),
            api_key=os.getenv("ES_API_KEY") or None,
            username=os.getenv("ES_USERNAME") or None,
            password=os.getenv("ES_PASSWORD") or None,
            ca_certs=os.getenv("ES_CA_CERTS") or None,
            origins=tuple(x.strip() for x in os.getenv(
                "CORS_ORIGINS", "http://localhost:5173,http://127.0.0.1:5173"
            ).split(",") if x.strip()),
        )


def connect(settings: Settings):
    options = {"request_timeout": 10, "max_retries": 1}
    if settings.api_key:
        options["api_key"] = settings.api_key
    elif settings.username:
        options["basic_auth"] = (settings.username, settings.password or "")
    if settings.ca_certs:
        options["ca_certs"] = settings.ca_certs
    return Elasticsearch(settings.url, **options)
