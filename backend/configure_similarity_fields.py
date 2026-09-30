"""Add and backfill symmetric lexical-search subfields in an existing index."""

import argparse
import json
from dataclasses import replace

from .config import Settings, connect
from .indexing import ensure_similarity_fields


def main():
    settings = Settings.from_env()
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--index", default=settings.index)
    args = parser.parse_args()
    settings = replace(settings, index=args.index)
    with connect(settings) as client:
        print(json.dumps(ensure_similarity_fields(client, settings.index), ensure_ascii=False))


if __name__ == "__main__":
    main()
