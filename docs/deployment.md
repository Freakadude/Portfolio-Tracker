# Deploying Folio with Portainer

CI builds the image on every green push to `main` and publishes it to the GitHub Container Registry as `ghcr.io/freakadude/portfolio-tracker` (tags `latest` and `sha-<commit>`; the System page shows the commit). Portainer pulls that image, so nothing is built on the Docker LXC and no `.env` file is needed there.

## One-time setup

1. **Let Portainer pull the image.** The repository is private, so its image is too. In GitHub, create a personal access token (classic) with only the `read:packages` scope (Settings, Developer settings). In Portainer, Registries, Add registry, Custom registry: URL `ghcr.io`, your GitHub user name, the token as the password. Enter the token in Portainer only; never in a file or a chat. (If you would rather not use a token, make the package public in GitHub, Packages, Package settings. The image contains no secrets, but it is your choice.)
2. **Create the stack.** Portainer, Stacks, Add stack, Repository: `https://github.com/Freakadude/Portfolio-Tracker`, reference `refs/heads/main`, compose path `docker-compose.yml` (for a private repository add your GitHub credentials there too). Or use the Web editor and paste the file.
3. **Set the environment variables** in the stack's panel:

   | Variable | Value |
   | --- | --- |
   | `FOLIO_SECRET_KEY` | required, 32 or more characters; make one with `uv run folio init` on your computer and copy it. Keep a copy in your password manager: without it the stored API keys cannot be read |
   | `FOLIO_LAN_IP` | required, the LXC's LAN address; the app is published on that interface only |
   | `FOLIO_BASE_URL` | optional, for example `http://192.168.1.10:8080`, so a notification opens Folio |
   | `FOLIO_TZ`, `FOLIO_LOG_LEVEL`, `FOLIO_EXTRA_BACKUP_DIR` | optional |
   | `FOLIO_IMAGE` | optional, to pin a build, for example `ghcr.io/freakadude/portfolio-tracker:sha-<commit>` |

4. Deploy, open `http://<FOLIO_LAN_IP>:8080/healthz`, then finish the setup wizard.

Data lives in the `folio-data` volume (database and backups). Do not delete the volume when you remove the stack.

## Updating

When CI is green on `main`, open the stack in Portainer and press "Update the stack" with "Re-pull image" switched on. Both containers (`web`, which migrates the database on start, and `worker`) restart on the new image. Every service has `pull_policy: always`, so a plain redeploy also pulls.

To go back, set `FOLIO_IMAGE` to an earlier `sha-` tag and update the stack. Take a backup first (`folio backup`, or the nightly one in the volume): a migration is not undone by an older image.

## Building on the host instead

`docker compose -f docker-compose.yml -f docker-compose.build.yml up --build` builds from the checkout.

## Not exposed to the internet

LAN or Tailscale only. Do not put it behind a publicly exposed reverse proxy.
