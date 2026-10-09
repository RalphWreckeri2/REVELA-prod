import { useState, useEffect, useCallback } from "react";
import { loginRequest, getMeRequest } from "../services/api";
import { AuthContext } from "./authContext";

export function AuthProvider({ children }) {
  const [token, setTokenState] = useState(() => localStorage.getItem("revela_token"));
  const [user, setUser] = useState(() => token === "dev-admin-token"
    ? { id: 1, fullName: "BPLO Administrator", role: "Admin", email: "admin@mataasnakahoy.gov.ph" }
    : null);

  const setToken = useCallback((newToken) => {
    setTokenState(newToken);
    if (newToken) {
      localStorage.setItem("revela_token", newToken);
    } else {
      localStorage.removeItem("revela_token");
    }
  }, []);

  useEffect(() => {
    if (!token || user || token === "dev-admin-token") return undefined;

    let isCurrent = true;
    const hydrateUser = async () => {
      try {
        const [me] = await Promise.all([
          getMeRequest(token),
          new Promise(resolve => setTimeout(resolve, 1000)),
        ]);
        if (!isCurrent) return;
        if (!["Admin", "SUPER_ADMIN", "System Administrator"].includes(me?.role)) {
          setToken(null);
        } else {
          setUser(me);
        }
      } catch {
        if (isCurrent) setToken(null);
      }
    };
    void hydrateUser();
    return () => { isCurrent = false; };
  }, [token, user, setToken]);

  async function login(email, password) {
    const data = await loginRequest(email, password);

    // If 2FA is required, return early without setting token
    if (data.status === "2fa_required") {
      return data;  // ← LoginPage checks this
    }

    // ── Role gate: block non-admin roles BEFORE the token is ever stored ──
    const role = data.user?.userRole;
    if (!["Admin", "SUPER_ADMIN", "System Administrator"].includes(role)) {
      throw new Error("Access denied. This portal is for Admin and Super Admin only.");
    }

    setToken(data.access_token);
    const me = await getMeRequest(data.access_token);
    setUser(me);
    return { ...data, user: me };
  }

  // Called after 2FA verification succeeds
  async function completeLogin(accessToken) {
    const me = await getMeRequest(accessToken);
    // Role gate: block non-admin roles from storing a session
    if (!["Admin", "SUPER_ADMIN", "System Administrator"].includes(me?.role)) {
      throw new Error("Access denied. This portal is for Admin and Super Admin only.");
    }
    setToken(accessToken);
    setUser(me);
    return me;
  }

  const refreshUser = useCallback(async () => {
    if (!token) return;
    try {
      const me = await getMeRequest(token);
      setUser(me);
    } catch {
      // Keep the current profile if a background refresh fails.
    }
  }, [token]);

  useEffect(() => {
    if (!token) return;
    const handleUserUpdate = () => {
      refreshUser();
    };
    window.addEventListener("revela:user-update", handleUserUpdate);
    window.addEventListener("revela:global-refresh", handleUserUpdate);
    return () => {
      window.removeEventListener("revela:user-update", handleUserUpdate);
      window.removeEventListener("revela:global-refresh", handleUserUpdate);
    };
  }, [token, refreshUser]);

  const logout = useCallback(() => {
    setToken(null);
    setUser(null);
  }, [setToken]);

  return (
    <AuthContext.Provider value={{ token, user, login, completeLogin, logout, refreshUser }}>
      {children}
    </AuthContext.Provider>
  );
}