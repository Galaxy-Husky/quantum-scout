#!/usr/bin/env python3
"""Download one publicly accessible source and emit a provenance manifest."""
import argparse, hashlib, json, re, sys, time
from datetime import datetime, timezone
from pathlib import Path
from urllib.request import Request, urlopen
from urllib.error import HTTPError, URLError
from searchos_project import ProjectLayout

def main():
    p=argparse.ArgumentParser()
    p.add_argument('--workspace',type=Path, help='Explicit run workspace; otherwise use the project cache')
    p.add_argument('--project-root', type=Path, default=Path.cwd())
    p.add_argument('--source-id',required=True)
    p.add_argument('--url',required=True)
    p.add_argument('--version',default=None)
    p.add_argument('--user-agent',default='quantum-scout-research/1.0')
    p.add_argument('--retries',type=int,default=1,help='additional attempts after the first request')
    p.add_argument('--max-bytes',type=int,default=100*1024*1024,help='maximum response size (default: 100 MiB)')
    a=p.parse_args()
    if a.max_bytes <= 0 or a.retries not in (0, 1):
        p.error('--max-bytes must be positive and --retries must be 0 or 1')
    safe=re.sub(r'[^A-Za-z0-9._-]+','_',a.source_id).strip('_')[:160] or 'source'
    workspace = a.workspace or ProjectLayout(a.project_root).cache
    directory=workspace/'sources'/safe; directory.mkdir(parents=True,exist_ok=True)
    now=datetime.now(timezone.utc).isoformat()
    meta={'source_id':a.source_id,'canonical_url':a.url,'document_version':a.version,'retrieved_at':now,'status':'download_failed','local_path':None,'sha256':None,'error':None}
    attempts=max(1,a.retries+1)
    for attempt in range(attempts):
        try:
            req=Request(a.url,headers={'User-Agent':a.user_agent})
            with urlopen(req,timeout=30) as response:
                chunks=[]
                total=0
                while True:
                    remaining = a.max_bytes - total
                    chunk=response.read(min(1024*1024, remaining + 1))
                    if not chunk:
                        break
                    total += len(chunk)
                    if total > a.max_bytes:
                        raise ValueError(f'response exceeds max-bytes={a.max_bytes}')
                    chunks.append(chunk)
                data=b''.join(chunks)
                ctype=response.headers.get_content_type()
                ext='.pdf' if ctype=='application/pdf' or a.url.lower().split('?')[0].endswith('.pdf') else '.html'
                path=directory/('original'+ext); path.write_bytes(data)
                meta.update(content_type=ctype,status='downloaded',local_path=str(path.relative_to(workspace)),sha256=hashlib.sha256(data).hexdigest(),attempts=attempt+1)
                break
        except (HTTPError,URLError,TimeoutError,OSError,ValueError) as e:
            meta['error']=f'{type(e).__name__}: {e}'
            meta['attempts']=attempt+1
            if isinstance(e, (ValueError, HTTPError)):
                break
            if attempt+1 < attempts:
                from urllib.parse import urlparse
                time.sleep(3.1 if (urlparse(a.url).hostname or '').endswith('arxiv.org') else 2)
    (directory/'metadata.json').write_text(json.dumps(meta,ensure_ascii=False,indent=2)+'\n')
    print(json.dumps(meta,ensure_ascii=False))
    return 0 if meta['status']=='downloaded' else 2
if __name__=='__main__': sys.exit(main())
