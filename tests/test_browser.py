"""Offline browser checks for coordinate links, map focus and legacy reports."""
import copy
import shutil
from pathlib import Path
from urllib.parse import parse_qs, urlparse

import pytest
from playwright.sync_api import expect, sync_playwright

STATIC = Path(__file__).resolve().parents[1] / 'osint_picture' / 'static'
JOB_ID = 'b' * 32


def report_fixture():
    return {
        'summary': 'The facade and junction match the public panorama.',
        'conclusion': 'The camera stood across the street from the landmark.',
        'precision': 'coordonnées', 'localization_confirmed': True,
        'best_candidate': {
            'place': 'Verified viewpoint', 'city': 'Paris', 'country': 'France',
            'confidence': 'forte', 'supporting_evidence': ['Facade and junction alignment.'],
            'contradictions': [], 'sources': [{'title': 'Reference panorama', 'url': 'https://example.com/panorama', 'supports': 'Matching geometry'}],
            'coordinates': {'kind': 'camera', 'latitude': 48.8583701, 'longitude': 2.2944812,
                            'accuracy_meters': 8, 'basis': 'Two fixed landmarks aligned in the panorama.'},
        },
        'alternatives': [], 'clues': [], 'visible_text': [], 'limitations': [],
        'research_performed': [], 'sources': [], 'map_zones': [],
        'tested_places': [{'label': 'Rejected alternative', 'status': 'écarté',
                           'latitude': -33.5, 'longitude': -70.6, 'basis': 'Different geometry.'}],
        'provenance': {'ai_assessment': 'indéterminée', 'ai_evidence': [], 'author': None,
                       'author_basis': 'Unknown', 'limitations': []},
        'temporal_analysis': 'Unknown date.', 'camera_orientation': None,
    }


@pytest.fixture(scope='module')
def browser():
    with sync_playwright() as playwright:
        executable = shutil.which('google-chrome') or shutil.which('chromium')
        if not executable and not Path(playwright.chromium.executable_path).exists():
            pytest.skip('Install Chromium with playwright install chromium for browser checks.')
        instance = playwright.chromium.launch(executable_path=executable, args=['--no-sandbox'])
        yield instance
        instance.close()


def open_fixture(browser, report, width=1440):
    context = browser.new_context(viewport={'width': width, 'height': 1000}, reduced_motion='reduce')
    context.add_init_script('Object.defineProperty(navigator, "clipboard", {value:{writeText:async text => {window.copiedCoordinates=text;}}});')
    page = context.new_page()
    errors = []
    page.on('pageerror', lambda error: errors.append(str(error)))
    prior = copy.deepcopy(report)
    prior['precision'] = 'ville'
    prior['localization_confirmed'] = False
    prior['best_candidate']['coordinates'] = {'kind': 'area', 'latitude': 0, 'longitude': 0, 'accuracy_meters': 10000, 'basis': 'Earlier area.'}
    prior['best_candidate']['confidence'] = 'faible'
    job = {
        'id': JOB_ID, 'status': 'completed', 'filename': 'photo.jpg', 'stage': 'Investigation complete',
        'progress': 100, 'created_at': '2026-11-05T09:00:00Z', 'events': [], 'error': None,
        'metadata': None, 'solar': None, 'settings': {'model': 'test-model', 'reasoning_effort': 'high'},
        'report': report, 'partial': report, 'references': [], 'reference_batches': [],
        'revisions': [{'stage': 'Earlier area', 'time': '2026-11-05T09:00:01Z', 'report': prior},
                      {'stage': 'Conclusion', 'time': '2026-11-05T09:00:02Z', 'report': report}],
    }

    def route(request):
        path = urlparse(request.request.url).path
        if path == '/api/health':
            request.fulfill(json={'codex_installed': True, 'authenticated': True})
        elif path == '/api/settings':
            request.fulfill(json={'settings': job['settings'], 'models': [{'id': 'test-model', 'name': 'Test', 'efforts': ['high']}]})
        elif path == '/api/jobs':
            request.fulfill(json=[job])
        elif path == '/api/jobs/' + JOB_ID:
            request.fulfill(json=job)
        elif path.startswith('/static/'):
            target = (STATIC / path.removeprefix('/static/')).resolve()
            if STATIC in target.parents and target.is_file():
                request.fulfill(path=str(target))
            else:
                request.fulfill(status=404)
        elif path == '/' or path.startswith('/investigations/'):
            request.fulfill(path=str(STATIC / 'dist' / 'index.html'))
        else:
            # External map tiles stay offline; real Leaflet still projects all layers.
            request.fulfill(status=204)

    page.route('**/*', route)
    page.goto('https://find-place.test/#enquete=' + JOB_ID)
    expect(page.locator('#report .conclusion')).to_be_visible()
    return context, page, errors


def test_coordinate_link_copy_marker_and_focus(browser, tmp_path):
    context, page, errors = open_fixture(browser, report_fixture())
    try:
        coordinate = page.locator('#report .coordinate-value')
        expect(coordinate).to_contain_text('48.858370, 2.294481')
        url = urlparse(coordinate.get_attribute('href'))
        assert url.hostname == 'www.google.com'
        assert parse_qs(url.query) == {'api': ['1'], 'query': ['48.8583701,2.2944812']}
        expect(page.locator('#map-position')).to_contain_text('Verified camera position')
        expect(page.locator('.coordinate-tooltip')).to_contain_text('48.858370, 2.294481')
        assert page.evaluate("document.querySelector('#map')._leaflet_map.getCenter().distanceTo([48.8583701, 2.2944812])") < 2
        assert page.evaluate("document.querySelector('#map')._leaflet_map.getZoom()") >= 17  # Rejected Chilean point must not zoom out.
        page.locator('#report [data-copy-coordinates]').click()
        expect(page.locator('#report [data-copy-coordinates]')).to_have_text('Copied ✓')
        assert page.evaluate('window.copiedCoordinates') == '48.858370, 2.294481'
        page.locator('.position-pin').click()
        expect(page.locator('.leaflet-popup-content a')).to_have_attribute('href', coordinate.get_attribute('href'))
        page.locator('#map-revision').select_option('0')
        expect(page.locator('#map-position')).to_contain_text('Approximate search area')
        expect(page.locator('.coordinate-tooltip')).to_have_count(1)
        expect(page.locator('.coordinate-tooltip')).to_contain_text('0.000000, 0.000000')
        page.locator('#map-toggle').click()
        expect(page.locator('#map-panel')).to_be_hidden()
        page.locator('#report [data-focus-coordinates]').click()
        expect(page.locator('#map-panel')).to_be_visible()
        expect(page.locator('#map-toggle')).to_have_attribute('aria-expanded', 'true')
        expect(page.locator('#map-revision')).to_have_value('1')
        assert page.evaluate("document.querySelector('#map')._leaflet_map.getCenter().distanceTo([48.8583701, 2.2944812])") < 2
        assert not errors
        page.screenshot(path=str(tmp_path / 'desktop.png'), full_page=True)
    finally:
        context.close()


@pytest.mark.parametrize('mode', ['landmark', 'legacy', 'no-coordinates', 'contradiction', 'unknown'])
def test_mobile_uncertainty_legacy_and_missing_coordinates(browser, mode, tmp_path):
    report = report_fixture()
    if mode == 'landmark':
        report['best_candidate']['coordinates'].update(kind='landmark', latitude=-33.5, longitude=-70.6, accuracy_meters=None)
        report['precision'] = 'site'
    elif mode == 'unknown':
        report['best_candidate']['coordinates']['kind'] = 'unknown'
    elif mode == 'legacy':
        del report['best_candidate']['coordinates']['kind']
    elif mode == 'no-coordinates':
        report['best_candidate']['coordinates'] = None
        report['localization_confirmed'] = False
        report['precision'] = 'région'
    else:
        report['best_candidate']['contradictions'] = ['Facade does not match.']
    context, page, errors = open_fixture(browser, report, width=390)
    try:
        assert page.evaluate('document.documentElement.scrollWidth <= innerWidth')
        if mode == 'landmark':
            expect(page.locator('#report')).to_contain_text('Photographed landmark')
            expect(page.locator('#report')).to_contain_text('Position uncertainty unknown')
            expect(page.locator('#report .coordinate-value')).to_contain_text('-33.500000, -70.600000')
            expect(page.locator('.position-pin .estimated')).to_be_visible()
        elif mode == 'no-coordinates':
            expect(page.locator('#report')).to_contain_text('Camera coordinates not established yet.')
            expect(page.locator('#map-position')).to_be_hidden()
            assert page.locator('.position-pin').count() == 0
        elif mode == 'legacy':
            expect(page.locator('#report')).to_contain_text('Verified camera position')
        else:
            expect(page.locator('#report')).to_contain_text('Candidate coordinates · unverified' if mode == 'unknown' else 'Estimated camera position')
            assert page.locator('.position-pin .verified').count() == 0
        page.screenshot(path=str(tmp_path / ('mobile-' + mode + '.png')), full_page=True)
        assert not errors
    finally:
        context.close()


def test_router_history_reload_and_settings(browser):
    context, page, errors = open_fixture(browser, report_fixture())
    try:
        expect(page).to_have_url('https://find-place.test/investigations/' + JOB_ID)
        page.locator('#new').click()
        expect(page.locator('#upload-section')).to_be_visible()
        page.go_back()
        expect(page.locator('#report .conclusion')).to_be_visible()
        page.reload()
        expect(page.locator('#report .conclusion')).to_be_visible()
        page.locator('#settings-open').click()
        expect(page.locator('#settings-dialog')).to_be_visible()
        expect(page.locator('#model')).to_have_value('test-model')
        page.locator('#settings-save').click()
        expect(page.locator('#settings-dialog')).not_to_be_visible()
        assert not errors
    finally:
        context.close()
