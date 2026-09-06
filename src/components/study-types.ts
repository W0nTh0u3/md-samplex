import type { Attempt, Edits, SubjectStats } from "@/lib/types";

export type User = { id: string; name: string; demo: boolean };

export type Dashboard = {
  subjects: SubjectStats[];
  attempts: Attempt[];
  bankVersion: string;
};

export type Session = {
  user: User | null;
  configured: boolean;
  demo: boolean;
};

export type Tab = "overview" | "subjects" | "progress";

export type ExamUser = Pick<User, "id" | "demo">;
export type SyncAction = "save" | "check" | "submit";
export type EditAttempt = (edits: Partial<Edits>) => void;
