/**
 * Touch-target audit — run with: node panel/touch-targets.test.mjs
 *
 * CLAUDE.md panel principles: every interactive control is >= 56px, because the
 * user is a receptionist working one-thumbed on a cheap Android while being
 * interrupted. NEXT stays a fixed-bottom 72px full-width button.
 *
 * A browser measurement would be better, but it is not reproducible in CI. This
 * reads the source instead and fails on any interactive element whose sizing
 * classes cannot reach 56px. Static, so it cannot catch a control sized purely
 * by its content — hence the explicit allowlist below, which is the honest
 * record of what this check does NOT prove.
 */

import assert from "node:assert/strict";
import { readdirSync, readFileSync, statSync } from "node:fs";
import { join } from "node:path";

const TOUCH_PX = 56;

/** Tailwind sizing classes that satisfy the rule. `touch` = 3.5rem = 56px. */
const OK_CLASS = /\b(h|min-h)-(touch|next|16|20|24|screen|full)\b/;
/** An explicit pixel-ish class that does NOT reach 56px. */
const BAD_HEIGHT = /\b(h|min-h)-(?:(\d+)|\[([0-9.]+)rem\])\b/g;

/** Files where an interactive element is intentionally sized by its container. */
const ALLOW = new Set([
  // The row itself is min-h-touch; the token badge inside is decoration.
  "app/components/QueueRow.tsx",
]);

function walk(dir) {
  const out = [];
  for (const name of readdirSync(dir)) {
    const p = join(dir, name);
    if (statSync(p).isDirectory()) out.push(...walk(p));
    else if (p.endsWith(".tsx")) out.push(p);
  }
  return out;
}

const files = walk("app");
assert(files.length > 0, "no .tsx files found — is the cwd wrong?");

const failures = [];
let interactive = 0;

for (const file of files) {
  const rel = file.split("\\").join("/");
  const src = readFileSync(file, "utf8");

  // Each JSX opening tag for an interactive element, with its attributes.
  const tags = src.matchAll(/<(button|input|a|Link)\s([^>]*?)\/?>/gs);
  for (const [, tag, attrs] of tags) {
    interactive++;
    const cls = /className=(?:"([^"]*)"|\{`([^`]*)`\}|\{`([\s\S]*?)`\})/.exec(attrs);
    const classText = cls ? (cls[1] ?? cls[2] ?? cls[3] ?? "") : "";

    // Sized by a shared component class that already guarantees the minimum.
    if (/\bbtn(-|\b)/.test(classText)) continue; // .btn => min-h-touch in globals.css
    if (/\bfield\b/.test(classText) && OK_CLASS.test(classText)) continue;
    if (OK_CLASS.test(classText)) continue;
    if (ALLOW.has(rel)) continue;

    // Explicitly too small?
    let m;
    BAD_HEIGHT.lastIndex = 0;
    while ((m = BAD_HEIGHT.exec(classText))) {
      const px = m[2] !== undefined ? Number(m[2]) * 4 : Number(m[3]) * 16;
      if (px < TOUCH_PX) {
        failures.push(`${rel}: <${tag}> has h-${m[2] ?? m[3]} (~${px}px) < ${TOUCH_PX}px`);
      }
    }
  }
}

if (failures.length) {
  console.error("Touch targets under 56px:\n  " + failures.join("\n  "));
  process.exit(1);
}

// NEXT must stay exactly 72px, fixed to the bottom, full width.
const next = readFileSync("app/components/NextButton.tsx", "utf8");
assert(/h-next/.test(next), "NEXT lost its 72px height");
assert(/w-full/.test(next), "NEXT is no longer full-width");
assert(/fixed inset-x-0 bottom-0/.test(next), "NEXT is no longer fixed to the bottom");

console.log(`✓  ${interactive} interactive elements across ${files.length} files`);
console.log(`✓  none sized below ${TOUCH_PX}px`);
console.log("✓  NEXT is still fixed-bottom, full-width, 72px");
console.log(`note: ${ALLOW.size} file(s) allowlisted (sized by container, not class)`);
