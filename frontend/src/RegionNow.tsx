import { useEffect, useState } from "react";
import { apiFetch } from "./frontend_api";

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
    days_over_standard?: number;
    days_with_data?: number;
    standard_pm2_5?: number;
    annual_mean_pm2_5?: number | null;
    monthly_mean_pm2_5?: Record<string, MonthAir>;
  } | null;
  unavailable: string[];
  method: { resolution: string; air_note: string; confidence: string };
}

interface Props {
  district?: string;
  title?: string;
}

function show(value: number | null | undefined, unit = "") {
  return value === null || value === undefined ? "not available" : `${value}${unit}`;
}

// Plain markup only. Styling is left to the page that uses it.
export default function RegionNow({ district = "sxr", title = "Srinagar now" }: Props) {
  const [data, setData] = useState<Climate | null>(null);
  const [error, setError] = useState("");

  useEffect(() => {
    apiFetch(`/api/climate/${district}`)
      .then(setData)
      .catch(() => setError("Air and temperature data could not be loaded."));
  }, [district]);

  if (error) return <section><p>{error}</p></section>;
  if (!data) return <section><p>Loading air and temperature...</p></section>;

  const { weather, air } = data;
  const months = Object.entries(air?.monthly_mean_pm2_5 || {});
  const summers = Object.entries(weather?.july_mean_max_c || {});

  return (
    <section>
      <h2>{title}</h2>

      <h3>Temperature</h3>
      {weather ? (
        <dl>
          <dt>Now</dt>
          <dd>{show(weather.temperature_c, " °C")}</dd>
          <dt>Today</dt>
          <dd>{show(weather.today_min_c, " °C")} to {show(weather.today_max_c, " °C")}</dd>
          <dt>Usual daily high this month</dt>
          <dd>
            {show(weather.normal_max_for_month_c, " °C")}
            {weather.today_vs_normal_c !== undefined &&
              ` (today is ${weather.today_vs_normal_c > 0 ? "+" : ""}${weather.today_vs_normal_c} °C against that)`}
          </dd>
          {weather.hottest_day && (
            <>
              <dt>Hottest day, {weather.period}</dt>
              <dd>{weather.hottest_day.temperature_c} °C on {weather.hottest_day.date}</dd>
            </>
          )}
        </dl>
      ) : (
        <p>Temperature is not available right now.</p>
      )}

      {summers.length > 0 && (
        <table>
          <caption>Average July daily high, °C</caption>
          <thead><tr>{summers.map(([year]) => <th key={year}>{year}</th>)}</tr></thead>
          <tbody><tr>{summers.map(([year, value]) => <td key={year}>{show(value)}</td>)}</tr></tbody>
        </table>
      )}

      <h3>Air</h3>
      {air ? (
        <dl>
          <dt>Fine particles (PM2.5) now</dt>
          <dd>{show(air.pm2_5, " µg/m³")}{air.pm2_5_band ? `, ${air.pm2_5_band}` : ""}</dd>
          <dt>Past year average</dt>
          <dd>{show(air.annual_mean_pm2_5, " µg/m³")}</dd>
          <dt>Days over the national standard of {air.standard_pm2_5} µg/m³</dt>
          <dd>{show(air.days_over_standard)} of {show(air.days_with_data)} days</dd>
        </dl>
      ) : (
        <p>Air quality is not available right now.</p>
      )}

      {months.length > 0 && (
        <table>
          <caption>Monthly average PM2.5, µg/m³, and days over the standard</caption>
          <thead><tr><th>Month</th><th>PM2.5</th><th>Band</th><th>Days over</th></tr></thead>
          <tbody>
            {months.map(([month, value]) => (
              <tr key={month}>
                <td>{month}</td>
                <td>{show(value.pm2_5)}</td>
                <td>{value.band || ""}</td>
                <td>{value.days_over_standard}</td>
              </tr>
            ))}
          </tbody>
        </table>
      )}

      <p>
        <small>
          {data.method.resolution} {data.method.air_note} Confidence: {data.method.confidence}.
        </small>
      </p>
    </section>
  );
}
