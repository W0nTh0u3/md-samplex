"use client";
import {
  ArrowDownToLine,
  ArrowRight,
  BookOpen,
  ChartNoAxesCombined,
  Check,
  ChevronRight,
  Play,
  Search,
  ShieldCheck,
  Stethoscope,
  Target,
} from "lucide-react";
import { countAnswered } from "@/lib/answers";
import { MODES, type Attempt, type SubjectStats } from "@/lib/types";
import { cx } from "./component-utils";
import type { Dashboard, Tab, User } from "./study-types";
import styles from "./study-dashboard.module.scss";

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

type StudyDashboardProps = {
  user: User;
  dashboard: Dashboard;
  tab: Tab;
  query: string;
  setQuery: (value: string) => void;
  openAttempt: (id: string) => void;
  setSetup: (subject: SubjectStats | undefined) => void;
};

export function StudyDashboard({
  user,
  dashboard,
  tab,
  query,
  setQuery,
  openAttempt,
  setSetup,
}: StudyDashboardProps) {
  const completed = dashboard.attempts.filter(
    (attempt) => attempt.status === "submitted",
  );
  const active = dashboard.attempts.filter(
    (attempt) => attempt.status !== "submitted",
  );
  const total = completed.reduce(
    (count, attempt) => count + attempt.questionIds.length,
    0,
  );
  const correct = completed.reduce(
    (count, attempt) => count + (attempt.score ?? 0),
    0,
  );
  const available = dashboard.subjects.reduce(
    (count, subject) => count + subject.available,
    0,
  );
  const subjects = dashboard.subjects.filter((subject) =>
    subject.name.toLowerCase().includes(query.toLowerCase()),
  );

  return (
    <div className={styles.dashboardContent}>
      {user.demo && (
        <div className={styles.previewNotice}>
          <ShieldCheck size={16} />
          <span>
            Local preview{" "}
            <span className="muted">
              · Progress stays in this browser’s preview account. Connect Google
              for access across devices.
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
            value={total ? `${Math.round((correct / total) * 100)}%` : "—"}
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
                    (subject) => subject.id === active[0].subject,
                  )?.name
                : "Small sessions. Lasting understanding."}
            </h2>
            <p>
              {active.length
                ? `${countAnswered(active[0].answers)} of ${active[0].questionIds.length} answered · ${MODES[active[0].mode].label}`
                : "Choose a subject, find your pace, and give your next 25 questions your full attention."}
            </p>
            <button
              className="primary"
              onClick={() =>
                active.length
                  ? openAttempt(active[0].id)
                  : setSetup(dashboard.subjects.find((s) => s.sizes.length))
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
            <span className={styles.artCaption}>PRACTICE WITH PURPOSE</span>
          </div>
        </section>
      )}

      {tab !== "progress" && (
        <section className={styles.subjectsSection}>
          <div className="section-head">
            <div>
              <h2>Explore your subjects</h2>
              <p>
                {available.toLocaleString()} available questions · 12 PLE
                subjects
              </p>
            </div>
            <label className={styles.search}>
              <Search size={17} />
              <input
                value={query}
                onChange={(event) => setQuery(event.target.value)}
                placeholder="Find a subject"
                aria-label="Find a subject"
              />
            </label>
          </div>
          <div className={cx(styles.subjectGrid, "grid-flow-dense")}>
            {subjects.map((subject) => (
              <button
                key={subject.id}
                className={cx(styles.subjectCard, "subject-card")}
                onClick={() => setSetup(subject)}
                disabled={!subject.sizes.length}
              >
                <div className={styles.subjectTop}>
                  <span className={styles.subjectMark}>
                    {subjectMarks[subject.id]}
                  </span>
                  <ArrowRight className={styles.subjectArrow} size={18} />
                </div>
                <div>
                  <h3>{subject.name}</h3>
                  <p>
                    {subject.available.toLocaleString()} questions{" "}
                    <span>· {subject.area}</span>
                  </p>
                </div>
                <div className={styles.subjectProgress}>
                  <span>
                    {subject.answered
                      ? `${Math.round((subject.correct / subject.answered) * 100)}% accuracy`
                      : subject.sizes.length
                        ? "Ready when you are"
                        : "Content under review"}
                  </span>
                  {subject.answered > 0 && (
                    <span>{subject.answered} practiced</span>
                  )}
                </div>
                <div className={styles.miniTrack}>
                  <span
                    style={{
                      width: `${subject.answered ? (subject.correct / subject.answered) * 100 : 0}%`,
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
            <span className="muted small">Includes unanswered questions</span>
          </div>
          <div className={styles.accuracyList}>
            {dashboard.subjects.map((subject) => (
              <div key={subject.id} className={styles.accuracyRow}>
                <span className={cx(styles.subjectMark, styles.smallMark)}>
                  {subjectMarks[subject.id]}
                </span>
                <strong>{subject.name}</strong>
                <div className={styles.miniTrack}>
                  <span
                    style={{
                      width: `${subject.answered ? (subject.correct / subject.answered) * 100 : 0}%`,
                    }}
                  />
                </div>
                <span>
                  {subject.answered
                    ? `${Math.round((subject.correct / subject.answered) * 100)}%`
                    : "—"}
                </span>
              </div>
            ))}
          </div>
        </section>
      )}

      {active.length > (tab === "overview" ? 1 : 0) && tab !== "subjects" && (
        <section className={styles.historySection}>
          <div className="section-head">
            <h2>In progress</h2>
            <span className="muted small">Resume at your own pace</span>
          </div>
          {active.slice(tab === "overview" ? 1 : 0).map((attempt) => (
            <HistoryRow
              key={attempt.id}
              attempt={attempt}
              subject={
                dashboard.subjects.find((s) => s.id === attempt.subject)
                  ?.name ?? ""
              }
              open={() => openAttempt(attempt.id)}
            />
          ))}
        </section>
      )}

      {tab !== "subjects" && (
        <section className={styles.historySection}>
          <div className="section-head">
            <h2>Recent sessions</h2>
            {completed.length > 0 && (
              <span className="muted small">{completed.length} completed</span>
            )}
          </div>
          {completed.length ? (
            completed
              .slice(0, tab === "progress" ? 50 : 5)
              .map((attempt) => (
                <HistoryRow
                  key={attempt.id}
                  attempt={attempt}
                  subject={
                    dashboard.subjects.find((s) => s.id === attempt.subject)
                      ?.name ?? ""
                  }
                  open={() => openAttempt(attempt.id)}
                />
              ))
          ) : (
            <div className={styles.emptyHistory}>
              <ChartNoAxesCombined size={28} strokeWidth={1.4} />
              <div>
                <h3>Your progress starts here</h3>
                <p>
                  Finish a session to see your score and revisit what you
                  learned.
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
    </div>
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
  attempt,
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
        {attempt.status === "submitted" ? (
          <Check size={19} />
        ) : (
          <Play size={18} />
        )}
      </span>
      <span className={styles.historyTitle}>
        <strong>{subject}</strong>
        <small>
          {MODES[attempt.mode].label} · {attempt.questionIds.length} questions ·{" "}
          {date(attempt.updatedAt)}
        </small>
      </span>
      <span className={styles.historyScore}>
        {attempt.status === "submitted"
          ? `${Math.round(((attempt.score ?? 0) / attempt.questionIds.length) * 100)}%`
          : "Resume"}
      </span>
      <ChevronRight size={18} />
    </button>
  );
}
