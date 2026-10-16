"""Verify generator entrypoints write into the project layout by default."""
from contextlib import redirect_stdout
import io
import json
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'scripts'))
from searchos_project import ProjectLayout, initialize
try:
    import searchos_adapter as adapter
    import searchos_online as online
    import schema_generator
    import check_searchos
    AVAILABLE = True
except ImportError:
    AVAILABLE = False


@unittest.skipUnless(AVAILABLE, 'Use the SearchOS environment')
class OutputTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.layout = ProjectLayout(self.temp.name)
        initialize(self.layout, 'TEST-0001', 'Synthetic configuration fixture', ['fixture'])

    def invoke(self, main, *args):
        with patch.object(sys, 'argv', ['test-command', *args]), redirect_stdout(io.StringIO()):
            return main()

    def assert_clean_root(self):
        self.assertEqual({p.name for p in self.layout.root.iterdir()}, {'artifacts'})

    def test_init_creates_templates_in_config_and_preserves_user_changes(self):
        self.assertTrue(self.layout.env_template.is_file())
        original = self.layout.config.read_bytes()
        initialize(self.layout, 'TEST-0002', 'Different case', ['different'])
        self.assertEqual(self.layout.config.read_bytes(), original)
        self.assert_clean_root()

    def test_schema_generator_defaults_to_config_directory(self):
        self.invoke(schema_generator.main, '--project-root', str(self.layout.root), '--case-id', 'TEST-0001')
        self.assertEqual(json.loads(self.layout.schema.read_text())['tables'][0]['entities'], ['TEST-0001'])
        self.assert_clean_root()

    def test_adapter_prepare_defaults_to_workspaces(self):
        self.invoke(adapter.main, 'prepare', '--project-root', str(self.layout.root), '--case-id', 'TEST-0001')
        workspaces = list(self.layout.workspaces.iterdir())
        self.assertEqual(len(workspaces), 1)
        self.assertEqual(adapter.load(workspaces[0])['case_ids'], ['TEST-0001'])
        self.assert_clean_root()

    def test_offline_check_writes_validation_directly(self):
        async def check():
            return {'fixture': True, 'isolated_executor': 'passed'}
        with patch.object(check_searchos, 'check', check):
            self.invoke(check_searchos.main, '--project-root', str(self.layout.root))
        self.assertTrue(json.loads(self.layout.offline.read_text())['fixture'])
        self.assert_clean_root()

    def test_doctor_uses_default_config_and_writes_only_diagnostic(self):
        with patch.object(online, 'configure'), patch.object(online, 'doctor', return_value={'ready': False}):
            result = self.invoke(online.main, 'doctor', '--project-root', str(self.layout.root))
        self.assertEqual(result, 2)
        self.assertFalse(self.layout.workspaces.exists())
        self.assertFalse(json.loads(self.layout.doctor.read_text())['ready'])
        self.assert_clean_root()

    def test_run_creates_workspace_and_online_validation_without_root_artifacts(self):
        async def run(runner, **kwargs):
            meta = adapter.load(runner.path)
            meta['online'] = {'events': [], 'searches': {}, 'sources': {}, 'invocations': [{'model_calls': 0}]}
            state = adapter.persist(runner.path, meta)
            return {'stop_reason': 'budget_exhausted', 'coverage': adapter.summary(state)}
        with patch.object(online, 'configure'), patch.object(online, 'doctor', return_value={'ready': True}), \
                patch.object(online.OnlineRunner, 'run', run):
            self.invoke(online.main, 'run', '--project-root', str(self.layout.root))
        report = json.loads(self.layout.online.read_text())
        self.assertFalse(report['live_model_extraction_tested'])
        self.assertEqual(report['model_calls_total'], 0)
        self.assertTrue((self.layout.root / report['workspace']).is_dir())
        self.assert_clean_root()


@unittest.skipUnless(AVAILABLE, 'Use the SearchOS environment')
class WorkspacePathTests(unittest.TestCase):
    def test_current_layout_only_and_invalid_state_is_not_rewritten(self):
        from searchos_project import WorkspaceLayout
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / 'fixture'
            adapter.prepare(path, case_ids=['TEST-0001'])
            layout = WorkspaceLayout(path)
            self.assertEqual(adapter.load(path)['version'], 2)
            self.assertTrue(layout.schema.is_file())
            self.assertTrue((layout.socm / 'search_state.json').is_file())
            before = layout.adapter.read_bytes()
            layout.adapter.rename(path / 'quantum_adapter.json')
            with self.assertRaisesRegex(ValueError, 'state/quantum_adapter.json'):
                adapter.load(path)
            self.assertEqual((path / 'quantum_adapter.json').read_bytes(), before)
            for invalid in ('{', '[]', '{"version": 1}', '{"version": 2}'):
                layout.adapter.write_text(invalid)
                with self.subTest(invalid=invalid), self.assertRaises(ValueError):
                    adapter.load(path)
                self.assertEqual(layout.adapter.read_text(), invalid)

    def test_old_project_config_is_not_a_fallback(self):
        with tempfile.TemporaryDirectory() as directory:
            old = Path(directory) / 'searchos/config/online-pilot.json'
            old.parent.mkdir(parents=True)
            old.write_text('{}')
            with patch.object(sys, 'argv', ['test', 'doctor', '--project-root', directory]), patch.object(online, 'configure'):
                with self.assertRaises(SystemExit) as error:
                    online.main()
                self.assertEqual(error.exception.code, 2)
            self.assertEqual(old.read_text(), '{}')
            self.assertFalse((Path(directory) / 'artifacts/quantum-scout').exists())


if __name__ == '__main__':
    unittest.main()
