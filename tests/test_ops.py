import importlib.util
import inspect
import io
import json
import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
import subprocess

SCRIPT = Path(__file__).resolve().parents[1] / 'scripts/ops.py'

class OpsTests(unittest.TestCase):
    def setUp(self):
        self.assertTrue(SCRIPT.exists(), 'operations CLI has not been implemented')
        spec = importlib.util.spec_from_file_location('ops', SCRIPT)
        self.mod = importlib.util.module_from_spec(spec); spec.loader.exec_module(self.mod)
        self.tmp = tempfile.TemporaryDirectory(); self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        self.mod.ROOT = self.root
        (self.root/'config').mkdir()
        (self.root/'config/host.env.example').write_text('PUID=1000\n')
    def test_init_never_overwrites_host_config_or_secrets(self):
        self.mod.initialize()
        (self.root/'config/host.env').write_text('PUID=999\n')
        (self.root/'secrets/qbit_password').write_text('keep-me')
        self.mod.initialize()
        self.assertEqual((self.root/'config/host.env').read_text(), 'PUID=999\n')
        self.assertEqual((self.root/'secrets/qbit_password').read_text(), 'keep-me')
        self.assertEqual((self.root/'secrets/qbit_password').stat().st_mode & 0o777, 0o600)
    def test_backup_restarts_original_services_on_restic_failure(self):
        appdata = self.root/'appdata'; appdata.mkdir()
        commands = []
        def compose(*args, **kw):
            commands.append(args)
            return 'sonarr\nqbittorrent\n' if args[0] == 'ps' and len(commands) == 1 else ''
        def run(args, **kw):
            if 'backup' in args: raise subprocess.CalledProcessError(1, args)
            return ''
        with patch.object(self.mod, 'model', return_value={'services': {'sonarr': {'volumes': [{'target':'/config','source':str(appdata/'sonarr')} ]}}}), patch.object(self.mod, 'compose', side_effect=compose), patch.object(self.mod, 'run', side_effect=run):
            with self.assertRaises(subprocess.CalledProcessError): self.mod.backup()
        self.assertEqual(commands[-1], ('start', 'sonarr', 'qbittorrent'))
        self.assertIn(('stop', '--timeout', '120', 'sonarr', 'qbittorrent'), commands)
    def services(self, name, host_ip):
        services = {n: {'image': 'app@sha256:0', 'network_mode': 'service:gluetun'} for n in ['qbittorrent', 'port-sync']}
        port = {'target': 32400, 'published': '32400'}
        if host_ip: port['host_ip'] = host_ip
        services[name] = {'image': 'app@sha256:0', 'ports': [port]}
        return {'services': services}
    def test_only_plex_may_publish_beyond_loopback(self):
        with patch.object(self.mod, 'model', return_value=self.services('plex', None)):
            self.mod.check(example=True)
        for host_ip in [None, '0.0.0.0']:
            with patch.object(self.mod, 'model', return_value=self.services('sonarr', host_ip)):
                with self.assertRaises(ValueError): self.mod.check(example=True)
    def test_check_refuses_placeholders(self):
        self.mod.initialize()
        (self.root/'secrets/qbit_password').write_text('[NEW-STRONG-PASSWORD]\n')
        with patch.object(self.mod, 'model') as model:
            with self.assertRaisesRegex(ValueError, r'\[NEW-STRONG-PASSWORD\] in secrets/qbit_password'): self.mod.check()
        model.assert_not_called()
    def prepare_spec(self):
        appdata, data = self.root/'appdata', self.root/'data'; data.mkdir(exist_ok=True)
        (self.root/'secrets').mkdir(exist_ok=True); (self.root/'config/homepage').mkdir(exist_ok=True)
        for name in ['qbit_username', 'qbit_password', 'sonarr_api_key', 'radarr_api_key']: (self.root/'secrets'/name).write_text('')
        return {'services': {
            'sonarr': {'environment': {'PUID': '1000', 'PGID': '1000'}, 'volumes': [
                {'type': 'bind', 'source': str(appdata/'sonarr'), 'target': '/config'},
                {'type': 'bind', 'source': str(data), 'target': '/data'}]},
            'plex': {'volumes': [{'type': 'bind', 'source': str(appdata/'plex'), 'target': '/config'},
                                 {'type': 'bind', 'source': str(data/'media'), 'target': '/data/media', 'read_only': True}]},
            'gluetun': {'volumes': [{'type': 'bind', 'source': str(self.root/'config/gluetun/post-rules.txt'), 'target': '/iptables/post-rules.txt'}]},
            'port-sync': {'volumes': [{'type': 'tmpfs', 'target': '/tmp'}, {'type': 'volume', 'source': 'forwarded', 'target': '/forwarded'}]}}}
    def run_prepare(self, spec, system_filesystem=False):
        with patch.object(self.mod.sys, 'platform', 'linux'), patch.object(self.mod.os, 'geteuid', return_value=0), \
                patch.object(self.mod, 'check'), patch.object(self.mod, 'model', return_value=spec), patch.object(self.mod.os, 'chown'), \
                patch.object(self.mod, 'on_system_filesystem', return_value=system_filesystem), patch('sys.stdout', new_callable=io.StringIO) as out:
            self.mod.prepare()
        return out.getvalue()
    def test_prepare_creates_folders_and_skips_mounts_without_a_host_path(self):
        spec = self.prepare_spec()
        self.run_prepare(spec)
        self.assertTrue((self.root/'appdata/sonarr').is_dir())
        self.assertTrue((self.root/'data/media/audiobooks').is_dir())
    def test_markers_list_only_bind_mounts_under_the_storage_roots(self):
        spec = self.prepare_spec()
        found = {(service, str(source), target) for service, source, target in self.mod.markers(spec)}
        self.assertEqual(found, {('sonarr', str(self.root/'appdata/sonarr'), '/config'), ('sonarr', str(self.root/'data'), '/data'),
                                 ('plex', str(self.root/'appdata/plex'), '/config'), ('plex', str(self.root/'data/media'), '/data/media')})
    def test_prepare_writes_a_marker_into_every_mounted_folder(self):
        spec = self.prepare_spec()
        output = self.run_prepare(spec)
        for folder in ['appdata/sonarr', 'appdata/plex', 'data', 'data/media']:
            marker = self.root/folder/self.mod.MARKER
            self.assertTrue(marker.is_file(), folder)
            self.assertEqual(marker.stat().st_mode & 0o777, 0o644)
        self.assertFalse((self.root/'config/gluetun'/self.mod.MARKER).exists())
        self.assertNotIn('Warning', output)
    def test_prepare_refuses_a_marker_that_is_a_symlink(self):
        spec = self.prepare_spec()
        victim = self.root/'victim'; victim.write_text('keep'); victim.chmod(0o600)
        (self.root/'appdata/plex').mkdir(parents=True); (self.root/'appdata/plex'/self.mod.MARKER).symlink_to(victim)
        with self.assertRaisesRegex(ValueError, 'symlink'): self.run_prepare(spec)
        self.assertEqual(victim.stat().st_mode & 0o777, 0o600)
    def test_prepare_refuses_a_marker_that_is_a_pipe(self):
        spec = self.prepare_spec()
        (self.root/'appdata/plex').mkdir(parents=True); os.mkfifo(self.root/'appdata/plex'/self.mod.MARKER)
        with self.assertRaisesRegex(ValueError, 'not a regular file'): self.run_prepare(spec)
    def test_prepare_warns_when_a_root_is_on_the_system_filesystem(self):
        output = self.run_prepare(self.prepare_spec(), system_filesystem=True)
        self.assertIn('system filesystem', output)
    def test_heal_builds_the_healer_from_the_model_and_compose_wrapper(self):
        spec = self.prepare_spec()
        (self.root/'scripts').mkdir(); (self.root/'scripts/heal.py').write_text(
            "DOCKER_TIMEOUT = 30\n"
            "class Healer:\n"
            "    def __init__(self, spec, markers, compose, run, probe, state_dir): self.args = (spec, markers, compose, run, probe, state_dir)\n"
            "    def heal(self, dry_run=False): return (self.args, dry_run)\n")
        real = importlib.util.spec_from_file_location('real_heal', SCRIPT.parent/'heal.py')
        real_module = importlib.util.module_from_spec(real); real.loader.exec_module(real_module)
        self.assertEqual(list(inspect.signature(real_module.Healer.__init__).parameters)[:7], ['self', 'spec', 'markers', 'compose', 'run', 'probe', 'state_dir'])
        with patch.object(self.mod, 'model', return_value=spec), patch.object(self.mod.Path, 'resolve', return_value=self.root/'scripts/ops.py'):
            (args, dry_run) = self.mod.heal(dry_run=True)
        self.assertTrue(dry_run)
        self.assertEqual(args[0], spec)
        self.assertIn(('plex', self.root/'data/media/.mediaharbor', '/data/media/.mediaharbor'), args[1])
        self.assertIs(args[2], self.mod.compose)
        self.assertIs(args[3], self.mod.run)
        self.assertIs(args[4], self.mod.reachable)
        self.assertEqual(args[5], self.root/'.local')
    def test_reachable_counts_any_http_answer(self):
        from http.server import BaseHTTPRequestHandler, HTTPServer
        from threading import Thread
        class Handler(BaseHTTPRequestHandler):
            def log_message(self, *args): pass
            def do_GET(self):
                self.send_response(302 if self.path == '/' else 401); self.send_header('Location', 'https://example.invalid/'); self.end_headers()
        server = HTTPServer(('127.0.0.1', 0), Handler)
        Thread(target=server.serve_forever, daemon=True).start()
        self.addCleanup(server.server_close); self.addCleanup(server.shutdown)
        self.assertTrue(self.mod.reachable(server.server_port))
        server.shutdown(); server.server_close()
        self.assertFalse(self.mod.reachable(server.server_port))
        import socket, time
        def listener(reply):
            sock = socket.socket(); sock.bind(('127.0.0.1', 0)); sock.listen(); self.addCleanup(sock.close)
            def answer():
                client, _ = sock.accept(); reply(client); client.close()
            Thread(target=answer, daemon=True).start()
            return sock.getsockname()[1]
        self.assertTrue(self.mod.reachable(listener(lambda c: c.sendall(b'not http\r\n'))), 'any byte is an answer')
        self.assertFalse(self.mod.reachable(listener(lambda c: None)), 'closed without a byte is what a broken port proxy does')
        def clean_close(client):
            client.recv(100); client.shutdown(socket.SHUT_WR)
        self.assertFalse(self.mod.reachable(listener(clean_close)), 'an orderly close without a byte is unreachable too')
        def drip(client):
            client.recv(100)
            for _ in range(20):
                time.sleep(0.4)
        started = time.monotonic()
        self.assertFalse(self.mod.reachable(listener(drip)))
        self.assertLess(time.monotonic() - started, 6.5, 'one deadline for the whole exchange')
    def test_run_forwards_timeout(self):
        with patch.object(self.mod.subprocess, 'run') as run:
            run.return_value.stdout = ''
            self.mod.run(['true'], timeout=7)
        self.assertEqual(run.call_args.kwargs['timeout'], 7)
    def test_restore_refuses_existing_destination(self):
        (self.root/'important').write_text('keep')
        with self.assertRaises(ValueError): self.mod.restore('latest', self.root)
        self.assertEqual((self.root/'important').read_text(), 'keep')
    def test_compose_ignores_inherited_environment(self):
        with patch.dict('os.environ', {'COMPOSE_FILE':'bad.yml','APPDATA_ROOT':'/wrong','HARBOR_ROOT':'/wrong'}), patch.object(self.mod, 'run', return_value='') as run:
            self.mod.compose('config', '--quiet')
        args, kwargs = run.call_args
        self.assertNotIn('COMPOSE_FILE', kwargs['env'])
        self.assertNotIn('APPDATA_ROOT', kwargs['env'])
        self.assertNotIn('HARBOR_ROOT', kwargs['env'])
        self.assertIn(self.root/'config/host.env', args[0])

if __name__ == '__main__': unittest.main()
