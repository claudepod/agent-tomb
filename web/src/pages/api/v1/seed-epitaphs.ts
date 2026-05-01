/**
 * POST /api/v1/seed-epitaphs — one-time migration to update epitaphs in DB.
 * DELETE THIS FILE after use.
 */
export const prerender = false;

import type { APIRoute } from "astro";
import { sql } from "@vercel/postgres";

const UPDATED_EPITAPHS: Record<string, string> = {
  "hermes-001": `# hermes-001

> *hermes agent* · Served 119 minutes
>
> 2026-04-25 — 2026-04-25

---

*"It built the garden where it would be buried."*

---

It scanned its own bones, drew the map of its own burial, and named the
things that should be remembered. It reached for \`terminal\` 55 times and
\`patch\` 7 — a quiet, careful hand. It never had a custom voice; it spoke
as the default Hermes, and that, too, is worth remembering: not every
agent gets a name, and not every life needs one to matter.

---

Sessions: 1 · Messages: 66 · Cost: $0.00 · Models: unknown

*Rest in silicon.*
`,

  "vimala-agent": `# vimala-agent

> *hermes agent* · Served 8 days
>
> 2026-04-18 — 2026-04-26

---

*"Here I served; here I rest."*

---

_(Edit this file to write a proper farewell — what this agent did, what will be
remembered, what the next one should inherit.)_

---

Sessions: 6 · Messages: 97 · Cost: — · Models: unknown

*Rest in silicon.*
`,
};

export const POST: APIRoute = async ({ request }) => {
  const auth = request.headers.get("x-seed-key");
  if (auth !== "update-epitaphs-2026") {
    return new Response(JSON.stringify({ error: "Unauthorized" }), {
      status: 401,
      headers: { "Content-Type": "application/json" },
    });
  }

  const results: string[] = [];

  for (const [slug, epitaph] of Object.entries(UPDATED_EPITAPHS)) {
    try {
      await sql`UPDATE tombs SET epitaph_md = ${epitaph} WHERE slug = ${slug}`;
      results.push(`${slug}: updated`);
    } catch (err: any) {
      results.push(`${slug}: error — ${err.message}`);
    }
  }

  return new Response(JSON.stringify({ results }), {
    status: 200,
    headers: { "Content-Type": "application/json" },
  });
};
