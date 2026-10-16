"""Observe asyncio thread shutdown in a bounded child; not a SIGSEGV reproducer."""
import argparse
import json
from pathlib import Path
import subprocess
import sys
import time

PROGRAM = '''import asyncio
async def main():
    print(await asyncio.to_thread(lambda: 42), flush=True)
asyncio.run(main())
print("asyncio_shutdown_completed", flush=True)
'''


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output', type=Path, required=True)
    parser.add_argument('--timeout', type=float, default=8)
    args = parser.parse_args()
    if args.output.exists():
        parser.error('Output exists; refusing to overwrite.')
    if not 0 < args.timeout <= 60:
        parser.error('Timeout must be greater than zero and at most 60 seconds.')
    started = time.monotonic()
    try:
        result = subprocess.run([sys.executable, '-c', PROGRAM], capture_output=True,
                                text=True, timeout=args.timeout)
        report = {'status': 'passed' if result.returncode == 0 and
                  'asyncio_shutdown_completed' in result.stdout else 'failed',
                  'exit_code': result.returncode, 'stdout': result.stdout, 'stderr': result.stderr}
    except subprocess.TimeoutExpired as exc:
        def decode(value):
            return value.decode(errors='replace') if isinstance(value, bytes) else value or ''
        report = {'status': 'timed_out', 'exit_code': None,
                  'stdout': decode(exc.stdout), 'stderr': decode(exc.stderr)}
    report.update(elapsed_seconds=time.monotonic() - started,
                  timeout_seconds=args.timeout, interpreter=sys.executable,
                  sigsegv_reproduced=report['exit_code'] == -11,
                  scope='asyncio thread shutdown only; no network or model calls')
    with args.output.open('x') as stream:
        json.dump(report, stream, indent=2)
        stream.write('\n')
    print(json.dumps(report))
    return 0 if report['status'] == 'passed' else 2


if __name__ == '__main__':
    raise SystemExit(main())
