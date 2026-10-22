"""Validate an isolated private Compose stack, with no published ports or real credentials.

Build an application image first, then run:
    python scripts/test_private_deployment.py --image ngx-trading-bot:test
Requires Docker Compose v2 with !override support and access to the Caddy image.
"""
import argparse
import json
from pathlib import Path
import secrets
import subprocess
import tempfile


PROBE = r'''
import base64
import http.client
import socket
import ssl
from websockets.sync.client import connect
context = ssl.create_default_context(cadata=CA_DATA)
def request(path, credentials=None):
    with socket.create_connection(('proxy', 443), timeout=10) as raw:
        with context.wrap_socket(raw, server_hostname='localhost') as secure:
            headers = f'GET {path} HTTP/1.1\r\nHost: localhost\r\nConnection: close\r\n'
            if credentials is not None:
                token = base64.b64encode(credentials.encode()).decode()
                headers += f'Authorization: Basic {token}\r\n'
            secure.sendall((headers + '\r\n').encode())
            response = http.client.HTTPResponse(secure)
            response.begin()
            return response.status, response.read()
assert request('/')[0] == 401
assert request('/_stcore/stream')[0] == 401
assert request('/_stcore/health', 'reviewer:wrong-password')[0] == 401
status, body = request('/_stcore/health', 'reviewer:' + PASSWORD)
assert status == 200 and body == b'ok', (status, body)
assert request('/', 'reviewer:' + PASSWORD)[0] == 200
token = base64.b64encode(('reviewer:' + PASSWORD).encode()).decode()
with connect('wss://localhost/_stcore/stream', sock=socket.create_connection(('proxy', 443), timeout=10),
             ssl=context, origin='https://localhost', subprotocols=['streamlit'],
             additional_headers={'Authorization': 'Basic ' + token}):
    pass
print('Verified HTTPS/WSS; missing/wrong credentials rejected; authenticated dashboard and health passed.')
'''


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--image', required=True)
    args = parser.parse_args()
    root = Path(__file__).resolve().parents[1]
    password = secrets.token_urlsafe(32)
    password_hash = subprocess.check_output([
        'docker', 'run', '--rm', 'caddy:2.10.2-alpine', 'caddy', 'hash-password',
        '--plaintext', password,
    ], text=True).strip()
    project = 'ngx-smoke-' + secrets.token_hex(5)
    with tempfile.TemporaryDirectory() as temporary:
        directory = Path(temporary)
        env_file = directory / 'settings.env'
        env_file.touch(mode=0o600)
        env_file.write_text("NGX_DOMAIN=localhost\nNGX_AUTH_USER=reviewer\nNGX_AUTH_HASH='" + password_hash + "'\n")
        override = directory / 'override.yaml'
        override.write_text('services:\n  dashboard:\n    image: ' + json.dumps(args.image)
                            + '\n  proxy:\n    ports: !override []\n')
        base = ['docker', 'compose', '--env-file', str(env_file), '-p', project,
                '-f', str(root / 'compose.private.yaml'), '-f', str(override)]
        def compose(*command, **kwargs):
            return subprocess.run(base + list(command), check=True, **kwargs)
        try:
            parsed = json.loads(subprocess.check_output(base + ['config', '--format', 'json'], text=True))
            assert not parsed['services']['dashboard'].get('ports')
            assert not parsed['services']['proxy'].get('ports')
            compose('up', '-d', '--no-build', '--wait', '--wait-timeout', '90')
            ca = subprocess.check_output(base + ['exec', '-T', 'proxy', 'cat',
                '/data/caddy/pki/authorities/local/root.crt'], text=True)
            script = 'CA_DATA = ' + repr(ca) + '\nPASSWORD = ' + repr(password) + '\n' + PROBE
            compose('exec', '-T', 'dashboard', 'python', '-', input=script, text=True)
            compose('exec', '-T', 'dashboard', 'python', '-c',
                    "import os, sqlite3; assert os.getuid() != 0; "
                    "c=sqlite3.connect('/app/data/smoke.db'); "
                    "c.execute('CREATE TABLE probe (value TEXT)'); "
                    "c.execute(\"INSERT INTO probe VALUES ('retained')\"); c.commit(); c.close()")
            compose('restart', 'dashboard')
            compose('up', '-d', '--no-build', '--wait', '--wait-timeout', '90')
            compose('exec', '-T', 'dashboard', 'python', '-c',
                    "import sqlite3; c=sqlite3.connect('/app/data/smoke.db'); "
                    "assert c.execute('SELECT value FROM probe').fetchone()[0] == 'retained'; c.close()")
            compose('exec', '-T', 'dashboard', 'python', '-', input=script, text=True)
            print('Non-root application and persistent storage across restart passed.')
        finally:
            # This random project and its synthetic data belong only to this test.
            compose('down', '--volumes', '--remove-orphans')


if __name__ == '__main__':
    main()
