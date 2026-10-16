#!/usr/bin/env python3
"""Look up explicit public model IDs/search terms on Hugging Face. No weights."""
import argparse
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import re
import urllib.error
import urllib.parse
import urllib.request


def get(url, limit=512000):
    req = urllib.request.Request(url, headers={'User-Agent': 'teamrepo-model-audit/1.1'})
    try:
        with urllib.request.urlopen(req, timeout=40) as r:
            body = r.read(limit + 1)
            if len(body) > limit:
                return None, 'response_too_large'
            return body.decode('utf-8'), None
    except urllib.error.HTTPError as e:
        return None, 'not_found' if e.code == 404 else 'http_%d' % e.code
    except (urllib.error.URLError, TimeoutError, OSError):
        return None, 'transport_error'


def lookup(model_id, cache):
    if not re.fullmatch(r'[\w.-]+/[\w.-]+', model_id):
        raise ValueError('Use an explicit public publisher/model ID')
    encoded = urllib.parse.quote(model_id, safe='/')
    url = 'https://huggingface.co/api/models/' + encoded
    stamp = datetime.now(timezone.utc).isoformat(timespec='seconds')
    raw, error = get(url)
    row = {'requested_id': model_id, 'lookup_status': error or 'found', 'checked_at': stamp, 'metadata_url': url}
    if error:
        return row
    metadata = json.loads(raw)
    canonical = metadata.get('id') or metadata.get('modelId') or model_id
    row.update(id=canonical, source_url='https://huggingface.co/' + canonical,
               source_revision=metadata.get('sha'), publisher=metadata.get('author') or canonical.split('/')[0],
               model_task=metadata.get('pipeline_tag'), architecture=metadata.get('config', {}).get('model_type'),
               license=metadata.get('cardData', {}).get('license'), languages=metadata.get('cardData', {}).get('language'),
               private=metadata.get('private'), gated=metadata.get('gated'),
               parameters=metadata.get('safetensors', {}).get('total'),
               match_status='exact' if canonical.lower() == model_id.lower() else 'alias')
    # Metadata does not describe the business task in the audited project.
    key = hashlib.sha256(model_id.encode()).hexdigest()[:20]
    (cache / (key + '.metadata.json')).write_text(raw, encoding='utf-8')
    revision = row['source_revision']
    if revision and re.fullmatch(r'[a-f0-9]{40}', revision):
        card_url = 'https://huggingface.co/%s/resolve/%s/README.md' % (urllib.parse.quote(canonical, safe='/'), revision)
        card, error = get(card_url)
        row['readme_status'] = error or 'found'
        row['readme_url'] = 'https://huggingface.co/%s/blob/%s/README.md' % (canonical, revision)
        if card is not None:
            (cache / (key + '.README.md')).write_text(card, encoding='utf-8')
    return row


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('--model', action='append', default=[])
    p.add_argument('--search', action='append', default=[], help='Public model name, never private code/configuration')
    p.add_argument('--cache', type=Path, required=True)
    p.add_argument('--output', type=Path, required=True)
    args = p.parse_args()
    if not args.model and not args.search:
        p.error('Provide --model and/or --search')
    args.cache.mkdir(parents=True, exist_ok=True)
    rows = [lookup(model_id, args.cache) for model_id in dict.fromkeys(args.model)]
    searches = []
    for query in args.search:
        url = 'https://huggingface.co/api/models?' + urllib.parse.urlencode({'search': query, 'limit': 5})
        raw, error = get(url)
        searches.append({'query': query, 'source_url': url, 'error': error,
                         'checked_at': datetime.now(timezone.utc).isoformat(timespec='seconds'),
                         'results': [{'id': m['id'], 'source_url': 'https://huggingface.co/' + m['id']} for m in json.loads(raw)] if raw else []})
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps({'schema_version': 1, 'models': rows, 'searches': searches}, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')
    print('%d model lookups, %d searches -> %s' % (len(rows), len(searches), args.output))


if __name__ == '__main__':
    main()
