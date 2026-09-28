"""Copy features-v9 into v10 with locative function words removed from /similar queries."""

import argparse
import json

from .config import Settings, connect
from .indexing import EMBEDDING_FIELD, EMBEDDING_LANGUAGES
from .reindex_search_v5 import reindex_search


PROBES = {
    "zh": ("similar_zh_v3", "名为母亲的河流旁的罗马堡垒", {"母亲", "罗马", "堡垒", "河流"}, {"的"}),
    "en": ("similar_en_v3", "Roman fort beside the river called Mother", {"roman", "fort", "mother", "river"}, {"besid"}),
    "ja": ("similar_ja_v3", "母と呼ばれる川のほとりのローマの砦", {"母", "ローマ", "砦", "川", "ほとり"}, set()),
    "fr": ("similar_fr_v3", "Fort romain au bord de la rivière appelée Mère", {"fort", "romain", "mère", "bord", "rivière"}, {"au"}),
    "es": ("similar_es_v3", "Fuerte romano junto al río llamado Madre", {"fuerte", "romano", "madre", "río"}, {"junto", "al"}),
}


def reindex_v10(client, settings, source: str, target: str):
    report = reindex_search(client, settings, source, target)
    tokens = {}
    for language, (analyzer, sample, required, forbidden) in PROBES.items():
        terms = [item["token"] for item in client.indices.analyze(
            index=target, analyzer=analyzer, text=sample)["tokens"]]
        if not required <= set(terms) or forbidden & set(terms):
            raise ValueError(f"Unexpected {language} query tokens: {terms}")
        tokens[language] = terms
    properties = client.indices.get_mapping(index=target)[target]["mappings"]["properties"]
    vector_fields = properties["literal_meanings"]["properties"][EMBEDDING_FIELD]["properties"]
    for language in EMBEDDING_LANGUAGES:
        field = vector_fields[language]
        if field["type"] != "dense_vector" or field["dims"] != 512 or field["similarity"] != "cosine":
            raise ValueError(f"Unexpected {language} vector mapping: {field}")
    report["locative_query_tokens"] = tokens
    report["vector_field"] = EMBEDDING_FIELD
    return report


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source", default="features-v9")
    parser.add_argument("--target", default="features-v10")
    args = parser.parse_args()
    settings = Settings.from_env()
    with connect(settings) as client:
        print(json.dumps(reindex_v10(client, settings, args.source, args.target), ensure_ascii=True))


if __name__ == "__main__":
    main()
