from datetime import UTC, datetime

from ..collect import duration_ms, likely_test_job, merge_history, parse_test_log
from ..measure_import import measure


def test_parse_pytest_counts_duration_and_slowest() -> None:
    result = parse_test_log(
        """
        2026-08-28T00:00:00Z 2.41s call tests/test_cli.py::test_add
        2026-08-28T00:00:01Z 0.10s call tests/test_cli.py::test_help
        ================= 12 passed, 2 skipped, 1 xfailed in 4.25s =================
        ABX_EVALS {"ttfi_ms": 18.75}
        """
    )

    assert result["total"] == 15
    assert result["passed"] == 12
    assert result["skipped"] == 2
    assert result["suite_duration_ms"] == 4250
    assert result["slowest"] == {
        "name": "tests/test_cli.py::test_add",
        "duration_ms": 2410,
    }
    assert result["ttfi_ms"] == 18.75


def test_parse_rust_and_go_without_double_counting_go_lines() -> None:
    result = parse_test_log(
        """
        test result: ok. 8 passed; 1 failed; 0 ignored; finished in 0.42s
        --- PASS: TestPublish (0.01s)
        --- PASS: TestPublish (0.01s)
        --- FAIL: TestTimeout (0.02s)
        """
    )

    assert result["total"] == 11
    assert result["passed"] == 9
    assert result["failed"] == 2


def test_test_job_filter_excludes_discovery_and_build_jobs() -> None:
    assert likely_test_job("Discovered test matrix / main/test_cli_add")
    assert likely_test_job("python / tests_api")
    assert not likely_test_job("Discover every test")
    assert not likely_test_job("Docker build and test / build linux/amd64")


def test_duration_ms_accepts_github_timestamps() -> None:
    assert duration_ms("2026-08-28T00:00:00Z", "2026-08-28T00:01:01.250Z") == 61250


def test_measure_import_reports_real_module_version() -> None:
    result = measure("json")

    assert result["package"] == "json"
    assert result["version"] == "2.0.9"
    assert isinstance(result["ttfi_ms"], float)


def test_merge_history_keeps_old_summaries_but_compacts_jobs() -> None:
    fresh = [
        {
            "id": 2,
            "project": "abxbus",
            "started_at": "2026-08-28T00:00:00Z",
            "jobs": [{"id": 20}],
        }
    ]
    previous = [
        {
            "id": 1,
            "project": "abxbus",
            "started_at": "2026-08-27T00:00:00Z",
            "jobs": [{"id": 10}],
            "tests": {"total": 5},
        }
    ]

    merged = merge_history(
        fresh, previous, datetime(2026, 8, 1, tzinfo=UTC), detailed_per_project=1
    )

    assert [run["id"] for run in merged] == [2, 1]
    assert merged[0]["jobs"] == [{"id": 20}]
    assert merged[1]["jobs"] == []
    assert merged[1]["tests"]["total"] == 5
