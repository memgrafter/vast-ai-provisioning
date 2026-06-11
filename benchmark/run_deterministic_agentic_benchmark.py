#!/usr/bin/env python3
"""Deterministic agentic-coding benchmark runner.

This runner does not ask the model to invent benchmark tasks. It reads a static
problem manifest, sends each language-bound problem in manifest order, validates
basic response shape, correlates optional llama.cpp backend timing logs, and
writes a compact Markdown report.
"""

from __future__ import annotations

import argparse
import json
import os
import re
import shlex
import statistics
import subprocess
import sys
import time
import urllib.error
import urllib.request
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

LANGUAGE_ALIASES: dict[str, set[str]] = {
    "cpp": {"cpp", "c++", "cc", "cxx"},
    "c++": {"cpp", "c++", "cc", "cxx"},
    "python": {"python", "py"},
    "java": {"java"},
    "typescript": {"typescript", "ts"},
    "javascript": {"javascript", "js"},
    "go": {"go", "golang"},
}

REQUIRED_SECTIONS = ["## Approach", "## Code", "## Complexity", "## Tests", "## Self-evaluation"]
FORBIDDEN_DRIFT_PHRASES = [
    "i will create a new",
    "let me create a problem",
    "here is a new leetcode",
    "i'll ask myself",
]


@dataclass
class BackendRelease:
    task: int
    slot_tokens: int
    truncated: int
    prompt_ms: float | None = None
    prompt_tokens: int | None = None
    prompt_tps: float | None = None
    eval_ms: float | None = None
    eval_tokens: int | None = None
    eval_tps: float | None = None
    draft_acceptance: float | None = None
    draft_accepted: int | None = None
    draft_generated: int | None = None


@dataclass
class RequestResult:
    iteration: int
    request_id: str
    task_id: str
    title: str
    language: str
    http_status: int
    client_start: str
    client_end: str
    response_bytes: int
    content_chars: int
    usage: dict[str, Any] | None
    validation: dict[str, Any]
    observed_context: int | None
    prompt_tokens: int | None
    completion_tokens: int | None
    backend: BackendRelease | None


def utc_now() -> datetime:
    return datetime.now(timezone.utc)


def iso_now() -> str:
    return utc_now().isoformat().replace("+00:00", "Z")


def load_manifest(path: Path) -> dict[str, Any]:
    manifest = json.loads(path.read_text(encoding="utf-8"))
    if manifest.get("version") != 1:
        raise ValueError(f"unsupported manifest version: {manifest.get('version')!r}")
    problems = manifest.get("problems")
    if not isinstance(problems, list) or not problems:
        raise ValueError("manifest must contain a non-empty problems list")
    seen_ids: set[str] = set()
    for index, problem in enumerate(problems, start=1):
        for key in ["id", "title", "language", "code_fence", "prompt", "requirements"]:
            if key not in problem:
                raise ValueError(f"problem #{index} missing required key: {key}")
        if problem["id"] in seen_ids:
            raise ValueError(f"duplicate problem id: {problem['id']}")
        seen_ids.add(problem["id"])
        if not isinstance(problem["requirements"], list) or not problem["requirements"]:
            raise ValueError(f"problem {problem['id']} must include non-empty requirements")
    return manifest


def build_system_message() -> dict[str, str]:
    return {
        "role": "system",
        "content": (
            "You are an expert competitive-programming and systems-design coding assistant. "
            "Solve exactly the provided benchmark problem. Do not invent a new problem. "
            "Do not change the requested language. Preserve the required response format."
        ),
    }


def build_user_message(problem: dict[str, Any], request_id: str, iteration: int, solution_dir: Path | None = None) -> dict[str, str]:
    requirements = "\n".join(f"- {item}" for item in problem["requirements"])
    patterns = "\n".join(f"- {item}" for item in problem.get("language_patterns", [])) or "- Use idiomatic language design."
    code_fence = problem["code_fence"]
    workspace = ""
    if solution_dir is not None:
        workspace = (
            "\n# Benchmark workspace\n"
            f"If you create or modify files, use only this run-specific directory: {solution_dir}\n"
            "Do not reuse files outside this directory.\n"
        )
    user = f"""REQUEST_ID: {request_id}
TASK_ID: {problem['id']}
ITERATION: {iteration}
LANGUAGE: {problem['language']}
EXPECTED_CODE_FENCE: ```{code_fence}

You must solve this exact static benchmark problem. Do not create a new problem.

# Problem
{problem['title']}

{problem['prompt']}

# Language-specific design patterns to elicit
{patterns}

# Requirements
{requirements}{workspace}

# Required response format
TASK_ID: {problem['id']}
LANGUAGE: {problem['language']}

## Approach
Explain the algorithm.

## Code
```{code_fence}
<complete solution>
```

## Complexity
State time and space complexity.

## Tests
Give representative tests.

## Self-evaluation
List likely bugs and edge cases.
"""
    return {"role": "user", "content": user}


def build_messages(problem: dict[str, Any], request_id: str, iteration: int) -> list[dict[str, str]]:
    return [build_system_message(), build_user_message(problem, request_id, iteration)]


def request_json(base_url: str, api_key: str | None, payload: dict[str, Any], timeout: int) -> tuple[int, bytes, dict[str, str]]:
    body = json.dumps(payload, separators=(",", ":")).encode("utf-8")
    req = urllib.request.Request(f"{base_url.rstrip('/')}/chat/completions", data=body, method="POST")
    req.add_header("Content-Type", "application/json")
    if api_key:
        req.add_header("Authorization", f"Bearer {api_key}")
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            return resp.status, resp.read(), dict(resp.headers.items())
    except urllib.error.HTTPError as exc:
        return exc.code, exc.read(), dict(exc.headers.items())


def stringify_response_part(value: Any) -> str:
    if value is None:
        return ""
    if isinstance(value, str):
        return value
    if isinstance(value, list):
        return "\n".join(
            part.get("text", str(part)) if isinstance(part, dict) else str(part)
            for part in value
        )
    return str(value)


def extract_content(response_body: bytes) -> tuple[str, dict[str, Any] | None, dict[str, Any]]:
    text = response_body.decode("utf-8", errors="replace")
    data = json.loads(text)
    usage = data.get("usage") if isinstance(data, dict) else None
    content = ""
    choices = data.get("choices") or []
    if choices:
        choice = choices[0]
        message = choice.get("message") or {}
        content = (
            message.get("content")
            or message.get("reasoning_content")
            or message.get("reasoning")
            or choice.get("text")
            or ""
        )
    if isinstance(content, list):
        content = "\n".join(part.get("text", str(part)) if isinstance(part, dict) else str(part) for part in content)
    return content, usage, data


def usage_token_count(usage: dict[str, Any] | None, key: str) -> int | None:
    if not isinstance(usage, dict):
        return None
    value = usage.get(key)
    return value if isinstance(value, int) else None


def observed_context_for_backend(backend_mode: str, usage: dict[str, Any] | None, backend: BackendRelease | None) -> int | None:
    if backend_mode == "llama.cpp" and backend is not None:
        return backend.slot_tokens
    return usage_token_count(usage, "prompt_tokens")


def target_context_threshold(backend_mode: str, target_context: int | None, response_headroom: int | None, max_tokens: int) -> int | None:
    if target_context is None:
        return None
    if backend_mode == "vllm":
        headroom = max_tokens if response_headroom is None else response_headroom
        return max(0, target_context - headroom)
    return target_context


def validate_response(content: str, problem: dict[str, Any]) -> dict[str, Any]:
    missing_sections = [section for section in REQUIRED_SECTIONS if section not in content]
    task_id_present = f"TASK_ID: {problem['id']}" in content
    language_present = f"LANGUAGE: {problem['language']}" in content
    fence_aliases = LANGUAGE_ALIASES.get(problem["code_fence"].lower(), {problem["code_fence"].lower()})
    fences = {match.lower() for match in re.findall(r"```([A-Za-z0-9_+#.-]+)", content)}
    fence_ok = bool(fences & fence_aliases)
    lower_content = content.lower()
    drift_phrases = [phrase for phrase in FORBIDDEN_DRIFT_PHRASES if phrase in lower_content]
    code_block_count = len(re.findall(r"```", content)) // 2
    ok = not missing_sections and task_id_present and language_present and fence_ok and not drift_phrases
    return {
        "ok": ok,
        "missing_sections": missing_sections,
        "task_id_present": task_id_present,
        "language_present": language_present,
        "code_fence_ok": fence_ok,
        "code_fences_seen": sorted(fences),
        "code_block_count": code_block_count,
        "drift_phrases": drift_phrases,
    }


def parse_backend_releases(path: Path) -> list[BackendRelease]:
    if not path.exists():
        return []
    current_task: int | None = None
    timing_by_task: dict[int, dict[str, Any]] = {}
    releases: list[BackendRelease] = []
    timing_task_re = re.compile(r"slot print_timing: id\s+\d+ \| task (\d+) \|")
    prompt_re = re.compile(r"prompt eval time =\s*([0-9.]+) ms /\s*(\d+) tokens .*?([0-9.]+) tokens per second")
    eval_re = re.compile(r"eval time =\s*([0-9.]+) ms /\s*(\d+) tokens .*?([0-9.]+) tokens per second")
    draft_re = re.compile(r"draft acceptance rate = ([0-9.]+) \(\s*(\d+) accepted /\s*(\d+) generated\)")
    release_re = re.compile(r"task (\d+) \| stop processing: n_tokens = (\d+), truncated = (\d+)")
    for line in path.read_text(errors="replace").splitlines():
        match = timing_task_re.search(line)
        if match:
            current_task = int(match.group(1))
            timing_by_task.setdefault(current_task, {})
        match = prompt_re.search(line)
        if match and current_task is not None:
            timing_by_task.setdefault(current_task, {}).update(
                prompt_ms=float(match.group(1)), prompt_tokens=int(match.group(2)), prompt_tps=float(match.group(3))
            )
        match = eval_re.search(line)
        if match and current_task is not None:
            timing_by_task.setdefault(current_task, {}).update(
                eval_ms=float(match.group(1)), eval_tokens=int(match.group(2)), eval_tps=float(match.group(3))
            )
        match = draft_re.search(line)
        if match and current_task is not None:
            timing_by_task.setdefault(current_task, {}).update(
                draft_acceptance=float(match.group(1)),
                draft_accepted=int(match.group(2)),
                draft_generated=int(match.group(3)),
            )
        match = release_re.search(line)
        if match:
            task = int(match.group(1))
            timing = timing_by_task.get(task, {})
            releases.append(
                BackendRelease(
                    task=task,
                    slot_tokens=int(match.group(2)),
                    truncated=int(match.group(3)),
                    **timing,
                )
            )
    return releases


def wait_for_new_backend_release(path: Path | None, previous_count: int, timeout_seconds: int) -> BackendRelease | None:
    if path is None:
        return None
    deadline = time.monotonic() + timeout_seconds
    while time.monotonic() < deadline:
        releases = parse_backend_releases(path)
        if len(releases) > previous_count:
            return releases[-1]
        time.sleep(0.5)
    return None



def backend_totals(rows: list[RequestResult]) -> dict[str, Any]:
    prompt_tokens = 0
    prompt_ms = 0.0
    eval_tokens = 0
    eval_ms = 0.0
    draft_accepted = 0
    draft_generated = 0
    for row in rows:
        backend = row.backend
        if backend is None:
            continue
        if backend.prompt_tokens is not None and backend.prompt_ms is not None:
            prompt_tokens += backend.prompt_tokens
            prompt_ms += backend.prompt_ms
        if backend.eval_tokens is not None and backend.eval_ms is not None:
            eval_tokens += backend.eval_tokens
            eval_ms += backend.eval_ms
        if backend.draft_accepted is not None and backend.draft_generated is not None:
            draft_accepted += backend.draft_accepted
            draft_generated += backend.draft_generated
    return {
        "prompt_tokens": prompt_tokens,
        "prompt_seconds": prompt_ms / 1000.0,
        "prefill_tps": prompt_tokens / (prompt_ms / 1000.0) if prompt_ms > 0 else None,
        "eval_tokens": eval_tokens,
        "eval_seconds": eval_ms / 1000.0,
        "generation_tps": eval_tokens / (eval_ms / 1000.0) if eval_ms > 0 else None,
        "draft_acceptance": draft_accepted / draft_generated if draft_generated else None,
        "draft_accepted": draft_accepted,
        "draft_generated": draft_generated,
    }


def fmt_float(value: float | None, digits: int = 2) -> str:
    return "n/a" if value is None else f"{value:.{digits}f}"


def parse_proxy_status_counts(proxy_log: Path | None) -> dict[str, int]:
    if proxy_log is None or not proxy_log.exists():
        return {}
    counts: dict[str, int] = {}
    for line in proxy_log.read_text(errors="replace").splitlines():
        if "POST /v1/chat/completions" not in line:
            continue
        match = re.search(r'"POST /v1/chat/completions HTTP/1\.1" (\d+)', line)
        if match:
            counts[match.group(1)] = counts.get(match.group(1), 0) + 1
    return counts


def parse_backend_header(backend_log: Path | None) -> dict[str, str]:
    if backend_log is None or not backend_log.exists():
        return {}
    header: dict[str, str] = {}
    for line in backend_log.read_text(errors="replace").splitlines()[:80]:
        if line.startswith("MODEL="):
            header["model"] = line.split("=", 1)[1]
        elif line.startswith("CTX="):
            header["ctx_line"] = line
        elif line.startswith("CACHE_K="):
            header["cache_line"] = line
        elif line.startswith("SERVE="):
            header["serve_line"] = line
        elif " - CUDA" in line:
            header.setdefault("gpu", line.strip())
        elif "upgrading K from" in line:
            header["kv_auto_upgrade"] = line.strip()
        elif "new slot, n_ctx" in line:
            header["slot"] = line.strip()
    return header


def context_bands(results: list[RequestResult], band_size: int = 30_000) -> list[tuple[int, int, list[RequestResult], dict[str, Any]]]:
    rows = [row for row in results if row.backend is not None]
    if not rows:
        return []
    max_ctx = max(row.backend.slot_tokens for row in rows if row.backend is not None)
    bands = []
    for low in range(0, max_ctx + band_size, band_size):
        high = low + band_size
        band_rows = [
            row for row in rows
            if row.backend is not None and row.backend.slot_tokens <= high and (low == 0 or row.backend.slot_tokens > low)
        ]
        bands.append((low, high, band_rows, backend_totals(band_rows)))
    return bands


def median_backend_value(rows: list[RequestResult], field: str) -> float | None:
    values = [getattr(row.backend, field) for row in rows if row.backend is not None and getattr(row.backend, field) is not None]
    if not values:
        return None
    return float(statistics.median(values))


def generate_report(path: Path, manifest_path: Path, run_id: str, results: list[RequestResult], backend_log: Path | None, proxy_log: Path | None) -> None:
    validated = [result.validation.get("ok") is True for result in results]
    backend_rows = [result for result in results if result.backend is not None]
    trunc_sum = sum(result.backend.truncated for result in backend_rows if result.backend is not None)
    max_ctx = max((result.observed_context for result in results if result.observed_context is not None), default=None)
    totals = backend_totals(results)
    proxy_counts = parse_proxy_status_counts(proxy_log)
    backend_header = parse_backend_header(backend_log)
    proxy_summary = "not provided" if not proxy_counts else ", ".join(f"HTTP {code}: {count}" for code, count in sorted(proxy_counts.items()))
    lines = [
        "# Deterministic Agentic Benchmark Report",
        "",
        f"Run ID: `{run_id}`",
        f"Manifest: `{manifest_path}`",
        f"Backend log: `{backend_log or 'not provided'}`",
        f"Proxy log: `{proxy_log or 'not provided'}` ({proxy_summary})",
        "",
    ]
    if backend_header:
        lines.extend(["## llama.cpp runtime", ""])
        for key in ["model", "ctx_line", "cache_line", "serve_line", "gpu", "kv_auto_upgrade", "slot"]:
            if key in backend_header:
                lines.append(f"- {key}: `{backend_header[key]}`")
        lines.append("")
    lines.extend([
        "## Validity",
        "",
        f"- Requests completed: {len(results)}",
        f"- Responses passing validation: {sum(validated)} / {len(validated)}",
        f"- Backend-correlated requests: {len(backend_rows)} / {len(results)}",
        f"- Max backend context: {max_ctx if max_ctx is not None else 'n/a'}",
        f"- Truncated responses: {trunc_sum}",
        f"- Proxy status counts: {proxy_summary}",
        "",
        "## Overall llama.cpp timing",
        "",
        f"- Prompt-eval tokens: {totals['prompt_tokens']}",
        f"- Prompt-eval seconds: {fmt_float(totals['prompt_seconds'], 3)}",
        f"- Weighted prefill TPS: {fmt_float(totals['prefill_tps'])} tok/s",
        f"- Generation tokens: {totals['eval_tokens']}",
        f"- Generation seconds: {fmt_float(totals['eval_seconds'], 3)}",
        f"- Weighted generation TPS: {fmt_float(totals['generation_tps'])} tok/s",
        f"- Draft acceptance: {fmt_float(totals['draft_acceptance'], 4)} ({totals['draft_accepted']} / {totals['draft_generated']})",
        "",
        "These TPS values come from llama.cpp final timing blocks: `prompt eval time` and `eval time`. If the server reuses an existing slot/checkpoint, prompt-eval tokens are the tokens actually evaluated for that request, not necessarily the full OpenAI `usage.prompt_tokens` value.",
        "",
        "## Context bands",
        "",
        "| Final context band | Requests | Context range | Prefill tok/s | Median prefill tok/s | Gen tok/s | Median gen tok/s | Draft acceptance |",
        "|---:|---:|---:|---:|---:|---:|---:|---:|",
    ])
    for low, high, band_rows, band_totals in context_bands(results):
        contexts = [row.backend.slot_tokens for row in band_rows if row.backend is not None]
        context_range = f"{min(contexts)}-{max(contexts)}" if contexts else "n/a"
        lines.append(
            f"| {low // 1000}-{high // 1000}k | {len(band_rows)} | {context_range} | "
            f"{fmt_float(band_totals['prefill_tps'])} | {fmt_float(median_backend_value(band_rows, 'prompt_tps'))} | "
            f"{fmt_float(band_totals['generation_tps'])} | {fmt_float(median_backend_value(band_rows, 'eval_tps'))} | "
            f"{fmt_float(band_totals['draft_acceptance'], 4)} |"
        )
    lines.extend([
        "",
        "## Requests",
        "",
        "| Iter | Task | Lang | HTTP | Valid | Context | Prompt eval toks | Prefill tok/s | Gen toks | Gen tok/s | Draft acc |",
        "|---:|---|---|---:|---|---:|---:|---:|---:|---:|---:|",
    ])
    for result in results:
        backend = result.backend
        lines.append(
            "| {iter} | `{task}` | {lang} | {http} | {valid} | {ctx} | {ptok} | {prefill} | {gtok} | {gen} | {draft} |".format(
                iter=result.iteration,
                task=result.task_id,
                lang=result.language,
                http=result.http_status,
                valid="yes" if result.validation.get("ok") else "no",
                ctx=result.observed_context if result.observed_context is not None else "n/a",
                ptok=backend.prompt_tokens if backend and backend.prompt_tokens is not None else "n/a",
                prefill=fmt_float(backend.prompt_tps if backend else None),
                gtok=backend.eval_tokens if backend and backend.eval_tokens is not None else "n/a",
                gen=fmt_float(backend.eval_tps if backend else None),
                draft=fmt_float(backend.draft_acceptance if backend else None, 4),
            )
        )
    lines.extend(["", "## Validation failures", ""])
    failures = [result for result in results if not result.validation.get("ok")]
    if not failures:
        lines.append("None.")
    else:
        for result in failures:
            lines.append(f"- Iteration {result.iteration} `{result.task_id}`: `{json.dumps(result.validation, sort_keys=True)}`")
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def resolve_model_profile_settings(model_id: str) -> dict[str, Any] | None:
    for path in sorted(Path("config/models").glob("*.json")):
        profile = json.loads(path.read_text(encoding="utf-8"))
        aliases = {str(profile.get("name")), str(profile.get("served_model_name"))}
        if model_id not in aliases:
            continue
        llamacpp = profile.get("llamacpp") or {}
        vllm = profile.get("vllm") or {}
        # Use the model's max-tokens default unless a benchmark explicitly
        # requires a specified different output budget.
        max_tokens = llamacpp.get("n_predict", vllm.get("max_new_tokens"))
        return {
            "provider_name": "model-profile",
            "provider": {},
            "model": profile,
            "compat": profile.get("compat") or {},
            "max_tokens": int(max_tokens) if max_tokens is not None else None,
            "reasoning": bool(profile.get("reasoning")),
        }
    return None


def resolve_model_settings(models_config: Path, model_id: str) -> dict[str, Any] | None:
    profile_settings = resolve_model_profile_settings(model_id)
    if profile_settings is not None:
        return profile_settings
    if not models_config.exists():
        return None
    config = json.loads(models_config.read_text(encoding="utf-8"))
    requested_provider: str | None = None
    requested_model = model_id
    if "/" in model_id:
        requested_provider, requested_model = model_id.split("/", 1)
    for provider_name, provider in (config.get("providers") or {}).items():
        if requested_provider is not None and provider_name != requested_provider:
            continue
        for model in provider.get("models") or []:
            if model.get("id") == requested_model or model.get("id") == model_id:
                compat = {}
                compat.update(provider.get("compat") or {})
                compat.update(model.get("compat") or {})
                return {
                    "provider_name": provider_name,
                    "provider": provider,
                    "model": model,
                    "compat": compat,
                    "max_tokens": int(model["maxTokens"]) if model.get("maxTokens") is not None else None,
                    "reasoning": bool(model.get("reasoning")),
                }
    return None


def thinking_enabled_for_request(model_settings: dict[str, Any] | None, thinking: str) -> bool:
    if thinking == "on":
        return True
    if thinking == "off":
        return False
    return bool(model_settings and model_settings.get("reasoning"))


def apply_reasoning_payload_settings(payload: dict[str, Any], model_settings: dict[str, Any] | None, thinking: str) -> None:
    if not model_settings:
        return
    thinking_format = (model_settings.get("compat") or {}).get("thinkingFormat")
    enabled = thinking_enabled_for_request(model_settings, thinking)
    if thinking_format == "qwen-chat-template":
        kwargs = payload.setdefault("chat_template_kwargs", {})
        kwargs["enable_thinking"] = enabled
        # Qwen3.x templates emit an assistant `<think>...</think>` preamble at
        # generation time. Preserve it when replaying assistant turns so
        # llama.cpp's rendered prompt remains token-identical to saved KV.
        kwargs["preserve_thinking"] = True
    elif thinking_format == "qwen":
        payload["enable_thinking"] = enabled
    elif enabled:
        if thinking_format == "deepseek":
            payload["thinking"] = {"type": "enabled"}
        # Other provider-specific thinking formats are intentionally left to
        # the client/model config used outside this direct HTTP benchmark.



def run_command(command: list[str], *, check: bool = True) -> subprocess.CompletedProcess[str]:
    return subprocess.run(command, text=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE, check=check)


ANSI_RE = re.compile(r"\x1b\[[0-?]*[ -/]*[@-~]")


def strip_ansi(text: str) -> str:
    return ANSI_RE.sub("", text)


def tmux_session_exists(session: str) -> bool:
    return run_command(["tmux", "has-session", "-t", session], check=False).returncode == 0


def tmux_pane_id(session: str, window: str) -> str:
    return run_command(["tmux", "display-message", "-p", "-t", f"{session}:{window}", "#{pane_id}"]).stdout.strip()


def pane_current_command(target: str) -> str:
    return run_command(["tmux", "display-message", "-p", "-t", target, "#{pane_current_command}"], check=False).stdout.strip()


def capture_pane_text(target: str, lines: int = 4000) -> str:
    return strip_ansi(run_command(["tmux", "capture-pane", "-p", "-t", target, "-S", f"-{lines}"], check=False).stdout)


def create_pi_tmux_session(session: str, window: str, cwd: Path, pi_model: str, pi_session_file: Path) -> str:
    launch = (
        f"cd {shlex.quote(str(cwd))} && "
        "source env.vast-management 2>/dev/null || true && "
        f"exec pi --model {shlex.quote(pi_model)} --session {shlex.quote(str(pi_session_file))}"
    )
    if tmux_session_exists(session):
        if run_command(["tmux", "list-windows", "-t", session, "-F", "#{window_name}"], check=False).stdout.splitlines().count(window):
            run_command(["tmux", "kill-window", "-t", f"{session}:{window}"], check=False)
        run_command(["tmux", "new-window", "-d", "-t", session, "-n", window, "-c", str(cwd), "bash", "-lc", launch])
    else:
        run_command(["tmux", "new-session", "-d", "-s", session, "-n", window, "-c", str(cwd), "bash", "-lc", launch])
    pane_id = tmux_pane_id(session, window)
    deadline = time.monotonic() + 90
    while time.monotonic() < deadline:
        if pane_current_command(pane_id) in {"node", "pi"}:
            return pane_id
        time.sleep(0.5)
    raise TimeoutError(f"pi pane did not start in tmux session {session}")


def submit_prompt_to_pane(pane_id: str, prompt_path: Path, buffer_name: str) -> None:
    run_command(["tmux", "load-buffer", "-b", buffer_name, str(prompt_path)])
    try:
        run_command(["tmux", "paste-buffer", "-p", "-b", buffer_name, "-t", pane_id])
    finally:
        run_command(["tmux", "delete-buffer", "-b", buffer_name], check=False)
    run_command(["tmux", "send-keys", "-t", pane_id, "Enter"])


def load_session_entries(path: Path) -> list[dict[str, Any]]:
    if not path.exists():
        return []
    entries: list[dict[str, Any]] = []
    for line in path.read_text(encoding="utf-8", errors="replace").splitlines():
        if not line.strip():
            continue
        try:
            entries.append(json.loads(line))
        except json.JSONDecodeError:
            continue
    return entries


def assistant_messages(entries: list[dict[str, Any]]) -> list[dict[str, Any]]:
    return [
        entry for entry in entries
        if entry.get("type") == "message" and isinstance(entry.get("message"), dict) and entry["message"].get("role") == "assistant"
    ]


def user_messages(entries: list[dict[str, Any]]) -> list[dict[str, Any]]:
    return [
        entry for entry in entries
        if entry.get("type") == "message" and isinstance(entry.get("message"), dict) and entry["message"].get("role") == "user"
    ]


def message_content_to_text(content: Any) -> str:
    if isinstance(content, str):
        return content
    if isinstance(content, dict):
        if isinstance(content.get("text"), str):
            return content["text"]
        return ""
    if isinstance(content, list):
        parts: list[str] = []
        for item in content:
            text = message_content_to_text(item)
            if text:
                parts.append(text)
        return "\n".join(parts)
    return ""


def wait_for_assistant_turn(session_file: Path, before_user_count: int, before_assistant_count: int, timeout_seconds: int) -> dict[str, Any]:
    deadline = time.monotonic() + timeout_seconds
    last_signature: tuple[int, int, int] | None = None
    stable_polls = 0
    while time.monotonic() < deadline:
        entries = load_session_entries(session_file)
        users = user_messages(entries)
        assistants = assistant_messages(entries)
        if len(users) > before_user_count and len(assistants) > before_assistant_count and session_file.exists():
            latest_entry = entries[-1] if entries else None
            latest_message = latest_entry.get("message") if isinstance(latest_entry, dict) and latest_entry.get("type") == "message" else None
            latest_role = latest_message.get("role") if isinstance(latest_message, dict) else None
            latest_stop_reason = latest_message.get("stopReason") if isinstance(latest_message, dict) else None
            if latest_role == "assistant" and latest_stop_reason not in {"toolUse", "aborted"}:
                stat = session_file.stat()
                signature = (len(entries), len(users), len(assistants), stat.st_size)
                if signature == last_signature:
                    stable_polls += 1
                else:
                    last_signature = signature
                    stable_polls = 0
                if stable_polls >= 2:
                    return assistants[-1]
            else:
                last_signature = None
                stable_polls = 0
        else:
            last_signature = None
            stable_polls = 0
        time.sleep(1)
    raise TimeoutError(f"timed out waiting for assistant turn in {session_file}")


def run_pi_tmux(args: argparse.Namespace, manifest: dict[str, Any], manifest_path: Path, run_id: str, out_dir: Path, jsonl_path: Path, report_path: Path) -> int:
    problems = manifest["problems"][: args.max_problems] if args.max_problems else manifest["problems"]
    if not problems:
        raise ValueError("selected problem list is empty")
    if not args.pi_model:
        raise ValueError("--driver pi-tmux requires --pi-model")
    responses_dir = out_dir / "responses"
    prompts_dir = out_dir / "prompts"
    captures_dir = out_dir / "tmux-captures"
    solution_dir = out_dir / "solutions"
    for path in [responses_dir, prompts_dir, captures_dir, solution_dir]:
        path.mkdir(exist_ok=True)
    pi_session_file = Path(args.pi_session_file or (out_dir / "pi-session.jsonl"))
    pi_session_file.parent.mkdir(parents=True, exist_ok=True)
    session_name = args.tmux_session or f"{args.tmux_session_prefix}-{run_id}"
    repo_root = Path.cwd()
    pane_id = "dry-run"
    results: list[RequestResult] = []
    try:
        if not args.dry_run:
            pane_id = create_pi_tmux_session(session_name, args.tmux_window, repo_root, args.pi_model, pi_session_file)
        total_iterations = args.max_iterations
        for iteration in range(1, total_iterations + 1):
            problem = problems[(iteration - 1) % len(problems)]
            request_id = f"{run_id}-iter-{iteration:04d}-{problem['id']}"
            prompt = build_user_message(problem, request_id, iteration, solution_dir=solution_dir)["content"]
            prompt_path = prompts_dir / f"{iteration:04d}-{problem['id']}.txt"
            response_path = responses_dir / f"{iteration:04d}-{problem['id']}.txt"
            capture_path = captures_dir / f"{iteration:04d}-{problem['id']}.txt"
            prompt_path.write_text(prompt, encoding="utf-8")
            start_time = iso_now()
            usage = None
            observed_context = None
            prompt_tokens = None
            completion_tokens = None
            if args.dry_run:
                status_code = 0
                content = ""
                validation = {"ok": True, "dry_run": True}
                end_time = start_time
            else:
                before_entries = load_session_entries(pi_session_file)
                before_user_count = len(user_messages(before_entries))
                before_assistant_count = len(assistant_messages(before_entries))
                submit_prompt_to_pane(pane_id, prompt_path, f"det-agentic-{iteration}")
                try:
                    assistant_entry = wait_for_assistant_turn(pi_session_file, before_user_count, before_assistant_count, args.timeout)
                    assistant_message = assistant_entry.get("message") or {}
                    status_code = 0
                    content = message_content_to_text(assistant_message.get("content"))
                    raw_usage = assistant_message.get("usage")
                    usage = raw_usage if isinstance(raw_usage, dict) else None
                    if usage is not None:
                        prompt_tokens = usage.get("input") if isinstance(usage.get("input"), int) else usage.get("prompt_tokens")
                        completion_tokens = usage.get("output") if isinstance(usage.get("output"), int) else usage.get("completion_tokens")
                        observed_context = prompt_tokens if isinstance(prompt_tokens, int) else None
                    validation = {
                        "ok": True,
                        "mode": "pi_tmux_unscored",
                        "stop_reason": assistant_message.get("stopReason"),
                        "provider": assistant_message.get("provider"),
                        "model": assistant_message.get("model"),
                    }
                except TimeoutError as exc:
                    status_code = 124
                    content = ""
                    validation = {"ok": False, "timeout": str(exc)}
                end_time = iso_now()
                capture_path.write_text(capture_pane_text(pane_id), encoding="utf-8")
                response_path.write_text(content, encoding="utf-8")
            result = RequestResult(
                iteration=iteration,
                request_id=request_id,
                task_id=problem["id"],
                title=problem["title"],
                language=problem["language"],
                http_status=200 if status_code == 0 else status_code,
                client_start=start_time,
                client_end=end_time,
                response_bytes=len(content.encode("utf-8")),
                content_chars=len(content),
                usage=usage,
                validation=validation,
                observed_context=observed_context,
                prompt_tokens=prompt_tokens,
                completion_tokens=completion_tokens,
                backend=None,
            )
            results.append(result)
            with jsonl_path.open("a", encoding="utf-8") as handle:
                handle.write(json.dumps(asdict(result), sort_keys=True) + "\n")
            print(f"iter={iteration} task={problem['id']} pi_status={status_code} valid={validation.get('ok')} context={observed_context} chars={len(content)}", flush=True)
            if args.fail_fast and (status_code != 0 or not validation.get("ok")):
                break
            if args.target_context is not None and observed_context is not None and observed_context >= args.target_context:
                break
        generate_report(report_path, manifest_path, run_id, results, None, None)
        print(f"tmux session={session_name}")
        print(f"tmux pane={pane_id}")
        print(f"pi_session={pi_session_file}")
        print(f"solution_dir={solution_dir}")
        print(f"wrote {jsonl_path}")
        print(f"wrote {report_path}")
        return 0 if all(result.validation.get("ok") for result in results) else 1
    finally:
        if not args.dry_run and not args.keep_session:
            run_command(["tmux", "kill-session", "-t", session_name], check=False)


def run(args: argparse.Namespace) -> int:
    manifest_path = Path(args.manifest)
    manifest = load_manifest(manifest_path)
    problems = manifest["problems"][: args.max_problems] if args.max_problems else manifest["problems"]
    if not problems:
        raise ValueError("selected problem list is empty")
    run_id = args.run_id or utc_now().strftime("det-agentic-%Y%m%d-%H%M%S")
    out_dir = Path(args.out_dir or Path("benchmark") / "runs" / run_id)
    out_dir.mkdir(parents=True, exist_ok=True)
    responses_dir = out_dir / "responses"
    responses_dir.mkdir(exist_ok=True)
    jsonl_path = out_dir / "requests.jsonl"
    report_path = out_dir / "report.md"
    if args.driver == "pi-tmux":
        return run_pi_tmux(args, manifest, manifest_path, run_id, out_dir, jsonl_path, report_path)
    backend_log = Path(args.backend_log) if args.backend_log else None
    proxy_log = Path(args.proxy_log) if args.proxy_log else None
    default_api_key_env = {"vllm": "VLLM_API_KEY", "llama.cpp": "LLAMACPP_API_KEY", "generic": "OPENAI_API_KEY"}[args.backend]
    api_key_env = args.api_key_env or default_api_key_env
    api_key = args.api_key or os.environ.get(api_key_env)
    model_settings = resolve_model_settings(Path(args.pi_models_config).expanduser(), args.model)
    max_tokens = args.max_tokens
    if max_tokens is None and model_settings is not None:
        max_tokens = model_settings.get("max_tokens")
    if max_tokens is None:
        raise ValueError("max tokens was not provided and could not be resolved from config/models or .pi/models.json; pass --max-tokens, set model-profile llamacpp.n_predict/vllm.max_new_tokens, or set model.maxTokens")

    context_threshold = target_context_threshold(args.backend, args.target_context, args.response_headroom, max_tokens)
    results: list[RequestResult] = []
    previous_backend_count = len(parse_backend_releases(backend_log)) if backend_log else 0
    conversation_history: list[dict[str, str]] = []

    if args.target_context is not None:
        total_iterations = args.max_iterations
    else:
        total_iterations = len(problems) if args.max_iterations is None else min(len(problems), args.max_iterations)

    for iteration in range(1, total_iterations + 1):
        problem = problems[(iteration - 1) % len(problems)]
        request_id = f"{run_id}-iter-{iteration:04d}-{problem['id']}"
        current_user_message = build_user_message(problem, request_id, iteration)
        if args.accumulate_context:
            messages = [build_system_message(), *conversation_history, current_user_message]
        else:
            messages = [build_system_message(), current_user_message]
        payload = {
            "model": args.model,
            "messages": messages,
            "temperature": args.temperature,
            "top_p": args.top_p,
            "max_tokens": max_tokens,
            "stream": False,
            "metadata": {"run_id": run_id, "request_id": request_id, "task_id": problem["id"]},
        }
        apply_reasoning_payload_settings(payload, model_settings, args.thinking)
        if args.dry_run:
            content = ""
            status = 0
            raw = b""
            usage = None
            validation = {"ok": True, "dry_run": True}
            backend = None
            start_time = end_time = iso_now()
        else:
            start_time = iso_now()
            status, raw, _headers = request_json(args.base_url, api_key, payload, args.timeout)
            end_time = iso_now()
            response_path = responses_dir / f"{iteration:04d}-{problem['id']}.json"
            response_path.write_bytes(raw)
            try:
                content, usage, _data = extract_content(raw)
            except Exception as exc:
                content = ""
                usage = None
                validation = {"ok": False, "parse_error": str(exc)}
            else:
                validation = validate_response(content, problem)
            backend = wait_for_new_backend_release(backend_log, previous_backend_count, args.backend_wait) if status == 200 and backend_log else None
            if backend is not None:
                previous_backend_count += 1
        prompt_tokens = usage_token_count(usage, "prompt_tokens")
        completion_tokens = usage_token_count(usage, "completion_tokens")
        observed_context = observed_context_for_backend(args.backend, usage, backend)
        if args.target_context is not None and observed_context is None and not args.dry_run:
            raise RuntimeError(
                f"--target-context requires observed context for backend {args.backend!r}; "
                "vllm/generic need response usage.prompt_tokens, llama.cpp needs --backend-log correlation"
            )
        result = RequestResult(
            iteration=iteration,
            request_id=request_id,
            task_id=problem["id"],
            title=problem["title"],
            language=problem["language"],
            http_status=status,
            client_start=start_time,
            client_end=end_time,
            response_bytes=len(raw),
            content_chars=len(content),
            usage=usage,
            validation=validation,
            observed_context=observed_context,
            prompt_tokens=prompt_tokens,
            completion_tokens=completion_tokens,
            backend=backend,
        )
        if args.accumulate_context and status == 200 and content:
            conversation_history.append(current_user_message)
            conversation_history.append({"role": "assistant", "content": content})
        results.append(result)
        with jsonl_path.open("a", encoding="utf-8") as handle:
            row = asdict(result)
            handle.write(json.dumps(row, sort_keys=True) + "\n")
        print(
            f"iter={iteration} task={problem['id']} status={status} valid={validation.get('ok')} "
            f"ctx={observed_context if observed_context is not None else 'n/a'} "
            f"prompt={prompt_tokens if prompt_tokens is not None else 'n/a'} "
            f"completion={completion_tokens if completion_tokens is not None else 'n/a'} "
            f"gen_tps={fmt_float(backend.eval_tps if backend else None)}",
            flush=True,
        )
        if args.fail_fast and (status != 200 or not validation.get("ok") or (backend is None and backend_log is not None)):
            break
        if context_threshold is not None and observed_context is not None and observed_context >= context_threshold:
            break

    generate_report(report_path, manifest_path, run_id, results, backend_log, proxy_log)
    print(f"wrote {jsonl_path}")
    print(f"wrote {report_path}")
    return 0 if all(result.validation.get("ok") for result in results) else 1


def parse_args(argv: list[str]) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--driver", choices=["direct", "pi-tmux"], default="direct", help="Execution driver. pi-tmux drives real Pi sessions through tmux.")
    parser.add_argument("--backend", choices=["vllm", "llama.cpp", "generic"], default="generic", help="Backend semantics for context tracking and API-key defaults in direct mode")
    parser.add_argument("--manifest", default="benchmark/problem_manifest.example.json")
    parser.add_argument("--base-url", default=os.environ.get("OPENAI_BASE_URL", "http://127.0.0.1:8081/v1"))
    parser.add_argument("--model", default=os.environ.get("OPENAI_MODEL", "qwen3.6-28b-reap-iq3-m"))
    parser.add_argument("--api-key", default=None)
    parser.add_argument("--api-key-env", default=None, help="Environment variable containing API key. Defaults by --backend")
    parser.add_argument("--run-id", default=None)
    parser.add_argument("--out-dir", default=None)
    parser.add_argument("--max-problems", type=int, default=None)
    parser.add_argument("--max-iterations", type=int, default=1000, help="Maximum requests when --target-context is set; otherwise caps one manifest pass")
    parser.add_argument("--max-tokens", type=int, default=None, help="Completion token cap. Defaults to config/models llamacpp.n_predict or vllm.max_new_tokens, then model.maxTokens from .pi/models.json")
    parser.add_argument("--pi-models-config", default=".pi/models.json", help="Pi models config used to resolve maxTokens when --max-tokens is omitted")
    parser.add_argument("--temperature", type=float, default=0.0)
    parser.add_argument("--top-p", type=float, default=1.0)
    parser.add_argument("--thinking", choices=["auto", "on", "off"], default="auto", help="Thinking mode for direct requests. auto follows model config; qwen-chat-template also preserves replayed thinking wrappers.")
    parser.add_argument("--timeout", type=int, default=900)
    parser.add_argument("--backend-log", default=None, help="Optional local llama.cpp backend log to correlate after each request")
    parser.add_argument("--proxy-log", default=None, help="Optional local proxy log to summarize in the report")
    parser.add_argument("--backend-wait", type=int, default=30)
    parser.add_argument("--target-context", type=int, default=None)
    parser.add_argument("--response-headroom", type=int, default=None, help="For --backend vllm, stop when usage.prompt_tokens reaches target-context minus this headroom. Defaults to max_tokens.")
    parser.add_argument("--no-accumulate-context", dest="accumulate_context", action="store_false", help="Do not include prior turns in later requests")
    parser.set_defaults(accumulate_context=True)
    parser.add_argument("--fail-fast", action="store_true")
    parser.add_argument("--pi-model", default=None, help="Pi model for --driver pi-tmux, e.g. provider/model")
    parser.add_argument("--tmux-session", default=None, help="Explicit tmux session name for --driver pi-tmux. Defaults to a unique session per run.")
    parser.add_argument("--tmux-session-prefix", default="det-agentic-benchmark", help="Prefix for auto-generated tmux session names in --driver pi-tmux")
    parser.add_argument("--tmux-window", default="deterministic-agentic", help="tmux window for --driver pi-tmux")
    parser.add_argument("--pi-session-file", default=None, help="Pi session file for --driver pi-tmux. Defaults inside out-dir.")
    parser.add_argument("--keep-session", action="store_true", help="Keep the benchmark-owned tmux session after exit")
    parser.add_argument("--dry-run", action="store_true", help="Validate manifest and write a report without calling an API")
    return parser.parse_args(argv)


if __name__ == "__main__":
    raise SystemExit(run(parse_args(sys.argv[1:])))
