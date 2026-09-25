# Changelog

All notable changes to this project are documented in this file.
The format follows [Keep a Changelog](https://keepachangelog.com/en/1.1.0/), and this project uses [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

### Added

- Self-healing: the `harbor-heal` systemd timer runs `harbor heal`, which restarts an app that stops working. It also starts qBittorrent and port-sync when Docker could not start them before Gluetun. After a limited number of restarts it logs `needs attention` and stops. `harbor heal --dry-run` shows what it would do.
- A health check for every app that serves HTTP.
- A `docker.service` drop-in that makes Docker wait for the storage mounts at boot.
- `harbor prepare` writes a `.mediaharbor` marker file into every appdata and data folder a container mounts. The healer uses it to tell a mounted disk from an empty mount point. `prepare` warns when a storage folder is on the system filesystem. It refuses to run while a marker path is not a regular file.
- A fault-injection test on real Docker, run in CI.
- Optional audiobooks: Bookshelf finds and downloads them, Audiobookshelf plays them.
- Optional Portainer stack deployment. Set `HARBOR_ROOT` to the host clone so the stack finds `secrets/`, the Gluetun rules and `port_sync.py`.
- `harbor check` fails while `config/host.env` or `secrets/` still hold a placeholder in square brackets, such as `[YOUR-TAILSCALE-NAME]`, and names the one to replace.

### Changed

- README setup has a new step 9, "Turn on self-healing". "Before you download anything real" is now step 10.
- The operations guide replaces the by-hand Gluetun recreate with the healer, and the update steps stop the healer timer first.
- `config/host.env.example` turns on every optional app.
- License is now The Unlicense (public domain) instead of MIT. Third-party apps and images keep their own licenses.
- GitHub Actions use version tags instead of commit SHA pins.

### Fixed

- The Homepage dashboard has links for Lidarr and SABnzbd.
- The CI secret scan runs. Before, a shell quoting error stopped it.
- `port-sync` starts on current Compose releases. Before, Compose split its `/tmp` options at the comma and refused to create the container.
- The qBittorrent Tailscale link uses port 8080. qBittorrent answered `Unauthorized` on port 8443, because the port did not match its own.
- `harbor prepare` works with mounts that have no host folder, such as the `port-sync` `/tmp`. Before, it stopped with `KeyError: 'source'`.

## [0.1.0] - 2026-09-13

### Added

- Docker Compose stack: Plex, Seerr, Sonarr, Radarr, Prowlarr, Bazarr, and qBittorrent behind Gluetun with Proton WireGuard.
- Optional profiles: Tautulli, Recyclarr, Unpackerr, FlareSolverr, Jellyfin, Lidarr, SABnzbd and Homepage.
- `harbor` CLI: `init`, `check`, `prepare`, `compose`, `backup`, `restore` and `export-secrets`.
- Authenticated qBittorrent port synchronization for Proton's forwarded port.
- Encrypted app backups with restic and encrypted credential export with age.
- Guides for private access, sharing with friends, operations and recovery.
- CI validation, a Git history secret scan and Renovate configuration.
