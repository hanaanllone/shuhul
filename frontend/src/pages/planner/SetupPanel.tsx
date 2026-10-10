import { CheckField, PanelSection, SelectField, SliderField, TextField } from "../../components/ui";
import type { LatLng } from "../../lib/types";
import type { PointName } from "./PlannerMap";

export interface PlannerForm {
  projectName: string;
  constructionType: string;
  widthMeters: number;
  priorities: Record<string, number>;
  constraints: Record<string, boolean>;
}

export const DEFAULT_FORM: PlannerForm = {
  projectName: "",
  constructionType: "road",
  widthMeters: 20,
  priorities: {
    treePriority: 60,
    greeneryPriority: 60,
    waterPriority: 60,
    heatPriority: 60,
    floodPriority: 60,
    shortestPriority: 50,
    constructionPriority: 50,
  },
  constraints: {
    heritage: false,
    water: false,
    forest: false,
    flood: false,
    steepSlope: false,
  },
};

// Each priority, with one plain line on what moving it does.
const PRIORITIES: [string, string, string][] = [
  ["treePriority", "Protect trees", "Higher keeps routes away from trees."],
  ["greeneryPriority", "Protect green space", "Higher keeps routes off fields, parks and other green land."],
  ["waterPriority", "Protect water", "Higher keeps routes away from rivers, lakes and wet ground."],
  ["heatPriority", "Avoid adding heat", "Higher avoids land that would warm most if paved."],
  ["floodPriority", "Avoid flood-prone land", "Higher avoids low ground where water has stood before."],
  ["shortestPriority", "Keep the route short", "Higher makes the balanced route more direct and less careful of the land."],
  ["constructionPriority", "Ease of construction", "Higher avoids steep slopes and buildings in the way."],
];

const CONSTRAINTS: [string, string, string][] = [
  ["heritage", "Heritage sites", "Stay 100 m clear of mapped heritage points"],
  ["water", "Water bodies", "Never cross rivers, lakes or ponds. Points on opposite banks cannot be joined"],
  ["forest", "Hill forest", "Dense tree cover on slopes"],
  ["flood", "Recorded flood land", "Land where water has been recorded since 1984"],
  ["steepSlope", "Very steep terrain", "Slopes of 30 degrees or more"],
];

interface Props {
  form: PlannerForm;
  onChange: (form: PlannerForm) => void;
  points: Record<PointName, LatLng | null>;
  picking: PointName | null;
  onPickPoint: (name: PointName | null) => void;
  running: { stage: string; progress: number } | null;
  error: string;
  // True when a saved project is open, so it can be updated in place.
  existing: boolean;
  onRun: (mode: "new" | "update") => void;
}

function pointText(point: LatLng | null) {
  return point ? `${point.lat.toFixed(5)}, ${point.lng.toFixed(5)}` : "Not set";
}

export default function SetupPanel({ form, onChange, points, picking, onPickPoint, running, error, existing, onRun }: Props) {
  const ready = Boolean(points.A && points.B);

  return (
    <>
      <PanelSection heading="Project details">
        <TextField
          label="Project name"
          value={form.projectName}
          placeholder="Untitled Project"
          onChange={(projectName) => onChange({ ...form, projectName })}
        />
        <SelectField
          label="Construction type"
          value={form.constructionType}
          options={[
            { value: "road", label: "Road" },
            { value: "bridge", label: "Bridge" },
            { value: "flyover", label: "Flyover" },
          ]}
          onChange={(constructionType) => onChange({ ...form, constructionType })}
        />
        <SliderField
          label="Corridor width"
          value={form.widthMeters}
          min={6}
          max={60}
          step={2}
          unit=" m"
          info="How wide a strip of land the project takes."
          onChange={(widthMeters) => onChange({ ...form, widthMeters })}
        />
      </PanelSection>

      <PanelSection heading="From and to">
        <div className="point-row">
          {(["A", "B"] as PointName[]).map((name) => (
            <div className="point-box" key={name}>
              <b>Point {name}</b>
              {pointText(points[name])}
              <div style={{ marginTop: 8 }}>
                <button
                  type="button"
                  className="btn is-dark is-small"
                  onClick={() => onPickPoint(picking === name ? null : name)}
                >
                  {picking === name ? "Cancel" : points[name] ? "Move" : "Set on map"}
                </button>
              </div>
            </div>
          ))}
        </div>
        <p className="field-hint">Both points have to be in the same district.</p>
      </PanelSection>

      <PanelSection heading="Priorities">
        {PRIORITIES.map(([key, label, info]) => (
          <SliderField
            key={key}
            label={label}
            info={info}
            value={form.priorities[key]}
            onChange={(value) => onChange({ ...form, priorities: { ...form.priorities, [key]: value } })}
          />
        ))}
      </PanelSection>

      <PanelSection heading="Never build on">
        {CONSTRAINTS.map(([key, label, hint]) => (
          <CheckField
            key={key}
            label={label}
            hint={hint}
            checked={form.constraints[key]}
            onChange={(checked) => onChange({ ...form, constraints: { ...form.constraints, [key]: checked } })}
          />
        ))}
      </PanelSection>

      <PanelSection>
        {error && <p className="message" style={{ marginBottom: 12 }}>{error}</p>}

        {running ? (
          <>
            <div className="progress" role="progressbar" aria-valuenow={running.progress} aria-valuemin={0} aria-valuemax={100}>
              <span style={{ width: `${running.progress}%` }} />
            </div>
            <p className="note" style={{ marginTop: 8 }}>{running.stage}</p>
          </>
        ) : existing ? (
          <>
            <button type="button" className="btn is-dark is-block" disabled={!ready} onClick={() => onRun("update")}>
              Update this project
            </button>
            <button
              type="button"
              className="btn is-ghost is-block"
              style={{ marginTop: 8 }}
              disabled={!ready}
              onClick={() => onRun("new")}
            >
              Save as a new project
            </button>
            <p className="field-hint">
              Updating replaces this project's routes. Saving as new keeps them and adds another project.
            </p>
          </>
        ) : (
          <button type="button" className="btn is-dark is-block" disabled={!ready} onClick={() => onRun("new")}>
            Plan routes
          </button>
        )}

        {!ready && !running && <p className="field-hint">Set points A and B to plan routes.</p>}
      </PanelSection>
    </>
  );
}
