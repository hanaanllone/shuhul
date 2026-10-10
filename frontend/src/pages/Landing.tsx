import { useEffect, useRef, useState } from "react";

interface Props {
  onNavigate: (path: string) => void;
}

// The third section answers these one at a time as the page is scrolled.
const STEPS = [
  {
    word: "Why",
    text:
      "Our cities are growing faster than anyone is counting the cost. Trees, wetlands and open " +
      "ground are lost to projects that were never weighed against them.",
  },
  {
    word: "What",
    text:
      "Shuhul is a planning map. It shows the heat, trees, water and flood risk of a place, and " +
      "what a new road or building would take from it.",
  },
  {
    word: "How",
    text:
      "Satellite images and open maps measure the land. Shuhul compares routes and sites on that " +
      "evidence, and sizes the planting needed to repay the damage.",
  },
];

const TEAM_NAME = "Henz te Gruse";

const TEAM = [
  {
    name: "Hanaan Lone",
    role: "Team leader",
    image: "/brand/team/hanaan.jpg",
    email: "hanaanllone@gmail.com",
    website: "hanaanlone.com",
    github: "https://github.com/hanaanllone",
    linkedin: "https://www.linkedin.com/in/hanaanlone/",
  },
  {
    name: "Sayan Qadri",
    role: "",
    image: "/brand/team/sayan.jpg",
    email: "sayanqadri27@gmail.com",
    website: "",
    github: "https://github.com/maraazSb",
    linkedin: "https://www.linkedin.com/in/sayanqadri/",
  },
];

const ICON_PATHS = {
  github:
    "M12 .297c-6.63 0-12 5.373-12 12 0 5.303 3.438 9.8 8.205 11.385.6.113.82-.258.82-.577 0-.285-.01-1.04-.015-2.04-3.338.724-4.042-1.61-4.042-1.61C4.422 18.07 3.633 17.7 3.633 17.7c-1.087-.744.084-.729.084-.729 1.205.084 1.838 1.236 1.838 1.236 1.07 1.835 2.809 1.305 3.495.998.108-.776.417-1.305.76-1.605-2.665-.3-5.466-1.332-5.466-5.93 0-1.31.465-2.38 1.235-3.22-.135-.303-.54-1.523.105-3.176 0 0 1.005-.322 3.3 1.23.96-.267 1.98-.399 3-.405 1.02.006 2.04.138 3 .405 2.28-1.552 3.285-1.23 3.285-1.23.645 1.653.24 2.873.12 3.176.765.84 1.23 1.91 1.23 3.22 0 4.61-2.805 5.625-5.475 5.92.42.36.81 1.096.81 2.22 0 1.606-.015 2.896-.015 3.286 0 .315.21.69.825.57C20.565 22.092 24 17.592 24 12.297c0-6.627-5.373-12-12-12",
  linkedin:
    "M20.447 20.452h-3.554v-5.569c0-1.328-.027-3.037-1.852-3.037-1.853 0-2.136 1.445-2.136 2.939v5.667H9.351V9h3.414v1.561h.046c.477-.9 1.637-1.85 3.37-1.85 3.601 0 4.267 2.37 4.267 5.455v6.286zM5.337 7.433c-1.144 0-2.063-.926-2.063-2.065 0-1.138.92-2.063 2.063-2.063 1.14 0 2.064.925 2.064 2.063 0 1.139-.925 2.065-2.064 2.065zm1.782 13.019H3.555V9h3.564v11.452zM22.225 0H1.771C.792 0 0 .774 0 1.729v20.542C0 23.227.792 24 1.771 24h20.451C23.2 24 24 23.227 24 22.271V1.729C24 .774 23.2 0 22.222 0h.003z",
};

function ProfileLink({ kind, url, name }: { kind: keyof typeof ICON_PATHS; url: string; name: string }) {
  const label = `${name} on ${kind === "github" ? "GitHub" : "LinkedIn"}`;

  return (
    <a className="person-icon" href={url} target="_blank" rel="noreferrer" aria-label={label} title={label}>
      <svg width="20" height="20" viewBox="0 0 24 24" fill="currentColor" aria-hidden="true">
        <path d={ICON_PATHS[kind]} />
      </svg>
    </a>
  );
}

export default function Landing({ onNavigate }: Props) {
  const page = useRef<HTMLElement>(null);
  const steps = useRef<HTMLElement>(null);
  const [step, setStep] = useState(0);

  function scrollTo(id: string) {
    document.getElementById(id)?.scrollIntoView({ behavior: "smooth" });
  }

  // Each section fades in as it comes into view, and out as it leaves.
  useEffect(() => {
    const root = page.current;
    if (!root) return;

    const sections = Array.from(root.querySelectorAll(".landing-section"));

    // Content only starts hidden once this is running, and what is already
    // on screen shows at once, so nothing stays invisible if the browser
    // is slow to report.
    function mark() {
      sections.forEach((section) => {
        const box = section.getBoundingClientRect();
        section.classList.toggle(
          "is-in-view",
          box.top < window.innerHeight * 0.7 && box.bottom > window.innerHeight * 0.3
        );
      });

      // The why, what, how section is three screens tall: how far it has
      // been scrolled through decides which of the three is showing.
      if (steps.current) {
        const box = steps.current.getBoundingClientRect();
        const travel = box.height - window.innerHeight;
        const done = travel > 0 ? Math.min(Math.max(-box.top / travel, 0), 1) : 0;
        setStep(Math.min(STEPS.length - 1, Math.floor(done * STEPS.length)));
      }
    }

    root.classList.add("is-animated");
    mark();
    root.addEventListener("scroll", mark, { passive: true });

    return () => {
      root.removeEventListener("scroll", mark);
      root.classList.remove("is-animated");
    };
  }, []);

  return (
    <main className="landing" ref={page}>
      {/* ---------- 1: what Shuhul is about ---------- */}
      <section className="landing-section landing-hero" id="top">
        <header className="landing-nav">
          <span className="wordmark">SHUHUL</span>
          <nav>
            <button className="nav-link thin" onClick={() => scrollTo("about")}>About us</button>
            <button className="nav-link thin" onClick={() => onNavigate("login")}>Login</button>
            <button className="btn" onClick={() => onNavigate("signup")}>Signup</button>
          </nav>
        </header>

        <div className="hero-words reveal">
          <h1 className="hero-lead">Shuhul is all about</h1>
          <span className="hero-word thin" style={{ gridArea: "planning" }}>Planning</span>
          <span className="hero-word thin" style={{ gridArea: "environment" }}>Environment</span>
          <span className="hero-word thin" style={{ gridArea: "development" }}>Development</span>
        </div>

        <button className="hero-more thin" onClick={() => scrollTo("problem")}>Learn more</button>
      </section>

      {/* ---------- 2: the problem ---------- */}
      <section className="landing-section landing-split" id="problem">
        <div className="split-light on-light">
          <span className="wordmark">SHUHUL</span>
          <h2 className="split-headline reveal">See the land first</h2>

          <p className="split-copy reveal">
            Urban development across South Asia is often driven by infrastructure needs without giving
            environmental impact the same weight during planning. We are seeing urban green spaces
            become smaller, trees being removed, water bodies and natural areas being affected, and
            development happening without enough accountability for the environmental cost.
          </p>
          <p className="split-copy is-offset reveal">
            Shuhul puts the environment on the same map as the project. Before a route is chosen, a
            planner can see how hot the ground already is, where the trees and wetlands are, what a
            road would remove, and where the loss can be made good nearby.
          </p>
        </div>

        <div className="split-dark" aria-hidden="true">
          <img className="strip is-first" src="/brand/strip-green.jpg" alt="" />
          <img className="strip is-second" src="/brand/strip-heat.jpg" alt="" />
        </div>
      </section>

      {/* ---------- 3: why, what, how ---------- */}
      <section className="landing-section landing-sage on-light" id="how" ref={steps}>
        <div className="sage-stage">
          <span className="wordmark">SHUHUL</span>

          <div className="sage-grid reveal">
            <div className="sage-words">
              {STEPS.map((item, index) => (
                <span key={item.word} className={index === step ? "is-active" : ""}>{item.word}</span>
              ))}
            </div>

            <h2 className="sage-display">It<br />does?</h2>

            <div className="sage-copy" aria-live="polite">
              <p key={step} className="sage-step">{STEPS[step].text}</p>
              <div>
                <button className="btn is-dark" onClick={() => onNavigate("signup")}>Start planning</button>
              </div>
            </div>
          </div>
        </div>
      </section>

      {/* ---------- 4: who we are ---------- */}
      <section className="landing-section landing-about" id="about">
        <span className="wordmark">SHUHUL</span>

        <div className="about-grid reveal">
          <div>
            <h2 className="about-title">About us</h2>
            <p className="team-name">Team {TEAM_NAME}</p>

            <div className="team">
              {TEAM.map((person) => (
                <article className="person" key={person.name}>
                  <img src={person.image} alt={`Portrait of ${person.name}`} width={480} height={480} />
                  <h3>{person.name}</h3>
                  {person.role && <p className="person-role">{person.role}</p>}
                  {person.website && (
                    <a href={`https://${person.website}`} target="_blank" rel="noreferrer">{person.website}</a>
                  )}
                  <a href={`mailto:${person.email}`}>{person.email}</a>
                  <div className="person-icons">
                    <ProfileLink kind="github" url={person.github} name={person.name} />
                    <ProfileLink kind="linkedin" url={person.linkedin} name={person.name} />
                  </div>
                </article>
              ))}
            </div>
          </div>

          <div className="about-copy">
            <p>
              We are Hanaan Lone and Sayan Qadri, two final-year students from Kashmir, brought together
              by a shared concern for the environment and the future of our cities.
            </p>
            <p>
              Growing up in Kashmir, we witnessed how once-green urban spaces gradually gave way to
              concrete, accompanied by rising temperatures and increasing environmental stress. This
              experience inspired us to build Shuhul, driven by a larger concern shared by communities
              across South Asia, where rapid and often poorly planned urbanisation threatens the balance
              between development and nature.
            </p>
            <p>
              Shuhul, meaning shade in Kashmiri, is a GIS-powered platform designed to make
              environmentally conscious urban planning more accessible, across Kashmir, South Asia and
              beyond. By mapping heat hotspots, analysing air quality and ecological stress, comparing
              infrastructure routes, and identifying opportunities for green restoration, we aim to help
              planners make informed decisions that put the environment at the heart of development.
            </p>
            <p>
              Our vision is a future where cities can grow without losing the natural spaces that make
              them liveable.
            </p>
            <div>
              <button className="btn" onClick={() => onNavigate("signup")}>Start planning</button>
            </div>
          </div>
        </div>
      </section>
    </main>
  );
}
