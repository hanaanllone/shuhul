// frontend/src/auth/session.ts

export interface ShuhulUser {
  id?: number | string;
  email: string;
  organisation: string;
}

export interface AuthResponse {
  user: ShuhulUser;
  message?: string;
}

const API_BASE =
  import.meta.env.VITE_API_URL || "http://localhost:5000";

/**
 * Login against the backend.
 */
export async function login(
  email: string,
  password: string,
  organisation: string
): Promise<ShuhulUser> {
  const response = await fetch(`${API_BASE}/api/auth/login`, {
    method: "POST",
    headers: {
      "Content-Type": "application/json",
    },
    credentials: "include",
    body: JSON.stringify({
      email,
      password,
      organisation,
    }),
  });

  const data = await response.json();

  if (!response.ok) {
    throw new Error(
      data.message || data.error || "Login failed."
    );
  }

  return data.user;
}

/**
 * Create a new account.
 */
export async function signup(
  email: string,
  password: string,
  organisation: string
): Promise<ShuhulUser> {
  const response = await fetch(`${API_BASE}/api/auth/signup`, {
    method: "POST",
    headers: {
      "Content-Type": "application/json",
    },
    credentials: "include",
    body: JSON.stringify({
      email,
      password,
      organisation,
    }),
  });

  const data = await response.json();

  if (!response.ok) {
    throw new Error(
      data.message || data.error || "Signup failed."
    );
  }

  return data.user;
}

/**
 * Ask the backend whether a user is currently logged in.
 */
export async function getSession(): Promise<ShuhulUser | null> {
  try {
    const response = await fetch(
      `${API_BASE}/api/auth/session`,
      {
        method: "GET",
        credentials: "include",
      }
    );

    if (!response.ok) {
      return null;
    }

    const data = await response.json();

    return data.user || null;
  } catch {
    return null;
  }
}

/**
 * Logout from the backend.
 */
export async function logout(): Promise<void> {
  try {
    await fetch(`${API_BASE}/api/auth/logout`, {
      method: "POST",
      credentials: "include",
    });
  } catch {
    // Ignore network errors during logout.
  }
}

/**
 * Async version of isLoggedIn.
 */
export async function isLoggedIn(): Promise<boolean> {
  const user = await getSession();
  return user !== null;
}