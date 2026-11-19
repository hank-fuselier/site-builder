# Site Builder

A small web app for building websites for customers who don't have one.

1. **Interview**: record what the business does, services, tone, pages, contact info.
2. **Collateral**: upload scans or photos of cards, flyers, brochures. Brand colors are pulled out automatically, and Claude can read the scans for services, phone, hours and style.
3. **Brand**: use the scanned colors, or get three suggested color schemes, font pairs and text logos.
4. **Domain**: enter the domain they own, or get suggested names with a live availability check (RDAP).
5. **Website**: Claude writes a complete multi-page site in their brand. Revise it with plain-English instructions, edit content directly, roll back versions, or download it as static HTML.

Each site has a shareable preview link at `PUBLIC_BASE_URL/s/<customer>/`. Once a customer's domain points at the server, the same site is served at that domain (with automatic HTTPS when using the Caddy profile). Contact-form messages show up under **Leads**.

## Run it

```bash
cp .env.example .env      # set ADMIN_PASSWORD, ANTHROPIC_API_KEY, PUBLIC_BASE_URL
docker compose up -d --build
```

Open `PUBLIC_BASE_URL/admin` and sign in with ADMIN_USER / ADMIN_PASSWORD.

**Ports 80/443 free and you want automatic HTTPS for customer domains?** Set `SITE_HOST` and `ACME_EMAIL` in `.env`, then:

```bash
docker compose --profile caddy up -d --build
```

**Already running nginx/Caddy for something else?** Use the app-only mode and proxy a hostname to `127.0.0.1:8080`. If that proxy runs in Docker, copy `docker-compose.override.example.yml` to `docker-compose.override.yml` and set the proxy's network name; the proxy then reaches the app at `site-builder-app:8080`. For customer domains, add them to that proxy too (the app picks the site from the `Host` header).

### Without Docker

```bash
python3 -m venv .venv && . .venv/bin/activate
pip install -r requirements.txt
set -a; . ./.env; set +a
uvicorn app.main:app --host 0.0.0.0 --port 8080
```

## Moving to another server

Everything lives in `./data` (SQLite database, uploads, Caddy certificates) and `.env`.

```bash
docker compose down
rsync -a site-builder/ newhost:site-builder/     # or: git clone + copy data/ and .env
ssh newhost 'cd site-builder && docker compose up -d --build'
```

Then update `PUBLIC_BASE_URL` (and `SITE_HOST`) and point customer domains' DNS at the new IP.

## Customer domain DNS

At the registrar, add `A` records for `@` and `www` pointing to the server's public IP.
