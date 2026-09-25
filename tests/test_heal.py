import fcntl
import importlib.util
import json
from pathlib import Path
import subprocess
import tempfile
import unittest
from unittest.mock import patch

SCRIPT = Path(__file__).resolve().parents[1] / 'scripts/heal.py'

SPEC = {'services': {
    'gluetun': {'ports': [{'host_ip': '127.0.0.1', 'published': '8080', 'target': 8080, 'protocol': 'tcp'}]},
    'port-sync': {'network_mode': 'service:gluetun', 'depends_on': {'gluetun': {'condition': 'service_healthy'}, 'qbittorrent': {'condition': 'service_started'}}},
    'qbittorrent': {'network_mode': 'service:gluetun', 'depends_on': {'gluetun': {'condition': 'service_healthy'}}},
    'plex': {'ports': [{'published': '32400', 'target': 32400, 'protocol': 'tcp'}, {'published': '32410', 'target': 32410, 'protocol': 'udp'}]},
    'recyclarr': {},
}}


class Fake:
    """Records Compose and Docker calls and answers them from an in-memory stack."""
    def __init__(self):
        self.containers = {}   # service -> dict(id, status, health, started)
        self.stale = set()     # services whose container cannot see its marker
        self.stopped_meanwhile = set()  # services stopped between observation and the restart
        self.restarted_meanwhile = set()  # services restarted by someone else between observation and the restart
        self.removed_meanwhile = set()  # services whose container was removed between observation and the restart
        self.extra_rows = []   # additional compose ps rows, such as a second container for one service
        self.no_exec = set()   # services whose image cannot run test
        self.unreachable = set()
        self.calls = []
        self.fail = None       # exception raised by the next mutation

    def compose(self, *args, capture=False, timeout=None, **kw):
        assert timeout is not None, ('every Compose call carries a timeout', args)
        self.calls.append(('compose', *args))
        if args[0] == 'ps':
            rows = [{'ID': c['id'], 'Service': s, 'State': c['status'], 'Health': c['health']} for s, c in self.containers.items()]
            # Unescaped, as Compose prints non-ASCII text.
            return ''.join(json.dumps(row, ensure_ascii=False) + '\n' for row in self.extra_rows + rows)
        if self.fail:
            error, self.fail = self.fail, None
            raise error
        return ''

    def run(self, args, capture=False, timeout=None, **kw):
        assert timeout is not None, ('every Docker call carries a timeout', args)
        self.calls.append(('run', *args))
        if args[:4] == ['docker', 'inspect', '--format', '{{.Id}} {{.State.Status}} {{.State.StartedAt}}']:
            lines = []
            for cid in args[4:]:
                service = next(s for s, c in self.containers.items() if c['id'] == cid)
                if service in self.removed_meanwhile:
                    continue
                c = self.containers[service]
                started = '2026-09-24T23:59:59Z' if service in self.restarted_meanwhile else c['started']
                lines.append(f"{cid}abcdef {'exited' if service in self.stopped_meanwhile else c['status']} {started}")
            output = ''.join(line + '\n' for line in lines)
            if any(s in self.removed_meanwhile for s, c in self.containers.items() if c['id'] in args[4:]):
                # Real docker inspect prints the containers it found, then exits 1 for the missing one.
                raise subprocess.CalledProcessError(1, args, output=output)
            return output
        if args[:4] == ['docker', 'inspect', '--format', '{{.Id}} {{.State.Status}} {{.State.StartedAt}} {{if .State.Error}}failed{{else}}ok{{end}} {{with index .State "Health"}}{{.Status}}{{end}}']:
            lines = []
            for cid in args[4:]:
                c = next(c for c in self.containers.values() if c['id'] == cid)
                lines.append(f"{cid}abcdef {c['status']} {c['started']} {'failed' if c.get('start_failed') else 'ok'} {c['health']}")
            return '\n'.join(lines) + '\n'
        if args[:2] == ['docker', 'exec']:
            service = next(s for s, c in self.containers.items() if c['id'] == args[2])
            if service in self.no_exec:
                raise subprocess.CalledProcessError(126, args)
            if service in self.stale:
                raise subprocess.CalledProcessError(1, args)
            return ''
        raise AssertionError(args)

    def probe(self, port):
        self.calls.append(('probe', port))
        return port not in self.unreachable

    def mutations(self):
        return [call[1:] for call in self.calls if call[0] == 'compose' and call[1] != 'ps']


class HealTests(unittest.TestCase):
    def setUp(self):
        spec = importlib.util.spec_from_file_location('heal', SCRIPT)
        self.mod = importlib.util.module_from_spec(spec); spec.loader.exec_module(self.mod)
        self.tmp = tempfile.TemporaryDirectory(); self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        self.fake = Fake()
        self.markers = []
        for service, folder, inside in [('plex', 'appdata/plex', '/config'), ('plex', 'data/media', '/data/media'), ('gluetun', 'appdata/gluetun', '/gluetun')]:
            (self.root/folder).mkdir(parents=True)
            (self.root/folder/'.mediaharbor').touch()
            self.markers.append((service, self.root/folder/'.mediaharbor', inside + '/.mediaharbor'))
        for i, service in enumerate(SPEC['services']):
            self.up(service, started=f'2026-09-24T10:00:0{i}Z', health='' if service == 'recyclarr' else 'healthy')

    def up(self, service, status='running', health='healthy', started='2026-09-24T10:00:00Z'):
        self.fake.containers[service] = {'id': 'id' + service, 'status': status, 'health': health, 'started': started}

    def healer(self):
        return self.mod.Healer(SPEC, self.markers, self.fake.compose, self.fake.run, self.fake.probe, self.root/'.local')

    def state(self):
        return json.loads((self.root/'.local/heal.json').read_text())

    def test_groups_and_probes_follow_the_model(self):
        self.assertEqual(self.mod.groups(SPEC), {'gluetun': ['qbittorrent', 'port-sync'], 'plex': [], 'recyclarr': []})
        self.assertEqual(self.mod.probes(SPEC), {'gluetun': [8080], 'port-sync': [], 'qbittorrent': [], 'plex': [32400], 'recyclarr': []})

    def test_epoch_orders_docker_timestamps(self):
        self.assertLess(self.mod.epoch('2026-09-24T04:14:01.9Z'), self.mod.epoch('2026-09-24T04:14:01.91377638Z'))
        self.assertLess(self.mod.epoch('0001-01-01T00:00:00Z'), self.mod.epoch('2026-01-01T00:00:00Z'))

    def test_healthy_stack_takes_no_action_and_writes_state(self):
        self.assertEqual(self.healer().heal(), [])
        self.assertEqual(self.fake.mutations(), [])
        self.assertEqual(self.state(), {'repairs': {}, 'sighted': []})
        self.assertFalse((self.root/'.local/heal.json.tmp').exists())
        self.assertEqual((self.root/'.local').stat().st_mode & 0o777, 0o700)

    def test_unhealthy_service_is_restarted_on_the_second_run(self):
        self.up('plex', health='unhealthy')
        with self.assertLogs('heal', level='INFO') as logs:
            self.assertEqual(self.healer().heal(), [])
        self.assertEqual(logs.output, ['INFO:heal:plex: unhealthy, first seen'])
        self.assertEqual(self.state()['sighted'], ['plex'])
        self.assertEqual(self.healer().heal(), [['restart', '--no-deps', '-t', '120', 'plex']])
        self.assertEqual(self.state()['repairs'], {'plex': 1})
        self.assertEqual(self.healer().heal(), [], 'every restart needs two sightings')
        self.assertEqual(self.healer().heal(), [['restart', '--no-deps', '-t', '120', 'plex']])

    def test_unreachable_port_is_repaired_only_when_seen_twice(self):
        self.fake.unreachable = {8080}
        self.assertEqual(self.healer().heal(), [])
        self.fake.unreachable = set()
        self.assertEqual(self.healer().heal(), [])
        self.assertEqual(self.state()['sighted'], [])
        self.fake.unreachable = {8080}
        self.healer().heal()
        self.assertEqual(self.healer().heal(), [['restart', '--no-deps', '-t', '120', 'gluetun', 'qbittorrent', 'port-sync']])

    def test_unreadable_marker_path_skips_the_service_without_crashing(self):
        real_stat = self.mod.os.stat
        def stat(path, *a, **kw):
            if str(path).endswith('.mediaharbor'):
                raise OSError(5, 'Input/output error')
            return real_stat(path, *a, **kw)
        with patch.object(self.mod.os, 'stat', stat), self.assertLogs('heal', level='WARNING') as logs:
            self.assertEqual(self.healer().heal(), [])
        self.assertTrue(any(line.startswith(('WARNING:heal:plex:', 'ERROR:heal:plex:')) for line in logs.output), logs.output)

    def test_dead_disk_that_is_still_mounted_skips_only_its_services(self):
        (self.root/'data/media/.mediaharbor').unlink()
        self.up('gluetun', health='unhealthy'); self.healer().heal()
        with patch.object(self.mod.Path, 'iterdir', side_effect=OSError(5, 'Input/output error')), self.assertLogs('heal', level='WARNING') as logs:
            self.assertEqual(self.healer().heal(), [['restart', '--no-deps', '-t', '120', 'gluetun', 'qbittorrent', 'port-sync']])
        self.assertTrue(any('plex: storage absent' in line for line in logs.output), logs.output)

    def test_repair_is_saved_before_its_command_runs(self):
        self.up('plex', health='unhealthy'); self.healer().heal()
        original = self.fake.compose
        def compose(*args, **kw):
            if args[0] == 'restart':
                raise KeyboardInterrupt  # systemd stops the run mid-restart
            return original(*args, **kw)
        self.fake.compose = compose
        with self.assertRaises(KeyboardInterrupt):
            self.healer().heal()
        self.assertEqual(self.state()['repairs'], {'plex': 1})

    def test_owner_without_a_health_check_is_reported(self):
        self.up('gluetun', health='')
        with self.assertLogs('heal', level='WARNING') as logs:
            self.healer().heal()
        self.assertIn('gluetun: no health check', logs.output[0])

    def test_cap_stops_restarts_and_logs_attention(self):
        (self.root/'.local').mkdir()
        (self.root/'.local/heal.json').write_text(json.dumps({'repairs': {'plex': 3}, 'sighted': ['plex']}))
        self.up('plex', health='unhealthy')
        with self.assertLogs('heal', level='ERROR') as logs:
            self.assertEqual(self.healer().heal(), [])
        self.assertIn('plex needs attention', logs.output[0])
        self.assertEqual(self.fake.mutations(), [])
        self.assertEqual(self.state()['repairs'], {'plex': 3})

    def test_recovery_clears_the_count(self):
        (self.root/'.local').mkdir()
        (self.root/'.local/heal.json').write_text(json.dumps({'repairs': {'plex': 2, 'gone': 1}, 'sighted': ['plex']}))
        with self.assertLogs('heal', level='INFO') as logs:
            self.healer().heal()
        self.assertIn('plex recovered', logs.output[0])
        self.assertEqual(self.state(), {'repairs': {}, 'sighted': []})

    def test_unhealthy_owner_restarts_its_running_sharers_only(self):
        self.up('gluetun', health='unhealthy'); self.up('port-sync', status='exited', health='')
        self.healer().heal()
        self.assertEqual(self.healer().heal(), [['restart', '--no-deps', '-t', '120', 'gluetun', 'qbittorrent']])
        self.assertEqual(self.state()['repairs'], {'gluetun': 1, 'qbittorrent': 1})

    def test_unhealthy_sharer_restarts_alone(self):
        self.up('qbittorrent', health='unhealthy')
        self.healer().heal()
        self.assertEqual(self.healer().heal(), [['restart', '--no-deps', '-t', '120', 'qbittorrent']])
        self.assertNotIn(('probe', 8080), self.fake.calls)

    def test_sharer_started_before_its_owner_is_restarted(self):
        self.up('gluetun', started='2026-09-24T11:00:00Z')
        self.assertEqual(self.healer().heal(), [['restart', '--no-deps', '-t', '120', 'qbittorrent'], ['restart', '--no-deps', '-t', '120', 'port-sync']])

    def test_unreachable_port_with_a_stale_sharer_restarts_only_the_sharers(self):
        self.up('gluetun', started='2026-09-24T11:00:00Z'); self.fake.unreachable = {8080}; self.healer().heal()
        self.assertEqual(self.healer().heal(), [['restart', '--no-deps', '-t', '120', 'qbittorrent'], ['restart', '--no-deps', '-t', '120', 'port-sync']])
        self.assertNotIn(('probe', 8080), self.fake.calls)

    def test_stale_storage_mount_is_restarted(self):
        self.fake.stale = {'plex', 'gluetun'}
        self.assertEqual(self.healer().heal(), [['restart', '--no-deps', '-t', '120', 'gluetun', 'qbittorrent', 'port-sync'], ['restart', '--no-deps', '-t', '120', 'plex']])
        exec_call = next(c for c in self.fake.calls if c[:3] == ('run', 'docker', 'exec') and c[3] == 'idplex')
        self.assertEqual(exec_call[4:], ('test', '-e', '/config/.mediaharbor', '-a', '-e', '/data/media/.mediaharbor'))

    def test_container_stopped_after_observation_is_not_restarted(self):
        self.fake.stale = {'plex'}; self.fake.stopped_meanwhile = {'plex'}
        with self.assertLogs('heal', level='INFO') as logs:
            self.assertEqual(self.healer().heal(), [])
        self.assertIn('plex: changed since it was observed', logs.output[-1])
        self.assertEqual(self.state()['repairs'], {})

    def test_container_restarted_by_someone_else_is_not_restarted_again(self):
        self.fake.stale = {'plex'}; self.fake.restarted_meanwhile = {'plex'}
        self.assertEqual(self.healer().heal(), [])

    def test_container_removed_after_observation_does_not_abort_the_run(self):
        self.up('gluetun', health='unhealthy'); self.healer().heal()
        self.fake.removed_meanwhile = {'port-sync'}
        self.assertEqual(self.healer().heal(), [['restart', '--no-deps', '-t', '120', 'gluetun', 'qbittorrent']])

    def test_member_stopped_after_observation_is_dropped_from_a_group_restart(self):
        self.up('gluetun', health='unhealthy'); self.healer().heal()
        self.fake.stopped_meanwhile = {'port-sync'}
        self.assertEqual(self.healer().heal(), [['restart', '--no-deps', '-t', '120', 'gluetun', 'qbittorrent']])

    def test_storage_that_cannot_be_checked_is_not_counted_as_healthy(self):
        (self.root/'.local').mkdir()
        (self.root/'.local/heal.json').write_text(json.dumps({'repairs': {'plex': 2}, 'sighted': []}))
        self.fake.no_exec = {'plex'}
        with self.assertLogs('heal', level='INFO') as logs:
            self.assertEqual(self.healer().heal(), [])
        self.assertIn('cannot check storage', logs.output[0])
        self.assertFalse(any('recovered' in line for line in logs.output), logs.output)
        self.assertEqual(self.state()['repairs'], {'plex': 2})

    def test_first_sighting_is_forgotten_when_the_next_run_does_not_repeat_it(self):
        self.fake.unreachable = {8080}
        self.healer().heal()
        self.fake.unreachable = set(); self.up('qbittorrent', health='starting')
        self.assertEqual(self.healer().heal(), [])
        self.up('qbittorrent'); self.fake.unreachable = {8080}
        self.assertEqual(self.healer().heal(), [], 'one slow answer after a gap must not restart the group')
        self.assertEqual(self.healer().heal(), [['restart', '--no-deps', '-t', '120', 'gluetun', 'qbittorrent', 'port-sync']])

    def test_capped_owner_does_not_hide_a_fault_in_its_sharer(self):
        (self.root/'.local').mkdir()
        (self.root/'.local/heal.json').write_text(json.dumps({'repairs': {'gluetun': 3}, 'sighted': []}))
        self.up('gluetun', health='unhealthy'); self.up('qbittorrent', health='unhealthy')
        self.healer().heal()
        self.assertEqual(self.healer().heal(), [['restart', '--no-deps', '-t', '120', 'qbittorrent']])

    def test_failed_re_check_before_a_restart_restarts_nothing(self):
        self.up('plex', health='unhealthy'); self.healer().heal()
        original = self.fake.run
        def run(args, **kw):
            if args[:4] == ['docker', 'inspect', '--format', '{{.Id}} {{.State.Status}} {{.State.StartedAt}}']:
                raise subprocess.TimeoutExpired(args, 30)
            return original(args, **kw)
        self.fake.run = run
        with self.assertLogs('heal', level='INFO') as logs:
            self.assertEqual(self.healer().heal(), [])
        self.assertIn('re-check before the restart timed out', logs.output[0])
        self.assertFalse(any('changed since it was observed' in line for line in logs.output), logs.output)

    def test_stale_sharer_is_never_capped(self):
        (self.root/'.local').mkdir()
        (self.root/'.local/heal.json').write_text(json.dumps({'repairs': {'qbittorrent': 3, 'port-sync': 3}, 'sighted': []}))
        self.up('gluetun', started='2026-09-24T11:00:00Z')
        self.assertEqual(self.healer().heal(), [['restart', '--no-deps', '-t', '120', 'qbittorrent'], ['restart', '--no-deps', '-t', '120', 'port-sync']])

    def test_sharer_that_failed_to_start_is_started_once_its_owner_is_healthy(self):
        self.up('qbittorrent', status='exited', health=''); self.fake.containers['qbittorrent']['start_failed'] = True
        self.up('gluetun', health='starting')
        self.assertEqual(self.healer().heal(), [])
        self.up('gluetun')
        self.assertEqual(self.healer().heal(), [['start', 'qbittorrent']])

    def test_ps_output_with_a_next_line_character_does_not_break_the_run(self):
        self.fake.extra_rows = [{'ID': 'idgone', 'Service': 'retired-app', 'State': 'exited', 'Health': '', 'Labels': 'note=a\x85b'}]
        self.assertEqual(self.healer().heal(), [])

    def test_created_service_without_dependencies_is_left_alone(self):
        self.up('plex', status='created', health='', started='0001-01-01T00:00:00Z')
        self.assertEqual(self.healer().heal(), [])

    def test_restart_is_logged_only_when_it_runs(self):
        (self.root/'.local').mkdir()
        self.up('plex', health='unhealthy'); self.healer().heal()
        with (self.root/'.local/backup.lock').open('w') as lock:
            fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
            with self.assertLogs('heal', level='INFO') as logs:
                self.healer().heal()
        self.assertFalse(any('restart 1 of 3' in line for line in logs.output), logs.output)

    def test_skipped_port_check_does_not_clear_the_count(self):
        # A host-side port fault a restart cannot fix, with a sharer still starting on the run after each restart.
        self.fake.unreachable = {8080}
        restarts = 0
        for _ in range(30):
            actions = self.healer().heal()
            restarts += len(actions)
            self.fake.containers['port-sync']['health'] = 'starting' if actions else 'healthy'
        self.assertEqual(restarts, 3)

    def test_sharer_without_its_disk_is_left_out_of_a_group_restart(self):
        self.markers.append(('qbittorrent', self.root/'data/torrents/.mediaharbor', '/data/.mediaharbor'))
        self.up('gluetun', health='unhealthy'); self.healer().heal()
        with self.assertLogs('heal', level='WARNING'):
            self.assertEqual(self.healer().heal(), [['restart', '--no-deps', '-t', '120', 'gluetun', 'port-sync']])

    def test_running_container_is_observed_when_a_service_has_two(self):
        self.fake.extra_rows = [{'ID': 'idold', 'Service': 'plex', 'State': 'exited', 'Health': ''}]
        self.fake.containers['plex-old'] = {'id': 'idold', 'status': 'exited', 'health': '', 'started': '2026-09-24T09:00:00Z'}
        self.up('plex', health='unhealthy'); self.healer().heal()
        self.assertEqual(self.healer().heal(), [['restart', '--no-deps', '-t', '120', 'plex']])

    def test_run_over_its_time_budget_defers_remaining_restarts(self):
        self.up('plex', health='unhealthy'); self.healer().heal()
        with patch.object(self.mod, 'RUN_BUDGET', -1), self.assertLogs('heal', level='INFO') as logs:
            self.assertEqual(self.healer().heal(), [])
        self.assertIn('the next run repairs it', logs.output[-1])
        self.assertEqual(self.state()['repairs'], {})

    def test_unreachable_port_restarts_the_group_only_when_all_members_are_healthy(self):
        self.fake.unreachable = {8080}
        self.healer().heal()
        self.assertEqual(self.healer().heal(), [['restart', '--no-deps', '-t', '120', 'gluetun', 'qbittorrent', 'port-sync']])
        self.fake.calls.clear(); self.fake.containers['port-sync']['health'] = 'starting'
        self.assertEqual(self.healer().heal(), [])
        self.assertNotIn(('probe', 8080), self.fake.calls)

    def test_stopped_member_explains_an_unreachable_port(self):
        self.up('qbittorrent', status='exited', health=''); self.fake.unreachable = {8080}
        self.healer().heal()
        self.assertEqual(self.healer().heal(), [])
        self.assertNotIn(('probe', 8080), self.fake.calls)

    def test_missing_host_marker_skips_that_service_only(self):
        (self.root/'data/media/.mediaharbor').unlink()
        self.up('plex', health='unhealthy'); self.up('gluetun', health='unhealthy')
        self.healer().heal()
        with self.assertLogs('heal', level='WARNING') as logs:
            self.assertEqual(self.healer().heal(), [['restart', '--no-deps', '-t', '120', 'gluetun', 'qbittorrent', 'port-sync']])
        self.assertTrue(any(line.startswith('WARNING:heal:plex: storage absent at') for line in logs.output), logs.output)

    def test_marker_deleted_from_a_populated_folder_is_reported_as_missing(self):
        (self.root/'data/media/.mediaharbor').unlink(); (self.root/'data/media/movies').mkdir()
        with self.assertLogs('heal', level='ERROR') as logs:
            self.assertEqual(self.healer().heal(), [])
        self.assertIn('plex: marker', logs.output[0]); self.assertIn('is missing from a folder that has content', logs.output[0])

    def test_empty_observation_is_a_clean_no_op(self):
        self.fake.containers.clear()
        with self.assertLogs('heal', level='WARNING') as logs:
            self.assertEqual(self.healer().heal(), [])
        self.assertIn('No containers found', logs.output[0])
        self.assertEqual(self.fake.mutations(), [])

    def test_stopped_paused_and_restarting_containers_are_left_alone(self):
        self.up('plex', status='exited', health='unhealthy'); self.up('qbittorrent', status='paused')
        self.up('gluetun', status='restarting', health='unhealthy')
        with self.assertLogs('heal', level='INFO') as logs:
            self.healer().heal()
        self.assertEqual(logs.output, ['INFO:heal:gluetun: restarting'])
        self.assertEqual(self.healer().heal(), [])

    def test_created_sharer_is_started_only_when_its_dependencies_are_healthy(self):
        self.up('qbittorrent', status='created', health='', started='0001-01-01T00:00:00Z')
        self.assertEqual(self.healer().heal(), [['start', 'qbittorrent']])
        self.fake.calls.clear(); self.up('gluetun', health='unhealthy')
        self.assertEqual(self.healer().heal(), [])

    def test_dry_run_mutates_nothing_and_writes_nothing(self):
        self.up('plex', health='unhealthy'); self.healer().heal()
        before = (self.root/'.local/heal.json').read_text()
        with self.assertLogs('heal', level='INFO') as logs:
            self.assertEqual(self.healer().heal(dry_run=True), [['restart', '--no-deps', '-t', '120', 'plex']])
        self.assertTrue(any('would run compose restart --no-deps -t 120 plex' in line for line in logs.output), logs.output)
        self.assertTrue(any(line.endswith('gluetun: healthy') for line in logs.output), logs.output)
        self.assertEqual(self.fake.mutations(), [])
        self.assertEqual((self.root/'.local/heal.json').read_text(), before)

    def test_second_run_exits_while_the_heal_lock_is_held(self):
        (self.root/'.local').mkdir()
        with (self.root/'.local/heal.lock').open('w') as lock:
            fcntl.flock(lock, fcntl.LOCK_EX)
            self.assertEqual(self.healer().heal(), [])
        self.assertEqual(self.fake.calls, [])

    def test_no_restart_while_a_backup_holds_its_lock(self):
        (self.root/'.local').mkdir()
        self.up('plex', health='unhealthy'); self.up('recyclarr', health='unhealthy'); self.healer().heal()
        with (self.root/'.local/backup.lock').open('w') as lock:
            fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
            self.assertEqual(self.healer().heal(), [])
        self.assertEqual(self.fake.mutations(), [])
        self.assertEqual(self.state()['repairs'], {})

    def test_failed_restart_still_counts_and_the_run_continues(self):
        self.up('plex', health='unhealthy'); self.up('recyclarr', health='unhealthy')
        self.healer().heal()
        self.fake.fail = subprocess.TimeoutExpired(['docker'], 300)
        with self.assertLogs('heal', level='ERROR') as logs:
            actions = self.healer().heal()
        self.assertEqual(actions, [['restart', '--no-deps', '-t', '120', 'plex'], ['restart', '--no-deps', '-t', '120', 'recyclarr']])
        self.assertIn('failed', logs.output[0])
        self.assertEqual(self.state()['repairs'], {'plex': 1, 'recyclarr': 1})

    def test_hand_edited_state_cannot_crash_the_run_or_lift_the_cap(self):
        (self.root/'.local').mkdir()
        for repairs, sighted in [({'plex': '2'}, []), ({'plex': None}, []), ({'plex': float('nan')}, []), ({'plex': -5}, []),
                                 ({'plex': 1}, 'plex'), ({'plex': 1}, [3]), ([], [])]:
            (self.root/'.local/heal.json').write_text(json.dumps({'repairs': repairs, 'sighted': sighted}))
            with self.assertLogs('heal', level='WARNING') as logs:
                self.healer().heal()
            self.assertIn('Ignoring heal.json with unexpected values', logs.output[0], (repairs, sighted))
            self.assertEqual(self.state(), {'repairs': {}, 'sighted': []})

    def test_unreadable_state_is_ignored(self):
        (self.root/'.local').mkdir(); (self.root/'.local/heal.json').write_text('{broken')
        with self.assertLogs('heal', level='WARNING'):
            self.healer().heal()
        self.assertEqual(self.state(), {'repairs': {}, 'sighted': []})


if __name__ == '__main__': unittest.main()
