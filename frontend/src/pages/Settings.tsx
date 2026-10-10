import { useState } from "react";
import type { FormEvent } from "react";
import { Panel, TextField } from "../components/ui";
import { errorMessage, post } from "../lib/api";

const SOURCES: [string, string][] = [
  ["Base map", "OpenStreetMap contributors, Humanitarian style by HOT"],
  ["Surface temperature and yearly change", "Landsat 8 and 9, USGS, summers of 2017 to 2025"],
  ["Vegetation and water indices", "Sentinel-2 composites"],
  ["Land cover", "ESA WorldCover 2021"],
  ["Water history and lost water", "JRC Global Surface Water, 1984 to 2021"],
  ["Detected buildings", "Microsoft building footprints"],
  ["Named buildings, roads and heritage", "OpenStreetMap contributors"],
  ["Air and weather", "Open-Meteo: CAMS air quality model and ERA5 reanalysis"],
  ["News reports", "Greater Kashmir, Free Press Kashmir and Kashmir Life, linked to the source"],
];

function ChangePassword() {
  const [current, setCurrent] = useState("");
  const [next, setNext] = useState("");
  const [again, setAgain] = useState("");
  const [busy, setBusy] = useState(false);
  const [done, setDone] = useState(false);
  const [error, setError] = useState("");

  async function submit(event: FormEvent) {
    event.preventDefault();
    setDone(false);
    setError("");

    if (next !== again) {
      setError("The two new passwords are not the same.");
      return;
    }

    setBusy(true);
    try {
      await post("/api/account/password", { current, new: next });
      setCurrent("");
      setNext("");
      setAgain("");
      setDone(true);
    } catch (problem) {
      setError(errorMessage(problem, "Could not change the password."));
    } finally {
      setBusy(false);
    }
  }

  return (
    <form onSubmit={submit}>
      <TextField
        label="Current password"
        type="password"
        value={current}
        onChange={setCurrent}
        required
        autoComplete="current-password"
      />
      <TextField
        label="New password"
        type="password"
        value={next}
        onChange={setNext}
        required
        autoComplete="new-password"
        hint="At least 8 characters."
      />
      <TextField
        label="New password again"
        type="password"
        value={again}
        onChange={setAgain}
        required
        autoComplete="new-password"
      />

      {error && <p className="message" style={{ marginTop: 14 }}>{error}</p>}
      {done && <p className="note" style={{ marginTop: 14 }}>Password changed.</p>}

      <button className="btn is-dark" style={{ marginTop: 18 }} disabled={busy}>
        {busy ? "Changing..." : "Change password"}
      </button>
    </form>
  );
}

export default function Settings() {
  return (
    <main className="page">
      <div className="page-head">
        <h1 className="page-title">Settings</h1>
      </div>

      <div className="air-grid">
        <Panel title="Password">
          <ChangePassword />
        </Panel>

        <Panel title="Where the data comes from">
          <table className="table">
            <tbody>
              {SOURCES.map(([what, where]) => (
                <tr key={what}>
                  <td>{what}</td>
                  <td>{where}</td>
                </tr>
              ))}
            </tbody>
          </table>
          <p className="note" style={{ marginTop: 12 }}>
            Shuhul supports planning decisions; it does not make them. Every figure is a screening
            estimate from open data and should be checked on the ground before it is relied on.
          </p>
        </Panel>
      </div>
    </main>
  );
}
