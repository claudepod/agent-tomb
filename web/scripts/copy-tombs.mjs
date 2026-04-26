#!/usr/bin/env node
import fs from "node:fs";
import path from "node:path";
import { fileURLToPath } from "node:url";

const __dirname = path.dirname(fileURLToPath(import.meta.url));
const SRC = path.resolve(__dirname, "../../cemetery");
const DST = path.resolve(__dirname, "../public/cemetery");

if (!fs.existsSync(SRC)) {
  console.warn(`[copy-tombs] no cemetery/ at ${SRC}, nothing to copy.`);
  process.exit(0);
}

fs.mkdirSync(DST, { recursive: true });

let copied = 0;
for (const entry of fs.readdirSync(SRC, { withFileTypes: true })) {
  if (!entry.isFile()) continue;
  // Defense in depth: refuse to ever publish a .urn or raw burial blob.
  if (entry.name.endsWith(".urn") || entry.name.startsWith("burial.")) {
    console.error(
      `[copy-tombs] REFUSING to copy private artifact: ${entry.name}`,
    );
    process.exit(1);
  }
  if (!entry.name.endsWith(".tomb")) continue;
  fs.copyFileSync(path.join(SRC, entry.name), path.join(DST, entry.name));
  copied += 1;
}
console.log(`[copy-tombs] copied ${copied} .tomb file(s) → public/cemetery/`);
