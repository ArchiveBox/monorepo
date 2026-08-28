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


def test_unreleased_version_is_reserved_without_bump():
    assert MODULE.classify("head", MODULE.VersionState()) == "reserve"


def test_candidate_owned_by_head_is_ready():
    assert MODULE.classify("head", MODULE.VersionState(candidate_owner="head")) == "ready"


def test_candidate_owned_by_older_commit_is_occupied():
    assert MODULE.classify("head", MODULE.VersionState(candidate_owner="old")) == "occupied"


def test_registry_version_without_tag_is_occupied():
    assert MODULE.classify("head", MODULE.VersionState(registry_exists=True)) == "occupied"


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
