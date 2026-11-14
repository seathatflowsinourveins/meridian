"""Offline GitHub response shapes from the REST examples linked in UPSTREAM.md."""

import io
import json
import re
from datetime import date, timedelta
from email.message import Message
from typing import Any
from urllib.error import HTTPError, URLError

import pytest

from deploy import landscape_watch as watch
from deploy.landscape_issue import publish


@pytest.fixture(autouse=True)
def no_real_credentials(monkeypatch):
    monkeypatch.delenv("GITHUB_TOKEN", raising=False)
    monkeypatch.delenv("GH_TOKEN", raising=False)


TODAY = date(2026, 11, 13)
ENGINE = "nautechsystems/nautilus_trader"
ADAPTER = "alpacahq/alpaca-py"


def release(tag, when="2026-11-13T01:00:00Z", *, draft=False, prerelease=False):
    return {"tag_name": tag, "published_at": when, "draft": draft, "prerelease": prerelease}


def repository(name, pushed="2026-11-13T01:00:00Z", *, archived=False, private=False):
    return {"full_name": name, "pushed_at": pushed, "archived": archived, "private": private}


class FakeGitHub(watch.GitHub):
    def __init__(self, replies: dict[str, Any]):
        self.replies = replies
        self.calls: list[tuple[str, str, Any]] = []

    def request(self, path: str, method: str = "GET", payload: Any = None) -> Any:
        self.calls.append((method, path, payload))
        if method != "GET":
            return {}
        value = self.replies[path]
        if isinstance(value, Exception):
            raise value
        return value


@pytest.fixture
def root(tmp_path):
    data = tmp_path / "docs/adr/data"
    data.mkdir(parents=True)
    (data / "ecosystem-manifest.md").write_text(
        f"### Layer 1, engine\n| Job | Rests on | State |\n| Engine | `{ENGINE}` | in use |\n"
        f"| Adapter | [{ADAPTER}](https://github.com/{ADAPTER}) | add |\n"
        "## Placement of the starred repositories\n| `other/excluded` | excluded: no job |\n",
        encoding="utf-8",
    )
    (tmp_path / "docs/adr/README.md").write_text(
        "| ADR | Title | Status | Last checked | Revisit |\n"
        "| [0001](0001-sample.md) | example | deferred | 2026-11-01 | 2027-01-30 |\n",
        encoding="utf-8",
    )
    (tmp_path / "pyproject.toml").write_text(
        '[project]\ndependencies = ["nautilus_trader==2.0.0rc9", "alpaca-py==0.45.0"]\n',
        encoding="utf-8",
    )
    return tmp_path


@pytest.fixture
def api():
    return FakeGitHub(
        {
            f"repos/{ENGINE}": repository(ENGINE),
            f"repos/{ADAPTER}": repository(ADAPTER),
            f"repos/{ENGINE}/releases?per_page=100&page=1": [release("v2.0.0rc9", prerelease=True)],
            f"repos/{ADAPTER}/releases?per_page=100&page=1": [release("v0.45.0")],
            "users/owner/starred?per_page=100&page=1": [repository("OTHER/Excluded")],
        }
    )


def test_clean_report_is_empty_and_only_uses_get(root, api):
    assert watch.collect(root, "owner/project", TODAY, api) == ""
    assert all(method == "GET" and payload is None for method, _, payload in api.calls)
    assert not any("other/excluded" in path for _, path, _ in api.calls)


def test_each_finding_and_source_links(root, api):
    index = root / "docs/adr/README.md"
    index.write_text(index.read_text().replace("2027-01-30", "2026-11-13"))
    api.replies[f"repos/{ENGINE}"] = repository(ENGINE, "2026-09-14T01:00:00Z")
    api.replies[f"repos/{ADAPTER}"] = repository(ADAPTER, archived=True)
    api.replies[f"repos/{ENGINE}/releases?per_page=100&page=1"] = [
        release("v2.0.0rc8", prerelease=True),
        release("v2.0.0rc10", prerelease=True),
        release("v2.0.0"),
        release("v3.0.0", draft=True),
    ]
    api.replies[f"repos/{ADAPTER}/releases?per_page=100&page=1"] = [release("0.46.0")]
    api.replies["users/owner/starred?per_page=100&page=1"].extend(
        [
            repository("new/candidate"),
            repository("hidden/private", private=True),
        ]
    )
    report = watch.collect(root, "owner/project", TODAY, api)
    assert (
        "ADR [0001](https://github.com/owner/project/blob/HEAD/docs/adr/0001-sample.md): "
        "revisit 2026-11-13" in report
    )
    assert f"No push in 60 days: https://github.com/{ENGINE}" in report
    assert f"Archived: https://github.com/{ADAPTER}" in report
    assert "nautilus_trader==2.0.0rc9" in report
    assert "/releases/tag/v2.0.0rc10" in report
    assert "/releases/tag/v2.0.0." in report
    assert "alpaca-py==0.45.0" in report
    assert "/releases/tag/0.46.0" in report
    assert "v2.0.0rc8" not in report and "v3.0.0" not in report
    assert "Unplaced star: https://github.com/new/candidate" in report
    assert "hidden/private" not in report and "OTHER/Excluded" not in report


@pytest.mark.parametrize(("days", "due"), [(59, False), (60, True), (61, True)])
def test_quiet_boundary(root, api, days, due):
    api.replies[f"repos/{ENGINE}"]["pushed_at"] = str(TODAY - timedelta(days=days)) + "T00:00:00Z"
    assert ("No push in 60 days" in watch.collect(root, "owner/project", TODAY, api)) == due


def test_missing_push_is_visible(root, api):
    api.replies[f"repos/{ENGINE}"]["pushed_at"] = None
    assert "No recorded push" in watch.collect(root, "owner/project", TODAY, api)


def test_manifest_architecture_and_all_placements_count(root):
    architecture, placed, scope = watch.manifest(root)
    assert architecture == {ENGINE, ADAPTER}
    assert placed == {ENGINE, ADAPTER, "other/excluded"}
    assert scope == "Scope: docs/adr/data/ecosystem-manifest.md."


def test_missing_manifest_is_an_error(root):
    (root / "docs/adr/data/ecosystem-manifest.md").unlink()
    with pytest.raises(FileNotFoundError):
        watch.manifest(root)


def test_invalid_manifest_is_an_error(root):
    (root / "docs/adr/data/ecosystem-manifest.md").write_text("no architecture")
    with pytest.raises(ValueError, match="no architecture rows"):
        watch.manifest(root)


@pytest.mark.parametrize(
    "boundary",
    [
        "## Placement of the starred repositories",
        "## Appendix: other repositories",
        "| repository | group | in architecture | starred |",
    ],
)
def test_all_layer_states_watched_but_placement_and_appendix_excluded(root, boundary):
    (root / "docs/adr/data/ecosystem-manifest.md").write_text(
        "| `outside/layers` | source mention |\n"
        "### Layer 1, toolchain\n"
        "| Engineering | `nautechsystems/nautilus_engineering` | compare with ours, then an ADR |\n"
        "### Layer 2, research\n"
        "| Candidate | `example/candidate` | deferred pending evidence |\n"
        f"{boundary}\n| `other/excluded` | watch |\n"
        "### Layer 99, only mentioned in the appendix\n| `other/later` | add |\n"
    )
    architecture, placed, _ = watch.manifest(root)
    assert architecture == {"nautechsystems/nautilus_engineering", "example/candidate"}
    assert placed == architecture | {"outside/layers", "other/excluded", "other/later"}


def test_star_and_release_pagination(root, api):
    api.replies["users/owner/starred?per_page=100&page=1"] = [repository(ENGINE)] * 100
    api.replies["users/owner/starred?per_page=100&page=2"] = [repository("page/two")]
    api.replies[f"repos/{ENGINE}/releases?per_page=100&page=1"] = [release("v1.0.0")] * 100
    api.replies[f"repos/{ENGINE}/releases?per_page=100&page=2"] = [release("v2.0.0rc10")]
    report = watch.collect(root, "owner/project", TODAY, api)
    assert "page/two" in report and "v2.0.0rc10" in report


@pytest.mark.parametrize(
    ("older", "newer"),
    [
        ("v2.0.0rc9", "2.0.0-rc.10"),
        ("2.0.0rc10", "2.0.0"),
        ("0.9.0", "0.10.0"),
        ("2.0.0", "2.0.0.post1"),
        ("2.0.0a1", "2.0.0b1"),
    ],
)
def test_numeric_and_prerelease_order(older, newer):
    assert watch.version(older) < watch.version(newer)


def test_unknown_release_format_fails_instead_of_hiding_updates(root, api):
    api.replies[f"repos/{ENGINE}/releases?per_page=100&page=1"] = [release("unrecognized")]
    with pytest.raises(ValueError, match="unsupported release version"):
        watch.collect(root, "owner/project", TODAY, api)


def test_major_release_revisit_uses_last_checked_baseline(root, api):
    index = root / "docs/adr/README.md"
    index.write_text(index.read_text().replace("2027-01-30", f"on a new major release of {ENGINE}"))
    path = f"repos/{ENGINE}/releases?per_page=100&page=1"
    api.replies[path] = [release("v2.0.0", "2026-10-01T00:00:00Z"), release("v2.1.0")]
    assert watch.adr_findings(root, TODAY, api) == []
    api.replies[path].append(release("v3.0.0rc1", prerelease=True))
    assert watch.adr_findings(root, TODAY, api) == []
    api.replies[path].append(release("v3.0.0"))
    assert len(watch.adr_findings(root, TODAY, api)) == 1


def test_index_dates_are_backed_by_decisions_or_appended_revisits():
    for line in (watch.ROOT / "docs/adr/README.md").read_text().splitlines():
        if not line.startswith("| [00"):
            continue
        _, adr, _, _, checked, revisit, _ = [c.strip() for c in line.split("|")]
        path = adr.split("(")[1].removesuffix(")")
        opening = "\n".join((watch.ROOT / "docs/adr" / path).read_text().splitlines()[:4])
        decision = re.search(r"\d{4}-\d{2}-\d{2}", opening)
        assert decision is not None
        assert checked >= decision[0]
        if checked == decision[0]:
            assert date.fromisoformat(revisit) == date.fromisoformat(checked) + timedelta(days=90)
        else:
            history = watch.ROOT / "docs/adr/data" / f"{path[:4]}-revisits.md"
            assert checked in history.read_text()


@pytest.mark.parametrize("token_present", [False, True])
def test_transport_uses_get_and_optional_environment_auth(monkeypatch, token_present):
    monkeypatch.delenv("GITHUB_TOKEN", raising=False)
    monkeypatch.delenv("GH_TOKEN", raising=False)
    if token_present:
        monkeypatch.setenv("GITHUB_TOKEN", "test-placeholder")

    def open_fake(request, *, timeout):
        assert request.full_url == "https://api.github.com/repos/example/project"
        assert request.method == "GET" and request.data is None and timeout == 30
        assert bool(request.get_header("Authorization")) == token_present
        return io.BytesIO(json.dumps(repository("example/project")).encode())

    monkeypatch.setattr(watch, "urlopen", open_fake)
    assert watch.GitHub().get("repos/example/project")["full_name"] == "example/project"


@pytest.mark.parametrize(
    "error",
    [
        HTTPError("https://api.github.com/x", 403, "rate limited", Message(), None),
        HTTPError("https://api.github.com/x", 404, "missing", Message(), None),
        URLError("unavailable"),
    ],
)
def test_api_errors_are_explicit_and_never_emit_partial_findings(root, monkeypatch, capsys, error):
    def fail(*args, **kwargs):
        raise error

    monkeypatch.setattr(watch, "ROOT", root)
    monkeypatch.setattr(watch, "urlopen", fail)
    monkeypatch.setattr("sys.argv", ["watch", "--repository", "owner/project"])
    assert watch.main() == 1
    captured = capsys.readouterr()
    assert captured.out == ""
    assert "report incomplete" in captured.err


def test_publisher_does_nothing_without_findings():
    api = FakeGitHub({})
    publish(api, "owner/project", "\n")
    assert api.calls == []


def test_publisher_creates_label_and_one_issue():
    api = FakeGitHub(
        {
            "repos/owner/project/labels?per_page=100&page=1": [],
            "repos/owner/project/issues?state=open&per_page=100&page=1": [],
        }
    )
    publish(api, "owner/project", "findings")
    writes = [call for call in api.calls if call[0] != "GET"]
    assert writes == [
        ("POST", "repos/owner/project/labels", {"name": "landscape", "color": "0e8a16"}),
        (
            "POST",
            "repos/owner/project/issues",
            {
                "title": "Landscape watch",
                "body": "findings",
                "labels": ["landscape"],
            },
        ),
    ]


def test_publisher_finds_open_issue_on_second_page_ignores_pr_and_keeps_labels():
    api = FakeGitHub(
        {
            "repos/owner/project/labels?per_page=100&page=1": [{"name": "landscape"}],
            "repos/owner/project/issues?state=open&per_page=100&page=1": [
                {"title": "Landscape watch", "pull_request": {}}
            ]
            * 100,
            "repos/owner/project/issues?state=open&per_page=100&page=2": [
                {
                    "title": "Landscape watch",
                    "number": 7,
                    "labels": [{"name": "landscape"}, {"name": "triage"}],
                }
            ],
        }
    )
    publish(api, "owner/project", "updated findings")
    assert [call for call in api.calls if call[0] != "GET"] == [
        (
            "PATCH",
            "repos/owner/project/issues/7",
            {
                "title": "Landscape watch",
                "body": "updated findings",
                "labels": ["landscape", "triage"],
            },
        ),
    ]


def test_publisher_does_not_overwrite_an_unlabelled_title_match():
    api = FakeGitHub(
        {
            "repos/owner/project/labels?per_page=100&page=1": [{"name": "landscape"}],
            "repos/owner/project/issues?state=open&per_page=100&page=1": [
                {"title": "Landscape watch", "number": 6, "labels": [{"name": "triage"}]},
                {"title": "Different title", "number": 8, "labels": [{"name": "landscape"}]},
            ],
        }
    )
    publish(api, "owner/project", "findings")
    writes = [call for call in api.calls if call[0] != "GET"]
    assert len(writes) == 1
    assert writes[0][:2] == ("POST", "repos/owner/project/issues")
    api.replies["repos/owner/project/issues?state=open&per_page=100&page=1"].append(
        {
            "title": "Landscape watch",
            "number": 9,
            "labels": [{"name": "landscape"}],
        }
    )
    api.calls.clear()
    publish(api, "owner/project", "updated findings")
    writes = [call for call in api.calls if call[0] != "GET"]
    assert len(writes) == 1
    assert writes[0][:2] == ("PATCH", "repos/owner/project/issues/9")
