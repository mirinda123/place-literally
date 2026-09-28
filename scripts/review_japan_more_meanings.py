"""Apply source-checked edits to the additional Japan city batch."""

import argparse
from datetime import datetime, timezone
import json

from backend.config import ROOT, Settings, connect
from backend.indexing import Feature


FEATURE_ID = "osm-node-1985508816"
OUTPUT_ROOT = ROOT / "work/literal-translations/japan-more-cities-20260927"
SOURCES = [
    "https://www.city.fukuyama.hiroshima.jp/site/profile/",
    "https://kotobank.jp/word/%E7%A6%8F%E5%B1%B1%E5%B8%82-124160",
]


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--apply", action="store_true")
    args = parser.parse_args()
    settings = Settings.from_env()
    with connect(settings) as client:
        hit = client.get(index=settings.index, id=FEATURE_ID)
        doc = hit["_source"]
        if doc.get("feature_id") != FEATURE_ID or doc.get("kind") != "city":
            raise ValueError("Unexpected feature identity")
        if doc.get("literal_name") != {"text": "福山市", "lang": "ja"}:
            raise ValueError("Unexpected original name")
        meanings = doc.get("literal_meanings", [])
        if len(meanings) != 3:
            raise ValueError("Unexpected meaning count")
        current = meanings[1]["translations"]["zh"]
        if current not in {"福山", "福气之山"}:
            raise ValueError(f"Meaning changed: {current}")
        report = {
            "index": settings.index,
            "feature_id": FEATURE_ID,
            "before": current,
            "after": "福气之山",
            "reason": "The draft repeated the name rather than expressing its lexical sense, while the other four translations say 'Mountain of Good Fortune'.",
            "sources": SOURCES,
            "apply": args.apply,
        }
        if args.apply and current != "福气之山":
            patch_meanings = json.loads(json.dumps(meanings, ensure_ascii=False))
            for item in patch_meanings:
                item.pop("vectors", None)
            patch_meanings[1]["translations"]["zh"] = "福气之山"
            patch = {"literal_meanings": patch_meanings, "meaning_id": None}
            Feature.model_validate({**doc, **patch})
            backup = OUTPUT_ROOT / "editorial-review" / datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S%fZ")
            backup.mkdir(parents=True, exist_ok=False)
            (backup / "before.json").write_text(
                json.dumps({"hit": dict(hit), "patch": patch}, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
            )
            client.update(
                index=settings.index,
                id=FEATURE_ID,
                doc=patch,
                if_seq_no=hit["_seq_no"],
                if_primary_term=hit["_primary_term"],
                refresh="wait_for",
            )
            report["backup_dir"] = str(backup.resolve())
            (backup / "report.json").write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(report, ensure_ascii=False))


if __name__ == "__main__":
    main()
