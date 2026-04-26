import fs from "node:fs";
import path from "node:path";
import { fileURLToPath } from "node:url";
import DOMPurify from "isomorphic-dompurify";
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

function isTombDir(entry: fs.Dirent): boolean {
  if (!entry.isDirectory()) return false;
  const dir = path.join(CEMETERY_DIR, entry.name);
  return (
    fs.existsSync(path.join(dir, "manifest.json")) &&
    fs.existsSync(path.join(dir, "epitaph.md")) &&
    fs.existsSync(path.join(dir, "soul.md"))
  );
}

function renderMarkdown(text: string): string {
  // Marked passes raw HTML through — community-submitted markdown is untrusted,
  // so DOMPurify is the safety net against XSS.
  const raw = marked.parse(text, { async: false }) as string;
  return DOMPurify.sanitize(raw, {
    USE_PROFILES: { html: true },
    FORBID_TAGS: ["script", "style", "iframe", "object", "embed", "form"],
    FORBID_ATTR: ["onerror", "onload", "onclick", "onmouseover"],
  });
}

export function loadTombs(): Tomb[] {
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
}

export function loadTomb(slug: string): Tomb | null {
  return loadTombs().find((t) => t.slug === slug) ?? null;
}

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
