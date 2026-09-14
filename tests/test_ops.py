import importlib.util
import json
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
