import { Component } from "react";
import type { ReactNode } from "react";

interface Props {
  // Changing this clears the error, so moving to another page recovers.
  resetKey: string;
  children: ReactNode;
}

interface State {
  failed: boolean;
}

// Keeps one broken page from blanking the whole app.
export default class ErrorBoundary extends Component<Props, State> {
  state: State = { failed: false };

  static getDerivedStateFromError(): State {
    return { failed: true };
  }

  componentDidUpdate(previous: Props) {
    if (previous.resetKey !== this.props.resetKey && this.state.failed) {
      this.setState({ failed: false });
    }
  }

  render() {
    if (!this.state.failed) return this.props.children;

    return (
      <main className="page">
        <div className="page-head">
          <h1 className="page-title">Something went wrong</h1>
        </div>
        <p className="muted" style={{ maxWidth: 560 }}>
          This page could not be shown. Nothing has been lost. Try again, or go to another page from
          the bar above.
        </p>
        <button className="btn" style={{ marginTop: 18 }} onClick={() => this.setState({ failed: false })}>
          Try again
        </button>
      </main>
    );
  }
}
