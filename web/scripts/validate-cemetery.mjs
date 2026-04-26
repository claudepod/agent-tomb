#!/usr/bin/env node
/**
 * Cemetery PR validator.
 *
 * Refuses any submission that:
 *   - contains a .urn or burial.enc / burial.meta.json (private artifacts must
 *     never live in the public garden)
 *   - exceeds size limits (per-tomb total < 1 MB; total cemetery < 200 MB)
 *   - has an invalid manifest.json (missing fields, HTML in name, bad UTF-8)
 *   - is missing required files (manifest, soul.md, epitaph.md, stats.json)
 *
 * Run from CI on every push and PR. Exit 0 = valid; non-zero = block merge.
 */
import fs from "node:fs";
import path from "node:path";
import { fileURLToPath } from "node:url";

const __dirname = path.dirname(fileURLToPath(import.meta.url));
const ROOT = path.resolve(__dirname, "../../cemetery");

const MAX_TOMB_BYTES = 1 * 1024 * 1024;          // 1 MB per tomb directory
const MAX_TOTAL_BYTES = 200 * 1024 * 1024;       // 200 MB whole cemetery
const FORBIDDEN_FILE_PATTERNS = [/\.urn$/i, /^burial\.(enc|meta\.json)$/i];
const REQUIRED_FILES = ["manifest.json", "soul.md", "epitaph.md", "stats.json"];
const HTML_TAG = /<[^>]+>/;

const errors = [];
const warnings = [];

function fail(msg) {
  errors.push(msg);
}

function warn(msg) {
  warnings.push(msg);
}

function dirSize(dir) {
  let total = 0;
  for (const ent of fs.readdirSync(dir, { withFileTypes: true })) {
    const p = path.join(dir, ent.name);
    if (ent.isDirectory()) total += dirSize(p);
    else if (ent.isFile()) total += fs.statSync(p).size;
  }
  return total;
}

function validateManifest(slug, dir) {
  const file = path.join(dir, "manifest.json");
  let raw;
  try {
    raw = fs.readFileSync(file, "utf-8");
  } catch (e) {
    fail(`${slug}: manifest.json unreadable (${e.message})`);
    return;
  }
  let m;
  try {
    m = JSON.parse(raw);
  } catch (e) {
    fail(`${slug}: manifest.json is not valid JSON (${e.message})`);
    return;
  }
  for (const field of ["name", "framework", "created_at", "agent_tomb_version"]) {
    if (!m[field] || typeof m[field] !== "string") {
      fail(`${slug}: manifest.${field} missing or not a string`);
    }
  }
  if (typeof m.name === "string" && HTML_TAG.test(m.name)) {
    fail(`${slug}: manifest.name contains HTML tags — reject for XSS safety`);
  }
  if (typeof m.name === "string" && m.name.length > 80) {
    fail(`${slug}: manifest.name longer than 80 chars`);
  }
  if (m.kind && m.kind !== "tomb") {
    fail(`${slug}: manifest.kind="${m.kind}" — only "tomb" may live in the garden`);
  }
}

function scanCemetery() {
  if (!fs.existsSync(ROOT)) {
    console.log(`[validate-cemetery] no cemetery/ at ${ROOT}, nothing to check.`);
    return;
  }
  // 1. Top-level files: only .tomb allowed
  for (const ent of fs.readdirSync(ROOT, { withFileTypes: true })) {
    if (ent.isFile()) {
      for (const re of FORBIDDEN_FILE_PATTERNS) {
        if (re.test(ent.name)) {
          fail(
            `${ent.name}: private artifact in public cemetery — refuse merge. ` +
            `(.urn / burial.enc must never be committed)`,
          );
        }
      }
      if (!ent.name.endsWith(".tomb") && !ent.name.startsWith(".")) {
        warn(`unexpected top-level file in cemetery/: ${ent.name}`);
      }
    } else if (ent.isDirectory()) {
      const dir = path.join(ROOT, ent.name);
      // 2. Each tomb directory must have required files
      for (const f of REQUIRED_FILES) {
        if (!fs.existsSync(path.join(dir, f))) {
          fail(`${ent.name}/: missing required file ${f}`);
        }
      }
      // 3. No forbidden files inside the directory either
      for (const sub of fs.readdirSync(dir)) {
        for (const re of FORBIDDEN_FILE_PATTERNS) {
          if (re.test(sub)) {
            fail(
              `${ent.name}/${sub}: private artifact in public cemetery — refuse merge.`,
            );
          }
        }
      }
      // 4. Per-tomb size cap
      const size = dirSize(dir);
      if (size > MAX_TOMB_BYTES) {
        fail(
          `${ent.name}/: total ${(size / 1024 / 1024).toFixed(2)} MB exceeds ` +
          `${(MAX_TOMB_BYTES / 1024 / 1024).toFixed(0)} MB cap`,
        );
      }
      // 5. Manifest content checks
      if (fs.existsSync(path.join(dir, "manifest.json"))) {
        validateManifest(ent.name, dir);
      }
    }
  }
  // 6. Total cemetery size cap
  const total = dirSize(ROOT);
  if (total > MAX_TOTAL_BYTES) {
    fail(
      `cemetery/ total ${(total / 1024 / 1024).toFixed(2)} MB exceeds ` +
      `${(MAX_TOTAL_BYTES / 1024 / 1024).toFixed(0)} MB cap`,
    );
  }
}

scanCemetery();

if (warnings.length) {
  console.log("⚠ warnings:");
  for (const w of warnings) console.log(`  - ${w}`);
}
if (errors.length) {
  console.error(`✗ ${errors.length} validation error(s):`);
  for (const e of errors) console.error(`  - ${e}`);
  process.exit(1);
}
console.log("✓ cemetery/ valid");
