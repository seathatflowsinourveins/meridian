"""Publish the completed watch report; invoked only by the default-branch workflow."""

import os
import re
import sys
from pathlib import Path

from deploy.landscape_watch import REPO, GitHub

TITLE = "Landscape watch"
LABEL = "landscape"


def publish(api: GitHub, repository: str, body: str) -> None:
    if not body.strip():
        return
    if re.fullmatch(REPO, repository) is None:
        raise ValueError("repository must be OWNER/REPO")
    prefix = f"repos/{repository}"
    labels = api.pages(f"{prefix}/labels")
    if not any(label["name"] == LABEL for label in labels):
        api.request(f"{prefix}/labels", "POST", {"name": LABEL, "color": "0e8a16"})
    issues = api.pages(f"{prefix}/issues?state=open")
    existing = next(
        (
            i
            for i in issues
            if i["title"] == TITLE
            and "pull_request" not in i
            and any(label["name"] == LABEL for label in i["labels"])
        ),
        None,
    )
    payload = {"title": TITLE, "body": body, "labels": [LABEL]}
    if existing is None:
        api.request(f"{prefix}/issues", "POST", payload)
    else:
        payload["labels"] = sorted({LABEL, *(label["name"] for label in existing["labels"])})
        api.request(f"{prefix}/issues/{existing['number']}", "PATCH", payload)


def main() -> None:
    publish(
        GitHub(), os.environ["GITHUB_REPOSITORY"], Path(sys.argv[1]).read_text(encoding="utf-8")
    )


if __name__ == "__main__":
    main()
