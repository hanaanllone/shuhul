import { useState } from "react";
import type { FormEvent } from "react";
import { Panel, TextField } from "../components/ui";
import { errorMessage, post } from "../lib/api";
import type { User } from "../lib/types";

interface Props {
  user: User;
  onChange: (user: User) => void;
}

export default function Profile({ user, onChange }: Props) {
  const [name, setName] = useState(user.name || "");
  const [organisation, setOrganisation] = useState(user.organisation);
  const [busy, setBusy] = useState(false);
  const [saved, setSaved] = useState(false);
  const [error, setError] = useState("");

  async function save(event: FormEvent) {
    event.preventDefault();
    setBusy(true);
    setSaved(false);
    setError("");

    try {
      const data = await post<{ user: User }>("/api/account/profile", { name, organisation });
      onChange(data.user);
      setSaved(true);
    } catch (problem) {
      setError(errorMessage(problem, "Could not save your profile."));
    } finally {
      setBusy(false);
    }
  }

  return (
    <main className="page">
      <div className="page-head">
        <h1 className="page-title">Profile</h1>
      </div>

      <div className="narrow">
        <Panel title="Your details">
          <form onSubmit={save}>
            <TextField label="Name" value={name} onChange={setName} autoComplete="name" />
            <TextField
              label="Organisation"
              value={organisation}
              onChange={setOrganisation}
              required
              autoComplete="organization"
            />
            <label className="field">
              <span className="field-label">Email</span>
              <input className="input" value={user.email} disabled />
              <div className="field-hint">The email you sign in with cannot be changed here.</div>
            </label>

            {error && <p className="message" style={{ marginTop: 14 }}>{error}</p>}
            {saved && <p className="note" style={{ marginTop: 14 }}>Saved.</p>}

            <button className="btn is-dark" style={{ marginTop: 18 }} disabled={busy}>
              {busy ? "Saving..." : "Save"}
            </button>
          </form>
        </Panel>
      </div>
    </main>
  );
}
