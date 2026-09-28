"""Embed a selected pilot of existing literal meanings with Alibaba Model Studio.

The stored vectors use text_type=document. --instruct applies only to the
optional text_type=query probe, as required by the provider's API.
"""

import argparse
import copy
import hashlib
import json
import logging
import math
import os
import time
from datetime import datetime, timezone
from pathlib import Path
from urllib.error import HTTPError, URLError
from urllib.parse import urlparse
from urllib.request import Request, urlopen

from elasticsearch import NotFoundError

from .config import ROOT, Settings, connect
from .indexing import EMBEDDING_FIELD, EMBEDDING_LANGUAGES


MODEL = "qwen3.7-text-embedding"
DIMENSIONS = 512
DEFAULT_ENDPOINT = "https://dashscope.aliyuncs.com/api/v1/services/embeddings/text-embedding/text-embedding"
DEFAULT_INSTRUCT = (
    "Given the literal meaning of a place name, find countries and cities "
    "whose names have a similar literal meaning."
)


def validate_vector(value):
    if (not isinstance(value, list) or len(value) != DIMENSIONS
            or any(not isinstance(x, (int, float)) or not math.isfinite(x) for x in value)):
        raise ValueError(f"Expected a finite {DIMENSIONS}-dimensional vector")
    vector = [float(x) for x in value]
    if not any(vector):
        raise ValueError("Embedding vector must not be zero")
    return vector


def read_plan(path: Path):
    plan = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(plan, dict) or set(plan) != {"countries", "cities"}:
        raise ValueError("The pilot plan must have countries and cities arrays")
    if any(not isinstance(plan[key], list) or any(not isinstance(feature_id, str) or not feature_id
                                                 for feature_id in plan[key])
           for key in ("countries", "cities")):
        raise ValueError("The pilot plan entries must be nonempty feature IDs")
    entries = [(feature_id, kind) for key, kind in (("countries", "country"), ("cities", "city"))
               for feature_id in plan[key]]
    if not entries or len({feature_id for feature_id, _ in entries}) != len(entries):
        raise ValueError("The pilot must contain distinct feature IDs")
    return entries


def load_features(client, index: str, entries):
    selected = []
    for feature_id, kind in entries:
        # Elasticsearch omits dense vectors from _source by default. Fetch them
        # explicitly so an already-complete pilot is recognized on subsequent runs.
        try:
            hit = client.get(index=index, id=feature_id, source_exclude_vectors=False)
        except NotFoundError:
            raise ValueError(f"Feature not found: {feature_id}")
        doc = hit["_source"]
        if doc.get("feature_id") != feature_id or doc.get("kind") != kind:
            raise ValueError(f"Feature identity or kind changed: {feature_id}")
        meanings = doc.get("literal_meanings") or []
        if not meanings:
            raise ValueError(f"Feature has no literal meanings: {feature_id}")
        for meaning in meanings:
            translations = meaning.get("translations", {})
            if any(not isinstance(translations.get(lang), str) or not translations[lang].strip()
                   for lang in EMBEDDING_LANGUAGES):
                raise ValueError(f"Feature lacks a pilot translation: {feature_id}")
        selected.append(doc)
    return selected


class EmbeddingClient:
    def __init__(self, cache_dir: Path, endpoint: str, instruct: str, batch_size: int,
                 logger: logging.Logger | None = None):
        host = urlparse(endpoint)
        if host.scheme != "https" or not host.hostname or not host.hostname.endswith(".aliyuncs.com"):
            raise ValueError("Embedding endpoint must be an HTTPS aliyuncs.com host")
        self.endpoint = endpoint
        self.instruct = instruct
        self.batch_size = batch_size
        self.cache_dir = cache_dir
        self.cache_dir.mkdir(parents=True, exist_ok=True)
        self.calls = 0
        self.tokens = 0
        self.cache_hits = 0
        self.api_seconds = 0.0
        self.api_batches = []
        self.logger = logger

    def _cache_path(self, text: str, text_type: str):
        identity = {"model": MODEL, "dims": DIMENSIONS, "text_type": text_type,
                    "instruct": self.instruct if text_type == "query" else None, "text": text}
        fingerprint = hashlib.sha256(json.dumps(identity, sort_keys=True, ensure_ascii=False)
                                     .encode("utf-8")).hexdigest()
        return self.cache_dir / f"{fingerprint}.json"

    def _request(self, texts: list[str], text_type: str):
        key = os.getenv("DASHSCOPE_API_KEY")
        if not key:
            raise ValueError("Set DASHSCOPE_API_KEY for uncached embedding requests")
        parameters = {"dimension": DIMENSIONS, "output_type": "dense", "text_type": text_type}
        if text_type == "query":
            parameters["instruct"] = self.instruct
        payload = {"model": MODEL, "input": {"texts": texts}, "parameters": parameters}
        request = Request(self.endpoint, data=json.dumps(payload, ensure_ascii=False).encode("utf-8"),
                          headers={"Authorization": f"Bearer {key}",
                                   "Content-Type": "application/json"}, method="POST")
        for attempt in range(3):
            try:
                with urlopen(request, timeout=90) as response:
                    result = json.loads(response.read())
                break
            except HTTPError as exc:
                if exc.code not in (429, 500, 502, 503, 504) or attempt == 2:
                    try:
                        error_code = json.loads(exc.read()).get("code", "unknown")
                    except (ValueError, UnicodeDecodeError):
                        error_code = "unknown"
                    raise RuntimeError(f"Embedding API HTTP {exc.code}, code={error_code}") from None
            except (URLError, TimeoutError) as exc:
                if attempt == 2:
                    raise RuntimeError(f"Embedding API transport failure: {type(exc).__name__}") from None
            time.sleep(2 ** attempt)

        embeddings = result.get("output", {}).get("embeddings", [])
        if len(embeddings) != len(texts):
            raise ValueError("Embedding API returned an incomplete batch")
        by_index = {item["text_index"]: validate_vector(item["embedding"]) for item in embeddings}
        if set(by_index) != set(range(len(texts))):
            raise ValueError("Embedding API returned invalid text indices")
        self.calls += 1
        self.tokens += result.get("usage", {}).get("total_tokens", 0)
        return [by_index[index] for index in range(len(texts))]

    def embed(self, texts, text_type: str):
        if text_type not in {"document", "query"}:
            raise ValueError("text_type must be document or query")
        unique = list(dict.fromkeys(texts))
        vectors = {}
        missing = []
        for text in unique:
            path = self._cache_path(text, text_type)
            if path.exists():
                vectors[text] = validate_vector(json.loads(path.read_text(encoding="utf-8")))
                self.cache_hits += 1
            else:
                missing.append(text)
        for start in range(0, len(missing), self.batch_size):
            batch = missing[start:start + self.batch_size]
            batch_start = time.perf_counter()
            if self.logger:
                self.logger.info("API batch started: type=%s texts=%d", text_type, len(batch))
            try:
                batch_vectors = self._request(batch, text_type)
            except Exception:
                if self.logger:
                    self.logger.error("API batch failed: type=%s texts=%d elapsed=%.3fs",
                                      text_type, len(batch), time.perf_counter() - batch_start)
                raise
            elapsed = time.perf_counter() - batch_start
            self.api_seconds += elapsed
            self.api_batches.append({"text_type": text_type, "texts": len(batch),
                                     "elapsed_seconds": round(elapsed, 3)})
            if self.logger:
                self.logger.info("API batch finished: type=%s texts=%d elapsed=%.3fs",
                                 text_type, len(batch), elapsed)
            for text, vector in zip(batch, batch_vectors, strict=True):
                path = self._cache_path(text, text_type)
                temporary = path.with_suffix(".tmp")
                temporary.write_text(json.dumps(vector, separators=(",", ":")), encoding="utf-8")
                os.replace(temporary, path)
                vectors[text] = vector
        return vectors


def pending_texts(selected, force=False):
    pending = []
    for doc in selected:
        for meaning in doc["literal_meanings"]:
            existing = meaning.get(EMBEDDING_FIELD, {})
            for lang in EMBEDDING_LANGUAGES:
                if lang in existing:
                    validate_vector(existing[lang])
                if force or lang not in existing:
                    pending.append(meaning["translations"][lang])
    return pending


def apply_vectors(client, index: str, selected, vectors, force=False):
    written = 0
    for original in selected:
        feature_id = original["feature_id"]
        # The replacement literal_meanings list must retain any existing vectors.
        fresh = client.get(index=index, id=feature_id, source_exclude_vectors=False)
        current = fresh["_source"]
        original_texts = [item["translations"] for item in original["literal_meanings"]]
        current_texts = [item["translations"] for item in current["literal_meanings"]]
        if original_texts != current_texts:
            raise ValueError(f"Translations changed during embedding: {feature_id}")
        meanings = copy.deepcopy(current["literal_meanings"])
        changed = False
        for meaning in meanings:
            stored = meaning.setdefault(EMBEDDING_FIELD, {})
            for lang in EMBEDDING_LANGUAGES:
                if force or lang not in stored:
                    stored[lang] = vectors[meaning["translations"][lang]]
                    changed = True
        if changed:
            client.update(index=index, id=feature_id, doc={"literal_meanings": meanings},
                          if_seq_no=fresh["_seq_no"], if_primary_term=fresh["_primary_term"])
            written += 1
    if written:
        client.indices.refresh(index=index)
    return written


def cosine(a, b):
    numerator = sum(x * y for x, y in zip(a, b, strict=True))
    denominator = math.sqrt(sum(x * x for x in a) * sum(y * y for y in b))
    return numerator / denominator


def probe(selected, vectors, embedding_client: EmbeddingClient, feature_id: str, lang: str):
    origin = next((doc for doc in selected if doc["feature_id"] == feature_id), None)
    if origin is None:
        raise ValueError(f"Probe feature is not in the pilot: {feature_id}")
    text = origin["literal_meanings"][0]["translations"][lang]
    query_vector = embedding_client.embed([text], "query")[text]
    neighbors = []
    for doc in selected:
        if doc["feature_id"] == feature_id:
            continue
        best = max((cosine(query_vector, vectors[item["translations"][lang]])
                    for item in doc["literal_meanings"]), default=-1)
        neighbors.append({"feature_id": doc["feature_id"], "name": doc["names"].get(lang)
                          or doc["names"].get("en"), "cosine": round(best, 4)})
    neighbors.sort(key=lambda item: (-item["cosine"], item["feature_id"]))
    return {"feature_id": feature_id, "lang": lang, "instruct": embedding_client.instruct,
            "nearest_in_pilot": neighbors[:5]}


def create_run_logger(output_dir: Path):
    output_dir.mkdir(parents=True, exist_ok=True)
    logger = logging.Logger("backend.embed_meanings", level=logging.INFO)
    formatter = logging.Formatter("%(asctime)sZ %(levelname)s %(message)s",
                                  datefmt="%Y-%m-%dT%H:%M:%S")
    formatter.converter = time.gmtime
    for handler in (logging.FileHandler(output_dir / "run.log", encoding="utf-8"),
                    logging.StreamHandler()):
        handler.setFormatter(formatter)
        logger.addHandler(handler)
    return logger


def run_job(args, logger: logging.Logger, started_at: str, run_start: float):
    preparation_start = time.perf_counter()
    settings = Settings.from_env()
    entries = read_plan(args.plan)
    with connect(settings) as client:
        mapping = client.indices.get_mapping(index=settings.index)[settings.index]["mappings"]
        vector_mapping = mapping["properties"]["literal_meanings"]["properties"][EMBEDDING_FIELD]
        if any(vector_mapping["properties"][lang]["dims"] != DIMENSIONS for lang in EMBEDDING_LANGUAGES):
            raise ValueError("ES vector mapping does not match the model's 512 dimensions")
        selected = load_features(client, settings.index, entries)
        needed = pending_texts(selected, force=args.force)
        preparation_seconds = time.perf_counter() - preparation_start
        logger.info("Preparation finished: features=%d pending_vectors=%d elapsed=%.3fs",
                    len(selected), len(needed), preparation_seconds)
        report = {"index": settings.index, "model": MODEL, "dimensions": DIMENSIONS,
                  "selected": [{"feature_id": doc["feature_id"], "kind": doc["kind"],
                                "meanings": len(doc["literal_meanings"])} for doc in selected],
                  "pending_vectors": len(needed), "unique_pending_texts": len(set(needed)),
                  "document_text_type": "document", "apply": args.apply, "force": args.force}
        timing = {"started_at_utc": started_at,
                  "preparation_seconds": round(preparation_seconds, 3)}
        if args.apply:
            endpoint = os.getenv("DASHSCOPE_EMBEDDING_URL", DEFAULT_ENDPOINT)
            embedder = EmbeddingClient(args.output_dir / "cache", endpoint, args.instruct,
                                       args.batch_size, logger=logger)
            vectors = {item["translations"][lang]: item[EMBEDDING_FIELD][lang]
                       for doc in selected for item in doc["literal_meanings"]
                       for lang in EMBEDDING_LANGUAGES
                       if lang in item.get(EMBEDDING_FIELD, {})}
            embedding_start = time.perf_counter()
            vectors.update(embedder.embed(needed, "document"))
            timing["document_embedding_seconds"] = round(time.perf_counter() - embedding_start, 3)
            logger.info("Document embeddings finished: pending=%d cache_hits=%d elapsed=%.3fs",
                        len(needed), embedder.cache_hits, timing["document_embedding_seconds"])
            probe_start = time.perf_counter()
            report["probe"] = probe(selected, vectors, embedder, args.probe_feature_id,
                                    args.probe_language)
            timing["probe_seconds"] = round(time.perf_counter() - probe_start, 3)
            logger.info("Query probe finished: elapsed=%.3fs", timing["probe_seconds"])
            update_start = time.perf_counter()
            report["updated_features"] = apply_vectors(client, settings.index, selected, vectors,
                                                        force=args.force)
            timing["es_write_seconds"] = round(time.perf_counter() - update_start, 3)
            logger.info("ES update finished: features=%d elapsed=%.3fs",
                        report["updated_features"], timing["es_write_seconds"])
            report["api_calls"] = embedder.calls
            report["total_tokens"] = embedder.tokens
            report["cache_hits"] = embedder.cache_hits
            timing["api_seconds"] = round(embedder.api_seconds, 3)
            timing["api_batches"] = embedder.api_batches
        timing["finished_at_utc"] = datetime.now(timezone.utc).isoformat()
        timing["total_seconds"] = round(time.perf_counter() - run_start, 3)
        report["timing"] = timing
        logger.info("Run finished: api_calls=%d updated_features=%d total=%.3fs",
                    report.get("api_calls", 0), report.get("updated_features", 0),
                    timing["total_seconds"])
        if args.apply:
            (args.output_dir / "report.json").write_text(
                json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
        print(json.dumps(report, ensure_ascii=False))


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--plan", type=Path, default=ROOT / "data" / "embedding-pilot-20.json")
    parser.add_argument("--output-dir", type=Path, default=ROOT / "work" / "embedding-pilot-20")
    parser.add_argument("--instruct", default=DEFAULT_INSTRUCT,
                        help="English retrieval task instruction; applies only to query probe")
    parser.add_argument("--probe-feature-id", default="china-cn")
    parser.add_argument("--probe-language", choices=EMBEDDING_LANGUAGES, default="zh")
    parser.add_argument("--batch-size", type=int, default=20)
    parser.add_argument("--force", action="store_true",
                        help="Refresh vectors for existing translations (cached inputs are reused)")
    parser.add_argument("--apply", action="store_true", help="Call the API and write vectors to ES")
    args = parser.parse_args()
    if not 1 <= args.batch_size <= 20 or not args.instruct.strip():
        parser.error("batch-size must be 1..20 and instruct must not be blank")

    run_start = time.perf_counter()
    started_at = datetime.now(timezone.utc).isoformat()
    logger = create_run_logger(args.output_dir)
    logger.info("Run started: mode=%s model=%s", "apply" if args.apply else "dry-run", MODEL)
    try:
        run_job(args, logger, started_at, run_start)
    except Exception as exc:
        logger.error("Run failed after %.3fs: %s", time.perf_counter() - run_start, exc)
        raise
    finally:
        for handler in logger.handlers[:]:
            logger.removeHandler(handler)
            handler.close()


if __name__ == "__main__":
    main()
