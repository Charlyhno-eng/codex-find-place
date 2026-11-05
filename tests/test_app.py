import asyncio
import io
import json
import sys
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from PIL import Image

from osint_picture import app as module
from osint_picture.app import Job
from osint_picture.engine import CodexError, codex_pass, investigate
from osint_picture.imaging import inspect_image, solar_check
from osint_picture.models import Candidate, Coordinates, Report


def blank_report():
    return Report(summary="Image uniforme", conclusion="Localisation indéterminée.", precision="indéterminée", best_candidate=None,
        alternatives=[], clues=[], visible_text=[], provenance={"ai_assessment":"indéterminée", "ai_evidence":[], "author":None,
        "author_basis":"Aucune attribution", "limitations":["Métadonnées absentes"]}, temporal_analysis="Date absente",
        research_performed=[], limitations=["Pas d'indice géographique"], sources=[])


def image_bytes():
    buffer = io.BytesIO()
    Image.new('RGB', (200, 100), (90, 100, 150)).save(buffer, format='JPEG')
    return buffer.getvalue()


def test_extraction_preserves_original_and_creates_evidence(tmp_path):
    original = tmp_path / 'original'
    raw = image_bytes()
    original.write_bytes(raw)
    result = inspect_image(original, tmp_path)
    assert original.read_bytes() == raw
    assert (result['width'], result['height']) == (200, 100)
    assert result['gps'] is None
    assert result['c2pa_marker_present'] is False
    assert len(result['sha256']) == 64
    assert all((tmp_path / p).exists() for p in ['preview.jpg', 'enhanced.jpg', *result['crops']])


def test_gps_date_and_declared_author_extracted(tmp_path):
    original = tmp_path / 'original'
    exif = Image.Exif()
    exif[315] = 'Auteur declare'
    exif[34853] = {1:'S', 2:(33.0, 30.0, 0.0), 3:'W', 4:(70.0, 40.0, 0.0)}
    exif[34665] = {36867: '2025:06:21 20:00:00', 36881: '+02:00'}
    Image.new('RGB', (100,100)).save(original, format='JPEG', exif=exif)
    data = inspect_image(original, tmp_path)
    assert data['gps']['latitude'] == -33.5
    assert data['gps']['longitude'] == pytest.approx(-70.6666667)
    assert data['exif']['Artist'] == 'Auteur declare'
    assert data['exif']['Exif']['DateTimeOriginal'] == '2025:06:21 20:00:00'


def paris():
    return Candidate(place='Paris', country='France', city='Paris', timezone='Europe/Paris',
        coordinates=Coordinates(latitude=48.8566,longitude=2.3522,accuracy_meters=10000,basis='Zone candidate'),
        confidence='faible', supporting_evidence=[], contradictions=[], sources=[])


def test_solar_requires_date_and_uses_real_offset():
    assert solar_check({}, paris())['status'] == 'non calculable'
    data = {'tags':{'EXIF DateTimeOriginal':'2025:06:21 20:00:00','EXIF OffsetTimeOriginal':'+02:00'}}
    result = solar_check(data, paris())
    assert result['status'] == 'calculé'
    assert 0 < result['solar_elevation_degrees'] < 30
    assert result['capture_time'].endswith('+02:00')
    assert 'sunset' in result['events']
    data['tags']['EXIF DateTimeOriginal'] = 'invalid'
    assert solar_check(data, paris())['status'] == 'non calculable'


def test_research_cycles_and_solar_recomputed(monkeypatch, tmp_path):
    stages = []
    async def fake(job, stage, instruction, images):
        stages.append(stage)
        assert 'ÉTAPE' in instruction
        assert images
        return blank_report()
    monkeypatch.setattr('osint_picture.engine.codex_pass', fake)
    job = Job('a'*32, tmp_path)
    job.metadata = {'crops':[]}
    asyncio.run(investigate(job))
    assert stages == ['observation']  # observation, web verification and audit share one pass
    assert len(job.revisions) == 2
    assert len(job.reference_batches) == 0
    assert 'research_rounds' not in job.settings
    assert job.status == 'completed'
    assert job.report['best_candidate'] is None
    assert job.solar['status'] == 'non calculable'


def test_cli_invocation_and_event_parsing(monkeypatch, tmp_path):
    real_spawn = asyncio.create_subprocess_exec
    script = tmp_path / 'fake_cli.py'
    report = blank_report().model_dump_json()
    script.write_text('import sys,json\nfrom pathlib import Path\nargs=sys.argv\nassert "never" in args and "--search" in args and "read-only" in args\nassert "--json" in args\nassert args[args.index("--model")+1] == "test-model"\nassert \'model_reasoning_effort="xhigh"\' in args\nassert sys.stdin.read()\nPath(args[args.index("--output-last-message")+1]).write_text('+repr(report)+')\nprint(json.dumps({"type":"item.started","item":{"type":"web_search"}}))\n')
    async def spawn(*args, **kwargs):
        return await real_spawn(sys.executable, str(script), *args[1:], **kwargs)
    monkeypatch.setattr('osint_picture.engine.asyncio.create_subprocess_exec', spawn)
    job = Job('b'*32, tmp_path)
    job.settings = {'model':'test-model','reasoning_effort':'xhigh','research_rounds':1}
    result = asyncio.run(codex_pass(job, 'test', 'ÉTAPE test', ['preview.jpg']))
    assert result.precision == 'indéterminée'
    assert job.process is None
    assert job.events[0]['message'] == 'Checking web sources'


def test_cli_nonzero_does_not_become_success(monkeypatch, tmp_path):
    real_spawn = asyncio.create_subprocess_exec
    async def spawn(*args, **kwargs):
        return await real_spawn(sys.executable, '-c', 'import sys;sys.stdin.read();sys.exit(3)', **kwargs)
    monkeypatch.setattr('osint_picture.engine.asyncio.create_subprocess_exec', spawn)
    job = Job('c'*32, tmp_path)
    with pytest.raises(CodexError):
        asyncio.run(codex_pass(job, 'fail', 'test', []))
    assert job.process is None


@pytest.fixture
def client(monkeypatch, tmp_path):
    monkeypatch.setattr(module, 'DATA', tmp_path)
    module.jobs.clear()
    yield TestClient(module.app)
    module.jobs.clear()


def test_api_upload_persistence_export_and_untrusted_content(client, monkeypatch):
    async def fake(job):
        job.metadata = await asyncio.to_thread(inspect_image, job.directory/'original', job.directory)
        job.report = blank_report().model_dump()
        job.update('completed','Terminée',100)
    monkeypatch.setattr(module,'run_job',fake)
    with client:
        assert client.get('/').status_code == 200
        assert client.get('/static/dist/index.html').status_code == 200
        assert client.get('/investigations/' + 'b' * 32).status_code == 200
        assert client.post('/api/jobs',files={'file':('fake.jpg',b'not image','image/jpeg')}).status_code == 400
        assert client.post('/api/jobs',files={'file':('empty.jpg',b'','image/jpeg')}).status_code == 400
        assert client.post('/api/jobs',headers={'Origin':'https://evil.example'},files={'file':('a.jpg',image_bytes())}).status_code == 403
        response = client.post('/api/jobs',files={'file':('<script>.jpg',image_bytes(),'image/jpeg')})
        assert response.status_code == 202
        job_id = response.json()['id']
        # Let the background preparation finish without depending on arbitrary timing.
        client.portal.call(lambda: module.jobs[job_id].task)
        data = client.get('/api/jobs/'+job_id).json()
        assert data['status'] == 'completed'
        assert data['filename'] == '<script>.jpg'
        assert client.get('/api/jobs/'+job_id+'/preview').status_code == 200
        assert client.get('/api/jobs/'+job_id+'/export').json()['report']['precision'] == 'indéterminée'
        assert client.get('/api/jobs/'+'0'*32).status_code == 404
    with client:
        assert client.get('/api/jobs/'+job_id).json()['status'] == 'completed'


def test_cancel_running_job_and_reject_parallel_upload(client, monkeypatch):
    async def waiting_investigation(job):
        await asyncio.Event().wait()
    monkeypatch.setattr(module,'investigate',waiting_investigation)
    with client:
        response = client.post('/api/jobs',files={'file':('a.jpg',image_bytes())})
        job_id = response.json()['id']
        assert client.post('/api/jobs',files={'file':('b.jpg',image_bytes())}).status_code == 429
        response = client.post('/api/jobs/'+job_id+'/cancel')
        assert response.json()['status'] == 'cancelled'
        assert module.jobs[job_id].task.done()


def test_settings_persist_validate_and_freeze_per_job(client, monkeypatch):
    monkeypatch.setattr('osint_picture.settings.catalog', lambda: ([{'id':'test-model','name':'Test','efforts':['high','max']}], {}))
    async def fake(job):
        job.metadata = inspect_image(job.directory/'original', job.directory)
        job.report = blank_report().model_dump()
        job.update('completed','Terminée',100)
    monkeypatch.setattr(module, 'run_job', fake)
    with client:
        payload = {'model':'test-model','reasoning_effort':'max'}
        assert client.put('/api/settings', json=payload).status_code == 200
        assert client.get('/api/settings').json()['settings'] == payload
        assert client.put('/api/settings', json={**payload, 'research_rounds':100}).status_code == 200  # legacy setting ignored
        assert client.put('/api/settings', json={**payload, 'model':'--evil command'}).status_code == 422
        assert client.put('/api/settings', json={**payload, 'reasoning_effort':'low'}).status_code == 422
        job_id = client.post('/api/jobs',files={'file':('a.jpg',image_bytes())}).json()['id']
        client.portal.call(lambda: module.jobs[job_id].task)
        assert client.get('/api/jobs/'+job_id).json()['settings'] == payload
        assert client.put('/api/settings',json={**payload,'reasoning_effort':'high'}).status_code == 200
        assert client.get('/api/jobs/'+job_id).json()['settings'] == payload
    with client:
        assert client.get('/api/settings').json()['settings']['reasoning_effort'] == 'high'
        assert client.get('/api/jobs/'+job_id).json()['settings'] == payload


def test_reference_download_compared_as_images_and_deduplicated(monkeypatch, tmp_path):
    import httpx
    import osint_picture.references as refs
    requests = []
    def serve(request):
        requests.append(str(request.url))
        if request.url.host == 'commons.wikimedia.org':
            return httpx.Response(200, json={'query':{'pages':{'1':{'title':'File:Photo.jpg','imageinfo':[{
                'thumburl':'https://upload.wikimedia.org/photo.jpg','descriptionurl':'https://commons.wikimedia.org/wiki/File:Photo.jpg',
                'extmetadata':{'Artist':{'value':'<b>Auteur</b>'}, 'LicenseShortName':{'value':'CC BY-SA 4.0'}}}]}}}})
        return httpx.Response(200,content=image_bytes())
    actual_client = httpx.AsyncClient
    monkeypatch.setattr(refs.httpx, 'AsyncClient', lambda **kw: actual_client(transport=httpx.MockTransport(serve), **kw))
    report = blank_report(); report.reference_queries = ['Brest port']
    job = Job('d'*32,tmp_path)
    results, batch = asyncio.run(refs.collect_references(job, report, 'cycle1'))
    assert len(results) == 1 and batch['reference_ids'] == ['ref-0001']
    assert results[0]['author'] == 'Auteur'
    assert (tmp_path/'ref-0001.jpg').exists()
    assert len(requests) == 2
    results, batch = asyncio.run(refs.collect_references(job, report, 'cycle2'))
    assert results == [] and len(requests) == 2
    async def blocked():
        async with actual_client(transport=httpx.MockTransport(serve)) as c:
            with pytest.raises(ValueError):
                await refs.read_limited(c,'https://127.0.0.1/private',100)
    asyncio.run(blocked())


def test_resuming_old_report_retains_history_and_compares_references(monkeypatch, tmp_path):
    from osint_picture.models import MapZone
    from pydantic import ValidationError
    with pytest.raises(ValidationError):
        MapZone(label='inversée',south=50,north=40,west=-5,east=2,confidence='faible',basis='test')
    report = blank_report()
    report.map_zones = [MapZone(label='Ouest de la France',south=45,north=50,west=-5,east=0,confidence='faible',basis='Architecture')]
    report.reference_queries = ['Brest port']
    job = Job('e'*32,tmp_path); job.metadata = {'crops':[]}; job.partial = report.model_dump()
    job.settings = {'model':'test-model','reasoning_effort':'high','research_rounds':2}
    calls = []
    async def collect(job, report, stage):
        return [{'id':'ref-0001','file':'ref-0001.jpg','page_url':'https://commons.wikimedia.org/'}], {}
    async def fake(job, stage, instruction, images):
        calls.append((stage, images))
        return report
    monkeypatch.setattr('osint_picture.engine.collect_references',collect)
    monkeypatch.setattr('osint_picture.engine.codex_pass',fake)
    asyncio.run(investigate(job,resume=True))
    assert len(calls) == 1 and 'observation' not in [c[0] for c in calls]
    assert 'ref-0001.jpg' in calls[0][1]
    assert len(job.revisions) == 2
    assert job.report['map_zones'][0]['label'] == 'Ouest de la France'
    assert job.status == 'completed'


def test_deepen_api_old_report_and_reference_routes(client, monkeypatch):
    seen = []
    async def fake(job, resume=False):
        seen.append(resume)
        if not resume:
            job.metadata = inspect_image(job.directory/'original', job.directory)
        job.revisions.append({'stage':'Saved','report':blank_report().model_dump()})
        job.report = blank_report().model_dump()
        job.update('completed','Terminée',100)
    monkeypatch.setattr(module,'run_job',fake)
    with client:
        job_id = client.post('/api/jobs',files={'file':('a.jpg',image_bytes())}).json()['id']
        client.portal.call(lambda: module.jobs[job_id].task)
        assert client.post('/api/jobs/'+job_id+'/deepen').status_code == 202
        client.portal.call(lambda: module.jobs[job_id].task)
        assert seen == [False,True]
        assert len(client.get('/api/jobs/'+job_id).json()['revisions']) == 2
        assert client.get('/api/jobs/'+job_id+'/references/ref-0001').status_code == 404
        job = module.jobs[job_id]
        (job.directory/'ref-0001.jpg').write_bytes(image_bytes())
        job.references = [{'id':'ref-0001','file':'ref-0001.jpg'}]
        assert client.get('/api/jobs/'+job_id+'/references/ref-0001').status_code == 200
        job.references[0]['file'] = '../original'
        assert client.get('/api/jobs/'+job_id+'/references/ref-0001').status_code == 404


def test_openverse_fallback_when_commons_unavailable(monkeypatch,tmp_path):
    import httpx
    import osint_picture.references as refs
    requests = []
    def serve(request):
        requests.append(request.url.host)
        if request.url.host == 'commons.wikimedia.org':
            return httpx.Response(403)
        if request.url.path == '/v1/images/':
            return httpx.Response(200,json={'results':[{'title':'Brest port','thumbnail':'https://api.openverse.org/v1/images/id/thumb/',
                'foreign_landing_url':'https://www.flickr.com/photos/test/123','creator':'Photo Author','license':'by-sa','license_version':'4.0',
                'license_url':'https://creativecommons.org/licenses/by-sa/4.0/'}]})
        return httpx.Response(200,content=image_bytes())
    actual_client = httpx.AsyncClient
    monkeypatch.setattr(refs.httpx,'AsyncClient',lambda **kw: actual_client(transport=httpx.MockTransport(serve),**kw))
    job=Job('f'*32,tmp_path); report=blank_report();report.reference_queries=['Brest port']
    result,batch=asyncio.run(refs.collect_references(job,report,'cycle1'))
    assert len(result)==1 and result[0]['provider']=='Openverse'
    assert batch['errors'] and batch['reference_ids']==['ref-0001']
    assert requests==['commons.wikimedia.org','api.openverse.org','api.openverse.org']
    assert result[0]['license']=='by-sa 4.0'


def test_delete_cancels_and_removes_persisted_job(client, monkeypatch):
    async def waiting(job):
        await asyncio.Event().wait()
    monkeypatch.setattr(module, 'investigate', waiting)
    with client:
        job_id = client.post('/api/jobs', files={'file':('a.jpg', image_bytes())}).json()['id']
        job = module.jobs[job_id]
        assert client.delete('/api/jobs/' + job_id).json() == {'deleted': job_id}
        assert job.task.done()
        assert not job.directory.exists()
        assert client.get('/api/jobs/' + job_id).status_code == 404
        assert client.get('/api/jobs/' + job_id + '/export').status_code == 404
        assert not client.get('/api/jobs').json()
    with client:
        assert not client.get('/api/jobs').json()


def test_settings_reject_model_outside_codex_catalog(client, monkeypatch):
    monkeypatch.setattr('osint_picture.settings.catalog', lambda: ([{'id':'real', 'name':'Real', 'efforts':['high']}], {}))
    with client:
        assert client.put('/api/settings', json={'model':'invented','reasoning_effort':'high','research_rounds':3}).status_code == 422
        assert client.get('/api/settings').json()['efforts'] == []


def test_tested_places_survive_final_audit_with_latest_verdict(monkeypatch, tmp_path):
    from osint_picture.models import TestedPlace
    place = TestedPlace(label='La Marne', status='à vérifier', latitude=46.994, longitude=-1.741,
                        basis='Cible de comparaison, pas localisation de la photo', sources=[], street_view_heading=90)
    research = blank_report(); research.tested_places = [place]
    final = blank_report()
    job = Job('e'*32, tmp_path); job.metadata = {'crops':[]}; job.partial = research.model_dump()
    job.settings = {'model':'test-model','reasoning_effort':'high','research_rounds':1}
    calls = []
    async def collect(job, report, stage):
        return [], {}
    async def street(job, report, stage):
        assert report.tested_places[0].label == 'La Marne'
        return [{'id':'ref-0001','file':'ref-0001.jpg','page_url':'https://www.google.com/maps/'}], {}
    async def fake(job, stage, instruction, images):
        calls.append((stage, images))
        return final if stage.startswith('conclusion') else research
    monkeypatch.setattr('osint_picture.engine.collect_references', collect)
    monkeypatch.setattr('osint_picture.engine.collect_street_views', street)
    monkeypatch.setattr('osint_picture.engine.codex_pass', fake)
    asyncio.run(investigate(job, resume=True))
    assert 'ref-0001.jpg' in calls[0][1]
    assert job.report['tested_places'][0]['label'] == 'La Marne'
    from osint_picture.engine import record_revision
    updated = blank_report(); updated.tested_places = [place.model_copy(update={'status':'accès bloqué'})]
    record_revision(job, 'Nouvelle vérification', updated)
    assert len(job.partial['tested_places']) == 1
    assert job.partial['tested_places'][0]['status'] == 'accès bloqué'


def test_tested_place_coordinates_must_be_paired():
    from osint_picture.models import TestedPlace
    from pydantic import ValidationError
    with pytest.raises(ValidationError):
        TestedPlace(label='Ville', status='à vérifier', latitude=48, longitude=None,
                    basis='test', sources=[], street_view_heading=None)


@pytest.mark.parametrize('mode', ['capture', 'blocked', 'no_coverage', 'consent_refused', 'concurrent'])
def test_street_view_browser_capture_and_blockage(monkeypatch, tmp_path, mode):
    blocked = mode in {'blocked', 'no_coverage'}
    from osint_picture.models import TestedPlace
    from osint_picture.streetview import collect_street_views
    import playwright.async_api as api
    class Locator:
        def __init__(self, page=None, unavailable=False): self.page, self.unavailable = page, unavailable
        async def click(self):
            if mode == 'blocked': raise TimeoutError("Consentement non franchi")
            self.page.url = self.page.requested
        first = property(lambda self: self)
        async def wait_for(self, **kw): pass
        async def count(self): return int(self.unavailable)
    class Page:
        url = ''
        async def goto(self, url, **kw):
            self.requested = url
            self.url = 'https://consent.google.com/' if mode in {'blocked', 'consent_refused'} else url
        def locator(self, *args): return Locator()
        def get_by_role(self, *args, **kw): return Locator(self)
        def get_by_text(self, *args, **kw): return Locator(self, mode == "no_coverage")
        async def wait_for_url(self, *args, **kw): pass
        async def wait_for_timeout(self, *args): pass
        async def screenshot(self, path, **kw):
            # Another collector completes while Playwright is taking its screenshot.
            if mode == 'concurrent':
                (tmp_path / 'ref-0001.jpg').write_bytes(b'commons-photo')
                job.references.append({'id':'ref-0001', 'file':'ref-0001.jpg', 'image_url':'https://example.com/photo'})
            Path(path).write_bytes(image_bytes())
    class Browser:
        closed = False
        async def new_context(self, **kw): return self
        async def new_page(self): return Page()
        async def close(self): self.closed = True
    browser = Browser()
    class Playwright:
        chromium = property(lambda self: self)
        async def launch(self, **kw): return browser
        async def __aenter__(self): return self
        async def __aexit__(self, *args): pass
    monkeypatch.setattr(api, 'async_playwright', Playwright)
    report = blank_report()
    report.tested_places = [TestedPlace(label='Rue de test', status='à vérifier', latitude=48, longitude=2,
                                       basis='Point de vue à comparer', sources=[], street_view_heading=90)]
    job = Job('b'*32, tmp_path)
    refs, batch = asyncio.run(collect_street_views(job, report, 'cycle'))
    assert browser.closed
    assert bool(refs) is not blocked
    assert bool(batch['errors']) is blocked
    if not blocked:
        assert (tmp_path / refs[0]['file']).exists()
        assert 'heading=90.0' in refs[0]['image_url']
        assert refs[0]['provider'] == 'Google Maps / Street View'
        if mode == 'concurrent':
            assert refs[0]['id'] == 'ref-0002'
            assert (tmp_path / 'ref-0001.jpg').read_bytes() == b'commons-photo'
            assert len({r['id'] for r in job.references}) == len(job.references)
    refs, batch = asyncio.run(collect_street_views(job, report, 'cycle2'))
    assert refs == [] and batch is None


@pytest.mark.parametrize('found_at', ['observation', 'deep'])
def test_confirmed_location_stops_without_extra_search(monkeypatch, tmp_path, found_at):
    from osint_picture.models import CameraOrientation, Source
    found = blank_report()
    found.localization_confirmed = True
    found.precision = 'coordonnées'
    found.best_candidate = paris()
    found.best_candidate.confidence = 'forte'
    found.best_candidate.coordinates.accuracy_meters = 5
    found.best_candidate.supporting_evidence = ['Distinctive facade and road geometry match.']
    found.best_candidate.sources = [Source(title='Verified panorama', url='https://example.com/panorama', supports='Matching facade')]
    found.camera_orientation = CameraOrientation(heading_degrees=90, pitch_degrees=-3,
        uncertainty_degrees=5, basis='Aligned verified landmarks.')
    calls, downloads = [], []
    async def fake(job, stage, instruction, images):
        calls.append(stage)
        if stage == found_at or (found_at == 'deep' and stage.startswith('deep-')):
            return found
        pending = blank_report()
        pending.continue_research = True
        pending.next_check = 'Compare the proposed site with a panorama'
        return pending
    async def collect(job, report, stage):
        downloads.append(stage)
        return [], {}
    monkeypatch.setattr('osint_picture.engine.codex_pass', fake)
    monkeypatch.setattr('osint_picture.engine.collect_references', collect)
    monkeypatch.setattr('osint_picture.engine.collect_street_views', collect)
    job = Job('a'*32, tmp_path)
    job.metadata = {'crops': []}
    job.settings = {'model': 'test-model', 'reasoning_effort': 'high', 'research_rounds': 6}
    asyncio.run(investigate(job))
    assert len(calls) == {'observation': 1, 'deep': 2}[found_at]
    assert len(downloads) == (2 if found_at == 'deep' else 0)
    assert job.status == 'completed'
    assert job.report['camera_orientation']['heading_degrees'] == 90
    assert job.stage == 'Location identified · search stopped'
    assert not any(stage.startswith('conclusion') for stage in calls)
    assert (tmp_path/'solar.json').exists()


def test_early_stop_requires_verified_site_not_city_or_unresolved_evidence():
    from osint_picture.engine import location_found
    from osint_picture.models import Source
    report = blank_report()
    report.localization_confirmed = True
    report.precision = 'ville'
    report.best_candidate = paris()
    report.best_candidate.confidence = 'forte'
    report.best_candidate.supporting_evidence = ['A landmark.']
    report.best_candidate.sources = [Source(title='Source', url='https://example.com', supports='Landmark')]
    assert not location_found(report)
    report.precision = 'site'
    assert location_found(report)
    report.best_candidate.contradictions = ['Facade geometry differs.']
    assert not location_found(report)
    report.best_candidate.contradictions = []
    report.best_candidate.sources = []
    assert not location_found(report)


def test_camera_angles_validate_and_legacy_reports_remain_readable():
    from osint_picture.models import CameraOrientation
    from pydantic import ValidationError
    assert blank_report().camera_orientation is None
    assert blank_report().localization_confirmed is False
    assert CameraOrientation(heading_degrees=0, pitch_degrees=-90).heading_degrees == 0
    for value in (-1, 360):
        with pytest.raises(ValidationError):
            CameraOrientation(heading_degrees=value)
    with pytest.raises(ValidationError):
        CameraOrientation(pitch_degrees=91)


def test_autonomous_research_continues_beyond_legacy_rounds(monkeypatch, tmp_path):
    calls = []
    async def fake(job, stage, instruction, images):
        calls.append(stage)
        report = blank_report()
        report.clues = []
        from osint_picture.models import Clue
        report.clues.append(Clue(category='landmark', observation=stage,
                                 interpretation='New discriminating evidence', strength='forte'))
        report.continue_research = len(calls) < 5
        report.next_check = 'Compare the next named street panorama'
        return report
    async def collect(*args): return [], {}
    monkeypatch.setattr('osint_picture.engine.codex_pass', fake)
    monkeypatch.setattr('osint_picture.engine.collect_references', collect)
    monkeypatch.setattr('osint_picture.engine.collect_street_views', collect)
    job = Job('a'*32, tmp_path)
    job.metadata = {'crops': []}
    job.settings = {'model':'test-model','reasoning_effort':'high','research_rounds':1}
    asyncio.run(investigate(job))
    assert len([s for s in calls if s.startswith('deep-')]) == 4
    assert job.status == 'completed'


def test_autonomous_research_stops_on_stagnation(monkeypatch, tmp_path):
    calls = []
    async def fake(job, stage, instruction, images):
        calls.append(stage)
        report = blank_report()
        report.continue_research = True
        report.next_check = 'Try the same panorama again'
        return report
    async def collect(*args): return [], {}
    monkeypatch.setattr('osint_picture.engine.codex_pass', fake)
    monkeypatch.setattr('osint_picture.engine.collect_references', collect)
    monkeypatch.setattr('osint_picture.engine.collect_street_views', collect)
    job = Job('b'*32, tmp_path); job.metadata = {'crops': []}
    job.settings = {'model':'test-model','reasoning_effort':'high'}
    asyncio.run(investigate(job))
    assert len([s for s in calls if s.startswith('deep-')]) == 2
    assert calls[-1].startswith('deep-')
    assert not any(s.startswith('conclusion-') for s in calls)


def test_similarity_cannot_confirm_without_evidence_and_altitude_is_optional():
    from osint_picture.engine import location_found
    from pydantic import ValidationError
    report = blank_report()
    report.best_candidate = paris()
    report.best_candidate.visual_similarity_score = 100
    assert not location_found(report)
    assert report.best_candidate.coordinates.altitude_meters is None
    coordinates = report.best_candidate.coordinates.model_copy(update={
        'altitude_meters': 35, 'altitude_basis': 'Surveyed elevation above mean sea level'})
    assert Coordinates.model_validate_json(coordinates.model_dump_json()).altitude_meters == 35
    with pytest.raises(ValidationError):
        type(report.best_candidate).model_validate({**report.best_candidate.model_dump(), 'visual_similarity_score':101})


def test_confirmed_site_keeps_one_actionable_camera_check(monkeypatch, tmp_path):
    from osint_picture.models import Source
    from osint_picture.engine import location_found
    site = blank_report()
    site.localization_confirmed = True
    site.precision = 'site'
    site.best_candidate = paris()
    site.best_candidate.confidence = 'forte'
    site.best_candidate.supporting_evidence = ['Landmark facade verified.']
    site.best_candidate.sources = [Source(title='Landmark', url='https://example.com', supports='Facade')]
    site.best_candidate.coordinates.kind = 'landmark'
    site.continue_research = True
    site.next_check = 'Align the facade and road junction in the nominated panorama.'
    assert not location_found(site)
    camera = site.model_copy(deep=True)
    camera.precision = 'coordonnées'
    camera.best_candidate.coordinates.kind = 'camera'
    camera.best_candidate.coordinates.accuracy_meters = 8
    assert location_found(camera)
    unknown = camera.model_copy(deep=True)
    unknown.best_candidate.coordinates.kind = 'unknown'
    assert not location_found(unknown)
    calls = []
    async def analyze(job, stage, instruction, images):
        calls.append(stage)
        return site if stage == 'observation' else camera
    started = set()
    async def photos(job, report, stage):
        started.add('photos')
        while 'street' not in started:
            await asyncio.sleep(0)
        return [], {}
    async def street(job, report, stage):
        started.add('street')
        while 'photos' not in started:
            await asyncio.sleep(0)
        return [], {}
    monkeypatch.setattr('osint_picture.engine.codex_pass', analyze)
    monkeypatch.setattr('osint_picture.engine.collect_references', photos)
    monkeypatch.setattr('osint_picture.engine.collect_street_views', street)
    job = Job('c'*32, tmp_path)
    job.metadata = {'crops': []}
    job.settings = {'model':'test-model', 'reasoning_effort':'high'}
    asyncio.run(asyncio.wait_for(investigate(job), 2))
    assert len(calls) == 2
    assert job.report['best_candidate']['coordinates']['kind'] == 'camera'
    assert job.report['best_candidate']['coordinates']['accuracy_meters'] == 8
    assert not job.report['continue_research']


def test_coordinate_roles_and_nonfinite_values():
    from pydantic import ValidationError
    assert Coordinates(latitude=0, longitude=0, accuracy_meters=None, basis='Unknown').kind == 'unknown'
    for field in ('latitude', 'longitude', 'accuracy_meters'):
        for value in (float('nan'), float('inf')):
            payload = dict(latitude=0, longitude=0, accuracy_meters=None, basis='test')
            payload[field] = value
            with pytest.raises(ValidationError):
                Coordinates(**payload)


def test_reference_searches_overlap_without_duplicate_images(monkeypatch, tmp_path):
    import httpx
    import osint_picture.references as refs
    started = set()
    async def serve(request):
        if request.url.host == 'commons.wikimedia.org':
            started.add(request.url.params['gsrsearch'])
            while len(started) < 2:
                await asyncio.sleep(0)
            return httpx.Response(200, json={'query': {'pages': {'1': {'title':'File:Shared.jpg', 'imageinfo':[{
                'thumburl':'https://upload.wikimedia.org/shared.jpg', 'descriptionurl':'https://commons.wikimedia.org/wiki/File:Shared.jpg'}]}}}})
        if request.url.host == 'api.openverse.org':
            return httpx.Response(200, json={'results': []})
        return httpx.Response(200, content=image_bytes())
    actual_client = httpx.AsyncClient
    monkeypatch.setattr(refs.httpx, 'AsyncClient', lambda **kw: actual_client(transport=httpx.MockTransport(serve), **kw))
    job = Job('f'*32, tmp_path)
    report = blank_report()
    report.reference_queries = ['Rare facade', 'Named junction']
    result, batch = asyncio.run(asyncio.wait_for(refs.collect_references(job, report, 'cycle'), 2))
    assert len(started) == 2
    assert len(result) == 1
    assert len(job.references) == 1
    assert batch['reference_ids'] == ['ref-0001']
