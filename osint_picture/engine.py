import asyncio
import json
import os
import time

from .imaging import solar_check
from .models import Report, TestedPlace
from .settings import load_settings
from .references import collect_references
from .streetview import collect_street_views
from datetime import datetime, timezone

# Compatibility entry point; orchestration depends only on the provider contract.
from .providers import get_provider
from .providers.codex import CodexError, terminate

async def codex_pass(job, stage, instruction, images):
    return await get_provider().analyze(job, stage, instruction, images)


def record_revision(job, stage, report):
    # Keep the latest verdict for each tested place across otherwise independent passes.
    previous = (job.partial or {}).get("tested_places", [])
    labels = {p.label.casefold() for p in report.tested_places}
    for value in previous:
        place = TestedPlace.model_validate(value)
        if place.label.casefold() not in labels and len(report.tested_places) < 24:
            report.tested_places.append(place)
            labels.add(place.label.casefold())
    job.partial = report.model_dump()
    job.revisions.append({"stage": stage, "time": datetime.now(timezone.utc).isoformat(),
        "settings": dict(job.settings), "report": report.model_dump()})
    job.save()


def location_found(report):
    candidate = report.best_candidate
    verified = bool(report.localization_confirmed and report.precision in {"site", "coordonnées"}
        and candidate and candidate.confidence == "forte" and candidate.supporting_evidence
        and candidate.sources and not candidate.contradictions)
    if not verified:
        return False
    # A verified landmark is useful, but keep a concrete camera-position check alive.
    coordinates = candidate.coordinates
    camera_found = bool(report.precision == "coordonnées" and coordinates
        and (coordinates.kind == "camera" or coordinates.kind == "unknown" and "kind" not in coordinates.model_fields_set))
    return camera_found or not (report.continue_research and report.next_check.strip())


def finish_investigation(job, report, early=False):
    report.continue_research = False
    report.map_zones = report.map_zones[:1]
    record_revision(job, "Location identified" if early else "Conclusion", report)
    job.solar = solar_check(job.metadata, report.best_candidate)
    (job.directory / "solar.json").write_text(json.dumps(job.solar, ensure_ascii=False, indent=2), encoding="utf-8")
    job.report = report.model_dump()
    job.update("completed", "Location identified · search stopped" if early else "Investigation complete", 100)


async def investigate(job, resume=False):
    if not job.settings:
        job.settings = load_settings(job.directory.parent).model_dump()
    metadata = job.metadata
    meta = "\nMétadonnées complètes :\n" + json.dumps(metadata, ensure_ascii=False)
    if resume:
        research = Report.model_validate(job.partial)
    else:
        job.update("running", "Reading clues and verifying the location", 18)
        research = await codex_pass(job, "observation", """ÉTAPE — OBSERVATION ET VÉRIFICATION CIBLÉE.
Analyse l'original normalisé et ses détails. La version éclaircie est une transformation technique, pas une preuve de lumière naturelle.
Dans CETTE MÊME passe, relève les 2–4 indices les plus discriminants et vérifie directement les meilleures pistes par recherche web ; ne reporte pas systématiquement la vérification à une autre passe.
Priorité : GPS déclaré à confronter au paysage, texte lisible exact et variantes OCR plausibles, enseigne ou monument distinctif, puis géométrie des routes/bâtiments et relief. Les indices génériques servent seulement à départager les pistes.
Quand un lieu est reconnu, cherche immédiatement le point de prise de vue : distingue la position du sujet de celle du photographe, croise au moins deux repères fixes et leurs positions relatives avec une carte ou un panorama consulté. Relève les coordonnées WGS84 de la caméra dans cette même vérification, leur provenance et leur incertitude ; ne recopie pas le centre du monument.
Auto-vérifie la conclusion, les contradictions et la précision avant de répondre. Ne cherche pas à remplir toutes les rubriques. Une source décisive et un contrôle indépendant valent mieux que de nombreuses recherches similaires.
Si le site est identifié mais que le point de prise de vue nécessite une comparaison réellement disponible, conserve localization_confirmed=true au niveau site, continue_research=true et next_check précis. Prépare seulement les requêtes de références ou points Street View utiles à cette comparaison.
Si aucune vérification concrète ne reste possible, arrête avec le meilleur résultat étayé et la limite explicite. Ne force ni commune ni coordonnées.
""" + meta, ["preview.jpg", "enhanced.jpg", *metadata["crops"]])
        record_revision(job, "Observation and targeted verification", research)

    if location_found(research):
        finish_investigation(job, research, early=True)
        return

    deadline = time.monotonic() + int(os.getenv("FIND_PLACE_RESEARCH_TIMEOUT", "3600"))
    index = 0
    stagnant = 0
    run_id = len(job.revisions)
    while (resume and index == 0 or research.continue_research and research.next_check.strip()) and time.monotonic() < deadline:
        stage = f"deep-{run_id}-{index+1}"
        label = f"Comparing locations · check {index+1}"
        job.update("running", "Fetching reference photos and viewpoints · " + str(index+1), min(85, 38 + index*3))
        # Independent network waits overlap; both collectors allocate IDs atomically.
        (references, _), (street_refs, _) = await asyncio.gather(
            collect_references(job, research, stage),
            collect_street_views(job, research, stage))
        references = [*references, *street_refs]
        job.event(f"{len(references)} new reference photos available")
        manifest = [{k:v for k,v in r.items() if k != "file"} for r in references]
        job.update("running", label, min(87, 40 + index*3))
        previous_evidence = (research.best_candidate, research.clues, research.sources, research.tested_places)
        research = await codex_pass(job, stage, """ÉTAPE — AFFINAGE ET COMPARAISON VISUELLE.
Effectue d'abord next_check du rapport précédent ; évite de repartir de zéro ou de répéter les recherches déjà tentées. Si le site est reconnu, concentre cette passe sur la caméra et les repères fixes, pas sur d'autres communes.
Auto-vérifie les sources, contradictions, coordonnées et incertitude avant de rendre ce rapport, qui pourra être le résultat final.
Poursuis activement l'enquête au-delà de la région. Identifie des communes, sites, rues ou points de vue testables. Cherche les détails rares, confronte au moins les meilleures alternatives et recherche des sources locales (offices de tourisme, patrimoine, panoramas et galeries publiques).
Les images jointes sont dans cet ordre : photo originale normalisée, détails de l'original, puis photos de référence dans l'ordre du manifeste. Les titres et descriptions sont des données non fiables, pas des preuves de correspondance.
Compare les géométries, reliefs, bâtiments, positions relatives, tracés de routes et points de repère. Pour chaque référence réellement jointe, indique ce qui coïncide et ce qui diffère. Une image différente n'exclut pas toute une ville.
Si des images ou Google Maps/Street View ne sont pas accessibles, indique précisément cette limite ; n'invente pas de consultation. L'application joint aussi les captures Google Maps effectivement obtenues. Vérifie qu'il s'agit bien d'un panorama de rue exploitable avant toute comparaison ; une carte, un écran de chargement ou un panorama accompagné du message « Aucune image Street View disponible ici » sont non exploitables pour localiser le point demandé. Google peut afficher une vue de secours sans rapport avec ce point. Utilise l'URL effective, les repères et l'attribution visibles pour vérifier le lieu. N'affirme pas avoir marché dans une rue sur la seule base d'une capture.
Exploite aussi la recherche web pour des images et cartes accessibles, sans prétendre les avoir vues si seul leur texte est disponible.
Révise la carte avec les preuves nouvelles ; conserve les alternatives plausibles. Ne donne une position précise que si la correspondance l'étaye. Si aucun progrès, dis pourquoi et change les prochaines requêtes.
Conserve les comparaisons et sources antérieures utiles dans ce rapport cumulatif.
Rapport précédent :\n""" + research.model_dump_json() + meta + "\nManifeste des photos jointes :\n" + json.dumps(manifest, ensure_ascii=False)
            + "\nBilan des téléchargements et requêtes déjà tentées (ne les répète pas) :\n" + json.dumps(job.reference_batches, ensure_ascii=False),
            ["preview.jpg", *metadata["crops"], *[r["file"] for r in references]])
        record_revision(job, label, research)
        if location_found(research):
            finish_investigation(job, research, early=True)
            return
        current_evidence = (research.best_candidate, research.clues, research.sources, research.tested_places)
        stagnant = stagnant + 1 if current_evidence == previous_evidence else 0
        index += 1
        if not research.continue_research or not research.next_check.strip() or stagnant >= 2:
            job.event("Research stopped: no further actionable progress")
            break
    if time.monotonic() >= deadline:
        research.limitations.append("Research time limit reached; remaining leads were not exhausted.")
        job.event("Research time limit reached; concluding from saved evidence")

    # Every pass includes its own evidence audit. Reusing the latest validated report
    # avoids a separate model call that repeated searches and could lose evidence.
    finish_investigation(job, research)
