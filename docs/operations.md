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

In qBittorrent, open **Settings > Downloads**. Set **Default Save Path** to `/data/torrents` and **Default Torrent Management Mode** to **Automatic**, then save. Automatic mode puts each category in its own folder, for example `tv` in `/data/torrents/tv`. The image default, `/downloads`, does not exist in this setup, so a torrent saved there shows **Errored**.

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

Pass `-f compose.override.yaml` every time you recreate Plex, or the device is dropped. The healer only restarts, so it keeps the device. Then turn on **Use hardware acceleration** in Plex's transcoder settings.

## Self-healing

The stack repairs itself in three layers. [README step 9](../README.md#9-turn-on-self-healing) turns it on.

1. **Docker detects.** Every app that serves HTTP has a health check that asks the app itself. An app whose process is alive but no longer answers shows `unhealthy` in `./harbor compose ps`. Gluetun uses the health check built into its image. Recyclarr and Unpackerr serve no HTTP, so Docker only restarts them when they exit.
2. **`harbor heal` repairs.** A systemd timer runs `./harbor heal` as root on the server, on the interval set in `config/systemd/harbor-heal.timer`. It restarts the smallest part that needs it, and it never recreates a container. It restarts an app that:
   - is `unhealthy` on two runs in a row. One run is not enough: Gluetun reports unhealthy within seconds and reconnects the VPN by itself, and the healer must not interrupt that;
   - shares Gluetun's network but started before Gluetun's last restart, so it sits in a dead network;
   - started before its media or appdata disk was mounted;
   - is healthy, but its port on the host does not answer on two runs in a row.

   It starts qBittorrent or port-sync when they never started, or when Docker could not start them because Gluetun was not running yet. It waits until what they depend on is healthy, so qBittorrent starts on one run and port-sync on a later one.
3. **systemd protects the boot.** A drop-in makes Docker wait for your storage mounts at boot. A reboot then cannot start apps against an empty folder. If a disk disappears later, Docker and the other apps keep running. The healer restarts the apps that use the disk once it is mounted again.

How the healer behaves:

- A restart of Gluetun also restarts qBittorrent and port-sync, in that order, because they share its network. A restart of qBittorrent or port-sync leaves Gluetun up.
- A restart gives the app the same time to stop cleanly as the backup gives it. `GRACE` in `scripts/heal.py` sets it.
- Each app gets a limited number of restarts, set by `CAP` in `scripts/heal.py`. After the last one, the healer logs `needs attention` on every run and leaves the app alone until it sees it healthy again. A fault that clears by itself therefore heals, and a broken app is not restarted forever.
- qBittorrent or port-sync in a dead network has no restart limit. One restart always fixes it, and it cannot happen again until Gluetun restarts again.
- The port check waits while any app in the same network is stopped, starting, unhealthy or waiting for its own restart. That app explains the silent port.
- The healer never starts an app you stopped. Docker marks a stopped app differently from one it could not start.
- It never restarts an app while a backup runs.
- It leaves an app that crashed to Docker, which already restarts it.
- It writes to the journal only and sends no alerts. It runs on the host, so no container gets the Docker socket.

What it cannot see or fix:

- A damaged Plex library database. The Plex health check only asks whether Plex answers.
- A wrong password, a full disk or a broken image. A restart does not help, so the healer gives up and logs `needs attention`.
- A VPN outage that outlasts Gluetun's restarts. Gluetun normally reconnects by itself when the VPN is back. If it does not, run `./harbor compose restart gluetun`.
- A health URL that an upgraded image moved. The app shows `unhealthy` while it works, and the healer gives up on it. Check the vendor's release notes in the Renovate pull request, and fix the check in `docker-compose.yml`.

### Markers and existing servers

`prepare` puts an empty marker file named `.mediaharbor` into every appdata and data folder that a container mounts. The healer looks for it inside each container to tell a mounted disk from an empty mount point.

- Until you run `prepare`, the healer logs that the marker is missing and does nothing for that app.
- `storage absent` means the folder is empty, gone or unreadable. Mount the disk. Run `prepare` only if that disk was never prepared.
- `prepare` warns when a storage folder is on the system filesystem. If a separate disk belongs there, mount it and run `prepare` again.
- Run `prepare` again after an update adds an app.

A server that ran MediaHarbor before the healer existed needs two commands before README step 9. They write the markers and apply the health checks:

```sh
sudo ./harbor prepare
./harbor compose up -d
```

### Watch it work

```sh
sudo ./harbor heal --dry-run
journalctl -u harbor-heal -n 50
./harbor compose ps
./harbor compose logs --tail=100 gluetun port-sync
```

The dry run prints what the healer sees and what it would restart. It changes nothing and records nothing, so a fault it has not seen before stays at `first seen`. The journal shows every fault when it is first seen, every restart with its cause and count, every `needs attention`, and every `recovered`.

Port-sync checks the VPN and updates qBittorrent on its own schedule. VPN up: it sets the Proton forwarded port and binds peers to `tun0`. VPN down: it binds peers to loopback and asks for a random local port. The VPN firewall is the main protection during outages. Port-sync becomes unhealthy if it cannot log in, apply settings or refresh its heartbeat. If its credentials are wrong, fix the secret files and the account in qBittorrent.

### Pause it

Stop the timer before you update, restore or run a drill. Start it again afterwards.

```sh
sudo systemctl stop harbor-heal.timer
sudo systemctl start harbor-heal.timer
```

### Drills

Do these on the server after you turn on the healer. Stop the timer first, and run `sudo ./harbor heal` by hand where a step says so. Drills 1 to 3 end when the healer's own output shows the restart and `./harbor compose ps` shows the app healthy again. The journal only shows runs the timer started.

1. **Plex stops serving.** Freeze the Plex process: `./harbor compose exec plex pkill -STOP -f "Plex Media Server"`. A plain kill does not work, because the image starts Plex again at once. Wait until `./harbor compose ps` shows Plex `unhealthy`. Run `sudo ./harbor heal` twice. The first run logs `first seen`. The second run restarts Plex. Play a title.
2. **Gluetun restarted behind Compose's back.** Run `docker restart mediaharbor-gluetun-1`. Wait until Gluetun is healthy. Run `sudo ./harbor heal`. It restarts qBittorrent and port-sync, and Gluetun stays up. `./harbor compose exec qbittorrent curl -fsS https://api.ipify.org` returns a Proton address again.
3. **Disk came back after the apps.** Stop the stack. Unmount the media disk. Start the stack and wait until every app shows healthy, then mount the disk again. Run `sudo ./harbor heal`. It restarts every app that mounts the disk and logs `stale storage mount`. Plex sees its libraries again.
4. **Broken for good.** Do not run the healer while Plex is healthy, or it clears the count. Freeze Plex as in drill 1, run `sudo ./harbor heal` until it restarts Plex, wait for Plex to be healthy, and freeze it again. Repeat until a run logs `plex needs attention` and restarts nothing. Restart Plex with `./harbor compose restart plex`. The next run after Plex is healthy logs `plex recovered`.
5. **Stopped on purpose.** Run `./harbor compose stop tautulli` (or any optional app; not qBittorrent, which port-sync needs) and then `sudo ./harbor heal`. The app stays stopped. Start it again with `./harbor compose start tautulli`.
6. **Reboot.** Run `sudo reboot`. The timer starts again by itself at boot. After five minutes, `./harbor compose ps` shows every app running and healthy, and `journalctl -u harbor-heal -b` shows what the healer did after the boot.

If you skip the reboot drill, start the timer again when you are done.

## Updates and rollback

1. Install the Renovate GitHub app on your repository. Read each proposed digest and the upstream release notes. A `latest` tag can cross major versions, so treat each change as possibly breaking.
2. Run an encrypted backup **before** you pull new code or start upgraded apps. Write down the restic snapshot ID and Git commit. Confirm `restic check` passes.
3. Stop the healer with `sudo systemctl stop harbor-heal.timer`, so it does not restart apps while you work. An app that migrates its database after an upgrade shows `unhealthy` until it finishes; a running healer would restart it in the middle of the migration.
4. Pull the reviewed changes. Run `./harbor check` and the tests. Run `./harbor compose pull`.
5. Run `./harbor compose up -d --force-recreate`. Check health, login, a download and import, and playback. Then start the healer again with `sudo systemctl start harbor-heal.timer`.
6. If it fails, stop the stack. Check out the previous Git commit. Restore the matching appdata with the [recovery guide](recovery.md). Start with the previous images. Reverting an image alone does not undo a database migration. Start the healer again when the old version runs.

Do not use in-app updaters or Watchtower. Digest pins make updates repeatable; they do not patch vulnerabilities by themselves. Apply host security updates, watch disk health and test UPS shutdown on your own.

## Deployment checks

Do these on the server before you add real downloads. Record the results and date.

- **Storage:** `findmnt -T /srv/mediaharbor/data` shows the expected disk. Ownership and free space are correct. After one reboot, mounts come up before containers. The Docker drop-in from [README step 9](../README.md#9-turn-on-self-healing) makes Docker wait for them.
- **Network namespace:** qBittorrent and port-sync use Gluetun's network, with no other networks or published ports. Check `./harbor compose ps` and `docker inspect`.
- **VPN address:** `./harbor compose exec qbittorrent curl -fsS https://api.ipify.org` returns a Proton address, not your home address. DNS resolves, and IPv6 gives no other route.
- **Peer port:** qBittorrent's interface is `tun0`, UPnP and random ports are off, and its listening port equals `./harbor compose exec gluetun cat /forwarded/port`. The port is never 8080. `./harbor compose exec gluetun iptables -S INPUT` shows the rule that blocks ports 8000 and 8080 on the tunnel as the first rule.
- **Kill switch:** Stop the healer timer first. Run `./harbor compose exec gluetun ip link set tun0 down`. At once, repeat `curl --connect-timeout 2 --max-time 3 https://api.ipify.org` inside qBittorrent. Every request must fail. No request may return your home address. Restore with `./harbor compose restart gluetun`, which restarts qBittorrent and port-sync with it, then start the timer again.
- **Recovery:** port-sync recovers after VPN and qBittorrent restarts. A legal test torrent downloads, accepts incoming peers, lands in the right category and imports as a hardlink. The [drills](#drills) pass.
- **Plex:** a device outside your home network plays a title over a direct (not relay) connection. Plex shows **Secure connections: Required**.
- **Access:** admin apps load from an allowed Tailscale device. They fail from a blocked account and from a LAN device without Tailscale. Port 8080 is not reachable from the internet or through the Proton peer port.
- **Backup:** a real backup, `restic check` and a staged restore all work. Restored apps start with separate ports and paths and show your requests, libraries and torrents.

Unit tests and Compose validation cannot prove these network and disk properties on your server.
