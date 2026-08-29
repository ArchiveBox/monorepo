#!/usr/bin/env python3
"""Collect ArchiveBox CI telemetry from existing public build results.

The collector is intentionally read-only. It never dispatches workflows or runs
member-repository test commands; it only reads GitHub Actions metadata/logs and
public package registries, then emits the static JSON consumed by the dashboard.
"""

from __future__ import annotations

import argparse
import json
import os
import re
import sys
from collections import defaultdict, deque
from datetime import UTC, datetime, timedelta
from http.client import IncompleteRead
from pathlib import Path
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.parse import quote, urlsplit
from urllib.request import HTTPRedirectHandler, Request, build_opener


SCHEMA_VERSION = 1
JOB_METRICS_VERSION = 1
LOG_PARSER_VERSION = 2
MAX_LOG_CANDIDATES_PER_RUN = 10
GITHUB_API = "https://api.github.com"
PROJECTS: tuple[dict[str, Any], ...] = (
    {
        "slug": "abxbus",
        "repo": "abxbus",
        "workflow": "ci.yml",
        "pypi": "abxbus",
        "import": "abxbus",
    },
    {
        "slug": "abxpkg",
        "repo": "abxpkg",
        "workflow": "tests.yml",
        "pypi": "abxpkg",
        "import": "abxpkg",
    },
    {
        "slug": "abx-plugins",
        "repo": "abx-plugins",
        "workflow": "test-parallel.yml",
        "pypi": "abx-plugins",
        "import": "abx_plugins",
    },
    {
        "slug": "abx-dl",
        "repo": "abx-dl",
        "workflow": "ci.yml",
        "pypi": "abx-dl",
        "import": "abx_dl",
        "docker": "abx-dl",
    },
    {
        "slug": "archivebox",
        "repo": "ArchiveBox",
        "workflow": "ci.yml",
        "pypi": "archivebox",
        "import": "archivebox",
        "docker": "archivebox",
    },
)

TEST_JOB_RE = re.compile(
    r"(?:^|[/ ])(?:test|tests|pytest|python|go|rust|typescript|docs?|plugin)", re.I
)
NON_TEST_JOB_RE = re.compile(
    r"(?:setup|build release|docker build|lint|prek|codeql|publish)", re.I
)
DOCKER_STEP_RE = re.compile(
    r"(?:build (?:local|pull request)|build and push|build .*image)", re.I
)
ANSI_RE = re.compile(r"\x1b\[[0-9;]*[A-Za-z]")
TIMESTAMP_RE = re.compile(r"^\d{4}-\d\d-\d\dT\d\d:\d\d:\d\d(?:\.\d+)?Z\s+")
PYTEST_SUMMARY_RE = re.compile(
    r"^(?:=+\s*)?(?P<body>(?:\d+\s+(?:passed|failed|skipped|error|errors|xfailed|xpassed|deselected)(?:,?\s*|$))+)",
    re.I,
)
COUNT_RE = re.compile(
    r"(\d+)\s+(passed|failed|skipped|error|errors|xfailed|xpassed|deselected)", re.I
)
DURATION_RE = re.compile(r"^\s*(\d+(?:\.\d+)?)s\s+call\s+(.+?::.+?)\s*$")
RUST_SUMMARY_RE = re.compile(
    r"test result: .*?\b(\d+) passed; (\d+) failed;.*?finished in (\d+(?:\.\d+)?)s",
    re.I,
)
JS_SUMMARY_RE = re.compile(
    r"Tests?\s*:?\s*(?:(\d+) failed[, ]+)?(?:(\d+) passed)?", re.I
)
TTFI_JSON_RE = re.compile(r"ABX_EVALS\s+(\{.*\})")
TTFI_TEXT_RE = re.compile(r"ABX_EVALS?.*?ttfi_ms[=:]\s*(\d+(?:\.\d+)?)", re.I)


def utc_now() -> datetime:
    return datetime.now(UTC)


def parse_time(value: str | None) -> datetime | None:
    if not value:
        return None
    try:
        return datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None


def duration_ms(start: str | None, end: str | None) -> int | None:
    start_dt, end_dt = parse_time(start), parse_time(end)
    if not start_dt or not end_dt:
        return None
    return max(0, round((end_dt - start_dt).total_seconds() * 1000))


class HTTPClient:
    def __init__(self, token: str | None = None, timeout: int = 30) -> None:
        self.token = token
        self.timeout = timeout
        self.requests = 0

    def get(
        self, url: str, *, accept: str = "application/json", timeout: int | None = None
    ) -> bytes:
        headers = {
            "Accept": accept,
            "User-Agent": "ArchiveBox-CI-Evals/1.0",
            "X-GitHub-Api-Version": "2022-11-28",
        }
        if self.token and url.startswith(GITHUB_API):
            headers["Authorization"] = f"Bearer {self.token}"
        request = Request(url, headers=headers)
        self.requests += 1
        try:
            with build_opener(CrossOriginRedirect()).open(
                request, timeout=timeout or self.timeout
            ) as response:  # noqa: S310
                return response.read()
        except HTTPError as error:
            if "Authorization" not in headers or error.code not in {401, 403, 404}:
                raise
            # A repository-scoped Actions token can be narrower than anonymous
            # access to another public ArchiveBox repository. Retry public reads
            # without credentials; protected job logs still fail closed.
            headers.pop("Authorization")
            self.requests += 1
            with build_opener(CrossOriginRedirect()).open(
                Request(url, headers=headers), timeout=timeout or self.timeout
            ) as response:  # noqa: S310
                return response.read()

    def json(self, url: str) -> Any:
        return json.loads(self.get(url))


class CrossOriginRedirect(HTTPRedirectHandler):
    """Do not leak GitHub credentials to signed log-storage redirects."""

    def redirect_request(
        self, request: Request, fp: Any, code: int, msg: str, headers: Any, newurl: str
    ) -> Request | None:
        redirected = super().redirect_request(request, fp, code, msg, headers, newurl)
        if redirected and urlsplit(request.full_url).netloc != urlsplit(newurl).netloc:
            redirected.remove_header("Authorization")
        return redirected


def clean_log(text: str) -> list[str]:
    lines = []
    for raw in text.splitlines():
        line = ANSI_RE.sub("", TIMESTAMP_RE.sub("", raw.strip())).strip()
        if line:
            lines.append(line)
    return lines


def parse_test_log(text: str) -> dict[str, Any]:
    """Extract conservative test metrics from pytest/Rust/Go/JS log output."""
    counts: defaultdict[str, int] = defaultdict(int)
    suite_seconds = 0.0
    slowest: dict[str, Any] | None = None
    relevant: list[str] = []
    seen_go: set[tuple[str, str]] = set()

    for line in clean_log(text):
        duration_match = DURATION_RE.match(line)
        if duration_match:
            test_seconds = float(duration_match.group(1))
            candidate = {
                "name": duration_match.group(2),
                "duration_ms": round(test_seconds * 1000),
            }
            if slowest is None or candidate["duration_ms"] > slowest["duration_ms"]:
                slowest = candidate
            relevant.append(line)

        rust_match = RUST_SUMMARY_RE.search(line)
        if rust_match:
            counts["passed"] += int(rust_match.group(1))
            counts["failed"] += int(rust_match.group(2))
            suite_seconds += float(rust_match.group(3))
            relevant.append(line)
            continue

        pytest_match = PYTEST_SUMMARY_RE.search(line)
        if pytest_match and COUNT_RE.search(pytest_match.group("body")):
            for amount, status in COUNT_RE.findall(pytest_match.group("body")):
                counts[
                    "error" if status.lower().startswith("error") else status.lower()
                ] += int(amount)
            elapsed = re.search(r"\bin\s+(\d+(?:\.\d+)?)s\b", line)
            if elapsed:
                suite_seconds += float(elapsed.group(1))
            relevant.append(line)
            continue

        if line.startswith(("--- PASS:", "--- FAIL:")):
            status = "passed" if line.startswith("--- PASS:") else "failed"
            name = line.split(":", 1)[1].strip().split()[0]
            key = (status, name)
            if key not in seen_go:
                counts[status] += 1
                seen_go.add(key)
            relevant.append(line)
            continue

        if "Tests" in line and ("passed" in line or "failed" in line):
            js_match = JS_SUMMARY_RE.search(line)
            if js_match and any(js_match.groups()):
                counts["failed"] += int(js_match.group(1) or 0)
                counts["passed"] += int(js_match.group(2) or 0)
                relevant.append(line)

        ttfi_match = TTFI_JSON_RE.search(line)
        if ttfi_match:
            try:
                event = json.loads(ttfi_match.group(1))
            except json.JSONDecodeError:
                event = {}
            if event.get("ttfi_ms") is not None:
                counts["_ttfi_ms"] = float(event["ttfi_ms"])
                relevant.append(line)
        else:
            ttfi_text_match = TTFI_TEXT_RE.search(line)
            if ttfi_text_match:
                counts["_ttfi_ms"] = float(ttfi_text_match.group(1))
                relevant.append(line)

    total = sum(
        counts[key]
        for key in ("passed", "failed", "error", "skipped", "xfailed", "xpassed")
    )
    result: dict[str, Any] = {
        "total": total or None,
        "passed": counts["passed"],
        "failed": counts["failed"],
        "skipped": counts["skipped"],
        "errors": counts["error"],
        "suite_duration_ms": round(suite_seconds * 1000) if suite_seconds else None,
        "slowest": slowest,
        "ttfi_ms": counts.get("_ttfi_ms"),
        "log_excerpt": relevant[-30:],
    }
    return result


def normalize_step(step: dict[str, Any]) -> dict[str, Any]:
    return {
        "name": step.get("name") or "step",
        "status": step.get("status"),
        "conclusion": step.get("conclusion"),
        "number": step.get("number"),
        "started_at": step.get("started_at"),
        "completed_at": step.get("completed_at"),
        "duration_ms": duration_ms(step.get("started_at"), step.get("completed_at")),
    }


def normalize_job(
    job: dict[str, Any], previous: dict[str, Any] | None = None
) -> dict[str, Any]:
    normalized = {
        "id": job["id"],
        "name": job.get("name") or "job",
        "status": job.get("status"),
        "conclusion": job.get("conclusion"),
        "started_at": job.get("started_at"),
        "completed_at": job.get("completed_at"),
        "duration_ms": duration_ms(job.get("started_at"), job.get("completed_at")),
        "url": job.get("html_url"),
        "runner": job.get("runner_name"),
        "labels": job.get("labels") or [],
        "steps": [normalize_step(step) for step in job.get("steps") or []],
        "tests": None,
        "ttfi_ms": None,
        "log_excerpt": [],
    }
    if previous:
        for key in (
            "tests",
            "ttfi_ms",
            "log_excerpt",
            "log_collected_at",
            "log_parser_version",
        ):
            if previous.get(key) is not None:
                normalized[key] = previous[key]
    return normalized


def likely_test_job(name_or_job: str | dict[str, Any]) -> bool:
    if isinstance(name_or_job, dict):
        name = name_or_job.get("name") or ""
        step_names = " ".join(
            step.get("name") or "" for step in name_or_job.get("steps") or []
        )
    else:
        name = name_or_job
        step_names = ""
    lowered = name.lower()
    discovery_job = lowered.startswith("discover ") or any(
        marker in lowered
        for marker in (
            " / discover test",
            " / discover every",
            " / discover python",
            " / find_",
        )
    )
    has_test_surface = bool(TEST_JOB_RE.search(f"{name} {step_names}"))
    return (
        has_test_surface
        and not discovery_job
        and not bool(NON_TEST_JOB_RE.search(name))
    )


def aggregate_run(run: dict[str, Any]) -> None:
    jobs = run.get("jobs") or (run.get("job_metrics") or {}).get("test_jobs") or []
    test_jobs = [
        job
        for job in jobs
        if job.get("log_parser_version") == LOG_PARSER_VERSION
        and (job.get("tests") or {}).get("total")
    ]
    total_tests = sum(job["tests"]["total"] for job in test_jobs)
    slowest_candidates = [
        job["tests"].get("slowest") for job in test_jobs if job["tests"].get("slowest")
    ]
    ttfi = [job.get("ttfi_ms") for job in jobs if job.get("ttfi_ms") is not None]
    docker_steps = [
        step["duration_ms"]
        for job in jobs
        for step in job.get("steps") or []
        if step.get("duration_ms") is not None
        and DOCKER_STEP_RE.search(step.get("name") or "")
    ]
    if test_jobs:
        run["tests"] = {
            "total": total_tests or None,
            "jobs_reported": len(test_jobs),
            "jobs_expected": sum(1 for job in jobs if likely_test_job(job)),
            "avg_duration_ms": round(run["duration_ms"] / total_tests)
            if total_tests and run.get("duration_ms")
            else None,
            "slowest": max(slowest_candidates, key=lambda item: item["duration_ms"])
            if slowest_candidates
            else None,
        }
    elif jobs:
        run["tests"] = {
            "total": None,
            "jobs_reported": 0,
            "jobs_expected": sum(1 for job in jobs if likely_test_job(job)),
            "avg_duration_ms": None,
            "slowest": None,
        }
    if ttfi:
        run["ttfi_ms"] = round(sum(ttfi) / len(ttfi), 2)
    if docker_steps:
        run["docker_build_ms"] = max(docker_steps)


def summarize_jobs(jobs: list[dict[str, Any]]) -> dict[str, Any]:
    """Keep regression-useful job timings after detailed job data is compacted."""
    timed = [job for job in jobs if job.get("duration_ms") is not None]
    top = sorted(timed, key=lambda job: job["duration_ms"], reverse=True)[:10]

    def compact(job: dict[str, Any]) -> dict[str, Any]:
        return {
            "id": job["id"],
            "name": job["name"],
            "duration_ms": job["duration_ms"],
            "conclusion": job.get("conclusion"),
            "url": job.get("url"),
        }

    def compact_test(job: dict[str, Any]) -> dict[str, Any]:
        summary = {
            "id": job["id"],
            "name": job["name"],
            "status": job.get("status"),
            "conclusion": job.get("conclusion"),
            "duration_ms": job.get("duration_ms"),
            "url": job.get("url"),
            "tests": job.get("tests"),
            "ttfi_ms": job.get("ttfi_ms"),
            "log_excerpt": job.get("log_excerpt") or [],
        }
        for key in ("log_collected_at", "log_parser_version"):
            if job.get(key) is not None:
                summary[key] = job[key]
        return summary

    test_candidates = sorted(
        (job for job in jobs if likely_test_job(job)),
        key=lambda job: job.get("duration_ms") or 0,
        reverse=True,
    )[:MAX_LOG_CANDIDATES_PER_RUN]
    return {
        "version": JOB_METRICS_VERSION,
        "count": len(jobs),
        "total_runner_ms": sum(job["duration_ms"] for job in timed),
        "slowest": compact(top[0]) if top else None,
        "top": [compact(job) for job in top],
        "test_jobs": [compact_test(job) for job in test_candidates],
        "collected_at": utc_now().isoformat(),
    }


def normalize_run(
    project: dict[str, Any], raw: dict[str, Any], jobs: list[dict[str, Any]]
) -> dict[str, Any]:
    started_at = raw.get("run_started_at") or raw.get("created_at")
    completed_at = max(
        (job.get("completed_at") or "" for job in jobs), default=""
    ) or raw.get("updated_at")
    pull_requests = raw.get("pull_requests") or []
    run = {
        "id": raw["id"],
        "project": project["slug"],
        "workflow": raw.get("name") or project["workflow"],
        "workflow_id": raw.get("workflow_id"),
        "run_number": raw.get("run_number"),
        "attempt": raw.get("run_attempt"),
        "event": raw.get("event"),
        "status": raw.get("status"),
        "conclusion": raw.get("conclusion"),
        "branch": raw.get("head_branch") or "(tag)",
        "title": raw.get("display_title")
        or raw.get("head_commit", {}).get("message")
        or raw.get("name"),
        "sha": raw.get("head_sha"),
        "pr_number": pull_requests[0].get("number") if pull_requests else None,
        "pr_url": pull_requests[0]
        .get("url", "")
        .replace("api.github.com/repos", "github.com")
        .replace("/pulls/", "/pull/")
        if pull_requests
        else None,
        "created_at": raw.get("created_at"),
        "started_at": started_at,
        "completed_at": completed_at,
        "duration_ms": duration_ms(started_at, completed_at),
        "url": raw.get("html_url"),
        "jobs": jobs,
    }
    aggregate_run(run)
    return run


def fetch_jobs(
    client: HTTPClient,
    project: dict[str, Any],
    run: dict[str, Any],
    previous: dict[str, Any] | None,
) -> list[dict[str, Any]]:
    previous_jobs = {job["id"]: job for job in (previous or {}).get("jobs") or []}
    jobs: list[dict[str, Any]] = []
    page = 1
    while True:
        url = f"{GITHUB_API}/repos/ArchiveBox/{project['repo']}/actions/runs/{run['id']}/jobs?per_page=100&page={page}"
        payload = client.json(url)
        batch = payload.get("jobs") or []
        jobs.extend(normalize_job(job, previous_jobs.get(job["id"])) for job in batch)
        if len(batch) < 100:
            break
        page += 1
    return jobs


def fetch_runs(
    client: HTTPClient,
    project: dict[str, Any],
    limit: int,
    previous_runs: dict[int, dict[str, Any]],
) -> list[dict[str, Any]]:
    raw_runs: list[dict[str, Any]] = []
    page = 1
    while len(raw_runs) < limit:
        url = (
            f"{GITHUB_API}/repos/ArchiveBox/{project['repo']}/actions/workflows/"
            f"{quote(project['workflow'])}/runs?per_page=100&page={page}"
        )
        batch = client.json(url).get("workflow_runs") or []
        raw_runs.extend(batch)
        if len(batch) < 100:
            break
        page += 1

    output = []
    for raw in raw_runs[:limit]:
        previous = previous_runs.get(raw["id"])
        if (
            previous
            and previous.get("status") == "completed"
            and raw.get("status") == "completed"
        ):
            output.append(previous)
            continue
        output.append(normalize_run(project, raw, []))
    return output


def collect_job_metadata(
    client: HTTPClient,
    runs: list[dict[str, Any]],
    budget: int,
) -> dict[str, int]:
    """Backfill every run's job timings without downloading or rerunning tests."""
    configs = {project["slug"]: project for project in PROJECTS}
    queues: dict[str, deque[dict[str, Any]]] = defaultdict(deque)
    for run in sorted(
        runs, key=lambda item: item.get("started_at") or "", reverse=True
    ):
        metrics = run.get("job_metrics") or {}
        if (
            run.get("status") != "completed"
            or metrics.get("version") != JOB_METRICS_VERSION
        ):
            queues[run["project"]].append(run)

    attempted = 0
    collected = 0
    while attempted < budget and any(queues.values()):
        for slug in [project["slug"] for project in PROJECTS]:
            if attempted >= budget or not queues[slug]:
                continue
            run = queues[slug].popleft()
            attempted += 1
            try:
                jobs = fetch_jobs(client, configs[slug], run, run)
            except (
                HTTPError,
                URLError,
                TimeoutError,
                IncompleteRead,
                json.JSONDecodeError,
            ):
                continue
            run["jobs"] = jobs
            run["job_metrics"] = summarize_jobs(jobs)
            completed_at = max(
                (job.get("completed_at") or "" for job in jobs), default=""
            )
            if completed_at:
                run["completed_at"] = completed_at
                run["duration_ms"] = duration_ms(run.get("started_at"), completed_at)
            aggregate_run(run)
            collected += 1

    return {
        "attempted": attempted,
        "collected": collected,
        "failed": attempted - collected,
        "remaining": sum(len(queue) for queue in queues.values()),
    }


def merge_history(
    fresh_runs: list[dict[str, Any]],
    previous_runs: list[dict[str, Any]],
    cutoff: datetime,
    detailed_per_project: int,
) -> list[dict[str, Any]]:
    merged = {
        int(run["id"]): run
        for run in previous_runs
        if (parse_time(run.get("started_at")) or cutoff) >= cutoff
    }
    merged.update(
        {
            int(run["id"]): run
            for run in fresh_runs
            if (parse_time(run.get("started_at")) or cutoff) >= cutoff
        }
    )
    grouped: defaultdict[str, list[dict[str, Any]]] = defaultdict(list)
    for run in merged.values():
        grouped[run["project"]].append(run)
    output: list[dict[str, Any]] = []
    for project_runs in grouped.values():
        project_runs.sort(key=lambda item: item.get("started_at") or "", reverse=True)
        for index, run in enumerate(project_runs):
            if index >= detailed_per_project:
                run = {**run, "jobs": []}
            output.append(run)
    output.sort(key=lambda item: item.get("started_at") or "", reverse=True)
    return output


def fetch_pypi(client: HTTPClient, project: dict[str, Any]) -> dict[str, Any]:
    package = project["pypi"]
    payload = client.json(f"https://pypi.org/pypi/{quote(package)}/json")
    latest = payload.get("info", {}).get("version")
    latest_files = payload.get("releases", {}).get(latest, [])
    wheels = [item for item in latest_files if item.get("packagetype") == "bdist_wheel"]
    release_history = []
    for version, files in payload.get("releases", {}).items():
        if not files:
            continue
        uploads = [
            item.get("upload_time_iso_8601")
            for item in files
            if item.get("upload_time_iso_8601")
        ]
        version_wheels = [
            item for item in files if item.get("packagetype") == "bdist_wheel"
        ]
        release_history.append(
            {
                "version": version,
                "uploaded_at": min(uploads) if uploads else None,
                "release_size_bytes": sum(item.get("size") or 0 for item in files),
                "wheel_size_bytes": max(
                    (item.get("size") or 0 for item in version_wheels), default=None
                ),
            }
        )
    release_history.sort(key=lambda item: item.get("uploaded_at") or "", reverse=True)
    return {
        "url": f"https://pypi.org/project/{package}/",
        "package": package,
        "version": latest,
        "wheel_size_bytes": max(
            (item.get("size") or 0 for item in wheels), default=None
        ),
        "release_size_bytes": sum(item.get("size") or 0 for item in latest_files)
        or None,
        "uploaded_at": min(
            (
                item.get("upload_time_iso_8601")
                for item in latest_files
                if item.get("upload_time_iso_8601")
            ),
            default=None,
        ),
        "releases": release_history[:100],
    }


def fetch_docker(client: HTTPClient, project: dict[str, Any]) -> dict[str, Any] | None:
    image = project.get("docker")
    if not image:
        return None
    payload = client.json(
        f"https://hub.docker.com/v2/repositories/archivebox/{quote(image)}/tags?page_size=100&ordering=-last_updated"
    )
    tags = []
    for tag in payload.get("results") or []:
        tags.append(
            {
                "name": tag.get("name"),
                "updated_at": tag.get("last_updated"),
                "compressed_size_bytes": tag.get("full_size"),
                "digest": tag.get("digest"),
                "architectures": [
                    {
                        "architecture": item.get("architecture"),
                        "os": item.get("os"),
                        "size_bytes": item.get("size"),
                    }
                    for item in tag.get("images") or []
                ],
            }
        )
    latest = next(
        (tag for tag in tags if tag["name"] in {"latest", "dev", "main"}),
        tags[0] if tags else None,
    )
    return {
        "url": f"https://hub.docker.com/r/archivebox/{image}/tags",
        "image": f"archivebox/{image}",
        "latest": latest,
        "tags": tags,
    }


def load_previous(path: Path | None) -> dict[str, Any]:
    if not path or not path.exists():
        return {}
    try:
        payload = json.loads(path.read_text())
    except (OSError, json.JSONDecodeError):
        return {}
    return payload if payload.get("schema_version") == SCHEMA_VERSION else {}


def collect_logs(
    client: HTTPClient,
    runs: list[dict[str, Any]],
    budget: int,
) -> dict[str, int]:
    queues: dict[str, deque[tuple[dict[str, Any], dict[str, Any]]]] = defaultdict(deque)
    for run in sorted(
        runs, key=lambda item: item.get("started_at") or "", reverse=True
    ):
        jobs = run.get("jobs") or (run.get("job_metrics") or {}).get("test_jobs") or []
        for job in jobs:
            if (
                (
                    job.get("tests") is None
                    or job.get("log_parser_version") != LOG_PARSER_VERSION
                )
                and likely_test_job(job)
                and job.get("status") == "completed"
            ):
                queues[run["project"]].append((run, job))

    attempted = 0
    collected = 0
    while attempted < budget and any(queues.values()):
        for slug in [project["slug"] for project in PROJECTS]:
            if attempted >= budget or not queues[slug]:
                continue
            run, job = queues[slug].popleft()
            attempted += 1
            try:
                raw = client.get(
                    f"{GITHUB_API}/repos/ArchiveBox/{next(p['repo'] for p in PROJECTS if p['slug'] == slug)}/actions/jobs/{job['id']}/logs",
                    accept="application/vnd.github+json",
                    timeout=10,
                )
                parsed = parse_test_log(raw.decode("utf-8", errors="replace"))
            except (HTTPError, URLError, TimeoutError, IncompleteRead) as error:
                job["log_error"] = (
                    f"{type(error).__name__}: {getattr(error, 'code', '')}".strip()
                )
                continue
            job["tests"] = {
                key: value
                for key, value in parsed.items()
                if key not in {"ttfi_ms", "log_excerpt"}
            }
            job["ttfi_ms"] = parsed["ttfi_ms"]
            job["log_excerpt"] = parsed["log_excerpt"]
            job["log_collected_at"] = utc_now().isoformat()
            job["log_parser_version"] = LOG_PARSER_VERSION
            collected += 1
            aggregate_run(run)
    for run in runs:
        jobs = run.get("jobs") or (run.get("job_metrics") or {}).get("test_jobs") or []
        for job in jobs:
            job.pop("log_error", None)
    return {
        "attempted": attempted,
        "collected": collected,
        "failed": attempted - collected,
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--output", type=Path, default=Path(__file__).with_name("site") / "data.json"
    )
    parser.add_argument("--previous", type=Path)
    parser.add_argument("--runs-per-project", type=int, default=200)
    parser.add_argument("--detailed-runs-per-project", type=int, default=4)
    parser.add_argument("--history-days", type=int, default=90)
    parser.add_argument("--job-metadata-budget", type=int, default=20)
    parser.add_argument("--log-budget", type=int, default=60)
    args = parser.parse_args(argv)

    token = os.environ.get("GH_TOKEN") or os.environ.get("GITHUB_TOKEN")
    client = HTTPClient(token=token)
    previous = load_previous(args.previous)
    previous_runs = {int(run["id"]): run for run in previous.get("runs") or []}
    project_records: list[dict[str, Any]] = []
    runs: list[dict[str, Any]] = []
    errors: list[dict[str, str]] = []

    for config in PROJECTS:
        record = {key: value for key, value in config.items() if key != "workflow"}
        record["repo_url"] = f"https://github.com/ArchiveBox/{config['repo']}"
        record["workflow_url"] = (
            f"{record['repo_url']}/actions/workflows/{config['workflow']}"
        )
        try:
            record["pypi"] = fetch_pypi(client, config)
        except (
            HTTPError,
            URLError,
            TimeoutError,
            IncompleteRead,
            json.JSONDecodeError,
        ) as error:
            record["pypi"] = next(
                (
                    item.get("pypi")
                    for item in previous.get("projects", [])
                    if item.get("slug") == config["slug"]
                ),
                None,
            )
            errors.append(
                {"project": config["slug"], "source": "pypi", "message": str(error)}
            )
        try:
            record["docker"] = fetch_docker(client, config)
        except (
            HTTPError,
            URLError,
            TimeoutError,
            IncompleteRead,
            json.JSONDecodeError,
        ) as error:
            record["docker"] = next(
                (
                    item.get("docker")
                    for item in previous.get("projects", [])
                    if item.get("slug") == config["slug"]
                ),
                None,
            )
            errors.append(
                {"project": config["slug"], "source": "docker", "message": str(error)}
            )
        try:
            runs.extend(
                fetch_runs(
                    client,
                    config,
                    args.runs_per_project,
                    previous_runs,
                )
            )
        except (
            HTTPError,
            URLError,
            TimeoutError,
            IncompleteRead,
            json.JSONDecodeError,
        ) as error:
            runs.extend(
                run
                for run in previous.get("runs", [])
                if run.get("project") == config["slug"]
            )
            errors.append(
                {"project": config["slug"], "source": "github", "message": str(error)}
            )
        project_records.append(record)

    cutoff = utc_now() - timedelta(days=args.history_days)
    runs = merge_history(
        runs, previous.get("runs") or [], cutoff, args.detailed_runs_per_project
    )
    job_stats = collect_job_metadata(client, runs, max(0, args.job_metadata_budget))
    log_stats = collect_logs(client, runs, max(0, args.log_budget))
    for run in runs:
        if run.get("jobs"):
            run["job_metrics"] = summarize_jobs(run["jobs"])
            aggregate_run(run)
    runs = merge_history(runs, [], cutoff, args.detailed_runs_per_project)

    payload = {
        "schema_version": SCHEMA_VERSION,
        "generated_at": utc_now().isoformat(),
        "history_days": args.history_days,
        "source": "GitHub Actions + PyPI + Docker Hub",
        "projects": project_records,
        "runs": runs,
        "collection": {
            "http_requests": client.requests,
            "job_metadata": job_stats,
            "logs": log_stats,
            "errors": errors,
        },
    }
    args.output.parent.mkdir(parents=True, exist_ok=True)
    temporary = args.output.with_suffix(args.output.suffix + ".tmp")
    temporary.write_text(json.dumps(payload, indent=2, sort_keys=False) + "\n")
    temporary.replace(args.output)
    print(
        f"Wrote {len(runs)} runs / {sum(len(run.get('jobs') or []) for run in runs)} jobs "
        f"to {args.output} ({client.requests} requests, "
        f"{job_stats['collected']}/{job_stats['attempted']} job lists, "
        f"{log_stats['collected']}/{log_stats['attempted']} logs)"
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
