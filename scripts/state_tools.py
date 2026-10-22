"""Read-only recovery reports and consistent SQLite backups. Never edits trading state."""
import argparse
import json
import os
import sqlite3
from contextlib import closing
from pathlib import Path


def open_source(path):
    resolved = Path(path).resolve(strict=True)
    return sqlite3.connect(resolved.as_uri() + '?mode=ro', uri=True)


def report(path):
    with closing(open_source(path)) as conn:
        conn.row_factory = sqlite3.Row
        states = [dict(row) for row in conn.execute('SELECT * FROM ticker_states ORDER BY symbol')]
        orders = [dict(row) for row in conn.execute('SELECT * FROM orders ORDER BY updated_at')]
        integrity = conn.execute('PRAGMA quick_check').fetchone()[0]
    return {'integrity': integrity, 'ticker_states': states, 'orders': orders,
            'instructions': 'Compare orders, actual fills, holdings, and available cash with broker records. '
                            'SUBMISSION_PENDING requires broker-side order discovery. '
                            'No state has been cleared. Do not restart live trading until reconciled.'}


def backup(source, destination):
    destination = Path(destination)
    # Refuse to replace any previous backup or follow an existing symlink.
    fd = os.open(destination, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o600)
    os.close(fd)
    try:
        with closing(open_source(source)) as src, closing(sqlite3.connect(destination)) as dst:
            src.backup(dst)
            result = dst.execute('PRAGMA integrity_check').fetchone()[0]
            if result != 'ok':
                raise RuntimeError(f'Backup integrity check failed: {result}')
    except BaseException:
        destination.unlink()
        raise


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('command', choices=['report', 'backup'])
    parser.add_argument('--db', required=True, type=Path)
    parser.add_argument('--output', type=Path)
    args = parser.parse_args()
    if args.command == 'report':
        print(json.dumps(report(args.db), indent=2))
    else:
        if args.output is None:
            parser.error('backup requires --output (a new file)')
        backup(args.db, args.output)
        print('Backup complete; integrity_check: ok')


if __name__ == '__main__':
    main()
