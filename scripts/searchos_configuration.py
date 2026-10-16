"""Read SearchOS configuration through its own schema/runtime; never migrate or write it."""
import hashlib
import os
from pathlib import Path
import re
import sys


def search_provider_name():
    """Use SearchOS's shared selection and key inference, without another default."""
    from searchos.config.web_overlay import store
    from searchos.tools.simple_browser.search import resolve_search_provider_name
    return resolve_search_provider_name(store.models.search_provider or '')


def settings_path(env_file=None, explicit=None):
    from searchos.config.web_overlay import overlay_path
    if explicit is not None:
        return Path(explicit).expanduser().resolve(), 'argument', True
    if os.environ.get('SF_WEB_SETTINGS_PATH'):
        return Path(os.environ['SF_WEB_SETTINGS_PATH']).expanduser().resolve(), 'environment', True
    if env_file is not None:
        project = Path(env_file).resolve().parent
        version = f'python{sys.version_info.major}.{sys.version_info.minor}'
        candidates = {p.resolve() for p in (project / 'web_settings.json',
            project / '.venv/lib' / version / 'site-packages/web_settings.json') if p.is_file()}
        if len(candidates) > 1:
            raise ValueError('Multiple SearchOS settings files beside the env project; select --settings-file')
        if candidates:
            return candidates.pop(), 'env_project', True
    return overlay_path().expanduser().resolve(), 'searchos_default', False


def configure_runtime(env_file=None, explicit=None):
    from searchos.config import web_overlay
    from searchos.config.settings import reload_settings_in_place, settings
    path, selection, required = settings_path(env_file, explicit)
    content = path.read_bytes() if path.is_file() else None
    if content is None and (required or path.exists()):
        raise ValueError('SearchOS settings file is missing or not a file: ' + str(path))
    try:
        overlay = (web_overlay.WebSettings.model_validate_json(content) if content is not None
                   else web_overlay.WebSettings())
    except ValueError:
        # Validation errors can include raw inputs; keep secret values out of CLI errors.
        raise ValueError('Invalid SearchOS settings JSON: ' + str(path)) from None
    references = [v for connection in overlay.models.provider_connections.values() for v in connection.api_key_envs]
    references += [p.api_key_env for p in overlay.models.custom_profiles.values()]
    references += [p.api_key_env for p in overlay.models.profile_overrides.values()]
    if any(v and not re.fullmatch(r'[A-Za-z_][A-Za-z_0-9]*', v) for v in references):
        raise ValueError('SearchOS api_key_env/api_key_envs must contain environment variable names')
    # Share SearchOS's model/connection/role resolution; its CLI's load_and_apply
    # also seeds/migrates files. The audit entry point only reads and applies.
    reload_settings_in_place()
    for name in web_overlay.WebSettings.model_fields:
        setattr(web_overlay.store, name, getattr(overlay, name))
    web_overlay.apply_to_runtime()
    for role in ('orchestrator', 'extraction', 'judge'):
        chosen = overlay.models.roles.get(role)
        if chosen is not None and (chosen not in settings.profiles or settings.roles.get(role) != chosen):
            raise ValueError('Invalid SearchOS model binding for role: ' + role)
    return {'settings_file': str(path), 'settings_loaded': content is not None,
            'selection': selection,
            'settings_sha256': hashlib.sha256(content).hexdigest() if content is not None else None}
