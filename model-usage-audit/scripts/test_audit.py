"""Regression checks for evidence, privacy, freshness and lifecycle semantics."""
import copy
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
from collect import choose_files, discover
from render import prepare, render


def snapshot(private=False):
    return {'schema_version': 1, 'collector_version': '1', 'visibility': 'all', 'accessible_count': 2,
            'coverage': {'max_files_per_repo': 25}, 'repositories': [
                {'repository': 'org/repo', 'private': private, 'commit': 'a' * 40, 'owner': None,
                 'scan_status': 'scanned', 'usages': [
                     {'id': 'one', 'repository': 'org/repo', 'model': 'x', 'status': 'candidate',
                      'origin': 'unknown', 'stage': 'unknown', 'evidence': []}]}]}


def review(**kw):
    item = {'id': 'one', 'reviewed_commit': 'a' * 40, 'status': 'reviewed',
            'review_evidence': ['https://github.com/org/repo/blob/' + 'a' * 40 + '/app.py#L1']}
    item.update(kw)
    return {'reviews': [item]}


class AuditTests(unittest.TestCase):
    def test_framework_import_is_not_a_model(self):
        self.assertEqual(discover('app.py', 'import torch\nimport transformers\nimport timm'), [])

    def test_loader_is_evidence_not_production(self):
        hit = discover('app.py', "m = AutoModel.from_pretrained('publisher/model')")[0]
        self.assertEqual((hit['model'], hit['kind'], hit['context']), ('publisher/model', 'loader', 'code'))

    def test_notebook_ignores_outputs_and_keeps_cell(self):
        nb = {'cells': [{'cell_type': 'code', 'source': ['m=YOLO("yolov8n.pt")'],
                         'outputs': [{'text': ['from_pretrained("private/secret")']}]}]}
        hits = discover('notebook.ipynb', json.dumps(nb))
        self.assertTrue(hits)
        self.assertTrue(all(h['cell'] == 'cell:0' and 'secret' not in h['model'] for h in hits))

    def test_comment_does_not_become_executable_evidence(self):
        self.assertEqual(discover('app.py', '# YOLO("yolov8n.pt")')[0]['context'], 'documentation')

    def test_python_symbols_are_not_model_identifiers(self):
        self.assertEqual(discover('app.py', 'model = nn.Module()\nmodel = args.model\nmodel = torch.load(path)\nmodel: bool = True'), [])
        self.assertEqual(discover('config.yaml', 'model: 512\nweights: null'), [])

    def test_yaml_hub_identifier_kept_in_full(self):
        hits = discover('config.yaml', 'model_name_or_path: Qwen/Qwen2.5-VL-7B-Instruct')
        self.assertIn('Qwen/Qwen2.5-VL-7B-Instruct', [h['model'] for h in hits])

    def test_secret_line_is_not_captured(self):
        self.assertEqual(discover('app.py', 'token = "sk-12345678901234567890"; m=YOLO("yolov8n.pt")'), [])

    def test_budget_and_codeowners(self):
        tree = [{'type': 'blob', 'path': '.github/CODEOWNERS', 'size': 20},
                {'type': 'blob', 'path': 'model.py', 'size': 20},
                {'type': 'blob', 'path': 'huge.py', 'size': 10000},
                {'type': 'blob', 'path': '.env', 'size': 20}]
        files, skipped, total = choose_files(tree, 1, 100)
        self.assertEqual(files[0]['path'], '.github/CODEOWNERS')
        self.assertEqual((total, skipped['budget'], skipped['oversize']), (2, 1, 1))

    def test_sha_mismatch_ignores_review(self):
        result = prepare(snapshot(), review(reviewed_commit='b' * 40))
        self.assertEqual(result['rows'][0]['status'], 'candidate')
        self.assertTrue(result['warnings'])

    def test_production_needs_runtime_evidence(self):
        result = prepare(snapshot(), review(stage='production_verified'))
        self.assertEqual(result['rows'][0]['stage'], 'inference_code')
        self.assertFalse(result['rows'][0]['production_verified'])

    def test_deprecation_requires_dated_source(self):
        with self.assertRaises(ValueError):
            prepare(snapshot(), review(lifecycle={'status': 'deprecated', 'reason': 'Old'}))

    def test_signed_or_unsafe_links_rejected(self):
        for url in ['javascript:alert(1)', 'https://x.org/a?token=secret', 'https://user:pass@x.org/a']:
            with self.assertRaises(ValueError):
                prepare(snapshot(), review(upstream=url))

    def test_public_export_does_not_reveal_private_counts_or_previous_repo(self):
        result = prepare(snapshot(True), public_only=True, previous=snapshot(True))
        self.assertEqual(result['accessible_count'], 0)
        self.assertEqual((result['rows'], result['changes']), ([], []))

    def test_partial_disappearance_is_unknown(self):
        previous = snapshot()
        data = snapshot()
        data['repositories'][0]['usages'] = []
        data['repositories'][0]['scan_status'] = 'partial'
        change = prepare(data, previous=previous)['changes'][0]
        self.assertIn('перепроверка', change['change'])

    def test_multiple_applications_remain_separate(self):
        rows = prepare(snapshot(), review(applications=[{'task': 'detect'}, {'task': 'classify'}]))['rows']
        self.assertEqual([r['task'] for r in rows], ['detect', 'classify'])
        self.assertNotEqual(rows[0]['id'], rows[1]['id'])

    def test_review_evidence_must_match_repository_sha(self):
        with self.assertRaises(ValueError):
            prepare(snapshot(), review(review_evidence=['https://github.com/org/repo/blob/main/app.py#L1']))

    def test_manual_findings_are_versioned_and_public_filtered(self):
        item = review()['reviews'][0]
        item.update(id='manual:one', repository='org/repo', model='custom', evidence=[{'url': item['review_evidence'][0]}])
        result = prepare(snapshot(), {'manual_usages': [item]})
        self.assertEqual(len(result['rows']), 2)
        item['reviewed_commit'] = 'b' * 40
        result = prepare(snapshot(), {'manual_usages': [item]})
        self.assertEqual(len(result['rows']), 1)
        self.assertTrue(result['warnings'])
        self.assertEqual(prepare(snapshot(True), {'manual_usages': [item]}, public_only=True)['rows'], [])

    def test_collection_uses_all_pages_and_keeps_visibility(self):
        from collect import list_repos
        class FakeAPI:
            def __init__(self):
                self.calls = []
            def get(self, path):
                self.calls.append(path)
                return [{'full_name': 'org/r%03d' % i, 'private': i == 100} for i in (range(100) if path.endswith('&page=1') else [100])]
        api = FakeAPI()
        self.assertEqual(len(list_repos(api, 'org', 'public')), 100)
        self.assertEqual(len(api.calls), 2)

    def test_responsible_is_repository_owner_even_with_conflicting_overlay(self):
        data = snapshot()
        data['repositories'][0].update(repository_owner='org', code_owner='@another-team')
        row = prepare(data, review(owner='wrong-user', applications=[{'owner':'also-wrong'}]))['rows'][0]
        self.assertEqual((row['owner'], row['owner_source'], row['code_owner']), ('org','github_repository_owner','@another-team'))

    def test_business_task_needs_pinned_code_evidence(self):
        with self.assertRaises(ValueError):
            prepare(snapshot(), review(business_task='Find animal intervals'))
        evidence = review()['reviews'][0]['review_evidence']
        row = prepare(snapshot(), review(business_task='Find animal intervals', business_evidence=evidence))['rows'][0]
        self.assertEqual(row['business_analysis'], 'analysed')

    def test_model_card_capability_is_not_project_business_analysis(self):
        info = {'lookup_status':'found','description':'Classifies images','source_url':'https://huggingface.co/a/b','checked_at':'2026-10-16'}
        row = prepare(snapshot(), review(model_info=info))['rows'][0]
        self.assertEqual(row['model_lookup'], 'found')
        self.assertEqual(row['business_analysis'], 'pending')

    def test_model_description_requires_source_and_date(self):
        with self.assertRaises(ValueError):
            prepare(snapshot(), review(model_info={'lookup_status':'found','description':'A model'}))

    def test_hf_alias_retains_requested_and_canonical_identifiers(self):
        from lookup_models import lookup
        metadata = json.dumps({'id':'publisher/canonical','sha':'a'*40,'cardData':{'license':'apache-2.0'}})
        with tempfile.TemporaryDirectory() as tmp, patch('lookup_models.get', side_effect=[(metadata,None),('# Card',None)]) as get:
            row = lookup('publisher/old-name', Path(tmp))
            self.assertEqual((row['requested_id'],row['id'],row['match_status']), ('publisher/old-name','publisher/canonical','alias'))
            self.assertTrue(get.call_args_list[1].args[0].endswith('/README.md'))
            self.assertEqual(row['source_revision'],'a'*40)

    def test_hf_access_error_is_not_nonexistence(self):
        from lookup_models import lookup
        with tempfile.TemporaryDirectory() as tmp, patch('lookup_models.get', return_value=(None,'http_401')):
            row = lookup('publisher/model', Path(tmp))
        self.assertEqual(row['lookup_status'],'http_401')

    def test_html_payload_cannot_escape_script(self):
        data = snapshot()
        data['repositories'][0]['usages'][0]['model'] = '</script><script>alert(1)</script>'
        with tempfile.TemporaryDirectory() as d:
            out = Path(d) / 'audit.html'
            render(prepare(data), out)
            self.assertNotIn('</script><script>alert(1)</script>', out.read_text())


if __name__ == '__main__':
    unittest.main()
