"use client";
import { ArrowLeft, Cloud, List } from "lucide-react";
import { cx } from "./component-utils";
import type { ExamUser } from "./study-types";
import styles from "./exam.module.scss";

type ExamHeaderProps = {
  subject?: string;
  modeLabel: string;
  questionCount: number;
  user: ExamUser;
  saveStatus: string;
  showNavigator: boolean;
  onBack: () => void | Promise<void>;
  onToggleNavigator: () => void;
};

export function ExamHeader({
  subject,
  modeLabel,
  questionCount,
  user,
  saveStatus,
  showNavigator,
  onBack,
  onToggleNavigator,
}: ExamHeaderProps) {
  return (
    <header className={styles.examHeader}>
      <button
        className="icon-button"
        onClick={onBack}
        aria-label="Pause and return to dashboard"
      >
        <ArrowLeft size={20} />
      </button>
      <div className={styles.examTitle}>
        <strong>{subject}</strong>
        <span>
          {modeLabel} · {questionCount} questions
        </span>
      </div>
      <div
        className={cx(
          styles.saveIndicator,
          saveStatus === "Awaiting retry" && "warning-text",
        )}
        role="status"
      >
        <Cloud size={16} />
        <span>
          {user.demo && saveStatus === "Synced"
            ? "Saved to preview"
            : saveStatus}
        </span>
      </div>
      <button
        className={cx(styles.navigatorToggle, "icon-button")}
        aria-label="Show question navigator"
        aria-expanded={showNavigator}
        onClick={onToggleNavigator}
      >
        <List size={21} />
      </button>
    </header>
  );
}
