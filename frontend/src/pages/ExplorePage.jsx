import { useEffect, useState } from "react";
import { Link } from "react-router-dom";
import { Figure, ResultsTable } from "../components/ExampleCard.jsx";
import { SectionHead } from "./StudioPage.jsx";
import { listExamples } from "../api/examples.js";

export default function ExplorePage() {
  const [examples, setExamples] = useState(null);
  const [error, setError] = useState(null);
  useEffect(() => {
    listExamples().then(setExamples).catch((e) => setError(e.message));
  }, []);
  return (
    <article className="mx-auto max-w-[1180px] px-4 py-10 sm:px-6">
      <h1 className="serif text-[30px]">Reference reconstructions</h1>
      <p className="mt-2 max-w-2xl text-[14px] text-ink-2">
        Each scene was reconstructed by this pipeline from openly licensed photographs or video. Open one to inspect cameras, depth and confidence,
        compare source photographs with the reconstruction, measure, and export.
      </p>
      {error && <p className="mt-6 text-bad">{error}</p>}
      {examples ? (
        <>
          <section className="mt-8">
            <ResultsTable examples={examples} />
          </section>
          <section className="mt-12">
            <SectionHead n="" aside={<Link to="/compare?a=example:plaster-skull&b=example:plaster-skull" className="text-[12.5px] text-accent underline">compare sparse and dense</Link>}>
              Figures
            </SectionHead>
            <div className="grid gap-8 sm:grid-cols-2">
              {examples.map((e, i) => (
                <Figure key={e.id} example={e} label={`Fig. ${i + 1}`} />
              ))}
            </div>
          </section>
          <section className="mt-12 border-t border-line pt-6">
            <h2 className="label mb-3">Sources and licences</h2>
            <ul className="space-y-1.5 text-[12.5px] text-muted">
              {examples.map((e) => (
                <li key={e.id}>
                  <span className="text-ink-2">{e.title}</span> — {e.author}, {e.license}. Full attribution in each scene’s overview panel and in{" "}
                  <span className="font-mono">examples/{e.id}/ATTRIBUTION.txt</span>.
                </li>
              ))}
            </ul>
          </section>
        </>
      ) : (
        <div className="mt-8 h-48 skeleton" />
      )}
    </article>
  );
}
