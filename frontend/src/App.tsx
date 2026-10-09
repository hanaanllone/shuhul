import { useEffect, useState } from "react";
import LoginSignup from "./LoginSignup";
import CreateProject from "./CreateProject";
import Home from "./Home";
import AOIAnalysis from "./AoiAnalysis";
import Settings from "./Settings";
import { getSession } from "./auth/session";
import EcologicalStress from "./EcologicalStress";
import EnvironmentalWatch from "./EnvironmentalWatch";

type Page =
  | { name: "home" }
  | { name: "create" }
  | { name: "project"; id: string }
  | { name: "aoi" }
  | { name: "ecological-stress" }
  | { name: "environmental-watch" }
  | { name: "settings" };

function readPage(): Page {
  const hash = window.location.hash.replace(/^#\/?/, "");

  if (hash.startsWith("project/")) {
    const id = hash.slice("project/".length);
    if (id) return { name: "project", id };
  }

  if (hash === "create") return { name: "create" };
  if (hash === "aoi") return { name: "aoi" };
  if (hash === "ecological-stress") return { name: "ecological-stress" };
  if (hash === "environmental-watch") return { name: "environmental-watch" };
  if (hash === "settings") return { name: "settings" };

  return { name: "home" };
}

export default function App() {
  const [authenticated, setAuthenticated] = useState(false);
  const [checkingSession, setCheckingSession] = useState(true);
  const [page, setPage] = useState<Page>(readPage);

  useEffect(() => {
    async function checkSession() {
      const user = await getSession();
      setAuthenticated(user !== null);
      setCheckingSession(false);
    }

    checkSession();

    const handleHashChange = () => setPage(readPage());
    window.addEventListener("hashchange", handleHashChange);

    return () => window.removeEventListener("hashchange", handleHashChange);
  }, []);

  function navigate(target: string) {
    window.location.hash = `/${target}`;
  }

  function openProject(projectId: string) {
    window.location.hash = `/project/${projectId}`;
  }

  function handleLogout() {
    setAuthenticated(false);
    navigate("home");
  }

  if (checkingSession) {
    return <div style={{ minHeight: "100vh", padding: 30 }}>Loading Shuhul...</div>;
  }

  if (!authenticated) {
    return (
      <LoginSignup
        onLogin={() => {
          setAuthenticated(true);
          navigate("home");
        }}
      />
    );
  }

  if (page.name === "home") {
    return <Home onNavigate={navigate} onOpenProject={openProject} />;
  }

  if (page.name === "create") {
    return <CreateProject onNavigate={navigate} />;
  }

  if (page.name === "project") {
    return (
      <CreateProject
        projectId={page.id}
        onNavigate={navigate}
      />
    );
  }

  if (page.name === "aoi") {
    return <AOIAnalysis onNavigate={navigate} />;
  }
  if (page.name === "ecological-stress") {
    return <EcologicalStress onNavigate={navigate} />;
  }
  if (page.name === "environmental-watch") {
  return (
    <EnvironmentalWatch
      onNavigate={(path) => {
        window.location.hash = path;
      }}
    />
  );
}
  return <Settings onNavigate={navigate} onLogout={handleLogout} />;
}
