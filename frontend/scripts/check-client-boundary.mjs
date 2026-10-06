/**
 * Catch a server component importing a plain value out of a `"use client"` module.
 *
 * Every export of a client module is a *client reference*, not the thing itself. A
 * component reference is fine — the server renders it by handing it to the client — but
 * calling a function reference on the server throws at request time:
 *
 *     Attempted to call hrefToString() from the server but hrefToString is on the
 *     client. It's not possible to invoke a client function from the server.
 *
 * Neither `tsc` nor `next build` catches it. Both compiled a broken `/vendors` page
 * quite happily, because the rule is enforced when the call runs, and a build never runs
 * it. That is what this script is for.
 *
 * The heuristic is React's own naming convention, which JSX enforces anyway: an export
 * starting with a capital letter is a component and may cross the boundary; a lowercase
 * one is a value or a function and may not. Types are erased at compile time, so
 * `import type` is ignored.
 *
 *     node scripts/check-client-boundary.mjs
 */

import { readFileSync, readdirSync, statSync } from "node:fs";
import { join, relative, resolve } from "node:path";

const SRC = resolve(import.meta.dirname, "..", "src");

/** Every .ts/.tsx file under src. */
function walk(dir) {
  const out = [];
  for (const entry of readdirSync(dir)) {
    const full = join(dir, entry);
    if (statSync(full).isDirectory()) out.push(...walk(full));
    else if (/\.tsx?$/.test(entry)) out.push(full);
  }
  return out;
}

const files = walk(SRC);
const isClient = new Map();
for (const file of files) {
  const head = readFileSync(file, "utf8").slice(0, 200);
  isClient.set(file, /^\s*["']use client["']/m.test(head));
}

/** `@/x/y` or a relative path -> absolute file, trying the usual extensions. */
function resolveImport(spec, fromFile) {
  let base;
  if (spec.startsWith("@/")) base = join(SRC, spec.slice(2));
  else if (spec.startsWith(".")) base = resolve(fromFile, "..", spec);
  else return null;
  for (const candidate of [
    `${base}.ts`,
    `${base}.tsx`,
    join(base, "index.ts"),
    join(base, "index.tsx"),
  ]) {
    if (files.includes(candidate)) return candidate;
  }
  return null;
}

const IMPORT_RE = /import\s+(type\s+)?\{([^}]*)\}\s+from\s+["']([^"']+)["']/g;

const problems = [];
for (const file of files) {
  if (isClient.get(file)) continue; // a client module may import anything
  const source = readFileSync(file, "utf8");
  for (const match of source.matchAll(IMPORT_RE)) {
    const [, typeOnly, names, spec] = match;
    if (typeOnly) continue;
    const target = resolveImport(spec, file);
    if (!target || !isClient.get(target)) continue;

    for (const raw of names.split(",")) {
      const name = raw.trim().replace(/^type\s+/, "").split(/\s+as\s+/)[0].trim();
      if (!name) continue;
      if (raw.trim().startsWith("type ")) continue;
      // Components are capitalised; anything else is a value being called.
      if (/^[A-Z]/.test(name)) continue;
      problems.push({
        file: relative(SRC, file),
        name,
        from: relative(SRC, target),
      });
    }
  }
}

if (problems.length) {
  console.error("Server modules importing values from client modules:\n");
  for (const problem of problems) {
    console.error(`  ${problem.file}`);
    console.error(`      imports ${problem.name}() from ${problem.from} ("use client")`);
  }
  console.error(
    "\nMove the helper into a module with no directive, so both sides can import it.",
  );
  process.exit(1);
}

console.log(
  `Client boundary clean: ${files.length} files, ` +
    `${[...isClient.values()].filter(Boolean).length} client modules.`,
);
