const $ = id => document.getElementById(id);
let selectedFile = null, objectUrl = null, activeId = null, timer = null, rendered = '', pollingGeneration = 0;
const terminal = status => ['completed', 'error', 'cancelled'].includes(status);
const escapeHtml = value => String(value ?? '').replace(/[&<>"']/g, c => ({'&':'&amp;', '<':'&lt;', '>':'&gt;', '"':'&quot;', "'":'&#39;'}[c]));
const p = text => `<p>${escapeHtml(text)}</p>`;
const list = values => values?.length ? `<ul>${values.map(v => `<li>${escapeHtml(v)}</li>`).join('')}</ul>` : '';
function safeUrl(url) { try { const u = new URL(url); return ['https:', 'http:'].includes(u.protocol) ? u.href : null; } catch { return null; } }
function sources(items) { return (items || []).map(s => { const url = safeUrl(s.url); return url ? `<a class="source" href="${escapeHtml(url)}" target="_blank" rel="noopener noreferrer">${escapeHtml(s.title)} ↗<span>${escapeHtml(s.supports)}</span></a>` : ''; }).join(''); }
const labels = {'faible':'low','moyenne':'medium','forte':'high','indéterminée':'undetermined','pays':'country','région':'region','ville':'city','site':'site','coordonnées':'coordinates','correspondance':'match','compatible':'compatible','écartée':'rejected','non exploitable':'unusable','à vérifier':'to verify','écarté':'rejected','accès bloqué':'access blocked','indices de génération':'signs of generation','provenance déclarée':'declared provenance'};
const label = value => labels[value] || value;
function cameraPose(report) {
  const coords = report.best_candidate?.coordinates;
  const pose = report.camera_orientation;
  const heading = pose?.heading_degrees;
  const pitch = pose?.pitch_degrees;
  return `<div class="camera-pose"><h4>Location coordinates &amp; viewing angle</h4>${coords ? `<div class="coordinates">X (longitude): ${Number(coords.longitude).toFixed(6)}° · Y (latitude): ${Number(coords.latitude).toFixed(6)}°<br>Z (altitude): ${coords.altitude_meters != null ? `${Number(coords.altitude_meters).toFixed(1)} m above sea level` : 'unknown'}${coords.altitude_basis ? p(coords.altitude_basis) : ''}</div>${p(coords.accuracy_meters != null ? `Estimated accuracy: ${coords.accuracy_meters.toLocaleString('en-GB')} m` : 'Position accuracy unknown')}${p(report.precision === 'coordonnées' ? 'Camera position supported by the reported evidence.' : 'Candidate area coordinates; the exact camera position is not established.')}${p(coords.basis)}` : p('Exact camera coordinates not established.')}${p(heading != null ? `Heading: ${Number(heading).toFixed(1)}° from true north${pose.uncertainty_degrees != null ? ` (±${pose.uncertainty_degrees}°)` : ' · uncertainty unknown'}` : 'Camera heading unknown.')}${pitch != null ? p(`Pitch: ${Number(pitch).toFixed(1)}° above the horizon`) : ''}${p(pose?.basis || 'No verified evidence of camera orientation.')}</div>`;
}
function candidate(c, best = false) {
  if (!c) return '';
  const coords = c.coordinates;
  return `<div class="${best ? 'conclusion' : 'candidate'}">${best ? `<span class="badge">${escapeHtml(label(c.confidence))} confidence</span>` : ''}<h${best ? '3' : '4'}>${escapeHtml(c.place)}</h${best ? '3' : '4'}>${p([c.city, c.country].filter(Boolean).join(' · '))}${coords ? `<div class="coordinates">X (longitude): ${Number(coords.longitude).toFixed(6)}° · Y (latitude): ${Number(coords.latitude).toFixed(6)}°<br>Z (altitude): ${coords.altitude_meters != null ? `${Number(coords.altitude_meters).toFixed(1)} m above sea level` : 'unknown'}${coords.altitude_basis ? p(coords.altitude_basis) : ''}</div>${p(coords.basis)}${coords.accuracy_meters !== null ? p(`Estimated area accuracy: ${coords.accuracy_meters.toLocaleString('en-GB')} m`) : p('Metric accuracy unknown.')}<a class="map-link" target="_blank" rel="noopener noreferrer" href="https://www.openstreetmap.org/?mlat=${Number(coords.latitude)}&mlon=${Number(coords.longitude)}#map=14/${Number(coords.latitude)}/${Number(coords.longitude)}">View candidate on map ↗</a>` : ''}${c.visual_similarity_score != null ? p(`Visual similarity: ${c.visual_similarity_score}/100 · AI estimate, not a location probability`) + p(c.similarity_basis) : ''}${list(c.supporting_evidence)}${c.contradictions?.length ? '<strong>Contradicting evidence</strong>' + list(c.contradictions) : ''}${sources(c.sources)}</div>`;
}
function fold(title, content, open = false) { return content ? `<details class="report-section" ${open ? 'open' : ''}><summary>${escapeHtml(title)}</summary>${content}</details>` : ''; }
function renderReport(r, partial) {
  const best = r.best_candidate;
  const heading = best ? `<div class="conclusion"><span class="badge">${escapeHtml(label(best.confidence))} confidence · precision ${escapeHtml(label(r.precision))}</span><h3>${escapeHtml(best.city || best.place)}</h3>${p(best.country || '')}${p(r.conclusion)}${r.narrowing ? p(r.narrowing) : ""}${cameraPose(r)}${fold('Why this location?', candidate(best))}</div>` : `<div class="conclusion"><h3>Location undetermined</h3>${p(r.conclusion)}${r.narrowing ? p(r.narrowing) : ""}</div>`;
  return `${partial ? '<p class="partial-label">Latest interim result · The conclusion may change.</p>' : '<p class="partial-label">Latest investigation conclusion</p>'}${heading}${fold('Clues examined · ' + (r.clues || []).length, (r.clues || []).map(c => `<div class="clue"><div class="clue-label">${escapeHtml(c.category)}<br><small>Strength ${escapeHtml(label(c.strength))}</small></div><div>${p(c.observation)}<small>${escapeHtml(c.interpretation)}</small></div></div>`).join(''))}${fold('Visual comparisons', (r.visual_comparisons || []).map(c => `<div class="comparison"><strong>${escapeHtml(c.reference_id)} · ${escapeHtml(label(c.verdict))}</strong>${p(c.conclusion)}${list(c.matching_details)}${list(c.differences)}</div>`).join(''))}${fold('Visible text', list(r.visible_text))}${fold('Alternative locations', (r.alternatives || []).map(c => candidate(c)).join(''))}${fold('Date, light and shadows', p(r.temporal_analysis))}${fold('Limitations and remaining checks', list(r.limitations))}${fold('Sources', sources(r.sources))}${fold('Research performed', list(r.research_performed))}${fold('Provenance and AI origin', p('AI origin: ' + label(r.provenance.ai_assessment)) + list(r.provenance.ai_evidence) + p('Declared author: ' + (r.provenance.author || 'unknown')) + p(r.provenance.author_basis) + list(r.provenance.limitations))}`;
}
function notice(text) { $('notice').textContent = text || ''; $('notice').hidden = !text; }
function select(file) {
  if (!file) return;
  if (file.size > 25 * 1024 * 1024) { notice('The limit is 25 MB per image.'); return; }
  selectedFile = file; notice('');
  if (objectUrl) URL.revokeObjectURL(objectUrl);
  objectUrl = URL.createObjectURL(file);
  $('selected-preview').src = objectUrl; $('selected-name').textContent = file.name;
  $('selected').hidden = false; $('dropzone').hidden = true; $('analyze').disabled = false;
}
$('file').addEventListener('change', e => select(e.target.files[0]));
$('remove').onclick = () => { $('file').value = ''; selectedFile = null; $('selected').hidden = true; $('dropzone').hidden = false; $('analyze').disabled = true; };
['dragenter', 'dragover'].forEach(name => $('dropzone').addEventListener(name, e => { e.preventDefault(); $('dropzone').classList.add('drag'); }));
['dragleave', 'drop'].forEach(name => $('dropzone').addEventListener(name, e => { e.preventDefault(); $('dropzone').classList.remove('drag'); }));
$('dropzone').addEventListener('drop', e => select(e.dataTransfer.files[0]));
async function api(url, options) { const response = await fetch(url, options); if (!response.ok) { let detail; try { detail = (await response.json()).detail; } catch { detail = 'Unexpected server response.'; } throw new Error(typeof detail === 'string' ? detail : 'Invalid request.'); } return response.json(); }
$('analyze').onclick = async () => {
  if (!selectedFile) return;
  $('analyze').disabled = true; notice('');
  const data = new FormData(); data.append('file', selectedFile);
  try { const job = await api('/api/jobs', {method:'POST', body:data}); openJob(job.id); } catch (e) { notice(e.message); $('analyze').disabled = false; }
};
function showJob(job) {
  $('job-title').textContent = job.status === 'completed' ? 'What this image reveals' : terminal(job.status) ? 'Investigation stopped' : 'Investigation in progress';
  $('stage').textContent = job.stage; $('percent').textContent = job.progress + ' %'; $('progress').value = job.progress;
  $('elapsed').textContent = `Started at ${new Date(job.created_at).toLocaleTimeString('en-GB', {hour:'2-digit', minute:'2-digit'})} · progress by stage`;
  $('timeline').replaceChildren(...job.events.slice(-7).reverse().map(event => { const li = document.createElement('li'); li.textContent = event.message; return li; }));
  $('cancel').hidden = terminal(job.status); $('working').hidden = !!job.report || !!job.partial || terminal(job.status);
  $('job-error').textContent = job.error || ''; $('job-error').hidden = !job.error;
  $('export').href = `/api/jobs/${job.id}/export`;
  $('job-settings').textContent = job.settings ? settingsLabel(job.settings) : 'Older investigation: model was not recorded.';
  $('deepen').hidden = !terminal(job.status) || !(job.report || job.partial);
  $('deepen-hint').hidden = $('deepen').hidden;
  updateMapData(job);
  renderReferences(job);
  const past = (job.revisions || []).slice(0, -1).reverse();
  const revisionKey = JSON.stringify([job.id, past]);
  if ($('revisions').dataset.key !== revisionKey) {
    $('revisions').innerHTML = past.map(r => fold(r.stage + ' · ' + new Date(r.time).toLocaleString('en-GB'), p(r.report.conclusion) + candidate(r.report.best_candidate))).join('');
    $('revisions').dataset.key = revisionKey;
  }
  $('revisions-panel').hidden = !past.length;
  if (job.metadata) {
    if ($('job-preview').dataset.job !== job.id) { $('job-preview').src = `/api/jobs/${job.id}/preview`; $('job-preview').dataset.job = job.id; }
    $('job-preview').hidden = false;
    $('file-details').textContent = `${job.filename} · ${job.metadata.width} × ${job.metadata.height} · ${(job.metadata.bytes / 1024 / 1024).toFixed(2)} MB`;
    $('metadata-panel').hidden = false; $('metadata').textContent = JSON.stringify(job.metadata, null, 2);
  }
  if (job.solar) { $('solar-panel').hidden = false; $('solar').textContent = JSON.stringify(job.solar, null, 2); }
  const report = job.report || job.partial;
  const key = JSON.stringify(report) + !!job.report;
  if (report && rendered !== key) { $('report').innerHTML = renderReport(report, !job.report); rendered = key; }
}
async function openJob(id) {
  resetMapSelection();
  if (matchMedia('(max-width:760px)').matches) setHistoryOpen(false);
  activeId = id; const generation = ++pollingGeneration;
  clearTimeout(timer); rendered = ''; notice('');
  document.body.classList.add('investigating'); $('investigation').hidden = false;
  $('report').replaceChildren(); $('job-preview').hidden = true; $('job-preview').removeAttribute('src'); delete $('job-preview').dataset.job;
  $('metadata-panel').hidden = true; $('solar-panel').hidden = true; $('job-error').hidden = true;
  $('file-details').textContent = ''; $('working').hidden = false;
  history.replaceState(null, '', '#enquete=' + id);
  async function poll() {
    try {
      const job = await api(`/api/jobs/${id}`);
      if (generation !== pollingGeneration) return;
      showJob(job);
      if (!terminal(job.status)) timer = setTimeout(poll, 1800);
      else refreshHistory();
    } catch (e) { if (generation !== pollingGeneration) return; notice(e.message + ' Retrying in a few seconds.'); timer = setTimeout(poll, 5000); }
  }
  await poll();
  await refreshHistory();
  window.scrollTo({top:0, behavior:'instant'});
}
$('cancel').onclick = async () => { $('cancel').disabled = true; try { await api(`/api/jobs/${activeId}/cancel`, {method:'POST'}); } catch (e) { notice(e.message); } finally { $('cancel').disabled = false; } };
$('new').onclick = () => { ++pollingGeneration; clearTimeout(timer); activeId = null; document.body.classList.remove('investigating'); $('investigation').hidden = true; history.replaceState(null, '', '/'); $('remove').click(); notice(''); refreshHistory(); };
function setHistoryOpen(open) {
  $('history-drawer').classList.toggle('open', open);
  document.body.classList.toggle('sidebar-open', open);
  $('history-toggle').setAttribute('aria-expanded', String(open));
  $('history-toggle').textContent = open ? '‹' : '›';
  $('history-section').inert = !open;
  if (map) requestAnimationFrame(() => map.invalidateSize());
}
$('history-toggle').onclick = () => setHistoryOpen(!$('history-drawer').classList.contains('open'));
$('history-toggle').addEventListener('pointerenter', e => { if (e.pointerType === 'mouse') setHistoryOpen(true); });
$('history-drawer').addEventListener('pointerleave', e => { if (e.pointerType === 'mouse' && !$('history-drawer').contains(document.activeElement)) setHistoryOpen(false); });
document.addEventListener('keydown', e => { if (e.key === 'Escape') setHistoryOpen(false); });
$('history-new').onclick = () => { $('new').click(); if (matchMedia('(max-width:760px)').matches) setHistoryOpen(false); };
// Hover opens the drawer; click and keyboard remain available on touch devices.
requestAnimationFrame(() => setHistoryOpen(false));
async function refreshHistory() {
  try {
    const items = await api('/api/jobs');
    $('history-empty').hidden = !!items.length;
    $('history').replaceChildren(...items.map(j => {
      const row = document.createElement('div'); row.className = 'history-row' + (activeId === j.id ? ' active' : '');
      const button = document.createElement('button'); button.className = 'history-item';
      if (activeId === j.id) button.setAttribute('aria-current', 'page');
      const strong = document.createElement('strong'); strong.textContent = j.filename;
      const span = document.createElement('span'); span.textContent = new Date(j.created_at).toLocaleString('en-GB') + ' · ' + ({completed:'Completed', running:'Running', pending:'Preparing', error:'Error', cancelled:'Stopped'}[j.status] || j.status);
      button.append(strong, span); button.onclick = () => openJob(j.id);
      const remove = document.createElement('button'); remove.className = 'history-delete'; remove.textContent = '×'; remove.title = 'Delete this investigation'; remove.setAttribute('aria-label', 'Delete investigation ' + j.filename);
      remove.onclick = async () => {
        if (!confirm('Delete this investigation et ses fichiers ? Une analyse en cours sera interrompue.')) return;
        remove.disabled = true;
        try { await api('/api/jobs/' + j.id, {method:'DELETE'}); if (activeId === j.id) $('new').click(); await refreshHistory(); }
        catch (e) { notice(e.message); remove.disabled = false; }
      };
      row.append(button, remove); return row;
    }));
  } catch (e) { console.debug(e.message); }
}
const effortLabels = {minimal:'Minimal', low:'Low', medium:'Medium', high:'High', xhigh:'Very high', max:'Maximum', ultra:'Ultra'};
let preferences = null, modelCatalog = [];
function settingsLabel(settings) { return `${settings.model} · reasoning ${effortLabels[settings.reasoning_effort] || settings.reasoning_effort} · autonomous research`; }
function updateEfforts(preferred) {
  const model = modelCatalog.find(m => m.id === $('model').value);
  const efforts = model?.efforts || [];
  $('settings-save').disabled = !efforts.length;
  $('reasoning').replaceChildren(...efforts.map(e => new Option(effortLabels[e] || e, e)));
  $('reasoning').value = efforts.includes(preferred) ? preferred : efforts.includes('high') ? 'high' : efforts[0];
}
async function loadSettings() {
  const data = await api('/api/settings');
  preferences = data.settings; modelCatalog = data.models;
  $('model').replaceChildren(...modelCatalog.map(m => new Option(m.name, m.id)));
  $('settings-summary').textContent = settingsLabel(preferences);
  $('model').value = modelCatalog.some(m => m.id === preferences.model) ? preferences.model : modelCatalog[0]?.id || ''; updateEfforts(preferences.reasoning_effort);
}
$('settings-open').onclick = async () => {
  try { await loadSettings(); $('settings-error').hidden = true; $('settings-dialog').showModal(); } catch (e) { notice(e.message); }
};
$('settings-close').onclick = () => $('settings-dialog').close();
$('model').onchange = () => updateEfforts($('reasoning').value);
$('settings-form').onsubmit = async e => {
  e.preventDefault(); $('settings-save').disabled = true;
  try {
    await api('/api/settings', {method:'PUT', headers:{'Content-Type':'application/json'}, body:JSON.stringify({model:$('model').value.trim(), reasoning_effort:$('reasoning').value})});
    await loadSettings(); $('settings-dialog').close();
  } catch (error) { $('settings-error').textContent = error.message; $('settings-error').hidden = false; }
  finally { $('settings-save').disabled = false; }
};
$('deepen').onclick = async () => {
  $('deepen').disabled = true;
  try { await api(`/api/jobs/${activeId}/deepen`, {method:'POST'}); await openJob(activeId); }
  catch (error) { notice(error.message); }
  finally { $('deepen').disabled = false; }
};

let map = null, mapLayers = null, mapRevisions = [], mapSelection = null, mapKey = '', referenceKey = '';
function resetMapSelection() { mapSelection = null; mapKey = ''; referenceKey = ''; }
function updateMapData(job) {
  mapRevisions = job.revisions?.length ? job.revisions : (job.report || job.partial) ? [{stage:'Available result', report:job.report || job.partial}] : [];
  const selected = mapSelection === null ? mapRevisions.length - 1 : Math.min(mapSelection, mapRevisions.length - 1);
  const select = $('map-revision');
  const opts = mapRevisions.map((r, i) => `${i+1}. ${r.stage}`);
  if (JSON.stringify(opts) !== select.dataset.options) {
    select.replaceChildren(...opts.map((label, i) => new Option(label, String(i))).reverse());
    select.dataset.options = JSON.stringify(opts);
  }
  select.disabled = !mapRevisions.length; select.value = String(selected);
  if (!$('map-panel').hidden) drawMap(selected);
}
function mapShapes(report, latest = false) {
  const zones = latest ? (report?.map_zones || []).slice(0,1) : report?.map_zones;
  if (zones?.length) return zones.map(z => ({...z, type:'bounds'}));
  return [report?.best_candidate, ...(latest ? [] : report?.alternatives || [])].filter(c => c?.coordinates && c.coordinates.accuracy_meters > 0).map(c => ({type:'circle', label:c.place, confidence:c.confidence, basis:c.coordinates.basis, ...c.coordinates}));
}
function drawMap(index) {
  if (typeof L === 'undefined') { $('map-message').textContent = 'Map library unavailable.'; return; }
  if (!map) {
    map = L.map('map', {worldCopyJump:true}).setView([20, 0], 2);
    L.tileLayer('https://tile.openstreetmap.org/{z}/{x}/{y}.png', {maxZoom:19, attribution:'&copy; <a href="https://www.openstreetmap.org/copyright" target="_blank" rel="noopener noreferrer">OpenStreetMap</a> contributors'}).addTo(map);
    mapLayers = L.featureGroup().addTo(map);
  }
  map.invalidateSize();
  const report = mapRevisions[index]?.report;
  let shapes = mapShapes(report, index === mapRevisions.length - 1);
  let inherited = false;
  if (!shapes.length) {
    for (let previous = index - 1; previous >= 0; previous--) {
      const earlier = mapShapes(mapRevisions[previous].report, true);
      if (earlier.length) { shapes = earlier.map(s => ({...s, historical:true, basis:'Previous working area · not revalidated at this stage. ' + s.basis})); inherited = true; break; }
    }
  }
  const registry = new Map();
  for (const revision of mapRevisions.slice(0, index + 1)) {
    for (const place of revision.report.tested_places || []) registry.set(place.label.toLocaleLowerCase('en'), place);
  }
  const places = [...registry.values()];
  const key = JSON.stringify([index, shapes, places, report?.best_candidate, report?.camera_orientation, report?.localization_confirmed]);
  if (key === mapKey) return;
  mapKey = key; mapLayers.clearLayers();
  $('map-zones').replaceChildren();
  const located = places.filter(p => Number.isFinite(p.latitude) && Number.isFinite(p.longitude));
  $('map-message').textContent = `${shapes.length} area(s) · ${located.length} tested location(s) mapped. ` + (inherited ? 'Dashed outline: previous working area, retained for context and not revalidated. ' : '') + (report?.narrowing || 'Markers show tested locations.');
  const addItem = (label, basis, lat, lon, status) => {
    const item = document.createElement('div'); item.className = 'zone-item';
    const strong = document.createElement('strong'); strong.textContent = label;
    const reason = document.createElement('p'); reason.textContent = basis;
    const link = document.createElement('a'); link.href = 'https://www.google.com/maps/search/?api=1&query=' + encodeURIComponent(Number.isFinite(lat) ? `${lat},${lon}` : label); link.textContent = 'Explore on Google Maps ↗'; link.target = '_blank'; link.rel = 'noopener noreferrer';
    item.append(strong, reason, link);
    if (Number.isFinite(lat)) {
      const street = document.createElement('a'); street.href = 'https://www.google.com/maps/@?api=1&map_action=pano&viewpoint=' + encodeURIComponent(`${lat},${lon}`); street.textContent = 'Street View ↗'; street.target = '_blank'; street.rel = 'noopener noreferrer'; street.className = 'street-link'; item.append(street);
    }
    if (status) item.dataset.status = status;
    $('map-zones').append(item);
    return item;
  };
  shapes.forEach((shape, i) => {
    const color = shape.historical ? '#8a8172' : '#416b45';
    const options = {color, weight:2, fillOpacity:.10, dashArray:shape.historical ? '6 6' : null};
    const layer = shape.type === 'bounds' ? L.rectangle([[shape.south, shape.west],[shape.north, shape.east]], options) : L.circle([shape.latitude, shape.longitude], {...options, radius:shape.accuracy_meters});
    const item = addItem(`${i+1}. ${shape.label}${shape.historical ? ' · previous area' : ' · leading area'} · confidence ${label(shape.confidence)}`, shape.basis);
    layer.bindPopup(item.cloneNode(true)); layer.addTo(mapLayers);
  });
  for (const place of places) {
    const color = {'à vérifier':'#466fa0',compatible:'#416b45','écarté':'#a14d49','accès bloqué':'#a66b39'}[place.status] || '#466fa0';
    const item = addItem(`${place.label} · ${label(place.status)}`, place.basis + (place.latitude == null ? ' · Coordinates unverified; no marker.' : ''), place.latitude, place.longitude, place.status);
    if (Number.isFinite(place.latitude) && Number.isFinite(place.longitude)) {
      L.circleMarker([place.latitude, place.longitude], {radius:7, color, weight:2, fillOpacity:.7}).bindPopup(item.cloneNode(true)).addTo(mapLayers);
    }
  }
  const camera = report?.best_candidate?.coordinates;
  if (report?.localization_confirmed && report.precision === 'coordonnées' && camera) {
    const lat = camera.latitude, lon = camera.longitude;
    const marker = L.circleMarker([lat, lon], {radius:9, color:'#a5b4fc', fillColor:'#7ce8ec', fillOpacity:1, weight:3});
    marker.bindPopup(`Verified camera position: ${lat.toFixed(6)}, ${lon.toFixed(6)}`).addTo(mapLayers);
    const heading = report.camera_orientation?.heading_degrees;
    if (heading != null) {
      const radians = heading * Math.PI / 180, distance = 100 / 6371000;
      const phi = lat * Math.PI / 180, lambda = lon * Math.PI / 180;
      const endPhi = Math.asin(Math.sin(phi)*Math.cos(distance) + Math.cos(phi)*Math.sin(distance)*Math.cos(radians));
      const endLambda = lambda + Math.atan2(Math.sin(radians)*Math.sin(distance)*Math.cos(phi), Math.cos(distance)-Math.sin(phi)*Math.sin(endPhi));
      L.polyline([[lat,lon],[endPhi*180/Math.PI,((endLambda*180/Math.PI+540)%360)-180]], {color:'#7ce8ec',weight:4}).bindTooltip(`Viewing direction: ${heading}° from true north`).addTo(mapLayers);
    }
  }
  if (!shapes.length && !places.length && !(report?.localization_confirmed && report.precision === 'coordonnées' && camera)) $('map-message').textContent = 'No map data at this stage. Further research may establish testable locations.';
  if (mapLayers.getLayers().length) map.fitBounds(mapLayers.getBounds().pad(.2), {maxZoom:17, animate:false});
  else map.setView([20,0],2,{animate:false});
}
$('map-toggle').onclick = () => {
  const panel = $('map-panel'); panel.hidden = !panel.hidden;
  $('map-toggle').setAttribute('aria-expanded', String(!panel.hidden));
  $('map-toggle').textContent = panel.hidden ? 'Show map' : 'Hide map';
  if (!panel.hidden) { mapKey = ''; requestAnimationFrame(() => drawMap(Number($('map-revision').value))); }
};
$('map-revision').onchange = () => { mapSelection = Number($('map-revision').value); drawMap(mapSelection); };
function renderReferences(job) {
  const key = JSON.stringify([job.id, job.references, job.reference_batches]);
  if (key === referenceKey) return; referenceKey = key;
  const refs = job.references || [], batches = job.reference_batches || [];
  $('references-panel').hidden = !refs.length && !batches.length;
  $('references').innerHTML = refs.map(r => {
    const url = safeUrl(r.page_url), license = safeUrl(r.license_url);
    return `<figure class="reference-card"><img loading="lazy" src="/api/jobs/${job.id}/references/${encodeURIComponent(r.id)}" alt="${escapeHtml(r.title)}"><figcaption>${url ? `<a target="_blank" rel="noopener noreferrer" href="${escapeHtml(url)}">${escapeHtml(r.id)} · ${escapeHtml(r.title)} ↗</a>` : escapeHtml(r.title)}<small>${escapeHtml(r.author)} · ${license ? `<a target="_blank" rel="noopener noreferrer" href="${escapeHtml(license)}">${escapeHtml(r.license)}</a>` : escapeHtml(r.license)}</small><small>Search: ${escapeHtml(r.query)}</small></figcaption></figure>`;
  }).join('');
  $('reference-errors').innerHTML = batches.filter(b => b.errors?.length).map(b => `<p class="reference-error">${escapeHtml(b.stage)} : ${b.errors.map(escapeHtml).join(' · ')}</p>`).join('');
}

(async () => {
  try { const health = await api('/api/health'); const ok = health.codex_installed && health.authenticated; $('engine').className = 'engine ' + (ok ? 'ready' : 'offline'); $('engine').lastChild.textContent = ok ? 'Codex ready' : health.codex_installed ? 'Connect Codex' : 'Codex missing'; if (!ok) notice(health.codex_installed ? 'Connect Codex using “codex login”, then reload this page.' : 'Install Codex CLI and sign in using “codex login”.'); } catch { $('engine').lastChild.textContent = 'Server unavailable'; }
  try { await loadSettings(); } catch (e) { notice('Settings unavailable: ' + e.message); }
  await refreshHistory(); const match = location.hash.match(/^#enquete=([a-f0-9]{32})$/); if (match) openJob(match[1]);
})();
