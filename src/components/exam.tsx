"use client";
import { useState } from "react";
import { BookOpen } from "lucide-react";
import { useAttempt } from "@/lib/client/use-attempt";
import { MODES, SUBJECTS } from "@/lib/types";
import { Modal } from "./modal";
import { ExamHeader } from "./exam-header";
import { ExamNavigator } from "./exam-navigator";
import { ExamQuestion } from "./exam-question";
import { ExamRecovery } from "./exam-recovery";
import { ExamResults } from "./exam-results";
import type { ExamUser } from "./study-types";
import styles from "./exam.module.scss";

export function Exam({
  id,
  user,
  leave,
}: {
  id: string;
  user: ExamUser;
  leave: () => void;
}) {
  const state = useAttempt(id, user.id);
  const { view, edit, busy, conflict, authLost } = state;
  const [confirm, setConfirm] = useState(false);
  const [showNavigator, setShowNavigator] = useState(false);
  const [showRecovery, setShowRecovery] = useState(false);
  const [checkedQuestionId, setCheckedQuestionId] = useState<string>();

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
    return <ExamResults view={view} leave={leave} />;

  const attempt = view.attempt;
  const question = view.questions[attempt.position];
  const paused = attempt.status !== "running";
  const answered = Object.keys(attempt.answers).length;
  const subject = SUBJECTS.find((item) => item.id === attempt.subject)?.name;
  const navigate = (position: number) => {
    edit({ position });
    setShowNavigator(false);
  };

  return (
    <div className={styles.examShell}>
      <a className="skip-link" href="#question">
        Skip to question
      </a>
      <ExamHeader
        subject={subject}
        modeLabel={MODES[attempt.mode].label}
        questionCount={attempt.questionIds.length}
        user={user}
        saveStatus={state.saveStatus}
        showNavigator={showNavigator}
        onBack={back}
        onToggleNavigator={() => setShowNavigator((value) => !value)}
      />
      <div className={styles.examLayout}>
        <ExamQuestion
          attempt={attempt}
          question={question}
          error={state.error}
          recoveryAvailable={Boolean(state.recovery?.length)}
          conflict={conflict}
          pendingSubmission={state.pendingSubmission}
          busy={busy}
          checkedQuestionId={checkedQuestionId}
          onRetry={() => void state.sync()}
          onShowRecovery={() => setShowRecovery(true)}
          onEdit={edit}
          onSync={state.sync}
          onChecked={setCheckedQuestionId}
          onResume={state.resume}
          onTakeover={state.takeover}
          onNavigate={navigate}
          onFinish={() => setConfirm(true)}
        />
        <ExamNavigator
          attempt={attempt}
          questions={view.questions}
          paused={paused}
          busy={busy}
          conflict={conflict}
          pendingSubmission={state.pendingSubmission}
          visible={showNavigator}
          onResume={state.resume}
          onPause={state.pause}
          onNavigate={navigate}
          onSubmit={() => setConfirm(true)}
        />
      </div>
      {confirm && (
        <Modal title="Ready to finish?" close={() => setConfirm(false)}>
          <p>
            You’ve answered{" "}
            <strong>
              {answered} of {attempt.questionIds.length}
            </strong>{" "}
            questions.
          </p>
          <p>
            {attempt.questionIds.length - answered > 0
              ? `${attempt.questionIds.length - answered} unanswered questions will count as incorrect in your score.`
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
        <ExamRecovery
          draft={state.recovery[0]}
          current={view}
          canRestore={!conflict}
          close={() => setShowRecovery(false)}
          restore={(draft) => {
            const answers = { ...attempt.answers };
            for (const [questionId, answer] of Object.entries(
              draft.view.attempt.answers,
            ))
              if (
                !attempt.checked.includes(questionId) &&
                view.questions.some(
                  (item) =>
                    item.id === questionId &&
                    item.choices.some((choice) => choice.label === answer),
                )
              )
                answers[questionId] = answer;
            const remainingMs =
              attempt.remainingMs === null
                ? null
                : Math.min(
                    attempt.remainingMs,
                    draft.view.attempt.remainingMs ?? attempt.remainingMs,
                  );
            const elapsedMs =
              remainingMs === null
                ? Math.max(attempt.elapsedMs, draft.view.attempt.elapsedMs)
                : attempt.elapsedMs + attempt.remainingMs! - remainingMs;
            edit({
              answers,
              flags: [
                ...new Set([...attempt.flags, ...draft.view.attempt.flags]),
              ].filter((questionId) =>
                attempt.questionIds.includes(questionId),
              ),
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
