"use client";
import { useState } from "react";
import {
  ArrowLeft,
  ArrowRight,
  Check,
  CheckCircle2,
  Clock3,
  Flag,
} from "lucide-react";
import { MODES, SUBJECTS, type AttemptView } from "@/lib/types";
import { cx, formatTime } from "./component-utils";
import { ExamFeedback } from "./exam-feedback";
import questionStyles from "./exam-question.module.scss";
import shellStyles from "./exam.module.scss";
import styles from "./exam-results.module.scss";

type ExamResultsProps = {
  view: AttemptView;
  leave: () => void;
};

export function ExamResults({ view, leave }: ExamResultsProps) {
  const [filter, setFilter] = useState("all");
  const attempt = view.attempt;
  const correct = attempt.score ?? 0;
  const unanswered =
    attempt.questionIds.length - Object.keys(attempt.answers).length;
  const incorrect = attempt.questionIds.length - correct - unanswered;
  const percentage = Math.round((correct / attempt.questionIds.length) * 100);
  const questions = view.questions.filter(
    (question) =>
      filter === "all" ||
      (filter === "mistakes" &&
        attempt.answers[question.id] !== question.feedback?.correctChoice) ||
      (filter === "flagged" && attempt.flags.includes(question.id)),
  );

  return (
    <div className={shellStyles.resultsShell}>
      <header className={shellStyles.examHeader}>
        <button
          className="icon-button"
          onClick={leave}
          aria-label="Back to dashboard"
        >
          <ArrowLeft size={20} />
        </button>
        <div className={shellStyles.examTitle}>
          <strong>Session complete</strong>
          <span>
            {SUBJECTS.find((subject) => subject.id === attempt.subject)?.name} ·{" "}
            {MODES[attempt.mode].label}
          </span>
        </div>
        <span className={shellStyles.saveIndicator}>
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
                {correct} of {attempt.questionIds.length}
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
              {formatTime(attempt.elapsedMs)} active study time
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
            ].map((option) => (
              <button
                key={option.id}
                className={filter === option.id ? styles.active : undefined}
                aria-pressed={filter === option.id}
                onClick={() => setFilter(option.id)}
              >
                {option.name}
              </button>
            ))}
          </div>
        </div>
        {questions.map((question) => (
          <article
            key={question.id}
            className={cx(styles.resultQuestion, "result-question")}
          >
            <div
              className={cx(
                questionStyles.questionToolbar,
                styles.resultQuestionToolbar,
                "question-toolbar",
              )}
            >
              <span>
                Question {view.questions.indexOf(question) + 1}{" "}
                <span className="muted">
                  · Source {question.originalNumber}
                </span>
              </span>
              {attempt.flags.includes(question.id) && (
                <Flag size={17} className="warning-text" />
              )}
            </div>
            {question.sharedCase && (
              <p className={questionStyles.sharedCase}>
                {question.sharedCase.text}
              </p>
            )}
            <h3>{question.stem}</h3>
            <div className={styles.resultChoices}>
              {question.choices.map((choice) => (
                <div
                  key={choice.label}
                  className={cx(
                    choice.label === question.feedback?.correctChoice
                      ? styles.successText
                      : attempt.answers[question.id] === choice.label
                        ? styles.errorText
                        : undefined,
                  )}
                >
                  <b>{choice.label}</b>
                  <span>{choice.text}</span>
                  {attempt.answers[question.id] === choice.label && (
                    <small>Your answer</small>
                  )}
                  {choice.label === question.feedback?.correctChoice && (
                    <Check size={17} />
                  )}
                </div>
              ))}
            </div>
            <ExamFeedback
              question={question}
              answer={attempt.answers[question.id]}
              className={styles.resultFeedback}
            />
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
