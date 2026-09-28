"""Copy features-v6 into v7 with generic land terms removed from /similar."""

import argparse
import json

from .config import Settings, connect
from .reindex_search_v6 import reindex_v6


PROBES = {
    "zh": ("similar_zh_v3", "气候温和之地", {"气候", "温和"}, {"之地"}),
    "en": ("similar_en_v3", "Land of a mild climate", {"mild", "climat"}, {"land"}),
    "ja": ("similar_ja_v3", "気候が穏やかな土地", {"気候", "穏やか"}, {"土地"}),
    "fr": ("similar_fr_v3", "Terre au climat doux", {"climat", "doux"}, {"terre"}),
    "es": ("similar_es_v3", "Tierra de clima templado", {"clima", "templado"}, {"tierra"}),
}


def reindex_v7(client, settings, source: str, target: str):
    report = reindex_v6(client, settings, source, target)
    tokens = {}
    for language, (analyzer, sample, required, forbidden) in PROBES.items():
        terms = [item["token"] for item in client.indices.analyze(
            index=target, analyzer=analyzer, text=sample)["tokens"]]
        if not required <= set(terms) or forbidden & set(terms):
            raise ValueError(f"Unexpected {language} query tokens: {terms}")
        tokens[language] = terms
    report["land_query_tokens"] = tokens
    return report


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source", default="features-v6")
    parser.add_argument("--target", default="features-v7")
    args = parser.parse_args()
    settings = Settings.from_env()
    with connect(settings) as client:
        print(json.dumps(reindex_v7(client, settings, args.source, args.target)))


if __name__ == "__main__":
    main()
