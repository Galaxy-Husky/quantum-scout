"""Explicit production-only schema creation. Research/semantic validation remains agent work."""
import argparse
import sqlite3
from pathlib import Path


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('command', choices=['create-schema'])
    parser.add_argument('--workspace', type=Path, default=Path.cwd())
    parser.add_argument('--mode', choices=['calibration', 'production'], default='calibration')
    args = parser.parse_args()
    if args.mode == 'calibration':
        print('calibration: no database or filesystem changes')
        return
    db = args.workspace / 'quantum-scout.db'
    if db.exists():
        raise SystemExit('Database exists; refusing to overwrite or migrate implicitly.')
    schema = (args.workspace / 'config/schema.sql') if (args.workspace / 'config/schema.sql').exists() else (Path(__file__).resolve().parents[1] / 'config/schema.sql')
    ddl = schema.read_text(encoding='utf-8')
    # Validate before creating the file, and commit DDL atomically.
    with sqlite3.connect(':memory:') as check:
        check.executescript(ddl)
        assert check.execute('PRAGMA integrity_check').fetchone()[0] == 'ok'
    db.touch(exist_ok=False)
    try:
        with sqlite3.connect(db) as connection:
            connection.execute('PRAGMA foreign_keys = ON')
            connection.executescript(ddl)
        print(db)
    except Exception:
        db.unlink(missing_ok=True)
        raise


if __name__ == '__main__':
    main()
