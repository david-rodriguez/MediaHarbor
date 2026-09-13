#!/usr/bin/env python3
"""Verify the pinned Gluetun loads secret files and management-port firewall rules.

Uses an intentionally invalid test identity. Does not establish a Proton tunnel.
"""
import base64
import importlib.util
from pathlib import Path
import subprocess
import tempfile
import time
import uuid

ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location('ops', ROOT/'scripts/ops.py')
ops = importlib.util.module_from_spec(spec); spec.loader.exec_module(ops)
image = ops.model(example=True)['services']['gluetun']['image']
name = 'harbor-firewall-test-' + uuid.uuid4().hex[:10]
with tempfile.TemporaryDirectory(prefix='harbor-gluetun-') as temporary:
    key = Path(temporary)/'key'
    key.write_text(base64.b64encode(bytes([1])*32).decode())
    key.chmod(0o600)
    try:
        subprocess.run(['docker','run','-d','--name',name,'--cap-add','NET_ADMIN','--device','/dev/net/tun',
                        '-v',str(key)+':/run/secrets/wireguard_private_key:ro',
                        '-v',str(ROOT/'config/gluetun/post-rules.txt')+':/iptables/post-rules.txt:ro',
                        '-e','VPN_SERVICE_PROVIDER=protonvpn','-e','VPN_TYPE=wireguard',
                        '-e','SERVER_COUNTRIES=Netherlands',
                        '-e','WIREGUARD_PRIVATE_KEY_SECRETFILE=/run/secrets/wireguard_private_key',
                        image],check=True,stdout=subprocess.DEVNULL)
        deadline = time.monotonic()+45
        while time.monotonic() < deadline:
            result=subprocess.run(['docker','exec',name,'iptables','-C','INPUT','-i','tun0','-p','tcp',
                                   '-m','multiport','--dports','8000,8080','-j','DROP'],capture_output=True)
            if result.returncode == 0:
                print('Real Gluetun startup: private-key file accepted and VPN management-port block installed')
                break
            time.sleep(1)
        else:
            raise RuntimeError('Gluetun did not install the required firewall rule')
    finally:
        subprocess.run(['docker','rm','-f','-v',name],stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL)
