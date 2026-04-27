import fs from "node:fs";
import path from "node:path";
import { fileURLToPath } from "node:url";
import { marked } from "marked";

const __dirname = path.dirname(fileURLToPath(import.meta.url));
const CEMETERY_DIR = path.resolve(__dirname, "../../../cemetery");

export interface Manifest {
  name: string;
  framework: string;
  mode: "cremation" | "burial";
  created_at: string;
  agent_tomb_version: string;
  soul_sha256: string;
}

export interface Stats {
  summary: {
    db_size_bytes?: number;
    session_count?: number;
    first_at?: string | null;
    last_at?: string | null;
    lifespan_days?: number | null;
    input_tokens?: number;
    output_tokens?: number;
    estimated_cost_usd?: number;
    message_count?: number;
    models?: string[];
    platforms?: string[];
    top_tools?: Array<[string, number]>;
  };
  skills: string[];
  notes: string[];
}

export interface Tomb {
  slug: string;
  manifest: Manifest;
  epitaphHtml: string;
  epitaphText: string;
  soulHtml: string;
  soulText: string;
  stats: Stats;
  tombFileExists: boolean;
}

// ---------------------------------------------------------------------------
// Markdown rendering (shared)
// ---------------------------------------------------------------------------

export function renderMarkdown(text: string): string {
  const raw = marked.parse(text, { async: false }) as string;
  // Sanitize: strip dangerous tags/attributes. Content is validated at
  // publish time (validate.ts secret scan + manifest checks), so this is
  // defense-in-depth using a simple regex strip rather than DOMPurify
  // (which has ESM/CJS issues in Vercel serverless).
  return raw
    .replace(/<script[\s>][\s\S]*?<\/script>/gi, "")
    .replace(/<style[\s>][\s\S]*?<\/style>/gi, "")
    .replace(/<iframe[\s>][\s\S]*?<\/iframe>/gi, "")
    .replace(/<object[\s>][\s\S]*?<\/object>/gi, "")
    .replace(/<embed[\s>][\s\S]*?<\/embed>/gi, "")
    .replace(/<form[\s>][\s\S]*?<\/form>/gi, "")
    .replace(/\s+on\w+\s*=\s*["'][^"']*["']/gi, "");
}

// ---------------------------------------------------------------------------
// Filesystem loader (build-time, for git-based tombs)
// ---------------------------------------------------------------------------

function isTombDir(entry: fs.Dirent): boolean {
  if (!entry.isDirectory()) return false;
  const dir = path.join(CEMETERY_DIR, entry.name);
  return (
    fs.existsSync(path.join(dir, "manifest.json")) &&
    fs.existsSync(path.join(dir, "epitaph.md")) &&
    fs.existsSync(path.join(dir, "soul.md"))
  );
}

export function loadTombs(): Tomb[] {
  try {
    if (!fs.existsSync(CEMETERY_DIR)) return [];
    const entries = fs.readdirSync(CEMETERY_DIR, { withFileTypes: true });
    const tombs: Tomb[] = [];
    for (const entry of entries) {
      if (!isTombDir(entry)) continue;
      const slug = entry.name;
      const dir = path.join(CEMETERY_DIR, slug);
      const manifest = JSON.parse(
        fs.readFileSync(path.join(dir, "manifest.json"), "utf-8"),
      ) as Manifest;
      const epitaphText = fs.readFileSync(path.join(dir, "epitaph.md"), "utf-8");
      const soulText = fs.readFileSync(path.join(dir, "soul.md"), "utf-8");
      const stats = JSON.parse(
        fs.readFileSync(path.join(dir, "stats.json"), "utf-8"),
      ) as Stats;
      tombs.push({
        slug,
        manifest,
        epitaphText,
        epitaphHtml: renderMarkdown(epitaphText),
        soulText,
        soulHtml: renderMarkdown(soulText),
        stats,
        tombFileExists: fs.existsSync(path.join(CEMETERY_DIR, `${slug}.tomb`)),
      });
    }
    return tombs.sort((a, b) =>
      (b.manifest.created_at || "").localeCompare(a.manifest.created_at || ""),
    );
  } catch (err) {
    // Filesystem not available in serverless runtime — rely on DB only
    console.error("[loadTombs] Filesystem read failed:", err);
    return [];
  }
}

export function loadTomb(slug: string): Tomb | null {
  return loadTombs().find((t) => t.slug === slug) ?? null;
}

// ---------------------------------------------------------------------------
// DB loader (SSR — queries Vercel Postgres directly)
// ---------------------------------------------------------------------------

// Dynamic import to avoid loading @vercel/postgres at module init time.
async function getDbModule() {
  return import("./db");
}

function dbRowToTomb(row: any): Tomb {
  const epitaphText = row.epitaph_md ?? "";
  const soulText = row.soul_md ?? "";
  let stats: Stats;
  try {
    stats = JSON.parse(row.stats_json);
  } catch {
    stats = {
      summary: {
        session_count: row.session_count,
        message_count: row.message_count,
        lifespan_days: row.lifespan_days,
        estimated_cost_usd: row.estimated_cost_usd,
        first_at: row.first_at,
        last_at: row.last_at,
        models: safeJsonParse(row.models, []),
        platforms: safeJsonParse(row.platforms, []),
      },
      skills: [],
      notes: [],
    };
  }
  return {
    slug: row.slug,
    manifest: {
      name: row.name,
      framework: row.framework,
      mode: "burial",
      created_at: row.created_at,
      agent_tomb_version: row.agent_tomb_version ?? "",
      soul_sha256: row.soul_sha256 ?? "",
    },
    epitaphHtml: renderMarkdown(epitaphText),
    epitaphText,
    soulHtml: renderMarkdown(soulText),
    soulText,
    stats,
    tombFileExists: false,
  };
}

function safeJsonParse(v: any, fallback: any) {
  if (typeof v !== "string") return fallback;
  try { return JSON.parse(v); } catch { return fallback; }
}

// ---------------------------------------------------------------------------
// Merged loader — combines git + DB, deduplicates by slug
// ---------------------------------------------------------------------------

export async function loadAllTombs(): Promise<Tomb[]> {
  let dbTombs: Tomb[] = [];
  try {
    const { listTombs: dbListTombs } = await getDbModule();
    const { tombs: rows } = await dbListTombs(200, 0);
    dbTombs = rows.map(dbRowToTomb);
  } catch (err) {
    console.error("[loadAllTombs] DB query failed, falling back to git:", err);
  }

  const gitTombs = loadTombs();

  // Merge: git tombs take priority (they have full content + download links)
  const bySlug = new Map<string, Tomb>();
  for (const t of dbTombs) bySlug.set(t.slug, t);
  for (const t of gitTombs) bySlug.set(t.slug, t);

  return Array.from(bySlug.values()).sort((a, b) =>
    (b.manifest.created_at || "").localeCompare(a.manifest.created_at || ""),
  );
}

export async function loadOneTomb(slug: string): Promise<Tomb | null> {
  // Try git first (has full pre-rendered content + download link)
  const git = loadTomb(slug);
  if (git) return git;
  // Fall back to DB
  try {
    const { getTomb: dbGetTomb } = await getDbModule();
    const row = await dbGetTomb(slug);
    return row ? dbRowToTomb(row) : null;
  } catch (err) {
    console.error("[loadOneTomb] DB query failed:", err);
    return null;
  }
}

// ---------------------------------------------------------------------------
// Helpers
// ---------------------------------------------------------------------------

export function formatDate(iso?: string | null): string {
  if (!iso) return "—";
  const d = new Date(iso);
  if (Number.isNaN(d.getTime())) return iso;
  return d.toISOString().slice(0, 10);
}

export function lifespanText(stats: Stats): string {
  const days = stats.summary.lifespan_days;
  if (days == null) return "—";
  if (days < 1) {
    const minutes = Math.round(days * 24 * 60);
    return `${minutes} minute${minutes === 1 ? "" : "s"}`;
  }
  return `${days} day${days === 1 ? "" : "s"}`;
}
