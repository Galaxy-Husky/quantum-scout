#!/usr/bin/env python3
"""Resolve layer-1 planning seeds to explicit body-open or ordinary web-search actions; no IO."""
import argparse
import json
from pathlib import Path
import yaml
from searchos_network import public_url

def seed_actions(path=None):
    path = Path(path) if path else Path(__file__).resolve().parents[1] / 'config/search-strategy.yaml'
    config = yaml.safe_load(path.read_text())
    actions, seen = [], set()
    for seed in config['configured_seed_queries']['layer1_sources']:
        sid = seed['id']
        if sid in seen or bool(seed.get('url')) == bool(seed.get('query')) or 'source' in seed:
            raise ValueError('Each unique layer-1 seed needs exactly one explicit url or ordinary query')
        seen.add(sid)
        if seed.get('url'):
            actions.append({'id': sid, 'kind': 'open-source', 'url': public_url(seed['url'])})
        else:
            query = seed['query'].strip()
            if not query or query.lower().startswith(('arxiv:', 'author:')):
                raise ValueError('Legacy index-specific seed syntax is not a web query')
            actions.append({'id': sid, 'kind': 'search', 'query': query})
    return actions

def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--config', type=Path)
    args = parser.parse_args()
    print(json.dumps(seed_actions(args.config), ensure_ascii=False, indent=2))

if __name__ == '__main__':
    main()
