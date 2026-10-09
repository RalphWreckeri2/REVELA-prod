// Guards the context split introduced in Phase 8.
//
// The refactor separated the context object + hook (`authContext.js`,
// `themeContext.js`) from the provider component (`AuthProvider.jsx`,
// `ThemeProvider.jsx`) so the provider files export only components and satisfy
// react-refresh/only-export-components.
//
// The invariant that keeps this safe: the provider files must IMPORT the
// context and must never CREATE one. If a provider ever called createContext
// itself, `useAuth()`/`useTheme()` would read a different object than the
// provider supplies, returning null at runtime while the build still passed.
import fs from "node:fs";
import path from "node:path";
import { fileURLToPath } from "node:url";

// Resolve against this file's location so the check works from any cwd.
const root = path.resolve(path.dirname(fileURLToPath(import.meta.url)), "..");
const read = (relative) => fs.readFileSync(path.join(root, relative), "utf8");

const files = [
  ["src/context/AuthProvider.jsx", "./authContext"],
  ["src/context/ThemeProvider.jsx", "./themeContext"],
];

let failures = 0;
for (const [file, mustImport] of files) {
  const source = read(file);
  const creates = /createContext\s*\(/.test(source);
  const imports = source.includes(mustImport);
  const ok = !creates && imports;
  if (!ok) failures += 1;
  console.log(
    `${ok ? "OK  " : "FAIL"} ${file.padEnd(32)} ` +
      `imports=${imports} definesContext=${creates}`,
  );
}

// Consumers must all reach the lowercase module, never the provider file.
const consumers = [
  "src/pages/MapPage.jsx",
  "src/pages/RegistryPage.jsx",
  "src/components/ProtectedRoute.jsx",
  "src/pages/SettingsPage.jsx",
];
for (const file of consumers) {
  const source = read(file);
  const good = /from\s+"\.\.?\/context\/(authContext|themeContext)"/.test(source);
  if (!good) failures += 1;
  console.log(`${good ? "OK  " : "FAIL"} ${file.padEnd(32)} imports lowercase context module`);
}

console.log(failures === 0 ? "\nAll context invariants hold." : `\n${failures} invariant(s) broken.`);
process.exit(failures === 0 ? 0 : 1);
