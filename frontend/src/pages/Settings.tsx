import { Panel, PanelSection } from "../components/ui";
import type { User } from "../lib/types";

interface Props {
  user: User;
  onLogout: () => void;
}

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

export default function Settings({ user, onLogout }: Props) {
  return (
    <main className="page">
      <div className="page-head">
        <h1 className="page-title">Settings</h1>
      </div>

      <div className="air-grid">
        <Panel title="Account">
          <table className="table">
            <tbody>
              <tr><td>Email</td><td>{user.email}</td></tr>
              <tr><td>Organisation</td><td>{user.organisation}</td></tr>
            </tbody>
          </table>
          <PanelSection>
            <button className="btn is-dark" onClick={onLogout}>Sign out</button>
          </PanelSection>
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
