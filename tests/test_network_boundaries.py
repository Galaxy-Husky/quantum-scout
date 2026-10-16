"""Real parser engines with generated documents; HTTP failures use explicit injection."""
import asyncio
import hashlib
import importlib.util
from pathlib import Path
import subprocess
import tempfile
import unittest
from unittest.mock import patch

import httpx

import searchos_network as network
from citation_backends import CitationBackend


def pdf_document(pages):
    """Small valid PDF fixture, generated locally without a PDF dependency."""
    objects = [b'<< /Type /Catalog /Pages 2 0 R >>', b'',
               b'<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica >>']
    kids = []
    for commands in pages:
        page_id = len(objects) + 1
        kids.append(f'{page_id} 0 R')
        objects.append(('<< /Type /Page /Parent 2 0 R /MediaBox [0 0 612 792] '
                        f'/Resources << /Font << /F1 3 0 R >> >> /Contents {page_id + 1} 0 R >>').encode())
        stream = commands.encode('ascii')
        objects.append(f'<< /Length {len(stream)} >>\nstream\n'.encode() + stream + b'\nendstream')
    objects[1] = f'<< /Type /Pages /Kids [{" ".join(kids)}] /Count {len(kids)} >>'.encode()
    data, offsets = b'%PDF-1.4\n', [0]
    for number, obj in enumerate(objects, 1):
        offsets.append(len(data))
        data += f'{number} 0 obj\n'.encode() + obj + b'\nendobj\n'
    start = len(data)
    data += f'xref\n0 {len(offsets)}\n0000000000 65535 f \n'.encode()
    data += b''.join(f'{offset:010d} 00000 n \n'.encode() for offset in offsets[1:])
    return data + f'trailer\n<< /Size {len(offsets)} /Root 1 0 R >>\nstartxref\n{start}\n%%EOF\n'.encode()


class ParserTests(unittest.TestCase):
    def test_real_pdf_pages_columns_and_grounding_offsets(self):
        body = pdf_document(['', 'BT /F1 12 Tf 40 700 Td (Left evidence.) Tj ET\n'
                            'BT /F1 12 Tf 330 700 Td (Right evidence.) Tj ET\n'
                            '40 500 200 50 re S'])
        segments = network.source_segments(body, 'application/pdf')
        self.assertEqual([s['location'] for s in segments], ['page:2'])
        self.assertIn('Left evidence.', segments[0]['text'])
        self.assertIn('Right evidence.', segments[0]['text'])
        path = Path(__file__).resolve().parents[1] / 'assets/quantum_grounding/executor.py'
        spec = importlib.util.spec_from_file_location('parser_gate_fixture', path)
        gate = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(gate)
        text = '[page:2]\n' + segments[0]['text']
        result = gate.validate({'run_id': 'parser-fixture', 'source': {
            'source_id': 'pdf-fixture', 'run_id': 'parser-fixture', 'status': 'opened',
            'document_version': 'generated-pdf', 'text': text}, 'evidence': [{
            'case_id': 'TEST-0001', 'source_id': 'pdf-fixture', 'field': 'constraints',
            'location': 'page:2', 'quote': 'Left evidence.'}]})
        self.assertFalse(result['grounding_failures'])
        receipt = result['validated_candidates'][0]['grounding']
        self.assertEqual(text[slice(*receipt['span'])], 'Left evidence.')
        self.assertEqual(receipt['source_sha256'], hashlib.sha256(text.encode()).hexdigest())

    def test_html_unicode_noise_removal_and_location_identity(self):
        html = ('<html><meta charset="utf-8"><nav>Not body evidence</nav>'
                '<script>Not source text</script><p>量子 café &amp; clocks</p>'
                '<p></p><p>Second body paragraph.</p></html>').encode()
        segments = network.source_segments(html, 'text/html; charset=utf-8')
        self.assertEqual([s['location'] for s in segments], ['paragraph:1', 'paragraph:3'])
        self.assertEqual(segments[0]['text'], '量子 café & clocks')
        self.assertNotIn('Not body evidence', str(segments))
        self.assertNotIn('Not source text', str(segments))

    def test_truncated_pdf_and_unsupported_body_are_rejected(self):
        with self.assertRaises(subprocess.CalledProcessError):
            network.source_segments(b'%PDF-1.4\n1 0 obj\n<<', 'application/pdf')
        with self.assertRaises(ValueError):
            network.source_segments(b'plain text is not an opened paper', 'text/plain')

    def test_empty_html_is_not_saved_as_successful_body(self):
        async def empty(*args):
            return b'<html><p> </p></html>', 'text/html', 'https://fixture.example/empty'
        with tempfile.TemporaryDirectory() as directory, patch.object(network, 'download', empty):
            with self.assertRaisesRegex(ValueError, 'Empty or unreadable'):
                asyncio.run(network.open_source('https://fixture.example/empty', directory, 'test'))
            self.assertEqual(list(Path(directory).iterdir()), [])


class DownloadTests(unittest.TestCase):
    def test_partial_stream_failure_never_persists_success(self):
        class BrokenStream(httpx.AsyncByteStream):
            async def __aiter__(self):
                yield b'<html><p>Partial generated evidence'
                raise httpx.ReadError('Synthetic interrupted body')
        original = httpx.AsyncClient
        transport = httpx.MockTransport(lambda request: httpx.Response(200,
            headers={'content-type': 'text/html'}, stream=BrokenStream()))
        with tempfile.TemporaryDirectory() as folder, patch.object(network.httpx, 'AsyncClient',
                side_effect=lambda **kw: original(transport=transport, **kw)):
            with self.assertRaises(httpx.ReadError):
                asyncio.run(network.open_source('https://fixture.example/partial', folder, 'offline'))
            self.assertEqual(list(Path(folder).iterdir()), [])

    def fetch(self, handler, *, limit=100):
        client = httpx.AsyncClient
        with patch.object(network.httpx, 'AsyncClient',
                          side_effect=lambda **kw: client(transport=httpx.MockTransport(handler), **kw)):
            return asyncio.run(network.download('https://fixture.example/start', limit=limit))

    def test_redirect_and_body_bound_preserve_final_identity(self):
        seen = []
        def handler(request):
            seen.append(str(request.url))
            return (httpx.Response(302, headers={'location': '/final'}) if request.url.path == '/start'
                    else httpx.Response(200, content=b'body', headers={'content-type': 'text/html'}))
        data, content_type, final = self.fetch(handler)
        self.assertEqual(data, b'body')
        self.assertEqual(final, 'https://fixture.example/final')
        self.assertEqual(len(seen), 2)
        with self.assertRaisesRegex(ValueError, 'byte limit'):
            self.fetch(lambda request: httpx.Response(200, content=b'x' * 101))

    def test_redirect_loop_and_local_redirect_fail_closed(self):
        seen = []
        def loop(request):
            seen.append(request)
            return httpx.Response(302, headers={'location': '/start'})
        with self.assertRaisesRegex(ValueError, 'Too many redirects'):
            self.fetch(loop)
        self.assertEqual(len(seen), 6)
        with self.assertRaisesRegex(ValueError, 'Local URLs'):
            self.fetch(lambda request: httpx.Response(302, headers={'location': 'http://127.0.0.1/private'}))

    def test_http_failures_are_not_returned_as_empty_success(self):
        for status in (403, 404, 429, 503):
            with self.subTest(status=status), self.assertRaises(httpx.HTTPStatusError):
                self.fetch(lambda request: httpx.Response(status, headers={'retry-after': '3'}))
        for error in (httpx.ConnectError('fixture'), httpx.ReadTimeout('fixture'), httpx.ReadError('fixture')):
            def fail(request):
                raise error
            with self.subTest(error=type(error).__name__), self.assertRaises(type(error)):
                self.fetch(fail)

    def test_invalid_identity_json_is_unknown_and_audited(self):
        for data in ([], None, {'title': 'Missing canonical ID'}):
            backend = CitationBackend('semantic_scholar', httpx.MockTransport(
                lambda request: httpx.Response(200, json=data)))
            with self.subTest(data=data):
                result = asyncio.run(backend.verify({'arxiv': '1309.3923'}, 'Expected title'))
                self.assertEqual(result['state'], 'unknown')
                self.assertEqual(backend.requests[0]['status'], 'failed')
