"""Shared SearchOS config contracts. Fake keys, no service requests or file migration."""
from copy import deepcopy
import hashlib
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

from searchos.config import web_overlay
from searchos.config.models import resolve_profile
from searchos.config.settings import settings, reload_settings_in_place
import searchos_online as online
from searchos_configuration import configure_runtime


class SharedConfigurationTests(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.addCleanup(self.directory.cleanup)
        self.root = Path(self.directory.name)
        before = settings.model_copy(deep=True)
        old_store = web_overlay.store.model_copy(deep=True)
        old_metadata = online._RUNTIME_CONFIGURATION
        def restore():
            reload_settings_in_place(before)
            for name in web_overlay.WebSettings.model_fields:
                setattr(web_overlay.store, name, getattr(old_store, name))
            online._RUNTIME_CONFIGURATION = old_metadata
        self.addCleanup(restore)
        # Intentionally overrides the outer fixture: prove JSON/env resolution from an empty environment.
        self.environment = patch.dict(os.environ, {}, clear=True)
        self.environment.start()
        self.addCleanup(self.environment.stop)
        default = patch.object(web_overlay, 'overlay_path', return_value=self.root / 'default-missing.json')
        default.start()
        self.addCleanup(default.stop)
        self.env = self.root / '.env'
        self.env.write_text('DASHSCOPE_API_KEY=offline-fixture\nSERPER_API_KEY=offline-search-fixture\n')

    def overlay(self, path, model='configured-fixture'):
        data = {'models': {'provider_connections': {'dashscope': {
            'protocol': 'openai_compatible', 'api_base': 'https://example.invalid/v1',
            'api_key_envs': ['DASHSCOPE_API_KEY'], 'thinking_style': 'enable_thinking'}},
            'custom_profiles': {'shared-main': {'model': model, 'provider_ref': 'dashscope', 'max_tokens': 12000}},
            'roles': {role: 'shared-main' for role in ('orchestrator', 'extraction', 'judge')},
            'search_provider': 'serper'}, 'advanced': {'llm_max_retries': 7}}
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(data))
        return data

    def test_auto_finds_setup_config_in_selected_env_projects_venv(self):
        version = f'python{sys.version_info.major}.{sys.version_info.minor}'
        path = self.root / '.venv/lib' / version / 'site-packages/web_settings.json'
        self.overlay(path)
        original = {p: p.read_bytes() for p in (path, self.env)}
        online.configure(self.env)
        for role in ('orchestrator', 'extraction', 'judge'):
            profile = resolve_profile(role)
            self.assertEqual(profile.model, 'configured-fixture')
            self.assertEqual(profile.api_key_env, 'DASHSCOPE_API_KEY')
            self.assertEqual(profile.api_base, 'https://example.invalid/v1')
            self.assertEqual(profile.max_tokens, 4096)
        self.assertEqual(settings.llm_max_retries, 0)
        self.assertEqual(web_overlay.store.models.search_provider, 'serper')
        self.assertEqual(online._RUNTIME_CONFIGURATION['selection'], 'env_project')
        self.assertEqual(online._RUNTIME_CONFIGURATION['settings_file'], str(path))
        self.assertEqual(online._RUNTIME_CONFIGURATION['settings_sha256'], hashlib.sha256(path.read_bytes()).hexdigest())
        self.assertNotIn('offline-fixture', json.dumps(online._RUNTIME_CONFIGURATION))
        self.assertEqual(original, {p: p.read_bytes() for p in original})

    def test_root_json_and_cli_argument_override_environment_path(self):
        root_settings = self.root / 'web_settings.json'
        self.overlay(root_settings, 'from-root')
        online.configure(self.env)
        self.assertEqual(resolve_profile('judge').model, 'from-root')
        explicit = self.root / 'selected.json'
        self.overlay(explicit, 'from-argument')
        os.environ['SF_WEB_SETTINGS_PATH'] = str(root_settings)
        online.configure(self.env, explicit)
        self.assertEqual(resolve_profile('judge').model, 'from-argument')
        self.assertEqual(online._RUNTIME_CONFIGURATION['selection'], 'argument')
        self.assertEqual(os.environ['SF_WEB_SETTINGS_PATH'], str(root_settings))
        online.configure(self.env)
        self.assertEqual(resolve_profile('judge').model, 'from-root')
        self.assertEqual(online._RUNTIME_CONFIGURATION['selection'], 'environment')

    def test_missing_default_resets_previous_overlay_and_preserves_env_base(self):
        path = self.root / 'selected.json'
        self.overlay(path)
        online.configure(self.env, path)
        os.environ.update(SF_PROVIDER='dashscope', SF_MODEL='env-main', SF_FAST_MODEL='env-fast')
        online.configure(self.env)
        self.assertEqual(resolve_profile('judge').model, 'env-main')
        self.assertNotIn('shared-main', settings.profiles)
        self.assertEqual(web_overlay.store.models.roles, {})
        self.assertFalse(online._RUNTIME_CONFIGURATION['settings_loaded'])

    def test_ambiguous_discovery_and_missing_explicit_paths_fail_closed(self):
        version = f'python{sys.version_info.major}.{sys.version_info.minor}'
        first = self.root / 'web_settings.json'
        second = self.root / '.venv/lib' / version / 'site-packages/web_settings.json'
        self.overlay(first)
        self.overlay(second)
        before = {p: p.read_bytes() for p in (first, second)}
        with self.assertRaisesRegex(ValueError, 'Multiple SearchOS'):
            online.configure(self.env)
        with self.assertRaisesRegex(ValueError, 'missing or not a file'):
            online.configure(self.env, self.root / 'does-not-exist.json')
        self.assertEqual(before, {p: p.read_bytes() for p in before})
        online.configure(self.env, first)
        self.assertEqual(resolve_profile('judge').model, 'configured-fixture')

    def test_invalid_json_and_secret_in_variable_name_are_rejected_without_disclosure(self):
        path = self.root / 'bad.json'
        before = settings.model_dump()
        for content in ('{', '[]', 'null', '{"unknown": "do-not-print-this"}'):
            with self.subTest(content=content):
                path.write_text(content)
                with self.assertRaises(ValueError) as caught:
                    online.configure(self.env, path)
                self.assertNotIn('do-not-print-this', str(caught.exception))
                self.assertEqual(settings.model_dump(), before)
        data = self.overlay(path)
        data['models']['provider_connections']['dashscope']['api_key_envs'] = ['sk-do-not-print-this']
        path.write_text(json.dumps(data))
        with self.assertRaises(ValueError) as caught:
            online.configure(self.env, path)
        self.assertNotIn('sk-do-not-print-this', str(caught.exception))
        self.assertEqual(settings.model_dump(), before)

    def test_invalid_core_binding_never_constructs_a_model(self):
        path = self.root / 'bad-binding.json'
        data = self.overlay(path)
        data['models']['roles']['judge'] = 'missing-model-card'
        path.write_text(json.dumps(data))
        with patch('searchos.config.models.get_model_for') as construct:
            with self.assertRaisesRegex(ValueError, 'Invalid SearchOS model binding'):
                online.configure(self.env, path)
        construct.assert_not_called()

    def test_cli_missing_settings_returns_two_before_workspace_creation(self):
        config = self.root / 'online.json'
        config.write_text(json.dumps({'cases': {'TEST-0001': {'description': 'Offline fixture'}}}))
        workspace = self.root / 'must-not-exist'
        process = subprocess.run([sys.executable, online.__file__, 'run', '--config', str(config),
            '--project-root', str(self.root), '--workspace', str(workspace),
            '--env-file', str(self.env), '--settings-file', str(self.root / 'missing.json')],
            capture_output=True, text=True, timeout=20)
        self.assertEqual(process.returncode, 2)
        self.assertIn('error:', process.stderr)
        self.assertNotIn('Traceback', process.stderr)
        self.assertFalse(workspace.exists())

    def test_shared_config_is_reported_by_doctor_without_network_calls(self):
        path = self.root / 'selected.json'
        self.overlay(path)
        online.configure(self.env, path)
        with patch('searchos.config.models.get_model_for') as construct, \
             patch('contextgem_extractor.make_llm') as context_llm, \
             patch.object(online.importlib.util, 'find_spec', return_value=object()), \
             patch.object(online.shutil, 'which', return_value='/fixture/pdftotext'):
            health = online.doctor(online.DEFAULTS)
        self.assertTrue(health['ready'], health)
        self.assertFalse(health['live_calls_tested'])
        self.assertEqual(construct.call_count, 3)
        context_llm.assert_called_once()
        self.assertEqual(health['roles']['judge']['model'], 'configured-fixture')
        self.assertEqual(health['configuration']['settings_file'], str(path))

    def test_task_inherits_shared_search_and_rejects_competing_choices(self):
        path = self.root / 'selected.json'
        self.overlay(path)
        os.environ['SF_SEARCH_PROVIDER'] = 'tavily'
        online.configure(self.env, path)
        task = self.root / 'task.json'
        data = {'cases': {'TEST-0001': {'description': 'Synthetic task', 'queries': ['quantum fixture']}}}
        task.write_text(json.dumps(data))
        original = task.read_bytes()
        config = online.read_config(task)
        self.assertEqual(config['providers'], ['serper'])
        self.assertEqual(config['cases']['TEST-0001']['queries'], {'serper': ['quantum fixture']})
        self.assertEqual(task.read_bytes(), original)
        for providers in (['arxiv'], ['tavily'], ['serper', 'tavily']):
            with self.subTest(providers=providers):
                task.write_text(json.dumps({**data, 'providers': providers}))
                with self.assertRaisesRegex(ValueError, 'must match'):
                    online.read_config(task)

    def test_search_follows_searchos_key_inference_and_explicit_env(self):
        from searchos_configuration import search_provider_name
        online.configure(self.env)
        self.assertEqual(search_provider_name(), 'serper')
        os.environ['SF_SEARCH_PROVIDER'] = 'tavily'
        self.assertEqual(search_provider_name(), 'tavily')
        os.environ['SF_SEARCH_PROVIDER'] = 'arxiv'
        with self.assertRaises(ValueError):
            search_provider_name()

    def test_cli_rejects_old_arxiv_and_pagination_before_workspace_creation(self):
        settings_path = self.root / 'settings.json'
        self.overlay(settings_path)
        for changes in ({'providers': ['arxiv']}, {'pages_per_query': 2},
                        {'cases': {'TEST-0001': {'description': 'Fixture', 'queries': {'arxiv': ['id:1']}}}}):
            with self.subTest(changes=changes):
                config = self.root / 'task.json'
                config.write_text(json.dumps({'cases': {'TEST-0001': {'description': 'Fixture'}}, **changes}))
                workspace = self.root / 'must-not-exist'
                result = subprocess.run([sys.executable, online.__file__, 'run', '--config', str(config),
                    '--project-root', str(self.root), '--workspace', str(workspace),
                    '--env-file', str(self.env), '--settings-file', str(settings_path)],
                    capture_output=True, text=True, timeout=20)
                self.assertEqual(result.returncode, 2, result.stderr)
                self.assertIn('error:', result.stderr)
                self.assertNotIn('Traceback', result.stderr)
                self.assertFalse(workspace.exists())

    def test_provider_factory_delegates_to_searchos_and_arxiv_is_unavailable(self):
        from searchos_network import make_provider
        expected = object()
        with patch('searchos.tools.simple_browser.search.build_search_provider', return_value=expected) as factory:
            self.assertIs(make_provider('serper'), expected)
        factory.assert_called_once_with('serper')
        with self.assertRaises(ValueError):
            make_provider('arxiv')

    def test_arxiv_paper_body_remains_readable_without_search_api(self):
        import asyncio
        import searchos_network as network
        seen = []
        async def body(url):
            seen.append(url)
            return b'<html><p>' + b'Generated paper evidence. ' * 8 + b'</p></html>', 'text/html', url
        with patch.object(network, 'download', body):
            result = asyncio.run(network.open_source('https://arxiv.org/abs/1309.3923v1', self.root, 'fixture'))
        self.assertEqual(seen, ['https://arxiv.org/pdf/1309.3923v1'])
        self.assertEqual(result['status'], 'opened')
