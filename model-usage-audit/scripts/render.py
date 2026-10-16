#!/usr/bin/env python3
"""Render a portable model audit. No network or third-party dependencies."""
import argparse
import copy
import json
from pathlib import Path
from urllib.parse import urlsplit
from datetime import date


def safe_url(value):
    if not isinstance(value, str):
        return False
    try:
        p = urlsplit(value)
        return p.scheme == 'https' and bool(p.hostname) and not p.username and not p.password and not p.query and p.port in (None, 443)
    except ValueError:
        return False


def prepare(data, review=None, public_only=False, previous=None):
    data = copy.deepcopy(data)
    if data.get('schema_version') != 1:
        raise ValueError('Unsupported inventory schema')
    repos = [r for r in data['repositories'] if not public_only or not r['private']]
    data['repositories'] = repos
    if public_only:
        data['visibility'] = 'public'
        # Do not disclose private repository counts in the public export.
        data['accessible_count'] = len(repos)
    manual, warnings = [], []
    repo_map = {r['repository']: r for r in repos}
    for item in (review or {}).get('manual_usages', []):
        repo = repo_map.get(item['repository'])
        if repo is None:
            continue
        if item.get('reviewed_commit') != repo['commit']:
            warnings.append(item['id'] + ': manual finding SHA mismatch; ignored')
            continue
        if not item.get('id', '').startswith('manual:'):
            raise ValueError('Manual usage ID must start with manual:')
        if not item.get('evidence') or not all(safe_url(e.get('url')) for e in item['evidence']):
            raise ValueError('Manual discovery requires safe code evidence')
        if any(u['id'] == item['id'] for u in repo['usages']):
            raise ValueError('Manual usage ID collides with discovered candidate')
        base = dict(id=item['id'], repository=item['repository'], model=item['model'], family=item.get('family', 'unspecified'),
                    origin='unknown', status='candidate', stage='unknown', owner=None, task=None,
                    revision=None, license='unknown', upstream=None, evidence=item['evidence'], discovered_by='manual_review')
        repo['usages'].append(base)
        manual.append(item)
    reviews = (review or {}).get('reviews', []) + manual
    if len({r['id'] for r in reviews}) != len(reviews):
        raise ValueError('Duplicate review id')
    review_map = {r['id']: r for r in reviews}
    allowed = {'canonical_model', 'task', 'owner', 'origin', 'stage', 'status', 'revision',
               'upstream', 'license', 'review_evidence', 'runtime_evidence', 'lifecycle', 'role', 'base_model', 'notes', 'family',
               'business_task', 'business_domain', 'business_evidence', 'input', 'output', 'code_trace', 'model_info'}
    origins = {'open_source', 'open_weights', 'custom', 'fine_tuned', 'proprietary_api', 'unknown'}
    stages = {'documentation', 'configuration', 'experiment', 'training_code', 'inference_code', 'production_verified', 'unknown'}
    statuses = {'not_checked', 'no_issue_found', 'review_needed', 'deprecated', 'retired'}
    rows = []
    for repo in repos:
        for original in repo['usages']:
            u = copy.deepcopy(original)
            u.update(private=repo['private'], commit=repo['commit'], code_owner=repo.get('code_owner'),
                     scan_status=repo['scan_status'], lifecycle={'status': 'not_checked'})
            item = review_map.get(u['id'])
            applications = [{}]
            if item:
                if item.get('reviewed_commit') != repo['commit']:
                    warnings.append(u['id'] + ': review SHA mismatch; overlay ignored')
                elif not item.get('review_evidence') or not all(safe_url(x) for x in item['review_evidence']):
                    raise ValueError(u['id'] + ': reviewed item requires safe evidence URLs')
                else:
                    prefix = 'https://github.com/%s/blob/%s/' % (repo['repository'], repo['commit'])
                    if not any(url.startswith(prefix) for url in item['review_evidence']):
                        raise ValueError('Review must include code evidence pinned to the reviewed repository SHA')
                    u.update({k: item[k] for k in allowed if k in item})
                    applications = item.get('applications', [{}])
                    if not isinstance(applications, list) or not applications:
                        raise ValueError('applications must be nonempty list')
            for index, app in enumerate(applications):
                row = copy.deepcopy(u)
                row.update({k: app[k] for k in allowed if k in app})
                # The requested accountability rule is the GitHub repository owner.
                row['owner'] = repo.get('repository_owner') or repo['repository'].split('/')[0]
                row['owner_source'] = 'github_repository_owner'
                row['owner_evidence'] = repo.get('owner_evidence') or 'https://github.com/' + row['owner']
                if len(applications) > 1:
                    row['id'] += ':' + str(index)
                if row['origin'] not in origins or row['stage'] not in stages or row['status'] not in {'candidate', 'reviewed'}:
                    raise ValueError('Invalid origin, stage or review status')
                if row.get('upstream') and not safe_url(row['upstream']):
                    raise ValueError('Unsafe upstream URL')
                for key in ('review_evidence', 'runtime_evidence'):
                    if not all(safe_url(x) for x in row.get(key, [])):
                        raise ValueError('Unsafe evidence URL')
                if row['stage'] == 'production_verified' and not row.get('runtime_evidence'):
                    row['stage'] = 'inference_code'
                    warnings.append(row['id'] + ': no runtime evidence; production unverified')
                row['production_verified'] = row['stage'] == 'production_verified'
                row['business_analysis'] = 'pending'
                if row.get('business_task'):
                    evidence = row.get('business_evidence', [])
                    prefix = 'https://github.com/%s/blob/%s/' % (repo['repository'], repo['commit'])
                    if not evidence or not all(safe_url(url) and url.startswith(prefix) for url in evidence):
                        raise ValueError('Business task needs evidence pinned to the repository SHA')
                    row['business_analysis'] = 'analysed'
                info = row.get('model_info', {})
                if info.get('lookup_status') in {'found', 'related', 'code_only'}:
                    if not info.get('description') or not safe_url(info.get('source_url')) or not info.get('checked_at'):
                        raise ValueError('Model description requires a dated source')
                row['model_lookup'] = info.get('lookup_status', 'not_checked')
                lifecycle = row['lifecycle']
                if lifecycle.get('status') not in statuses:
                    raise ValueError('Invalid lifecycle status')
                if lifecycle['status'] in {'deprecated', 'retired', 'no_issue_found'}:
                    if not safe_url(lifecycle.get('source')) or not lifecycle.get('checked_at') or not lifecycle.get('reason'):
                        raise ValueError('Lifecycle conclusion requires dated source and applicable reason')
                    date.fromisoformat(lifecycle['checked_at'])
                row['risks'] = []
                if not row.get('owner'):
                    row['risks'].append('Ответственный неизвестен')
                if not row.get('revision'):
                    row['risks'].append('Версия весов / модели не установлена')
                if row['status'] == 'candidate':
                    row['risks'].append('Применение требует проверки')
                if lifecycle['status'] == 'not_checked':
                    row['risks'].append('Lifecycle не проверен')
                elif lifecycle['status'] in {'review_needed', 'deprecated', 'retired'}:
                    row['risks'].append('Lifecycle: ' + lifecycle['status'])
                rows.append(row)
    data['rows'] = rows
    data['warnings'] = warnings
    data['findings'] = []
    by_repo = {r['repository']: r for r in repos}
    for finding in (review or {}).get('repository_findings', []):
        repo = by_repo.get(finding['repository'])
        if repo is None:
            continue
        if finding.get('reviewed_commit') != repo['commit']:
            warnings.append(finding['repository'] + ': repository finding SHA mismatch; ignored')
            continue
        if not safe_url(finding.get('source')) or not finding.get('checked_at') or not finding.get('code_evidence') or not all(safe_url(x) for x in finding['code_evidence']):
            raise ValueError('Repository finding requires dated source and code evidence')
        date.fromisoformat(finding['checked_at'])
        data['findings'].append(finding)
    data['changes'] = []
    if previous:
        old = {r['repository']: r for r in previous['repositories'] if not public_only or not r['private']}
        for repo in repos:
            before = old.get(repo['repository'])
            if not before:
                data['changes'].append({'repository': repo['repository'], 'change': 'Репозиторий впервые в охвате', 'model': None})
                continue
            comparable = (data.get('collector_version') == previous.get('collector_version') and
                          data.get('collector_sha256') == previous.get('collector_sha256') and
                          data['coverage'] == previous.get('coverage') and
                          before['scan_status'] == repo['scan_status'] == 'scanned')
            a, b = {u['model'] for u in before['usages']}, {u['model'] for u in repo['usages']}
            for model in sorted(b - a):
                data['changes'].append({'repository': repo['repository'], 'model': model, 'change': 'Впервые обнаружено' if comparable else 'Новое обнаружение; охват несопоставим'})
            for model in sorted(a - b):
                data['changes'].append({'repository': repo['repository'], 'model': model, 'change': 'Не обнаружено в текущем срезе кода' if comparable else 'Не найдено; требуется перепроверка охвата'})
        for name in sorted(set(old) - {r['repository'] for r in repos}):
            data['changes'].append({'repository': name, 'model': None, 'change': 'Нет в текущем охвате; состояние неизвестно'})
    return data


def render(data, output):
    template = (Path(__file__).resolve().parent.parent / 'assets/dashboard.html').read_text(encoding='utf-8')
    script = (Path(__file__).resolve().parent.parent / 'assets/dashboard.js').read_text(encoding='utf-8')
    payload = json.dumps(data, ensure_ascii=False).replace('<', '\\u003c').replace('>', '\\u003e').replace('&', '\\u0026')
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(template.replace('__AUDIT_SCRIPT__', script).replace('__AUDIT_JSON__', payload), encoding='utf-8')


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('--input', required=True, type=Path)
    p.add_argument('--review', type=Path)
    p.add_argument('--previous', type=Path)
    p.add_argument('--output', required=True, type=Path)
    p.add_argument('--public-only', action='store_true')
    args = p.parse_args()
    read = lambda path: json.loads(path.read_text(encoding='utf-8')) if path else None
    data = prepare(read(args.input), read(args.review), args.public_only, read(args.previous))
    render(data, args.output)
    print('%d repositories, %d rows, %d warnings -> %s' % (len(data['repositories']), len(data['rows']), len(data['warnings']), args.output))


if __name__ == '__main__':
    main()
