// Small building blocks used on every page: panels, tabs, stats and fields.

import type { ChangeEvent, ReactNode } from "react";

// ---------- Panel ----------

interface PanelProps {
  title?: string;
  tone?: "sage" | "ivory" | "dark";
  className?: string;
  children: ReactNode;
}

export function Panel({ title, tone = "sage", className = "", children }: PanelProps) {
  const toneClass = tone === "ivory" ? "is-ivory" : tone === "dark" ? "is-dark" : "";

  return (
    <section className={`panel ${toneClass} ${className}`}>
      {title && <h2 className="panel-title" style={{ marginBottom: 16 }}>{title}</h2>}
      {children}
    </section>
  );
}

export function PanelSection({ heading, children }: { heading?: string; children: ReactNode }) {
  return (
    <div className="panel-section">
      {heading && <h3 className="panel-heading">{heading}</h3>}
      {children}
    </div>
  );
}

// ---------- Tabs ----------

interface TabsProps<T extends string> {
  tabs: { id: T; label: string; disabled?: boolean }[];
  active: T;
  onChange: (id: T) => void;
}

export function Tabs<T extends string>({ tabs, active, onChange }: TabsProps<T>) {
  return (
    <div className="tabs" role="tablist">
      {tabs.map((tab) => (
        <button
          key={tab.id}
          role="tab"
          className="tab"
          aria-selected={tab.id === active}
          disabled={tab.disabled}
          onClick={() => onChange(tab.id)}
        >
          {tab.label}
        </button>
      ))}
    </div>
  );
}

// ---------- Stat ----------

export function Stat({ label, value, note }: { label: string; value: ReactNode; note?: string }) {
  return (
    <div className="stat">
      <div className="stat-label">{label}</div>
      <div className="stat-value">{value}</div>
      {note && <div className="stat-note">{note}</div>}
    </div>
  );
}

// ---------- Fields ----------

interface TextFieldProps {
  label: string;
  value: string;
  onChange: (value: string) => void;
  type?: string;
  placeholder?: string;
  hint?: string;
  required?: boolean;
  autoComplete?: string;
}

export function TextField({ label, value, onChange, type = "text", hint, ...rest }: TextFieldProps) {
  return (
    <label className="field">
      <span className="field-label">{label}</span>
      <input
        className="input"
        type={type}
        value={value}
        onChange={(event: ChangeEvent<HTMLInputElement>) => onChange(event.target.value)}
        {...rest}
      />
      {hint && <div className="field-hint">{hint}</div>}
    </label>
  );
}

interface SelectFieldProps {
  label: string;
  value: string;
  options: { value: string; label: string }[];
  onChange: (value: string) => void;
  hint?: string;
}

export function SelectField({ label, value, options, onChange, hint }: SelectFieldProps) {
  return (
    <label className="field">
      <span className="field-label">{label}</span>
      <select className="select" value={value} onChange={(event) => onChange(event.target.value)}>
        {options.map((option) => (
          <option key={option.value} value={option.value}>{option.label}</option>
        ))}
      </select>
      {hint && <div className="field-hint">{hint}</div>}
    </label>
  );
}

// A small "i" that says in a line what a setting does, on hover, focus or tap.
export function Info({ text }: { text: string }) {
  return (
    <span className="info" tabIndex={0} role="note" aria-label={text}>
      i
      <span className="info-text" aria-hidden="true">{text}</span>
    </span>
  );
}

interface SliderFieldProps {
  label: string;
  value: number;
  onChange: (value: number) => void;
  min?: number;
  max?: number;
  step?: number;
  unit?: string;
  info?: string;
}

export function SliderField({ label, value, onChange, min = 0, max = 100, step = 1, unit = "", info }: SliderFieldProps) {
  return (
    <label className="field">
      <span className="field-label">
        <span>
          {label}
          {info && <Info text={info} />}
        </span>
        <span className="field-value">{value}{unit}</span>
      </span>
      <input
        className="slider"
        type="range"
        min={min}
        max={max}
        step={step}
        value={value}
        onChange={(event) => onChange(Number(event.target.value))}
      />
    </label>
  );
}

interface CheckFieldProps {
  label: string;
  checked: boolean;
  onChange: (checked: boolean) => void;
  hint?: string;
}

export function CheckField({ label, checked, onChange, hint }: CheckFieldProps) {
  return (
    <label className="check">
      <input type="checkbox" checked={checked} onChange={(event) => onChange(event.target.checked)} />
      <span>
        {label}
        {hint && <small>{hint}</small>}
      </span>
    </label>
  );
}
