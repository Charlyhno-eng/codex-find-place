import asyncio
import json
import os
import re
import shutil
import uuid
from contextlib import asynccontextmanager
from datetime import datetime, timezone
from pathlib import Path

import uvicorn
from fastapi import FastAPI, File, HTTPException, Request, UploadFile
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from PIL import UnidentifiedImageError, Image

from .engine import investigate, terminate
from .imaging import inspect_image
from .settings import Settings, load_settings, save_settings, settings_payload

ROOT = Path(__file__).resolve().parent
DATA = Path(os.getenv("OSINT_DATA_DIR", str(ROOT.parent / "data"))).resolve()
MAX_UPLOAD = 25 * 1024 * 1024
jobs = {}
upload_lock = asyncio.Lock()


class Job:
    def __init__(self, job_id, directory):
        self.id, self.directory = job_id, directory
        self.status, self.stage, self.progress = "pending", "Preparing", 0
        self.created_at = datetime.now(timezone.utc).isoformat()
        self.filename = ""
        self.events = []
        self.metadata = self.report = self.partial = self.solar = self.error = None
        self.process = self.task = None
        self.settings = None
        self.revisions, self.references, self.reference_batches = [], [], []

    def snapshot(self):
        return {key: getattr(self, key) for key in ("id", "status", "stage", "progress", "created_at", "filename", "events", "metadata", "report", "partial", "solar", "error", "settings", "revisions", "references", "reference_batches")}

    def save(self):
        temp = self.directory / "state.tmp"
        temp.write_text(json.dumps(self.snapshot(), ensure_ascii=False), encoding="utf-8")
        temp.replace(self.directory / "state.json")

    def event(self, message):
        if self.events and self.events[-1]["message"] == message:
            return
        self.events.append({"time": datetime.now(timezone.utc).isoformat(), "message": message})
        self.events = self.events[-100:]
        self.save()

    def update(self, status, stage, progress):
        self.status, self.stage, self.progress = status, stage, progress
        self.event(stage)
        self.save()


@asynccontextmanager
async def lifespan(app):
    DATA.mkdir(parents=True, exist_ok=True)
    for state in DATA.glob("*/state.json"):
        try:
            value = json.loads(state.read_text(encoding="utf-8"))
            job = Job(value["id"], state.parent)
            for k in job.snapshot():
                if k in value:
                    setattr(job, k, value[k])
            if job.status in {"pending", "running"}:
                job.status, job.error = "error", "The application stopped during this investigation. Start a new analysis."
                job.save()
            jobs[job.id] = job
        except (ValueError, KeyError, OSError):
            continue
    yield
    tasks = [j.task for j in jobs.values() if j.task and not j.task.done()]
    for task in tasks:
        task.cancel()
    if tasks:
        await asyncio.gather(*tasks, return_exceptions=True)


app = FastAPI(title="Codex Find Place", lifespan=lifespan)


@app.middleware("http")
async def local_only(request: Request, call_next):
    if request.url.hostname not in {"127.0.0.1", "localhost", "::1", "testserver"}:
        return JSONResponse({"detail": "This application only allows local access."}, status_code=403)
    origin = request.headers.get("origin")
    if origin and origin != str(request.base_url).rstrip("/"):
        return JSONResponse({"detail": "Origin not allowed."}, status_code=403)
    response = await call_next(request)
    response.headers["X-Content-Type-Options"] = "nosniff"
    response.headers["Referrer-Policy"] = "strict-origin-when-cross-origin"
    response.headers["Content-Security-Policy"] = "default-src 'self'; img-src 'self' blob: data: https://tile.openstreetmap.org; style-src 'self'; script-src 'self'; connect-src 'self'; frame-ancestors 'none'; base-uri 'none'; form-action 'self'"
    return response


@app.get("/")
async def index():
    return FileResponse(ROOT / "static/index.html")


@app.get("/api/health")
async def health():
    binary = shutil.which("codex")
    authenticated = False
    if binary:
        try:
            p = await asyncio.create_subprocess_exec(binary, "login", "status", stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE)
            try:
                await asyncio.wait_for(p.communicate(), 10)
                authenticated = p.returncode == 0
            finally:
                if p.returncode is None:
                    p.kill()
                    await p.wait()
        except OSError:
            pass
    return {"codex_installed": bool(binary), "authenticated": authenticated}


@app.get("/api/settings")
async def read_settings():
    try:
        return settings_payload(DATA)
    except ValueError as exc:
        raise HTTPException(503, str(exc))


@app.put("/api/settings")
async def update_settings(settings: Settings):
    try:
        save_settings(DATA, settings)
    except ValueError as exc:
        raise HTTPException(422, str(exc))
    return settings_payload(DATA)


async def run_job(job, resume=False):
    try:
        if not resume:
            job.update("running", "Extracting metadata and preparing image details", 8)
            preparation = asyncio.create_task(asyncio.to_thread(inspect_image, job.directory / "original", job.directory))
            try:
                job.metadata = await asyncio.shield(preparation)
            except asyncio.CancelledError:
                # A worker thread cannot be cancelled; let it finish before deletion.
                await preparation
                raise
        job.save()
        if resume:
            await investigate(job, resume=True)
        else:
            await investigate(job)
    except asyncio.CancelledError:
        await terminate(job.process)
        job.error = "Analysis stopped. Interim results have been saved."
        job.update("cancelled", "Analysis stopped", job.progress)
        raise
    except Exception as exc:
        job.error = str(exc)[:2000] or type(exc).__name__
        job.update("error", "Analysis stopped due to an error", job.progress)


@app.post("/api/jobs", status_code=202)
async def create_job(file: UploadFile = File(...)):
    if upload_lock.locked():
        raise HTTPException(429, "An upload is already in progress.")
    async with upload_lock:
        return await _create_job(file)


async def _create_job(file):
    if any(j.status in {"pending", "running"} for j in jobs.values()):
        raise HTTPException(429, "An investigation is already running. Wait for it to finish or stop it.")
    job_id = uuid.uuid4().hex
    directory = DATA / job_id
    directory.mkdir(parents=True)
    try:
        size = 0
        with (directory / "original").open("wb") as output:
            while chunk := await file.read(1024 * 1024):
                size += len(chunk)
                if size > MAX_UPLOAD:
                    raise HTTPException(413, "The image exceeds the 25 MB limit.")
                output.write(chunk)
        if not size:
            raise HTTPException(400, "The file is empty.")
        try:
            with Image.open(directory / "original") as image:
                if image.width * image.height > 40_000_000:
                    raise ValueError("Image too large")
                image.verify()
        except (UnidentifiedImageError, OSError, ValueError, Image.DecompressionBombError, Image.DecompressionBombWarning):
            raise HTTPException(400, "Unreadable image or image too large (40 megapixels maximum).")
        job = Job(job_id, directory)
        job.filename = Path(file.filename or "image").name[:180]
        job.settings = load_settings(DATA).model_dump()
        job.save()
        jobs[job_id] = job
        job.task = asyncio.create_task(run_job(job))
        return {"id": job_id}
    except BaseException:
        shutil.rmtree(directory, ignore_errors=True)
        raise
    finally:
        await file.close()


def get_job(job_id):
    if not re.fullmatch(r"[a-f0-9]{32}", job_id) or job_id not in jobs:
        raise HTTPException(404, "Investigation not found.")
    return jobs[job_id]


@app.get("/api/jobs")
async def list_jobs():
    return [{"id": j.id, "filename": j.filename, "status": j.status, "created_at": j.created_at} for j in sorted(jobs.values(), key=lambda j: j.created_at, reverse=True)]


@app.get("/api/jobs/{job_id}")
async def job_status(job_id: str):
    return get_job(job_id).snapshot()


@app.post("/api/jobs/{job_id}/cancel")
async def cancel_job(job_id: str):
    job = get_job(job_id)
    if job.task and not job.task.done():
        job.task.cancel()
        await asyncio.gather(job.task, return_exceptions=True)
    return job.snapshot()


@app.delete("/api/jobs/{job_id}")
async def delete_job(job_id: str):
    async with upload_lock:
        job = get_job(job_id)
        if job.task and not job.task.done():
            job.task.cancel()
            await asyncio.gather(job.task, return_exceptions=True)
        # Wait for cancellation and its final state write before removing the files.
        await asyncio.to_thread(shutil.rmtree, job.directory)
        del jobs[job_id]
        return {"deleted": job_id}


@app.post("/api/jobs/{job_id}/deepen", status_code=202)
async def deepen_job(job_id: str):
    async with upload_lock:
        job = get_job(job_id)
        if any(j.status in {"pending", "running"} for j in jobs.values()):
            raise HTTPException(429, "An investigation is already running.")
        if not (job.report or job.partial) or not job.metadata:
            raise HTTPException(409, "No report available for further research yet.")
        if not (job.directory / "preview.jpg").exists():
            raise HTTPException(409, "The images for this investigation are no longer available.")
        job.settings = load_settings(DATA).model_dump()
        job.error = None
        job.partial = job.report or job.partial
        job.report = None
        job.update("running", "Resuming investigation", 30)
        job.task = asyncio.create_task(run_job(job, resume=True))
        return {"id": job.id}


@app.get("/api/jobs/{job_id}/references/{reference_id}")
async def reference_image(job_id: str, reference_id: str):
    job = get_job(job_id)
    ref = next((r for r in job.references if r["id"] == reference_id), None)
    if not ref or not re.fullmatch(r"ref-[0-9]{4,8}\.jpg", ref["file"]):
        raise HTTPException(404, "Reference not found.")
    path = job.directory / ref["file"]
    if not path.exists():
        raise HTTPException(404, "Reference image unavailable.")
    return FileResponse(path, media_type="image/jpeg")


@app.get("/api/jobs/{job_id}/preview")
async def preview(job_id: str):
    path = get_job(job_id).directory / "preview.jpg"
    if not path.exists():
        raise HTTPException(404, "Preparing preview.")
    return FileResponse(path, media_type="image/jpeg")


@app.get("/api/jobs/{job_id}/export")
async def export_job(job_id: str):
    job = get_job(job_id)
    return JSONResponse(job.snapshot(), headers={"Content-Disposition": f'attachment; filename="investigation-{job_id[:8]}.json"'})


app.mount("/static", StaticFiles(directory=ROOT / "static"), name="static")


def main():
    print("\n  Codex Find Place → http://127.0.0.1:8000\n")
    uvicorn.run("osint_picture.app:app", host="127.0.0.1", port=8000)
