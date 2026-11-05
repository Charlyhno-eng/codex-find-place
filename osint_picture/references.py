"""Download bounded public reference photos from Wikimedia Commons and Openverse for actual vision comparison."""
import asyncio
import html
import io
import json
import re
from urllib.parse import urlparse

import httpx
from PIL import Image, ImageOps

HEADERS = {"User-Agent": "OSINT-Picture/0.2 (local photo research; Wikimedia Commons references)"}


def plain(value):
    return html.unescape(re.sub(r"<[^>]*>", "", str(value or "")))[:1000]


async def read_limited(client, url, limit, params=None):
    parsed = urlparse(url)
    if parsed.scheme != "https" or parsed.hostname not in {"commons.wikimedia.org", "upload.wikimedia.org", "api.openverse.org"} or parsed.port not in (None, 443):
        raise ValueError("Reference source not allowed")
    async with client.stream("GET", url, params=params) as response:
        response.raise_for_status()
        content = bytearray()
        async for chunk in response.aiter_bytes():
            content.extend(chunk)
            if len(content) > limit:
                raise ValueError("Reference file too large")
        return bytes(content)


async def collect_references(job, report, stage):
    previous_queries = {q for b in job.reference_batches for q in b["queries"]}
    queries = [q[:180] for q in report.reference_queries if q.strip() and q[:180] not in previous_queries][:4]
    if not queries:
        queries = [c.place[:180] for c in [report.best_candidate, *report.alternatives] if c and c.place[:180] not in previous_queries][:4]
    batch = {"stage": stage, "queries": queries, "reference_ids": [], "errors": []}
    seen = {r["page_url"] for r in job.references}
    async with httpx.AsyncClient(headers=HEADERS, timeout=httpx.Timeout(20), follow_redirects=False) as client:
        async def search(query):
            return await read_limited(client, "https://commons.wikimedia.org/w/api.php", 2*1024*1024,
                {"action":"query", "format":"json", "generator":"search", "gsrsearch":query,
                 "gsrnamespace":6, "gsrlimit":3, "prop":"imageinfo", "iiprop":"url|extmetadata", "iiurlwidth":960})
        # At most four independent searches share a single client and overlap waits.
        results = await asyncio.gather(*(search(query) for query in queries), return_exceptions=True)
        for query, raw in zip(queries, results):
            before = len(batch["reference_ids"])
            try:
                if isinstance(raw, BaseException):
                    raise raw
                data = json.loads(raw)
                if "error" in data:
                    raise ValueError(plain(data["error"].get("info", "Erreur Wikimedia")))
                for page in data.get("query", {}).get("pages", {}).values():
                    info = next(iter(page.get("imageinfo", [])), {})
                    url, page_url = info.get("thumburl"), info.get("descriptionurl")
                    if not url or not page_url or page_url in seen:
                        continue
                    try:
                        content = await read_limited(client, url, 6*1024*1024)
                        with Image.open(io.BytesIO(content)) as image:
                            if image.width * image.height > 8_000_000:
                                raise ValueError("Reference image too large")
                            normalized = ImageOps.exif_transpose(image).convert("RGB")
                            normalized.thumbnail((1200, 1200))
                            ref_id = f"ref-{len(job.references)+1:04d}"
                            filename = ref_id + ".jpg"
                            normalized.save(job.directory / filename, quality=88)
                        ext = info.get("extmetadata", {})
                        field = lambda key: plain(ext.get(key, {}).get("value", ""))
                        reference = {"id":ref_id, "file":filename, "title":plain(page.get("title")),
                            "page_url":page_url, "image_url":url, "query":query, "stage":stage,
                            "author":field("Artist"), "license":field("LicenseShortName"),
                            "license_url":field("LicenseUrl"), "description":field("ImageDescription")}
                        job.references.append(reference)
                        batch["reference_ids"].append(ref_id)
                        seen.add(page_url)
                        if len(batch["reference_ids"]) >= 8:
                            break
                    except (httpx.HTTPError, OSError, ValueError, Image.DecompressionBombError) as exc:
                        batch["errors"].append(f"Reference image unavailable: {str(exc)[:200]}")
                if len(batch["reference_ids"]) >= 8:
                    break
            except (httpx.HTTPError, OSError, ValueError) as exc:
                batch["errors"].append(f"{query} : {str(exc)[:250]}")
            if len(batch["reference_ids"]) == before:
                await openverse_fallback(client, job, query, stage, batch, seen)
            if len(batch["reference_ids"]) >= 8:
                break
    if not batch["reference_ids"] and not batch["errors"]:
        batch["errors"].append("No new reference photos found for these leads.")
    job.reference_batches.append(batch)
    job.save()
    return [r for r in job.references if r["id"] in batch["reference_ids"]], batch


async def openverse_fallback(client, job, query, stage, batch, seen):
    """Independent public image index when Commons has no usable result."""
    try:
        raw = await read_limited(client, "https://api.openverse.org/v1/images/", 2*1024*1024,
            {"q": query, "page_size": 3})
        data = json.loads(raw)
        for item in data.get("results", []):
            page_url = item.get("foreign_landing_url")
            if not page_url or page_url in seen:
                continue
            # Openverse serves a bounded thumbnail without fetching arbitrary third-party URLs.
            url = item.get("thumbnail", "")
            if urlparse(url).hostname != "api.openverse.org":
                continue
            try:
                content = await read_limited(client, url, 6*1024*1024)
                with Image.open(io.BytesIO(content)) as image:
                    if image.width * image.height > 8_000_000:
                        raise ValueError("Reference image too large")
                    normalized = ImageOps.exif_transpose(image).convert("RGB")
                    normalized.thumbnail((1200, 1200))
                    ref_id = f"ref-{len(job.references)+1:04d}"
                    filename = ref_id + ".jpg"
                    normalized.save(job.directory / filename, quality=88)
                ref = {"id": ref_id, "file": filename, "title": plain(item.get("title")),
                    "page_url": page_url, "image_url": url, "query": query, "stage": stage,
                    "author": plain(item.get("creator")),
                    "license": plain(str(item.get("license", "")) + " " + str(item.get("license_version", ""))),
                    "license_url": item.get("license_url", ""), "description": "Thumbnail indexed by Openverse; resolution may limit detailed comparisons", "provider": "Openverse"}
                job.references.append(ref)
                batch["reference_ids"].append(ref_id)
                seen.add(page_url)
                if len(batch["reference_ids"]) >= 8:
                    break
            except (httpx.HTTPError, OSError, ValueError, Image.DecompressionBombError) as exc:
                batch["errors"].append(f"Image Openverse indisponible : {str(exc)[:200]}")
    except (httpx.HTTPError, OSError, ValueError) as exc:
        batch["errors"].append(f"Openverse · {query} : {str(exc)[:250]}")
