"""Bounded retrieval for the Quantum Scout online runner (no model calls)."""
import asyncio
import hashlib
import shutil
import subprocess
import tempfile
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import urldefrag, urlparse

import httpx


def public_url(url):
    parsed = urlparse(url)
    if parsed.scheme not in {'http', 'https'} or not parsed.hostname or parsed.username or parsed.password:
        raise ValueError('Expected an HTTP(S) source URL without credentials')
    if parsed.hostname in {'localhost', '0.0.0.0', '127.0.0.1', '::1'}:
        raise ValueError('Local URLs are not research sources')
    return url


async def download(url, limit=20_000_000, timeout=30):
    public_url(url)
    async with httpx.AsyncClient(timeout=timeout, follow_redirects=False) as client:
        for _ in range(6):
            async with client.stream('GET', url, headers={'User-Agent': 'quantum-scout/1.0'}) as response:
                if response.is_redirect:
                    url = public_url(str(response.url.join(response.headers['location'])))
                    continue
                response.raise_for_status()
                chunks, size = [], 0
                async for chunk in response.aiter_bytes():
                    size += len(chunk)
                    if size > limit:
                        raise ValueError('Source exceeds download byte limit')
                    chunks.append(chunk)
                return b''.join(chunks), response.headers.get('content-type', ''), str(response.url)
    raise ValueError('Too many redirects')


async def deepseek_fetch(url, limit=20_000_000, timeout=30):
    """Fetch a public URL as Markdown through DeepSeek Fetch."""
    import os
    key = os.environ.get('DEEPSEEK_API_KEY', '')
    if not key:
        raise RuntimeError('DEEPSEEK_API_KEY not set')
    public_url(url)
    # Search results may point at a section or figure. Fetch accepts the page
    # URL; fragments are client-side selectors and can make the API reject it.
    fetch_url, _fragment = urldefrag(url)
    async with httpx.AsyncClient(timeout=timeout) as client:
        response = await client.post(
            'https://api.deepseek.com/v1/tools/fetch',
            headers={'Authorization': f'Bearer {key}', 'Content-Type': 'application/json'},
            json={'url': fetch_url})
        response.raise_for_status()
        payload = response.json()
    content = payload.get('content', '')
    if not isinstance(content, str) or not content.strip() or len(content.encode()) > limit:
        raise ValueError('DeepSeek Fetch returned empty or oversized content')
    return content.encode(), 'text/markdown', fetch_url


def make_provider(name):
    from searchos.tools.simple_browser.search import build_search_provider
    return build_search_provider(name)


def source_segments(data, content_type):
    """PDF pages or HTML paragraphs; locations reference this saved extraction."""
    if data.startswith(b'%PDF-'):
        if not shutil.which('pdftotext'):
            raise RuntimeError('pdftotext is required to open PDF sources')
        with tempfile.TemporaryDirectory(prefix='scout-pdf-') as directory:
            pdf, text = Path(directory) / 'source.pdf', Path(directory) / 'source.txt'
            pdf.write_bytes(data)
            # Poppler's default follows reading order; -layout can interleave two columns.
            subprocess.run(['pdftotext', str(pdf), str(text)], check=True,
                           timeout=30, capture_output=True)
            pages = text.read_text(errors='replace').split('\f')
        return [{'location': f'page:{i+1}', 'text': page.strip()}
                for i, page in enumerate(pages) if page.strip()]
    if 'markdown' in content_type:
        # DeepSeek Fetch returns escaped Markdown (for example ``\\#``).
        # Keep paragraph boundaries as stable locations for grounding.
        paragraphs = [part.strip() for part in data.decode(errors='replace').split('\n\n')]
        return [{'location': f'paragraph:{i+1}', 'text': part}
                for i, part in enumerate(paragraphs) if part]
    if 'html' in content_type:
        from lxml import html
        doc = html.fromstring(data)
        for element in doc.xpath('//script|//style|//nav|//header|//footer|//form'):
            element.drop_tree()
        parts = [' '.join(e.text_content().split()) for e in doc.xpath('//p|//h1|//h2|//h3|//li|//tr|//pre')]
        return [{'location': f'paragraph:{i+1}', 'text': part} for i, part in enumerate(parts) if part]
    raise ValueError('Only actual PDF/HTML source documents are supported')


async def parse_source(data, content_type):
    """Keep IO deadlines responsive; cancelled PDF parsing kills its child process.

    HTML CPU work runs read-only in a worker; cancellation cannot commit source files.
    The worker may finish after cancellation, so max_seconds is a cooperative budget.
    """
    if not data.startswith(b'%PDF-'):
        return await asyncio.to_thread(source_segments, data, content_type)
    if not shutil.which('pdftotext'):
        raise RuntimeError('pdftotext is required to open PDF sources')
    with tempfile.TemporaryDirectory(prefix='scout-pdf-') as directory:
        pdf, text = Path(directory) / 'source.pdf', Path(directory) / 'source.txt'
        pdf.write_bytes(data)
        process = await asyncio.create_subprocess_exec('pdftotext', str(pdf), str(text),
                    stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE)
        try:
            stdout, stderr = await asyncio.wait_for(process.communicate(), 30)
        except BaseException:
            if process.returncode is None:
                process.kill()
            await process.communicate()
            raise
        if process.returncode:
            raise subprocess.CalledProcessError(process.returncode, 'pdftotext', stdout, stderr)
        pages = text.read_text(errors='replace').split('\f')
    return [{'location': f'page:{i+1}', 'text': page.strip()}
            for i, page in enumerate(pages) if page.strip()]


async def open_source(url, directory, run_id, provider=None):
    # Abstracts and search snippets are discovery leads, not opened paper bodies.
    if urlparse(url).hostname in {'arxiv.org', 'www.arxiv.org', 'export.arxiv.org'}:
        url = url.replace('/abs/', '/pdf/')
    if provider == 'deepseek':
        data, content_type, final_url = await deepseek_fetch(url)
    else:
        data, content_type, final_url = await download(url)
    segments = await parse_source(data, content_type)
    if not segments or sum(len(s['text']) for s in segments) < 100:
        raise ValueError('Empty or unreadable document body')
    raw_sha = hashlib.sha256(data).hexdigest()
    sid = 'source_' + hashlib.sha256(final_url.encode()).hexdigest()[:20]
    directory = Path(directory) / sid
    directory.mkdir(parents=True, exist_ok=True)
    (directory / (raw_sha + '.original')).write_bytes(data)
    text = '\n\n'.join(f"[{s['location']}]\n{s['text']}" for s in segments)
    (directory / (raw_sha + '.txt')).write_text(text)
    return {'source_id': sid, 'run_id': run_id, 'url': final_url, 'requested_url': url,
            'status': 'opened', 'document_version': 'sha256:' + raw_sha, 'raw_sha256': raw_sha,
            'opened_at': datetime.now(timezone.utc).isoformat(), 'text': text, 'segments': segments,
            'text_extraction': {'engine': 'pdftotext' if data.startswith(b'%PDF-') else 'lxml',
                                'mode': 'reading_order' if data.startswith(b'%PDF-') else 'paragraphs'}}
