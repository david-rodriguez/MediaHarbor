# Portainer stacks

This guide is optional. Use it if you want Portainer to start, stop and update the apps. If you do not use Portainer, use `./harbor compose` as the [README](../README.md#set-it-up) shows.

Use one method only. Do not start the apps with Portainer and with `./harbor compose up` at the same time.

## How it works

Portainer runs Compose inside its own container. That container cannot see this repository. It can see the host's files through Docker.

The stack still needs files from the repository on the host: `secrets/`, `config/gluetun/post-rules.txt` and `scripts/port_sync.py`. Set `HARBOR_ROOT` to the host folder of your clone. Compose then loads those files from that folder. If you do not set `HARBOR_ROOT`, Compose uses the folder of the Compose file.

## Set it up

1. Do steps 1 to 4 of the [README setup](../README.md#set-it-up).
2. In `config/host.env`, remove the `#` in front of `HARBOR_ROOT=/opt/mediaharbor`.
3. In Portainer, open **Stacks > Add stack**.
4. Set the name to `mediaharbor`. You must use this name. `./harbor backup` finds the containers by this name.
5. Select one build method:
   - **Repository:** your repository URL, reference `refs/heads/main`, Compose path `docker-compose.yml`.
   - **Web editor:** paste the contents of `docker-compose.yml`.
6. Under **Environment variables**, select **Load variables from .env file** and pick your `config/host.env`.
7. Get a Plex claim token from <https://plex.tv/claim> and put it in `secrets/plex_claim`. The token expires in 4 minutes. Select **Deploy the stack** at once.
8. Do README steps 5 to 8, but skip each `./harbor compose up` command. Portainer already started the apps. If the Plex token expired, put a new token in `secrets/plex_claim` and restart the `plex` container in Portainer.

Compose can log `secret file ... does not exist`. This warning comes from inside the Portainer container, and you can ignore it. If a container fails to start, make sure `HARBOR_ROOT` is an absolute path and that the files exist on the host.

## Keep things in sync

Portainer and `./harbor` must use the same settings.

- **Settings:** when you change a variable in Portainer, make the same change in `config/host.env`. `./harbor backup` reads that file.
- **Updates:** run `git pull` in `/opt/mediaharbor` first. Then update the stack in Portainer: **Pull and redeploy** for the Repository method, or paste the new file for the Web editor method. Follow [updates and rollback](operations.md#updates-and-rollback) for the backup and checks.
- **Edits in Portainer:** `./harbor check` does not see changes that you make only in the web editor. Make changes in the repository and run `./harbor check`.

These commands still work from `/opt/mediaharbor`: `check`, `prepare`, `backup`, `restore` and `export-secrets`. Use `./harbor compose` only to read, for example `ps`, `logs` and `exec`.

Reboots work the same as without Portainer. See [routine checks](operations.md#routine-checks).
