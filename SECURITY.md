# Security policy

## Report a vulnerability

Do not open a public issue for a security problem. Use GitHub's **Report a vulnerability** button on the repository's Security tab. Include the affected file, the steps to reproduce, and the impact. You get a reply as soon as possible.

## Scope

In scope:

- The Compose file, the `harbor` CLI and the scripts in this repository.
- Defaults that expose a service, leak a credential or bypass the VPN.

Out of scope:

- Vulnerabilities in the upstream images (Plex, Sonarr, qBittorrent and others). Report those to their projects.
- Setups that change the defaults, such as extra published ports or disabled app authentication.

## Security defaults

- Admin ports bind to `127.0.0.1`. Only Plex port 32400 is published to the network.
- qBittorrent traffic goes only through the Gluetun VPN firewall.
- No container gets the Docker socket.
- Images are pinned to registry digests. Updates are reviewed, not automatic.
- Credentials are ignored by Git and mounted as Compose secrets with mode `0600`.
- CI scans the full Git history for secrets.

Docker publishes ports with its own firewall rules, so host firewalls such as UFW do not filter port 32400. Keep Plex updated and set **Secure connections** to **Required**.
