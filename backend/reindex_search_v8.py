"""Copy features-v7 into v8 with generic place terms removed from /similar."""

import argparse
import json

from .config import Settings, connect
from .reindex_search_v7 import reindex_v7


PROBES = {
    "zh": ("similar_zh_v3", "梅希特利的新地方", {"新"}, {"地方"}),
    "en": ("similar_en_v3", "New place of Mexitli", {"new", "mexitli"}, {"place"}),
    "ja": ("similar_ja_v3", "メシトリの新しい場所", {"新しい"}, {"場所"}),
    "fr": ("similar_fr_v3", "Nouveau lieu de Mexitli", {"nouveau", "mexitli"}, {"lieu"}),
    "es": ("similar_es_v3", "Nuevo lugar de Mexitli", {"nuevo", "mexitli"}, {"lugar"}),
}


def reindex_v8(client, settings, source: str, target: str):
    report = reindex_v7(client, settings, source, target)
    tokens = {}
    for language, (analyzer, sample, required, forbidden) in PROBES.items():
        terms = [item["token"] for item in client.indices.analyze(
            index=target, analyzer=analyzer, text=sample)["tokens"]]
        if not required <= set(terms) or forbidden & set(terms):
            raise ValueError(f"Unexpected {language} query tokens: {terms}")
        tokens[language] = terms
    report["place_query_tokens"] = tokens
    return report


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source", default="features-v7")
    parser.add_argument("--target", default="features-v8")
    args = parser.parse_args()
    settings = Settings.from_env()
    with connect(settings) as client:
        print(json.dumps(reindex_v8(client, settings, args.source, args.target)))


if __name__ == "__main__":
    main()
