# Backups and rebuilds

Three things need protection:

- **Git** holds the deployment.
- **Appdata** holds databases, app passwords, API keys, Plex settings and torrent resume data.
- **`config/host.env` and `secrets/`** hold host settings and credentials.

Back up all three. Media files and the host OS need their own protection.

## Recovery kit

Keep these in your password manager **and** an offline copy:

- Git repository URL
- age identity
- restic repository URL and password
- storage provider credentials
- disk layout and mount UUIDs
- media UID/GID
- Tailscale and Plex account recovery codes

Never keep the only decryption key next to its encrypted archive. `/etc/mediaharbor` and the host's Tailscale state are not in the app backup, so the kit is essential.

## Encrypted credentials in Git (optional)

Install age from its official packages. Make an identity on a trusted computer, outside the repository, and keep it in the recovery kit. Its public recipient starts with `age1`.

```sh
age-keygen -o /a/safe/location/mediaharbor.agekey
./harbor export-secrets age1YOUR_PUBLIC_RECIPIENT encrypted/bootstrap.tar.age
```

The export holds only `config/host.env` and `secrets/`, encrypted with age. It holds no app databases. It refuses to overwrite a file, and it writes the archive only after tar and encryption both succeed. You can commit the `.age` file. Export again after you change credentials or host settings.

To recover, decrypt into a private folder, list it, then extract:

```sh
umask 077
mkdir -p /srv/recovery/bootstrap
age -d -i /a/safe/location/mediaharbor.agekey -o /srv/recovery/bootstrap.tar encrypted/bootstrap.tar.age
tar -tf /srv/recovery/bootstrap.tar
tar -xf /srv/recovery/bootstrap.tar -C /srv/recovery/bootstrap
```

Copy the recovered `config/host.env` and `secrets/` into a fresh checkout. Delete the plaintext files when done. Never commit decrypted files.

## App backups with restic

Pick a destination off this server: SFTP, S3-compatible storage or another protected restic repository. A second folder on the same disk does not survive a disk failure.

Install restic on the host. Set these variables in your shell, or in a root-owned, mode `0600` file at `/etc/mediaharbor/backup.env` for systemd:

```text
RESTIC_REPOSITORY=sftp:backup-user@backup-host:/backups/mediaharbor
RESTIC_PASSWORD_FILE=/etc/mediaharbor/restic-password
```

Store the password in that file (mode `0600`) and in the recovery kit. For SFTP, verify the SSH host key and use a dedicated key. For S3, add its credentials the same way. Systemd does not load this file into your shell, so export the variables before you run the commands by hand. Run backups as root so every app folder is readable.

```sh
restic init
/opt/mediaharbor/harbor backup
restic snapshots --tag mediaharbor
restic check
```

Run `restic init` only once, to create the repository. `harbor backup` then:

1. Tests the repository before it stops anything.
2. Takes a local lock, so two backups cannot run together.
3. Stops the running services, so databases are consistent.
4. Backs up appdata, secrets, host settings and the deployment files.
5. Starts the same services again, even if the backup fails.

Apps are down while the backup uploads, so plan a quiet time. Plex metadata can be large; the first backup takes longest. If the process is killed, the machine shuts down or Docker fails, the apps may stay stopped: check them afterwards. Do not run updates during a backup.

Not in the backup: media and downloads in `DATA_ROOT`, `/etc/fstab`, Tailscale enrollment and `/etc/mediaharbor`. Protect those separately.

After a good manual backup and restore drill, install the nightly timer. Change `/opt/mediaharbor` in the unit if your checkout lives elsewhere.

```sh
sudo install -m 644 config/systemd/harbor-backup.service /etc/systemd/system/
sudo install -m 644 config/systemd/harbor-backup.timer /etc/systemd/system/
sudo systemctl daemon-reload
sudo systemctl enable --now harbor-backup.timer
systemctl list-timers harbor-backup.timer
journalctl -u harbor-backup.service
```

The timer sends no alerts, so check for failures. Nothing is pruned automatically. When you trust your backups, preview a retention policy:

```sh
restic forget --tag mediaharbor --keep-daily 7 --keep-weekly 4 --keep-monthly 12 --dry-run
```

Remove `--dry-run` and add `--prune` only when the result matches what you want. Keep a known-good snapshot from before each upgrade.

## Restore drill and full rebuild

1. Install Linux, mount the media disks in their usual places, and install Docker, Compose, Python, Tailscale, restic and age. Restore SSH and storage credentials from the kit.
2. Clone the Git commit that matches the snapshot. Do not start the apps yet. Export the restic variables. Run `restic snapshots --tag mediaharbor` and pick a snapshot ID.
3. Run `./harbor restore SNAPSHOT_ID /srv/recovery/restore`. The target folder must **not** exist. Restore never overwrites live appdata.
4. restic keeps the original absolute paths under the target. `/srv/mediaharbor/appdata` becomes `/srv/recovery/restore/srv/mediaharbor/appdata`, and `/opt/mediaharbor/secrets` becomes `/srv/recovery/restore/opt/mediaharbor/secrets`. Look before you copy.
5. With all apps stopped, copy appdata, `config/host.env` and `secrets/` into place with `sudo rsync -a` to keep ownership. Move old appdata aside first; never merge SQLite files. Fix paths in `host.env` if disks moved.
6. Run `./harbor check`, then `sudo ./harbor prepare`. Seerr needs UID/GID 1000; the other apps use your configured IDs. Repeat [README step 2](../README.md#2-set-up-tailscale) to enroll Tailscale and create the app links again. Then reapply the [access policy](access.md#limit-who-can-reach-the-server).
7. Start Gluetun and qBittorrent. Check the VPN. Then start the rest. Check requests, indexers, library paths, Plex playback and torrents. Record the snapshot ID and result.

`restic check` proves the repository is intact, not that the apps work. Only a real restore drill proves that.
