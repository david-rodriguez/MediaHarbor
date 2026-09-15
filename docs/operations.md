# Operations

## App connections

Leave **URL Base** empty in every app. Apps talk to each other by Docker service name, not by the Tailscale URL:

| From | To | Settings |
| --- | --- | --- |
| Sonarr / Radarr / Lidarr / Bookshelf | qBittorrent | Host `gluetun`, port `8080`, your Web UI account; categories `tv`, `movies`, `music`, `audiobooks` |
| Sonarr / Radarr / Lidarr / Bookshelf | SABnzbd | `http://sabnzbd:8080` and its API key |
| Sonarr / Radarr | Plex | **Settings > Connect > Plex Media Server**: host `plex`, port `32400`, sign in; turn on library updates |
| Prowlarr | Sonarr / Radarr / Lidarr / Bookshelf | `http://sonarr:8989`, `http://radarr:7878`, `http://lidarr:8686`, `http://bookshelf:8787` (app type **Readarr**); each app's API key |
| Prowlarr | FlareSolverr | **Settings > Indexers**: add a FlareSolverr proxy at `http://flaresolverr:8191` with a tag; add that tag to Cloudflare-protected indexers |
| Bazarr | Sonarr / Radarr | Same URLs and API keys |
| Seerr | Plex | Sign in with your Plex admin account; server `plex`, port `32400`; select libraries |
| Seerr | Sonarr / Radarr | Same URLs and API keys; select root folders and quality profiles |
| Seerr | Jellyfin | `http://jellyfin:8096`, if you use Jellyfin instead of Plex |
| Tautulli | Plex | Host `plex`, port `32400` |

The Plex connection in Sonarr and Radarr tells Plex to scan as soon as a file is imported. New titles then show up with artwork in seconds. App passwords and API keys that you enter in app screens are stored in appdata, and the encrypted app backup covers them.

### Library folders

| App | Path |
| --- | --- |
| qBittorrent downloads | `/data/torrents/tv`, `/data/torrents/movies`, `/data/torrents/music`, `/data/torrents/audiobooks` |
| Sonarr / Radarr / Lidarr / Bookshelf root folders | `/data/media/tv`, `/data/media/movies`, `/data/media/music`, `/data/media/audiobooks` |
| SABnzbd | `/data/usenet/incomplete`, `/data/usenet/complete` |
| Plex libraries | `/data/media/tv`, `/data/media/movies`, `/data/media/music` |
| Audiobookshelf library | `/audiobooks` |

In qBittorrent, set **Settings > Downloads > Default Save Path** to `/data/torrents`. The image default, `/downloads`, does not exist in this setup, so the automation apps cannot import from it.

qBittorrent, SABnzbd and the four automation apps share one `/data` mount, so imports use hardlinks when both folders are on the same filesystem. Separate ZFS datasets or mounts break hardlinks even if the paths look close. No remote path mapping is needed. Plex, Jellyfin and Audiobookshelf get read-only media access. Bazarr can write subtitles next to media.

### Audiobooks

Bookshelf finds and downloads audiobooks. Audiobookshelf plays them.

- One Bookshelf install handles one book type. When you add the root folder `/data/media/audiobooks`, pick the **Spoken** quality profile so it grabs audio, not ebooks.
- In Audiobookshelf, create the first admin account at once. Then add a library with media type **Books** and the folder `/audiobooks`. Keep **Automatically watch library for changes** on, so new imports appear on their own.
- Audiobookshelf cannot upload or edit audio files. It keeps covers and metadata in its own appdata folder.

### Keep the library tidy

- In Sonarr, Radarr and Bookshelf, open **Settings > Media Management**. Turn on **Rename Episodes** / **Rename Movies** / **Rename Books** and **Use Hardlinks instead of Copy**.
- Plex fetches posters, backgrounds and details itself. Its default agents need no setup.
- The `recyclarr` profile syncs recommended quality profiles and naming. Create its config once:

  ```sh
  ./harbor compose run --rm recyclarr config create
  ```

  Edit `APPDATA_ROOT/recyclarr/recyclarr.yml`. Use `http://sonarr:8989` and `http://radarr:7878` as base URLs. Put API keys in `secrets.yml` in the same folder and refer to them with `!secret`.

### Archived downloads

Some releases arrive as `.rar` archives. The `unpackerr` profile extracts them before import. Copy the API keys from Sonarr and Radarr (**Settings > General**) into `secrets/sonarr_api_key` and `secrets/radarr_api_key`. Then run `sudo ./harbor prepare` and `./harbor compose up -d unpackerr`.

## Hardware transcoding

Plex Pass can transcode with an Intel or AMD GPU. Add the device to the `plex` service in a local `compose.override.yaml` (Git ignores it), then add that file to the wrapper from the repository root:

```yaml
services:
  plex:
    devices: [/dev/dri:/dev/dri]
```

```sh
./harbor compose -f compose.override.yaml up -d plex
```

Pass `-f compose.override.yaml` every time you recreate Plex, or the device is dropped. Then turn on **Use hardware acceleration** in Plex's transcoder settings.

## Routine checks

```sh
./harbor check
./harbor compose ps
./harbor compose logs --tail=100 gluetun port-sync
```

Gluetun reports VPN health. Port-sync becomes unhealthy if it cannot log in, apply settings or refresh its heartbeat. Every 30 seconds it checks the VPN and updates qBittorrent:

- VPN up: it sets the Proton forwarded port and binds peers to `tun0`.
- VPN down: it binds peers to loopback and asks for a random local port.

The VPN firewall is the main protection during outages. If port-sync's credentials are wrong, fix the secret files and the account in qBittorrent. No alerts are sent. Check health often, or connect your own alerting before you leave the server unattended.

Every app has `restart: unless-stopped`. Docker starts each app again after it exits and after the host reboots. An app that you stopped yourself stays stopped. Docker does not restart a container that is only unhealthy. Gluetun reconnects on its own. If you replace Gluetun, recreate everything that shares its network:

```sh
./harbor compose up -d --force-recreate gluetun qbittorrent port-sync
```

## Updates and rollback

1. Install the Renovate GitHub app on your repository. Read each proposed digest and the upstream release notes. A `latest` tag can cross major versions, so treat each change as possibly breaking.
2. Run an encrypted backup **before** you pull new code or start upgraded apps. Write down the restic snapshot ID and Git commit. Confirm `restic check` passes.
3. Pull the reviewed changes. Run `./harbor check` and the tests. Run `./harbor compose pull`.
4. Run `./harbor compose up -d --force-recreate`. Check health, login, a download and import, and playback.
5. If it fails, stop the stack. Check out the previous Git commit. Restore the matching appdata with the [recovery guide](recovery.md). Start with the previous images. Reverting an image alone does not undo a database migration.

Do not use in-app updaters or Watchtower. Digest pins make updates repeatable; they do not patch vulnerabilities by themselves. Apply host security updates, watch disk health and test UPS shutdown on your own.

## Deployment checks

Do these on the server before you add real downloads. Record the results and date.

- **Storage:** `findmnt -T /srv/mediaharbor/data` shows the expected disk. Ownership and free space are correct. After one reboot, mounts come up before containers. If your disks mount separately, add `RequiresMountsFor=` to the Docker systemd unit.
- **Network namespace:** qBittorrent and port-sync use Gluetun's network, with no other networks or published ports. Check `./harbor compose ps` and `docker inspect`.
- **VPN address:** `./harbor compose exec qbittorrent curl -fsS https://api.ipify.org` returns a Proton address, not your home address. DNS resolves, and IPv6 gives no other route.
- **Peer port:** qBittorrent's interface is `tun0`, UPnP and random ports are off, and its listening port equals `./harbor compose exec gluetun cat /forwarded/port`. The port is never 8080. `./harbor compose exec gluetun iptables -S INPUT` shows the rule that blocks ports 8000 and 8080 on the tunnel as the first rule.
- **Kill switch:** Run `./harbor compose exec gluetun ip link set tun0 down`. At once, repeat `curl --connect-timeout 2 --max-time 3 https://api.ipify.org` inside qBittorrent. Every request must fail. No request may return your home address. Restore with the recreate command above.
- **Recovery:** port-sync recovers after VPN and qBittorrent restarts. A legal test torrent downloads, accepts incoming peers, lands in the right category and imports as a hardlink.
- **Plex:** a device outside your home network plays a title over a direct (not relay) connection. Plex shows **Secure connections: Required**.
- **Access:** admin apps load from an allowed Tailscale device. They fail from a blocked account and from a LAN device without Tailscale. Port 8080 is not reachable from the internet or through the Proton peer port.
- **Backup:** a real backup, `restic check` and a staged restore all work. Restored apps start with separate ports and paths and show your requests, libraries and torrents.

Unit tests and Compose validation cannot prove these network and disk properties on your server.
