/**
 * POST /api/v1/seal-souls — one-time migration to encrypt existing souls.
 * DELETE THIS FILE after use.
 */
export const prerender = false;

import type { APIRoute } from "astro";
import { sql } from "@vercel/postgres";

export const POST: APIRoute = async ({ request }) => {
  const body = await request.json();
  const { key, password, slugs } = body;

  if (key !== "seal-souls-2026") {
    return new Response(JSON.stringify({ error: "Unauthorized" }), {
      status: 401,
      headers: { "Content-Type": "application/json" },
    });
  }

  if (!password || !slugs?.length) {
    return new Response(JSON.stringify({ error: "Missing password or slugs" }), {
      status: 400,
      headers: { "Content-Type": "application/json" },
    });
  }

  const results: string[] = [];

  for (const slug of slugs) {
    try {
      // Read current soul
      const { rows } = await sql`SELECT soul_md FROM tombs WHERE slug = ${slug}`;
      if (!rows.length) { results.push(`${slug}: not found`); continue; }

      const soulMd = rows[0].soul_md;

      // Encrypt with Web Crypto (PBKDF2 + AES-GCM)
      const salt = crypto.getRandomValues(new Uint8Array(16));
      const iv = crypto.getRandomValues(new Uint8Array(12));
      const iterations = 100000;

      const keyMaterial = await crypto.subtle.importKey(
        "raw", new TextEncoder().encode(password), "PBKDF2", false, ["deriveKey"]
      );
      const aesKey = await crypto.subtle.deriveKey(
        { name: "PBKDF2", salt, iterations, hash: "SHA-256" },
        keyMaterial,
        { name: "AES-GCM", length: 256 },
        false,
        ["encrypt"]
      );
      const ct = await crypto.subtle.encrypt(
        { name: "AES-GCM", iv },
        aesKey,
        new TextEncoder().encode(soulMd)
      );

      const encJson = JSON.stringify({
        salt: btoa(String.fromCharCode(...salt)),
        iv: btoa(String.fromCharCode(...iv)),
        ciphertext: btoa(String.fromCharCode(...new Uint8Array(ct))),
        iterations,
      });

      await sql`
        UPDATE tombs
        SET soul_protected = TRUE,
            soul_enc = ${encJson},
            soul_md = '_This soul is sealed. Enter the viewing password to read it._'
        WHERE slug = ${slug}
      `;

      results.push(`${slug}: sealed`);
    } catch (err: any) {
      results.push(`${slug}: error — ${err.message}`);
    }
  }

  return new Response(JSON.stringify({ results }), {
    status: 200,
    headers: { "Content-Type": "application/json" },
  });
};
