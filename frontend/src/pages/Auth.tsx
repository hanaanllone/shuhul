import { useState } from "react";
import type { FormEvent } from "react";
import { TextField } from "../components/ui";
import { errorMessage, post } from "../lib/api";
import type { User } from "../lib/types";

interface Props {
  mode: "login" | "signup";
  onNavigate: (path: string) => void;
  onAuthenticated: (user: User) => void;
}

export default function Auth({ mode, onNavigate, onAuthenticated }: Props) {
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [organisation, setOrganisation] = useState("");
  const [error, setError] = useState("");
  const [busy, setBusy] = useState(false);

  const isSignup = mode === "signup";

  async function submit(event: FormEvent) {
    event.preventDefault();
    setBusy(true);
    setError("");

    try {
      const data = await post<{ user: User }>(`/api/auth/${isSignup ? "signup" : "login"}`, {
        email,
        password,
        organisation,
      });
      onAuthenticated(data.user);
    } catch (problem) {
      setError(errorMessage(problem, "Could not sign in."));
    } finally {
      setBusy(false);
    }
  }

  return (
    <main className="auth">
      <div className="auth-brand">
        <button className="auth-wordmark" onClick={() => onNavigate("")}>SHUHUL</button>

        <div className="auth-notes">
          <p>
            Urban development across South Asia is often driven by infrastructure needs without
            giving environmental impact the same weight during planning.
          </p>
          <p>
            We are seeing urban green spaces become smaller, trees being removed, water bodies and
            natural areas being affected, and development happening without enough accountability
            for the environmental cost.
          </p>
        </div>
      </div>

      <form className="auth-card on-light" onSubmit={submit}>
        <h1 className="auth-title">{isSignup ? "Sign up" : "Login"}</h1>

        <TextField label="Email" type="email" value={email} onChange={setEmail} required autoComplete="email" />
        <TextField
          label="Password"
          type="password"
          value={password}
          onChange={setPassword}
          required
          autoComplete={isSignup ? "new-password" : "current-password"}
          hint={isSignup ? "At least 8 characters." : undefined}
        />
        {isSignup && (
          <TextField
            label="Organisation"
            value={organisation}
            onChange={setOrganisation}
            required
            autoComplete="organization"
          />
        )}

        {error && <p className="message" style={{ marginTop: 14 }}>{error}</p>}

        <button className="btn is-dark is-block" style={{ marginTop: 22 }} disabled={busy}>
          {busy ? "Please wait..." : isSignup ? "Create account" : "Login"}
        </button>

        <p className="note" style={{ marginTop: 16 }}>
          {isSignup ? "Already have an account? " : "New to Shuhul? "}
          <button type="button" className="link-btn" onClick={() => onNavigate(isSignup ? "login" : "signup")}>
            {isSignup ? "Login" : "Create an account"}
          </button>
        </p>
      </form>
    </main>
  );
}
