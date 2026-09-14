# Changelog

All notable changes to this project are documented in this file.
The format follows [Keep a Changelog](https://keepachangelog.com/en/1.1.0/), and this project uses [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

### Added

- Optional audiobooks: Bookshelf finds and downloads them, Audiobookshelf plays them.
- Optional Portainer stack deployment. Set `HARBOR_ROOT` to the host clone so the stack finds `secrets/`, the Gluetun rules and `port_sync.py`.
- `harbor check` fails while `config/host.env` or `secrets/` still hold a placeholder in square brackets, such as `[YOUR-TAILSCALE-NAME]`, and names the one to replace.

### Changed

- `config/host.env.example` turns on every optional app.
- License is now The Unlicense (public domain) instead of MIT. Third-party apps and images keep their own licenses.
- GitHub Actions use version tags instead of commit SHA pins.

### Fixed

- The Homepage dashboard has links for Lidarr and SABnzbd.
- The CI secret scan runs. Before, a shell quoting error stopped it.
- `port-sync` starts on current Compose releases. Before, Compose split its `/tmp` options at the comma and refused to create the container.

## [0.1.0] - 2026-09-13

### Added

- Docker Compose stack: Plex, Seerr, Sonarr, Radarr, Prowlarr, Bazarr, and qBittorrent behind Gluetun with Proton WireGuard.
- Optional profiles: Tautulli, Recyclarr, Unpackerr, FlareSolverr, Jellyfin, Lidarr, SABnzbd and Homepage.
- `harbor` CLI: `init`, `check`, `prepare`, `compose`, `backup`, `restore` and `export-secrets`.
- Authenticated qBittorrent port synchronization for Proton's forwarded port.
- Encrypted app backups with restic and encrypted credential export with age.
- Guides for private access, sharing with friends, operations and recovery.
- CI validation, a Git history secret scan and Renovate configuration.
