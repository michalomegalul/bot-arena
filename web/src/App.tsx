import { NavLink, Route, Routes } from "react-router-dom";
import { Arena } from "./pages/Arena";
import { BotPage } from "./pages/BotPage";
import { NotFound } from "./pages/common";

export function App() {
  return (
    <>
      <a className="skip" href="#main">
        Skip to content
      </a>
      <header className="topbar">
        <nav className="nav" aria-label="Main">
          <NavLink to="/" className="brand" end>
            <span aria-hidden="true">🏁</span> Bot Arena
          </NavLink>
          <NavLink to="/" end>
            Arena
          </NavLink>
          <span className="nav-disabled" aria-disabled="true" title="Coming in Phase 6">
            Claude's Journal <span className="soon">soon</span>
          </span>
          <a className="nav-right" href="https://github.com/michalomegalul/bot-arena" target="_blank" rel="noreferrer">
            GitHub ↗
          </a>
        </nav>
      </header>
      <main id="main" className="page">
        <Routes>
          <Route path="/" element={<Arena />} />
          <Route path="/bots/:runId/:botId" element={<BotPage />} />
          <Route path="*" element={<NotFound />} />
        </Routes>
      </main>
      <footer className="footer muted small">
        Paper money only, not investment advice. Prices from Alpaca; decisions after each close, fills at the next open.
      </footer>
    </>
  );
}
