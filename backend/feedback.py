"""Store reader corrections separately from the place records they describe."""

from datetime import datetime, timezone
from typing import Literal
from uuid import uuid4

from elasticsearch import BadRequestError
from pydantic import BaseModel, ConfigDict, Field, HttpUrl, field_validator


class FeedbackRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    feature_id: str = Field(min_length=1, max_length=200)
    meaning_index: int | None = Field(default=None, ge=0)
    language: Literal["zh", "en", "ja", "fr", "es"]
    description: str = Field(min_length=1, max_length=2000)
    nickname: str | None = Field(default=None, max_length=80)
    suggested_meaning: str | None = Field(default=None, max_length=500)
    source_url: HttpUrl | None = None

    @field_validator("feature_id", "description", "nickname", "suggested_meaning", mode="before")
    @classmethod
    def trim_text(cls, value):
        return value.strip() if isinstance(value, str) else value


FEEDBACK_MAPPING = {
    "dynamic": "strict",
    "_meta": {"schema": "place-feedback-v1"},
    "properties": {
        "id": {"type": "keyword"},
        "feature_id": {"type": "keyword"},
        "language": {"type": "keyword"},
        "meaning_index": {"type": "integer"},
        "place_name": {"type": "text"},
        "original_name": {"type": "object", "enabled": False},
        "meaning_snapshot": {"type": "object", "enabled": False},
        "description": {"type": "text"},
        "nickname": {"type": "keyword"},
        "suggested_meaning": {"type": "text"},
        "source_url": {"type": "keyword", "ignore_above": 2048},
        "status": {"type": "keyword"},
        "created_at": {"type": "date"},
    },
}


def build_feedback_document(feature: dict, report: FeedbackRequest) -> dict:
    meanings = feature.get("literal_meanings") or []
    has_meaning = any(any(isinstance(text, str) and text.strip()
                          for text in (item.get("translations") or {}).values()) for item in meanings)
    if report.meaning_index is not None:
        if not has_meaning or report.meaning_index >= len(meanings):
            raise ValueError("This place has no meaning at that index")

    names = feature.get("names") or {}
    place_name = (names.get(report.language) or names.get("en") or names.get("zh")
                  or next(iter(names.values()), report.feature_id))
    selected = meanings[report.meaning_index] if report.meaning_index is not None else None
    if selected is not None:
        meaning_snapshot = {"translations": selected.get("translations") or {}}
    elif has_meaning:
        meaning_snapshot = {"meanings": [
            {"translations": item.get("translations") or {}} for item in meanings
        ]}
    else:
        meaning_snapshot = None
    return {
        "id": uuid4().hex,
        "feature_id": report.feature_id,
        "language": report.language,
        "meaning_index": report.meaning_index,
        "place_name": place_name,
        "original_name": feature.get("literal_name"),
        "meaning_snapshot": meaning_snapshot,
        "description": report.description,
        "nickname": report.nickname or None,
        "suggested_meaning": report.suggested_meaning or None,
        "source_url": str(report.source_url) if report.source_url else None,
        "status": "pending",
        "created_at": datetime.now(timezone.utc).isoformat(),
    }


def ensure_feedback_index(client, index: str) -> None:
    if client.indices.exists(index=index):
        properties = client.indices.get_mapping(index=index)[index]["mappings"].get("properties", {})
        if "nickname" not in properties:
            client.indices.put_mapping(index=index, properties={"nickname": FEEDBACK_MAPPING["properties"]["nickname"]})
        return
    try:
        client.indices.create(index=index, mappings=FEEDBACK_MAPPING)
    except BadRequestError as exc:
        error = exc.body.get("error") if isinstance(exc.body, dict) else None
        if not isinstance(error, dict) or error.get("type") != "resource_already_exists_exception":
            raise


def save_feedback(client, index: str, document: dict) -> None:
    ensure_feedback_index(client, index)
    client.index(index=index, id=document["id"], document=document, refresh="wait_for")
