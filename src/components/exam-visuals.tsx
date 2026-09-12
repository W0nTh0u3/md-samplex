"use client";

import Image from "next/image";
import type { VisualKind, VisualRef } from "@/lib/types";
import { cx } from "./component-utils";
import styles from "./exam-visuals.module.scss";

type ExamVisualsProps = {
  visuals?: VisualRef[];
  visibility?: "question" | "feedback";
  className?: string;
};

function localPath(path: string): string | undefined {
  const normalized = path.startsWith("/") ? path : `/${path}`;
  if (
    !normalized.startsWith("/assets/") ||
    normalized.includes("..") ||
    normalized.includes("\\") ||
    normalized.includes("://")
  )
    return undefined;
  return normalized;
}

function kindLabel(kind: VisualKind) {
  return kind === "table"
    ? "Source table"
    : kind === "diagram"
      ? "Source diagram"
      : "Source image";
}

export function ExamVisuals({
  visuals,
  visibility,
  className,
}: ExamVisualsProps) {
  const items = (visuals ?? []).filter(
    (visual) => !visibility || visual.visibility === visibility,
  );
  const renderable = items
    .map((visual) => ({ visual, path: localPath(visual.path) }))
    .filter((item): item is { visual: VisualRef; path: string } =>
      Boolean(item.path),
    );

  if (!renderable.length) return null;

  return (
    <div
      className={cx(styles.visuals, className)}
      data-testid="verified-visuals"
      aria-label="Verified source visuals"
    >
      {renderable.map(({ visual, path }) => (
        <figure className={styles.visual} key={visual.id}>
          <div className={styles.frame}>
            <Image
              src={path}
              alt={visual.alt}
              width={1200}
              height={760}
              sizes="(max-width: 720px) 100vw, 760px"
            />
          </div>
          <figcaption>
            <span>{kindLabel(visual.kind)}</span>
            {visual.caption && (
              <>
                {" · "}
                {visual.caption}
              </>
            )}
          </figcaption>
        </figure>
      ))}
    </div>
  );
}
