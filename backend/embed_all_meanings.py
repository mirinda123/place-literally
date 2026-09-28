"""Fill missing document embeddings for every existing literal-meaning translation.

The current ES text remains authoritative. A resumed run skips stored vectors and
reuses successful API responses from the ignored output directory's cache.
"""

import argparse
import copy
import json
import os
import time
from datetime import datetime, timezone
from pathlib import Path

from elasticsearch import ConflictError
from elasticsearch.helpers import scan

from .config import ROOT, Settings, connect
from .embed_meanings import (DEFAULT_ENDPOINT, DEFAULT_INSTRUCT, DIMENSIONS, MODEL,
                             EmbeddingClient, create_run_logger, validate_vector)
from .indexing import EMBEDDING_FIELD, EMBEDDING_LANGUAGES


def inventory(client, index: str):
    """Read the entire current index, retaining vectors for accurate resume checks."""
    selected = []
    counts = {"all_features": 0, "features_with_meanings": 0, "meanings": 0,
              "existing_vectors": 0, "pending_vectors": 0}
    missing_translations = []
    for hit in scan(client, index=index, size=500, source_exclude_vectors=False,
                    query={"query": {"match_all": {}},
                           "_source": ["feature_id", "kind", "literal_meanings"]}):
        doc = hit["_source"]
        counts["all_features"] += 1
        meanings = doc.get("literal_meanings") or []
        if not meanings:
            continue
        counts["features_with_meanings"] += 1
        counts["meanings"] += len(meanings)
        pending = []
        for meaning_index, meaning in enumerate(meanings):
            translations = meaning.get("translations") or {}
            vectors = meaning.get(EMBEDDING_FIELD) or {}
            for language in EMBEDDING_LANGUAGES:
                text = translations.get(language)
                if not isinstance(text, str) or not text.strip():
                    missing_translations.append({"feature_id": doc["feature_id"],
                                                 "meaning_index": meaning_index,
                                                 "language": language})
                    continue
                if language in vectors:
                    validate_vector(vectors[language])
                    counts["existing_vectors"] += 1
                else:
                    pending.append((meaning_index, language, text))
                    counts["pending_vectors"] += 1
        if pending:
            selected.append({"feature_id": doc["feature_id"],
                             "translations": [copy.deepcopy(item.get("translations") or {})
                                              for item in meanings],
                             "pending": pending})
    return selected, counts, missing_translations


def apply_feature(client, index: str, selected: dict, vectors: dict[str, list[float]]):
    """Update only absent vectors after checking the original translations and ES version."""
    current = client.get(index=index, id=selected["feature_id"],
                         source_exclude_vectors=False)
    doc = current["_source"]
    meanings = doc.get("literal_meanings") or []
    if [item.get("translations") or {} for item in meanings] != selected["translations"]:
        return 0, "translations_changed"
    updated = copy.deepcopy(meanings)
    added = 0
    for meaning_index, language, text in selected["pending"]:
        stored = updated[meaning_index].setdefault(EMBEDDING_FIELD, {})
        if language not in stored:
            stored[language] = vectors[text]
            added += 1
    if not added:
        return 0, None
    try:
        client.update(index=index, id=selected["feature_id"],
                      doc={"literal_meanings": updated},
                      if_seq_no=current["_seq_no"],
                      if_primary_term=current["_primary_term"])
    except ConflictError:
        return 0, "version_conflict"
    return added, None


def run(args):
    output_dir = args.output_dir
    logger = create_run_logger(output_dir)
    started = time.perf_counter()
    started_utc = datetime.now(timezone.utc).isoformat()
    try:
        settings = Settings.from_env()
        with connect(settings) as client:
            mapping = client.indices.get_mapping(index=settings.index)[settings.index]["mappings"]
            properties = mapping["properties"]["literal_meanings"]["properties"][EMBEDDING_FIELD]["properties"]
            if any(properties[language].get("dims") != DIMENSIONS
                   for language in EMBEDDING_LANGUAGES):
                raise ValueError("Index vector mapping does not match the current 512-d model")
            selected, before, untranslated = inventory(client, settings.index)
            needed = [text for item in selected for _, _, text in item["pending"]]
            logger.info("Inventory: features=%d with_meanings=%d meanings=%d existing=%d pending=%d pending_features=%d",
                        before["all_features"], before["features_with_meanings"],
                        before["meanings"], before["existing_vectors"],
                        before["pending_vectors"], len(selected))
            report = {"index": settings.index, "model": MODEL, "dimensions": DIMENSIONS,
                      "started_at_utc": started_utc, "before": before,
                      "pending_features": len(selected),
                      "unique_pending_texts": len(set(needed)),
                      "missing_translations": untranslated,
                      "apply": args.apply}
            if args.apply and needed:
                if not os.getenv("DASHSCOPE_API_KEY"):
                    raise ValueError("DASHSCOPE_API_KEY is required for pending embeddings")
                embedder = EmbeddingClient(output_dir / "cache",
                                           os.getenv("DASHSCOPE_EMBEDDING_URL", DEFAULT_ENDPOINT),
                                           DEFAULT_INSTRUCT, args.batch_size, logger=logger)
                embedding_start = time.perf_counter()
                vectors = embedder.embed(needed, "document")
                report["embedding_seconds"] = round(time.perf_counter() - embedding_start, 3)
                logger.info("Embedding finished: unique_texts=%d calls=%d cache_hits=%d seconds=%.3f",
                            len(vectors), embedder.calls, embedder.cache_hits,
                            report["embedding_seconds"])
                report["api_calls"] = embedder.calls
                report["tokens"] = embedder.tokens
                report["cache_hits"] = embedder.cache_hits
                report["api_seconds"] = round(embedder.api_seconds, 3)
                written_features = 0
                written_vectors = 0
                conflicts = []
                for position, item in enumerate(selected, start=1):
                    added, reason = apply_feature(client, settings.index, item, vectors)
                    if added:
                        written_features += 1
                        written_vectors += added
                    if reason:
                        conflicts.append({"feature_id": item["feature_id"], "reason": reason})
                    if position % 25 == 0 or position == len(selected):
                        logger.info("Write progress: %d/%d features, %d vectors, %d conflicts",
                                    position, len(selected), written_vectors, len(conflicts))
                if written_features:
                    client.indices.refresh(index=settings.index)
                report["written_features"] = written_features
                report["written_vectors"] = written_vectors
                report["conflicts"] = conflicts
            elif args.apply:
                report.update(api_calls=0, tokens=0, cache_hits=0,
                              written_features=0, written_vectors=0, conflicts=[])
            if args.apply:
                _, after, _ = inventory(client, settings.index)
                report["after"] = after
            report["finished_at_utc"] = datetime.now(timezone.utc).isoformat()
            report["elapsed_seconds"] = round(time.perf_counter() - started, 3)
            (output_dir / ("report.json" if args.apply else "dry-run.json")).write_text(
                json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
            logger.info("Finished: pending_after=%s elapsed=%.3fs",
                        report.get("after", {}).get("pending_vectors", "dry-run"),
                        report["elapsed_seconds"])
            print(json.dumps(report, ensure_ascii=False))
            if args.apply and report["after"]["pending_vectors"]:
                raise RuntimeError("Some embeddings remain; rerun with the same output directory")
    finally:
        for handler in logger.handlers[:]:
            logger.removeHandler(handler)
            handler.close()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output-dir", type=Path,
                        default=ROOT / "work" / "embedding-all-20260927")
    parser.add_argument("--batch-size", type=int, default=20)
    parser.add_argument("--apply", action="store_true",
                        help="Call the provider and write only missing vectors")
    args = parser.parse_args()
    if not 1 <= args.batch_size <= 20:
        parser.error("batch-size must be 1..20")
    run(args)


if __name__ == "__main__":
    main()
