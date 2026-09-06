"use client";
import { ArrowRight, Check, Clock3, Pause, Play, XCircle } from "lucide-react";
import type { Attempt, PublicQuestion } from "@/lib/types";
import { cx, formatTime } from "./component-utils";
import styles from "./exam-question.module.scss";

type ExamNavigatorProps = {
  attempt: Attempt;
  questions: PublicQuestion[];
  paused: boolean;
  busy: boolean;
  conflict: boolean;
  pendingSubmission: boolean;
  visible: boolean;
  onResume: () => void;
  onPause: () => void | Promise<void>;
  onNavigate: (position: number) => void;
  onSubmit: () => void;
};

export function ExamNavigator({
  attempt,
  questions,
  paused,
  busy,
  conflict,
  pendingSubmission,
  visible,
  onResume,
  onPause,
  onNavigate,
  onSubmit,
}: ExamNavigatorProps) {
  const answered = Object.keys(attempt.answers).length;
  return (
    <aside
      className={cx(styles.examAside, visible && styles.visible)}
      aria-label="Session controls"
    >
      <div className={styles.timerCard}>
        <span className="eyebrow">
          {attempt.remainingMs === null
            ? "ACTIVE STUDY TIME"
            : "TIME REMAINING"}
        </span>
        <div
          className={cx(
            styles.timer,
            "timer",
            attempt.remainingMs !== null &&
              attempt.remainingMs < 60000 &&
              "warning-text",
          )}
        >
          <Clock3 size={23} />
          <span
            aria-label={
              attempt.remainingMs === null
                ? "Active study time"
                : "Remaining time"
            }
          >
            {formatTime(attempt.remainingMs ?? attempt.elapsedMs)}
          </span>
        </div>
        <p>
          {paused
            ? "Paused. Ready when you are."
            : attempt.mode === "practice"
              ? "Take your time. Understand the why."
              : "Your timer pauses when you leave."}
        </p>
        <button
          className="full"
          disabled={busy || conflict || pendingSubmission}
          onClick={paused ? onResume : onPause}
        >
          {paused ? <Play size={15} /> : <Pause size={15} />}
          {paused ? "Resume" : "Pause session"}
        </button>
      </div>
      <div className={styles.navigator}>
        <div className="section-head">
          <h2>Your questions</h2>
          <span>
            {answered}/{attempt.questionIds.length}
          </span>
        </div>
        <div className={cx(styles.questionGrid, "question-grid")}>
          {questions.map((question, index) => (
            <button
              key={question.id}
              aria-label={`Question ${index + 1}${attempt.checked.includes(question.id) ? (attempt.answers[question.id] === question.feedback?.correctChoice ? ", checked correct" : ", checked incorrect") : attempt.answers[question.id] ? ", answered" : ", unanswered"}${attempt.flags.includes(question.id) ? ", flagged" : ""}`}
              aria-current={attempt.position === index ? "step" : undefined}
              disabled={paused || busy}
              className={cx(
                attempt.checked.includes(question.id)
                  ? attempt.answers[question.id] ===
                    question.feedback?.correctChoice
                    ? cx(styles.checkedCorrect, "checked-correct")
                    : cx(styles.checkedIncorrect, "checked-incorrect")
                  : attempt.answers[question.id]
                    ? cx(styles.answered, "answered")
                    : undefined,
                attempt.position === index && styles.current,
                attempt.flags.includes(question.id) && styles.flagged,
              )}
              onClick={() => onNavigate(index)}
            >
              {index + 1}
              {attempt.checked.includes(question.id) &&
                (attempt.answers[question.id] ===
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
              {attempt.flags.includes(question.id) && (
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
          {attempt.mode === "practice" && (
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
        onClick={onSubmit}
      >
        Submit session
        <ArrowRight size={17} />
      </button>
      <p className={styles.asideNote}>
        Unanswered questions count toward your final score.
      </p>
    </aside>
  );
}
