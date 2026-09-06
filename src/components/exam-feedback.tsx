"use client";
import { useEffect, useRef } from "react";
import type { PublicQuestion } from "@/lib/types";
import { cx } from "./component-utils";
import styles from "./exam-feedback.module.scss";

type ExamFeedbackProps = {
  question: PublicQuestion;
  answer?: string;
  autoFocus?: boolean;
  className?: string;
};

export function ExamFeedback({
  question,
  answer,
  autoFocus = false,
  className,
}: ExamFeedbackProps) {
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
        className,
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
        {feedback.sources.map((source, index) => (
          <p key={`pages-${index}`}>
            Source {index + 1} · Question / explanation: pages{" "}
            {source.pages.join(", ")}
            {source.answerPages?.length
              ? ` · Answer key: pages ${source.answerPages.join(", ")}`
              : ""}
          </p>
        ))}
      </details>
      <details className={styles.sourceFiles}>
        <summary>Show source files</summary>
        {feedback.sources.map((source, index) => (
          <p key={`files-${index}`}>
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
