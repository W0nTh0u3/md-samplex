"use client";
import { useCallback, useEffect, useRef, useState } from "react";
import { tick } from "../engine";
import { normalizeAnswersForQuestions } from "../answers";
import type { AttemptView, Draft, Edits } from "../types";
import { api, getEditor, HttpError } from "./api";
import {
  conflictsFor,
  latestDraft,
  loadDraft,
  preserveConflict,
  saveDraft,
} from "./drafts";

export function useAttempt(id: string, ownerId: string) {
  const [view, setView] = useState<AttemptView>();
  const [saveStatus, setSaveStatus] = useState("Loading session");
  const [error, setError] = useState("");
  const [conflict, setConflict] = useState(false);
  const [recovery, setRecovery] = useState<Draft[]>();
  const [busy, setBusy] = useState(false);
  const [authLost, setAuthLost] = useState(false);
  const [pendingSubmission, setPendingSubmission] = useState(false);
  const current = useRef<Draft | undefined>(undefined);
  const sequence = useRef(0);
  const inFlight = useRef<Promise<void> | undefined>(undefined);
  const stopped = useRef(false);
  const lastTick = useRef(0);
  const debounce = useRef<ReturnType<typeof setTimeout> | undefined>(undefined);
  const alive = useRef(true);

  const normalizeView = useCallback((candidate: AttemptView): AttemptView => {
    return {
      ...candidate,
      attempt: {
        ...candidate.attempt,
        answers: normalizeAnswersForQuestions(
          candidate.attempt.answers,
          candidate.questions,
        ),
      },
    };
  }, []);

  const persist = useCallback(async (draft: Draft) => {
    try {
      await saveDraft(draft);
    } catch {
      setError(
        "Browser storage is unavailable. Keep this tab open until progress has synced.",
      );
    }
  }, []);

  const display = useCallback(
    (draft: Draft) => {
      const normalizedDraft = {
        ...draft,
        view: normalizeView(draft.view),
      };
      current.current = normalizedDraft;
      if (alive.current) {
        setView(normalizedDraft.view);
        setPendingSubmission(normalizedDraft.pendingAction === "submit");
      }
      void persist(normalizedDraft);
    },
    [normalizeView, persist],
  );

  const checkpoint = useCallback(() => {
    const d = current.current;
    const now = performance.now();
    const delta = lastTick.current ? now - lastTick.current : 0;
    lastTick.current = now;
    if (!d || d.view.attempt.status !== "running" || stopped.current) return;
    sequence.current++;
    display({
      ...d,
      dirty: true,
      savedAt: Date.now(),
      view: { ...d.view, attempt: tick(d.view.attempt, delta) },
    });
  }, [display]);

  const sync = useCallback(
    async (
      action: "save" | "check" | "submit" = "save",
      questionId?: string,
      keepalive = false,
    ): Promise<void> => {
      if (inFlight.current) {
        await inFlight.current;
        if (action === "save" && !keepalive) return;
      }
      const task = async () => {
        checkpoint();
        let draft = current.current;
        if (
          !draft ||
          stopped.current ||
          draft.view.attempt.status === "submitted" ||
          (!draft.dirty && action === "save")
        )
          return;
        if (
          draft.pendingAction === "submit" ||
          draft.view.attempt.remainingMs === 0
        )
          action = "submit";
        if (action === "submit") {
          draft = {
            ...draft,
            pendingAction: "submit",
            view: {
              ...draft.view,
              attempt: { ...draft.view.attempt, status: "paused" },
            },
          };
          display(draft);
        }
        const sentSequence = sequence.current;
        const { answers, flags, position, remainingMs, elapsedMs, status } =
          draft.view.attempt;
        if (action !== "save") setBusy(true);
        setSaveStatus("Syncing");
        try {
          const received = await api<AttemptView>(
            `/api/attempts/${id}`,
            {
              action,
              editorId: draft.editorId,
              revision: draft.baseRevision,
              questionId,
              edits: {
                answers,
                flags,
                position,
                remainingMs,
                elapsedMs,
                status,
              },
            },
            keepalive,
          );
          const live = current.current!;
          const newer =
            sentSequence !== sequence.current &&
            received.attempt.status !== "submitted";
          const next: Draft = {
            ...live,
            baseRevision: received.attempt.revision,
            dirty: newer,
            pendingAction: undefined,
            savedAt: Date.now(),
            view: newer
              ? {
                  ...received,
                  attempt: {
                    ...received.attempt,
                    answers: live.view.attempt.answers,
                    flags: live.view.attempt.flags,
                    position:
                      action === "check"
                        ? received.attempt.position
                        : live.view.attempt.position,
                    elapsedMs: live.view.attempt.elapsedMs,
                    remainingMs: live.view.attempt.remainingMs,
                    status: live.view.attempt.status,
                  },
                }
              : received,
          };
          display(next);
          setSaveStatus(newer ? "Saved locally" : "Synced");
          setError("");
        } catch (cause) {
          const e = cause as HttpError;
          setSaveStatus("Awaiting retry");
          if (e.status === 409) {
            stopped.current = true;
            const kept = current.current!;
            display({
              ...kept,
              view: {
                ...kept.view,
                attempt: { ...kept.view.attempt, status: "paused" },
              },
            });
            await preserveConflict(kept).catch(() => undefined);
            setRecovery([kept]);
            setConflict(true);
          }
          if ([401, 403, 404].includes(e.status)) {
            stopped.current = true;
            setAuthLost(true);
          }
          setError(
            e.message ||
              "Connection interrupted. Progress is saved on this device.",
          );
        } finally {
          setBusy(false);
        }
      };
      inFlight.current = task();
      try {
        await inFlight.current;
      } finally {
        inFlight.current = undefined;
      }
    },
    [checkpoint, display, id],
  );

  const edit = useCallback(
    (edits: Partial<Edits>) => {
      if (
        !current.current ||
        stopped.current ||
        current.current.view.attempt.status === "submitted"
      )
        return;
      checkpoint();
      sequence.current++;
      const d = current.current!;
      display({
        ...d,
        dirty: true,
        savedAt: Date.now(),
        view: { ...d.view, attempt: { ...d.view.attempt, ...edits } },
      });
      setSaveStatus("Saved locally");
      clearTimeout(debounce.current);
      debounce.current = setTimeout(() => void sync(), 500);
    },
    [checkpoint, display, sync],
  );

  const open = useCallback(
    async (takeover = false) => {
      setBusy(true);
      setError("");
      try {
        const editorId = await getEditor();
        const remote = await api<AttemptView>(`/api/attempts/${id}`);
        if (remote.attempt.ownerId !== ownerId)
          throw new HttpError("The signed-in account has changed.", 401);
        const local = await loadDraft(ownerId, id, editorId).catch(
          () => undefined,
        );
        const other = await latestDraft(ownerId, id).catch(() => undefined);
        setRecovery(await conflictsFor(ownerId, id).catch(() => []));
        if (remote.attempt.status === "submitted") {
          if (local?.dirty) await preserveConflict(local);
          display({
            ownerId,
            attemptId: id,
            editorId,
            baseRevision: remote.attempt.revision,
            view: remote,
            dirty: false,
            savedAt: Date.now(),
          });
          setConflict(false);
          stopped.current = false;
          return;
        }
        const recoverable =
          local?.dirty &&
          local.baseRevision === remote.attempt.revision &&
          remote.attempt.editorId === editorId;
        if (other?.dirty && !recoverable) {
          await preserveConflict(other);
          setRecovery([other]);
        }
        if (remote.attempt.editorId !== editorId && !takeover) {
          display({
            ownerId,
            attemptId: id,
            editorId,
            baseRevision: remote.attempt.revision,
            view: {
              ...remote,
              attempt: { ...remote.attempt, status: "paused" },
            },
            dirty: false,
            savedAt: Date.now(),
          });
          stopped.current = true;
          setConflict(true);
          return;
        }
        const claimed = await api<AttemptView>(`/api/attempts/${id}`, {
          action: "claim",
          editorId,
          revision: remote.attempt.revision,
          takeover,
        });
        const restored = recoverable
          ? {
              ...claimed,
              attempt: {
                ...local.view.attempt,
                revision: claimed.attempt.revision,
                status: "paused" as const,
              },
            }
          : claimed;
        display({
          ownerId,
          attemptId: id,
          editorId,
          baseRevision: claimed.attempt.revision,
          view: restored,
          dirty: Boolean(recoverable),
          savedAt: Date.now(),
          pendingAction: recoverable ? local.pendingAction : undefined,
        });
        stopped.current = false;
        setConflict(false);
        setSaveStatus(recoverable ? "Saved locally" : "Synced");
        lastTick.current = performance.now();
      } catch (cause) {
        const e = cause as HttpError;
        if ([401, 403, 404].includes(e.status)) setAuthLost(true);
        setError(
          e.message || "Could not load this session. Reconnect and retry.",
        );
      } finally {
        setBusy(false);
      }
    },
    [display, id, ownerId],
  );

  useEffect(() => {
    alive.current = true;
    const start = setTimeout(() => void open(), 0);
    return () => {
      alive.current = false;
      clearTimeout(start);
    };
  }, [open]);

  useEffect(() => {
    const clock = setInterval(() => {
      checkpoint();
      if (
        current.current?.view.attempt.remainingMs === 0 ||
        current.current?.pendingAction === "submit"
      )
        void sync("submit");
    }, 1000);
    const cloud = setInterval(() => void sync(), 5000);
    const pause = () => {
      if (current.current?.view.attempt.status === "running") {
        edit({ status: "paused" });
        void sync("save", undefined, true);
      }
    };
    const visibility = () => {
      if (document.hidden) pause();
    };
    const retry = () => void sync();
    const channel = new BroadcastChannel("ple-account");
    channel.onmessage = () => {
      pause();
      stopped.current = true;
      setAuthLost(true);
    };
    document.addEventListener("visibilitychange", visibility);
    window.addEventListener("pagehide", pause);
    window.addEventListener("online", retry);
    return () => {
      pause();
      clearTimeout(debounce.current);
      clearInterval(clock);
      clearInterval(cloud);
      document.removeEventListener("visibilitychange", visibility);
      window.removeEventListener("pagehide", pause);
      window.removeEventListener("online", retry);
      channel.close();
    };
  }, [checkpoint, edit, sync]);

  const pause = async () => {
    edit({ status: "paused" });
    await sync("save", undefined, true);
  };
  const resume = () => {
    lastTick.current = performance.now();
    edit({ status: "running" });
  };
  return {
    view,
    edit,
    sync,
    pause,
    resume,
    busy,
    saveStatus,
    error,
    conflict,
    recovery,
    authLost,
    pendingSubmission,
    takeover: () => open(true),
    retry: () => open(),
  };
}
