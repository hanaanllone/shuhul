import { useEffect, useState } from "react";
import ProjectThumb from "../components/ProjectThumb";
import { api, errorMessage } from "../lib/api";
import { day } from "../lib/format";
import type { ProjectSummary } from "../lib/types";

interface Props {
  onNavigate: (path: string) => void;
}

const STATUS_LABEL: Record<string, string> = {
  queued: "Waiting",
  running: "Analysing",
  completed: "Ready",
  failed: "Failed",
};

export default function Home({ onNavigate }: Props) {
  const [projects, setProjects] = useState<ProjectSummary[] | null>(null);
  const [error, setError] = useState("");

  useEffect(() => {
    api<{ projects: ProjectSummary[] }>("/api/projects")
      .then((data) => setProjects(data.projects))
      .catch((problem) => setError(errorMessage(problem, "Could not load projects.")));
  }, []);

  return (
    <main className="page">
      <div className="page-head">
        <h1 className="page-title is-plain">Home</h1>
      </div>

      <button className="project-card" onClick={() => onNavigate("plan")}>
        <div className="thumb thumb-new" aria-hidden="true">+</div>
        <span className="project-name">New Project</span>
      </button>

      <h2 className="page-sub" style={{ margin: "44px 0 20px" }}>Recent Projects</h2>

      {error && <p className="message">{error}</p>}
      {!projects && !error && <p className="muted">Loading projects...</p>}
      {projects?.length === 0 && (
        <p className="muted">No projects yet. Start one with New Project.</p>
      )}

      <div className="project-grid">
        {projects?.map((project) => (
          <button className="project-card" key={project.id} onClick={() => onNavigate(`plan/${project.id}`)}>
            <ProjectThumb preview={project.preview} />
            <span className="project-name">{project.project_name}</span>
            <span className="project-meta">
              {STATUS_LABEL[project.status] || project.status} · {day(project.created_at)}
            </span>
          </button>
        ))}
      </div>

      {projects && projects.length > 0 && (
        <p className="note" style={{ marginTop: 28 }}>
          Map data © OpenStreetMap contributors, Humanitarian style.
        </p>
      )}
    </main>
  );
}
