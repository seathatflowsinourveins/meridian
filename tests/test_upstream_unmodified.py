"""The vendored NautilusTrader example files are byte-for-byte what upstream ships."""

import hashlib
import os
import subprocess
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parent.parent
TAG_DIR = "upstream/nautilus_trader/v2.0.0rc9"
VENDORED = f"{TAG_DIR}/examples/live/interactive_brokers"

# Git blob ids, as listed in UPSTREAM.md: the two example files and NautilusTrader's LICENSE at
# tag v2.0.0rc9 (commit da6b57aefdd62b44f675e434ffcfefca7f4025dd), and the GPL-3.0 text from
# gnu.org that the LGPL builds on.
UPSTREAM_BLOBS = {
    f"{VENDORED}/_common.py": "c3ce3319514926dbbe29d46dd458168dfd385d79",
    f"{VENDORED}/ib_v2_order_strategies.py": "80c8bcca0eca0ea2b76714c3af67a2406d6c4885",
    f"{TAG_DIR}/LICENSE": "5550e2db15f239ea8d3cf54bfa3b035eab8d3174",
    f"{TAG_DIR}/COPYING": "f288702d2fa16d3cdf0035b15a9fcbc552cd88e7",
}
# Written here, not copied: names the source, version and licence of the files above.
OWN_FILES = {f"{TAG_DIR}/NOTICE.md"}


def git_blob_id(data: bytes) -> str:
    return hashlib.sha1(b"blob %d\0" % len(data) + data, usedforsecurity=False).hexdigest()


@pytest.mark.parametrize("name", sorted(UPSTREAM_BLOBS))
def test_vendored_file_matches_upstream(name):
    assert git_blob_id((REPO_ROOT / name).read_bytes()) == UPSTREAM_BLOBS[name]


def test_nothing_else_is_under_upstream():
    # Everything git can see under upstream/, at any depth (ignored caches are not listed).
    out = subprocess.run(
        ["git", "ls-files", "-z", "--cached", "--others", "--exclude-standard", "--", "upstream"],
        cwd=REPO_ROOT,
        check=True,
        capture_output=True,
    ).stdout
    listed = sorted(os.fsdecode(name) for name in out.split(b"\0") if name)
    assert listed == sorted(set(UPSTREAM_BLOBS) | OWN_FILES)


def test_the_notice_names_the_source_version_and_licence():
    text = (REPO_ROOT / TAG_DIR / "NOTICE.md").read_text(encoding="utf-8")
    for needed in ("v2.0.0rc9", "da6b57aefdd62b44f675e434ffcfefca7f4025dd", "LGPL-3.0-only"):
        assert needed in text
