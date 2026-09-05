export class HttpError extends Error {
  constructor(
    message: string,
    public status: number,
  ) {
    super(message);
  }
}
export async function api<T>(
  url: string,
  body?: unknown,
  keepalive = false,
): Promise<T> {
  const response = await fetch(url, {
    method: body === undefined ? "GET" : "POST",
    credentials: "include",
    cache: "no-store",
    signal: AbortSignal.timeout(15000),
    headers: body === undefined ? {} : { "Content-Type": "application/json" },
    ...(body === undefined ? {} : { body: JSON.stringify(body) }),
    keepalive,
  });
  const data = await response.json();
  if (!response.ok)
    throw new HttpError(data.error ?? "Please retry.", response.status);
  return data as T;
}

// sessionStorage holds only a tab identifier. All progress lives in IndexedDB.
// A Web Lock detects duplicated tabs that inherited the same sessionStorage.
export async function tabEditor(): Promise<string> {
  let id = sessionStorage.getItem("ple-editor") ?? crypto.randomUUID();
  if (navigator.locks) {
    const claim = (candidate: string) =>
      new Promise<boolean>((resolve) => {
        void navigator.locks.request(
          `ple-editor-${candidate}`,
          { ifAvailable: true },
          async (lock) => {
            resolve(Boolean(lock));
            if (lock)
              await new Promise<void>((release) =>
                window.addEventListener("pagehide", () => release(), {
                  once: true,
                }),
              );
          },
        );
      });
    if (!(await claim(id))) {
      id = crypto.randomUUID();
      await claim(id);
    }
  }
  sessionStorage.setItem("ple-editor", id);
  return id;
}
let editorPromise: Promise<string> | undefined;
export const getEditor = () => (editorPromise ??= tabEditor());
