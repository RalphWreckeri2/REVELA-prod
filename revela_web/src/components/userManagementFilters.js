export function normalizeUserRole(role) {
  const normalized = String(role || "").trim().toLowerCase();
  if (normalized === "admin") return "Admin";
  if (normalized === "inspector") return "Inspector";
  if (normalized === "super_admin" || normalized === "system administrator") return "SUPER_ADMIN";
  return String(role || "").trim();
}

function matchesUserSearch(user, query) {
  const fields = [user.fullName, user.email, user.phone, user.userRole];
  return fields.some(value => String(value || "").toLowerCase().includes(query));
}

export function detectedUserRole(users, search = "") {
  const query = search.trim().toLowerCase();
  if (!query) return "all";
  const roles = new Set(
    users.filter(user => matchesUserSearch(user, query))
      .map(user => normalizeUserRole(user.userRole))
      .filter(Boolean),
  );
  return roles.size === 1 ? [...roles][0] : "all";
}

export function filterUsers(users, search = "", role = "all") {
  const query = search.trim().toLowerCase();
  const normalizedRole = role === "all" ? "all" : normalizeUserRole(role);
  return users.filter(user => {
    const matchesRole = normalizedRole === "all" || normalizeUserRole(user.userRole) === normalizedRole;
    return matchesRole && (!query || matchesUserSearch(user, query));
  });
}
