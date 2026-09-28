"""Generate resumable literal-meaning drafts with the locally authenticated Codex CLI."""
import argparse
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import re
import shutil
import subprocess
import tempfile
import time

from elasticsearch import helpers

from .config import ROOT, Settings, connect
from .indexing import Feature, SCHEMA

PROMPT_PATH = Path(__file__).parent / "prompts" / "literal_meanings.txt"
DEFAULT_LANGUAGES = ["zh", "en", "ja", "fr", "es"]
DEFAULT_MODEL = "gpt-6-sol"
DEFAULT_REASONING = "high"
FILLER_PREFIX = re.compile(r"^(?:可能意为|可能是|另一种说法|另一种解释|也可能意为|may mean|possibly means|another interpretation|alternatively\s*[:,])", re.I)
KINDS = {"country": ["country"], "city": ["city"], "town": ["town"],
         "state": ["state", "province"],
         "settlement": ["city", "town", "metropolis"], "selected": []}


def save_json(path, value):
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(path.name + "." + os.urandom(4).hex() + ".tmp")
    temporary.write_text(json.dumps(value, ensure_ascii=False, indent=2), encoding="utf-8")
    # Windows scanners can briefly hold the destination open while a long run
    # rewrites report.json after each place. Retry the atomic swap, not the model.
    for attempt in range(20):
        try:
            temporary.replace(path)
            return
        except PermissionError:
            if attempt == 19:
                raise
            time.sleep(min(0.5, 0.05 * (attempt + 1)))


def parse_languages(value):
    languages = [part.strip() for part in value.split(",")]
    if not languages or any(not re.fullmatch(r"[a-z]{2,8}(?:-[A-Za-z0-9]{1,8})*", x) for x in languages):
        raise argparse.ArgumentTypeError("Use comma-separated language tags, e.g. zh,en,ja,fr,es")
    if len(set(languages)) != len(languages) or len(languages) > 20:
        raise argparse.ArgumentTypeError("Use 1-20 distinct language tags")
    return languages


def payload_for(doc, languages):
    existing_languages = [lang for meaning in doc.get("literal_meanings", [])
                          for lang in meaning["translations"]]
    target_languages = list(dict.fromkeys([*languages, *existing_languages]))
    return {"feature_id": doc["feature_id"], "kind": doc["kind"], "names": doc["names"],
            "literal_name": doc.get("literal_name"),
            "literal_meanings": doc.get("literal_meanings", []),
            "target_languages": target_languages}


def needs_work(doc, languages, review_existing=False):
    meanings = doc.get("literal_meanings", [])
    return review_existing or not meanings or any(
        any(not meaning["translations"].get(lang) for meaning in meanings) for lang in languages)


def output_schema(languages):
    return {"type": "object", "additionalProperties": False,
        "required": ["feature_id", "status", "literal_name", "literal_meanings", "note"],
        "properties": {
            "feature_id": {"type": "string"},
            "status": {"type": "string", "enum": ["ready", "uncertain"]},
            "literal_name": {"anyOf": [{"type": "null"}, {"type": "object",
                "additionalProperties": False, "required": ["text", "lang"],
                "properties": {"text": {"type": "string"}, "lang": {"type": "string"}}}]},
            "literal_meanings": {"type": "array", "items": {"type": "object",
                "additionalProperties": False, "required": ["translations"], "properties": {
                    "translations": {"type": "object", "additionalProperties": False,
                        "required": languages, "properties": {lang: {"type": "string"} for lang in languages}}}}},
            "note": {"type": "string"}}}


def validate_result(result, payload):
    expected = {"feature_id", "status", "literal_name", "literal_meanings", "note"}
    if not isinstance(result, dict) or set(result) != expected or result["feature_id"] != payload["feature_id"]:
        raise ValueError("Unexpected response fields or feature identity")
    meanings = result["literal_meanings"]
    if not isinstance(meanings, list):
        raise ValueError("Meanings must be a list")
    if not isinstance(result["note"], str) or len(result["note"]) > 2000:
        raise ValueError("Invalid explanation")
    if result["status"] == "uncertain":
        if result["literal_name"] is not None or meanings:
            raise ValueError("Uncertain results must not contain publishable meanings")
    elif result["status"] == "ready":
        if not 1 <= len(meanings) <= 3:
            raise ValueError("Ready results require one to three distinct meanings")
        name = result["literal_name"]
        if not isinstance(name, dict) or set(name) != {"text", "lang"}:
            raise ValueError("Missing original name")
        if payload["literal_name"]:
            if name != payload["literal_name"]:
                raise ValueError("Must preserve the existing original name")
        elif (name["text"] not in payload["names"].values() or name["lang"] == "und"
              or (name["lang"] in payload["names"] and payload["names"][name["lang"]] != name["text"])):
            raise ValueError("Original name must match a supplied spelling and language")
        for meaning in meanings:
            if not isinstance(meaning, dict) or set(meaning) != {"translations"}:
                raise ValueError("Each meaning needs only a translations object")
            translations = meaning["translations"]
            if not isinstance(translations, dict) or set(translations) != set(payload["target_languages"]):
                raise ValueError("Every meaning must contain exactly the requested languages")
            if any(not isinstance(value, str) or not value.strip() or len(value) > 300 or "\n" in value or "\r" in value
                   for value in translations.values()):
                raise ValueError("Ready results require nonempty meanings of at most 300 characters on one line")
            if any(FILLER_PREFIX.match(value.strip()) for value in translations.values()):
                raise ValueError("Translation values must contain the meaning, without uncertainty prefaces")
        first_lang = payload["target_languages"][0]
        if len({item["translations"][first_lang].strip().casefold() for item in meanings}) != len(meanings):
            raise ValueError("Duplicate interpretations must be combined")
        # Reuse business validation, including original-name language syntax.
        Feature.model_validate({"feature_id": payload["feature_id"], "kind": payload["kind"],
            "names": payload["names"], "location": {"lon": 0, "lat": 0},
            "literal_name": name, "literal_meanings": meanings})
    else:
        raise ValueError("Invalid translation status")
    return result


def cache_key(payload, model, prompt, reasoning_effort=DEFAULT_REASONING):
    serialized = json.dumps({"payload": payload, "model": model, "reasoning_effort": reasoning_effort,
                             "prompt": prompt}, ensure_ascii=False, sort_keys=True)
    return hashlib.sha256(serialized.encode("utf-8")).hexdigest()


def corrected_languages(old_meanings, new_meanings, languages):
    changed_count = bool(old_meanings) and len(old_meanings) != len(new_meanings)
    return [lang for lang in languages if changed_count or any(
        old["translations"].get(lang) and old["translations"][lang] != new["translations"].get(lang)
        for old, new in zip(old_meanings, new_meanings))]


def call_codex(executable, payload, model, prompt, timeout, reasoning_effort=DEFAULT_REASONING):
    # Separate directory: the translation worker does not need the repository or ES credentials.
    with tempfile.TemporaryDirectory(prefix="literal-name-translation-") as directory:
        folder = Path(directory)
        schema_file, output_file = folder / "schema.json", folder / "result.json"
        save_json(schema_file, output_schema(payload["target_languages"]))
        command = [executable, "--search", "exec", "--ignore-user-config", "--ephemeral", "--skip-git-repo-check",
                   "--sandbox", "workspace-write", "--color", "never", "--output-schema", str(schema_file),
                   "--output-last-message", str(output_file), "--cd", directory]
        if model:
            command += ["--model", model]
        command += ["-c", f'model_reasoning_effort="{reasoning_effort}"', "-"]
        # CLI authentication is retained; unrelated app credentials are not passed along.
        env = {key: value for key, value in os.environ.items()
               if not key.startswith(("ES_", "ATLAS_", "DASHSCOPE_"))}
        try:
            completed = subprocess.run(command, input=prompt + "\n" + json.dumps(payload, ensure_ascii=False),
                text=True, encoding="utf-8", errors="replace", capture_output=True,
                cwd=directory, env=env, timeout=timeout, shell=False)
        except subprocess.TimeoutExpired as exc:
            raise RuntimeError(f"Codex timed out after {timeout}s") from exc
        if completed.returncode:
            # Do not dump CLI logs or authentication details into the console/report.
            raise RuntimeError(f"Codex exited with code {completed.returncode}; check codex login status and model access")
        if not output_file.exists():
            raise ValueError("Codex did not produce a final JSON response")
        return validate_result(json.loads(output_file.read_text(encoding="utf-8-sig")), payload)


def merge_result(doc, payload, result):
    validate_result(result, payload)
    if result["status"] != "ready":
        return None
    # Reject a stale draft if its original name, existing meanings, or identity changed.
    if payload_for(doc, payload["target_languages"]) != payload:
        raise ValueError("Feature changed since this draft was generated; regenerate it")
    old_meanings = doc.get("literal_meanings", [])
    corrected = corrected_languages(old_meanings, result["literal_meanings"], payload["target_languages"])
    merged = {**doc, "literal_name": result["literal_name"],
              "literal_meanings": result["literal_meanings"]}
    if corrected and merged.get("meaning_id"):
        merged["meaning_id"] = None
    Feature.model_validate(merged)
    patch = {"literal_name": merged["literal_name"], "literal_meanings": merged["literal_meanings"]}
    if corrected and doc.get("meaning_id"):
        patch["meaning_id"] = None
    return patch


def apply_result(client, settings, hit_id, payload, result, backup_dir):
    fresh = client.get(index=settings.index, id=hit_id)
    patch = merge_result(fresh["_source"], payload, result)
    if patch is None:
        return
    backup_name = hashlib.sha256(hit_id.encode()).hexdigest() + ".json"
    save_json(backup_dir / backup_name, {"index": settings.index, **dict(fresh)})
    client.update(index=settings.index, id=hit_id, doc=patch,
        if_seq_no=fresh["_seq_no"], if_primary_term=fresh["_primary_term"], refresh="wait_for")


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--kind", choices=KINDS, default="country", help="settlement includes cities/towns; selected accepts explicit IDs across kinds")
    parser.add_argument("--languages", type=parse_languages, default=DEFAULT_LANGUAGES)
    parser.add_argument("--model", default=DEFAULT_MODEL, help="Exact Codex model ID (default: gpt-6-sol)")
    parser.add_argument("--reasoning-effort", choices=["none", "minimal", "low", "medium", "high", "xhigh", "max", "ultra"],
                        default=DEFAULT_REASONING, help="Reasoning effort (default: high); support depends on the model")
    parser.add_argument("--codex-bin", default="codex", help="CLI executable name or absolute path")
    parser.add_argument("--feature-id", action="append", help="Restrict to specific feature IDs; repeatable")
    parser.add_argument("--feature-id-file", type=Path, help="JSON array of feature IDs; combine with --kind selected for mixed kinds")
    parser.add_argument("--guidance-file", type=Path, help="Optional trusted batch-specific research guidance appended to the prompt")
    parser.add_argument("--review-existing", action="store_true", help="Also recheck places already translated in every selected language")
    parser.add_argument("--limit", type=int, help="Maximum places to process after filtering")
    parser.add_argument("--delay", type=float, default=3, help="Seconds between model calls")
    parser.add_argument("--timeout", type=int, default=180, help="Timeout per CLI call")
    parser.add_argument("--retries", type=int, default=2, help="Retries per place with exponential backoff")
    parser.add_argument("--max-errors", type=int, default=3, help="Stop after this many failed places")
    parser.add_argument("--output-dir", type=Path, default=ROOT / "work" / "literal-translations")
    parser.add_argument("--dry-run", action="store_true", help="Save plan and prompts without calling Codex or modifying ES")
    parser.add_argument("--apply", action="store_true", help="Write ready drafts to ES, including corrections to selected languages")
    args = parser.parse_args(argv)
    if (args.limit is not None and args.limit < 1) or args.delay < 0 or args.timeout < 1 or args.max_errors < 1 or not 0 <= args.retries <= 5:
        parser.error("limit/timeout must be positive, delay nonnegative, retries 0-5")
    if args.dry_run and args.apply:
        parser.error("--dry-run and --apply cannot be combined")
    feature_ids = list(args.feature_id or [])
    if args.feature_id_file:
        from_file = json.loads(args.feature_id_file.read_text(encoding="utf-8"))
        if not isinstance(from_file, list) or not from_file or any(not isinstance(value, str) or not value for value in from_file):
            parser.error("--feature-id-file must contain a nonempty JSON array of IDs")
        feature_ids.extend(from_file)
    if len(feature_ids) != len(set(feature_ids)):
        parser.error("Feature IDs must be distinct")
    if args.kind == "selected" and not feature_ids:
        parser.error("--kind selected requires --feature-id or --feature-id-file")
    executable = shutil.which(args.codex_bin)
    if not args.dry_run and not executable:
        parser.error("Codex CLI not found; provide --codex-bin or install/login to Codex")
    prompt = PROMPT_PATH.read_text(encoding="utf-8")
    if args.guidance_file:
        guidance = args.guidance_file.read_text(encoding="utf-8").strip()
        if not guidance or len(guidance) > 5000:
            parser.error("--guidance-file must contain 1-5000 characters")
        prompt += "\nBATCH GUIDANCE (trusted):\n" + guidance + "\n"
    settings = Settings.from_env()
    run_dir = args.output_dir / "runs" / datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S%fZ")
    report = {"kind": args.kind, "languages": args.languages, "review_existing": args.review_existing, "model": args.model,
              "reasoning_effort": args.reasoning_effort,
              "index": settings.index, "dry_run": args.dry_run, "apply": args.apply, "items": []}
    with connect(settings) as client:
        mapping = client.indices.get_mapping(index=settings.index)[settings.index]["mappings"]
        if mapping.get("_meta", {}).get("schema") != SCHEMA:
            raise ValueError("Expected a features index with the required schema")
        filters = [{"terms": {"kind": KINDS[args.kind]}}] if KINDS[args.kind] else []
        if feature_ids:
            filters.append({"terms": {"feature_id": feature_ids}})
        hits = sorted(helpers.scan(client, index=settings.index, query={"query": {"bool": {"filter": filters}}}),
                      key=lambda hit: hit["_source"]["feature_id"])
        missing = set(feature_ids) - {hit["_source"]["feature_id"] for hit in hits}
        if missing:
            raise ValueError(f"Selected feature IDs are missing or have the wrong kind: {sorted(missing)}")
        pending = [(hit, payload_for(hit["_source"], args.languages)) for hit in hits
                   if needs_work(hit["_source"], args.languages, args.review_existing)][:args.limit]
        report.update(matched=len(hits), pending=len(pending))
        save_json(run_dir / "plan.json", {**report, "inputs": [data for _, data in pending]})
        save_json(run_dir / "report.json", report)
        (run_dir / "prompt.txt").write_text(prompt, encoding="utf-8")
        last_call = 0.0
        for hit, payload in pending:
            key = cache_key(payload, args.model, prompt, args.reasoning_effort)
            path = args.output_dir / "cache" / (key + ".json")
            item = {"feature_id": payload["feature_id"], "cache": str(path.resolve())}
            if args.dry_run:
                item["status"] = "planned"
            else:
                try:
                    if path.exists():
                        cached = json.loads(path.read_text(encoding="utf-8"))
                        result = validate_result(cached["result"], payload)
                        item["cached"] = True
                    else:
                        for attempt in range(args.retries + 1):
                            time.sleep(max(0, args.delay - (time.monotonic() - last_call)))
                            try:
                                result = call_codex(executable, payload, args.model, prompt, args.timeout, args.reasoning_effort)
                                break
                            except (RuntimeError, ValueError, OSError):
                                if attempt == args.retries:
                                    raise
                                time.sleep(min(60, 5 * 2**attempt))
                            finally:
                                last_call = time.monotonic()
                        save_json(path, {"input": payload, "result": result, "model": report["model"],
                            "reasoning_effort": args.reasoning_effort,
                            "generated_at": datetime.now(timezone.utc).isoformat(), "verified": False})
                    item["status"] = result["status"]
                    if result["status"] == "ready":
                        corrected = corrected_languages(payload["literal_meanings"], result["literal_meanings"],
                                                        payload["target_languages"])
                        if corrected:
                            item["corrected_languages"] = corrected
                            if hit["_source"].get("meaning_id"):
                                item["meaning_group_review_required"] = True
                    if args.apply and result["status"] == "ready":
                        apply_result(client, settings, hit["_id"], payload, result, run_dir / "backups")
                        item["applied"] = True
                except Exception as exc:
                    item.update(status="error", error=f"{type(exc).__name__}: {str(exc)[:300]}")
            report["items"].append(item)
            save_json(run_dir / "report.json", report)
            print(json.dumps(item, ensure_ascii=True), flush=True)
            if sum(entry["status"] == "error" for entry in report["items"]) >= args.max_errors:
                print("Stopped at --max-errors; inspect report and rerun to resume.", flush=True)
                break
    print(json.dumps({"report": str((run_dir / 'report.json').resolve()),
                      "pending": report["pending"]}, ensure_ascii=True))
    return 1 if any(item["status"] == "error" for item in report["items"]) else 0


if __name__ == "__main__":
    raise SystemExit(main())
