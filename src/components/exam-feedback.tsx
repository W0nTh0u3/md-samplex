"use client";

import { useEffect, useRef } from "react";
import {
  answerLabels,
  feedbackAnswerIsCorrect,
  feedbackAnswerMode,
  feedbackCorrectLabels,
  hasAnswer,
} from "@/lib/answers";
import type { Answer, PublicQuestion } from "@/lib/types";
import { cx } from "./component-utils";
import { ExamVisuals } from "./exam-visuals";
import styles from "./exam-feedback.module.scss";

type ExamFeedbackProps = {
  question: PublicQuestion;
  answer?: Answer;
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
  const mode = feedbackAnswerMode(feedback);
  const selectedLabels = answerLabels(answer);
  const keyedLabels = feedbackCorrectLabels(feedback);
  const correct = feedbackAnswerIsCorrect(feedback, answer);
  const unanswered = selectedLabels.length === 0;
  const rationaleChoices = question.choices.filter((choice) =>
    feedback.choiceRationales?.[choice.label]?.trim(),
  );
  const hasChoiceRationales = rationaleChoices.length > 0;
  const keyedRationales = keyedLabels
    .map((label) => feedback.choiceRationales?.[label]?.trim())
    .filter((value): value is string => Boolean(value));
  const explanationText = feedback.explanation.trim();
  const keyedExplanation = keyedRationales.join(" ");
  const hasDistinctExplanation = Boolean(
    explanationText &&
    explanationText !== keyedExplanation &&
    !keyedRationales.includes(explanationText),
  );
  const selectedText = selectedLabels.length ? selectedLabels.join(", ") : "—";
  const correctText = keyedLabels.length ? keyedLabels.join(", ") : "—";
  const hasNotionLocator = feedback.sources.some(
    (source) => source.kind === "notion" || Boolean(source.locator),
  );

  function sourceLocation(source: (typeof feedback.sources)[number]) {
    const questionLocation = source.pages.length
      ? `Question / explanation: pages ${source.pages.join(", ")}`
      : source.locator
        ? `Notion locator: ${source.locator}`
        : "Question / explanation: local export";
    const answerLocation = source.answerPages?.length
      ? ` · Answer key: pages ${source.answerPages.join(", ")}`
      : "";
    return `${questionLocation}${answerLocation}`;
  }

  function sourceUrl(source: (typeof feedback.sources)[number]) {
    return source.url && /^https?:\/\//i.test(source.url) ? source.url : null;
  }

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
          {selectedText}
        </div>
        <div className={cx(styles.feedbackVerdict, "feedback-verdict")}>
          <span className={styles.feedbackKicker}>Answer review</span>
          <h2 ref={heading} tabIndex={-1}>
            {correct
              ? "That’s correct."
              : hasAnswer(answer)
                ? "Review this answer."
                : "Review the source answer."}
          </h2>
        </div>
        <span className={styles.feedbackAnswer}>
          <span>
            {mode === "multiple" ? "Correct choices" : "Correct choice"}
          </span>{" "}
          <strong>{correctText}</strong>
          {mode === "multiple" && selectedLabels.length > 0 && (
            <>
              <br />
              <span>Your choices</span> <strong>{selectedText}</strong>
            </>
          )}
        </span>
      </div>
      <div className={styles.feedbackBody}>
        <p className={styles.feedbackLede}>
          {mode === "multiple"
            ? correct
              ? "Your selected set matches the source answer key exactly."
              : "Compare your selected set with the complete keyed set."
            : hasChoiceRationales
              ? "Compare each option with the source rationale before continuing."
              : correct
                ? "Your choice matches the source answer key."
                : hasAnswer(answer)
                  ? "Use the explanation to compare your choice with the source answer."
                  : "Use the explanation to review the source answer before continuing."}
        </p>
        {hasChoiceRationales && (
          <section
            className={styles.choiceRationales}
            data-testid="feedback-choice-rationales"
            aria-label="Choice rationales"
          >
            <div className={styles.rationaleHeading}>
              <h3>Why each choice is right or wrong</h3>
              <span>Source rationale</span>
            </div>
            <ol>
              {rationaleChoices.map((choice) => {
                const isCorrect = keyedLabels.includes(choice.label);
                const isSelected = selectedLabels.includes(choice.label);
                return (
                  <li
                    key={choice.label}
                    className={cx(
                      styles.rationale,
                      isCorrect && styles.rationaleCorrect,
                      isSelected && !isCorrect && styles.rationaleSelected,
                    )}
                    data-testid="feedback-choice-rationale"
                  >
                    <div className={styles.rationaleChoice}>
                      <strong>{choice.label}</strong>
                      <span>{choice.text}</span>
                      <small>
                        {isCorrect
                          ? "Correct choice"
                          : isSelected
                            ? "Your choice"
                            : "Not the source answer"}
                      </small>
                    </div>
                    <p>{feedback.choiceRationales?.[choice.label]}</p>
                  </li>
                );
              })}
            </ol>
          </section>
        )}
        {(!hasChoiceRationales || hasDistinctExplanation) && (
          <div
            className={styles.explanation}
            data-testid="feedback-explanation"
          >
            {feedback.explanation ||
              "No explanation was provided in the source."}
          </div>
        )}
        <ExamVisuals
          visuals={question.visuals}
          visibility="feedback"
          className={styles.feedbackVisuals}
        />
      </div>
      <details className={styles.sourceDetails}>
        <summary>
          {hasNotionLocator ? "View source locations" : "View source pages"}
        </summary>
        {feedback.sources.map((source, index) => (
          <p key={`pages-${index}`}>
            Source {index + 1} · {sourceLocation(source)}
            {sourceUrl(source) && (
              <>
                {" "}
                <a href={sourceUrl(source)!} target="_blank" rel="noreferrer">
                  Open original
                </a>
              </>
            )}
          </p>
        ))}
      </details>
      <details className={styles.sourceFiles}>
        <summary>Show source files</summary>
        {feedback.sources.map((source, index) => (
          <p key={`files-${index}`}>
            <strong>{source.filename}</strong>
            <br />
            {sourceLocation(source)}
            {source.title && (
              <>
                <br />
                Notion page: {source.title}
              </>
            )}
            {sourceUrl(source) && (
              <>
                <br />
                <a href={sourceUrl(source)!} target="_blank" rel="noreferrer">
                  Open original
                </a>
              </>
            )}
          </p>
        ))}
      </details>
    </section>
  );
}
