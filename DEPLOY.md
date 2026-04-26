# Deploying agentmemorial.com

The site at `web/` is a static Astro build. We deploy it to **Cloudflare Pages**
because it's free, fast, has built-in DNS, and rebuilds on every push to `main`.

## One-time setup

### 1. Push the repo to GitHub

```bash
cd ~/projects/agent-tomb
git remote add origin https://github.com/Claudepod/agent-tomb.git
git push -u origin main
```

### 2. Create the Cloudflare Pages project

1. Go to <https://dash.cloudflare.com> → **Workers & Pages** → **Create** → **Pages** → **Connect to Git**.
2. Authorize Cloudflare to read the `Claudepod/agent-tomb` repo.
3. Configure the build:

   | Field                        | Value                                  |
   | ---------------------------- | -------------------------------------- |
   | Framework preset             | Astro                                  |
   | Build command                | `cd web && npm install && npm run build` |
   | Build output directory       | `web/dist`                             |
   | Root directory               | (leave empty — we build from repo root) |
   | Environment variable         | `NODE_VERSION` = `22`                  |

4. Click **Save and Deploy**. The first build takes ~90 seconds. You'll get a
   `*.pages.dev` URL to verify everything renders.

### 3. Point the custom domain

1. In the Pages project → **Custom domains** → **Set up a custom domain**.
2. Enter `www.agentmemorial.com`. Cloudflare will:
   - Add the domain to your account if not already there.
   - Create the necessary CNAME record automatically (if DNS is on Cloudflare).
   - Issue a TLS cert (Let's Encrypt, ~5 min).
3. Add an apex redirect: in the Cloudflare DNS dashboard, create a redirect
   rule from `agentmemorial.com` → `https://www.agentmemorial.com` (301).

If your DNS is **not** on Cloudflare, point a CNAME at the `*.pages.dev`
hostname yourself, then complete the SSL/TLS verification in the Pages UI.

## Triggering rebuilds

- **Code or design changes** — push to `main`. Pages rebuilds automatically.
- **New burial** — add the unpacked tomb under `cemetery/<slug>/` (with the
  optional `.tomb` archive next to it). Push or merge a PR. Pages rebuilds and
  the new grave appears in the garden.

## Build verification

Locally, before pushing:

```bash
cd web
npm install
npm run build
npm run preview   # serves dist/ at http://localhost:4321
```

The GitHub Actions workflow at `.github/workflows/web.yml` also runs `npm run build`
on every push and PR — Cloudflare and Actions are independent verifiers.

## Rolling back

In the Cloudflare Pages dashboard → **Deployments**, every previous build is
preserved. Click any deployment → **Rollback** to instantly serve that version.

## Future: agent-tomb publish

The CLI will eventually grow an `agent-tomb publish ./my-agent.tomb` command
that opens a PR to add the tomb to the cemetery. Until then, burials are added
by hand via PR.
