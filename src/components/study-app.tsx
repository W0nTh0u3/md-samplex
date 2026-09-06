"use client";
import { useEffect, useState } from "react";
import Link from "next/link";
import {
  Activity,
  BookOpen,
  ChartNoAxesCombined,
  ChevronRight,
  CircleAlert,
  Home,
  LogOut,
  Menu,
  X,
} from "lucide-react";
import { api } from "@/lib/client/api";
import type { SubjectStats } from "@/lib/types";
import { Exam } from "./exam";
import { cx } from "./component-utils";
import { StudyDashboard } from "./study-dashboard";
import { Setup, Welcome } from "./study-entry";
import type { Dashboard, Session, Tab } from "./study-types";
import styles from "./study-app.module.scss";

const navigation = [
  { id: "overview" as const, label: "Overview", icon: Home },
  { id: "subjects" as const, label: "Question bank", icon: BookOpen },
  {
    id: "progress" as const,
    label: "My progress",
    icon: ChartNoAxesCombined,
  },
];

export function StudyApp() {
  const [session, setSession] = useState<Session>();
  const [dashboard, setDashboard] = useState<Dashboard>();
  const [tab, setTab] = useState<Tab>("overview");
  const [attemptId, setAttemptId] = useState<string>();
  const [setup, setSetup] = useState<SubjectStats>();
  const [query, setQuery] = useState("");
  const [error, setError] = useState("");
  const [refresh, setRefresh] = useState(0);
  const [mobileMenuOpen, setMobileMenuOpen] = useState(false);

  useEffect(() => {
    let cancelled = false;
    const start = setTimeout(() => {
      void api<Session>("/api/session")
        .then((value) => {
          if (cancelled) return;
          setSession(value);
          const requested = new URLSearchParams(location.search).get("attempt");
          if (value.user && requested) setAttemptId(requested);
          if (new URLSearchParams(location.search).has("auth"))
            setError(
              "Google sign-in did not complete. Please try again or check the project configuration.",
            );
        })
        .catch((e) => setError(e.message));
    }, 0);
    return () => {
      cancelled = true;
      clearTimeout(start);
    };
  }, []);

  useEffect(() => {
    if (!session?.user || attemptId) return;
    let cancelled = false;
    void api<Dashboard>("/api/dashboard")
      .then((value) => {
        if (!cancelled) setDashboard(value);
      })
      .catch((e) => setError(e.message));
    return () => {
      cancelled = true;
    };
  }, [session, attemptId, refresh]);

  useEffect(() => {
    const channel = new BroadcastChannel("ple-account");
    channel.onmessage = () => {
      setAttemptId(undefined);
      setDashboard(undefined);
      setSession((value) => (value ? { ...value, user: null } : value));
    };
    const pop = () => {
      setAttemptId(
        new URLSearchParams(location.search).get("attempt") ?? undefined,
      );
    };
    window.addEventListener("popstate", pop);
    return () => {
      channel.close();
      window.removeEventListener("popstate", pop);
    };
  }, []);

  function openAttempt(id: string) {
    history.pushState({}, "", `/?attempt=${id}`);
    setAttemptId(id);
  }

  function leaveAttempt() {
    history.pushState({}, "", "/");
    setAttemptId(undefined);
    setRefresh((n) => n + 1);
  }

  async function logout() {
    try {
      await api("/api/logout", {});
      const channel = new BroadcastChannel("ple-account");
      channel.postMessage("signed-out");
      channel.close();
      setDashboard(undefined);
      setSession((s) => (s ? { ...s, user: null } : s));
    } catch {
      setError("We couldn't sign you out. Please refresh and try again.");
    }
  }

  if (attemptId && session?.user)
    return (
      <Exam
        key={attemptId}
        id={attemptId}
        user={session.user}
        leave={leaveAttempt}
      />
    );

  return (
    <div className={styles.appShell}>
      <a className="skip-link" href="#content">
        Skip to content
      </a>
      <aside
        className={cx(styles.sidebar, mobileMenuOpen && styles.mobileOpen)}
      >
        <Link className={styles.brand} href="/" aria-label="PLE Practice home">
          <span className={styles.brandIcon}>
            <Activity size={23} />
          </span>
          <span>
            PLE<span className={styles.brandLight}>Practice</span>
          </span>
        </Link>
        <button
          className={cx(styles.mobileMenuTrigger, "icon-button")}
          aria-label={
            mobileMenuOpen ? "Close navigation menu" : "Open navigation menu"
          }
          aria-expanded={mobileMenuOpen}
          onClick={() => setMobileMenuOpen((value) => !value)}
        >
          {mobileMenuOpen ? <X size={20} /> : <Menu size={20} />}
        </button>
        <nav aria-label="Main navigation">
          {navigation.map((item) => (
            <button
              key={item.id}
              className={cx(styles.navLink, tab === item.id && styles.active)}
              aria-current={tab === item.id ? "page" : undefined}
              onClick={() => {
                setTab(item.id);
                setMobileMenuOpen(false);
              }}
            >
              <item.icon size={19} />
              {item.label}
              {tab === item.id && <span className={styles.navDot} />}
            </button>
          ))}
        </nav>
        <div className={styles.sidebarBottom}>
          <span className={styles.avatar}>
            {session?.user?.name.slice(0, 1) || "P"}
          </span>
          <div>
            <strong>
              {session?.user
                ? session.user.name.split(" ")[0]
                : "Your study space"}
            </strong>
            <small>
              {session?.user?.demo
                ? "Local preview"
                : session?.user
                  ? "Personal account"
                  : "PLE preparation"}
            </small>
          </div>
          {session?.user && (
            <button
              className="icon-button"
              onClick={logout}
              aria-label="Sign out"
            >
              <LogOut size={17} />
            </button>
          )}
        </div>
      </aside>

      <main
        id="content"
        className={cx(
          styles.mainContent,
          "overflow-x-hidden w-full max-w-full",
        )}
      >
        <header className={styles.topbar}>
          <div className={styles.breadcrumb}>
            Your workspace <ChevronRight size={14} />{" "}
            <span>{navigation.find((n) => n.id === tab)?.label}</span>
          </div>
          <span className={styles.topbarNote}>
            <span className={styles.liveDot} />
            Philippine PLE
          </span>
        </header>
        <div className={styles.pageContent}>
          {error && (
            <div className={cx("notice", "error")} role="alert">
              <CircleAlert size={17} aria-hidden="true" />
              <span>{error}</span>
              <button
                onClick={() => {
                  setError("");
                  setRefresh((n) => n + 1);
                }}
              >
                Retry
              </button>
            </div>
          )}
          {!session ? (
            <div className="loading-state" role="status">
              Opening your study space…
            </div>
          ) : !session.user ? (
            <Welcome configured={session.configured} demo={session.demo} />
          ) : !dashboard ? (
            <div className="loading-state" role="status">
              Loading your question bank…
            </div>
          ) : (
            <StudyDashboard
              user={session.user}
              dashboard={dashboard}
              tab={tab}
              query={query}
              setQuery={setQuery}
              openAttempt={openAttempt}
              setSetup={setSetup}
            />
          )}
        </div>
      </main>
      {setup && (
        <Setup
          subject={setup}
          close={() => setSetup(undefined)}
          start={(id) => {
            setSetup(undefined);
            openAttempt(id);
          }}
        />
      )}
    </div>
  );
}
