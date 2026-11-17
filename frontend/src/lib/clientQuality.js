// In-browser input checks. Used when no reconstruction server is connected so
// visitors still get real feedback on their own footage. Same measurements as
// the server (Laplacian variance at 640px, exposure, dHash) — but no feature
// matching, so overlap and parallax are not assessed here.

const W = 640;

export async function fileToBitmap(file) {
  try {
    return await createImageBitmap(file, { imageOrientation: "from-image" });
  } catch {
    throw new Error(`${file.name} couldn't be decoded as an image.`);
  }
}

export function grayFromSource(src, srcW, srcH) {
  const h = Math.round((srcH * W) / srcW);
  const c = new OffscreenCanvas(W, h);
  const ctx = c.getContext("2d", { willReadFrequently: true });
  ctx.drawImage(src, 0, 0, W, h);
  const { data } = ctx.getImageData(0, 0, W, h);
  const g = new Float32Array(W * h);
  for (let i = 0; i < W * h; i++) g[i] = 0.299 * data[i * 4] + 0.587 * data[i * 4 + 1] + 0.114 * data[i * 4 + 2];
  return { g, w: W, h };
}

export function frameMetrics({ g, w, h }) {
  let sum = 0,
    sum2 = 0,
    n = 0,
    mean = 0,
    dark = 0,
    bright = 0;
  for (let y = 1; y < h - 1; y++)
    for (let x = 1; x < w - 1; x++) {
      const i = y * w + x;
      const lap = g[i - 1] + g[i + 1] + g[i - w] + g[i + w] - 4 * g[i];
      sum += lap;
      sum2 += lap * lap;
      n++;
    }
  for (let i = 0; i < g.length; i++) {
    mean += g[i];
    if (g[i] <= 5) dark++;
    if (g[i] >= 250) bright++;
  }
  const lm = sum / n;
  return {
    sharpness: sum2 / n - lm * lm,
    brightness: mean / g.length,
    clippedDark: dark / g.length,
    clippedBright: bright / g.length,
    dhash: dhash({ g, w, h }),
  };
}

function dhash({ g, w, h }) {
  // 9x8 box-downsample then compare neighbours → 64 bits as two 32-bit ints.
  const cells = new Float32Array(72);
  for (let cy = 0; cy < 8; cy++)
    for (let cx = 0; cx < 9; cx++) {
      let s = 0,
        c = 0;
      const x0 = Math.floor((cx * w) / 9),
        x1 = Math.floor(((cx + 1) * w) / 9);
      const y0 = Math.floor((cy * h) / 8),
        y1 = Math.floor(((cy + 1) * h) / 8);
      for (let y = y0; y < y1; y += 2)
        for (let x = x0; x < x1; x += 2) {
          s += g[y * w + x];
          c++;
        }
      cells[cy * 9 + cx] = s / Math.max(1, c);
    }
  const bits = [];
  for (let y = 0; y < 8; y++) for (let x = 0; x < 8; x++) bits.push(cells[y * 9 + x + 1] > cells[y * 9 + x] ? 1 : 0);
  return bits;
}

const hamming = (a, b) => a.reduce((s, v, i) => s + (v !== b[i] ? 1 : 0), 0);

export function buildClientReport(metrics, width, height) {
  const n = metrics.length;
  const findings = [];
  const flags = metrics.map(() => []);
  const med = [...metrics.map((m) => m.sharpness)].sort((a, b) => a - b)[Math.floor(n / 2)] || 0;
  metrics.forEach((m, i) => {
    if (m.sharpness < 0.35 * med || m.sharpness < 15) flags[i].push("blurry");
    if (m.brightness < 45 || m.clippedDark > 0.25) flags[i].push("dark");
    if (m.brightness > 220 || m.clippedBright > 0.25) flags[i].push("overexposed");
    if (i > 0 && hamming(m.dhash, metrics[i - 1].dhash) <= 3) flags[i].push("duplicate");
  });
  const count = (f) => flags.filter((x) => x.includes(f)).length;
  const blur = count("blurry"),
    dark = count("dark"),
    bright = count("overexposed"),
    dup = count("duplicate");
  if (blur) findings.push({ code: "blur", severity: blur > n / 2 ? "problem" : "warning", message: `${blur} of ${n} images look blurry. Removing them will likely help.` });
  if (dark) findings.push({ code: "lighting-dark", severity: "warning", message: `${dark} images look underexposed.` });
  if (bright) findings.push({ code: "lighting-bright", severity: "warning", message: `${bright} images have large blown-out areas.` });
  if (dup > Math.max(2, n / 10)) findings.push({ code: "duplicates", severity: "info", message: `${dup} images are nearly identical to their neighbour.` });
  const short = Math.min(width, height);
  if (short < 480) findings.push({ code: "low-resolution", severity: "problem", message: `Images are only ${width}×${height}. At least 720p is recommended.` });
  if (n < 8) findings.push({ code: "too-few", severity: n < 3 ? "problem" : "warning", message: `Only ${n} images. 20–80 overlapping views usually work best.` });
  const comp = {
    sharpness: 1 - blur / n,
    exposure: 1 - (dark + bright) / n,
    resolution: short < 480 ? 0.2 : short < 720 ? 0.6 : 1,
    variety: 1 - Math.min(1, dup / n),
  };
  let score = (comp.sharpness * 35 + comp.exposure * 25 + comp.resolution * 20 + comp.variety * 20) * (n < 8 ? 0.8 : 1);
  if (n < 3) score = Math.min(score, 15);
  score = Math.round(score);
  if (!findings.length) findings.push({ code: "ok", severity: "info", message: "These images look sharp and well exposed." });
  return {
    score,
    grade: score >= 85 ? "great" : score >= 70 ? "good" : score >= 50 ? "fair" : "poor",
    findings,
    frameFlags: flags,
    components: comp,
    method: "heuristic (in-browser; overlap not assessed)",
  };
}

/** Sample frames from a video element at the given rate within [start, end]. */
export async function sampleVideo(video, { start = 0, end = null, fps = 2, max = 120, onFrame }) {
  const stop = Math.min(end ?? video.duration, video.duration);
  const frames = [];
  const step = 1 / fps;
  for (let t = start; t <= stop && frames.length < max; t += step) {
    await new Promise((resolve) => {
      const done = () => {
        video.removeEventListener("seeked", done);
        resolve();
      };
      video.addEventListener("seeked", done);
      video.currentTime = Math.min(t, video.duration - 0.01);
    });
    const gray = grayFromSource(video, video.videoWidth, video.videoHeight);
    const thumb = new OffscreenCanvas(160, Math.round((160 * video.videoHeight) / video.videoWidth));
    thumb.getContext("2d").drawImage(video, 0, 0, thumb.width, thumb.height);
    const blob = await thumb.convertToBlob({ type: "image/jpeg", quality: 0.7 });
    const f = { t, metrics: frameMetrics(gray), thumb: URL.createObjectURL(blob) };
    frames.push(f);
    onFrame?.(f, frames.length);
  }
  return frames;
}
