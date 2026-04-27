/**
 * POST /api/v1/report/:slug — report a tomb for abuse.
 */
export const prerender = false;

import type { APIRoute } from "astro";
import {
  ensureSchema,
  getTomb,
  checkRateLimit,
  hashIP,
  insertReport,
  countDistinctReporters,
  flagTomb,
} from "../../../../lib/db";

const REPORT_RATE_LIMIT = 3;
const AUTO_FLAG_THRESHOLD = 3;

export const POST: APIRoute = async ({ params, request }) => {
  try {
    await ensureSchema();

    const slug = params.slug!;
    const tomb = await getTomb(slug);
    if (!tomb) {
      return json({ error: "Tomb not found." }, 404);
    }

    const clientIP =
      request.headers.get("x-forwarded-for")?.split(",")[0]?.trim() ||
      "unknown";
    const ipHash = await hashIP(clientIP);

    const allowed = await checkRateLimit(ipHash, "report", REPORT_RATE_LIMIT);
    if (!allowed) {
      return json({ error: "Rate limit exceeded." }, 429);
    }

    let body: { reason?: string; contact?: string };
    try {
      body = await request.json();
    } catch {
      return json({ error: "Invalid JSON body." }, 400);
    }

    if (!body.reason || body.reason.length < 5) {
      return json({ error: "Reason must be at least 5 characters." }, 400);
    }

    await insertReport(
      slug,
      body.reason.slice(0, 1000),
      body.contact?.slice(0, 200) ?? null,
      ipHash,
    );

    const reporters = await countDistinctReporters(slug);
    if (reporters >= AUTO_FLAG_THRESHOLD) {
      await flagTomb(slug);
    }

    return json({ reported: true });
  } catch (err: any) {
    console.error("Report error:", err);
    return json({ error: "Internal server error." }, 500);
  }
};

function json(data: any, status = 200) {
  return new Response(JSON.stringify(data), {
    status,
    headers: { "Content-Type": "application/json" },
  });
}
