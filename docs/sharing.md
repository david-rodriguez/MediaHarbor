# Share with friends and family

Sharing has three parts:

- **Watch**: friends stream your library in their own Plex apps.
- **Request**: friends ask for new titles in Seerr, or add them to their Plex Watchlist.
- **Listen**: friends play your audiobooks in the Audiobookshelf app.

## Let friends watch

1. In Plex, open **Settings > Remote Access** and turn it on. Choose **Manually specify public port** and enter `32400`.
2. On your router, forward TCP port 32400 to this server. Without the forward, Plex uses its relay, which limits quality.
3. In **Settings > Network**, set **LAN Networks** to your home subnet, for example `192.168.1.0/24`. Plex runs in a Docker network, so without this it treats home devices as remote.
4. Set **Secure connections** to **Required**.
5. Open Plex's library access settings and invite each person by email or Plex username. Choose which libraries they can see.

Friends then open Plex on any device and see your server.

## Let friends request

Seerr uses Plex accounts, so friends do not need a new password.

1. In Seerr, open **Settings > Users**. Turn on **Enable Plex Sign-In**.
2. Set **Default Permissions** for new users. A good start is **Request** plus **Auto-Request Movies** and **Auto-Request Series**.
3. Optional: set request limits per user, and choose whether requests need your approval.
4. Open **Users > Import Plex Users** to add everyone who has library access.

### Watchlist auto-requests

With **Auto-Request** permission, anything a friend adds to their Plex Watchlist becomes a Seerr request.

1. Each friend signs in to Seerr with Plex **once**. Seerr needs that sign-in to read their Watchlist.
2. Each friend opens their Seerr profile and turns on **Auto-Request**.
3. After that, they only use the Watchlist in their Plex app.

Limits:

- Auto-requests are standard quality only. 4K needs a manual request.
- Local Seerr accounts cannot use Watchlists. Only Plex sign-ins can.
- If a friend's Plex session in Seerr expires, auto-requests pause. They sign in again to resume.

## Give friends private access to Seerr

Seerr is not on the public internet. Share it through Tailscale:

1. In the Tailscale admin console, open **Machines**, select this server and choose **Share**.
2. Send the invite link. The friend installs Tailscale and accepts the invite.
3. The friend opens `https://YOUR-SERVER-NAME` (the Seerr Serve mapping from [access](access.md)).

A shared user can only reach the one machine you share. Limit them to Seerr's port too, in your tailnet policy file. Replace the IP with this server's Tailscale IP:

```json
{
  "hosts": {
    "mediaharbor": "100.x.y.z"
  },
  "grants": [
    { "src": ["autogroup:shared"], "dst": ["mediaharbor"], "ip": ["tcp:443"] }
  ]
}
```

Keep this rule next to your admin rules from [access](access.md). Remove any broad "allow all" rule, because a narrow rule does not override a broad one. Test with a friend's account: Seerr must load, and `https://YOUR-SERVER-NAME:8989` must fail.

Do not use Tailscale Funnel or a router port forward for Seerr or the admin apps.

## Let friends listen to audiobooks

Audiobookshelf has its own accounts. It does not use Plex sign-in.

1. In Audiobookshelf, open **Settings > Users** and add a user for each friend. Give them access to the audiobook library only.
2. Add `"tcp:13378"` to the `autogroup:shared` grant above.
3. The friend installs the Audiobookshelf app and signs in with `https://YOUR-SERVER-NAME:13378`.
