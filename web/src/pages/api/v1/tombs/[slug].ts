/**
 * GET /api/v1/tombs/:slug — get a single tomb with full content.
 */
export const prerender = false;

import type { APIRoute } from "astro";
import { ensureSchema, getTomb } from "../../../../lib/db";

export const GET: APIRoute = async ({ params }) => {
  await ensureSchema();

  const tomb = await getTomb(params.slug!);
  if (!tomb) {
    return new Response(JSON.stringify({ error: "Tomb not found." }), {
      status: 404,
      headers: { "Content-Type": "application/json" },
    });
  }

  return new Response(
    JSON.stringify({
      slug: tomb.slug,
      name: tomb.name,
      framework: tomb.framework,
      created_at: tomb.created_at,
      published_at: tomb.published_at,
      agent_tomb_version: tomb.agent_tomb_version,
      session_count: tomb.session_count,
      message_count: tomb.message_count,
      lifespan_days: tomb.lifespan_days,
      estimated_cost_usd: tomb.estimated_cost_usd,
      first_at: tomb.first_at,
      last_at: tomb.last_at,
      models: safeJsonParse(tomb.models, []),
      platforms: safeJsonParse(tomb.platforms, []),
      epitaph_md: tomb.epitaph_md,
      soul_md: tomb.soul_protected ? null : tomb.soul_md,
      soul_protected: tomb.soul_protected ?? false,
      soul_enc: tomb.soul_enc ?? null,
      stats: safeJsonParse(tomb.stats_json, {}),
    }),
    { headers: { "Content-Type": "application/json" } },
  );
};

function safeJsonParse(v: any, fallback: any) {
  if (typeof v !== "string") return fallback;
  try { return JSON.parse(v); } catch { return fallback; }
}
