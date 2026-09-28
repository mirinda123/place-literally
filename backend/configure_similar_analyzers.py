"""Add the original query-only analyzers to a legacy features-v4 index."""

import argparse
import json

from .config import Settings, connect
from .indexing import SIMILAR_ANALYSIS


def configure(client, index: str):
    if not client.indices.exists(index=index):
        raise ValueError(f"Index does not exist: {index}")
    state = client.cluster.state(metric="metadata", index=index)["metadata"]["indices"][index]["state"]
    if state != "open":
        raise ValueError(f"Index must be open before migration: {index}")
    before = client.indices.get_settings(index=index)[index]["settings"]["index"]
    analysis = before.get("analysis", {})
    legacy = {
        group: {name: value for name, value in SIMILAR_ANALYSIS[group].items()
                if not name.endswith("_v2")}
        for group in ("filter", "analyzer")
    }
    expected = legacy["analyzer"]
    present = set(expected) & set(analysis.get("analyzer", {}))
    if present and present != set(expected):
        raise ValueError(f"Partial similarity analyzer configuration in {index}: {sorted(present)}")
    if not present:
        count_before = client.count(index=index)["count"]
        client.indices.close(index=index)
        try:
            client.indices.put_settings(index=index, settings={"analysis": legacy})
        finally:
            client.indices.open(index=index)
        count_after = client.count(index=index)["count"]
        if count_after != count_before:
            raise ValueError(f"Document count changed: {count_before} -> {count_after}")
        action = "configured"
    else:
        action = "already_configured"

    probes = {
        "similar_zh": ("南方的都城", {"南方", "都城"}, {"的"}),
        "similar_en": ("not of the central country", {"not", "central", "countri"}, {"of", "the"}),
        "similar_fr": ("pays de la ville", {"pays", "ville"}, {"de", "la"}),
        "similar_es": ("país de la ciudad", {"país", "ciudad"}, {"de", "la"}),
    }
    tokens = {}
    for analyzer, (sample, required, forbidden) in probes.items():
        terms = [item["token"] for item in client.indices.analyze(
            index=index, analyzer=analyzer, text=sample)["tokens"]]
        if not required <= set(terms) or forbidden & set(terms):
            raise ValueError(f"Unexpected {analyzer} tokens: {terms}")
        tokens[analyzer] = terms
    return {"index": index, "action": action, "probes": tokens}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--index", default=Settings.from_env().index)
    args = parser.parse_args()
    with connect(Settings.from_env()) as client:
        print(json.dumps(configure(client, args.index), ensure_ascii=False))


if __name__ == "__main__":
    main()
