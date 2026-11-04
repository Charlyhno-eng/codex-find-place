import asyncio
import json
import os
import signal
import time
from pathlib import Path

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
    return bool(report.localization_confirmed and report.precision in {"site", "coordonnées"}
        and candidate and candidate.confidence == "forte" and candidate.supporting_evidence
        and candidate.sources and not candidate.contradictions)


def finish_investigation(job, report, early=False):
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
        job.update("running", "Visual observation", 18)
        research = await codex_pass(job, "observation", """ÉTAPE — INVENTAIRE.
Analyse l'original normalisé, la version éclaircie (transformation technique, pas preuve de lumière naturelle), et les quatre détails.
Inventorie minutieusement les indices et textes lisibles. Construis des pistes argumentées, avec les alternatives sérieuses sur la carte.
Prépare des requêtes de photos de référence précises, y compris plusieurs lieux si l'hypothèse reste large.
Ne force pas de localisation. Le rapport est préliminaire.
""" + meta, ["preview.jpg", "enhanced.jpg", *metadata["crops"]])
        record_revision(job, "Visual observation", research)
        if location_found(research):
            finish_investigation(job, research, early=True)
            return
        job.update("running", "Researching and verifying leads", 32)
        research = await codex_pass(job, "research", """ÉTAPE — ENQUÊTE WEB.
Vérifie les hypothèses par plusieurs recherches ciblées et sources indépendantes. Cherche inscriptions, lieux, relief, architecture, signalisation et photos publiques accessibles.
Passe d'une région aux communes/sites possibles à l'aide d'indices discriminants. Cherche aussi à réfuter la meilleure piste.
Pour un GPS déclaré, vérifie le paysage et les lieux correspondants. Fournis un fuseau IANA uniquement si le candidat est localisé.
Conserve tous les indices utiles. Prépare les requêtes photographiques du prochain cycle. Une région comme « ouest de la France » est le point de départ d'une recherche ciblée, pas la fin de l'enquête.
Rapport précédent :\n""" + research.model_dump_json() + meta, ["preview.jpg", "enhanced.jpg"])
        record_revision(job, "Web investigation", research)

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
        job.update("running", "Searching reference photos · " + str(index+1), min(85, 38 + index*3))
        references, batch = await collect_references(job, research, stage)
        job.update("running", "Comparing viewpoints in Google Maps", min(86, 39 + index*3))
        street_refs, _ = await collect_street_views(job, research, stage)
        references = [*references, *street_refs]
        job.event(f"{len(references)} new reference photos available")
        manifest = [{k:v for k,v in r.items() if k != "file"} for r in references]
        job.update("running", label, min(87, 40 + index*3))
        previous_evidence = (research.best_candidate, research.clues, research.sources, research.tested_places)
        research = await codex_pass(job, stage, """ÉTAPE — AFFINAGE ET COMPARAISON VISUELLE.
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

    solar = solar_check(metadata, research.best_candidate)
    job.solar = solar
    job.update("running", "Temporal verification and conclusion", 91)
    final = await codex_pass(job, f"conclusion-{run_id}", """ÉTAPE — AUDIT ET CONCLUSION.
Vérifie les éléments décisifs et leurs sources. Conserve tous les indices, comparaisons d'images et sources utiles des étapes précédentes.
Le calcul solaire concerne le candidat précédent ; si tu changes de lieu, ne le réutilise pas comme preuve pour le nouveau.
Conclue au niveau géographique réellement défendable : pays, région, ville, site, coordonnées ou indéterminée. N'annonce jamais un point précis pour remplir le schéma.
Sélectionne une seule meilleure piste pour la carte finale, avec au plus un rectangle dans map_zones. N'enveloppe pas plusieurs alternatives dans un grand rectangle artificiel. Réduis ce rectangle au plus petit périmètre réellement étayé. Les autres pistes restent dans alternatives. Conserve un périmètre de travail faible s'il reste plausible, même sans commune confirmée. S'il est réfuté, explique son retrait. Les communes examinées restent cartographiables dans tested_places, même si aucun contour principal n'est retenu.
Cherche une dernière fois une commune testable à partir des indices les plus discriminants si city est encore null. Ne transforme pas une compatibilité générale en localisation confirmée.
Place les découvertes nouvelles et les preuves décisives au début du résumé et de la conclusion.
Explique les pistes testées, les rejets et ce qui bloque encore une localisation plus fine. Un arrêt faute de pistes ou de temps n'est pas une preuve que le lieu est trouvé.
Rapport d'enquête :\n""" + research.model_dump_json() + meta + "\nCalcul solaire :\n" + json.dumps(solar, ensure_ascii=False), ["preview.jpg"])
    finish_investigation(job, final)
