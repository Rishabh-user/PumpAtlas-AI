import { dirname } from "path";
import { fileURLToPath } from "url";
import { FlatCompat } from "@eslint/eslintrc";

/**
 * ESLint was in `devDependencies` and `npm run lint` was in `scripts`, but no config
 * file existed — so the command did not lint anything. It dropped into Next's
 * interactive "How would you like to configure ESLint?" wizard, which on a terminal
 * waits for a keypress and in CI either hangs or exits non-zero for a reason that has
 * nothing to do with the code. A lint script that cannot run is a lint script nobody
 * runs.
 *
 * `next/core-web-vitals` is Next's own recommended set plus the accessibility and
 * loading-performance rules; `next/typescript` adds the TypeScript ones. Both ship
 * inside `eslint-config-next`, already installed, so this adds no dependency.
 */
const compat = new FlatCompat({ baseDirectory: dirname(fileURLToPath(import.meta.url)) });

const config = [
  {
    // Build output and machine-local state. Linting generated code reports other
    // people's style as this project's problem.
    ignores: [".next/**", ".next-build/**", "out/**", "node_modules/**", "next-env.d.ts"],
  },
  ...compat.extends("next/core-web-vitals", "next/typescript"),
];

export default config;
