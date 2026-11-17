import { Link } from "react-router-dom";
import { exampleCover } from "../api/examples.js";
import { formatBytes, formatCount, formatDuration } from "../lib/scene.js";

/** A scene presented as a numbered figure with a factual caption. */
export function Figure({ example: e, label, compact = false }) {
  return (
    <figure className="m-0">
      <Link to={`/scene/example/${e.id}`} className="group block border border-line bg-surface" aria-label={`Open ${e.title}`}>
        <img
          src={exampleCover(e)}
          alt={`Source view of ${e.title}`}
          loading="lazy"
          className={`w-full object-cover ${compact ? "aspect-[3/2]" : "aspect-[4/3]"} transition-opacity group-hover:opacity-90`}
        />
      </Link>
      <figcaption className="caption mt-2">
        <b>{label}.</b> {e.title}. {e.inputFrames ?? e.cameras} {e.sourceType === "video" ? "frames selected from video" : "photographs"};{" "}
        {e.cameras} views registered{e.reprojectionPx != null ? `, mean reprojection error ${e.reprojectionPx.toFixed(2)} px` : ""};{" "}
        {formatCount(e.points)} fused points. {!compact && <>Source: {e.author}, {e.license}. </>}
        <Link to={`/scene/example/${e.id}`} className="text-accent underline">
          Open
        </Link>
      </figcaption>
    </figure>
  );
}

/** Table 1: measured results for the precomputed scenes. */
export function ResultsTable({ examples }) {
  return (
    <div className="overflow-x-auto">
      <table className="table-paper min-w-[760px]">
        <caption className="caption mb-2 text-left caption-top">
          <b>Table 1.</b> Precomputed reconstructions produced by this pipeline (high-quality mode, Apple M4 Pro). Reprojection error is the mean over
          all sparse observations. Splat PSNR is measured on held-out views over the full frame; it is not comparable across scenes with different
          backgrounds.
        </caption>
        <thead>
          <tr>
            <th>Scene</th>
            <th>Type</th>
            <th>Input</th>
            <th className="num">Views</th>
            <th className="num">Reproj. (px)</th>
            <th className="num">Points</th>
            <th className="num">Splats</th>
            <th className="num">PSNR (dB)</th>
            <th className="num">Time</th>
            <th>Licence</th>
          </tr>
        </thead>
        <tbody>
          {examples.map((e) => (
            <tr key={e.id}>
              <td>
                <Link to={`/scene/example/${e.id}`} className="text-accent underline">
                  {e.title}
                </Link>
              </td>
              <td className="text-muted">{e.category}</td>
              <td className="text-muted">{e.sourceType === "video" ? "video" : "photos"}</td>
              <td className="num">
                {e.cameras}/{e.inputFrames ?? e.cameras}
              </td>
              <td className="num">{e.reprojectionPx != null ? e.reprojectionPx.toFixed(2) : "—"}</td>
              <td className="num">{formatCount(e.points)}</td>
              <td className="num">{e.splatCount ? formatCount(e.splatCount) : "—"}</td>
              <td className="num">{e.splatPsnr != null ? e.splatPsnr.toFixed(1) : "—"}</td>
              <td className="num">{e.seconds ? formatDuration(e.seconds) : "—"}</td>
              <td className="whitespace-nowrap text-muted">{e.license}</td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}

export default function ExampleCard({ example: e }) {
  return <Figure example={e} label={e.title} compact />;
}

export { formatBytes };
