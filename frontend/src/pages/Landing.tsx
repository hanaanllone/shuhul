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

export default function Landing({ onNavigate }: Props) {
  function scrollTo(id: string) {
    document.getElementById(id)?.scrollIntoView({ behavior: "smooth" });
  }

  return (
    <main className="landing">
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

        <div className="hero-words">
          <h1 className="hero-lead">Shuhul is all about</h1>
          <span className="hero-word thin" style={{ gridArea: "planning" }}>Planning</span>
          <span className="hero-word thin" style={{ gridArea: "environment" }}>Environment</span>
          <span className="hero-word thin" style={{ gridArea: "development" }}>Development</span>
        </div>

        <button className="hero-more thin" onClick={() => scrollTo("about")}>Learn more</button>
      </section>

      {/* ---------- 2: the problem ---------- */}
      <section className="landing-section landing-split" id="about">
        <div className="split-light on-light">
          <span className="wordmark">SHUHUL</span>
          <h2 className="split-headline">See the land first</h2>

          <p className="split-copy">
            Urban development across South Asia is often driven by infrastructure needs without giving
            environmental impact the same weight during planning. We are seeing urban green spaces
            become smaller, trees being removed, water bodies and natural areas being affected, and
            development happening without enough accountability for the environmental cost.
          </p>
          <p className="split-copy is-offset">
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

        <div className="sage-grid">
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
    </main>
  );
}
