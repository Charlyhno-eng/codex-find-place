import asyncio
import json
import os
import signal
from pathlib import Path
from ..models import Report
from ..settings import load_settings
from ..prompts import BASE_PROMPT

class CodexError(Exception):
    pass


async def terminate(process):
    if process and process.returncode is None:
        try:
            os.killpg(process.pid, signal.SIGTERM)
        except ProcessLookupError:
            return
        try:
            await asyncio.wait_for(process.wait(), 5)
        except asyncio.TimeoutError:
            try:
                os.killpg(process.pid, signal.SIGKILL)
            except ProcessLookupError:
                pass
            await process.wait()


async def codex_pass(job, stage, instruction, images):
    directory: Path = job.directory
    schema = directory / "report-schema.json"
    definition = Report.model_json_schema()
    if stage.startswith("conclusion-"):
        definition["properties"]["map_zones"]["maxItems"] = 1
    def require_all(value):
        if isinstance(value, dict):
            if value.get("type") == "object":
                value["required"] = list(value.get("properties", {}))
            value.pop("default", None)
            for child in value.values():
                require_all(child)
        elif isinstance(value, list):
            for child in value:
                require_all(child)
    require_all(definition)
    schema.write_text(json.dumps(definition, ensure_ascii=False), encoding="utf-8")
    settings = job.settings or load_settings(directory.parent).model_dump()
    output = directory / f"{stage}-report.json"
    output.unlink(missing_ok=True)
    args = ["codex", "--search", "--ask-for-approval", "never", "exec", "--ignore-user-config",
            "--sandbox", "read-only", "--skip-git-repo-check", "--ephemeral", "--json",
            "--color", "never", "-C", str(directory), "-c", 'model_reasoning_effort=' + json.dumps(settings['reasoning_effort']),
            "--output-schema", str(schema), "--output-last-message", str(output)]
    args += ["--model", settings["model"]]
    for img in images:
        args += ["--image", str(directory / img)]
    args += ["-"]
    prompt = BASE_PROMPT + "\n" + instruction
    (directory / f"{stage}-prompt.txt").write_text(prompt, encoding="utf-8")
    with (directory / f"{stage}-stderr.log").open("wb") as stderr:
        try:
            process = await asyncio.create_subprocess_exec(*args, stdin=asyncio.subprocess.PIPE,
                stdout=asyncio.subprocess.PIPE, stderr=stderr, start_new_session=True, limit=4*1024*1024)
        except FileNotFoundError as exc:
            raise CodexError("Codex CLI not found. Install Codex and run codex login.") from exc
        job.process = process
        try:
            async with asyncio.timeout(int(os.getenv("OSINT_PASS_TIMEOUT", "900"))):
                process.stdin.write(prompt.encode())
                await process.stdin.drain()
                process.stdin.close()
                error_message = None
                with (directory / f"{stage}-events.jsonl").open("w", encoding="utf-8") as trace:
                    async for line in process.stdout:
                        trace.write(line.decode(errors="replace"))
                        trace.flush()
                        try:
                            event = json.loads(line)
                        except ValueError:
                            continue
                        kind = event.get("type", "")
                        if kind in {"error", "turn.failed"}:
                            error_message = event.get("message") or event.get("error", {}).get("message") or "Codex engine failed."
                        if kind == "item.started":
                            item = event.get("item", {})
                            labels = {"web_search": "Checking web sources", "command_execution": "Verifying evidence", "mcp_tool_call": "Consulting a tool"}
                            if item.get("type") in labels:
                                job.event(labels[item["type"]])
                    code = await process.wait()
                if code != 0 or error_message:
                    tail = (directory / f"{stage}-stderr.log").read_text(errors="replace")[-2500:]
                    raise CodexError(str(error_message or tail or f"Codex exited with code {code}.")[:1800])
                if not output.exists():
                    raise CodexError("Codex did not provide a structured report.")
                return Report.model_validate_json(output.read_text(encoding="utf-8"))
        except TimeoutError as exc:
            raise CodexError("This analysis stage timed out. Existing results have been saved.") from exc
        finally:
            await terminate(process)
            job.process = None

