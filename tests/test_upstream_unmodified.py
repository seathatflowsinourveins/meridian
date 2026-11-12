"""The vendored NautilusTrader example files are byte-for-byte what upstream ships."""

import hashlib
import os
import subprocess
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parent.parent
VENDORED = "upstream/nautilus_trader/v2.0.0rc9/examples/live/interactive_brokers"

# Git blob ids of these files at tag v2.0.0rc9
# (commit da6b57aefdd62b44f675e434ffcfefca7f4025dd), as listed in UPSTREAM.md.
UPSTREAM_BLOBS = {
    f"{VENDORED}/_common.py": "c3ce3319514926dbbe29d46dd458168dfd385d79",
    f"{VENDORED}/ib_v2_order_strategies.py": "80c8bcca0eca0ea2b76714c3af67a2406d6c4885",
}


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
    assert listed == sorted(UPSTREAM_BLOBS)
