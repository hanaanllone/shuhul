import { useEffect, useRef, useState } from "react";
import type { User } from "../lib/types";

interface NavItem {
  label: string;
  path?: string;
  children?: { label: string; path: string; hint: string }[];
}

// Related tools sit together under one heading.
const ITEMS: NavItem[] = [
  { label: "Home", path: "home" },
  { label: "Route plan", path: "plan" },
  {
    label: "Environment",
    children: [
      { label: "Area analysis", path: "environment/area", hint: "Measure any area or district" },
      { label: "Ecological stress", path: "environment/stress", hint: "Where pressure is highest, and why" },
      { label: "Air and temperature", path: "environment/air", hint: "Today and the past year" },
    ],
  },
  { label: "Watch", path: "watch" },
];

interface Props {
  current: string;
  user: User | null;
  onNavigate: (path: string) => void;
  onLogout: () => void;
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

      <div className="nav-menu">
        <button
          className="nav-link"
          aria-expanded={open === "account"}
          aria-haspopup="menu"
          onClick={() => setOpen(open === "account" ? null : "account")}
        >
          {user?.organisation || "Account"} ▾
        </button>

        {open === "account" && (
          <div className="nav-dropdown align-right" role="menu">
            <button role="menuitem" onClick={() => go("settings")}>
              Settings
              <small>{user?.email}</small>
            </button>
            <button role="menuitem" onClick={onLogout}>Sign out</button>
          </div>
        )}
      </div>
    </header>
  );
}
