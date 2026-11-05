import type { Coordinates, Report, Source, Candidate } from "./types";
export const escapeHtml = (value: unknown) =>
  String(value ?? "").replace(
    /[&<>"']/g,
    (c) =>
      ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" })[
        c
      ] || c,
  );
const p = (text: unknown) => `<p>${escapeHtml(text)}</p>`;
const list = (values: string[] | undefined) =>
  values?.length
    ? `<ul>${values.map((v) => `<li>${escapeHtml(v)}</li>`).join("")}</ul>`
    : "";
export function safeUrl(url: string) {
  try {
    const u = new URL(url);
    return ["https:", "http:"].includes(u.protocol) ? u.href : null;
  } catch {
    return null;
  }
}
function sources(items: Source[] | undefined) {
  return (items || [])
    .map((s) => {
      const url = safeUrl(s.url);
      return url
        ? `<a class="source" href="${escapeHtml(url)}" target="_blank" rel="noopener noreferrer">${escapeHtml(s.title)} ↗<span>${escapeHtml(s.supports)}</span></a>`
        : "";
    })
    .join("");
}
const labels: Record<string, string> = {
  faible: "low",
  moyenne: "medium",
  forte: "high",
  indéterminée: "undetermined",
  pays: "country",
  région: "region",
  ville: "city",
  site: "site",
  coordonnées: "coordinates",
  correspondance: "match",
  compatible: "compatible",
  écartée: "rejected",
  "non exploitable": "unusable",
  "à vérifier": "to verify",
  écarté: "rejected",
  "accès bloqué": "access blocked",
  "indices de génération": "signs of generation",
  "provenance déclarée": "declared provenance",
};
export const label = (value: string) => labels[value] || value;
export function validCoordinates(
  coords: Coordinates | null | undefined,
): coords is Coordinates {
  return (
    !!coords &&
    Number.isFinite(coords.latitude) &&
    Number.isFinite(coords.longitude) &&
    Math.abs(coords.latitude) <= 90 &&
    Math.abs(coords.longitude) <= 180
  );
}
export function coordinateText(coords: Coordinates) {
  return `${coords.latitude.toFixed(6)}, ${coords.longitude.toFixed(6)}`;
}
export function googleMapsUrl(coords: Coordinates) {
  return (
    "https://www.google.com/maps/search/?api=1&query=" +
    encodeURIComponent(`${coords.latitude},${coords.longitude}`)
  );
}
export function verifiedCamera(report: Report | null | undefined) {
  const c = report?.best_candidate;
  return !!(
    validCoordinates(c?.coordinates) &&
    report?.localization_confirmed &&
    report?.precision === "coordonnées" &&
    ["camera", undefined].includes(c?.coordinates?.kind) &&
    c?.confidence === "forte" &&
    c?.supporting_evidence?.length &&
    c?.sources?.length &&
    !c?.contradictions?.length
  );
}
export function coordinateStatus(report: Report | null | undefined) {
  if (verifiedCamera(report)) return "Verified camera position";
  return (
    (
      {
        camera: "Estimated camera position",
        landmark: "Photographed landmark",
        area: "Approximate search area",
      } as Record<string, string>
    )[report?.best_candidate?.coordinates?.kind || "unknown"] ||
    "Candidate coordinates · unverified"
  );
}
export function coordinateCard(
  report: Report | null | undefined,
  compact = false,
) {
  const coords = report?.best_candidate?.coordinates;
  if (!validCoordinates(coords))
    return compact
      ? ""
      : '<div class="coordinate-empty">Camera coordinates not established yet.</div>';
  const text = coordinateText(coords),
    verified = verifiedCamera(report);
  const uncertainty =
    coords.accuracy_meters != null
      ? `Estimated uncertainty: ${coords.accuracy_meters.toLocaleString("en-GB")} m`
      : "Position uncertainty unknown";
  return `<div class="coordinate-card ${verified ? "verified" : "estimated"} ${compact ? "compact" : ""}"><div class="coordinate-status"><span class="position-dot"></span>${escapeHtml(coordinateStatus(report))}</div><a class="coordinate-value" href="${escapeHtml(googleMapsUrl(coords))}" target="_blank" rel="noopener noreferrer" aria-label="Open coordinates ${escapeHtml(text)} in Google Maps">${text}<span aria-hidden="true"> ↗</span></a><div class="coordinate-caption">Latitude, longitude · WGS84</div><div class="coordinate-uncertainty">${escapeHtml(uncertainty)}</div>${!compact ? p(coords.basis) : ""}<div class="coordinate-actions"><button type="button" class="secondary" data-copy-coordinates="${text}">Copy coordinates</button><button type="button" class="secondary" data-focus-coordinates>Locate on map ◎</button></div>${!verified && !compact ? "<small>The point represents the candidate or subject; the exact camera position remains unverified.</small>" : ""}</div>`;
}
function cameraPose(report: Report) {
  const coords = report.best_candidate?.coordinates,
    pose = report.camera_orientation;
  const heading = pose?.heading_degrees,
    pitch = pose?.pitch_degrees;
  const details =
    (coords?.altitude_meters != null
      ? p(
          `Altitude: ${Number(coords.altitude_meters).toFixed(1)} m above sea level`,
        ) + (coords.altitude_basis ? p(coords.altitude_basis) : "")
      : "") +
    p(
      heading != null
        ? `Heading: ${Number(heading).toFixed(1)}° from true north${pose?.uncertainty_degrees != null ? ` (±${pose?.uncertainty_degrees}°)` : " · uncertainty unknown"}`
        : "Camera heading unknown.",
    ) +
    (pitch != null
      ? p(`Pitch: ${Number(pitch).toFixed(1)}° above the horizon`)
      : "") +
    p(pose?.basis || "No verified evidence of camera orientation.");
  return coordinateCard(report) + fold("Viewing angle & altitude", details);
}
export function candidate(c: Candidate | null, best = false) {
  if (!c) return "";
  const coords = c.coordinates;
  return `<div class="${best ? "conclusion" : "candidate"}">${best ? `<span class="badge">${escapeHtml(label(c.confidence))} confidence</span>` : ""}<h${best ? "3" : "4"}>${escapeHtml(c.place)}</h${best ? "3" : "4"}>${p([c.city, c.country].filter(Boolean).join(" · "))}${validCoordinates(coords) ? `<a class="coordinates map-link" target="_blank" rel="noopener noreferrer" href="${escapeHtml(googleMapsUrl(coords))}">${coordinateText(coords)} ↗ Google Maps</a>${p(coords.basis)}${p(coords.accuracy_meters != null ? `Estimated uncertainty: ${coords.accuracy_meters.toLocaleString("en-GB")} m` : "Position uncertainty unknown.")}` : ""}${c.visual_similarity_score != null ? p(`Visual similarity: ${c.visual_similarity_score}/100 · AI estimate, not a location probability`) + p(c.similarity_basis) : ""}${list(c?.supporting_evidence)}${c?.contradictions?.length ? "<strong>Contradicting evidence</strong>" + list(c?.contradictions) : ""}${sources(c?.sources)}</div>`;
}
export function fold(title: string, content: string, open = false) {
  return content
    ? `<details class="report-section" ${open ? "open" : ""}><summary>${escapeHtml(title)}</summary>${content}</details>`
    : "";
}
export function renderReport(r: Report, partial: boolean) {
  const best = r.best_candidate;
  const heading = best
    ? `<div class="conclusion"><span class="badge">${escapeHtml(label(best.confidence))} confidence · precision ${escapeHtml(label(r.precision))}</span><h3>${escapeHtml(best.place || best.city)}</h3>${p([best.city, best.country].filter(Boolean).join(" · "))}${p(r.conclusion)}${r.narrowing ? p(r.narrowing) : ""}${cameraPose(r)}${fold("Why this location?", candidate(best))}</div>`
    : `<div class="conclusion"><h3>Location undetermined</h3>${p(r.conclusion)}${r.narrowing ? p(r.narrowing) : ""}</div>`;
  return `${partial ? '<p class="partial-label">Latest interim result · The conclusion may change.</p>' : '<p class="partial-label">Latest investigation conclusion</p>'}${heading}`;
}
export function renderEvidence(r: Report) {
  return `${fold("Clues examined · " + (r.clues || []).length, (r.clues || []).map((c) => `<div class="clue"><div class="clue-label">${escapeHtml(c.category)}<br><small>Strength ${escapeHtml(label(c.strength))}</small></div><div>${p(c.observation)}<small>${escapeHtml(c.interpretation)}</small></div></div>`).join(""))}${fold("Visual comparisons", (r.visual_comparisons || []).map((c) => `<div class="comparison"><strong>${escapeHtml(c.reference_id)} · ${escapeHtml(label(c.verdict))}</strong>${p(c.conclusion)}${list(c.matching_details)}${list(c.differences)}</div>`).join(""))}${fold("Visible text", list(r.visible_text))}${fold("Alternative locations", (r.alternatives || []).map((c) => candidate(c)).join(""))}${fold("Date, light and shadows", p(r.temporal_analysis))}${fold("Limitations and remaining checks", list(r.limitations))}${fold("Sources", sources(r.sources))}${fold("Research performed", list(r.research_performed))}${fold("Provenance and AI origin", p("AI origin: " + label(r.provenance.ai_assessment)) + list(r.provenance.ai_evidence) + p("Declared author: " + (r.provenance.author || "unknown")) + p(r.provenance.author_basis) + list(r.provenance.limitations))}`;
}
