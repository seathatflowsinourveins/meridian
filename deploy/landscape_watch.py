"""Read-only landscape report: python3 -m deploy.landscape_watch --repository OWNER/REPO.

Only GitHub REST GETs; no broker, dependency installation, or local writes. Empty stdout
means nothing is due; an incomplete read exits nonzero without publishing a partial report.
GITHUB_TOKEN (or GH_TOKEN) is optional. Sources and fallback scope: UPSTREAM.md.
"""

import argparse
import json
import os
import re
import sys
import tomllib
from datetime import UTC, date, datetime, timedelta
from pathlib import Path
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

ROOT = Path(__file__).resolve().parents[1]
# Plan section 3's currently used engine, adapter, toolchain, runtimes and review.
# Until the manifest lands, these are both the watched and the placed repositories.
FALLBACK = {
    "nautechsystems/nautilus_trader",
    "alpacahq/alpaca-py",
    "astral-sh/uv",
    "astral-sh/ruff",
    "microsoft/pyright",
    "pytest-dev/pytest",
    "gitleaks/gitleaks",
    "anthropics/claude-code",
    "openai/codex",
    "deepseek-ai/deepseek-harness",
    "stablyai/orca",
    "openai/codex-plugin-cc",
}
PACKAGES = {"nautechsystems/nautilus_trader": "nautilus_trader", "alpacahq/alpaca-py": "alpaca-py"}
REPO = r"[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+"
VERSION = re.compile(
    r"v?(\d+)\.(\d+)(?:\.(\d+))?(?:[-.]?(dev|a|alpha|b|beta|rc|post)[.-]?(\d+))?", re.I
)


class GitHub:
    """REST transport; reporting calls only get/pages, publishing is a separate command."""

    def request(self, path: str, method: str = "GET", payload: Any = None) -> Any:
        if not path.startswith(("repos/", "users/")) or ":" in path or ".." in path:
            raise ValueError("invalid GitHub API path")
        headers = {"Accept": "application/vnd.github+json", "X-GitHub-Api-Version": "2026-03-10"}
        token = os.environ.get("GITHUB_TOKEN") or os.environ.get("GH_TOKEN")
        if token:
            headers["Authorization"] = f"Bearer {token}"
        data = None if payload is None else json.dumps(payload).encode()
        if data is not None:
            headers["Content-Type"] = "application/json"
        request = Request(
            f"https://api.github.com/{path}", data=data, headers=headers, method=method
        )
        try:
            with urlopen(request, timeout=30) as response:
                return json.load(response)
        except HTTPError as exc:
            # Never print response bodies, request headers or environment values.
            raise RuntimeError(f"GitHub HTTP {exc.code}: {path}; report incomplete") from None
        except URLError, TimeoutError:
            raise RuntimeError(f"GitHub unavailable: {path}; report incomplete") from None

    def get(self, path: str) -> Any:
        return self.request(path)

    def pages(self, path: str) -> list[dict[str, Any]]:
        rows = []
        for page in range(1, 1001):
            separator = "&" if "?" in path else "?"
            batch = self.get(f"{path}{separator}per_page=100&page={page}")
            if not isinstance(batch, list):
                raise ValueError(f"expected GitHub list: {path}")
            rows.extend(batch)
            if len(batch) < 100:
                return rows
        raise ValueError(f"pagination did not end: {path}")


def repositories(text: str) -> set[str]:
    """Manifest repo cells may use backticks or GitHub links; ignore paths and prose."""
    names = re.findall(rf"`({REPO})`", text)
    names += re.findall(rf"https://github\.com/({REPO})(?=[/)#?\s]|$)", text)
    return {name.removesuffix(".git").lower() for name in names}


def manifest(root: Path) -> tuple[set[str], set[str], str]:
    path = root / "docs/adr/data/ecosystem-manifest.md"
    if not path.exists():
        names = {name.lower() for name in FALLBACK}
        return names, names, "Fallback scope (manifest absent): " + ", ".join(sorted(names)) + "."
    text = path.read_text(encoding="utf-8")
    # Architecture tables carry the plan's states. Appendix placements are still counted
    # as placed, but excluded/rejected repositories are not watched for maintenance.
    architecture = set()
    for line in text.splitlines():
        cells = [cell.strip().lower() for cell in line.split("|")]
        if line.startswith("|") and any(
            re.match(r"^(?:\*\*|`)?(?:in use|add|measure|watch)(?:\b)", cell) for cell in cells
        ):
            architecture.update(repositories(line))
    if not architecture:
        raise ValueError("manifest has no architecture rows with in use/add/measure/watch states")
    return architecture, repositories(text), "Scope: docs/adr/data/ecosystem-manifest.md."


def version(tag: str) -> tuple[int, ...]:
    match = VERSION.fullmatch(tag)
    if match is None:
        raise ValueError(f"unsupported release version: {tag}")
    major, minor, patch, stage, number = match.groups()
    ranks = {"dev": -4, "a": -3, "alpha": -3, "b": -2, "beta": -2, "rc": -1, "post": 1}
    return (
        int(major),
        int(minor),
        int(patch or 0),
        ranks.get((stage or "").lower(), 0),
        int(number or 0),
    )


def releases(api: GitHub, repo: str) -> list[dict[str, Any]]:
    return [row for row in api.pages(f"repos/{repo}/releases") if not row["draft"]]


def adr_findings(root: Path, today: date, api: GitHub) -> list[str]:
    findings = []
    for line in (root / "docs/adr/README.md").read_text(encoding="utf-8").splitlines():
        if not re.match(r"\| \[\d{4}\]", line):
            continue
        _, adr, _, _, checked, revisit, _ = [cell.strip() for cell in line.split("|")]
        last_checked = date.fromisoformat(checked)
        if re.match(r"\d{4}-\d{2}-\d{2}", revisit):
            if date.fromisoformat(revisit[:10]) <= today:
                findings.append(f"ADR {adr}: revisit {revisit}; last checked {checked}.")
        else:
            match = re.fullmatch(rf"on a new major release of ({REPO})", revisit)
            if match is None:
                raise ValueError(f"unsupported revisit trigger for {adr}")
            repo = match[1]
            published = [
                (version(r["tag_name"])[0], date.fromisoformat(r["published_at"][:10]))
                for r in releases(api, repo)
                if not r["prerelease"]
            ]
            prior = [major for major, when in published if when <= last_checked]
            if not prior:
                raise ValueError(f"no release baseline on {checked} for {repo}")
            if any(
                major > max(prior) and last_checked < when <= today for major, when in published
            ):
                findings.append(f"ADR {adr}: {revisit}; last checked {checked}.")
    return findings


def collect(root: Path, repository: str, today: date, api: GitHub) -> str:
    if re.fullmatch(REPO, repository) is None:
        raise ValueError("repository must be OWNER/REPO")
    architecture, placed, scope = manifest(root)
    findings = [
        re.sub(
            r"\((\d{4}-[^)]+)\)", rf"(https://github.com/{repository}/blob/HEAD/docs/adr/\1)", item
        )
        for item in adr_findings(root, today, api)
    ]
    for repo in sorted(architecture):
        info = api.get(f"repos/{repo}")
        if info["private"]:
            raise ValueError("manifest must contain public repositories only")
        if info["archived"]:
            findings.append(f"Archived: https://github.com/{repo}.")
        elif info["pushed_at"] is None:
            findings.append(f"No recorded push: https://github.com/{repo}.")
        elif date.fromisoformat(info["pushed_at"][:10]) <= today - timedelta(days=60):
            findings.append(
                f"No push in 60 days: https://github.com/{repo} (last {info['pushed_at'][:10]})."
            )
    config = tomllib.loads((root / "pyproject.toml").read_text(encoding="utf-8"))
    pins = dict(dep.split("==") for dep in config["project"]["dependencies"] if "==" in dep)
    for repo, package in PACKAGES.items():
        pin = pins[package]
        for release in releases(api, repo):
            tag = release["tag_name"]
            if version(tag) > version(pin):
                findings.append(
                    f"Release beyond {package}=={pin}: https://github.com/{repo}/releases/tag/{tag}."
                )
    for row in api.pages(f"users/{repository.split('/')[0]}/starred"):
        if not row["private"] and row["full_name"].lower() not in placed:
            findings.append(f"Unplaced star: https://github.com/{row['full_name']}.")
    if not findings:
        return ""
    return (
        f"Landscape watch — {today}\n\n{scope}\n\n"
        + "\n".join(f"- {item}" for item in findings)
        + "\n"
    )


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--repository", default=os.environ.get("GITHUB_REPOSITORY"))
    args = parser.parse_args()
    if not args.repository:
        parser.error("--repository OWNER/REPO or GITHUB_REPOSITORY is required")
    try:
        report = collect(ROOT, args.repository, datetime.now(UTC).date(), GitHub())
    except (RuntimeError, ValueError, KeyError, OSError) as exc:
        print(f"Landscape watch failed: {exc}", file=sys.stderr)
        return 1
    print(report, end="")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
