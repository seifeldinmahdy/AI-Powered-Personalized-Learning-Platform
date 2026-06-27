#!/usr/bin/env node
/**
 * Pre-synthesize the avatar's playful reaction voicelines in LearnPal's REAL
 * voice (edge-tts) WITH Audio2Face blendshapes, so they play back lip-synced
 * and offline at the exhibition — no robotic browser speechSynthesis.
 *
 * Run ONCE while the AI service (and its TTS + A2F) are online:
 *   node scripts/bake-reactions.mjs
 *   AI_SERVICE_URL=http://localhost:8001 node scripts/bake-reactions.mjs
 *
 * Writes src/data/reactionClips.generated.json  ({ [quipText]: { audio_base64,
 * blendshapes } }), which the app imports and plays on each reaction.
 */
import fs from "node:fs";
import path from "node:path";
import { fileURLToPath } from "node:url";

const __dirname = path.dirname(fileURLToPath(import.meta.url));
const DATA_DIR = path.resolve(__dirname, "..", "src", "data");
const LINES_PATH = path.join(DATA_DIR, "reactionLines.json");
const OUT_PATH = path.join(DATA_DIR, "reactionClips.generated.json");

const AI_URL = process.env.AI_SERVICE_URL || "http://localhost:8001";

const lines = JSON.parse(fs.readFileSync(LINES_PATH, "utf8"));

// Collect unique (text, emotion) pairs across all reaction kinds.
const jobs = new Map(); // text -> emotion
for (const kind of Object.keys(lines)) {
  const { emotion, quips } = lines[kind];
  for (const text of quips) if (!jobs.has(text)) jobs.set(text, emotion || null);
}

// Keep any clips already baked so a re-run only fills gaps.
let out = {};
try { out = JSON.parse(fs.readFileSync(OUT_PATH, "utf8")); } catch { /* fresh */ }

console.log(`Baking ${jobs.size} reaction voicelines via ${AI_URL}/tutor/synthesize-reaction`);

let ok = 0, fail = 0;
for (const [text, emotion] of jobs) {
  process.stdout.write(`  • "${text}" … `);
  try {
    const res = await fetch(`${AI_URL}/tutor/synthesize-reaction`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ text, emotion }),
    });
    if (!res.ok) throw new Error(`HTTP ${res.status}: ${await res.text()}`);
    const data = await res.json();
    if (!data.audio_base64) throw new Error("no audio returned");
    out[text] = { audio_base64: data.audio_base64, blendshapes: data.blendshapes || null };
    ok++;
    console.log(data.blendshapes ? "ok (with lip-sync)" : "ok (audio only — A2F unavailable)");
  } catch (e) {
    fail++;
    console.log(`FAILED: ${e.message}`);
  }
}

fs.writeFileSync(OUT_PATH, JSON.stringify(out, null, 0));
console.log(`\nDone. ${ok} ok, ${fail} failed → ${path.relative(process.cwd(), OUT_PATH)}`);
if (fail) process.exitCode = 1;
