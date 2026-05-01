/**
 * Tomb upload validation.
 */

const REQUIRED_FILES = ["manifest.json", "soul.md", "epitaph.md", "stats.json"];
const FORBIDDEN_PATTERNS = [/\.urn$/i, /^burial\.(enc|meta\.json)$/i];
const HTML_TAG = /<[^>]+>/;
const MAX_NAME_LEN = 80;
const MAX_TOMB_BYTES = 1 * 1024 * 1024;

const SECRET_PATTERNS = [
  /AKIA[0-9A-Z]{16}/,
  /ghp_[A-Za-z0-9_]{36}/,
  /github_pat_[A-Za-z0-9_]{82}/,
  /sk-ant-[A-Za-z0-9\-_]{20,}/,
  /sk-[A-Za-z0-9]{20,}/,
  /-----BEGIN (?:RSA |EC |DSA )?PRIVATE KEY-----/,
  /AIza[0-9A-Za-z\-_]{35}/,
  /(?:api[_-]?key|secret|token|password|bearer)\s*[:=]\s*['"]?[A-Za-z0-9\-_]{20,}/i,
];

export interface ValidatedTomb {
  slug: string;
  manifest: {
    name: string;
    framework: string;
    kind?: string;
    created_at: string;
    agent_tomb_version: string;
    soul_sha256?: string;
    soul_protected?: boolean;
  };
  stats: any;
  files: {
    "manifest.json": string;
    "soul.md": string;
    "epitaph.md": string;
    "stats.json": string;
    "soul.enc"?: string;
  };
}

export type ValidationResult =
  | { ok: true; tomb: ValidatedTomb }
  | { ok: false; errors: string[] };

export function validateTomb(
  entries: Map<string, string>,
  rawSize: number,
): ValidationResult {
  const errors: string[] = [];

  if (rawSize > MAX_TOMB_BYTES) {
    errors.push(`File exceeds ${MAX_TOMB_BYTES / 1024} KB limit`);
  }

  for (const f of REQUIRED_FILES) {
    if (!entries.has(f)) errors.push(`Missing required file: ${f}`);
  }

  for (const name of entries.keys()) {
    for (const re of FORBIDDEN_PATTERNS) {
      if (re.test(name)) {
        errors.push(`Forbidden file: ${name}`);
      }
    }
  }

  if (errors.length) return { ok: false, errors };

  let manifest: any;
  try {
    manifest = JSON.parse(entries.get("manifest.json")!);
  } catch {
    return { ok: false, errors: ["manifest.json is not valid JSON"] };
  }

  for (const field of ["name", "framework", "created_at", "agent_tomb_version"]) {
    if (!manifest[field] || typeof manifest[field] !== "string") {
      errors.push(`manifest.${field} missing or not a string`);
    }
  }

  if (typeof manifest.name === "string") {
    if (HTML_TAG.test(manifest.name)) errors.push("manifest.name contains HTML tags");
    if (manifest.name.length > MAX_NAME_LEN) errors.push(`manifest.name exceeds ${MAX_NAME_LEN} chars`);
  }

  if (manifest.kind && manifest.kind !== "tomb") {
    errors.push(`manifest.kind="${manifest.kind}" — only "tomb" allowed`);
  }

  // Validate soul.enc if present
  const soulEncRaw = entries.get("soul.enc");
  if (soulEncRaw) {
    try {
      const enc = JSON.parse(soulEncRaw);
      if (!enc.salt || !enc.iv || !enc.ciphertext) {
        errors.push("soul.enc missing required fields (salt, iv, ciphertext)");
      }
    } catch {
      errors.push("soul.enc is not valid JSON");
    }
  }

  // Secret scan (skip soul.enc — it's encrypted ciphertext)
  for (const [filename, content] of entries) {
    if (filename === "soul.enc") continue;
    for (const pattern of SECRET_PATTERNS) {
      if (pattern.test(content)) {
        errors.push(`Possible secret in ${filename}`);
        break;
      }
    }
  }

  let stats: any;
  try {
    stats = JSON.parse(entries.get("stats.json")!);
  } catch {
    return { ok: false, errors: [...errors, "stats.json is not valid JSON"] };
  }

  if (errors.length) return { ok: false, errors };

  const slug = slugify(manifest.name);
  if (!slug) return { ok: false, errors: ["manifest.name produces an empty slug"] };

  return {
    ok: true,
    tomb: {
      slug,
      manifest,
      stats,
      files: {
        "manifest.json": entries.get("manifest.json")!,
        "soul.md": entries.get("soul.md")!,
        "epitaph.md": entries.get("epitaph.md")!,
        "stats.json": entries.get("stats.json")!,
        ...(soulEncRaw ? { "soul.enc": soulEncRaw } : {}),
      },
    },
  };
}

export function slugify(name: string): string {
  return name
    .toLowerCase()
    .replace(/[^a-z0-9\u4e00-\u9fff]+/g, "-")
    .replace(/^-+|-+$/g, "")
    .slice(0, 60);
}
