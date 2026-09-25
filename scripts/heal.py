#!/usr/bin/env python3
"""Detect broken services and restart the smallest network group; Python standard library only."""
from datetime import datetime, timezone
import fcntl
import json
import logging
import os
from pathlib import Path
import subprocess
import time

# Restarts per service until it is seen healthy again.
CAP = 3
# Seconds an app gets to stop cleanly before Docker kills it; the backup's stop in ops.py uses the same value.
GRACE = 120
COMPOSE_TIMEOUT = 600
DOCKER_TIMEOUT = 30
# Seconds after which a run starts no new restart; the rest wait for the next run.
RUN_BUDGET = 600


def groups(spec):
    """Owner -> services that join its network namespace, each after the members it depends on."""
    found = {name: [] for name, service in spec['services'].items() if not service.get('network_mode', '').startswith('service:')}
    for name, service in spec['services'].items():
        mode = service.get('network_mode', '')
        if mode.startswith('service:'):
            found[mode.split(':', 1)[1]].append(name)
    for owner, sharers in found.items():
        ordered = []
        while sharers:
            first = next(s for s in sharers if not set(spec['services'][s].get('depends_on', {})) & set(sharers) - {s})
            sharers.remove(first); ordered.append(first)
        found[owner] = ordered
    return found


def probes(spec):
    """Service -> TCP ports it publishes on the host. Every one is reached at 127.0.0.1."""
    # A published range cannot be probed as one port and is skipped.
    return {name: [int(port['published']) for port in service.get('ports', []) if str(port.get('published', '')).isdigit() and port['protocol'] == 'tcp']
            for name, service in spec['services'].items()}


def populated(folder):
    try:
        return any(folder.iterdir())
    except OSError:
        # Gone, or a dead disk that is still mounted: either way there is nothing to read.
        return False


def epoch(stamp):
    """Docker trims trailing zeros from fractions, so timestamps cannot be compared as strings."""
    base, _, fraction = stamp.rstrip('Z').partition('.')
    seconds = datetime.strptime(base, '%Y-%m-%dT%H:%M:%S').replace(tzinfo=timezone.utc).timestamp()
    return seconds + (float('0.' + fraction) if fraction else 0.0)


class Healer:
    def __init__(self, spec, markers, compose, run, probe, state_dir):
        """markers: (service, marker path on the host, marker path inside the container)."""
        self.spec, self.markers, self.compose, self.run, self.probe = spec, markers, compose, run, probe
        self.state_dir = Path(state_dir)
        self.log = logging.getLogger('heal')
        self.groups = groups(spec)
        self.owner = {sharer: owner for owner, sharers in self.groups.items() for sharer in sharers}
        self.probes = probes(spec)

    def heal(self, dry_run=False):
        """Run one cycle. Returns the list of Compose mutations taken or, in a dry run, proposed."""
        if dry_run:
            return self.cycle(dry_run=True)
        self.state_dir.mkdir(mode=0o700, exist_ok=True)
        with (self.state_dir/'heal.lock').open('w') as lock:
            try:
                fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
            except BlockingIOError:
                self.log.info('Another heal run is active; skipping')
                return []
            return self.cycle(dry_run=False)

    def absent(self, service):
        return [host for name, host, _ in self.markers if name == service and not os.path.exists(host)]

    def cycle(self, dry_run):
        state = self.load_state()
        containers = self.observe()
        actions, handled, started = [], set(), time.monotonic()
        for owner, sharers in self.groups.items():
            for service in [owner, *sharers]:
                if service in handled or service not in containers:
                    continue
                absent = self.absent(service)
                if absent:
                    for host in absent:
                        if populated(host.parent):
                            self.log.error('%s: marker %s is missing from a folder that has content; if findmnt shows the disk mounted there, '
                                           'run sudo ./harbor prepare, otherwise mount it', service, host)
                        else:
                            self.log.warning('%s: storage absent at %s; mount it, and run sudo ./harbor prepare if it never was', service, host.parent)
                    continue
                if sharers and service == owner and containers[service]['health'] == '':
                    self.log.warning('%s: no health check, so faults in it are invisible to the healer', service)
                verdict, cause = self.classify(service, containers, state)
                if verdict == 'healthy':
                    if dry_run:
                        self.log.info('%s: healthy', service)
                    if state['repairs'].pop(service, 0) or service in state['sighted']:
                        self.log.info('%s recovered', service)
                    continue
                if verdict == 'leave':
                    # A fault seen once and Docker's own crash back-off are worth a journal line; a stopped app is not.
                    self.log.log(logging.INFO if dry_run or cause == 'restarting' or cause.endswith('first seen') else logging.DEBUG, '%s: %s', service, cause)
                    continue
                members = [service]
                if verdict == 'restart' and service in self.groups:
                    members += [s for s in self.groups[service] if containers.get(s, {}).get('status') == 'running' and not self.absent(s)]
                # A stale namespace cannot come back without the owner restarting again, so it is never capped:
                # capping it would strand the sharer in a dead network for good.
                if state['repairs'].get(service, 0) >= CAP and cause != 'stale network namespace':
                    # Its sharers are still classified on their own, so a fault in one of them is not hidden.
                    self.log.error('%s needs attention: %s; %d restarts did not help', service, cause, state['repairs'][service])
                    continue
                handled.update(members)
                if not dry_run and verdict == 'restart':
                    # Minutes can pass inside one run; a member stopped or restarted by someone else meanwhile is left alone.
                    members = self.unchanged(members, containers)
                    if members is None:
                        continue
                    if service not in members:
                        self.log.info('%s: changed since it was observed; left alone', service)
                        continue
                command = ['start', service] if verdict == 'start' else ['restart', '--no-deps', '-t', str(GRACE), *members]
                if dry_run:
                    self.log.info('%s: %s; would run compose %s', service, cause, ' '.join(command))
                    actions.append(command)
                    continue
                if time.monotonic() - started > RUN_BUDGET:
                    self.log.info('%s: %s; this run has used its time, the next run repairs it', service, cause)
                    continue
                if self.mutate(command, members, state, f'{service}: {cause}'):
                    actions.append(command)
        state['repairs'] = {name: count for name, count in state['repairs'].items() if name in containers}
        if not dry_run:
            self.save_state(state)
        return actions

    def debounce(self, service, cause, state):
        """A fault must be seen on two runs in a row before it is repaired; a sighting the next run does not repeat is forgotten."""
        state['sighting'].add(service)
        if service not in state['sighted']:
            return 'leave', cause + ', first seen'
        return 'restart', cause

    def classify(self, service, containers, state):
        container = containers[service]
        status, health = container['status'], container['health']
        if status == 'created' or (status == 'exited' and container['start_failed']):
            # Never started, or Docker could not start it (a sharer started before its owner, as after a reboot).
            # An app a person stopped is exited without a start error and is left alone below.
            needs = self.spec['services'][service].get('depends_on', {})
            if needs and all(containers.get(n, {}).get('status') == 'running' and containers[n]['health'] in ('healthy', '') for n in needs):
                return 'start', 'never started' if status == 'created' else 'failed to start'
            return 'leave', status
        if status != 'running':
            # Operator actions (stop, pause) and Docker's own crash back-off are never undone.
            return 'leave', status
        if health == 'starting':
            return 'leave', 'starting'
        if health == 'unhealthy':
            return self.debounce(service, 'unhealthy', state)
        owner = containers.get(self.owner.get(service))
        if owner and owner['status'] == 'running' and container['started'] < owner['started']:
            return 'restart', 'stale network namespace'
        storage = self.storage(service, container['id'])
        if storage == 'stale':
            return 'restart', 'stale storage mount'
        if storage == 'unknown':
            # Not checked is not healthy: only a full clean check clears the repair count.
            return 'leave', 'storage not checked'
        if self.probes[service]:
            # A member that is stopped, starting, unhealthy or stale already explains an unreachable port:
            # the operator stopped it, or restarting only that member is the smaller repair.
            members = [service, *self.groups[service]]
            if not all(containers.get(m, {}).get('status') == 'running' and containers[m]['health'] in ('healthy', '')
                       and containers[m]['started'] >= container['started'] for m in members):
                return 'leave', 'port check waits for its network group'
            for port in self.probes[service]:
                if not self.probe(port):
                    return self.debounce(service, f'port {port} unreachable on the host', state)
        return 'healthy', ''

    def storage(self, service, container_id):
        """'ok', 'stale' when the container cannot see a marker the host sees, or 'unknown'."""
        paths = [inside for name, _, inside in self.markers if name == service]
        if not paths:
            return 'ok'
        # As the container's own user: an app that cannot traverse its mount is broken anyway.
        test = ['docker', 'exec', container_id, 'test']
        for path in paths:
            test += ['-e', path, '-a']
        try:
            self.run(test[:-1], timeout=DOCKER_TIMEOUT)
            return 'ok'
        except subprocess.CalledProcessError as error:
            if error.returncode == 1:
                return 'stale'
            self.log.warning('%s: cannot check storage inside the container (exit %d)', service, error.returncode)
        except subprocess.TimeoutExpired:
            self.log.warning('%s: storage check timed out', service)
        return 'unknown'

    def unchanged(self, services, containers):
        """The given services whose containers still run with the start time observed, in the same order; None if Docker did not answer."""
        command = ['docker', 'inspect', '--format', '{{.Id}} {{.State.Status}} {{.State.StartedAt}}', *(containers[s]['id'] for s in services)]
        try:
            output = self.run(command, capture=True, timeout=DOCKER_TIMEOUT)
        except subprocess.CalledProcessError as error:
            # A removed container makes inspect fail; the lines for the others are still printed.
            output = error.output
        except subprocess.TimeoutExpired:
            self.log.warning('%s: re-check before the restart timed out; no restart this run', ' '.join(services))
            return None
        live = [line.split() for line in output.split('\n') if line]
        return [s for s in services if any(full.startswith(containers[s]['id']) and status == 'running' and epoch(when) == containers[s]['started']
                                           for full, status, when in live)]

    def observe(self):
        """Service -> id, status, health ('' without a check) and start time, from Compose and Docker."""
        # split('\n'), not splitlines(): the latter also splits on characters JSON may carry unescaped.
        rows = [json.loads(line) for line in self.compose('ps', '--all', '--format', 'json', capture=True, timeout=COMPOSE_TIMEOUT).split('\n') if line]
        ids = {}
        for row in rows:
            # An interrupted recreate can leave two containers for one service; the running one is the service.
            if row['Service'] in self.spec['services'] and (row['Service'] not in ids or row['State'] == 'running'):
                ids[row['Service']] = row['ID']
        if not ids:
            self.log.warning('No containers found for this project; nothing to heal')
            return {}
        containers = {}
        # Only fields Docker controls: the health log holds text the container itself printed.
        # index, not .State.Health: inspect rejects a missing key, and a container without a check has none.
        # State.Error is set only when Docker failed to start the container, never by a stop.
        fields = '{{.Id}} {{.State.Status}} {{.State.StartedAt}} {{if .State.Error}}failed{{else}}ok{{end}} {{with index .State "Health"}}{{.Status}}{{end}}'
        for line in self.run(['docker', 'inspect', '--format', fields, *ids.values()], capture=True, timeout=DOCKER_TIMEOUT).split('\n'):
            if not line:
                continue
            container_id, status, started, start, *health = line.split()
            service = next(s for s, i in ids.items() if container_id.startswith(i))
            containers[service] = {'id': ids[service], 'status': status, 'started': epoch(started), 'health': health[0] if health else '',
                                   'start_failed': start == 'failed'}
        return containers

    def mutate(self, command, members, state, reason):
        """Count and run one Compose mutation while holding the backup lock. False when a backup is running."""
        with (self.state_dir/'backup.lock').open('w') as lock:
            try:
                fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
            except BlockingIOError:
                self.log.info('Backup running; compose %s waits for the next run', ' '.join(command))
                return False
            self.log.warning('%s; compose %s (restart %d of %d)', reason, ' '.join(command), state['repairs'].get(members[0], 0) + 1, CAP)
            for member in members:
                state['repairs'][member] = state['repairs'].get(member, 0) + 1
                # The next restart of a debounced fault needs two fresh sightings.
                state['sighting'].discard(member)
            # Saved before the command, so a run that systemd stops mid-restart still counts it.
            self.save_state(state)
            try:
                self.compose(*command, timeout=COMPOSE_TIMEOUT)
            except (subprocess.CalledProcessError, subprocess.TimeoutExpired) as error:
                self.log.error('compose %s failed: %s', ' '.join(command), error)
            return True

    def load_state(self):
        try:
            state = json.loads((self.state_dir/'heal.json').read_text())
            repairs, sighted = state['repairs'], state['sighted']
            # A hand-edited file must not crash every run or lift the cap.
            if (isinstance(repairs, dict) and isinstance(sighted, list) and all(isinstance(s, str) for s in sighted)
                    and all(type(count) is int and count >= 0 for count in repairs.values())):
                return {'repairs': dict(repairs), 'sighted': set(sighted), 'sighting': set()}
            self.log.warning('Ignoring heal.json with unexpected values')
        except FileNotFoundError:
            pass
        except (ValueError, KeyError, TypeError):
            self.log.warning('Ignoring unreadable heal.json')
        return {'repairs': {}, 'sighted': set(), 'sighting': set()}

    def save_state(self, state):
        temporary = self.state_dir/'heal.json.tmp'
        temporary.write_text(json.dumps({'repairs': state['repairs'], 'sighted': sorted(state['sighting'])}, indent=1))
        os.replace(temporary, self.state_dir/'heal.json')
