"""
Every committed run record has the format the handbook gives (docs/HANDBOOK.md, "Run records"):
named ``<milestone>-<lane>-<UTC stamp>-<mode>.json``; JSON with sorted keys, a two-space indent
and one trailing newline; the common fields; and a pass, since only a passing run is committed.
"""

import json
import re

import pytest
from test_paper_only import REPO_ROOT
from test_public_tree import tracked_files

NAME = re.compile(r"^evidence/(M\d+)-([a-z0-9]+(?:-[a-z0-9]+)*)-(\d{8}T\d{6}Z)-([a-z]+)\.json$")
COMMON = {
    "schema",
    "milestone",
    "lane",
    "mode",
    "result",
    "problems",
    "run_started_utc",
    "run_ended_utc",
}
RECORDS = sorted(n for n in tracked_files() if n.startswith("evidence/"))


def test_there_are_committed_records():
    assert RECORDS, "git reported no records; the checks below would pass without looking"


@pytest.mark.parametrize("name", RECORDS)
def test_a_committed_record_has_the_handbooks_format(name):
    named = NAME.match(name)
    assert named, f"{name}: not named <milestone>-<lane>-<UTC stamp>-<mode>.json"
    text = (REPO_ROOT / name).read_text(encoding="utf-8")
    data = json.loads(text)
    assert text == json.dumps(data, indent=2, sort_keys=True) + "\n"
    assert data.keys() >= COMMON, COMMON - data.keys()
    assert data["schema"] == "meridian.run-record/1"
    assert (data["milestone"], data["lane"], data["mode"]) == (
        named.group(1),
        named.group(2),
        named.group(4),
    )
    assert data["result"] == "pass" and data["problems"] == []
