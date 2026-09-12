export const SUBJECTS = [
  { id: "biochemistry", name: "Biochemistry", area: "Basic sciences" },
  { id: "anatomy", name: "Anatomy & Histology", area: "Basic sciences" },
  {
    id: "microbiology",
    name: "Microbiology & Parasitology",
    area: "Basic sciences",
  },
  { id: "physiology", name: "Physiology", area: "Basic sciences" },
  { id: "legal-medicine", name: "Legal Medicine", area: "Clinical sciences" },
  { id: "pathology", name: "Pathology", area: "Basic sciences" },
  { id: "pharmacology", name: "Pharmacology", area: "Basic sciences" },
  { id: "surgery", name: "Surgery", area: "Clinical sciences" },
  {
    id: "internal-medicine",
    name: "Internal Medicine",
    area: "Clinical sciences",
  },
  {
    id: "obstetrics-gynecology",
    name: "Obstetrics & Gynecology",
    area: "Clinical sciences",
  },
  { id: "pediatrics", name: "Pediatrics", area: "Clinical sciences" },
  {
    id: "preventive-medicine",
    name: "Preventive Medicine",
    area: "Clinical sciences",
  },
] as const;
export type SubjectId = (typeof SUBJECTS)[number]["id"];
export type AnswerMode = "single" | "multiple";
export type Answer = string | string[];
export type SourceMetadata = Record<string, string | boolean>;
export type SourceRef = {
  filename: string;
  pages: number[];
  answerPages?: number[];
  kind?: "pdf" | "notion";
  locator?: string;
  title?: string;
  url?: string;
  metadata?: SourceMetadata;
};
export type VisualKind = "image" | "table" | "diagram";
export type VisualVisibility = "question" | "feedback";
export type VisualRef = {
  id: string;
  path: string;
  sha256: string;
  kind: VisualKind;
  alt: string;
  caption?: string;
  visibility: VisualVisibility;
  sourceLocator?: string;
};
export type SharedCase = {
  id: string;
  text: string;
  visuals?: VisualRef[];
};
export type Question = {
  id: string;
  subject: SubjectId;
  originalNumber: number;
  stem: string;
  choices: { label: string; text: string }[];
  /** Omitted on historical records; treat omission as `single`. */
  answerMode?: AnswerMode;
  correctChoice: string | null;
  correctChoices?: string[];
  explanation: string;
  choiceRationales?: Record<string, string>;
  sources: SourceRef[];
  status: "validated" | "needs_review";
  issues: string[];
  sharedCase?: SharedCase;
  visuals?: VisualRef[];
};
export type Mode = "practice" | "ple" | "topnotch";
export const MODES: Record<
  Mode,
  { label: string; seconds: number; description: string }
> = {
  practice: {
    label: "Practice",
    seconds: 0,
    description: "No timer. Check an answer when you’re ready.",
  },
  ple: {
    label: "PLE pace",
    seconds: 72,
    description: "120 minutes per 100 questions. Feedback at the end.",
  },
  topnotch: {
    label: "Topnotch pace",
    seconds: 54,
    description: "90 minutes per 100 questions. Feedback at the end.",
  },
};
export type Attempt = {
  id: string;
  ownerId: string;
  bankVersion: string;
  subject: SubjectId;
  mode: Mode;
  questionIds: string[];
  answers: Record<string, Answer>;
  checked: string[];
  flags: string[];
  position: number;
  remainingMs: number | null;
  elapsedMs: number;
  status: "paused" | "running" | "submitted";
  revision: number;
  editorId: string;
  createdAt: string;
  updatedAt: string;
  submittedAt?: string;
  score?: number;
};
export type Feedback = {
  /** Omitted on historical feedback objects; treat omission as `single`. */
  answerMode?: AnswerMode;
  correctChoice: string | null;
  correctChoices?: string[];
  explanation: string;
  choiceRationales?: Record<string, string>;
  sources: SourceRef[];
};
export type PublicQuestion = Pick<
  Question,
  "id" | "stem" | "choices" | "originalNumber" | "sharedCase" | "visuals"
> & { answerMode?: AnswerMode; feedback?: Feedback };
export type AttemptView = { attempt: Attempt; questions: PublicQuestion[] };
export type Draft = {
  ownerId: string;
  attemptId: string;
  baseRevision: number;
  editorId: string;
  view: AttemptView;
  dirty: boolean;
  savedAt: number;
  pendingAction?: "submit";
};
export type Edits = Pick<
  Attempt,
  "answers" | "flags" | "position" | "remainingMs" | "elapsedMs" | "status"
>;
export type SubjectStats = (typeof SUBJECTS)[number] & {
  available: number;
  sizes: number[];
  answered: number;
  correct: number;
};
