import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import test from "node:test";

const pages = ["MapPage", "RegistryPage", "InspectionPage", "UserManagementPage"];

test("page headers use the shared sync control without losing their refresh registration", () => {
  const navbar = readFileSync(new URL("./DashboardLayout.jsx", import.meta.url), "utf8");
  assert.match(navbar, /appRefresh\?\.run\("manual"\)/);
  assert.match(navbar, /className=\{`app-sync-now/);

  for (const name of pages) {
    const source = readFileSync(new URL(`../pages/${name}.jsx`, import.meta.url), "utf8");
    assert.match(source, /useAppDataRefresh\(/, `${name} still registers for header sync`);
    assert.doesNotMatch(source, /quick-refresh-btn/, `${name} no longer shows a duplicate refresh button`);
  }
});
