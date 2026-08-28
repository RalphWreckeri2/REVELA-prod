import { API_ORIGIN } from "./api";

export const changePasswordRequest = async (payload, token) => {
  const response = await fetch(
    `${API_ORIGIN}/api/auth/change-password`,
    {
      method: "PUT",
      headers: {
        "Content-Type": "application/json",
        Authorization: `Bearer ${token}`,
      },
      body: JSON.stringify(payload),
    },
  );

  if (!response.ok) {
    const errorData = await response.json();
    throw new Error(errorData.error || "Failed to change password.");
  }
  return response.json();
};

export const setup2faRequest = async (token) => {
  const response = await fetch(`${API_ORIGIN}/api/auth/setup-2fa`, {
    method: "POST",
    headers: {
      "Content-Type": "application/json",
      Authorization: `Bearer ${token}`,
    },
  });

  if (!response.ok) {
    const errorData = await response.json();
    throw new Error(
      errorData.message || errorData.error || "Failed to initialize 2FA setup.",
    );
  }

  return await response.json();
};

export const verify2faSetupRequest = async (data, token) => {
  const response = await fetch(
    `${API_ORIGIN}/api/auth/verify-2fa-setup`,
    {
      method: "POST",
      headers: {
        "Content-Type": "application/json",
        Authorization: `Bearer ${token}`,
      },
      body: JSON.stringify(data), // e.g., { code: "123456" }
    },
  );

  if (!response.ok) {
    const errorData = await response.json();
    throw new Error(
      errorData.message || errorData.error || "Invalid 2FA code.",
    );
  }

  return await response.json();
};
