#!/usr/bin/env python3
"""Opt-in fault injection on real Docker: break a disposable stack and prove harbor heal repairs it.

Uses a throwaway Compose project, loopback ports only, no real credentials.
"""
import importlib.util
import json
import logging
from pathlib import Path
import socket
import subprocess
import tempfile
import time
import uuid

ROOT = Path(__file__).resolve().parents[1]


def load(name):
    spec = importlib.util.spec_from_file_location(name, ROOT/'scripts'/f'{name}.py')
    module = importlib.util.module_from_spec(spec); spec.loader.exec_module(module)
    return module


ops, healing = load('ops'), load('heal')
image = ops.model(example=True)['services']['port-sync']['image']
project = 'harbor-heal-' + uuid.uuid4().hex[:8]
with socket.socket() as probe_socket:
    probe_socket.bind(('127.0.0.1', 0)); port = probe_socket.getsockname()[1]
# The server stays down after a restart while /tmp/broken exists in the container's own filesystem.
# init: true gives the containers a PID 1 that forwards SIGTERM, as the real images' s6 does, so a
# restart with the healer's stop grace finishes in seconds instead of at the deadline.
SERVE = "if [ ! -e /tmp/broken ]; then python -m http.server 8000 & fi; sleep infinity"
CHECK = {'test': ['CMD', 'wget', '-q', '--spider', 'http://127.0.0.1:8000/'], 'interval': '2s', 'timeout': '2s', 'retries': 2, 'start_period': '2s'}
STACK = {'name': project, 'services': {
    'owner': {'image': image, 'init': True, 'command': ['sh', '-c', SERVE], 'healthcheck': CHECK, 'volumes': ['./data:/data'], 'ports': [f'127.0.0.1:{port}:8000']},
    'sharer': {'image': image, 'init': True, 'command': ['sleep', 'infinity'], 'network_mode': 'service:owner',
               'depends_on': {'owner': {'condition': 'service_healthy', 'restart': True}}},
    'plain': {'image': image, 'init': True, 'command': ['sh', '-c', SERVE], 'healthcheck': CHECK, 'volumes': ['./data:/data']}}}
logging.basicConfig(level=logging.INFO, format='%(levelname)s %(message)s')


def main(work):
    def compose(*args, capture=False, timeout=None):
        return ops.run(['docker', 'compose', '--project-directory', work, '-f', work/'compose.yml', *args], capture=capture, timeout=timeout)

    def container(service):
        rows = [json.loads(line) for line in compose('ps', '--all', '--format', 'json', capture=True).splitlines() if line.strip()]
        return next(row for row in rows if row['Service'] == service)

    def inspect(service):
        container_id = container(service)['ID']
        state = json.loads(ops.run(['docker', 'inspect', '--format', '{{json .State}}', container_id], capture=True))
        return {'id': container_id, 'status': state['Status'], 'started': state['StartedAt'], 'health': (state.get('Health') or {}).get('Status', '')}

    def wait_for(service, health, seconds=40):
        deadline = time.monotonic() + seconds
        while time.monotonic() < deadline:
            if inspect(service)['health'] == health:
                return
            time.sleep(1)
        raise AssertionError(f'{service} did not become {health}')

    def exec_in(service, *command, check=True):
        return subprocess.run(['docker', 'exec', container(service)['ID'], *command], capture_output=True, text=True, check=check)

    def heal(dry_run=False):
        markers = [(service, work/'data'/ops.MARKER, f'/data/{ops.MARKER}') for service in ('owner', 'plain')]
        return healing.Healer(model, markers, compose, ops.run, ops.reachable, work/'.local').heal(dry_run=dry_run)

    (work/'data').mkdir(); (work/'data'/ops.MARKER).touch()
    (work/'compose.yml').write_text(json.dumps(STACK))
    model = json.loads(compose('config', '--format', 'json', capture=True))
    compose('up', '-d', '--wait')
    ids = {service: inspect(service)['id'] for service in STACK['services']}
    assert heal() == [], 'healthy stack must need no action'
    print('0. healthy stack: no action, host port probe passed')

    exec_in('plain', 'pkill', 'python'); wait_for('plain', 'unhealthy')
    assert heal() == [], 'first sighting of unhealthy must only record it'
    before = inspect('plain')
    assert heal() == [['restart', '--no-deps', '-t', '120', 'plain']]
    wait_for('plain', 'healthy'); after = inspect('plain')
    assert after['id'] == before['id'] and after['started'] > before['started'], 'restart must keep the container'
    assert heal() == [] and json.loads((work/'.local/heal.json').read_text())['repairs'] == {}
    print('1. killed server: restarted once (same container), healthy, count cleared')

    exec_in('plain', 'sh', '-c', 'touch /tmp/broken; pkill python'); wait_for('plain', 'unhealthy')
    restarts = 0
    for _ in range(9):
        actions = heal()
        if actions:
            restarts += 1; wait_for('plain', 'unhealthy')
        time.sleep(1)
    assert restarts == 3, restarts
    frozen = inspect('plain')
    assert heal() == [] and heal() == [] and inspect('plain')['started'] == frozen['started'], 'cap must stop restarts'
    exec_in('plain', 'rm', '/tmp/broken'); compose('restart', '--no-deps', '-t', '5', 'plain'); wait_for('plain', 'healthy')
    assert heal() == [] and json.loads((work/'.local/heal.json').read_text())['repairs'] == {}
    print('2. persistent fault: exactly 3 restarts, then needs attention; operator restart cleared the count')

    ops.run(['docker', 'restart', ids['owner']]); wait_for('owner', 'healthy')
    assert exec_in('sharer', 'wget', '-q', '-O', '-', 'http://127.0.0.1:8000/', check=False).returncode != 0, 'sharer must be in the dead namespace'
    assert heal() == [['restart', '--no-deps', '-t', '120', 'sharer']]
    assert exec_in('sharer', 'wget', '-q', '-O', '-', 'http://127.0.0.1:8000/', check=False).returncode == 0
    assert inspect('sharer')['id'] == ids['sharer']
    print('3. Docker restarted the owner: stale sharer restarted and reaches the owner again')

    (work/'data').rename(work/'data.old'); (work/'data').mkdir(); (work/'data'/ops.MARKER).touch(); (work/'data.old'/ops.MARKER).unlink()
    assert exec_in('plain', 'test', '-e', f'/data/{ops.MARKER}', check=False).returncode == 1, 'container must still see the old folder'
    assert heal() == [['restart', '--no-deps', '-t', '120', 'owner', 'sharer'], ['restart', '--no-deps', '-t', '120', 'plain']]
    for service in ('owner', 'plain'):
        wait_for(service, 'healthy')
        assert exec_in(service, 'test', '-e', f'/data/{ops.MARKER}', check=False).returncode == 0, service
        assert inspect(service)['id'] == ids[service]
    assert heal() == [], 'after a group restart the sharer must be in the new namespace'
    print('4. disk folder replaced on the host: stale containers restarted in order, marker visible again')

    compose('rm', '-sf', 'sharer'); compose('create', 'sharer')
    assert inspect('sharer')['status'] == 'created'
    assert heal() == [['start', 'sharer']] and inspect('sharer')['status'] == 'running'
    ops.run(['docker', 'stop', inspect('sharer')['id']]); compose('stop', 'owner')
    assert subprocess.run(['docker', 'start', inspect('sharer')['id']], capture_output=True).returncode != 0, 'a sharer cannot start without its owner'
    compose('start', 'owner'); wait_for('owner', 'healthy')
    assert heal() == [['start', 'sharer']] and inspect('sharer')['status'] == 'running'
    print('5. sharer left in created, and sharer that failed to start before its owner: both started')

    compose('stop', 'plain')
    assert heal() == [] and heal() == [] and inspect('plain')['status'] == 'exited'
    assert heal(dry_run=True) == []
    print('6. stopped on purpose: left alone')
    print('Real fault injection: restart, cap, stale namespace, stale mount, created and stopped cases passed')


with tempfile.TemporaryDirectory(prefix='harbor-heal-') as temporary:
    work = Path(temporary)
    try:
        main(work)
    finally:
        subprocess.run(['docker', 'compose', '--project-directory', work, '-f', work/'compose.yml', 'down', '-v', '--remove-orphans'],
                       stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
