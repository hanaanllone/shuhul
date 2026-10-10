import { useEffect, useRef } from "react";

interface Props {
  onNavigate: (path: string) => void;
}

const STEPS = [
  {
    word: "Why",
    text:
      "Urban development across South Asia is often driven by infrastructure needs without giving " +
      "environmental impact the same weight during planning. Green spaces shrink, trees are removed " +
      "and water bodies are built over, with little accountability for the environmental cost.",
  },
  {
    word: "What",
    text:
      "Shuhul is a planning tool for governments and urban planners. It maps heat, tree canopy, water " +
      "and flood risk, compares alternative routes for a new road, and shows what each one would cost " +
      "the land around it.",
  },
  {
    word: "How",
    text:
      "Satellite imagery and open maps measure the land. Routing weighs distance against environmental " +
      "cost. A thermal model estimates the heat a project adds and how much of it nearby planting can " +
      "repay, so mitigation stays close to the damage.",
  },
];

const TEAM = [
  {
    name: "Hanaan Lone",
    role: "Team leader",
    image: "/brand/team/hanaan.jpg",
    email: "hanaanllone@gmail.com",
    website: "hanaanlone.in",
  },
  {
    name: "Sayan Qadri",
    role: "",
    image: "/brand/team/sayan.jpg",
    email: "sayanqadri27@gmail.com",
    website: "",
  },
];

export default function Landing({ onNavigate }: Props) {
  const page = useRef<HTMLElement>(null);

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
      <section className="landing-section landing-sage on-light" id="how">
        <span className="wordmark">SHUHUL</span>

        <div className="sage-grid reveal">
          <div className="sage-words">
            {STEPS.map((step) => (
              <span key={step.word}>{step.word}</span>
            ))}
          </div>

          <h2 className="sage-display">It<br />does?</h2>

          <div className="sage-copy">
            {STEPS.map((step) => (
              <p key={step.word}>{step.text}</p>
            ))}
            <div>
              <button className="btn is-dark" onClick={() => onNavigate("signup")}>Start planning</button>
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
