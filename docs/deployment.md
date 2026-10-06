# Deploying Folio with Portainer

CI builds the image on every green push to `main` and publishes it to the GitHub Container Registry as `ghcr.io/freakadude/portfolio-tracker` (tags `latest` and `sha-<commit>`; the System page shows the commit). Portainer pulls that image, so nothing is built on the Docker LXC and no `.env` file is needed there.

## One-time setup

1. **Make the image public.** The package has its own visibility, separate from the repository's, and it is not on the repository's settings page: open https://github.com/users/Freakadude/packages/container/portfolio-tracker/settings (or your profile, Packages, `portfolio-tracker`, Package settings), Danger Zone, Change visibility, Public. The image holds Folio's code but no secrets or data. A private image with a token in Portainer's Registries did not work: Portainer's connection test asks for write access, and even with it the stack's pull went out without the login ("unauthorized").
2. **Create the stack.** Portainer, Stacks, Add stack, Repository: `https://github.com/Freakadude/Portfolio-Tracker`, reference `refs/heads/main`, compose path `docker-compose.yml`. Or use the Web editor and paste the file.
3. **Set the environment variables** in the stack's panel:

   | Variable | Value |
   | --- | --- |
   | `FOLIO_SECRET_KEY` | required, 32 or more characters; make one with `uv run folio init` on your computer and copy it. Keep a copy in your password manager: without it the stored API keys cannot be read |
   | `FOLIO_LAN_IP` | required, the LXC's LAN address; the app is published on that interface only |
   | `FOLIO_WEB_PORT` | optional, the port Folio is reachable on; default 8555 |
   | `FOLIO_BASE_URL` | optional, for example `http://192.168.1.10:8555`, so a notification opens Folio |
   | `FOLIO_TZ`, `FOLIO_LOG_LEVEL`, `FOLIO_EXTRA_BACKUP_DIR` | optional |
   | `FOLIO_TAILSCALE_USER`, `FOLIO_TRUSTED_PROXIES` | optional, both or neither: sign in through Tailscale Serve (see below) |
   | `FOLIO_IMAGE` | optional, to pin a build, for example `ghcr.io/freakadude/portfolio-tracker:sha-<commit>` |

4. Deploy, open `http://<FOLIO_LAN_IP>:8555/healthz`, then finish the setup wizard.

Data lives in the `folio-data` volume (database and backups). Do not delete the volume when you remove the stack.

## Updating

When CI is green on `main`, open the stack in Portainer and press "Update the stack" with "Re-pull image" switched on. Both containers (`web`, which migrates the database on start, and `worker`) restart on the new image. Every service has `pull_policy: always`, so a plain redeploy also pulls.

To go back, set `FOLIO_IMAGE` to an earlier `sha-` tag and update the stack. Take a backup first (`folio backup`, or the nightly one in the volume): a migration is not undone by an older image.

## Building on the host instead

`docker compose -f docker-compose.yml -f docker-compose.build.yml up --build` builds from the checkout.

## Not exposed to the internet

LAN or Tailscale only. Do not put it behind a publicly exposed reverse proxy.

## Signing in through Tailscale Serve (optional)

If you reach Folio through Tailscale Serve, it can pass your tailnet login to Folio so you do not type the password. It is off unless you set both variables:

- `FOLIO_TAILSCALE_USER`: the tailnet login that may sign in, for example `you@example.com`.
- `FOLIO_TRUSTED_PROXIES`: the address Tailscale Serve connects to Folio from, as Folio sees it. With Tailscale Serve on the LXC host and Folio in a container, that is the Docker network's gateway, often `172.18.0.1` (`docker network inspect` on the stack's network shows its Gateway). A range such as `172.18.0.0/16` works too.

The login page then shows "Sign in through Tailscale" when the request really comes through Tailscale Serve as that user. Anyone else who reaches Folio directly can write the same header, so Folio ignores it unless the connection comes from the address you listed; do not list an address that other people or devices can use to reach Folio. A tailnet sign-in does not ask for the two-factor code (the device was already identified by the tailnet); the password and the code still work as before. A typo in `FOLIO_TRUSTED_PROXIES` stops the web container from starting, with a message.
