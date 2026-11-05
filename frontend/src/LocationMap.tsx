import {
  useEffect,
  useRef,
  useState,
  useImperativeHandle,
  type Ref,
} from "react";
import { createMap } from "./map";
import type { Job, Report } from "./types";
export interface MapHandle {
  focus: () => void;
}
export function LocationMap({ job, ref }: { job: Job; ref: Ref<MapHandle> }) {
  const root = useRef<HTMLElement>(null),
    controller = useRef<ReturnType<typeof createMap> | null>(null);
  const [visible, setVisible] = useState(true),
    [selection, setSelection] = useState<number | null>(null);
  const revisions = job.revisions?.length
    ? job.revisions
    : job.report || job.partial
      ? [
          {
            stage: "Available result",
            report: (job.report || job.partial) as Report,
          },
        ]
      : [];
  const index =
    selection === null
      ? revisions.length - 1
      : Math.min(selection, revisions.length - 1);
  useEffect(() => {
    controller.current = createMap(root.current!);
    const observer = new ResizeObserver(() => controller.current?.resize());
    observer.observe(root.current!);
    return () => {
      observer.disconnect();
      controller.current?.dispose();
      controller.current = null;
    };
  }, []);
  useEffect(() => {
    if (visible) controller.current?.draw(revisions, index);
  }, [job, visible, index]);
  useImperativeHandle(ref, () => ({
    focus() {
      setVisible(true);
      setSelection(null);
      requestAnimationFrame(() => {
        controller.current?.draw(revisions, revisions.length - 1);
        const r = job.report || job.partial;
        if (r) controller.current?.focus(r);
        root.current?.scrollIntoView({
          behavior: matchMedia("(prefers-reduced-motion: reduce)").matches
            ? "instant"
            : "smooth",
          block: "center",
        });
      });
    },
  }));
  return (
    <section ref={root} className="map-section">
      <div className="map-heading">
        <div>
          <h3>Your location on the map</h3>
          <p>The result, its uncertainty and the places checked.</p>
        </div>
        <button
          id="map-toggle"
          className="secondary"
          aria-expanded={visible}
          aria-controls="map-panel"
          onClick={() => setVisible(!visible)}
        >
          {visible ? "Hide map" : "Show map"}
        </button>
      </div>
      <div id="map-panel" hidden={!visible}>
        <div id="map-position" hidden />
        <label htmlFor="map-revision">Investigation stage</label>
        <select
          id="map-revision"
          value={index}
          disabled={!revisions.length}
          onChange={(e) => setSelection(Number(e.target.value))}
        >
          {revisions
            .map((r, i) => (
              <option key={i} value={i}>
                {i + 1}. {r.stage}
              </option>
            ))
            .reverse()}
        </select>
        <div
          id="map"
          role="region"
          aria-label="Location result and candidate areas"
        />
        <p id="map-message" role="status" />
        <div className="map-legend">
          <span>
            <i className="legend-camera" />
            Verified camera
          </span>
          <span>
            <i className="legend-estimate" />
            Estimated point
          </span>
          <span>
            <i className="legend-tested" />
            Tested location
          </span>
        </div>
        <details className="map-evidence">
          <summary>Areas &amp; locations checked</summary>
          <div id="map-zones" />
        </details>
        <small>
          Areas reflect evidence and may change as clues are verified. Cyan
          marks a verified camera position; amber marks an estimated point or
          subject. The circle shows reported uncertainty. Map: OpenStreetMap
          (Internet required).
        </small>
      </div>
    </section>
  );
}
