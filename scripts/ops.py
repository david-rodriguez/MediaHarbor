#!/usr/bin/env python3
"""Explicit Compose configuration and recovery operations; Python standard library only."""
import argparse
import base64
import fcntl
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile

ROOT = Path(__file__).resolve().parents[1]
CORE_SECRETS = ['wireguard_private_key', 'qbit_username', 'qbit_password']
OPTIONAL_SECRETS = ['plex_claim', 'sonarr_api_key', 'radarr_api_key']
# Plex authenticates its own clients; every other port stays on loopback.
PUBLIC_PORTS = {('plex', '32400')}


def run(args, *, capture=False, env=None):
    result = subprocess.run([str(arg) for arg in args], cwd=ROOT, env=env,
                            check=True, text=True, stdout=subprocess.PIPE if capture else None)
    return result.stdout if capture else ''


def compose(*args, example=False, capture=False):
    env = dict(os.environ)
    keys = {line.split('=', 1)[0] for line in (ROOT/'config/host.env.example').read_text().splitlines() if '=' in line and not line.startswith('#')}
    for key in list(env):
        if key.startswith('COMPOSE_') or key in keys or key in {'APPDATA_ROOT', 'DATA_ROOT', 'HARBOR_ROOT'}:
            env.pop(key)
    config = ROOT/'config'/('host.env.example' if example else 'host.env')
    return run(['docker', 'compose', '--project-directory', ROOT, '--env-file', config,
                '-f', ROOT/'docker-compose.yml', *args], capture=capture, env=env)


def model(example=False):
    return json.loads(compose('--profile', '*', 'config', '--format', 'json', example=example, capture=True))


def initialize():
    os.umask(0o077)
    target = ROOT/'config/host.env'
    if not target.exists():
        shutil.copyfile(ROOT/'config/host.env.example', target)
    target.chmod(0o600)
    (ROOT/'secrets').mkdir(exist_ok=True, mode=0o700)
    for name in CORE_SECRETS + OPTIONAL_SECRETS:
        path = ROOT/'secrets'/name
        if not path.exists():
            path.write_text('admin\n' if name == 'qbit_username' else '')
        path.chmod(0o600)
    print('Private configuration initialized. Edit config/host.env and secrets/; existing values preserved.')


def check(example=False):
    if not example:
        for path in [ROOT/'config/host.env', *sorted((ROOT/'secrets').glob('*'))]:
            if '[PLACEHOLDER]' in path.read_text():
                raise ValueError(f'Replace [PLACEHOLDER] in {path.relative_to(ROOT)}')
    spec = model(example)
    for name, service in spec['services'].items():
        if '@sha256:' not in service['image']:
            raise ValueError(f'{name}: image is not digest pinned')
        for port in service.get('ports', []):
            if port.get('host_ip') != '127.0.0.1' and (name, str(port.get('published'))) not in PUBLIC_PORTS:
                raise ValueError(f'{name}: host ports must bind to loopback')
        for volume in service.get('volumes', []):
            if 'docker.sock' in volume.get('source', ''):
                raise ValueError(f'{name}: Docker socket access is forbidden')
    for name in ['qbittorrent', 'port-sync']:
        if spec['services'][name].get('network_mode') != 'service:gluetun':
            raise ValueError(f'{name}: must share Gluetun networking')
    if not example:
        for key in CORE_SECRETS + OPTIONAL_SECRETS:
            path = ROOT/'secrets'/key
            if not path.is_file():
                raise ValueError(f'secrets/{key} is missing; run init')
            if key in CORE_SECRETS and not path.read_text().strip():
                raise ValueError(f'Fill secrets/{key}')
            if path.stat().st_mode & 0o077:
                raise ValueError(f'secrets/{key} must have mode 0600')
        try:
            key = base64.b64decode((ROOT/'secrets/wireguard_private_key').read_text().strip(), validate=True)
        except ValueError:
            raise ValueError('WireGuard private key must be valid base64') from None
        if len(key) != 32:
            raise ValueError('WireGuard private key must decode to 32 bytes')
        for path in roots(spec):
            if not path.is_absolute() or path == Path('/'):
                raise ValueError('Storage paths must be absolute non-root directories')
    print('Compose configuration and deployment policy checks passed' + (' (templates only).' if example else '.'))


def roots(spec):
    volumes = spec['services']['sonarr']['volumes']
    appdata = Path(next(v['source'] for v in volumes if v['target'] == '/config')).parent
    data = Path(next(v['source'] for v in volumes if v['target'] == '/data'))
    return appdata, data


def prepare():
    if sys.platform != 'linux' or os.geteuid() != 0:
        raise ValueError('Run prepare as root on the target Linux NAS after mounting storage')
    check()
    spec = model()
    appdata, data = roots(spec)
    if not data.is_dir():
        raise ValueError('Create and mount DATA_ROOT first; prepare will not create the storage root')
    uid = int(spec['services']['sonarr']['environment']['PUID'])
    gid = int(spec['services']['sonarr']['environment']['PGID'])
    for name, service in spec['services'].items():
        for volume in service.get('volumes', []):
            path = Path(volume['source'])
            if path.parent == appdata and not path.exists():
                path.mkdir(parents=True, mode=0o750)
                # The official Seerr image always runs as UID/GID 1000.
                os.chown(path, *((1000, 1000) if name == 'seerr' else (uid, gid)))
    for name in ['torrents/movies','torrents/tv','torrents/music','torrents/audiobooks','usenet/incomplete','usenet/complete','media/movies','media/tv','media/music','media/audiobooks']:
        path = data/name
        path.mkdir(parents=True, exist_ok=True)
        os.chown(path, uid, gid)
        path.chmod(0o2775)
    # Secrets read by containers running as the media user.
    for name in ['qbit_username', 'qbit_password', 'sonarr_api_key', 'radarr_api_key']:
        os.chown(ROOT/'secrets'/name, uid, gid)
    for template in (ROOT/'config/homepage').glob('*.yaml'):
        target = appdata/'homepage'/template.name
        if not target.exists():
            shutil.copyfile(template, target)
            os.chown(target, uid, gid)
    print('Directories prepared. Existing appdata ownership was not modified.')


def backup():
    (ROOT/'.local').mkdir(exist_ok=True, mode=0o700)
    with (ROOT/'.local/backup.lock').open('w') as lock:
        fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        _backup()


def _backup():
    # Verify repository credentials and reachability before stopping applications.
    run(['restic', 'snapshots', '--json'], capture=True)
    spec = model()
    appdata = Path(next(v['source'] for v in spec['services']['sonarr']['volumes'] if v['target'] == '/config')).parent
    if not appdata.is_dir():
        raise ValueError('Application data root does not exist')
    running = compose('ps', '--status', 'running', '--services', capture=True).split()
    try:
        if running:
            compose('stop', '--timeout', '120', *running)
        # Never capture databases while a stack service is still writing.
        if compose('ps', '--status', 'running', '--services', capture=True).strip():
            raise RuntimeError('Containers are still running; backup aborted')
        run(['restic', 'backup', '--tag', 'mediaharbor', appdata,
             ROOT/'secrets', ROOT/'docker-compose.yml',
             ROOT/'scripts', ROOT/'harbor', ROOT/'docs', ROOT/'config'])
    finally:
        if running:
            compose('start', *running)
    print('Encrypted snapshot created. Run restic check and perform a restore drill.')


def restore(snapshot, target):
    target = Path(target).resolve()
    if target.exists():
        raise ValueError('Restore target must not exist; restore into a new staging directory')
    target.mkdir(parents=True, mode=0o700)
    run(['restic', 'restore', snapshot, '--tag', 'mediaharbor', '--target', target])
    print(f'Restored into {target}. Follow docs/recovery.md to inspect and install the recovered files.')


def export_secrets(recipient, output):
    output = Path(output).resolve()
    if output.exists():
        raise ValueError('Choose a new encrypted output filename')
    for path in [ROOT/'config/host.env', ROOT/'secrets']:
        if not path.exists():
            raise ValueError('Run init before exporting secrets')
    output.parent.mkdir(parents=True, exist_ok=True)
    fd, temporary = tempfile.mkstemp(dir=output.parent, suffix='.age.tmp')
    os.close(fd)
    try:
        with subprocess.Popen(['tar', '-C', str(ROOT), '-cf', '-', 'config/host.env', 'secrets'], stdout=subprocess.PIPE) as archive:
            encrypted = subprocess.run(['age', '-r', recipient, '-o', temporary], stdin=archive.stdout)
            archive.stdout.close()
            archive_status = archive.wait()
            if encrypted.returncode or archive_status:
                raise RuntimeError('Secret export failed')
        os.replace(temporary, output)
    finally:
        Path(temporary).unlink(missing_ok=True)
    print(f'Encrypted bootstrap archive written to {output}. Store the age identity separately.')


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest='action', required=True)
    sub.add_parser('init')
    sub.add_parser('prepare')
    validation = sub.add_parser('check'); validation.add_argument('--example', action='store_true')
    sub.add_parser('backup')
    recovery = sub.add_parser('restore'); recovery.add_argument('snapshot'); recovery.add_argument('target')
    export = sub.add_parser('export-secrets'); export.add_argument('recipient'); export.add_argument('output')
    dc = sub.add_parser('compose'); dc.add_argument('args', nargs=argparse.REMAINDER)
    args = parser.parse_args()
    if args.action == 'init': initialize()
    elif args.action == 'check': check(args.example)
    elif args.action == 'prepare': prepare()
    elif args.action == 'backup': backup()
    elif args.action == 'restore': restore(args.snapshot, args.target)
    elif args.action == 'export-secrets': export_secrets(args.recipient, args.output)
    elif args.action == 'compose': compose(*args.args)


if __name__ == '__main__':
    try:
        main()
    except (ValueError, RuntimeError, OSError, subprocess.CalledProcessError) as error:
        print(f'harbor: {error}', file=sys.stderr)
        sys.exit(1)
