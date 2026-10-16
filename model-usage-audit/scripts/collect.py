#!/usr/bin/env python3
"""Read-only GitHub model discovery. Python 3.9+, stdlib and authenticated gh.

This produces candidates, NOT an assertion of production use or a complete SBOM.
No repository code, notebook outputs or model weights are executed/downloaded.
"""
import argparse
import base64
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, timezone
import hashlib
import http.client
import json
from pathlib import Path, PurePosixPath
import re
import subprocess
import time
import urllib.error
import urllib.parse
import urllib.request

VERSION = '1.1.0'
EXTS = {'.py', '.ipynb', '.yaml', '.yml', '.json', '.toml', '.md', '.txt', '.js', '.ts', '.tsx', '.sh', '.ini', '.cfg'}
SKIP = {'.git', 'node_modules', '.venv', 'venv', 'vendor', 'third_party', 'dist', 'build', '__pycache__'}
FAMILIES = {
    'YOLO': r'\byolov?[3-9][a-z0-9_.-]*\b|\byolo11[a-z0-9_.-]*\b',
    'MegaDetector': r'\bmegadetector\b|\bmd_v[45][a-z0-9_.-]*\b',
    'SAM': r'\bsam[_-]?(?:vit_[bhl]|2(?:\.1)?|3)(?:[_a-z0-9.-]*)\b|\bsegment_anything\b',
    'ResNet': r'\bresnet(?:18|34|50|101|152)(?:[_a-z0-9.-]*)\b',
    'EfficientNet': r'\befficientnet[_-]?[a-z0-9_.-]+\b',
    'DINO': r'\bdinov[23][a-z0-9_.-]*\b',
    'Whisper': r'\bwhisper(?:[_-](?:tiny|base|small|medium|large)(?:[._-][a-z0-9]+)*)?\b',
    'CLIP': r'\b(?:open_clip|clip-vit[a-z0-9/_.-]*|ViT-[BLH]/\d+)\b',
    'BERT': r'\b(?:rubert|bert-base|bert-large|distilbert)[a-z0-9/_.-]*\b',
    'LLM': r'\b(?:gpt-[a-z0-9_.-]+|gigachat(?:-[a-z0-9_.-]+)?|qwen[0-9.a-z_-]*|llama[0-9.a-z_-]*|gemini-[a-z0-9_.-]+|deepseek-[a-z0-9_.-]+|mistral-[a-z0-9_.-]+)\b',
    'Audio Spectrogram Transformer': r'\b(?:ASTModel|ASTForAudioClassification|ASTForAudioClassificationCustom)\b',
    'MediaPipe': r'\bmediapipe\b',
    'MimicMotion': r'\bMimicMotion\b',
    'S3D': r'\bS3D\b',
    'VideoMAE': r'\bvideomae[a-z0-9/_.-]*\b',
}
PATTERNS = [(k, re.compile(v, re.I)) for k, v in FAMILIES.items()]
LOAD = re.compile(r'''(?:from_pretrained|create_model|SentenceTransformer|YOLO|hf_hub_download)\s*\(\s*(?:repo_id\s*=\s*)?["']([^"'\n]{2,180})["']''')
CHECKPOINT = re.compile(r'''["']([^"'\n]{1,180}\.(?:pt|pth|ckpt|onnx|safetensors|h5|tflite))["']''', re.I)
CONFIG_KEY = r'(?:model(?:_name|_id|_path|_name_or_path)?|checkpoint|weights|backbone)'
QUOTED_CONFIG = re.compile(CONFIG_KEY + r'''\s*=\s*["']([^"'\n]{2,180})["']''', re.I)
YAML_CONFIG = re.compile(r'''^\s*["']?''' + CONFIG_KEY + r'''["']?\s*[:=]\s*["']?([\w./-]{2,180})''', re.I)
SECRET = re.compile(r'(?:gh[pousr]_[A-Za-z0-9_]{16,}|sk-[A-Za-z0-9_-]{16,}|(?:api[_-]?key|password|token|secret)\s*[:=])', re.I)


def now():
    return datetime.now(timezone.utc).isoformat(timespec='seconds')


def safe_id(value):
    return bool(re.fullmatch(r'[A-Za-z0-9][A-Za-z0-9_./:@+-]{0,179}', value)) and not SECRET.search(value) and '..' not in value and '://' not in value


def logical_lines(path, content):
    if path.endswith('.ipynb'):
        # Notebook outputs may contain credentials, huge binary data and misleading results.
        nb = json.loads(content)
        for index, cell in enumerate(nb.get('cells', [])):
            for n, line in enumerate(''.join(cell.get('source', [])).splitlines(), 1):
                yield n, line, 'cell:%d' % index, cell.get('cell_type') == 'code'
    else:
        code = PurePosixPath(path).suffix in {'.py', '.js', '.ts', '.tsx', '.sh'}
        for n, line in enumerate(content.splitlines(), 1):
            yield n, line, None, code


def discover(path, content):
    found = []
    for n, line, cell, code in logical_lines(path, content):
        if SECRET.search(line) or len(line) > 4000:
            continue
        comment = line.lstrip().startswith(('#', '//', '*', '>'))
        context = 'code' if code and not comment else ('documentation' if path.endswith('.md') or comment or (cell and not code) else 'configuration')
        hits = []
        for match in LOAD.finditer(line):
            if safe_id(match[1]):
                hits.append((match[1], 'loader', 'unspecified'))
        for match in CHECKPOINT.finditer(line):
            if safe_id(match[1]):
                hits.append((match[1], 'checkpoint', 'unspecified'))
        for family, pattern in PATTERNS:
            for match in pattern.finditer(line):
                if not any(x in match[0].lower() for x in ('factory', '_utils', 'from_pretrained', 'forconditionalgeneration')):
                    hits.append((match[0], 'family_reference', family))
        config = list(QUOTED_CONFIG.finditer(line))
        if PurePosixPath(path).suffix.lower() in {'.yaml', '.yml', '.json', '.toml', '.ini', '.cfg'}:
            config += list(YAML_CONFIG.finditer(line))
        for match in config:
            value = match[1]
            if safe_id(value) and not value.isdigit() and value.lower() not in {'true', 'false', 'none', 'null', 'self', 'model', 'str', 'path', 'dict', 'list', 'args', 'config'} and not value.startswith(('path/to/', 'your_', 'path_to_', 'eval_')):
                hits.append((value, 'model_configuration', 'unspecified'))
        for model, kind, family in hits:
            if safe_id(model):
                found.append(dict(model=model, family=family, kind=kind, context=context,
                                  path=path, line=n, cell=cell))
    return found


def choose_files(tree, limit, max_bytes):
    selected, skipped = [], {'unsupported_or_excluded': 0, 'oversize': 0, 'budget': 0}
    candidates = []
    for item in tree:
        p = PurePosixPath(item['path'])
        if item.get('type') != 'blob' or (p.suffix.lower() not in EXTS and p.name != 'CODEOWNERS') or SKIP.intersection(p.parts) or p.name.endswith(('.lock', '-lock.json')) or p.name.startswith('.env'):
            skipped['unsupported_or_excluded'] += item.get('type') == 'blob'
            continue
        if item.get('size', 0) > max_bytes:
            skipped['oversize'] += 1
            continue
        path = str(p)
        priority = 0 if p.name in {'CODEOWNERS', 'model-usage.json'} else 1 if re.search(r'(model|infer|predict|train|config|requirements|pyproject|readme|deploy|pipeline|main|app|service|agent)', path, re.I) else 2
        candidates.append((priority, len(p.parts), path, item))
    candidates.sort(key=lambda x: x[:3])
    selected = [x[3] for x in candidates[:limit]]
    skipped['budget'] = max(0, len(candidates) - limit)
    return selected, skipped, len(candidates)


class GitHub:
    def __init__(self, cache):
        self.token = subprocess.check_output(['gh', 'auth', 'token'], text=True).strip()
        self.cache = Path(cache)
        self.cache.mkdir(parents=True, exist_ok=True)

    def get(self, endpoint, immutable=False):
        key = hashlib.sha256(endpoint.encode()).hexdigest()
        file = self.cache / (key + '.json')
        if immutable and file.exists():
            return json.loads(file.read_text())
        req = urllib.request.Request('https://api.github.com/' + endpoint,
            headers={'Authorization': 'Bearer ' + self.token, 'Accept': 'application/vnd.github+json', 'User-Agent': 'teamrepo-model-usage-audit/' + VERSION})
        for attempt in range(3):
            try:
                with urllib.request.urlopen(req, timeout=45) as response:
                    data = json.load(response)
                if immutable:
                    file.write_text(json.dumps(data), encoding='utf-8')
                return data
            except urllib.error.HTTPError as exc:
                if exc.code not in {429, 500, 502, 503, 504} or attempt == 2:
                    raise RuntimeError('GitHub HTTP %s' % exc.code) from None
                time.sleep(2 ** attempt)
            except (urllib.error.URLError, TimeoutError, OSError, http.client.RemoteDisconnected):
                if attempt == 2:
                    raise RuntimeError('GitHub transport unavailable after 3 attempts') from None
                time.sleep(2 ** attempt)
        raise RuntimeError('GitHub retries exhausted')


def list_repos(api, org, visibility):
    repos, page = [], 1
    while True:
        batch = api.get('orgs/%s/repos?per_page=100&type=all&page=%d' % (org, page))
        repos.extend(batch)
        if len(batch) < 100:
            break
        page += 1
    if visibility == 'public':
        repos = [r for r in repos if not r['private']]
    return sorted(repos, key=lambda r: r['full_name'].lower())


def scan_repo(api, repo, args):
    name = repo['full_name']
    result = dict(repository=name, url=repo['html_url'], private=repo['private'], archived=repo['archived'],
                  fork=repo['fork'], description=repo.get('description'), pushed_at=repo['pushed_at'],
                  branch=repo['default_branch'], commit=None, scan_status='unavailable',
                  files_read=0, candidates_total=None, tree_truncated=None, skipped={}, errors=[],
                  owner=repo['owner']['login'], repository_owner=repo['owner']['login'],
                  owner_evidence=repo['owner']['html_url'], owner_source='github_repository_owner',
                  code_owner=None, code_owner_evidence=None, usages=[], manifests=[])
    try:
        if repo.get('size') == 0:
            result['scan_status'] = 'empty'
            return result
        commit = api.get('repos/%s/commits/%s' % (name, urllib.parse.quote(repo['default_branch'], safe='')))
        sha = commit['sha']
        result['commit'] = sha
        tree = api.get('repos/%s/git/trees/%s?recursive=1' % (name, commit['commit']['tree']['sha']), True)
        result['tree_truncated'] = tree.get('truncated', False)
        files, skipped, total = choose_files(tree.get('tree', []), args.max_files, args.max_bytes)
        result.update(candidates_total=total, skipped=skipped)
        groups = {}
        for item in files:
            path = item['path']
            try:
                blob = api.get('repos/%s/git/blobs/%s' % (name, item['sha']), True)
                content = base64.b64decode(blob['content']).decode('utf-8')
                result['files_read'] += 1
                if PurePosixPath(path).name == 'CODEOWNERS':
                    # Only the catch-all declaration; path ownership is not model ownership.
                    owners = [l.split()[1:] for l in content.splitlines() if l.strip().startswith('* ')]
                    if owners:
                        result['code_owner'] = ' '.join(owners[-1])
                        result['code_owner_evidence'] = 'https://github.com/%s/blob/%s/%s' % (name, sha, urllib.parse.quote(path))
                if PurePosixPath(path).name == 'model-usage.json':
                    # Preserve declarations separately; agent validates them against code.
                    result['manifests'].append({'path': path, 'sha': item['sha']})
                for hit in discover(path, content):
                    key = hit['model'].lower()
                    ev = {k: hit[k] for k in ('path', 'line', 'cell', 'kind', 'context')}
                    ev['blob_sha'] = item['sha']
                    ev['url'] = 'https://github.com/%s/blob/%s/%s%s' % (name, sha, urllib.parse.quote(path), '' if hit['cell'] else '#L%d' % hit['line'])
                    if key not in groups:
                        groups[key] = dict(id=hashlib.sha256((name + ':' + key).encode()).hexdigest()[:16],
                                           repository=name, model=hit['model'], family=hit['family'],
                                           origin='unknown', license='unknown', owner=None, task=None,
                                           stage='unknown', production_verified=False, status='candidate',
                                           revision=None, upstream=None, evidence=[])
                    usage = groups[key]
                    if usage['family'] == 'unspecified' and hit['family'] != 'unspecified':
                        usage['family'] = hit['family']
                    if ev not in usage['evidence']:
                        usage['evidence'].append(ev)
            except (RuntimeError, UnicodeError, ValueError, KeyError, TypeError, AttributeError) as exc:
                result['errors'].append({'path': path, 'error': type(exc).__name__})
        result['usages'] = sorted(groups.values(), key=lambda u: u['model'].lower())
        result['scan_status'] = 'partial' if result['errors'] or tree.get('truncated') or skipped['oversize'] or skipped['budget'] else 'scanned'
    except Exception as exc:
        # No raw exceptions: URLs/headers/body can contain sensitive material.
        result['errors'].append({'error': type(exc).__name__})
    return result


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('--org', required=True)
    p.add_argument('--visibility', choices=['public', 'all'], default='public')
    p.add_argument('--repo', action='append', help='Repository name; repeat for explicit subset')
    p.add_argument('--max-files', type=int, default=25)
    p.add_argument('--max-bytes', type=int, default=300000)
    p.add_argument('--workers', type=int, default=6)
    p.add_argument('--output', type=Path, required=True)
    p.add_argument('--cache', type=Path, required=True, help='Local private cache, never commit')
    args = p.parse_args()
    if not re.fullmatch(r'[A-Za-z0-9][A-Za-z0-9-]{0,38}', args.org):
        p.error('Invalid organization')
    if min(args.max_files, args.max_bytes, args.workers) <= 0 or args.workers > 12:
        p.error('Budgets must be positive; max 12 workers')
    api = GitHub(args.cache)
    started = now()
    repos = list_repos(api, args.org, args.visibility)
    accessible_count = len(repos)
    if args.repo:
        repos = [r for r in repos if r['name'] in args.repo]
        missing = set(args.repo) - {r['name'] for r in repos}
        if missing:
            p.error('Requested repositories unavailable under selected visibility: ' + ', '.join(sorted(missing)))
    data = dict(schema_version=1, collector_version=VERSION,
                collector_sha256=hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
                organization=args.org, started_at=started,
                generated_at=None, visibility=args.visibility, accessible_count=accessible_count,
                coverage={'branch_scope': 'default_only', 'max_files_per_repo': args.max_files,
                          'max_bytes_per_file': args.max_bytes, 'executed_repository_code': False,
                          'excluded': sorted(SKIP), 'unsupported_formats_excluded': True},
                repositories=[])
    with ThreadPoolExecutor(max_workers=args.workers) as pool:
        futures = {pool.submit(scan_repo, api, r, args): r for r in repos}
        for index, future in enumerate(as_completed(futures), 1):
            row = future.result()
            data['repositories'].append(row)
            print('%d/%d %s: %s, %d files, %d candidates' %
                  (index, len(repos), row['repository'], row['scan_status'], row['files_read'], len(row['usages'])), flush=True)
    data['repositories'].sort(key=lambda r: r['repository'].lower())
    data['generated_at'] = now()
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(data, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')


if __name__ == '__main__':
    main()
