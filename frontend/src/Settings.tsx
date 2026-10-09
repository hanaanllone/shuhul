import { useEffect, useState } from "react";
import { getSession, logout } from "./auth/session";

interface SettingsProps {
  onNavigate: (path: string) => void;
  onLogout: () => void;
}

export default function Settings({ onNavigate, onLogout }: SettingsProps) {
  const [user, setUser] = useState<any>(null);

  useEffect(() => {
    getSession().then(setUser);
  }, []);

  return (
    <>
      <style>{`
        * { box-sizing: border-box; }
        body { margin: 0; font-family: Arial, sans-serif; background: #f7f6f1; }
        .page { min-height: 100vh; padding: 24px 32px; }
        .layout { display:grid; grid-template-columns:210px 1fr; min-height:calc(100vh - 48px); border:3px solid #17275f; }
        .sidebar { border-right:3px solid #17275f; }
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
        .menu { display:flex; flex-direction:column; gap:28px; padding:85px 12px; }
        .menu button { padding:0; border:0; background:transparent; text-align:left; color:#111; font-size:14px; cursor:pointer; }
        .menu button.active,.menu button:hover { color:#008b8b; }
        .content { min-width:0; }
        .header { height:65px; display:flex; align-items:center; padding:0 24px; border-bottom:3px solid #17275f; }
        .header h1 { margin:0; color:#17275f; font-size:32px; }
        .panel { max-width:620px; margin:45px 40px; padding:28px; border:2px solid #17275f; background:#fff; }
        .row { padding:15px 0; border-bottom:1px solid #ddd; }
        .label { color:#777; font-size:11px; text-transform:uppercase; margin-bottom:5px; }
        .value { color:#17275f; font-size:16px; font-weight:600; }
        .logout { margin-top:25px; padding:10px 18px; border:0; background:#17275f; color:white; cursor:pointer; }
      `}</style>
      <main className="page">
        <div className="layout">
          <aside className="sidebar">
            <div className="logo"><img src="/logo.png" alt="Tshaai" /></div>
            <nav className="menu">
              {["Home","AOI Analysis","Environmental Watch","Ecological Stress","Thermal Compensation","Environmental Analysis","Settings"].map(item => (
                <button
                  key={item}
                  className={item === "Settings" ? "active" : ""}
                  onClick={() => onNavigate(
                    item === "Home" ? "home" :
                    item === "AOI Analysis" ? "aoi" :
                    item === "Environmental Watch"  ? "environmental-watch":
                    item === "Settings" ? "settings" : "home"
                  )}
                >{item}</button>
              ))}
            </nav>
          </aside>
          <section className="content">
            <header className="header"><h1>Settings</h1></header>
            <div className="panel">
              <div className="row"><div className="label">Name</div><div className="value">{user?.name || "—"}</div></div>
              <div className="row"><div className="label">Organisation</div><div className="value">{user?.organisation || "—"}</div></div>
              <div className="row"><div className="label">Email</div><div className="value">{user?.email || "—"}</div></div>
              <button className="logout" onClick={async () => { await logout(); onLogout(); }}>Log out</button>
            </div>
          </section>
        </div>
      </main>
    </>
  );
}
