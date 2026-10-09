import { useState } from "react";
import type { FormEvent } from "react";
import "./LoginSignup.css";
import { login, signup } from "./auth/session";

interface LoginSignupProps {
  onLogin: () => void;
}

export default function LoginSignup({
  onLogin,
}: LoginSignupProps) {
  const [isSignup, setIsSignup] = useState(false);

  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [organisation, setOrganisation] = useState("");

  const [loading, setLoading] = useState(false);
  const [errorMessage, setErrorMessage] = useState("");

  async function handleSubmit(
    event: FormEvent<HTMLFormElement>
  ) {
    event.preventDefault();

    setErrorMessage("");

    if (!email || !password || !organisation) {
      setErrorMessage("Please fill in all fields.");
      return;
    }

    setLoading(true);

    try {
      if (isSignup) {
        await signup(
          email,
          password,
          organisation
        );
      } else {
        await login(
          email,
          password,
          organisation
        );
      }

      onLogin();
    } catch (error) {
      if (error instanceof Error) {
        setErrorMessage(error.message);
      } else {
        setErrorMessage(
          "Something went wrong. Please try again."
        );
      }
    } finally {
      setLoading(false);
    }
  }

  function switchMode() {
    setIsSignup((current) => !current);
    setErrorMessage("");
  }

  return (
    <main className="login-page">
      <div className="planning-tag">
        Planning
      </div>

      <section className="brand-panel">
        <div className="brand-block">
          <span>Shuhul</span>
        </div>

        <img
          className="logo"
          src="/logo.png"
          width="125"
          alt="Shuhul"
        />

        <div className="development-tag">
          Development
        </div>
      </section>

      <section className="form-panel">
        <div className="form-heading">
          <h1>
            {isSignup ? "CREATE ACCOUNT" : "LOGIN"}
          </h1>
        </div>

        <form onSubmit={handleSubmit}>
          <input
            type="email"
            placeholder="Email"
            value={email}
            onChange={(event) =>
              setEmail(event.target.value)
            }
            disabled={loading}
            required
          />

          <input
            type="password"
            placeholder="Password"
            value={password}
            onChange={(event) =>
              setPassword(event.target.value)
            }
            disabled={loading}
            required
          />

          <input
            type="text"
            placeholder="Organisation"
            value={organisation}
            onChange={(event) =>
              setOrganisation(event.target.value)
            }
            disabled={loading}
            required
          />

          {errorMessage && (
            <div className="auth-error">
              {errorMessage}
            </div>
          )}

          <div className="form-actions">
            <button
              type="submit"
              disabled={loading}
            >
              {loading
                ? "Please wait..."
                : isSignup
                ? "Create Account"
                : "Login"}
            </button>

            <div className="form-links">
              {!isSignup && (
                <a
                  href="#forgot-password"
                  onClick={(event) => {
                    event.preventDefault();
                    setErrorMessage(
                      "Password recovery will be added next."
                    );
                  }}
                >
                  Forgot Password
                </a>
              )}

              <a
                href="#create-account"
                onClick={(event) => {
                  event.preventDefault();
                  switchMode();
                }}
              >
                {isSignup
                  ? "Already have an account?"
                  : "Create an Account"}
              </a>
            </div>
          </div>
        </form>
      </section>
    </main>
  );
}