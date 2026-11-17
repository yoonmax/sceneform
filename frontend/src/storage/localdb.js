// IndexedDB for small local metadata: recently opened scenes, camera presets,
// and per-scene edit stacks for examples (which have no server). Every call
// degrades gracefully when IndexedDB is unavailable.

const DB_NAME = "sceneform";
const VERSION = 1;
let dbPromise = null;

function open() {
  if (dbPromise) return dbPromise;
  dbPromise = new Promise((resolve) => {
    try {
      const req = indexedDB.open(DB_NAME, VERSION);
      req.onupgradeneeded = () => {
        const db = req.result;
        for (const store of ["recent", "presets", "edits", "projects"]) {
          if (!db.objectStoreNames.contains(store)) db.createObjectStore(store);
        }
      };
      req.onsuccess = () => resolve(req.result);
      req.onerror = () => resolve(null);
      req.onblocked = () => resolve(null);
    } catch {
      resolve(null);
    }
  });
  return dbPromise;
}

async function tx(store, mode, fn) {
  const db = await open();
  if (!db) return undefined;
  return new Promise((resolve) => {
    try {
      const t = db.transaction(store, mode);
      const s = t.objectStore(store);
      const req = fn(s);
      t.oncomplete = () => resolve(req?.result);
      t.onerror = () => resolve(undefined);
    } catch {
      resolve(undefined);
    }
  });
}

export const localdb = {
  get: (store, key) => tx(store, "readonly", (s) => s.get(key)),
  set: (store, key, value) => tx(store, "readwrite", (s) => s.put(value, key)),
  del: (store, key) => tx(store, "readwrite", (s) => s.delete(key)),
  async all(store) {
    const db = await open();
    if (!db) return [];
    return new Promise((resolve) => {
      try {
        const out = [];
        const req = db.transaction(store, "readonly").objectStore(store).openCursor();
        req.onsuccess = () => {
          const c = req.result;
          if (c) {
            out.push({ key: c.key, value: c.value });
            c.continue();
          } else resolve(out);
        };
        req.onerror = () => resolve([]);
      } catch {
        resolve([]);
      }
    });
  },
  async clearAll() {
    for (const s of ["recent", "presets", "edits", "projects"]) await tx(s, "readwrite", (st) => st.clear());
  },
};

export async function rememberRecent(key, info) {
  await localdb.set("recent", key, { ...info, openedAt: Date.now() });
}
