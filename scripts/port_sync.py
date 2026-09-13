#!/usr/bin/env python3
"""Reconcile Proton's forwarded peer port without bypassing Web UI authentication."""
import http.cookiejar
import json
import logging
from pathlib import Path
import time
import urllib.error
import urllib.parse
import urllib.request


def read_port(path):
    try:
        raw = path.read_text().strip()
    except FileNotFoundError:
        return None
    if not raw.isascii() or not raw.isdecimal() or not 1024 <= int(raw) <= 65535 or int(raw) == 8080:
        raise ValueError('Invalid forwarded peer port')
    return int(raw)


class Client:
    def __init__(self, url, username, password):
        self.url, self.username, self.password = url, username, password

    def reconcile(self, port):
        # A new authenticated session handles container restarts and credential rotation.
        cookies = http.cookiejar.CookieJar()
        opener = urllib.request.build_opener(urllib.request.HTTPCookieProcessor(cookies))
        def request(endpoint, fields=None):
            data = urllib.parse.urlencode(fields).encode() if fields is not None else None
            req = urllib.request.Request(self.url + '/api/v2/' + endpoint, data=data,
                                         headers={'Referer': self.url + '/'})
            with opener.open(req, timeout=10) as response:
                return response.read()
        login = request('auth/login', {'username': self.username.read_text().strip(),
                                       'password': self.password.read_text().rstrip('\r\n')})
        # qBittorrent 5.2 returns 204 with an empty body; older versions return Ok.
        if login.strip() not in (b'', b'Ok.') or not cookies:
            raise RuntimeError('qBittorrent rejected credentials')
        try:
            wanted = {'current_network_interface': 'tun0' if port is not None else 'lo',
                      'upnp': False, 'random_port': port is None}
            if port is not None:
                wanted['listen_port'] = port
            current = json.loads(request('app/preferences'))
            if any(current.get(key) != value for key, value in wanted.items()):
                # Port zero asks qBittorrent to choose a new port; the saved value is nonzero.
                payload = wanted if port is not None else {**wanted, 'listen_port': 0}
                request('app/setPreferences', {'json': json.dumps(payload)})
                current = json.loads(request('app/preferences'))
                if any(current.get(key) != value for key, value in wanted.items()):
                    raise RuntimeError('qBittorrent did not apply network settings: ' + repr({key: current.get(key) for key in wanted}))
                logging.info('Peer settings reconciled; forwarding %s', 'enabled' if port else 'disabled')
        finally:
            request('auth/logout', {})


def main():
    logging.basicConfig(level=logging.INFO, format='%(asctime)s %(levelname)s %(message)s')
    client = Client('http://127.0.0.1:8080', Path('/run/secrets/qbit_username'), Path('/run/secrets/qbit_password'))
    while True:
        try:
            try:
                with urllib.request.urlopen('http://127.0.0.1:9999/', timeout=5) as response:
                    healthy = response.status == 200
            except (OSError, urllib.error.URLError):
                healthy = False
            try:
                port = read_port(Path('/forwarded/port')) if healthy else None
            except ValueError:
                port = None
            client.reconcile(port)
            Path('/tmp/sync-health').touch()
        except (OSError, ValueError, RuntimeError, urllib.error.URLError):
            # Do not log HTTP bodies, credentials or request URLs.
            logging.warning('Port sync unavailable; check VPN health, Web UI credentials and settings')
            Path('/tmp/sync-health').unlink(missing_ok=True)
        time.sleep(30)


if __name__ == '__main__':
    main()
