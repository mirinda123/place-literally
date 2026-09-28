"""List pending reader feedback from the local Elasticsearch index."""

import argparse
import json

from .config import Settings, connect


def main() -> None:
    parser = argparse.ArgumentParser(description="List pending place-meaning feedback as JSON lines")
    parser.add_argument("--limit", type=int, default=50, choices=range(1, 201), metavar="1-200")
    args = parser.parse_args()
    settings = Settings.from_env()
    with connect(settings) as client:
        if not client.indices.exists(index=settings.feedback_index):
            print("No feedback yet.")
            return
        result = client.search(index=settings.feedback_index,
                               query={"term": {"status": "pending"}},
                               sort=[{"created_at": "desc"}], size=args.limit)
        for hit in result["hits"]["hits"]:
            print(json.dumps(hit["_source"], ensure_ascii=False))


if __name__ == "__main__":
    main()
