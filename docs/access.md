# Private access

Proton VPN carries qBittorrent's traffic and gives it a forwarded **peer** port. It does not connect your laptop to the server. Tailscale does that. Install Tailscale on the server and on each of your devices, sign in, turn on account MFA and approve the devices.

Plex is different: it uses its own public port 32400. See [sharing](sharing.md).

## First login with SSH

From your computer, replace `server` with your server's address:

```sh
ssh -L 8080:127.0.0.1:8080 -L 32400:127.0.0.1:32400 your-user@server
```

- qBittorrent: open `http://localhost:8080`. The image prints a temporary password in `./harbor compose logs qbittorrent`. Log in, then set the username and password from your secret files at once. The files do not set the app password.
- Plex: open `http://localhost:32400/web` to finish first-time setup.

This works before Tailscale Serve is set up.

## Lock down qBittorrent

In qBittorrent's settings:

- Set **Advanced > Network interface** to `tun0`.
- Turn off UPnP/NAT-PMP and random listening ports.
- Keep Web UI authentication, Host header validation and CSRF protection on.
- Leave "Bypass authentication for clients on localhost" and "for clients in whitelisted IP subnets" **off**. The port helper logs in over localhost.
- Add the server's full Tailscale DNS name to **Server domains** before you use Serve.

## HTTPS with Tailscale Serve

On the server, run `sudo tailscale up`. In the Tailscale admin console, turn on MagicDNS and HTTPS. Use the full hostname Tailscale gives you, such as `mediaharbor.example-tailnet.ts.net`. HTTPS certificates put the hostname in public certificate transparency logs, so pick a name that tells nothing private.

```sh
sudo tailscale serve --bg --https=443 http://127.0.0.1:5055
sudo tailscale serve --bg --https=8443 http://127.0.0.1:8080
sudo tailscale serve --bg --https=8989 http://127.0.0.1:8989
sudo tailscale serve --bg --https=7878 http://127.0.0.1:7878
sudo tailscale serve --bg --https=9696 http://127.0.0.1:9696
sudo tailscale serve --bg --https=6767 http://127.0.0.1:6767
sudo tailscale serve status
```

Seerr is at `https://YOUR-SERVER-NAME`. qBittorrent is at `https://YOUR-SERVER-NAME:8443`. Each app uses its root URL, so leave **URL Base** empty everywhere.

Add mappings only for the optional apps you turn on:

```sh
sudo tailscale serve --bg --https=8181 http://127.0.0.1:8181   # Tautulli
sudo tailscale serve --bg --https=8096 http://127.0.0.1:8096   # Jellyfin
sudo tailscale serve --bg --https=8686 http://127.0.0.1:8686   # Lidarr
sudo tailscale serve --bg --https=8081 http://127.0.0.1:8081   # SABnzbd
sudo tailscale serve --bg --https=8787 http://127.0.0.1:8787   # Bookshelf
sudo tailscale serve --bg --https=13378 http://127.0.0.1:13378 # Audiobookshelf
sudo tailscale serve --bg --https=3000 http://127.0.0.1:3000   # Homepage
```

For Homepage, set `HOMEPAGE_ALLOWED_HOSTS=YOUR-SERVER-NAME:3000` and `HOMEPAGE_VAR_BASE_URL=https://YOUR-SERVER-NAME` in `config/host.env`. Remove links for apps you do not use. Do not use `*` for allowed hosts.

If qBittorrent rejects requests through Serve, turn on its reverse proxy support and trust only the proxy address shown in its logs. Do not turn off its protections.

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
- After a rebuild, enroll the new server again and reapply the Serve mappings. Do not copy a Tailscale identity onto two live machines.
- Docker Engine 28+ is required. Older versions could expose localhost-published ports to the local network.
