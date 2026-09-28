"""Copy features-v5 into v6 with file-backed, query-only similarity stop words."""

import argparse
import json

from .config import Settings, connect
from .reindex_search_v5 import reindex_search


PROBES = {
    "zh": ("similar_zh_v3", "台湾北部的城市", {"台湾", "北部"}, {"城市"}),
    "en": ("similar_en_v3", "City of northern Taiwan", {"northern", "taiwan"}, {"citi"}),
    "ja": ("similar_ja_v3", "台湾北部の都市", {"台湾", "北部"}, {"都市"}),
    "fr": ("similar_fr_v3", "Ville du nord de Taïwan", {"nord", "taïwan"}, {"ville"}),
    "es": ("similar_es_v3", "Ciudad del norte de Taiwán", {"norte", "taiwán"}, {"ciudad"}),
}


def reindex_v6(client, settings, source: str, target: str):
    report = reindex_search(client, settings, source, target)
    tokens = {}
    for language, (analyzer, sample, required, forbidden) in PROBES.items():
        terms = [item["token"] for item in client.indices.analyze(
            index=target, analyzer=analyzer, text=sample)["tokens"]]
        if not required <= set(terms) or forbidden & set(terms):
            raise ValueError(f"Unexpected {language} query tokens: {terms}")
        tokens[language] = terms
    report["city_query_tokens"] = tokens
    return report


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source", default="features-v5")
    parser.add_argument("--target", default="features-v6")
    args = parser.parse_args()
    with connect(Settings.from_env()) as client:
        print(json.dumps(reindex_v6(client, Settings.from_env(), args.source, args.target)))


if __name__ == "__main__":
    main()
