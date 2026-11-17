import { useRef, useState } from "react";
import { Icon } from "./ui.jsx";

const VIDEO = ["video/mp4", "video/quicktime", "video/webm"];
const IMAGE = ["image/jpeg", "image/png", "image/webp"];

export function classify(files) {
  const list = [...files];
  const videos = list.filter((f) => VIDEO.includes(f.type) || /\.(mp4|mov|webm)$/i.test(f.name));
  const images = list.filter((f) => IMAGE.includes(f.type) || /\.(jpe?g|png|webp)$/i.test(f.name));
  const other = list.filter((f) => !videos.includes(f) && !images.includes(f));
  if (videos.length && images.length) return { error: "Please choose either one video or a set of photos, not both." };
  if (videos.length > 1) return { error: "Please choose a single video." };
  if (videos.length) return { kind: "video", files: videos, skipped: other };
  if (images.length) return { kind: "photos", files: images, skipped: other };
  if (other.some((f) => /\.hei[cf]$/i.test(f.name)))
    return { error: "HEIC photos aren't supported yet. Export them as JPEG (on iPhone: Settings → Camera → Formats → Most Compatible)." };
  return { error: "Those files aren't supported. Use MP4, MOV or WebM video, or JPEG, PNG or WebP photos." };
}

export default function UploadDropzone({ onFiles, compact = false }) {
  const video = useRef();
  const photos = useRef();
  const [over, setOver] = useState(false);
  const [error, setError] = useState(null);

  const take = (files) => {
    if (!files?.length) return;
    const r = classify(files);
    if (r.error) return setError(r.error);
    setError(null);
    onFiles(r);
  };

  return (
    <div
      onDragOver={(e) => {
        e.preventDefault();
        setOver(true);
      }}
      onDragLeave={() => setOver(false)}
      onDrop={(e) => {
        e.preventDefault();
        setOver(false);
        take(e.dataTransfer.files);
      }}
      className={`relative grid gap-6 border border-dashed transition-colors md:grid-cols-[minmax(0,1fr)_340px] ${over ? "border-accent bg-accent-soft" : "border-line-strong bg-raised"} ${compact ? "p-5" : "p-6"}`}
    >
      <div>
        <div className="text-[15px] font-semibold">Create a 3D scene</div>
        <p className="mt-1 max-w-md text-[13.5px] text-ink-2">
          Drop a video or a set of photographs anywhere in this box, or choose a file. Nothing is processed until you review the input and start
          the reconstruction.
        </p>
        <div className="mt-5 flex flex-wrap gap-2">
          <button className="btn btn-primary btn-lg" onClick={() => video.current.click()}>
            <Icon name="video" size={16} /> Upload video
          </button>
          <button className="btn btn-secondary btn-lg" onClick={() => photos.current.click()}>
            <Icon name="photos" size={16} /> Upload photos
          </button>
        </div>
        {error && (
          <p role="alert" className="mt-3 flex items-center gap-1.5 text-[13px] text-bad">
            <Icon name="alert" size={15} /> {error}
          </p>
        )}
      </div>
      <dl className="grid grid-cols-[64px_1fr] content-start gap-x-3 gap-y-1.5 border-line text-[12px] md:border-l md:pl-6">
        <dt className="label pt-px">Video</dt>
        <dd className="font-mono text-ink-2">MP4 · MOV · WebM, ≤ 5 min</dd>
        <dt className="label pt-px">Photos</dt>
        <dd className="font-mono text-ink-2">JPEG · PNG · WebP, 3–300</dd>
        <dt className="label pt-px">Advised</dt>
        <dd className="text-ink-2">20–80 sharp, overlapping views taken while moving around the subject</dd>
        <dt className="label pt-px">Avoid</dt>
        <dd className="text-ink-2">motion blur, moving people, mirrors and glass</dd>
      </dl>
      <input ref={video} type="file" accept={VIDEO.join(",")} className="hidden" onChange={(e) => take(e.target.files)} aria-label="Choose a video" />
      <input ref={photos} type="file" accept={IMAGE.join(",")} multiple className="hidden" onChange={(e) => take(e.target.files)} aria-label="Choose photos" />
    </div>
  );
}
