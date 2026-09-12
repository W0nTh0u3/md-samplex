"use client";
import { useEffect, useRef } from "react";
import {
  Check,
  CheckCircle2,
  ChevronLeft,
  ChevronRight,
  CircleAlert,
  Flag,
  Pause,
  Play,
  RotateCcw,
} from "lucide-react";
import {
  answerLabels,
  answerMode,
  countAnswered,
  feedbackCorrectLabels,
  hasAnswer,
} from "@/lib/answers";
import type { Attempt, PublicQuestion } from "@/lib/types";
import { cx, formatTime } from "./component-utils";
import { ExamFeedback } from "./exam-feedback";
import { ExamVisuals } from "./exam-visuals";
import type { EditAttempt, SyncAction } from "./study-types";
import styles from "./exam-question.module.scss";

type ExamQuestionProps = {
  attempt: Attempt;
  question: PublicQuestion;
  error: string;
  recoveryAvailable: boolean;
  conflict: boolean;
  pendingSubmission: boolean;
  busy: boolean;
  checkedQuestionId?: string;
  onRetry: () => void;
  onShowRecovery: () => void;
  onEdit: EditAttempt;
  onSync: (
    action?: SyncAction,
    questionId?: string,
    keepalive?: boolean,
  ) => Promise<void>;
  onChecked: (questionId: string) => void;
  onResume: () => void;
  onTakeover: () => void;
  onNavigate: (position: number) => void;
  onFinish: () => void;
};

export function ExamQuestion({
  attempt,
  question,
  error,
  recoveryAvailable,
  conflict,
  pendingSubmission,
  busy,
  checkedQuestionId,
  onRetry,
  onShowRecovery,
  onEdit,
  onSync,
  onChecked,
  onResume,
  onTakeover,
  onNavigate,
  onFinish,
}: ExamQuestionProps) {
  const questionHeading = useRef<HTMLHeadingElement>(null);
  const paused = attempt.status !== "running";
  const answered = countAnswered(attempt.answers);
  const locked = attempt.checked.includes(question.id);
  const selected = attempt.answers[question.id];
  const selectedLabels = answerLabels(selected);
  const multiple = answerMode(question) === "multiple";
  const correctLabels = question.feedback
    ? feedbackCorrectLabels(question.feedback)
    : [];
  const flagged = attempt.flags.includes(question.id);

  function choose(label: string, checked = true) {
    if (multiple) {
      const next = checked
        ? [...new Set([...selectedLabels, label])]
        : selectedLabels.filter((value) => value !== label);
      const answers = { ...attempt.answers };
      if (next.length) answers[question.id] = next;
      else delete answers[question.id];
      onEdit({ answers });
      return;
    }
    onEdit({
      answers: {
        ...attempt.answers,
        [question.id]: label,
      },
    });
  }

  useEffect(() => {
    questionHeading.current?.focus();
  }, [attempt.position, attempt.status]);

  return (
    <main className={styles.questionMain} id="question">
      {error && (
        <div className={cx("notice", "error")} role="alert">
          <CircleAlert size={17} aria-hidden="true" />
          <span>{error}</span>
          {!conflict && <button onClick={onRetry}>Retry save</button>}
        </div>
      )}
      {recoveryAvailable && (
        <div className="notice">
          <RotateCcw size={17} />
          <span>A local draft is available for recovery.</span>
          <button onClick={onShowRecovery}>Review draft</button>
        </div>
      )}
      <div className={cx(styles.questionToolbar, "question-toolbar")}>
        <span>
          Question <strong>{attempt.position + 1}</strong> of{" "}
          {attempt.questionIds.length}
        </span>
        <button
          className={cx(styles.flagButton, flagged && styles.flagged)}
          aria-pressed={flagged}
          disabled={paused || busy}
          onClick={() =>
            onEdit({
              flags: flagged
                ? attempt.flags.filter((id) => id !== question.id)
                : [...attempt.flags, question.id],
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
        aria-valuemax={attempt.questionIds.length}
      >
        <span
          style={{
            width: `${(answered / attempt.questionIds.length) * 100}%`,
          }}
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
              : pendingSubmission
                ? "Your submission is queued."
                : "Take a breath. You’re in control."}
          </h1>
          <p>
            {conflict
              ? "This session is open elsewhere or has a newer save. Take over to continue here. Any local draft is retained for review and recovery."
              : pendingSubmission
                ? "Your responses are saved locally. Reconnect and retry to receive your results."
                : "Your session is paused. Resume when you’re ready; only active study time counts."}
          </p>
          <div className={styles.pauseSummary}>
            <span>{answered} answered</span>
            <span>{attempt.questionIds.length - answered} remaining</span>
            <span>
              {attempt.remainingMs === null
                ? "Untimed"
                : `${formatTime(attempt.remainingMs)} left`}
            </span>
          </div>
          <button
            className="primary"
            disabled={busy}
            onClick={
              conflict
                ? onTakeover
                : pendingSubmission
                  ? () => onSync("submit")
                  : onResume
            }
          >
            <Play size={17} fill="currentColor" />
            {busy
              ? "Opening…"
              : conflict
                ? "Take over session"
                : pendingSubmission
                  ? "Retry submission"
                  : "Resume session"}
          </button>
        </section>
      ) : (
        <>
          {question.sharedCase && (
            <aside className={styles.sharedCase}>
              <strong>Clinical case</strong>
              <p>{question.sharedCase.text}</p>
              <ExamVisuals
                visuals={question.sharedCase.visuals}
                visibility="question"
                className={styles.caseVisuals}
              />
              {question.feedback && (
                <ExamVisuals
                  visuals={question.sharedCase.visuals}
                  visibility="feedback"
                  className={styles.caseFeedbackVisuals}
                />
              )}
            </aside>
          )}
          <h1
            ref={questionHeading}
            tabIndex={-1}
            className={styles.questionStem}
          >
            {question.stem}
          </h1>
          <ExamVisuals visuals={question.visuals} visibility="question" />
          <fieldset
            className={cx(styles.choices, "choices")}
            disabled={locked || busy}
          >
            <legend>{multiple ? "Select all that apply" : "Choose one"}</legend>
            {question.choices.map((choice) => {
              const isSelected = selectedLabels.includes(choice.label);
              const isCorrect = correctLabels.includes(choice.label);
              return (
                <label
                  key={choice.label}
                  className={cx(
                    styles.choice,
                    "choice",
                    isSelected && styles.selected,
                    question.feedback && isCorrect && styles.correct,
                    question.feedback &&
                      isSelected &&
                      !isCorrect &&
                      styles.incorrect,
                  )}
                >
                  <input
                    type={multiple ? "checkbox" : "radio"}
                    name={`answer-${question.id}`}
                    value={choice.label}
                    checked={isSelected}
                    onChange={(event) =>
                      choose(choice.label, event.currentTarget.checked)
                    }
                  />
                  <span className={styles.choiceLabel}>{choice.label}</span>
                  <span className={styles.choiceText}>{choice.text}</span>
                  {isSelected && <Check size={18} />}
                </label>
              );
            })}
          </fieldset>
          <p
            className={styles.answerInstruction}
            data-testid="answer-instruction"
          >
            {multiple
              ? "Select every option supported by the source."
              : "Select the single best answer."}
          </p>
          {attempt.mode === "practice" && !locked && (
            <div className={styles.checkRow}>
              <span>
                Check your answer to see the explanation, then continue when
                you’re ready.
              </span>
              <button
                className="primary"
                disabled={!hasAnswer(selected) || busy}
                onClick={() => {
                  onChecked(question.id);
                  void onSync("check", question.id);
                }}
              >
                <CheckCircle2 size={17} />
                Check answer
              </button>
            </div>
          )}
          {question.feedback && (
            <ExamFeedback
              question={question}
              answer={selected}
              autoFocus={checkedQuestionId === question.id}
            />
          )}
          <div className={styles.questionNavigation}>
            <button
              disabled={attempt.position === 0 || busy}
              onClick={() => onNavigate(attempt.position - 1)}
            >
              <ChevronLeft size={17} />
              Previous
            </button>
            <span>
              {attempt.position + 1} / {attempt.questionIds.length}
            </span>
            {attempt.position < attempt.questionIds.length - 1 ? (
              <button
                onClick={() => onNavigate(attempt.position + 1)}
                disabled={busy}
              >
                Next question
                <ChevronRight size={17} />
              </button>
            ) : (
              <button className="primary" onClick={onFinish} disabled={busy}>
                Finish session
                <Check size={17} />
              </button>
            )}
          </div>
          <p className={styles.questionSource}>
            Source question {question.originalNumber} · Original option order
            preserved
          </p>
        </>
      )}
    </main>
  );
}
