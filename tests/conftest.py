"""Keep default offline tests independent of the operator's real credentials."""
import os

import pytest


@pytest.fixture(autouse=True)
def isolate_live_credentials(monkeypatch):
    # Individual fixtures can supply explicit fake keys after this cleanup.
    # This does not apply when running the opt-in live scripts directly.
    for name in list(os.environ):
        if name.endswith('_API_KEY') or name in {'OPENAI_API_TOKEN', 'ANTHROPIC_AUTH_TOKEN'}:
            monkeypatch.delenv(name, raising=False)

    # Synthetic tests choose a backend without real credentials or a local JSON.
    monkeypatch.setenv('SF_SEARCH_PROVIDER', 'serper')
