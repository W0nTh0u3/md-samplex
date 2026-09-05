"use client";
import { useEffect, useRef, useState } from "react";
import {
  ArrowLeft,
  ArrowRight,
  BookOpen,
  Check,
  CheckCircle2,
  ChevronLeft,
  ChevronRight,
  Clock3,
  Cloud,
  Download,
  Flag,
  List,
  Pause,
  Play,
  RotateCcw,
  XCircle,
} from "lucide-react";
import { useAttempt } from "@/lib/client/use-attempt";
import {
  MODES,
  SUBJECTS,
  type AttemptView,
  type Draft,
  type PublicQuestion,
} from "@/lib/types";
import { Modal } from "./modal";
import styles from "./exam.module.scss";

const cx = (...classes: Array<string | false | null | undefined>) =>
  classes.filter(Boolean).join(" ");

function time(ms: number) {
  const seconds = Math.ceil(ms / 1000);
  return `${Math.floor(seconds / 60)
    .toString()
    .padStart(2, "0")}:${(seconds % 60).toString().padStart(2, "0")}`;
}

export function Exam({
  id,
  user,
  leave,
}: {
  id: string;
  user: { id: string; demo: boolean };
  leave: () => void;
}) {
  const state = useAttempt(id, user.id);
  const { view, edit, busy, conflict, authLost } = state;
  const [confirm, setConfirm] = useState(false);
  const [showNavigator, setShowNavigator] = useState(false);
  const [showRecovery, setShowRecovery] = useState(false);
  const [checkedQuestionId, setCheckedQuestionId] = useState<string>();
  const questionHeading = useRef<HTMLHeadingElement>(null);
  const position = view?.attempt.position;
  useEffect(() => {
    if (position !== undefined) questionHeading.current?.focus();
  }, [position, view?.attempt.status]);
  async function back() {
    await state.pause();
    leave();
  }

  if (authLost)
    return (
      <main className={styles.standalone}>
        <h1>Sign in to continue</h1>
        <p>
          Your account-scoped draft is retained on this device. Sign in with the
          same account to recover it.
        </p>
        <a className="primary" href="/auth/login">
          Continue with Google
        </a>
        <button onClick={leave}>Back to dashboard</button>
      </main>
    );
  if (!view)
    return (
      <main className={styles.standalone}>
        <BookOpen size={32} />
        <h1>
          {state.error
            ? "Could not open this session"
            : "Preparing your study space…"}
        </h1>
        {state.error && (
          <>
            <p role="alert">{state.error}</p>
            <button className="primary" onClick={state.retry}>
              Retry
            </button>
            <button onClick={leave}>Back to dashboard</button>
          </>
        )}
      </main>
    );
  if (view.attempt.status === "submitted")
    return <Results view={view} leave={leave} />;

  const a = view.attempt;
  const q = view.questions[a.position];
  const paused = a.status !== "running";
  const answered = Object.keys(a.answers).length;
  const locked = a.checked.includes(q.id);
  const selected = a.answers[q.id];
  const flagged = a.flags.includes(q.id);
  const subject = SUBJECTS.find((s) => s.id === a.subject)?.name;
  const navigate = (position: number) => {
    edit({ position });
    setShowNavigator(false);
  };

  return (
    <div className={styles.examShell}>
      <a className="skip-link" href="#question">
        Skip to question
      </a>
      <header className={styles.examHeader}>
        <button
          className="icon-button"
          onClick={back}
          aria-label="Pause and return to dashboard"
        >
          <ArrowLeft size={20} />
        </button>
        <div className={styles.examTitle}>
          <strong>{subject}</strong>
          <span>
            {MODES[a.mode].label} · {a.questionIds.length} questions
          </span>
        </div>
        <div
          className={cx(
            styles.saveIndicator,
            state.saveStatus === "Awaiting retry" && "warning-text",
          )}
          role="status"
        >
          <Cloud size={16} />
          <span>
            {user.demo && state.saveStatus === "Synced"
              ? "Saved to preview"
              : state.saveStatus}
          </span>
        </div>
        <button
          className={cx(styles.navigatorToggle, "icon-button")}
          aria-label="Show question navigator"
          onClick={() => setShowNavigator((v) => !v)}
        >
          <List size={21} />
        </button>
      </header>
      <div className={styles.examLayout}>
        <main className={styles.questionMain} id="question">
          {state.error && (
            <div className={cx("notice", "error")} role="alert">
              {state.error}
              {!conflict && (
                <button onClick={() => state.sync()}>Retry save</button>
              )}
            </div>
          )}
          {state.recovery && state.recovery.length > 0 && (
            <div className="notice">
              <RotateCcw size={17} />
              <span>A local draft is available for recovery.</span>
              <button onClick={() => setShowRecovery(true)}>
                Review draft
              </button>
            </div>
          )}
          <div className={cx(styles.questionToolbar, "question-toolbar")}>
            <span>
              Question <strong>{a.position + 1}</strong> of{" "}
              {a.questionIds.length}
            </span>
            <button
              className={cx(styles.flagButton, flagged && styles.flagged)}
              aria-pressed={flagged}
              disabled={paused || busy}
              onClick={() =>
                edit({
                  flags: flagged
                    ? a.flags.filter((id) => id !== q.id)
                    : [...a.flags, q.id],
                })
              }
            >
              <Flag size={16} fill={flagged ? "currentColor" : "none"} />
              {flagged ? "Flagged" : "Flag for review"}
            </button>
          </div>
          <div
            className={styles.questionProgress}
            role="progressbar"
            aria-label="Questions answered"
            aria-valuenow={answered}
            aria-valuemin={0}
            aria-valuemax={a.questionIds.length}
          >
            <span
              style={{ width: `${(answered / a.questionIds.length) * 100}%` }}
            />
          </div>
          {paused || conflict ? (
            <section className={styles.pausePanel}>
              <span className={styles.pauseIcon}>
                <Pause size={28} />
              </span>
              <h1>
                {conflict
                  ? "Continue on this device?"
                  : state.pendingSubmission
                    ? "Your submission is queued."
                    : "Take a breath. You’re in control."}
              </h1>
              <p>
                {conflict
                  ? "This session is open elsewhere or has a newer save. Take over to continue here. Any local draft is retained for review and recovery."
                  : state.pendingSubmission
                    ? "Your responses are saved locally. Reconnect and retry to receive your results."
                    : "Your session is paused. Resume when you’re ready; only active study time counts."}
              </p>
              <div className={styles.pauseSummary}>
                <span>{answered} answered</span>
                <span>{a.questionIds.length - answered} remaining</span>
                <span>
                  {a.remainingMs === null
                    ? "Untimed"
                    : `${time(a.remainingMs)} left`}
                </span>
              </div>
              <button
                className="primary"
                disabled={busy}
                onClick={
                  conflict
                    ? state.takeover
                    : state.pendingSubmission
                      ? () => state.sync("submit")
                      : state.resume
                }
              >
                <Play size={17} fill="currentColor" />
                {busy
                  ? "Opening…"
                  : conflict
                    ? "Take over session"
                    : state.pendingSubmission
                      ? "Retry submission"
                      : "Resume session"}
              </button>
            </section>
          ) : (
            <>
              {q.sharedCase && (
                <aside className={styles.sharedCase}>
                  <strong>Clinical case</strong>
                  <p>{q.sharedCase.text}</p>
                </aside>
              )}
              <h1
                ref={questionHeading}
                tabIndex={-1}
                className={styles.questionStem}
              >
                {q.stem}
              </h1>
              <fieldset
                className={cx(styles.choices, "choices")}
                disabled={locked || busy}
              >
                <legend className="sr-only">Choose an answer</legend>
                {q.choices.map((choice) => (
                  <label
                    key={choice.label}
                    className={cx(
                      styles.choice,
                      "choice",
                      selected === choice.label && styles.selected,
                      q.feedback &&
                        choice.label === q.feedback.correctChoice &&
                        styles.correct,
                      q.feedback &&
                        selected === choice.label &&
                        selected !== q.feedback.correctChoice &&
                        styles.incorrect,
                    )}
                  >
                    <input
                      type="radio"
                      name={`answer-${q.id}`}
                      value={choice.label}
                      checked={selected === choice.label}
                      onChange={() =>
                        edit({
                          answers: { ...a.answers, [q.id]: choice.label },
                        })
                      }
                    />
                    <span className={styles.choiceLabel}>{choice.label}</span>
                    <span className={styles.choiceText}>{choice.text}</span>
                    {selected === choice.label && <Check size={18} />}
                  </label>
                ))}
              </fieldset>
              {a.mode === "practice" && !locked && (
                <div className={styles.checkRow}>
                  <span>
                    Check your answer to see the explanation, then continue when
                    you’re ready.
                  </span>
                  <button
                    className="primary"
                    disabled={!selected || busy}
                    onClick={() => {
                      setCheckedQuestionId(q.id);
                      void state.sync("check", q.id);
                    }}
                  >
                    <CheckCircle2 size={17} />
                    Check answer
                  </button>
                </div>
              )}
              {q.feedback && (
                <Feedback
                  question={q}
                  answer={selected}
                  autoFocus={checkedQuestionId === q.id}
                />
              )}
              <div className={styles.questionNavigation}>
                <button
                  disabled={a.position === 0 || busy}
                  onClick={() => navigate(a.position - 1)}
                >
                  <ChevronLeft size={17} />
                  Previous
                </button>
                <span>
                  {a.position + 1} / {a.questionIds.length}
                </span>
                {a.position < a.questionIds.length - 1 ? (
                  <button
                    onClick={() => navigate(a.position + 1)}
                    disabled={busy}
                  >
                    Next question
                    <ChevronRight size={17} />
                  </button>
                ) : (
                  <button
                    className="primary"
                    onClick={() => setConfirm(true)}
                    disabled={busy}
                  >
                    Finish session
                    <Check size={17} />
                  </button>
                )}
              </div>
              <p className={styles.questionSource}>
                Source question {q.originalNumber} · Original option order
                preserved
              </p>
            </>
          )}
        </main>
        <aside
          className={cx(styles.examAside, showNavigator && styles.visible)}
          aria-label="Session controls"
        >
          <div className={styles.timerCard}>
            <span className="eyebrow">
              {a.remainingMs === null ? "ACTIVE STUDY TIME" : "TIME REMAINING"}
            </span>
            <div
              className={cx(
                styles.timer,
                "timer",
                a.remainingMs !== null &&
                  a.remainingMs < 60000 &&
                  "warning-text",
              )}
            >
              <Clock3 size={23} />
              <span
                aria-label={
                  a.remainingMs === null
                    ? "Active study time"
                    : "Remaining time"
                }
              >
                {time(a.remainingMs ?? a.elapsedMs)}
              </span>
            </div>
            <p>
              {paused
                ? "Paused. Ready when you are."
                : a.mode === "practice"
                  ? "Take your time. Understand the why."
                  : "Your timer pauses when you leave."}
            </p>
            <button
              className="full"
              disabled={busy || conflict || state.pendingSubmission}
              onClick={paused ? state.resume : state.pause}
            >
              {paused ? <Play size={15} /> : <Pause size={15} />}
              {paused ? "Resume" : "Pause session"}
            </button>
          </div>
          <div className={styles.navigator}>
            <div className="section-head">
              <h2>Your questions</h2>
              <span>
                {answered}/{a.questionIds.length}
              </span>
            </div>
            <div className={cx(styles.questionGrid, "question-grid")}>
              {view.questions.map((question, i) => (
                <button
                  key={question.id}
                  aria-label={`Question ${i + 1}${a.checked.includes(question.id) ? (a.answers[question.id] === question.feedback?.correctChoice ? ", checked correct" : ", checked incorrect") : a.answers[question.id] ? ", answered" : ", unanswered"}${a.flags.includes(question.id) ? ", flagged" : ""}`}
                  aria-current={a.position === i ? "step" : undefined}
                  disabled={paused || busy}
                  className={cx(
                    a.checked.includes(question.id)
                      ? a.answers[question.id] ===
                        question.feedback?.correctChoice
                        ? cx(styles.checkedCorrect, "checked-correct")
                        : cx(styles.checkedIncorrect, "checked-incorrect")
                      : a.answers[question.id]
                        ? cx(styles.answered, "answered")
                        : undefined,
                    a.position === i && styles.current,
                    a.flags.includes(question.id) && styles.flagged,
                  )}
                  onClick={() => navigate(i)}
                >
                  {i + 1}
                  {a.checked.includes(question.id) &&
                    (a.answers[question.id] ===
                    question.feedback?.correctChoice ? (
                      <Check
                        size={10}
                        className={styles.navigatorResultIcon}
                        aria-hidden="true"
                      />
                    ) : (
                      <XCircle
                        size={10}
                        className={styles.navigatorResultIcon}
                        aria-hidden="true"
                      />
                    ))}
                  {a.flags.includes(question.id) && (
                    <span className={styles.flagDot} />
                  )}
                </button>
              ))}
            </div>
            <div className={styles.navigatorLegend}>
              <span>
                <i className={styles.answeredKey} />
                Selected
              </span>
              {a.mode === "practice" && (
                <>
                  <span>
                    <i className={styles.correctKey} />
                    Correct
                  </span>
                  <span>
                    <i className={styles.incorrectKey} />
                    Incorrect
                  </span>
                </>
              )}
              <span>
                <i className={styles.flagKey} />
                Flagged
              </span>
              <span>
                <i />
                Unanswered
              </span>
            </div>
          </div>
          <button
            className={cx(styles.submitButton, "full")}
            disabled={busy || conflict}
            onClick={() => setConfirm(true)}
          >
            Submit session
            <ArrowRight size={17} />
          </button>
          <p className={styles.asideNote}>
            Unanswered questions count toward your final score.
          </p>
        </aside>
      </div>
      {confirm && (
        <Modal title="Ready to finish?" close={() => setConfirm(false)}>
          <p>
            You’ve answered{" "}
            <strong>
              {answered} of {a.questionIds.length}
            </strong>{" "}
            questions.
          </p>
          <p>
            {a.questionIds.length - answered > 0
              ? `${a.questionIds.length - answered} unanswered questions will count as incorrect in your score.`
              : "All questions have an answer."}{" "}
            Your responses will be locked and your results will be available.
          </p>
          <div className="dialog-actions">
            <button onClick={() => setConfirm(false)}>Keep studying</button>
            <button
              className="primary"
              disabled={busy}
              onClick={async () => {
                await state.sync("submit");
                setConfirm(false);
              }}
            >
              {busy ? "Submitting…" : "Submit session"}
            </button>
          </div>
        </Modal>
      )}
      {showRecovery && state.recovery?.[0] && (
        <Recovery
          draft={state.recovery[0]}
          current={view}
          canRestore={!conflict}
          close={() => setShowRecovery(false)}
          restore={(draft) => {
            const answers = { ...a.answers };
            for (const [id, answer] of Object.entries(
              draft.view.attempt.answers,
            ))
              if (
                !a.checked.includes(id) &&
                view.questions.some(
                  (q) =>
                    q.id === id && q.choices.some((c) => c.label === answer),
                )
              )
                answers[id] = answer;
            const remainingMs =
              a.remainingMs === null
                ? null
                : Math.min(
                    a.remainingMs,
                    draft.view.attempt.remainingMs ?? a.remainingMs,
                  );
            const elapsedMs =
              remainingMs === null
                ? Math.max(a.elapsedMs, draft.view.attempt.elapsedMs)
                : a.elapsedMs + a.remainingMs! - remainingMs;
            edit({
              answers,
              flags: [
                ...new Set([...a.flags, ...draft.view.attempt.flags]),
              ].filter((id) => a.questionIds.includes(id)),
              remainingMs,
              elapsedMs,
              status: "paused",
            });
            setShowRecovery(false);
            void state.sync();
          }}
        />
      )}
    </div>
  );
}

function Feedback({
  question,
  answer,
  autoFocus = false,
}: {
  question: PublicQuestion;
  answer?: string;
  autoFocus?: boolean;
}) {
  const heading = useRef<HTMLHeadingElement>(null);
  const feedback = question.feedback!;
  const correct = answer === feedback.correctChoice;
  const unanswered = !answer;
  useEffect(() => {
    if (autoFocus) heading.current?.focus();
  }, [autoFocus]);
  return (
    <section
      className={cx(
        styles.feedback,
        "feedback",
        correct && styles.isCorrect,
        unanswered && styles.isUnanswered,
      )}
      aria-live="polite"
      aria-label="Answer feedback"
    >
      <div className={styles.feedbackHeader}>
        <div className={styles.feedbackMark} aria-hidden="true">
          {answer ?? "—"}
        </div>
        <div className={cx(styles.feedbackVerdict, "feedback-verdict")}>
          <span className={styles.feedbackKicker}>Answer review</span>
          <h2 ref={heading} tabIndex={-1}>
            {correct
              ? "That’s correct."
              : answer
                ? "Review this answer."
                : "Review the source answer."}
          </h2>
        </div>
        <span className={styles.feedbackAnswer}>
          Correct choice <strong>{feedback.correctChoice}</strong>
        </span>
      </div>
      <div className={styles.feedbackBody}>
        <p className={styles.feedbackLede}>
          {correct
            ? "Your choice matches the source answer key."
            : answer
              ? "Use the explanation to compare your choice with the source answer."
              : "Use the explanation to review the source answer before continuing."}
        </p>
        <div className={styles.explanation} data-testid="feedback-explanation">
          {feedback.explanation || "No explanation was provided in the source."}
        </div>
      </div>
      <details className={styles.sourceDetails}>
        <summary>View source pages</summary>
        {feedback.sources.map((source, i) => (
          <p key={`pages-${i}`}>
            Source {i + 1} · Question / explanation: pages{" "}
            {source.pages.join(", ")}
            {source.answerPages?.length
              ? ` · Answer key: pages ${source.answerPages.join(", ")}`
              : ""}
          </p>
        ))}
      </details>
      <details className={styles.sourceFiles}>
        <summary>Show source files</summary>
        {feedback.sources.map((source, i) => (
          <p key={`files-${i}`}>
            <strong>{source.filename}</strong>
            <br />
            Question / explanation: pages {source.pages.join(", ")}
            {source.answerPages?.length
              ? ` · Answer key: pages ${source.answerPages.join(", ")}`
              : ""}
          </p>
        ))}
      </details>
    </section>
  );
}

function Results({ view, leave }: { view: AttemptView; leave: () => void }) {
  const [filter, setFilter] = useState("all");
  const a = view.attempt;
  const correct = a.score ?? 0;
  const unanswered = a.questionIds.length - Object.keys(a.answers).length;
  const incorrect = a.questionIds.length - correct - unanswered;
  const percentage = Math.round((correct / a.questionIds.length) * 100);
  const questions = view.questions.filter(
    (q) =>
      filter === "all" ||
      (filter === "mistakes" &&
        a.answers[q.id] !== q.feedback?.correctChoice) ||
      (filter === "flagged" && a.flags.includes(q.id)),
  );
  return (
    <div className={styles.resultsShell}>
      <header className={styles.examHeader}>
        <button
          className="icon-button"
          onClick={leave}
          aria-label="Back to dashboard"
        >
          <ArrowLeft size={20} />
        </button>
        <div className={styles.examTitle}>
          <strong>Session complete</strong>
          <span>
            {SUBJECTS.find((s) => s.id === a.subject)?.name} ·{" "}
            {MODES[a.mode].label}
          </span>
        </div>
        <span className={styles.saveIndicator}>
          <CheckCircle2 size={16} />
          Saved
        </span>
      </header>
      <main className={styles.resultsMain}>
        <section className={styles.resultHero}>
          <div
            className={styles.scoreRing}
            style={{ "--score": `${percentage}%` } as React.CSSProperties}
          >
            <div>
              <strong>{percentage}%</strong>
              <span>
                {correct} of {a.questionIds.length}
              </span>
            </div>
          </div>
          <div>
            <div className="eyebrow">ANOTHER STEP FORWARD</div>
            <h1>Progress starts with practice.</h1>
            <p>
              Revisit the questions, understand the explanations, and take that
              knowledge into your next session.
            </p>
            <span className="muted small">
              <Clock3 size={14} className={styles.inlineIcon} />{" "}
              {time(a.elapsedMs)} active study time
            </span>
          </div>
        </section>
        <div className={styles.resultCounts}>
          <div>
            <span className="success-text">Correct</span>
            <strong>{correct}</strong>
          </div>
          <div>
            <span className="error-text">Incorrect</span>
            <strong>{incorrect}</strong>
          </div>
          <div>
            <span className="muted">Unanswered</span>
            <strong>{unanswered}</strong>
          </div>
        </div>
        <div className={cx("section-head", styles.reviewHeader)}>
          <h2>Review your session</h2>
          <div className={styles.filterPills}>
            {[
              { id: "all", name: "All questions" },
              { id: "mistakes", name: "Mistakes" },
              { id: "flagged", name: "Flagged" },
            ].map((f) => (
              <button
                key={f.id}
                className={filter === f.id ? styles.active : undefined}
                aria-pressed={filter === f.id}
                onClick={() => setFilter(f.id)}
              >
                {f.name}
              </button>
            ))}
          </div>
        </div>
        {questions.map((q) => (
          <article
            key={q.id}
            className={cx(styles.resultQuestion, "result-question")}
          >
            <div className={cx(styles.questionToolbar, "question-toolbar")}>
              <span>
                Question {view.questions.indexOf(q) + 1}{" "}
                <span className="muted">· Source {q.originalNumber}</span>
              </span>
              {a.flags.includes(q.id) && (
                <Flag size={17} className="warning-text" />
              )}
            </div>
            {q.sharedCase && (
              <p className={styles.sharedCase}>{q.sharedCase.text}</p>
            )}
            <h3>{q.stem}</h3>
            <div className={styles.resultChoices}>
              {q.choices.map((c) => (
                <div
                  key={c.label}
                  className={cx(
                    c.label === q.feedback?.correctChoice
                      ? styles.successText
                      : a.answers[q.id] === c.label
                        ? styles.errorText
                        : undefined,
                  )}
                >
                  <b>{c.label}</b>
                  <span>{c.text}</span>
                  {a.answers[q.id] === c.label && <small>Your answer</small>}
                  {c.label === q.feedback?.correctChoice && <Check size={17} />}
                </div>
              ))}
            </div>
            <Feedback question={q} answer={a.answers[q.id]} />
          </article>
        ))}
        {!questions.length && (
          <div className="empty">No questions in this filter.</div>
        )}
        <button className="primary" onClick={leave}>
          Back to your study space
          <ArrowRight size={18} />
        </button>
        <p className={cx("small", "muted", styles.resultsNote)}>
          Scores reflect the historical source answer keys. Source explanations
          have not been updated to current clinical guidelines.
        </p>
      </main>
    </div>
  );
}

function Recovery({
  draft,
  current,
  canRestore,
  close,
  restore,
}: {
  draft: Draft;
  current: AttemptView;
  canRestore: boolean;
  close: () => void;
  restore: (draft: Draft) => void;
}) {
  const differences = Object.entries(draft.view.attempt.answers).filter(
    ([id, answer]) => current.attempt.answers[id] !== answer,
  );
  function download() {
    const blob = new Blob([JSON.stringify(draft, null, 2)], {
      type: "application/json",
    });
    const url = URL.createObjectURL(blob);
    const a = document.createElement("a");
    a.href = url;
    a.download = `ple-draft-${draft.attemptId}.json`;
    a.click();
    URL.revokeObjectURL(url);
  }
  return (
    <Modal title="Your saved local draft" close={close}>
      <p>
        Saved {new Date(draft.savedAt).toLocaleString()}. There are{" "}
        {differences.length} answers that differ from the current session.
      </p>
      <p>
        Restoring copies its editable answers and review flags into this
        session. Checked answers stay locked, and remaining time can only
        decrease.
      </p>
      <div className={styles.recoveryDifferences}>
        {differences.map(([id, answer]) => (
          <p key={id}>
            Question {current.attempt.questionIds.indexOf(id) + 1}: current{" "}
            {current.attempt.answers[id] ?? "unanswered"} → draft {answer}
          </p>
        ))}
      </div>
      <div className="dialog-actions">
        <button onClick={download}>
          <Download size={16} />
          Download draft
        </button>
        <button
          className="primary"
          disabled={
            !canRestore ||
            draft.view.attempt.bankVersion !== current.attempt.bankVersion
          }
          onClick={() => restore(draft)}
        >
          Restore draft
        </button>
      </div>
      {!canRestore && (
        <p className="small muted">
          Take over the session before restoring this draft.
        </p>
      )}
    </Modal>
  );
}
