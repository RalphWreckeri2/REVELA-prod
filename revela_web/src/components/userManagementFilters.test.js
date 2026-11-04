import test from "node:test";
import assert from "node:assert/strict";
import { detectedUserRole, filterUsers, normalizeUserRole } from "./userManagementFilters.js";

const users = [
  { fullName: "Gio H. Reyes", email: "gio@example.com", userRole: "Admin" },
  { fullName: "Gina Cruz", email: "gina@example.com", userRole: "Inspector" },
  { fullName: "Alex Admin", email: "alex@example.com", userRole: "Admin" },
  { fullName: "Super User", email: "super@example.com", userRole: "System Administrator" },
];

test("search detects the unique matching role and clears it for ambiguous results", () => {
  assert.equal(detectedUserRole(users, "gio"), "Admin");
  assert.equal(detectedUserRole(users, "super"), "SUPER_ADMIN");
  assert.equal(detectedUserRole(users, "admin"), "all");
  assert.equal(detectedUserRole(users, "example.com"), "all");
  assert.equal(detectedUserRole(users, ""), "all");
});

test("role filtering treats legacy system administrator role as Super Admin", () => {
  assert.equal(normalizeUserRole("System Administrator"), "SUPER_ADMIN");
  assert.deepEqual(filterUsers(users, "", "SUPER_ADMIN"), [users[3]]);
  assert.deepEqual(filterUsers(users, "gio", "Admin"), [users[0]]);
});

test("search safely handles missing profile fields", () => {
  const incompleteUser = { fullName: null, email: null, phone: null, userRole: "Admin" };
  assert.deepEqual(filterUsers([incompleteUser], "admin"), [incompleteUser]);
});
