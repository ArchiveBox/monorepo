import importlib.util
import sys
from pathlib import Path

import pytest


PATH = Path(__file__).with_name("prepare_release_version.py")
SPEC = importlib.util.spec_from_file_location("prepare_release_version", PATH)
MODULE = importlib.util.module_from_spec(SPEC)
assert SPEC.loader
sys.modules[SPEC.name] = MODULE
SPEC.loader.exec_module(MODULE)


@pytest.mark.parametrize(
    ("version", "scheme", "expected"),
    [("1.2.3", "patch", "1.2.4"), ("1.2.3rc9", "rc", "1.2.3rc10")],
)
def test_increment(version, scheme, expected):
    assert MODULE.increment(version, scheme) == expected


def test_stable_release_target_selects_requested_version_without_regression():
    assert MODULE.apply_version_floor("0.9.36", "0.9.40", "patch") == "0.9.40"
    assert MODULE.apply_version_floor("0.9.41", "0.9.40", "patch") == "0.9.41"
    assert MODULE.apply_version_floor("0.9.36", "", "patch") == "0.9.36"
    with pytest.raises(ValueError, match="stable release target"):
        MODULE.apply_version_floor("0.9.36", "0.9.40rc1", "patch")


def test_next_rc_cycle_moves_past_published_stable():
    assert MODULE.next_rc_after_stable("0.9.35rc657", "0.9.36") == "0.9.37rc1"


def test_next_rc_cycle_starts_after_matching_stable_source():
    assert MODULE.next_rc_after_stable("0.9.36", "0.9.36") == "0.9.37rc1"


def test_next_rc_cycle_keeps_rc_when_stable_has_not_passed_it():
    assert MODULE.next_rc_after_stable("0.9.37rc1", "0.9.36") is None


def test_unreleased_version_is_reserved_without_bump():
    assert MODULE.classify("head", MODULE.VersionState()) == "reserve"


def test_candidate_owned_by_head_is_ready():
    assert MODULE.classify("head", MODULE.VersionState(candidate_owner="head")) == "ready"


def test_candidate_owned_by_older_commit_is_occupied():
    assert MODULE.classify("head", MODULE.VersionState(candidate_owner="old")) == "occupied"


def test_registry_version_without_tag_is_occupied():
    assert MODULE.classify("head", MODULE.VersionState(registry_exists=True)) == "occupied"


def test_registry_check_uses_exact_version_json():
    url = MODULE.registry_url("abx-plugins", "1.12.181")
    assert url.startswith("https://pypi.org/pypi/abx-plugins/1.12.181/json?cache_bust=")
    assert "/simple/" not in url


def test_release_tag_on_head_can_be_adopted():
    assert MODULE.classify("head", MODULE.VersionState(release_owner="head", registry_exists=True)) == "reserve"


def test_conflicting_candidate_and_release_owners_fail_closed():
    with pytest.raises(ValueError, match="different commits"):
        MODULE.classify("head", MODULE.VersionState(candidate_owner="one", release_owner="two"))


def test_cascade_leaves_version_selection_to_the_consumer():
    workflow = (PATH.parents[2] / "workflows" / "cascade-release.yml").read_text()
    graph = (PATH.parents[2] / "release-graph.toml").read_text()
    assert "NEXT_VERSION" not in workflow
    assert "bump_version.sh" not in workflow
    assert "version_scheme" not in graph
    assert "time.sleep" not in workflow
    assert "pypi.org/pypi" not in workflow
    assert "actions/download-artifact" in workflow
    assert "blake2b" in workflow


def test_cascade_updates_package_locks_without_rewriting_floating_install_defaults():
    workflow = (PATH.parents[2] / "workflows" / "cascade-release.yml").read_text()

    assert 'LOCK_ARGS=(uv lock --no-cache --no-sources --find-links "$WHEEL_DIR")' in workflow
    assert '--upgrade-package "$requirement"' in workflow
    assert "dockerfile_path.write_text" not in workflow
    assert "setup_path.write_text" not in workflow
