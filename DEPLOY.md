# Deploying agentmemorial.com

The site at `web/` is a static Astro build. Either **Vercel** or **Cloudflare
Pages** works — pick one.

- **Vercel** is the smoothest for Astro out of the box and is preferred when
  the project owner already has a Vercel account. Section below.
- **Cloudflare Pages** is a fine alternative; section further down.

---

## Option A — Vercel

### 1. Push the repo to GitHub (one-time)

Already done if `git remote -v` shows `origin → github.com/Claudepod/agent-tomb`.

### 2. Import the project

1. <https://vercel.com/new> → pick the GitHub repo `Claudepod/agent-tomb`.
2. **Root Directory**: click *Edit* and set to `web`. (Astro lives in a
   subfolder; the rest of the repo — including `cemetery/` — is still cloned
   so the build script can read it.)
3. **Framework preset**: Astro (auto-detected).
4. **Build & Output**: leave defaults. Vercel reads `web/package.json` and
   runs `npm run build`, producing `web/dist`.
5. **Environment variables**: none needed.
6. **Project Settings → General → Node.js Version**: set to `22.x` to match
   `.nvmrc`.
7. Deploy. The first build takes ~60 seconds and gives you a
   `agent-tomb-<hash>.vercel.app` URL — open it to verify the garden renders
   and `/cemetery/hermes-001/` shows the seed grave.

### 3. Add the custom domain

1. Project → **Settings → Domains** → add `www.agentmemorial.com` (set as
   primary) and `agentmemorial.com` (Vercel will auto-redirect to www).
2. Vercel will show you the exact DNS records to create. Typically:

   | Host | Type  | Value                     |
   | ---- | ----- | ------------------------- |
   | `@`  | A     | `76.76.21.21`             |
   | `www`| CNAME | `cname.vercel-dns.com`    |

### 4. GoDaddy DNS

1. <https://dcc.godaddy.com> → My Products → **DNS** next to
   `agentmemorial.com`.
2. Delete or edit the default `Parked` records (the auto-created `A @ → ParkedIP`
   and the `CNAME www → @`).
3. Add the two records Vercel gave you (above table). Save.
4. Propagation usually finishes in 5–30 minutes; check
   <https://dnschecker.org/#A/agentmemorial.com>.
5. Back in Vercel, the domain status will flip from **Invalid Configuration**
   to **Valid Configuration** automatically — TLS certs issue within a minute
   after that.

### 5. Triggering rebuilds

- Push to `main` → Vercel rebuilds automatically.
- New burial: add unpacked tomb under `cemetery/<slug>/` (and the optional
  `.tomb` next to it) → push → site rebuilds. CI (`web.yml`) also validates
  the cemetery on every PR independently.

### Rollbacks

Project → **Deployments** → any previous deployment → **Promote to Production**.

---

## Option B — Cloudflare Pages

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
