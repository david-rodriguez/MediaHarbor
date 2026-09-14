# Private access

Proton VPN carries qBittorrent's traffic and gives it a forwarded **peer** port. It does not connect your laptop to the server. Tailscale does that. [README step 2](../README.md#2-set-up-tailscale) installs Tailscale and creates the app links. Turn on multi-factor authentication (MFA) for your Tailscale account, and approve each device.

Plex is different: it uses its own public port 32400. See [sharing](sharing.md).

## First login with SSH

From your computer, replace `server` with your server's address:

```sh
ssh -L 8080:127.0.0.1:8080 -L 32400:127.0.0.1:32400 your-user@server
```

- qBittorrent: open `http://localhost:8080`. The image prints a temporary password in `./harbor compose logs qbittorrent`. Log in, then set the username and password from your secret files at once. The files do not set the app password.
- Plex: open `http://localhost:32400/web` to finish first-time setup.

The SSH tunnel works even when Tailscale does not.

## Lock down qBittorrent

In qBittorrent's settings:

- Set **Advanced > Network interface** to `tun0`.
- Turn off UPnP/NAT-PMP and random listening ports.
- Keep Web UI authentication, Host header validation and CSRF protection on.
- Leave "Bypass authentication for clients on localhost" and "for clients in whitelisted IP subnets" **off**. The port helper logs in over localhost.
- Add the server's full Tailscale DNS name to **Server domains** before you use Serve.

## HTTPS with Tailscale Serve

Tailscale Serve gives each app an HTTPS address on your Tailscale network. [README step 2](../README.md#2-set-up-tailscale) creates the links. Run `sudo tailscale serve status` to list them.

- HTTPS certificates put the server's Tailscale name in public certificate transparency logs. Pick a name that tells nothing private.
- Each app uses its root URL, so leave **URL Base** empty everywhere.
- For Homepage, use the full Tailscale name in `config/host.env`. Do not use `*` for allowed hosts. Remove links for apps that you do not use.
- If qBittorrent rejects requests through Serve, turn on its reverse proxy support. Trust only the proxy address shown in its logs. Do not turn off its protections.

## Limit who can reach the server

The default Tailscale policy lets every tailnet member reach every port. Replace it. Give admins the admin ports, and give shared friends Seerr only:

```json
{
  "hosts": {
    "mediaharbor": "100.x.y.z"
  },
  "grants": [
    { "src": ["autogroup:admin"], "dst": ["mediaharbor"], "ip": ["tcp:22", "tcp:443", "tcp:8443", "tcp:8989", "tcp:7878", "tcp:9696", "tcp:6767"] },
    { "src": ["autogroup:shared"], "dst": ["mediaharbor"], "ip": ["tcp:443"] }
  ]
}
```

Add the ports of optional apps you turn on. Keep grants for your own other devices. Remove broad allow rules: a narrow rule does not override a broad one. Test with an allowed account and a blocked account.

More rules:

- Do not turn on Tailscale Funnel or router forwards for any app except Plex.
- Do not make this server use a Tailscale exit node. Gluetun already routes downloads.
- On a laptop, the Tailscale client and Proton's full-device client can fight over routing. Check split tunneling if access stops.
- After a rebuild, enroll the new server again and repeat [README step 2](../README.md#2-set-up-tailscale). Do not copy a Tailscale identity onto two live machines.
- Docker Engine 28+ is required. Older versions could expose localhost-published ports to the local network.
