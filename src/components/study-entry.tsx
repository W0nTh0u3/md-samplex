"use client";
import { useState } from "react";
import {
  ArrowRight,
  BookOpen,
  ChartNoAxesCombined,
  Clock3,
} from "lucide-react";
import { api, getEditor } from "@/lib/client/api";
import {
  MODES,
  type AttemptView,
  type Mode,
  type SubjectStats,
} from "@/lib/types";
import { Modal } from "./modal";
import { cx } from "./component-utils";
import styles from "./study-entry.module.scss";

export function Welcome({
  configured,
  demo,
}: {
  configured: boolean;
  demo: boolean;
}) {
  return (
    <section className={styles.welcome}>
      <div className="eyebrow">YOUR PLE STUDY SPACE</div>
      <h1>Your next step, doctor.</h1>
      <p>
        Practice with purpose. Build confidence across all 12 PLE subjects,
        learn from source explanations, and return to your progress anywhere.
      </p>
      <div className={styles.welcomeFeatures}>
        <span>
          <BookOpen size={19} />
          Subject-based practice
        </span>
        <span>
          <Clock3 size={19} />A pace that works for you
        </span>
        <span>
          <ChartNoAxesCombined size={19} />
          Progress you can see
        </span>
      </div>
      {configured ? (
        <a href="/auth/login" className="primary">
          Continue with Google <ArrowRight size={18} />
        </a>
      ) : demo ? (
        <button className="primary" onClick={() => location.reload()}>
          Open local preview <ArrowRight size={18} />
        </button>
      ) : (
        <div className="notice">
          Google sign-in is not connected yet. Follow the Supabase setup in
          README.md to open your study space.
        </div>
      )}
      <p className="small muted">
        Historical source material for exam study. Explanations retain their
        original references.
      </p>
    </section>
  );
}

export function Setup({
  subject,
  close,
  start,
}: {
  subject: SubjectStats;
  close: () => void;
  start: (id: string) => void;
}) {
  const [mode, setMode] = useState<Mode>("practice");
  const [count, setCount] = useState(subject.sizes[0] ?? 25);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");

  async function create() {
    setBusy(true);
    setError("");
    try {
      const result = await api<AttemptView>("/api/attempts", {
        subject: subject.id,
        mode,
        count,
        editorId: await getEditor(),
      });
      start(result.attempt.id);
    } catch (e) {
      setError((e as Error).message);
      setBusy(false);
    }
  }

  return (
    <Modal title="Make this session yours" close={close}>
      <p className={styles.setupSubject}>
        {subject.name}{" "}
        <span>{subject.available.toLocaleString()} available questions</span>
      </p>
      <fieldset>
        <legend>Choose your mode</legend>
        <div className={styles.modeOptions}>
          {(Object.keys(MODES) as Mode[]).map((option) => (
            <label
              key={option}
              className={cx(
                styles.modeOption,
                mode === option && styles.selected,
              )}
            >
              <input
                type="radio"
                name="mode"
                value={option}
                checked={mode === option}
                onChange={() => setMode(option)}
              />
              <span>
                <strong>{MODES[option].label}</strong>
                <small>{MODES[option].description}</small>
              </span>
            </label>
          ))}
        </div>
      </fieldset>
      <fieldset>
        <legend>Session size</legend>
        <div className={styles.sizeOptions}>
          {[25, 50, 100].map((size) => (
            <label
              key={size}
              className={cx(
                styles.sizeOption,
                count === size && styles.selected,
                !subject.sizes.includes(size) && styles.unavailable,
              )}
            >
              <input
                type="radio"
                name="size"
                value={size}
                checked={count === size}
                disabled={!subject.sizes.includes(size)}
                onChange={() => setCount(size)}
              />
              <strong>{size}</strong>
              <small>questions</small>
            </label>
          ))}
        </div>
      </fieldset>
      <div className={styles.paceNote}>
        <Clock3 size={18} />
        <p>
          {mode === "practice"
            ? "Untimed. Check and lock each answer when you’re ready."
            : `${(MODES[mode].seconds * count) / 60} minutes of active study. Your timer pauses when you leave or hide this screen.`}
        </p>
      </div>
      {error && (
        <p role="alert" className="error-text">
          {error}
        </p>
      )}
      <button
        className="primary full"
        onClick={create}
        disabled={busy || !subject.sizes.length}
      >
        {busy ? "Preparing your session…" : "Let’s begin"}
        <ArrowRight size={18} />
      </button>
    </Modal>
  );
}
