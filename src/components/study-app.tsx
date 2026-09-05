"use client";
import { useEffect, useState } from "react";
import Link from "next/link";
import {
  Activity,
  ArrowDownToLine,
  ArrowRight,
  BookOpen,
  ChartNoAxesCombined,
  Check,
  ChevronRight,
  Clock3,
  Home,
  LogOut,
  Menu,
  Play,
  Search,
  ShieldCheck,
  Stethoscope,
  Target,
  X,
} from "lucide-react";
import { api, getEditor } from "@/lib/client/api";
import {
  MODES,
  type Attempt,
  type AttemptView,
  type Mode,
  type SubjectStats,
} from "@/lib/types";
import { Modal } from "./modal";
import { Exam } from "./exam";
import styles from "./study-app.module.scss";

const cx = (...classes: Array<string | false | null | undefined>) =>
  classes.filter(Boolean).join(" ");

type User = { id: string; name: string; demo: boolean };
type Dashboard = {
  subjects: SubjectStats[];
  attempts: Attempt[];
  bankVersion: string;
};
type Session = { user: User | null; configured: boolean; demo: boolean };
type Tab = "overview" | "subjects" | "progress";
const subjectMarks: Record<string, string> = {
  biochemistry: "Bc",
  anatomy: "An",
  microbiology: "Mi",
  physiology: "Ph",
  "legal-medicine": "Lm",
  pathology: "Pa",
  pharmacology: "Rx",
  surgery: "Su",
  "internal-medicine": "Im",
  "obstetrics-gynecology": "Ob",
  pediatrics: "Pe",
  "preventive-medicine": "Pm",
};
const date = (value: string) =>
  new Date(value).toLocaleDateString("en-PH", {
    month: "short",
    day: "numeric",
  });

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
    } catch (e) {
      setError((e as Error).message);
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
  const completed =
    dashboard?.attempts.filter((a) => a.status === "submitted") ?? [];
  const active =
    dashboard?.attempts.filter((a) => a.status !== "submitted") ?? [];
  const total = completed.reduce((n, a) => n + a.questionIds.length, 0);
  const correct = completed.reduce((n, a) => n + (a.score ?? 0), 0);
  const available =
    dashboard?.subjects.reduce((n, s) => n + s.available, 0) ?? 0;
  const subjects =
    dashboard?.subjects.filter((s) =>
      s.name.toLowerCase().includes(query.toLowerCase()),
    ) ?? [];
  const nav = [
    { id: "overview" as const, label: "Overview", icon: Home },
    { id: "subjects" as const, label: "Question bank", icon: BookOpen },
    {
      id: "progress" as const,
      label: "My progress",
      icon: ChartNoAxesCombined,
    },
  ];

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
          {nav.map((item) => (
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
            <span>{nav.find((n) => n.id === tab)?.label}</span>
          </div>
          <span className={styles.topbarNote}>
            <span className={styles.liveDot} />
            Philippine PLE
          </span>
        </header>
        <div className={styles.pageContent}>
          {error && (
            <div className={cx("notice", "error")} role="alert">
              {error}
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
            <>
              {session.user.demo && (
                <div className={styles.previewNotice}>
                  <ShieldCheck size={16} />
                  <span>
                    Local preview{" "}
                    <span className="muted">
                      · Progress stays in this browser’s preview account.
                      Connect Google for access across devices.
                    </span>
                  </span>
                </div>
              )}
              <section className={styles.greeting}>
                <div>
                  <div className="eyebrow">ONE SESSION CLOSER</div>
                  <h1>
                    {tab === "overview"
                      ? "Your next step, doctor."
                      : tab === "subjects"
                        ? "Build your knowledge."
                        : "See how far you’ve come."}
                  </h1>
                  <p>
                    {tab === "overview"
                      ? "A focused space to practice, understand, and keep moving forward."
                      : tab === "subjects"
                        ? "Twelve subjects. Start with the one you want to strengthen."
                        : "Every session is another chance to find what needs your attention."}
                  </p>
                </div>
                <div className={styles.greetingSymbol} aria-hidden="true">
                  <Stethoscope size={46} strokeWidth={1.2} />
                </div>
              </section>

              {tab !== "subjects" && (
                <div className={cx(styles.statsGrid, "grid-flow-dense")}>
                  <Stat
                    icon={<BookOpen size={18} />}
                    label="Questions practiced"
                    value={total.toLocaleString()}
                    detail="Across completed sessions"
                  />
                  <Stat
                    icon={<Target size={18} />}
                    label="Overall accuracy"
                    value={
                      total ? `${Math.round((correct / total) * 100)}%` : "—"
                    }
                    detail={
                      total
                        ? `${correct} correct of ${total} questions`
                        : "Your first session starts the story"
                    }
                  />
                  <Stat
                    icon={<Check size={18} />}
                    label="Sessions completed"
                    value={String(completed.length)}
                    detail={`${active.length} ${active.length === 1 ? "session" : "sessions"} in progress`}
                  />
                </div>
              )}

              {tab === "overview" && (
                <section className={styles.sessionFeature}>
                  <div className={styles.featureCopy}>
                    <span className="eyebrow">
                      {active.length
                        ? "PICK UP WHERE YOU LEFT OFF"
                        : "MAKE TODAY COUNT"}
                    </span>
                    <h2>
                      {active.length
                        ? dashboard.subjects.find(
                            (s) => s.id === active[0].subject,
                          )?.name
                        : "Small sessions. Lasting understanding."}
                    </h2>
                    <p>
                      {active.length
                        ? `${Object.keys(active[0].answers).length} of ${active[0].questionIds.length} answered · ${MODES[active[0].mode].label}`
                        : "Choose a subject, find your pace, and give your next 25 questions your full attention."}
                    </p>
                    <button
                      className="primary"
                      onClick={() =>
                        active.length
                          ? openAttempt(active[0].id)
                          : setSetup(
                              dashboard.subjects.find((s) => s.sizes.length),
                            )
                      }
                    >
                      <Play size={16} fill="currentColor" />
                      {active.length ? "Continue session" : "Start a session"}
                    </button>
                  </div>
                  <div className={styles.featureArt} aria-hidden="true">
                    <div className={styles.orbit} />
                    <div className={cx(styles.orbit, styles.orbitTwo)} />
                    <div className={styles.artCenter}>
                      <BookOpen size={48} strokeWidth={1} />
                    </div>
                    <span className={styles.artCaption}>
                      PRACTICE WITH PURPOSE
                    </span>
                  </div>
                </section>
              )}

              {tab !== "progress" && (
                <section className={styles.subjectsSection}>
                  <div className="section-head">
                    <div>
                      <h2>Explore your subjects</h2>
                      <p>
                        {available.toLocaleString()} available questions · 12
                        PLE subjects
                      </p>
                    </div>
                    <label className={styles.search}>
                      <Search size={17} />
                      <input
                        value={query}
                        onChange={(e) => setQuery(e.target.value)}
                        placeholder="Find a subject"
                        aria-label="Find a subject"
                      />
                    </label>
                  </div>
                  <div className={cx(styles.subjectGrid, "grid-flow-dense")}>
                    {subjects.map((s) => (
                      <button
                        key={s.id}
                        className={cx(styles.subjectCard, "subject-card")}
                        onClick={() => setSetup(s)}
                        disabled={!s.sizes.length}
                      >
                        <div className={styles.subjectTop}>
                          <span className={styles.subjectMark}>
                            {subjectMarks[s.id]}
                          </span>
                          <ArrowRight
                            className={styles.subjectArrow}
                            size={18}
                          />
                        </div>
                        <div>
                          <h3>{s.name}</h3>
                          <p>
                            {s.available.toLocaleString()} questions{" "}
                            <span>· {s.area}</span>
                          </p>
                        </div>
                        <div className={styles.subjectProgress}>
                          <span>
                            {s.answered
                              ? `${Math.round((s.correct / s.answered) * 100)}% accuracy`
                              : s.sizes.length
                                ? "Ready when you are"
                                : "Content under review"}
                          </span>
                          {s.answered > 0 && (
                            <span>{s.answered} practiced</span>
                          )}
                        </div>
                        <div className={styles.miniTrack}>
                          <span
                            style={{
                              width: `${s.answered ? (s.correct / s.answered) * 100 : 0}%`,
                            }}
                          />
                        </div>
                      </button>
                    ))}
                  </div>
                  {!subjects.length && (
                    <p className="empty">
                      No subjects match “{query}”. Try another name.
                    </p>
                  )}
                </section>
              )}

              {tab === "progress" && (
                <section>
                  <div className="section-head">
                    <h2>Accuracy by subject</h2>
                    <span className="muted small">
                      Includes unanswered questions
                    </span>
                  </div>
                  <div className={styles.accuracyList}>
                    {dashboard.subjects.map((s) => (
                      <div key={s.id} className={styles.accuracyRow}>
                        <span
                          className={cx(styles.subjectMark, styles.smallMark)}
                        >
                          {subjectMarks[s.id]}
                        </span>
                        <strong>{s.name}</strong>
                        <div className={styles.miniTrack}>
                          <span
                            style={{
                              width: `${s.answered ? (s.correct / s.answered) * 100 : 0}%`,
                            }}
                          />
                        </div>
                        <span>
                          {s.answered
                            ? `${Math.round((s.correct / s.answered) * 100)}%`
                            : "—"}
                        </span>
                      </div>
                    ))}
                  </div>
                </section>
              )}

              {active.length > (tab === "overview" ? 1 : 0) &&
                tab !== "subjects" && (
                  <section className={styles.historySection}>
                    <div className="section-head">
                      <h2>In progress</h2>
                      <span className="muted small">
                        Resume at your own pace
                      </span>
                    </div>
                    {active.slice(tab === "overview" ? 1 : 0).map((a) => (
                      <HistoryRow
                        key={a.id}
                        attempt={a}
                        subject={
                          dashboard.subjects.find((s) => s.id === a.subject)
                            ?.name ?? ""
                        }
                        open={() => openAttempt(a.id)}
                      />
                    ))}
                  </section>
                )}
              {tab !== "subjects" && (
                <section className={styles.historySection}>
                  <div className="section-head">
                    <h2>Recent sessions</h2>
                    {completed.length > 0 && (
                      <span className="muted small">
                        {completed.length} completed
                      </span>
                    )}
                  </div>
                  {completed.length ? (
                    completed
                      .slice(0, tab === "progress" ? 50 : 5)
                      .map((a) => (
                        <HistoryRow
                          key={a.id}
                          attempt={a}
                          subject={
                            dashboard.subjects.find((s) => s.id === a.subject)
                              ?.name ?? ""
                          }
                          open={() => openAttempt(a.id)}
                        />
                      ))
                  ) : (
                    <div className={styles.emptyHistory}>
                      <ChartNoAxesCombined size={28} strokeWidth={1.4} />
                      <div>
                        <h3>Your progress starts here</h3>
                        <p>
                          Finish a session to see your score and revisit what
                          you learned.
                        </p>
                      </div>
                      <ArrowDownToLine size={19} />
                    </div>
                  )}
                </section>
              )}
              <footer className={styles.pageFooter}>
                <span>Built for the work before the white coat.</span>
                <span>Source-attributed study material · PLE Practice</span>
              </footer>
            </>
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

function Welcome({ configured, demo }: { configured: boolean; demo: boolean }) {
  return (
    <section className={styles.welcome}>
      <div className="eyebrow">YOUR PLE STUDY SPACE</div>
      <h1>Your next step, doctor.</h1>
      <p>
        Practice with purpose. Build confidence across all 12 PLE subjects,
        learn from source explanations, and return to your progress anywhere.
      </p>
      <div className={styles.welcomeFeatures}>
        <span>
          <BookOpen size={19} />
          Subject-based practice
        </span>
        <span>
          <Clock3 size={19} />A pace that works for you
        </span>
        <span>
          <ChartNoAxesCombined size={19} />
          Progress you can see
        </span>
      </div>
      {configured ? (
        <a href="/auth/login" className="primary">
          Continue with Google <ArrowRight size={18} />
        </a>
      ) : demo ? (
        <button className="primary" onClick={() => location.reload()}>
          Open local preview <ArrowRight size={18} />
        </button>
      ) : (
        <div className="notice">
          Google sign-in is not connected yet. Follow the Supabase setup in
          README.md to open your study space.
        </div>
      )}
      <p className="small muted">
        Historical source material for exam study. Explanations retain their
        original references.
      </p>
    </section>
  );
}
function Stat({
  icon,
  label,
  value,
  detail,
}: {
  icon: React.ReactNode;
  label: string;
  value: string;
  detail: string;
}) {
  return (
    <div className={styles.stat}>
      <div className={styles.statLabel}>
        {icon}
        <span>{label}</span>
      </div>
      <strong>{value}</strong>
      <p>{detail}</p>
    </div>
  );
}
function HistoryRow({
  attempt: a,
  subject,
  open,
}: {
  attempt: Attempt;
  subject: string;
  open: () => void;
}) {
  return (
    <button className={styles.historyRow} onClick={open}>
      <span className={styles.historyIcon}>
        {a.status === "submitted" ? <Check size={19} /> : <Play size={18} />}
      </span>
      <span className={styles.historyTitle}>
        <strong>{subject}</strong>
        <small>
          {MODES[a.mode].label} · {a.questionIds.length} questions ·{" "}
          {date(a.updatedAt)}
        </small>
      </span>
      <span className={styles.historyScore}>
        {a.status === "submitted"
          ? `${Math.round(((a.score ?? 0) / a.questionIds.length) * 100)}%`
          : "Resume"}
      </span>
      <ChevronRight size={18} />
    </button>
  );
}
function Setup({
  subject,
  close,
  start,
}: {
  subject: SubjectStats;
  close: () => void;
  start: (id: string) => void;
}) {
  const [mode, setMode] = useState<Mode>("practice");
  const [count, setCount] = useState(subject.sizes[0] ?? 25);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  async function create() {
    setBusy(true);
    setError("");
    try {
      const result = await api<AttemptView>("/api/attempts", {
        subject: subject.id,
        mode,
        count,
        editorId: await getEditor(),
      });
      start(result.attempt.id);
    } catch (e) {
      setError((e as Error).message);
      setBusy(false);
    }
  }
  return (
    <Modal title="Make this session yours" close={close}>
      <p className={styles.setupSubject}>
        {subject.name}{" "}
        <span>{subject.available.toLocaleString()} available questions</span>
      </p>
      <fieldset>
        <legend>Choose your mode</legend>
        <div className={styles.modeOptions}>
          {(Object.keys(MODES) as Mode[]).map((m) => (
            <label
              key={m}
              className={cx(styles.modeOption, mode === m && styles.selected)}
            >
              <input
                type="radio"
                name="mode"
                value={m}
                checked={mode === m}
                onChange={() => setMode(m)}
              />
              <span>
                <strong>{MODES[m].label}</strong>
                <small>{MODES[m].description}</small>
              </span>
            </label>
          ))}
        </div>
      </fieldset>
      <fieldset>
        <legend>Session size</legend>
        <div className={styles.sizeOptions}>
          {[25, 50, 100].map((n) => (
            <label
              key={n}
              className={cx(
                styles.sizeOption,
                count === n && styles.selected,
                !subject.sizes.includes(n) && styles.unavailable,
              )}
            >
              <input
                type="radio"
                name="size"
                value={n}
                checked={count === n}
                disabled={!subject.sizes.includes(n)}
                onChange={() => setCount(n)}
              />
              <strong>{n}</strong>
              <small>questions</small>
            </label>
          ))}
        </div>
      </fieldset>
      <div className={styles.paceNote}>
        <Clock3 size={18} />
        <p>
          {mode === "practice"
            ? "Untimed. Check and lock each answer when you’re ready."
            : `${(MODES[mode].seconds * count) / 60} minutes of active study. Your timer pauses when you leave or hide this screen.`}
        </p>
      </div>
      {error && (
        <p role="alert" className="error-text">
          {error}
        </p>
      )}
      <button
        className="primary full"
        onClick={create}
        disabled={busy || !subject.sizes.length}
      >
        {busy ? "Preparing your session…" : "Let’s begin"}
        <ArrowRight size={18} />
      </button>
    </Modal>
  );
}
