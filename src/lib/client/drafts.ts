import type { Draft } from "../types";

const DATABASE = "ple-practice-recovery";
function database(): Promise<IDBDatabase> {
  return new Promise((resolve, reject) => {
    const request = indexedDB.open(DATABASE, 1);
    request.onupgradeneeded = () => {
      request.result.createObjectStore("drafts");
      request.result.createObjectStore("conflicts");
    };
    request.onsuccess = () => resolve(request.result);
    request.onerror = () => reject(request.error);
  });
}
async function transaction<T>(
  store: "drafts" | "conflicts",
  mode: IDBTransactionMode,
  operation: (store: IDBObjectStore) => IDBRequest<T>,
): Promise<T> {
  const db = await database();
  return new Promise((resolve, reject) => {
    const tx = db.transaction(store, mode);
    const request = operation(tx.objectStore(store));
    tx.oncomplete = () => {
      db.close();
      resolve(request.result);
    };
    tx.onerror = tx.onabort = () => {
      db.close();
      reject(tx.error || request.error);
    };
  });
}
const key = (owner: string, id: string, editor: string) =>
  `${owner}:${id}:${editor}`;
export async function saveDraft(draft: Draft) {
  await transaction("drafts", "readwrite", (store) =>
    store.put(draft, key(draft.ownerId, draft.attemptId, draft.editorId)),
  );
}
export async function loadDraft(
  owner: string,
  id: string,
  editor: string,
): Promise<Draft | undefined> {
  return transaction("drafts", "readonly", (store) =>
    store.get(key(owner, id, editor)),
  );
}
export async function latestDraft(
  owner: string,
  id: string,
): Promise<Draft | undefined> {
  const drafts = await transaction<Draft[]>("drafts", "readonly", (store) =>
    store.getAll(),
  );
  return drafts
    .filter((d) => d.ownerId === owner && d.attemptId === id)
    .sort((a, b) => b.savedAt - a.savedAt)[0];
}
export async function preserveConflict(draft: Draft) {
  await transaction("conflicts", "readwrite", (store) =>
    store.put(
      draft,
      `${key(draft.ownerId, draft.attemptId, draft.editorId)}:${Date.now()}`,
    ),
  );
}
export async function conflictsFor(
  owner: string,
  id: string,
): Promise<Draft[]> {
  const drafts = await transaction<Draft[]>("conflicts", "readonly", (store) =>
    store.getAll(),
  );
  return drafts
    .filter((d) => d.ownerId === owner && d.attemptId === id)
    .sort((a, b) => b.savedAt - a.savedAt);
}
