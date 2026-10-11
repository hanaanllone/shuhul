import { useEffect, useState } from "react";
import ErrorBoundary from "./components/ErrorBoundary";
import NavBar from "./components/NavBar";
import { api, post } from "./lib/api";
import type { User } from "./lib/types";
import AirClimate from "./pages/AirClimate";
import AreaAnalysis from "./pages/AreaAnalysis";
import Auth from "./pages/Auth";
import EcologicalStress from "./pages/EcologicalStress";
import Home from "./pages/Home";
import Landing from "./pages/Landing";
import Profile from "./pages/Profile";
import RoutePlanner from "./pages/RoutePlanner";
import Settings from "./pages/Settings";
import SiteFinder from "./pages/SiteFinder";
import Watch from "./pages/Watch";

// The address after "#/" decides the page: "plan", "plan/<id>",
// "environment/stress" and so on.
function readPath(): string {
  return window.location.hash.replace(/^#\/?/, "");
}

const PUBLIC_PATHS = ["", "login", "signup"];

export default function App() {
  const [user, setUser] = useState<User | null | undefined>(undefined);
  const [path, setPath] = useState(readPath);

  useEffect(() => {
    api<{ authenticated: boolean; user?: User }>("/api/auth/session")
      .then((data) => setUser(data.authenticated && data.user ? data.user : null))
      .catch(() => setUser(null));

    const onHashChange = () => setPath(readPath());
    window.addEventListener("hashchange", onHashChange);
    return () => window.removeEventListener("hashchange", onHashChange);
  }, []);

  function navigate(target: string) {
    window.location.hash = `/${target}`;
  }

  async function logout() {
    await post("/api/auth/logout").catch(() => undefined);
    setUser(null);
    navigate("");
  }

  if (user === undefined) return null;

  // ---------- Signed out ----------
  if (!user) {
    if (path === "login" || path === "signup") {
      return (
        <Auth
          key={path}
          mode={path}
          onNavigate={navigate}
          onAuthenticated={(signedIn) => {
            setUser(signedIn);
            navigate("home");
          }}
        />
      );
    }

    return <Landing onNavigate={navigate} />;
  }

  // ---------- Signed in ----------
  const current = PUBLIC_PATHS.includes(path) ? "home" : path;
  const [section, detail] = current.split("/");

  let page;
  if (section === "plan") {
    page = <RoutePlanner key={detail || "new"} projectId={detail} onNavigate={navigate} />;
  } else if (current === "environment/area") {
    page = <AreaAnalysis />;
  } else if (current === "environment/stress") {
    page = <EcologicalStress />;
  } else if (current === "environment/air") {
    page = <AirClimate />;
  } else if (current === "environment/sites") {
    page = <SiteFinder />;
  } else if (section === "watch") {
    page = <Watch onNavigate={navigate} />;
  } else if (section === "profile") {
    page = <Profile user={user} onChange={setUser} />;
  } else if (section === "settings") {
    page = <Settings />;
  } else {
    page = <Home onNavigate={navigate} />;
  }

  return (
    <>
      <NavBar current={current} user={user} onNavigate={navigate} onLogout={logout} />
      <ErrorBoundary resetKey={current}>{page}</ErrorBoundary>
    </>
  );
}
