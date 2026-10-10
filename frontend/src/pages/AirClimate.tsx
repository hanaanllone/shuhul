import { useEffect, useState } from "react";
import DistrictSelect, { useDistricts } from "../components/DistrictSelect";
import { Panel, PanelSection, Stat } from "../components/ui";
import { api, errorMessage } from "../lib/api";
import { num, signed } from "../lib/format";

interface MonthAir {
  pm2_5: number | null;
  band: string | null;
  days_over_standard: number;
}

interface Climate {
  weather: {
    temperature_c?: number;
    today_max_c?: number;
    today_min_c?: number;
    normal_max_for_month_c?: number;
    today_vs_normal_c?: number;
    july_mean_max_c?: Record<string, number | null>;
    hottest_day?: { date: string; temperature_c: number } | null;
    period?: string;
  } | null;
  air: {
    pm2_5?: number | null;
    pm2_5_band?: string | null;
    pm10?: number | null;
    no2?: number | null;
    o3?: number | null;
    days_over_standard?: number;
    days_with_data?: number;
    standard_pm2_5?: number;
    annual_mean_pm2_5?: number | null;
    monthly_mean_pm2_5?: Record<string, MonthAir>;
  } | null;
  unavailable: string[];
  method: { weather_source: string; air_source: string; resolution: string; air_note: string; bands: string; confidence: string };
}

const MONTHS = ["Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"];

interface BarItem {
  label: string;
  value: number | null;
}

// A plain bar per value, with the number written under it. Bars start at
// `base`; anything other than zero is stated under the chart by the caller.
function Bars({ items, unit, base = 0 }: { items: BarItem[]; unit: string; base?: number }) {
  const top = Math.max(...items.map((item) => item.value || 0), base + 1);

  return (
    <>
      <div className="bars" role="img" aria-label={items.map((item) => `${item.label}: ${num(item.value, 1)} ${unit}`).join(", ")}>
        {items.map((item, index) => (
          <div
            key={index}
            className="bar"
            title={`${item.label}: ${num(item.value, 1)} ${unit}`}
            style={{ height: `${Math.max(2, (100 * ((item.value || 0) - base)) / (top - base))}%` }}
          />
        ))}
      </div>
      <div className="bar-labels">
        {items.map((item, index) => (
          <span key={index}>
            {item.label}
            <br />
            {num(item.value, 0)}
          </span>
        ))}
      </div>
    </>
  );
}

export default function AirClimate() {
  const districts = useDistricts();
  const [district, setDistrict] = useState("sxr");
  const [data, setData] = useState<Climate | null>(null);
  const [error, setError] = useState("");

  useEffect(() => {
    setData(null);
    setError("");

    api<Climate>(`/api/climate/${district}`)
      .then(setData)
      .catch((problem) => setError(errorMessage(problem, "Air and temperature data could not be loaded.")));
  }, [district]);

  const weather = data?.weather;
  const air = data?.air;

  const summers = Object.entries(weather?.july_mean_max_c || {}).map(([year, value]) => ({
    label: `'${year.slice(2)}`,
    value,
  }));
  // The year covers thirteen calendar months, so the first and last share a
  // name: the first one and each January carry their year.
  const months = Object.entries(air?.monthly_mean_pm2_5 || {}).map(([month, value], index) => {
    const name = MONTHS[Number(month.slice(5, 7)) - 1];
    return {
      label: index === 0 || name === "Jan" ? `${name} '${month.slice(2, 4)}` : name,
      value: value.pm2_5,
    };
  });

  // Temperature has no meaningful zero, so its bars start just under the
  // coolest July and the chart says so.
  const coolest = Math.min(...summers.map((item) => item.value || Infinity));
  const summerBase = Number.isFinite(coolest) ? Math.floor(coolest) - 2 : 0;

  return (
    <main className="page">
      <div className="page-head">
        <h1 className="page-title">Air and temperature</h1>
        <div className="page-control">
          <DistrictSelect districts={districts} value={district} onChange={setDistrict} />
        </div>
      </div>

      {error && <p className="message">{error}</p>}
      {!data && !error && <p className="muted">Loading...</p>}

      {data && (
        <>
          <div className="air-grid">
            <Panel title="Temperature">
              {weather ? (
                <>
                  <div className="stat-grid">
                    <Stat label="Now" value={`${num(weather.temperature_c, 1)} °C`} />
                    <Stat
                      label="Today"
                      value={`${num(weather.today_min_c, 0)} to ${num(weather.today_max_c, 0)} °C`}
                    />
                    <Stat
                      label="Against usual"
                      value={weather.today_vs_normal_c === undefined ? "—" : `${signed(weather.today_vs_normal_c, 1)} °C`}
                      note={`Usual high this month ${num(weather.normal_max_for_month_c, 1)} °C`}
                    />
                  </div>

                  {summers.length > 0 && (
                    <PanelSection heading="Average July daily high, °C">
                      <Bars items={summers} unit="°C" base={summerBase} />
                      <p className="note" style={{ marginTop: 8 }}>Bars start at {summerBase} °C, not zero.</p>
                    </PanelSection>
                  )}

                  {weather.hottest_day && (
                    <PanelSection>
                      <p>
                        Hottest day, {weather.period}: <b>{num(weather.hottest_day.temperature_c, 1)} °C</b> on{" "}
                        {weather.hottest_day.date}.
                      </p>
                    </PanelSection>
                  )}
                </>
              ) : (
                <p className="note">Temperature is not available right now.</p>
              )}
            </Panel>

            <Panel title="Air">
              {air ? (
                <>
                  <div className="stat-grid">
                    <Stat
                      label="Fine particles now"
                      value={`${num(air.pm2_5, 0)} µg/m³`}
                      note={air.pm2_5_band || undefined}
                    />
                    <Stat label="Past year average" value={`${num(air.annual_mean_pm2_5, 0)} µg/m³`} />
                    <Stat
                      label="Days over the standard"
                      value={num(air.days_over_standard)}
                      note={`of ${num(air.days_with_data)}, limit ${air.standard_pm2_5} µg/m³`}
                    />
                  </div>

                  {months.length > 0 && (
                    <PanelSection heading="Monthly average PM2.5, µg/m³">
                      <Bars items={months} unit="µg/m³" />
                    </PanelSection>
                  )}
                </>
              ) : (
                <p className="note">Air quality is not available right now.</p>
              )}
            </Panel>
          </div>

          <p className="note on-dark" style={{ marginTop: 24, maxWidth: 900 }}>
            {data.method.resolution} {data.method.air_note} {data.method.bands} Sources:{" "}
            {data.method.weather_source}; {data.method.air_source}. Confidence: {data.method.confidence}.
          </p>
        </>
      )}
    </main>
  );
}
