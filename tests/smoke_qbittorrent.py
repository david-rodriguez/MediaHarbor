#!/usr/bin/env python3
"""Opt-in Docker integration test. Uses disposable state, no network or host ports."""
import importlib.util
import json
from pathlib import Path
import re
import subprocess
import tempfile
import time
import uuid

ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location('ops', ROOT/'scripts/ops.py')
ops = importlib.util.module_from_spec(spec); spec.loader.exec_module(ops)
services = ops.model(example=True)['services']
name = 'harbor-test-' + uuid.uuid4().hex[:10]
def docker(*args, **kwargs):
    try:
        return subprocess.check_output(['docker', *map(str,args)], text=True, **kwargs)
    except subprocess.CalledProcessError as error:
        print(error.output)
        raise

with tempfile.TemporaryDirectory(prefix='harbor-qbit-') as temporary:
    path = Path(temporary)
    try:
        docker('run','-d','--name',name,'--network','none','-e','PUID=1000','-e','PGID=1000',services['qbittorrent']['image'])
        password = None
        deadline = time.monotonic() + 90
        while time.monotonic() < deadline:
            logs = docker('logs',name,stderr=subprocess.STDOUT)
            logs = re.sub(r'\x1b\[[0-9;]*[A-Za-z]', '', logs)
            match = re.search(r'temporary password is provided for this session: (\S+)', logs)
            if match:
                password = match[1]; break
            time.sleep(1)
        if not password: raise RuntimeError('Temporary qBittorrent password was not generated')
        (path/'username').write_text('admin')
        (path/'password').write_text(password)
        code = '''import sys; sys.path.insert(0, '/app')
from pathlib import Path
from port_sync import Client
client=Client('http://127.0.0.1:8080',Path('/test/username'),Path('/test/password'))
client.reconcile(45678)
client.reconcile(None)
client.reconcile(45678)
print('Real qBittorrent API: authenticated port/interface changes and reconnect cycle passed')
'''
        result = docker('run','--rm','--network','container:'+name,
                        '-v',str(ROOT/'scripts')+':/app:ro','-v',str(path)+':/test:ro',
                        services['port-sync']['image'],'python','-B','-c',code)
        print(result.strip())
    finally:
        subprocess.run(['docker','rm','-f','-v',name],stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL)
