import hashlib
import io
import json
import math
import shutil
import subprocess
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

import exifread
from astral import Observer
from astral.sun import elevation, sun
from PIL import ExifTags, Image, ImageEnhance, ImageOps, ImageStat

Image.MAX_IMAGE_PIXELS = 40_000_000
ALLOWED = {"JPEG", "PNG", "WEBP", "TIFF", "HEIF", "AVIF"}


def serial(value):
    if isinstance(value, bytes):
        return value.decode("utf-8", errors="replace")[:12000]
    if isinstance(value, dict):
        return {str(k): serial(v) for k, v in value.items()}
    if isinstance(value, (list, tuple)):
        return [serial(v) for v in value]
    if isinstance(value, float) and not math.isfinite(value):
        return str(value)
    if isinstance(value, (int, float, str, bool)) or value is None:
        return value
    return str(value)[:12000]


def gps_coordinate(values, ref):
    result = float(values[0]) + float(values[1]) / 60 + float(values[2]) / 3600
    return -result if str(ref).upper() in {"S", "W"} else result


def inspect_image(path: Path, directory: Path):
    raw = path.read_bytes()
    with Image.open(io.BytesIO(raw)) as source:
        if source.format not in ALLOWED:
            raise ValueError("Unsupported format. Use JPEG, PNG, WebP, TIFF or AVIF.")
        source.load()
        exif = source.getexif()
        metadata = {ExifTags.TAGS.get(k, str(k)): serial(v) for k, v in exif.items()}
        for ifd in (ExifTags.IFD.Exif, ExifTags.IFD.GPSInfo):
            try:
                values = exif.get_ifd(ifd)
                labels = ExifTags.GPSTAGS if ifd == ExifTags.IFD.GPSInfo else ExifTags.TAGS
                metadata[ifd.name] = {labels.get(k, str(k)): serial(v) for k, v in values.items()}
            except (KeyError, ValueError, TypeError):
                pass
        gps = None
        try:
            g = exif.get_ifd(ExifTags.IFD.GPSInfo)
            lat, lon = gps_coordinate(g[2], g[1]), gps_coordinate(g[4], g[3])
            if math.isfinite(lat) and math.isfinite(lon) and -90 <= lat <= 90 and -180 <= lon <= 180:
                gps = {"latitude": lat, "longitude": lon, "warning": "GPS declared in file; not authenticated."}
        except (KeyError, ValueError, TypeError, ZeroDivisionError, IndexError):
            pass
        info = {k: serial(v) for k, v in source.info.items() if k not in {"exif", "icc_profile"}}
        profile = source.info.get("icc_profile")
        if profile:
            info["icc_profile_bytes"] = len(profile)
        rgb = ImageOps.exif_transpose(source).convert("RGB")
        width, height = rgb.size
        preview = rgb.copy()
        preview.thumbnail((2400, 2400))
        preview.save(directory / "preview.jpg", quality=92)
        ImageEnhance.Brightness(ImageOps.autocontrast(preview)).enhance(1.5).save(directory / "enhanced.jpg", quality=92)
        crops = []
        # Four overlapping quadrants preserve small details without exceeding model input sizes.
        w, h = rgb.size
        for i, box in enumerate(((0, 0, w * .6, h * .6), (w * .4, 0, w, h * .6), (0, h * .4, w * .6, h), (w * .4, h * .4, w, h))):
            name = f"detail-{i+1}.jpg"
            detail = rgb.crop(tuple(map(int, box)))
            detail.thumbnail((1800, 1800))
            detail.save(directory / name, quality=94)
            crops.append(name)
        brightness = ImageStat.Stat(preview.convert("L")).mean[0]
        fmt = source.format
    with path.open("rb") as file:
        try:
            tags = {str(k): serial(v) for k, v in exifread.process_file(file, details=True).items() if "Thumbnail" not in str(k)}
        except Exception as exc:
            tags = {"read_error": str(exc)}
    exiftool = None
    if shutil.which("exiftool"):
        try:
            result = subprocess.run(["exiftool", "-json", "-G", "-a", str(path)], capture_output=True, timeout=30, check=True)
            exiftool = json.loads(result.stdout)[0]
        except (subprocess.SubprocessError, ValueError):
            exiftool = {"error": "ExifTool unavailable for this file"}
    result = {
        "sha256": hashlib.sha256(raw).hexdigest(), "bytes": len(raw), "format": fmt,
        "width": width, "height": height, "exif": metadata, "tags": tags, "embedded": info,
        "gps": gps, "mean_luminance_0_255": round(brightness, 2),
        "c2pa_marker_present": b"c2pa" in raw.lower(),
        "c2pa_verification": "Unverified: presence or absence of a marker does not prove origin.",
        "exiftool": exiftool,
        "crops": crops,
    }
    (directory / "metadata.json").write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
    return result


def solar_check(metadata, candidate):
    """Only compute for a candidate with coordinates, a real capture date and a valid timezone."""
    if not candidate or not candidate.coordinates:
        return {"status": "non calculable", "reason": "No supported candidate coordinates."}
    tags = metadata.get("tags", {})
    exif = metadata.get("exif", {})
    nested = exif.get("Exif", {})
    stamp = tags.get("EXIF DateTimeOriginal") or nested.get("DateTimeOriginal") or exif.get("DateTimeOriginal")
    offset = tags.get("EXIF OffsetTimeOriginal") or nested.get("OffsetTimeOriginal")
    if not stamp:
        return {"status": "non calculable", "reason": "Capture date missing. Brightness alone establishes neither time nor country."}
    try:
        naive = datetime.strptime(str(stamp), "%Y:%m:%d %H:%M:%S")
        if offset and str(offset) not in {"None", ""}:
            when = datetime.fromisoformat(naive.isoformat() + str(offset))
            assumption = "UTC offset declared in file; authenticity not established."
        elif candidate.timezone:
            zone = ZoneInfo(candidate.timezone)
            when = naive.replace(tzinfo=zone)
            assumption = "EXIF time assumed local to candidate; daylight saving ambiguity is possible."
        else:
            return {"status": "non calculable", "reason": "Timezone and UTC offset unknown."}
        observer = Observer(candidate.coordinates.latitude, candidate.coordinates.longitude)
        try:
            times = {k: v.isoformat() for k, v in sun(observer, date=when.date(), tzinfo=when.tzinfo).items()}
        except ValueError:
            times = {"note": "A solar event does not occur on this date (polar region)."}
        return {"status": "calculé", "candidate": candidate.place, "capture_time": when.isoformat(),
                "assumption": assumption, "solar_elevation_degrees": round(elevation(observer, when), 2),
                "events": times, "method": "Astral astronomical calculation; historical weather not verified.",
                "limit": "Candidate consistency check, not proof of location. Exposure and editing can darken the image."}
    except (ValueError, KeyError, TypeError, OverflowError) as exc:
        return {"status": "non calculable", "reason": f"Unusable date or timezone: {exc}"}
