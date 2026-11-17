import { useEffect, useState } from "react";
import { Link } from "react-router-dom";
import CreateFlow from "../components/CreateFlow.jsx";
import { Figure, ResultsTable } from "../components/ExampleCard.jsx";
import { listExamples } from "../api/examples.js";

export const REFERENCES = [
  ["1", "J. L. Schönberger and J.-M. Frahm. Structure-from-Motion Revisited. CVPR 2016. (COLMAP)"],
  ["2", "L. Yang et al. Depth Anything V2. NeurIPS 2024."],
  ["3", "B. Curless and M. Levoy. A Volumetric Method for Building Complex Models from Range Images. SIGGRAPH 1996."],
  ["4", "B. Kerbl, G. Kopanas, T. Leimkühler and G. Drettakis. 3D Gaussian Splatting for Real-Time Radiance Field Rendering. SIGGRAPH 2023."],
  ["5", "R. Hartley and A. Zisserman. Multiple View Geometry in Computer Vision, 2nd ed. Cambridge University Press, 2004."],
];

export function SectionHead({ n, children, id, aside }) {
  return (
    <div className="mb-4 flex items-baseline justify-between gap-4 border-b border-line pb-2">
      <h2 id={id} className="serif text-[19px]">
        <span className="mr-2 font-mono text-[13px] font-normal text-faint">{n}</span>
        {children}
      </h2>
      {aside}
    </div>
  );
}

const METHOD = [
  ["Frame selection", "Video is sampled with FFmpeg; a keyframe is taken once the view has moved enough (ORB inlier overlap and feature flow), choosing the sharpest frame in that window. Blurred frames are excluded."],
  ["Camera estimation", "SIFT features, exhaustive or sequential matching with geometric verification, incremental mapping and bundle adjustment [1]. Views are undistorted to a pinhole model."],
  ["Depth fusion", "Per-view relative depth [2] is fitted to the triangulated SfM depths (RANSAC, then Huber IRLS) with a smooth local correction. A point is kept only if neighbouring views with sufficient baseline agree with it and none observes free space in front of it."],
  ["Surface and splat", "Optional TSDF fusion with marching cubes [3]; in high-quality mode a 3D Gaussian splat [4] is trained on the posed images and evaluated on held-out views."],
];

export default function StudioPage() {
  const [examples, setExamples] = useState(null);
  const [error, setError] = useState(null);

  useEffect(() => {
    listExamples().then(setExamples).catch((e) => setError(e.message));
  }, []);

  const lead = examples?.[0];

  return (
    <article className="mx-auto max-w-[1180px] px-4 sm:px-6">
      <header className="border-b border-line pb-8 pt-10 sm:pt-14">
        <p className="font-mono text-[11px] uppercase tracking-[0.12em] text-muted">sceneform · reconstruction workbench</p>
        <h1 className="serif mt-3 max-w-[820px] text-[30px] leading-[1.15] sm:text-[38px]">
          Multi-view 3D reconstruction from ordinary photographs and video
        </h1>
        <div className="mt-6 grid gap-8 lg:grid-cols-[minmax(0,1fr)_360px]">
          <div className="max-w-[700px]">
            <p className="label mb-1.5">Abstract</p>
            <p className="serif text-[15.5px] leading-[1.65] text-ink-2">
              Given a short video or a set of overlapping photographs, sceneform recovers the camera pose of every view, estimates dense depth, and
              fuses it into a coloured point cloud in which each point is confirmed by several cameras. A surface mesh and, where a supported GPU is
              available, a trained Gaussian splat are produced alongside. Every result can be inspected against its source images: camera
              frustums, per-view depth and confidence, reprojection error, and a direct comparison of each photograph with the reconstruction
              rendered from its estimated pose. Scale is reported as relative unless a reference length is given.
            </p>
            <p className="mt-4 text-[13px] text-muted">
              Start below, open a{" "}
              <Link to={lead ? `/scene/example/${lead.id}` : "/explore"} className="text-accent underline">
                reference reconstruction
              </Link>
              , or read the <Link to="/learn" className="text-accent underline">capture protocol</Link>.
            </p>
          </div>
          {lead && <Figure example={lead} label="Fig. 1" />}
        </div>
      </header>

      <section aria-labelledby="s1" className="py-10">
        <SectionHead n="1" id="s1">New reconstruction</SectionHead>
        <CreateFlow />
      </section>

      <section aria-labelledby="s2" className="py-10">
        <SectionHead n="2" id="s2" aside={<Link to="/explore" className="text-[12.5px] text-accent underline">all scenes</Link>}>
          Reference reconstructions
        </SectionHead>
        {error && <p className="text-[13px] text-bad">{error}</p>}
        {examples ? (
          <>
            <ResultsTable examples={examples} />
            <div className="mt-8 grid gap-6 sm:grid-cols-2 lg:grid-cols-4">
              {examples.map((e, i) => (
                <Figure key={e.id} example={e} label={`Fig. 2${"abcdefgh"[i]}`} compact />
              ))}
            </div>
          </>
        ) : (
          <div className="h-40 skeleton" aria-label="Loading scenes" />
        )}
      </section>

      <section aria-labelledby="s3" className="py-10">
        <SectionHead n="3" id="s3">Method</SectionHead>
        <ol className="grid gap-x-10 gap-y-6 md:grid-cols-2">
          {METHOD.map(([t, d], i) => (
            <li key={t}>
              <h3 className="text-[14px] font-semibold">
                <span className="mr-2 font-mono text-[12px] font-normal text-faint">3.{i + 1}</span>
                {t}
              </h3>
              <p className="mt-1 text-[13.5px] leading-relaxed text-ink-2">{d}</p>
            </li>
          ))}
        </ol>
        <p className="mt-6 text-[13px] text-muted">
          Details, failure cases and the local setup are described in <Link to="/learn" className="text-accent underline">learn</Link>.
        </p>
      </section>

      <section aria-labelledby="refs" className="pb-14 pt-6">
        <h2 id="refs" className="label mb-3">References</h2>
        <ol className="space-y-1 text-[12.5px] text-muted">
          {REFERENCES.map(([n, t]) => (
            <li key={n} className="flex gap-3">
              <span className="font-mono text-faint">[{n}]</span>
              <span>{t}</span>
            </li>
          ))}
        </ol>
      </section>
    </article>
  );
}
