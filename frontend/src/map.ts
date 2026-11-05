import * as L from "leaflet";
import type { Report, Revision, Coordinates } from "./types";
import {
  validCoordinates,
  verifiedCamera,
  coordinateCard,
  coordinateStatus,
  coordinateText,
  googleMapsUrl,
  escapeHtml,
  label,
} from "./report";
type Shape = (
  | { type: "bounds"; south: number; west: number; north: number; east: number }
  | ({ type: "circle" } & Coordinates)
) & { label: string; confidence: string; basis: string; historical?: boolean };
export function createMap(root: HTMLElement) {
  const $ = (id: string) => root.querySelector<HTMLElement>("#" + id)!;
  let map: L.Map | null = null,
    mapLayers: L.FeatureGroup | null = null,
    mapKey = "";
  let mapRevisions: Revision[] = [];
  function mapShapes(report: Report | undefined, latest = false): Shape[] {
    const zones = latest
      ? (report?.map_zones || []).slice(0, 1)
      : report?.map_zones;
    if (zones?.length)
      return zones.map((z) => ({ ...z, type: "bounds" as const }));
    return (latest ? [] : report?.alternatives || [])
      .filter((c) => c?.coordinates && (c.coordinates.accuracy_meters ?? 0) > 0)
      .map((c) => ({
        type: "circle",
        label: c.place,
        confidence: c.confidence,
        ...c.coordinates!,
      }));
  }
  function drawMap(index: number) {
    if (!map) {
      map = L.map($("map"), { worldCopyJump: true }).setView([20, 0], 2);
      ($("map") as HTMLElement & { _leaflet_map: L.Map })._leaflet_map = map;
      L.tileLayer("https://tile.openstreetmap.org/{z}/{x}/{y}.png", {
        maxZoom: 19,
        attribution:
          '&copy; <a href="https://www.openstreetmap.org/copyright" target="_blank" rel="noopener noreferrer">OpenStreetMap</a> contributors',
      }).addTo(map);
      mapLayers = L.featureGroup().addTo(map);
    }
    if (!mapLayers) return;
    map.invalidateSize();
    const report = mapRevisions[index]?.report;
    let shapes = mapShapes(report, index === mapRevisions.length - 1);
    let inherited = false;
    if (
      !shapes.length &&
      !validCoordinates(report?.best_candidate?.coordinates)
    ) {
      for (let previous = index - 1; previous >= 0; previous--) {
        const earlier = mapShapes(mapRevisions[previous].report, true);
        if (earlier.length) {
          shapes = earlier.map((s) => ({
            ...s,
            historical: true,
            basis:
              "Previous working area · not revalidated at this stage. " +
              s.basis,
          }));
          inherited = true;
          break;
        }
      }
    }
    const registry = new Map<
      string,
      NonNullable<Report["tested_places"]>[number]
    >();
    for (const revision of mapRevisions.slice(0, index + 1)) {
      for (const place of revision.report.tested_places || [])
        registry.set(place.label.toLocaleLowerCase("en"), place);
    }
    const places = [...registry.values()];
    const key = JSON.stringify([
      index,
      shapes,
      places,
      report?.best_candidate,
      report?.camera_orientation,
      report?.localization_confirmed,
      report?.precision,
    ]);
    if (key === mapKey) return;
    mapKey = key;
    mapLayers.clearLayers();
    $("map-zones").replaceChildren();
    $("map-position").innerHTML = coordinateCard(report, true);
    $("map-position").hidden = !validCoordinates(
      report?.best_candidate?.coordinates,
    );
    const located = places.filter(
      (p) => Number.isFinite(p.latitude) && Number.isFinite(p.longitude),
    );
    $("map-message").textContent =
      `${shapes.length} area(s) · ${located.length} tested location(s) mapped. ` +
      (inherited
        ? "Dashed outline: previous working area, retained for context and not revalidated. "
        : "") +
      (report?.narrowing || "Markers show tested locations.");
    const addItem = (
      label: string,
      basis: string,
      lat?: number | null,
      lon?: number | null,
      status?: string,
    ) => {
      const item = document.createElement("div");
      item.className = "zone-item";
      const strong = document.createElement("strong");
      strong.textContent = label;
      const reason = document.createElement("p");
      reason.textContent = basis;
      const link = document.createElement("a");
      link.href =
        "https://www.google.com/maps/search/?api=1&query=" +
        encodeURIComponent(Number.isFinite(lat) ? `${lat},${lon}` : label);
      link.textContent = "Explore on Google Maps ↗";
      link.target = "_blank";
      link.rel = "noopener noreferrer";
      item.append(strong, reason, link);
      if (Number.isFinite(lat)) {
        const street = document.createElement("a");
        street.href =
          "https://www.google.com/maps/@?api=1&map_action=pano&viewpoint=" +
          encodeURIComponent(`${lat},${lon}`);
        street.textContent = "Street View ↗";
        street.target = "_blank";
        street.rel = "noopener noreferrer";
        street.className = "street-link";
        item.append(street);
      }
      if (status) item.dataset.status = status;
      $("map-zones").append(item);
      return item;
    };
    shapes.forEach((shape, i) => {
      const color = shape.historical ? "#a4a6b8" : "#9cafff";
      const options = {
        color,
        weight: 2,
        fillOpacity: 0.1,
        dashArray: shape.historical ? "6 6" : undefined,
      };
      const layer =
        shape.type === "bounds"
          ? L.rectangle(
              [
                [shape.south, shape.west],
                [shape.north, shape.east],
              ],
              options,
            )
          : L.circle([shape.latitude, shape.longitude], {
              ...options,
              radius: shape.accuracy_meters ?? 0,
            });
      const item = addItem(
        `${i + 1}. ${shape.label}${shape.historical ? " · previous area" : " · leading area"} · confidence ${label(shape.confidence)}`,
        shape.basis,
      );
      layer.bindPopup(item.cloneNode(true) as HTMLElement);
      layer.addTo(mapLayers!);
    });
    for (const place of places) {
      const color =
        (
          {
            "à vérifier": "#466fa0",
            compatible: "#416b45",
            écarté: "#a14d49",
            "accès bloqué": "#a66b39",
          } as Record<string, string>
        )[place.status] || "#466fa0";
      const item = addItem(
        `${place.label} · ${label(place.status)}`,
        place.basis +
          (place.latitude == null
            ? " · Coordinates unverified; no marker."
            : ""),
        place.latitude,
        place.longitude,
        place.status,
      );
      if (Number.isFinite(place.latitude) && Number.isFinite(place.longitude)) {
        L.circleMarker([place.latitude!, place.longitude!], {
          radius: 7,
          color,
          weight: 2,
          fillOpacity: 0.7,
        })
          .bindPopup(item.cloneNode(true) as HTMLElement)
          .addTo(mapLayers);
      }
    }
    const camera = report?.best_candidate?.coordinates;
    const hasPoint = validCoordinates(camera),
      verified = verifiedCamera(report);
    let primaryBounds = null;
    if (hasPoint) {
      const lat = camera.latitude,
        lon = camera.longitude;
      const color = verified ? "#7ce8ec" : "#ffc57c";
      const marker = L.marker([lat, lon], {
        icon: L.divIcon({
          className: "position-pin",
          html: `<span class="${verified ? "verified" : "estimated"}"></span>`,
          iconSize: [24, 24],
          iconAnchor: [12, 12],
        }),
        zIndexOffset: 1000,
      });
      const popup = document.createElement("div");
      popup.innerHTML = `<strong>${escapeHtml(coordinateStatus(report))}</strong><br><a href="${escapeHtml(googleMapsUrl(camera))}" target="_blank" rel="noopener noreferrer">${coordinateText(camera)} ↗ Google Maps</a><br>${escapeHtml(camera.accuracy_meters != null ? `Estimated uncertainty: ${camera.accuracy_meters} m` : "Position uncertainty unknown")}`;
      marker
        .bindPopup(popup)
        .bindTooltip(coordinateText(camera), {
          permanent: true,
          direction: "top",
          offset: [0, -12],
          className: "coordinate-tooltip",
        })
        .addTo(mapLayers);
      if (camera.accuracy_meters != null && camera.accuracy_meters > 0) {
        const circle = L.circle([lat, lon], {
          radius: camera.accuracy_meters,
          color,
          weight: 1.5,
          fillOpacity: 0.1,
          dashArray: verified ? undefined : "5 5",
        }).addTo(mapLayers);
        primaryBounds = circle.getBounds();
      } else
        primaryBounds = L.latLngBounds([
          [lat, lon],
          [lat, lon],
        ]);
      const heading = report?.camera_orientation?.heading_degrees;
      if (verified && heading != null) {
        const radians = (heading * Math.PI) / 180,
          distance = 100 / 6371000;
        const phi = (lat * Math.PI) / 180,
          lambda = (lon * Math.PI) / 180;
        const endPhi = Math.asin(
          Math.sin(phi) * Math.cos(distance) +
            Math.cos(phi) * Math.sin(distance) * Math.cos(radians),
        );
        const endLambda =
          lambda +
          Math.atan2(
            Math.sin(radians) * Math.sin(distance) * Math.cos(phi),
            Math.cos(distance) - Math.sin(phi) * Math.sin(endPhi),
          );
        L.polyline(
          [
            [lat, lon],
            [
              (endPhi * 180) / Math.PI,
              (((endLambda * 180) / Math.PI + 540) % 360) - 180,
            ],
          ],
          { color, weight: 4 },
        )
          .bindTooltip(`Viewing direction: ${heading}° from true north`)
          .addTo(mapLayers);
      }
      $("map-message").textContent =
        `${coordinateStatus(report)} · ${located.length} tested location(s). ` +
        (report?.narrowing ||
          "Click the coordinates to open this point in Google Maps.");
    }
    if (!shapes.length && !places.length && !hasPoint)
      $("map-message").textContent =
        "Reading the scene. The map will update as location evidence becomes available.";
    // Keep the result visible even when rejected locations are far away.
    if (primaryBounds)
      map.fitBounds(primaryBounds.pad(0.25), {
        maxZoom: verified ? 19 : 15,
        animate: false,
      });
    else if (mapLayers.getLayers().length)
      map.fitBounds(mapLayers.getBounds().pad(0.2), {
        maxZoom: 17,
        animate: false,
      });
    else map.setView([20, 0], 2, { animate: false });
  }
  return {
    draw(revisions: Revision[], index: number) {
      mapRevisions = revisions;
      drawMap(index);
    },
    resize() {
      map?.invalidateSize();
    },
    dispose() {
      map?.remove();
    },
    focus(report: Report) {
      const c = report.best_candidate?.coordinates;
      if (validCoordinates(c))
        map?.setView(
          [c.latitude, c.longitude],
          verifiedCamera(report) ? 19 : 15,
        );
    },
  };
}
