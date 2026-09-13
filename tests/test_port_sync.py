import importlib.util
import json
from pathlib import Path
import tempfile
import unittest
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from threading import Thread
from urllib.parse import parse_qs

SCRIPT = Path(__file__).resolve().parents[1] / 'scripts/port_sync.py'

class SyncTests(unittest.TestCase):
    def setUp(self):
        self.assertTrue(SCRIPT.exists(), 'port synchronizer has not been implemented')
        spec = importlib.util.spec_from_file_location('port_sync', SCRIPT)
        self.mod = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(self.mod)
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        (self.root/'username').write_text('admin')
        (self.root/'password').write_text('test&password')
        self.prefs = {'listen_port': 6881, 'current_network_interface': '', 'upnp': True, 'random_port': True}
        self.reject = False
        outer = self
        class Handler(BaseHTTPRequestHandler):
            def log_message(self, *args): pass
            def do_POST(self):
                body = parse_qs(self.rfile.read(int(self.headers['Content-Length'])).decode())
                if self.path.endswith('/auth/login'):
                    outer.assertEqual(body['password'], ['test&password'])
                    self.send_response(200 if outer.reject else 204)
                    self.send_header('Set-Cookie', 'QBT_SID_8080=test; Path=/')
                    self.end_headers()
                    self.wfile.write(b'Fails.' if outer.reject else b'')
                elif self.path.endswith('/auth/logout'):
                    self.send_response(200); self.end_headers()
                else:
                    outer.assertIn('QBT_SID_8080=test', self.headers.get('Cookie', ''))
                    outer.prefs.update(json.loads(body['json'][0]))
                    if outer.prefs['listen_port'] == 0:
                        outer.prefs['listen_port'] = 49152
                        outer.prefs['random_port'] = True
                    self.send_response(200); self.end_headers()
            def do_GET(self):
                outer.assertIn('QBT_SID_8080=test', self.headers.get('Cookie', ''))
                self.send_response(200); self.end_headers()
                self.wfile.write(json.dumps(outer.prefs).encode())
        server = ThreadingHTTPServer(('127.0.0.1', 0), Handler)
        Thread(target=server.serve_forever, daemon=True).start()
        self.addCleanup(server.server_close)
        self.addCleanup(server.shutdown)
        self.client = self.mod.Client(f'http://127.0.0.1:{server.server_port}', self.root/'username', self.root/'password')
    def test_sets_forwarded_port_and_vpn_interface(self):
        self.client.reconcile(45678)
        self.assertEqual(self.prefs, dict(listen_port=45678, current_network_interface='tun0', upnp=False, random_port=False))
    def test_reconciles_after_qbittorrent_settings_reset(self):
        self.client.reconcile(45678)
        self.prefs['listen_port'] = 6881
        self.client.reconcile(45678)
        self.assertEqual(self.prefs['listen_port'], 45678)
    def test_rejects_failed_login(self):
        self.reject = True
        with self.assertRaises(RuntimeError): self.client.reconcile(45678)
        self.assertEqual(self.prefs['listen_port'], 6881)
    def test_missing_port_disables_peer_interface(self):
        self.client.reconcile(None)
        self.assertEqual(self.prefs['current_network_interface'], 'lo')
        self.assertEqual(self.prefs['listen_port'], 49152)
    def test_port_file_validation(self):
        path = self.root/'port'
        self.assertIsNone(self.mod.read_port(path))
        for value in ['', '0', '65536', '-1', '8080,9999', 'bad']:
            path.write_text(value)
            with self.assertRaises(ValueError): self.mod.read_port(path)
        path.write_text('45678\n')
        self.assertEqual(self.mod.read_port(path), 45678)

if __name__ == '__main__': unittest.main()
