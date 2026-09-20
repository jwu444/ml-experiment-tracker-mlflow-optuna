import { useState, type ReactNode } from "react";
import { Link } from "react-router-dom";
import { IconButton, ThemeToggle } from "../ui";
import NavRail from "./NavRail";
import styles from "./AppShell.module.css";

const SIDEBAR_KEY = "wp-sidebar";

interface AppShellProps {
  children: ReactNode;
  topbarRight?: ReactNode;
  /** `chat` reads prose in a single column, `upload` frames one short form, and
   *  `wide` is for tables — the leaderboard carries eight columns, and at chat
   *  width its notes and timestamps are clipped rather than merely tight. */
  width?: "chat" | "upload" | "wide";
}

function initialCollapsed(): boolean {
  try {
    return localStorage.getItem(SIDEBAR_KEY) === "collapsed";
  } catch {
    return false;
  }
}

export default function AppShell({ children, topbarRight, width = "chat" }: AppShellProps) {
  const [collapsed, setCollapsed] = useState(initialCollapsed);

  function toggle() {
    setCollapsed((prev) => {
      const next = !prev;
      try {
        localStorage.setItem(SIDEBAR_KEY, next ? "collapsed" : "expanded");
      } catch {
        // ignore persistence failures (private mode, etc.)
      }
      return next;
    });
  }

  return (
    <div className={styles.shell} data-collapsed={collapsed}>
      <header className={styles.topbar}>
        <div className={styles.left}>
          <IconButton
            label={collapsed ? "Show navigation" : "Hide navigation"}
            aria-expanded={!collapsed}
            onClick={toggle}
          >
            ☰
          </IconButton>
          {/* The only link left in the topbar: sections and the entities under
              them all live in the rail below, so there is one place to look. */}
          <Link to="/" className={styles.brand}>
            CSV Analysis
          </Link>
        </div>
        <div className={styles.right}>
          {topbarRight}
          <ThemeToggle />
        </div>
      </header>
      <div className={styles.body}>
        {!collapsed && (
          <aside className={styles.sidebar}>
            <NavRail />
          </aside>
        )}
        <main data-width={width} className={styles.main}>
          {children}
        </main>
      </div>
    </div>
  );
}
