"""Diagnostic tooling and CLI behavior, using disposable snapshots and no credentials."""
from copy import deepcopy
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import patch

from audit_reachability import audit
import searchos_online as online


class OperationsTests(unittest.TestCase):
    def test_reachability_counts_workspaces_not_fields_and_skips_corrupt_snapshots(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            paths = [root / name for name in ('old', 'new', 'bad', 'missing')]
            for index, path in enumerate(paths[:2]):
                (path / 'calibration').mkdir(parents=True)
                (path / 'calibration/batch.json').write_text(json.dumps({
                    'stop_reason': 'error' if index == 0 else 'budget_exhausted',
                    'events': [{'timestamp': f'2026-10-1{index}T00:00:00Z'}],
                    'quality': {'warnings': [{'category': 'grounding'}, {'category': 'grounding'}],
                        'field_diagnostics': [{'reasons': {'quote_not_found': 2}},
                                              {'reasons': {'quote_not_found': 1}}]}}))
            (paths[2] / 'calibration').mkdir(parents=True)
            invalid = paths[2] / 'calibration/batch.json'
            invalid.write_text('{')
            before = {str(p): p.read_bytes() for p in root.rglob('batch.json')}
            result = audit([*paths, paths[1]], window=2)
            self.assertEqual(result['snapshots'], 2)
            self.assertEqual(result['workspaces'], [str(paths[1]), str(paths[0])])
            self.assertEqual(len(result['skipped']), 2)
            self.assertEqual(next(r for r in result['warning_categories']
                if r['branch'] == 'grounding')['observations'], 2)
            self.assertEqual(next(r for r in result['diagnostic_reasons']
                if r['branch'] == 'quote_not_found')['observations'], 2)
            self.assertEqual(before, {str(p): p.read_bytes() for p in root.rglob('batch.json')})
            for content in ('[]', 'null', '{"events": [null]}'):
                invalid.write_text(content)
                self.assertEqual(audit([paths[2]])['snapshots'], 0)
            latest = audit(paths[:2], window=1)
            self.assertEqual(latest['workspaces'], [str(paths[1])])

    def test_doctor_reports_missing_configuration_without_network_or_secrets(self):
        config = {**deepcopy(online.DEFAULTS), 'providers': ['serper', 'tavily'],
                  'citation_backend': 'openalex'}
        profile = SimpleNamespace(model='fixture-model', provider='fixture-protocol',
                                  api_key_env='FIXTURE_SECRET_KEY', api_key_fallback=None)
        with patch.dict(os.environ, {}, clear=True), \
             patch('searchos.config.models.resolve_profile', return_value=profile), \
             patch('searchos.config.models.get_model_for') as construct, \
             patch.object(online.importlib.util, 'find_spec', return_value=None), \
             patch.object(online.shutil, 'which', return_value=None):
            health = online.doctor(config)
        self.assertFalse(health['ready'])
        self.assertFalse(health['live_calls_tested'])
        construct.assert_not_called()
        self.assertEqual(len([p for p in health['problems'] if 'FIXTURE_SECRET_KEY' in p]), 3)
        for problem in ('missing SERPER_API_KEY', 'missing TAVILY_API_KEY', 'missing OPENALEX_API_KEY',
                        'pdftotext is not installed', 'contextgem is not installed'):
            self.assertIn(problem, health['problems'])

    def test_doctor_model_construction_failure_does_not_disclose_key(self):
        profile = SimpleNamespace(model='fixture-model', provider='fixture-protocol',
                                  api_key_env='FIXTURE_SECRET_KEY', api_key_fallback=None)
        with patch.dict(os.environ, {'FIXTURE_SECRET_KEY': 'private-fixture-value'}, clear=True), \
             patch('searchos.config.models.resolve_profile', return_value=profile), \
             patch('searchos.config.models.get_model_for', side_effect=ValueError('private-fixture-value')), \
             patch.object(online.importlib.util, 'find_spec', return_value=None):
            health = online.doctor(online.DEFAULTS)
        self.assertFalse(health['ready'])
        self.assertNotIn('private-fixture-value', json.dumps(health))
        self.assertEqual(len([p for p in health['problems'] if 'model construction failed' in p]), 3)

    def test_cli_invalid_config_exits_two_before_creating_workspace(self):
        script = Path(online.__file__)
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            config = root / 'bad.json'
            workspace = root / 'must-not-exist'
            for content in ('[]', 'null', '{', '{"cases": []}'):
                config.write_text(content)
                process = subprocess.run([sys.executable, str(script), 'run', '--config', str(config),
                    '--project-root', str(root), '--workspace', str(workspace)],
                    text=True, capture_output=True, timeout=30)
                self.assertEqual(process.returncode, 2, process.stderr)
                self.assertIn('error:', process.stderr)
                self.assertNotIn('Traceback', process.stderr)
                self.assertEqual(process.stdout, '')
                self.assertFalse(workspace.exists())
