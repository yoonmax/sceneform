let cache = null;

export async function listExamples() {
  if (cache) return cache;
  const res = await fetch(`${import.meta.env.BASE_URL}examples/index.json`);
  if (!res.ok) throw new Error("Couldn't load the example list.");
  cache = (await res.json()).examples;
  return cache;
}

export const exampleCover = (e) => `${import.meta.env.BASE_URL}${e.cover}`;
