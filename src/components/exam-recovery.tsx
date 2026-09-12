"use client";
import { Download } from "lucide-react";
import { answerSetsEqual, formatAnswer } from "@/lib/answers";
import type { AttemptView, Draft } from "@/lib/types";
import { Modal } from "./modal";
import styles from "./exam-recovery.module.scss";

type ExamRecoveryProps = {
  draft: Draft;
  current: AttemptView;
  canRestore: boolean;
  close: () => void;
  restore: (draft: Draft) => void;
};

export function ExamRecovery({
  draft,
  current,
  canRestore,
  close,
  restore,
}: ExamRecoveryProps) {
  const differenceIds = [
    ...new Set([
      ...Object.keys(current.attempt.answers),
      ...Object.keys(draft.view.attempt.answers),
    ]),
  ].filter(
    (id) =>
      !answerSetsEqual(
        current.attempt.answers[id],
        draft.view.attempt.answers[id],
      ),
  );

  function download() {
    const blob = new Blob([JSON.stringify(draft, null, 2)], {
      type: "application/json",
    });
    const url = URL.createObjectURL(blob);
    const link = document.createElement("a");
    link.href = url;
    link.download = `ple-draft-${draft.attemptId}.json`;
    link.click();
    URL.revokeObjectURL(url);
  }

  return (
    <Modal title="Your saved local draft" close={close}>
      <p>
        Saved {new Date(draft.savedAt).toLocaleString()}. There are{" "}
        {differenceIds.length} answers that differ from the current session.
      </p>
      <p>
        Restoring copies its editable answers and review flags into this
        session. Checked answers stay locked, and remaining time can only
        decrease.
      </p>
      <div className={styles.recoveryDifferences}>
        {differenceIds.map((id) => (
          <p key={id}>
            Question {current.attempt.questionIds.indexOf(id) + 1}: current{" "}
            {formatAnswer(current.attempt.answers[id])} → draft{" "}
            {formatAnswer(draft.view.attempt.answers[id])}
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
