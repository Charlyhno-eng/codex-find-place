"""Capture a few model-nominated public viewpoints in a fresh browser context.

Screenshots are evidence to inspect, never an automatic match or proof of coverage.
No accounts, consent bypass, or uploads of the investigated image.
"""
import shutil
import re
from urllib.parse import urlencode, urlparse


def street_url(latitude, longitude, heading=0):
    return 'https://www.google.com/maps/@?' + urlencode({
        'api': 1, 'map_action': 'pano', 'viewpoint': f'{latitude},{longitude}',
        'heading': heading, 'pitch': 0, 'fov': 80, 'hl': 'fr',
    })


async def collect_street_views(job, report, stage):
    seen = {r.get('image_url') for r in job.references}
    places = [p for p in report.tested_places if p.latitude is not None and p.status != 'écarté']
    targets = []
    for place in places:
        # Examine both sides when direction is unknown; never invent a road trajectory.
        for heading in ([place.street_view_heading] if place.street_view_heading is not None else [0, 180]):
            url = street_url(place.latitude, place.longitude, heading)
            if url not in seen:
                targets.append((place, url))
    targets = targets[:4]
    if not targets:
        return [], None
    batch = {'stage': stage + '-streetview', 'queries': [p.label for p, _ in targets],
             'reference_ids': [], 'errors': []}
    refs = []
    try:
        from playwright.async_api import async_playwright
        async with async_playwright() as playwright:
            executable = shutil.which('google-chrome') or shutil.which('chromium') or shutil.which('chromium-browser')
            browser = await playwright.chromium.launch(executable_path=executable, args=['--no-sandbox'])
            try:
                context = await browser.new_context(viewport={'width': 1280, 'height': 850}, locale='fr-FR')
                page = await context.new_page()
                for place, url in targets:
                    try:
                        await page.goto(url, wait_until='domcontentloaded', timeout=30000)
                        if urlparse(page.url).hostname == 'consent.google.com':
                            # Use Google's ordinary refusal choice; never accept tracking or bypass a challenge.
                            reject = page.get_by_role('button', name=re.compile(r'^(Tout refuser|Reject all)$'))
                            await reject.wait_for(state='visible', timeout=8000)
                            await reject.click()
                            await page.wait_for_url(re.compile(r'https://(www|maps)\.google\.com/maps/.*'), timeout=15000)
                        if urlparse(page.url).hostname not in {'www.google.com', 'maps.google.com'} or '/sorry' in page.url:
                            raise ValueError('Google access blocked or consent required')
                        # A JavaScript shell, consent page, or map without canvas is not a usable capture.
                        await page.locator('canvas').first.wait_for(state='visible', timeout=12000)
                        if await page.get_by_role('button', name='Tout accepter', exact=True).count():
                            raise ValueError('Google consent required; no view compared')
                        # Let imagery settle; the model must still check that a panorama is visible.
                        await page.wait_for_timeout(2000)
                        unavailable = page.get_by_text(re.compile(r'Aucune image Street View disponible|No Street View imagery|Street View is not available', re.I))
                        if await unavailable.count():
                            raise ValueError('Google reports no Street View imagery at this point; the fallback view is not evidence for this location')
                        ref_id = f'ref-{len(job.references)+1:04d}'
                        filename = ref_id + '.jpg'
                        await page.screenshot(path=str(job.directory / filename), type='jpeg', quality=85)
                        ref = {'id': ref_id, 'file': filename, 'title': 'Street view to verify · ' + place.label,
                               'page_url': page.url, 'image_url': url, 'query': place.label, 'stage': stage,
                               'author': 'Attribution visible dans la capture', 'license': 'Google Maps · consultation',
                               'license_url': 'https://www.google.com/intl/fr/help/terms_maps/',
                               'description': 'Unvalidated browser capture. Verify panorama, actual position, coverage and date. A no Street View imagery message makes this capture unusable for the requested point, even if a fallback view appears.',
                               'provider': 'Google Maps / Street View'}
                        job.references.append(ref)
                        refs.append(ref)
                        batch['reference_ids'].append(ref_id)
                    except Exception as exc:
                        # Playwright has its own TimeoutError hierarchy. Cancellation remains propagated.
                        batch['errors'].append(f'{place.label} : {str(exc)[:220]}')
            finally:
                await browser.close()
    except Exception as exc:
        batch['errors'].append('Navigateur Street View indisponible : ' + str(exc)[:220])
    job.reference_batches.append(batch)
    job.save()
    return refs, batch
