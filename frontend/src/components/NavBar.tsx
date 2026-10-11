import { useEffect, useRef, useState } from "react";
import type { ReactNode } from "react";
import type { User } from "../lib/types";

interface NavItem {
  label: string;
  path?: string;
  children?: { label: string; path: string; hint: string }[];
}

// Related tools sit together under one heading.
const ITEMS: NavItem[] = [
  { label: "Home", path: "home" },
  { label: "Watch", path: "watch" },
  { label: "Route plan", path: "plan" },
  {
    label: "Environment",
    children: [
      { label: "Area analysis", path: "environment/area", hint: "Measure any area or district" },
      { label: "Ecological stress", path: "environment/stress", hint: "Where pressure is highest, and why" },
      { label: "Where to build", path: "environment/sites", hint: "Land that would cost the least to build on" },
      { label: "Air and temperature", path: "environment/air", hint: "Today and the past year" },
    ],
  },
  { label: "Smart city Srinagar", path: "smart-city" },
];

interface Props {
  current: string;
  user: User | null;
  onNavigate: (path: string) => void;
  onLogout: () => void;
}

function Icon({ children }: { children: ReactNode }) {
  return (
    <svg
      width="20"
      height="20"
      viewBox="0 0 24 24"
      fill="none"
      stroke="currentColor"
      strokeWidth="1.8"
      strokeLinecap="round"
      strokeLinejoin="round"
      aria-hidden="true"
    >
      {children}
    </svg>
  );
}

export default function NavBar({ current, user, onNavigate, onLogout }: Props) {
  const [open, setOpen] = useState<string | null>(null);
  const bar = useRef<HTMLElement>(null);

  // Menus close on a click elsewhere or on Escape.
  useEffect(() => {
    function onPointer(event: MouseEvent) {
      if (!bar.current?.contains(event.target as Node)) setOpen(null);
    }
    function onKey(event: KeyboardEvent) {
      if (event.key === "Escape") setOpen(null);
    }

    document.addEventListener("mousedown", onPointer);
    document.addEventListener("keydown", onKey);
    return () => {
      document.removeEventListener("mousedown", onPointer);
      document.removeEventListener("keydown", onKey);
    };
  }, []);

  function go(path: string) {
    setOpen(null);
    onNavigate(path);
  }

  const who = user?.name || user?.email || "Profile";

  return (
    <header className="nav" ref={bar}>
      <button className="wordmark" onClick={() => go("home")}>SHUHUL</button>

      <nav className="nav-links" aria-label="Main">
        {ITEMS.map((item) =>
          item.children ? (
            <div className="nav-menu" key={item.label}>
              <button
                className={`nav-link ${item.children.some((child) => child.path === current) ? "is-current" : ""}`}
                aria-expanded={open === item.label}
                aria-haspopup="menu"
                onClick={() => setOpen(open === item.label ? null : item.label)}
              >
                {item.label} ▾
              </button>

              {open === item.label && (
                <div className="nav-dropdown" role="menu">
                  {item.children.map((child) => (
                    <button key={child.path} role="menuitem" onClick={() => go(child.path)}>
                      {child.label}
                      <small>{child.hint}</small>
                    </button>
                  ))}
                </div>
              )}
            </div>
          ) : (
            <button
              key={item.label}
              className={`nav-link ${current.split("/")[0] === item.path ? "is-current" : ""}`}
              onClick={() => go(item.path as string)}
            >
              {item.label}
            </button>
          )
        )}
      </nav>

      <div className="nav-icons">
        <button
          className={`nav-icon ${current === "profile" ? "is-current" : ""}`}
          aria-label={`Profile: ${who}`}
          title={`Profile: ${who}`}
          onClick={() => go("profile")}
        >
          <Icon>
            <circle cx="12" cy="8" r="4" />
            <path d="M4 21v-1a6 6 0 0 1 6-6h4a6 6 0 0 1 6 6v1" />
          </Icon>
        </button>

        <button
          className={`nav-icon ${current === "settings" ? "is-current" : ""}`}
          aria-label="Settings"
          title="Settings"
          onClick={() => go("settings")}
        >
          <Icon>
            <circle cx="12" cy="12" r="3" />
            <circle cx="12" cy="12" r="7" />
            <path d="M20 12h2.2M1.8 12H4M12 4V1.8M12 22.2V20M17.66 17.66l1.55 1.55M4.79 4.79l1.55 1.55M17.66 6.34l1.55-1.55M4.79 19.21l1.55-1.55" />
          </Icon>
        </button>

        <button className="nav-icon" aria-label="Sign out" title="Sign out" onClick={onLogout}>
          <Icon>
            <path d="M9 21H5a2 2 0 0 1-2-2V5a2 2 0 0 1 2-2h4" />
            <path d="M16 17l5-5-5-5M21 12H9" />
          </Icon>
        </button>
      </div>
    </header>
  );
}
