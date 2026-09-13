#!/usr/bin/env python3
"""Opt-in integration test with installed restic, age and tar; no real credentials."""
import importlib.util
import os
from pathlib import Path
import sqlite3
import subprocess
import tempfile
from unittest.mock import patch

SOURCE = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location('ops', SOURCE/'scripts/ops.py')
ops = importlib.util.module_from_spec(spec); spec.loader.exec_module(ops)

with tempfile.TemporaryDirectory(prefix='harbor-recovery-') as temporary:
    root = Path(temporary)
    checkout = root/'checkout'; checkout.mkdir()
    for folder in ['config', 'secrets', 'scripts', 'docs']:
        (checkout/folder).mkdir()
    for file in ['config/host.env','config/host.env.example','docker-compose.yml','harbor','scripts/example.py','docs/example.md']:
        (checkout/file).write_text('test fixture\n')
    (checkout/'secrets/qbit_password').write_text('recovery-test-only')
    (checkout/'secrets/qbit_password').chmod(0o600)
    appdata = root/'appdata'; (appdata/'sonarr').mkdir(parents=True)
    database = sqlite3.connect(appdata/'sonarr/settings.db')
    database.execute('create table settings (value text)')
    database.execute("insert into settings values ('survived')")
    database.commit(); database.close()
    password = root/'restic-password'; password.write_text('integration-test-only')
    os.environ['RESTIC_REPOSITORY'] = str(root/'repository')
    os.environ['RESTIC_PASSWORD_FILE'] = str(password)
    ops.ROOT = checkout
    ops.run(['restic','init'], capture=True)
    states = []
    def compose(*args, **kwargs):
        states.append(args)
        return 'sonarr\n' if len(states) == 1 else ''
    with patch.object(ops, 'model', return_value={'services':{'sonarr':{'volumes':[{'target':'/config','source':str(appdata/'sonarr')}]}}}), patch.object(ops, 'compose', side_effect=compose):
        ops.backup()
    assert states[-1] == ('start','sonarr')
    ops.run(['restic','check'],capture=True)
    staging = root/'restore'
    ops.restore('latest',staging)
    recovered = staging/str(appdata).lstrip('/')/'sonarr/settings.db'
    connection = sqlite3.connect(recovered)
    assert connection.execute('select value from settings').fetchone()[0] == 'survived'
    connection.close()
    recovered_secret = staging/str(checkout).lstrip('/')/'secrets/qbit_password'
    assert recovered_secret.read_text() == 'recovery-test-only'
    assert recovered_secret.stat().st_mode & 0o777 == 0o600
    identity = root/'identity'
    subprocess.run(['age-keygen','-o',str(identity)],check=True,stderr=subprocess.DEVNULL)
    recipient = subprocess.check_output(['age-keygen','-y',str(identity)],text=True).strip()
    encrypted = root/'bootstrap.tar.age'
    ops.export_secrets(recipient, encrypted)
    archive = root/'bootstrap.tar'
    subprocess.run(['age','-d','-i',str(identity),'-o',str(archive),str(encrypted)],check=True)
    output = subprocess.check_output(['tar','-xOf',str(archive),'secrets/qbit_password'],text=True)
    assert output == 'recovery-test-only'
    print('Real restic backup/check/staged restore and age export/decryption passed')
