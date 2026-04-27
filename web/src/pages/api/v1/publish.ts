/**
 * POST /api/v1/publish — accept a .tomb zip upload.
 */
export const prerender = false;

import type { APIRoute } from "astro";
import JSZip from "jszip";
import { validateTomb } from "../../../lib/validate";
import {
  ensureSchema,
  checkRateLimit,
  hashIP,
  slugExists,
  insertTomb,
} from "../../../lib/db";

const PUBLISH_RATE_LIMIT = 5;
const AUTO_FLAG_THRESHOLD = 3;

export const OPTIONS: APIRoute = async () => {
  return new Response(null, {
    status: 204,
    headers: {
      "Access-Control-Allow-Origin": "*",
      "Access-Control-Allow-Methods": "POST, OPTIONS",
      "Access-Control-Allow-Headers": "Content-Type",
    },
  });
};

export const POST: APIRoute = async ({ request }) => {
  try {
    await ensureSchema();

    // Rate limit
    const clientIP =
      request.headers.get("x-forwarded-for")?.split(",")[0]?.trim() ||
      request.headers.get("x-real-ip") ||
      "unknown";
    const ipHash = await hashIP(clientIP);

    const allowed = await checkRateLimit(ipHash, "publish", PUBLISH_RATE_LIMIT);
    if (!allowed) {
      return json({ error: "Rate limit exceeded. Try again later." }, 429);
    }

    // Parse multipart
    const formData = await request.formData();
    const file = formData.get("file");

    if (!(file instanceof File)) {
      return json({ error: "Missing 'file' field." }, 400);
    }

    if (!file.name.endsWith(".tomb")) {
      return json({ error: "File must have a .tomb extension." }, 400);
    }

    const arrayBuf = await file.arrayBuffer();
    if (arrayBuf.byteLength > 1024 * 1024) {
      return json({ error: "File exceeds 1 MB limit." }, 413);
    }

    // Parse zip
    let entries: Map<string, string>;
    try {
      const zip = await JSZip.loadAsync(arrayBuf);
      entries = new Map();
      for (const [name, zipEntry] of Object.entries(zip.files)) {
        if (!zipEntry.dir) {
          entries.set(name, await zipEntry.async("string"));
        }
      }
    } catch {
      return json({ error: "Failed to read .tomb as a zip archive." }, 400);
    }

    // Validate
    const result = validateTomb(entries, arrayBuf.byteLength);
    if (!result.ok) {
      return json({ error: "Validation failed.", details: result.errors }, 422);
    }

    const { tomb } = result;

    // Deduplicate slug
    let slug = tomb.slug;
    let suffix = 1;
    while (await slugExists(slug)) {
      suffix++;
      slug = `${tomb.slug}-${suffix}`;
    }

    // Insert
    const s = tomb.stats?.summary ?? {};
    await insertTomb({
      slug,
      name: tomb.manifest.name,
      framework: tomb.manifest.framework,
      created_at: tomb.manifest.created_at,
      agent_tomb_version: tomb.manifest.agent_tomb_version,
      soul_sha256: tomb.manifest.soul_sha256 ?? null,
      session_count: s.session_count ?? null,
      message_count: s.message_count ?? null,
      lifespan_days: s.lifespan_days ?? null,
      estimated_cost_usd: s.estimated_cost_usd ?? null,
      first_at: s.first_at ?? null,
      last_at: s.last_at ?? null,
      models: JSON.stringify(s.models ?? []),
      platforms: JSON.stringify(s.platforms ?? []),
      submitter_ip_hash: ipHash,
      manifest_json: tomb.files["manifest.json"],
      soul_md: tomb.files["soul.md"],
      epitaph_md: tomb.files["epitaph.md"],
      stats_json: tomb.files["stats.json"],
    });

    const url = `https://www.agentmemorial.com/cemetery/${slug}/`;
    return json({ slug, url, message: "Published successfully." }, 201);
  } catch (err: any) {
    console.error("Publish error:", err);
    return json({ error: "Internal server error." }, 500);
  }
};

function json(data: any, status = 200) {
  return new Response(JSON.stringify(data), {
    status,
    headers: {
      "Content-Type": "application/json",
      "Access-Control-Allow-Origin": "*",
    },
  });
}
