import { Link } from "react-router-dom";

export function Loading() {
  return (
    <div className="loading" role="status" aria-live="polite">
      <span className="pulse" aria-hidden="true" /> Loading…
    </div>
  );
}

export function ErrorBox({ error }: { error?: Error }) {
  return (
    <section className="card error" role="alert">
      <h2>Something went wrong</h2>
      <p className="muted">{error?.message ?? "Unknown error"}</p>
      <p>
        <Link to="/">Back to the arena</Link>
      </p>
    </section>
  );
}

export function NotFound() {
  return (
    <section className="card error">
      <h2>Page not found</h2>
      <p>
        <Link to="/">Back to the arena</Link>
      </p>
    </section>
  );
}
