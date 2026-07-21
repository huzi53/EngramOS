# VPS graduation runbook

**Trigger:** laptop uptime is actually hurting you (missed backups, captures lost while
the laptop was off/asleep/traveling without you). Not before — the laptop-first setup
is €0/mo and good enough until this is a real problem (plan.md M0 decision).

This is an afternoon move, not a rewrite: the app, DB schema, auth, and backup/restore
scripts are hosting-agnostic and don't change.

## Steps

1. **Provision.** Spin up a Hetzner CX22 (or equivalent) with the Docker-preinstalled
   image. `git clone` this repo onto it, `cp .env.example .env`, and fill in the same
   secrets you used on the laptop.

2. **Domain (deferred until now).** Buy one on Cloudflare Registrar, turn on account
   2FA, add an A-record pointing at the VPS IP. This is the point where the pre-M0
   steps that v1.4 originally had happen — they were deferred to graduation, not cut.

3. **Re-enable public HTTPS.** Add back to `.env`:
   ```
   DOMAIN=engram.example.com
   ACME_EMAIL=you@example.com
   ```
   Swap the Caddyfile back to the ACME variant:
   ```
   {$DOMAIN} {
       tls {$ACME_EMAIL}
       reverse_proxy api:8000
   }
   ```
   In `docker-compose.yml`, restore on the `caddy` service:
   ```yaml
   ports:
     - "80:80"
     - "443:443"
   volumes:
     - ./Caddyfile:/etc/caddy/Caddyfile:ro
     - caddy_data:/data
     - caddy_config:/config
   ```
   and add `caddy_data:` / `caddy_config:` back under the top-level `volumes:` block.
   `tailscale serve` is no longer needed for public access (though Tailscale still works
   fine for admin SSH-over-tailnet if you want it).

4. **Migrate data.** Pick one:
   - (a) `pg_dump` on the laptop → `psql` restore on the VPS, or
   - (b) since backups already go to B2, run `scripts/restore.sh` on the VPS pointed at
     the same `RESTIC_REPOSITORY` — restic just needs the same env, no repo move.

5. **Re-point scheduling.** The VPS is Linux, so backups move from Windows Task
   Scheduler back to a host crontab:
   ```
   0 3 * * *  cd /opt/engram && ./scripts/backup.sh >> /var/log/engram-backup.log 2>&1
   ```

6. **Cut over.** `docker compose up -d` on the VPS, verify `https://$DOMAIN/health`,
   then stop the laptop stack.
