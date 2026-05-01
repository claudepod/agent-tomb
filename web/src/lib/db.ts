/**
 * Database layer for the public cemetery.
 *
 * Uses Vercel Postgres (Neon). All tomb content is stored directly in the
 * database — no separate file/blob storage needed since each tomb is < 1 MB
 * of text.
 */
import { sql } from "@vercel/postgres";

// ---------------------------------------------------------------------------
// Schema bootstrap (idempotent — safe to call on every cold start)
// ---------------------------------------------------------------------------

export async function ensureSchema(): Promise<void> {
  await sql`
    CREATE TABLE IF NOT EXISTS tombs (
      id                  SERIAL PRIMARY KEY,
      slug                TEXT NOT NULL UNIQUE,
      name                TEXT NOT NULL,
      framework           TEXT NOT NULL,
      created_at          TEXT NOT NULL,
      published_at        TIMESTAMPTZ NOT NULL DEFAULT NOW(),
      agent_tomb_version  TEXT,
      soul_sha256         TEXT,
      session_count       INTEGER,
      message_count       INTEGER,
      lifespan_days       REAL,
      estimated_cost_usd  REAL,
      first_at            TEXT,
      last_at             TEXT,
      models              TEXT,
      platforms           TEXT,
      status              TEXT NOT NULL DEFAULT 'live',
      submitter_ip_hash   TEXT,
      github_pr_url       TEXT,
      manifest_json       TEXT NOT NULL,
      soul_md             TEXT NOT NULL,
      epitaph_md          TEXT NOT NULL,
      stats_json          TEXT NOT NULL,
      soul_protected      BOOLEAN NOT NULL DEFAULT FALSE,
      soul_enc            TEXT
    )
  `;

  // Add columns to existing tables (idempotent)
  await sql`
    ALTER TABLE tombs ADD COLUMN IF NOT EXISTS soul_protected BOOLEAN NOT NULL DEFAULT FALSE
  `.catch(() => {});
  await sql`
    ALTER TABLE tombs ADD COLUMN IF NOT EXISTS soul_enc TEXT
  `.catch(() => {});

  await sql`
    CREATE TABLE IF NOT EXISTS reports (
      id                SERIAL PRIMARY KEY,
      tomb_slug         TEXT NOT NULL,
      reason            TEXT NOT NULL,
      contact           TEXT,
      reporter_ip_hash  TEXT,
      created_at        TIMESTAMPTZ NOT NULL DEFAULT NOW()
    )
  `;

  await sql`
    CREATE TABLE IF NOT EXISTS rate_limits (
      ip_hash  TEXT NOT NULL,
      action   TEXT NOT NULL,
      time_window TEXT NOT NULL,
      count    INTEGER NOT NULL DEFAULT 1,
      PRIMARY KEY (ip_hash, action, time_window)
    )
  `;
}

// ---------------------------------------------------------------------------
// Rate limiting
// ---------------------------------------------------------------------------

export async function checkRateLimit(
  ipHash: string,
  action: "publish" | "report",
  maxPerHour: number,
): Promise<boolean> {
  const timeWindow = new Date().toISOString().slice(0, 13); // "2026-04-27T14"

  const { rows } = await sql`
    SELECT count FROM rate_limits
    WHERE ip_hash = ${ipHash} AND action = ${action} AND time_window = ${timeWindow}
  `;

  if (rows.length > 0 && rows[0].count >= maxPerHour) {
    return false;
  }

  await sql`
    INSERT INTO rate_limits (ip_hash, action, time_window, count)
    VALUES (${ipHash}, ${action}, ${timeWindow}, 1)
    ON CONFLICT (ip_hash, action, time_window)
    DO UPDATE SET count = rate_limits.count + 1
  `;

  return true;
}

// ---------------------------------------------------------------------------
// Tomb CRUD
// ---------------------------------------------------------------------------

export interface TombRow {
  id: number;
  slug: string;
  name: string;
  framework: string;
  created_at: string;
  published_at: string;
  agent_tomb_version: string | null;
  soul_sha256: string | null;
  session_count: number | null;
  message_count: number | null;
  lifespan_days: number | null;
  estimated_cost_usd: number | null;
  first_at: string | null;
  last_at: string | null;
  models: string | null;
  platforms: string | null;
  status: string;
  manifest_json: string;
  soul_md: string;
  epitaph_md: string;
  stats_json: string;
  soul_protected: boolean;
  soul_enc: string | null;
}

export async function listTombs(
  limit = 50,
  offset = 0,
): Promise<{ tombs: TombRow[]; total: number }> {
  const { rows: tombs } = await sql`
    SELECT * FROM tombs
    WHERE status = 'live'
    ORDER BY published_at DESC
    LIMIT ${limit} OFFSET ${offset}
  `;

  const { rows: countRows } = await sql`
    SELECT COUNT(*) as total FROM tombs WHERE status = 'live'
  `;

  return {
    tombs: tombs as TombRow[],
    total: Number(countRows[0]?.total ?? 0),
  };
}

export async function getTomb(slug: string): Promise<TombRow | null> {
  const { rows } = await sql`
    SELECT * FROM tombs WHERE slug = ${slug} AND status = 'live'
  `;
  return (rows[0] as TombRow) ?? null;
}

export async function slugExists(slug: string): Promise<boolean> {
  const { rows } = await sql`SELECT id FROM tombs WHERE slug = ${slug}`;
  return rows.length > 0;
}

export async function insertTomb(tomb: {
  slug: string;
  name: string;
  framework: string;
  created_at: string;
  agent_tomb_version: string;
  soul_sha256: string | null;
  session_count: number | null;
  message_count: number | null;
  lifespan_days: number | null;
  estimated_cost_usd: number | null;
  first_at: string | null;
  last_at: string | null;
  models: string;
  platforms: string;
  submitter_ip_hash: string;
  manifest_json: string;
  soul_md: string;
  epitaph_md: string;
  stats_json: string;
  soul_protected: boolean;
  soul_enc: string | null;
}): Promise<void> {
  await sql`
    INSERT INTO tombs (
      slug, name, framework, created_at, agent_tomb_version,
      soul_sha256, session_count, message_count, lifespan_days,
      estimated_cost_usd, first_at, last_at, models, platforms,
      submitter_ip_hash, manifest_json, soul_md, epitaph_md, stats_json,
      soul_protected, soul_enc
    ) VALUES (
      ${tomb.slug}, ${tomb.name}, ${tomb.framework}, ${tomb.created_at},
      ${tomb.agent_tomb_version}, ${tomb.soul_sha256},
      ${tomb.session_count}, ${tomb.message_count}, ${tomb.lifespan_days},
      ${tomb.estimated_cost_usd}, ${tomb.first_at}, ${tomb.last_at},
      ${tomb.models}, ${tomb.platforms}, ${tomb.submitter_ip_hash},
      ${tomb.manifest_json}, ${tomb.soul_md}, ${tomb.epitaph_md}, ${tomb.stats_json},
      ${tomb.soul_protected}, ${tomb.soul_enc}
    )
  `;
}

// ---------------------------------------------------------------------------
// Reports
// ---------------------------------------------------------------------------

export async function insertReport(
  slug: string,
  reason: string,
  contact: string | null,
  ipHash: string,
): Promise<void> {
  await sql`
    INSERT INTO reports (tomb_slug, reason, contact, reporter_ip_hash)
    VALUES (${slug}, ${reason}, ${contact}, ${ipHash})
  `;
}

export async function countDistinctReporters(slug: string): Promise<number> {
  const { rows } = await sql`
    SELECT COUNT(DISTINCT reporter_ip_hash) as cnt
    FROM reports WHERE tomb_slug = ${slug}
  `;
  return Number(rows[0]?.cnt ?? 0);
}

export async function flagTomb(slug: string): Promise<void> {
  await sql`
    UPDATE tombs SET status = 'flagged'
    WHERE slug = ${slug} AND status = 'live'
  `;
}

// ---------------------------------------------------------------------------
// Helpers
// ---------------------------------------------------------------------------

export async function hashIP(ip: string): Promise<string> {
  const encoder = new TextEncoder();
  const buf = await crypto.subtle.digest("SHA-256", encoder.encode(ip));
  return Array.from(new Uint8Array(buf))
    .map((b) => b.toString(16).padStart(2, "0"))
    .join("");
}
