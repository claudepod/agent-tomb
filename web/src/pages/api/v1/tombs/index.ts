/**
 * GET /api/v1/tombs — list live tombs.
 */
export const prerender = false;

import type { APIRoute } from "astro";
import { ensureSchema, listTombs } from "../../../../lib/db";

export const GET: APIRoute = async ({ url }) => {
  await ensureSchema();

  const limit = Math.min(Number(url.searchParams.get("limit") || 50), 200);
  const offset = Math.max(Number(url.searchParams.get("offset") || 0), 0);

  const { tombs, total } = await listTombs(limit, offset);

  const items = tombs.map((t) => ({
    slug: t.slug,
    name: t.name,
    framework: t.framework,
    created_at: t.created_at,
    published_at: t.published_at,
    agent_tomb_version: t.agent_tomb_version,
    session_count: t.session_count,
    message_count: t.message_count,
    lifespan_days: t.lifespan_days,
    estimated_cost_usd: t.estimated_cost_usd,
    first_at: t.first_at,
    last_at: t.last_at,
    models: safeJsonParse(t.models, []),
    platforms: safeJsonParse(t.platforms, []),
  }));

  return new Response(JSON.stringify({ tombs: items, total, limit, offset }), {
    headers: { "Content-Type": "application/json" },
  });
};

function safeJsonParse(v: any, fallback: any) {
  if (typeof v !== "string") return fallback;
  try { return JSON.parse(v); } catch { return fallback; }
}
