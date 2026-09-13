# Sources

This setup follows these vendor documents.

## Media apps

- [LinuxServer Plex](https://docs.linuxserver.io/images/docker-plex/): container settings, claim token and `/dev/dri` transcoding.
- [LinuxServer secrets from files](https://docs.linuxserver.io/FAQ/#can-i-use-docker-secrets): `FILE__` environment variables.
- [Seerr Plex features](https://docs.seerr.dev/using-seerr/plex/) and [Watchlist auto-request](https://docs.seerr.dev/using-seerr/plex/watchlist-auto-request/): Plex sign-in, permissions and limits.
- [Seerr installation](https://docs.seerr.dev/getting-started/): official image, UID 1000 and `init`.
- [Tautulli](https://docs.linuxserver.io/images/docker-tautulli/): container settings.
- [Recyclarr Docker](https://recyclarr.dev/wiki/installation/docker/): major-version tag, `user`, config creation.
- [Unpackerr configuration](https://unpackerr.zip/docs/install/configuration): environment variables and `filepath:` secrets.
- [FlareSolverr](https://github.com/FlareSolverr/FlareSolverr): Prowlarr proxy use.
- [Bookshelf](https://github.com/pennydreadful/bookshelf): Readarr revival, `hardcover` tag, port 8787.
- [Audiobookshelf Docker](https://www.audiobookshelf.org/docs#docker-compose-install): volumes, `user` and the `PORT` variable.

## Downloads and VPN

- [Gluetun Proton provider](https://github.com/qdm12/gluetun-wiki/blob/main/setup/providers/protonvpn.md): WireGuard key and NAT-PMP.
- [Gluetun port forwarding](https://github.com/qdm12/gluetun-wiki/blob/main/setup/advanced/vpn-port-forwarding.md): forwarded port file and reconnect behavior. Gluetun v4 plans to retire the status file; review `scripts/port_sync.py` before that upgrade.
- [Gluetun firewall](https://github.com/qdm12/gluetun-wiki/blob/main/setup/options/firewall.md): custom post-rules.
- [Gluetun secrets](https://github.com/qdm12/gluetun-wiki/blob/main/setup/advanced/docker-secrets.md): private key from a file.
- [Proton port forwarding](https://protonvpn.com/support/port-forwarding): plan requirements.
- [LinuxServer qBittorrent](https://docs.linuxserver.io/images/docker-qbittorrent/): temporary admin password.
- [qBittorrent Web API](https://github.com/qbittorrent/qBittorrent/wiki#webui-api): sessions and preferences.

## Access, platform and backups

- [Tailscale Serve](https://tailscale.com/docs/reference/tailscale-cli/serve): private HTTPS to localhost.
- [Tailscale sharing](https://tailscale.com/kb/1084/sharing): sharing one machine and `autogroup:shared`.
- [Tailscale Linux install](https://tailscale.com/download/linux).
- [Docker port publishing](https://docs.docker.com/engine/network/port-publishing/): localhost binding and the pre-28 exposure issue.
- [Docker Engine install](https://docs.docker.com/engine/install/).
- [restic backups](https://restic.readthedocs.io/en/stable/040_backup.html) and [installation](https://restic.readthedocs.io/en/stable/020_installation.html).
- [age](https://github.com/FiloSottile/age).
- [Portainer stacks](https://docs.portainer.io/user/docker/stacks/add): Repository and Web editor methods, environment variables.
- [Renovate Compose support](https://docs.renovatebot.com/modules/manager/docker-compose/).
- [Homepage configuration](https://gethomepage.dev/configs/).
