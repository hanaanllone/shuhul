import { useEffect, useState } from "react";
import { apiFetch } from "./frontend_api";

interface Project {
  id: string;
  project_name: string;
  status: string;
  stage: string;
  progress: number;
  created_at: string;
  updated_at: string;
}

interface RecentWorkProps {
  onNavigate: (path: string) => void;
  onOpenProject: (projectId: string) => void;
}

const menuItems = [
  "Home",
  "AOI Analysis",
  "Environmental Watch",
  "Ecological Stress",
  "Thermal Compensation",
  "Environmental Analysis",
  "Settings",
];

export default function RecentWork({
  onNavigate,
  onOpenProject,
}: RecentWorkProps) {
  const [projects, setProjects] = useState<Project[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState("");

  async function loadProjects() {
    try {
      setLoading(true);
      const data = await apiFetch("/api/projects");
      setProjects(data.projects || []);
      setError("");
    } catch (err) {
      setError(err instanceof Error ? err.message : "Could not load projects.");
    } finally {
      setLoading(false);
    }
  }

  useEffect(() => {
    loadProjects();
  }, []);

  return (
    <>
      <style>{`
        * { box-sizing: border-box; }
        body { margin: 0; font-family: Arial, sans-serif; background: #f7f6f1; }
        .page { min-height: 100vh; padding: 24px 32px; }
        .layout {
          display: grid;
          grid-template-columns: 210px 1fr;
          min-height: calc(100vh - 48px);
          border: 3px solid #17275f;
        }
        .sidebar { border-right: 3px solid #17275f; }
        .logo {
          height: 60px; display: flex; align-items: center ; margin :5px 0px 0px 0px;
          border-bottom: 3px solid #17275f;
          align-items:center;justify-content:center;
        }
        .logo img {
          // margin-left: 75px;
          // margin-top: 4px;
          width: 60px;
        }
        .menu { display: flex; flex-direction: column; gap: 28px; padding: 85px 2px; }
        .menu button {
          padding: 0; border: 0; background: transparent; text-align: left;
          color: #111; font-size: 14px; cursor: pointer;
        }
        .menu button.active, .menu button:hover { color: #008b8b; }
        .content { display: flex; flex-direction: column; min-width: 0; }
        .header {
          height: 65px; display: flex; align-items: center; padding: 0 24px;
          border-bottom: 3px solid #17275f;
        }
        .header h1 { margin: 0; color: #17275f; font-size: 32px; }
        .folders {
          display: flex; flex-wrap: wrap; gap: 65px;
          padding: 55px 40px;
        }
        .folder-link {
          width: 145px; color: #111; text-align: center;
          text-decoration: none; cursor: pointer;
        }
        .folder-icon {
          position: relative; width: 105px; height: 75px; margin: 0 auto 14px;
          border: 6px solid #3c302a; background: #ffb323;
        }
        .folder-icon::before {
          position: absolute; top: -22px; left: -6px; width: 45px; height: 22px;
          border: 6px solid #3c302a; border-bottom: none;
          background: #ffb323; content: "";
        }
        .folder-icon span {
          position: relative; z-index: 1; font-size: 42px; font-weight: bold;
          line-height: 62px;
        }
        .folder-name { display: block; font-size: 15px; font-weight: 600; }
        .folder-status {
          display: block; margin-top: 6px; color: #777; font-size: 10px;
          text-transform: capitalize;
        }
        .folder-link:hover .folder-icon { background: #ffc34d; }
        .empty {
          margin: 55px 40px; padding: 28px; border: 1px solid #8aa4a5;
          color: #555; max-width: 500px;
        }
        .error { margin: 20px 40px; color: #a33; font-size: 13px; }
        @media (max-width: 700px) {
          .page { padding: 12px; }
          .layout { grid-template-columns: 1fr; }
          .sidebar { display: none; }
          .folders { justify-content: center; gap: 40px; }
        }
      `}</style>

      <main className="page">
        <div className="layout">
          <aside className="sidebar">
            <div className="logo"><img src="/logo.png" alt="Tshaai" /></div>
            <nav className="menu">
              {menuItems.map((item) => (
                <button
                  key={item}
                  className={item === "Home" ? "active" : ""}
                  onClick={() =>
                    onNavigate(
                      item === "Home"
                        ? "home"
                        : item === "AOI Analysis"
                        ? "aoi"
                        : item === "Environmental Watch"
                        ? "environmental-watch"
                        : item === "Ecological Stress"
                        ? "ecological-stress"
                        : item === "Settings"
                        ? "settings"
                        : "home"
                    )
                  }
                >
                  {item}
                </button>
              ))}
            </nav>
          </aside>

          <section className="content">
            <header className="header"><h1>Recent Work</h1></header>

            {error && <div className="error">{error}</div>}

            {loading ? (
              <div className="empty">Loading projects...</div>
            ) : (
              <div className="folders">
                <button
                  className="folder-link"
                  onClick={() => onNavigate("create")}
                  style={{ border: 0, background: "transparent" }}
                >
                  <div className="folder-icon"><span>+</span></div>
                  <span className="folder-name">Create New</span>
                </button>

                {projects.map((project) => (
                  <button
                    className="folder-link"
                    key={project.id}
                    onClick={() => onOpenProject(project.id)}
                    style={{ border: 0, background: "transparent" }}
                  >
                    <div className="folder-icon" />
                    <span className="folder-name">{project.project_name}</span>
                    <span className="folder-status">{project.status}</span>
                  </button>
                ))}
              </div>
            )}

            {!loading && projects.length === 0 && !error && (
              <div className="empty">
                No saved projects yet. Select <b>Create New</b> to start a
                sustainable infrastructure analysis.
              </div>
            )}
          </section>
        </div>
      </main>
    </>
  );
}
