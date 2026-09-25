# Security policy

## Report a vulnerability

Do not open a public issue for a security problem. Use GitHub's **Report a vulnerability** button on the repository's Security tab. Include the affected file, the steps to reproduce, and the impact. You get a reply as soon as possible.

## Scope

In scope:

- The Compose file, the `harbor` CLI, the scripts and the systemd units in this repository.
- Defaults that expose a service, leak a credential or bypass the VPN.

Out of scope:

- Vulnerabilities in the upstream images (Plex, Sonarr, qBittorrent and others). Report those to their projects.
- Setups that change the defaults, such as extra published ports or disabled app authentication.

## Security defaults

The [security model](README.md#security-model) in the README lists the defaults this project promises. A default that does not hold is in scope.
