"""Offline configuration ownership and preparation checks; no provider requests."""
import asyncio
import hashlib
import json
from pathlib import Path
from types import SimpleNamespace

import pytest

import searchos_configuration as configuration
import searchos_project as project


def test_settings_precedence_ignores_files_beside_credentials(tmp_path, monkeypatch):
    from searchos.config import web_overlay
    default = tmp_path / 'environment' / 'web_settings.json'
    monkeypatch.setattr(web_overlay, 'overlay_path', lambda: default)
    monkeypatch.delenv('SF_WEB_SETTINGS_PATH', raising=False)
    (tmp_path / 'web_settings.json').write_text('invalid legacy file')
    env = tmp_path / '.env'
    assert configuration.settings_path(env) == (default, 'searchos_default', False)
    override = tmp_path / 'shared.json'
    monkeypatch.setenv('SF_WEB_SETTINGS_PATH', str(override))
    assert configuration.settings_path(env) == (override, 'environment', True)
    explicit = tmp_path / 'explicit.json'
    assert configuration.settings_path(env, explicit) == (explicit, 'argument', True)


@pytest.mark.parametrize('content', [None, '{broken', '{"models":{"custom_profiles":{"x":{"api_key_env":"actual secret"}}}}'])
def test_explicit_settings_fail_closed_without_exposing_values(tmp_path, content):
    target = tmp_path / 'settings.json'
    if content is not None:
        target.write_text(content)
    with pytest.raises(ValueError) as error:
        configuration.configure_runtime(explicit=target)
    assert 'actual secret' not in str(error.value)


def test_settings_are_read_only_and_receipt_hashes_selected_file(tmp_path, monkeypatch):
    from searchos.config import web_overlay
    import importlib
    settings_module = importlib.import_module('searchos.config.settings')
    monkeypatch.setattr(web_overlay, 'store', web_overlay.WebSettings())
    monkeypatch.setattr(web_overlay, 'apply_to_runtime', lambda: None)
    monkeypatch.setattr(settings_module, 'reload_settings_in_place', lambda: None)
    target = tmp_path / 'settings.json'
    content = b'{"models":{"search_provider":"deepseek"}}\n'
    target.write_bytes(content)
    receipt = configuration.configure_runtime(explicit=target)
    assert receipt['settings_sha256'] == hashlib.sha256(content).hexdigest()
    assert web_overlay.store.models.search_provider == 'deepseek'
    assert target.read_bytes() == content


def test_init_keeps_inputs_out_of_artifacts_and_preserves_user_edits(tmp_path):
    layout = project.ProjectLayout(tmp_path)
    project.initialize(layout, 'TEST-0001', 'Explicit test system', ['query'])
    assert layout.config.relative_to(tmp_path) == Path('searchos/config/online-pilot.json')
    assert not layout.base.exists()
    supplied = json.loads(layout.config.read_text())
    assert supplied['cases']['TEST-0001']['queries'] == ['query']
    layout.config.write_text('{"user":"edited"}')
    layout.env_template.write_text('user template')
    assert project.initialize(layout, 'TEST-0002', 'Other system', [])['created'] == []
    assert layout.config.read_text() == '{"user":"edited"}'
    assert layout.env_template.read_text() == 'user template'


def test_doctor_checks_deepseek_key_without_network(monkeypatch):
    from searchos_online import DEFAULTS, doctor
    from searchos.config import models
    profile = SimpleNamespace(model='offline', provider='openai_compatible',
                              api_key_env='OFFLINE_API_KEY', api_key_fallback='')
    monkeypatch.setenv('OFFLINE_API_KEY', 'test-only')
    monkeypatch.setattr(models, 'resolve_profile', lambda role: profile)
    monkeypatch.setattr(models, 'get_model_for', lambda role: object())
    monkeypatch.setattr('contextgem_extractor.make_llm', lambda runner: object())
    monkeypatch.setattr('searchos_online.shutil.which', lambda name: None)
    config = {**DEFAULTS, 'providers': ['deepseek'], 'cases': {}}
    assert 'missing DEEPSEEK_API_KEY' in doctor(config)['problems']
    monkeypatch.setenv('DEEPSEEK_API_KEY', 'test-only')
    assert doctor(config)['ready']  # Fetch provides Markdown; no local PDF parser is used.


def test_runtime_uses_installed_sources_and_excludes_design_references(tmp_path, monkeypatch):
    sources = {name: tmp_path / name for name in ('searchos', 'contextgem')}
    monkeypatch.setattr(project, 'installed_source', sources.get)
    monkeypatch.setattr(project.subprocess, 'check_output', lambda *a, **k: 'offline-revision\n')
    monkeypatch.setattr(project.subprocess, 'run',
                        lambda *a, **k: SimpleNamespace(returncode=0, stdout='offline-revision\n'))
    layout = project.ProjectLayout(tmp_path)
    project.snapshot_runtime(layout)
    manifest = json.loads(layout.manifest.read_text())
    assert manifest['repository'] == str(sources['searchos'])
    assert set(manifest['integrations']) == set(sources)
    assert manifest['source_revision_role'] == 'observed_checkout_not_installed_build_proof'
    assert manifest['lock_sha256'] == hashlib.sha256(layout.lock.read_bytes()).hexdigest()


def test_markdown_fetch_records_actual_extraction_engine(tmp_path, monkeypatch):
    import searchos_network as network
    content = ('Source paragraph with enough body text for the extraction boundary. ' * 3).encode()
    async def fetch(url):
        return content, 'text/markdown', url
    monkeypatch.setattr(network, 'deepseek_fetch', fetch)
    source = asyncio.run(network.open_source('https://example.org/paper', tmp_path,
                                             'offline', provider='deepseek'))
    assert source['text_extraction'] == {'engine': 'markdown', 'mode': 'paragraphs'}
    assert source['segments'][0]['text'] == content.decode().strip()
    assert next(tmp_path.rglob('*.original')).read_bytes() == content
