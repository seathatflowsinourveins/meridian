"""Test ownership for rc9 nodes, including references retained by pytest tracebacks.

rc9 crates/live/src/node/mod.rs requires dropping even a disposed LiveNode.
A traceback can retain this proxy after teardown, but cannot retain its node.
"""

import gc
from typing import Any
from weakref import WeakSet

import pytest
from nautilus_trader.live import LiveNode, LiveNodeBuilder


class OwnedNode:
    def __init__(self, node: LiveNode):
        self._node: LiveNode | None = node

    def __getattr__(self, name: str) -> Any:
        if self._node is None:
            raise RuntimeError("test node already released")
        return getattr(self._node, name)

    def release(self) -> None:
        if self._node is not None:
            try:
                self._node.dispose()
            finally:
                self._node = None


@pytest.fixture
def live_nodes(monkeypatch):
    # Do not retain successful nodes: a test may build and drop several in turn.
    nodes: WeakSet[OwnedNode] = WeakSet()

    def own(build):
        def managed(*args, **kwargs):
            node = OwnedNode(build(*args, **kwargs))
            nodes.add(node)
            return node

        return managed

    monkeypatch.setattr(LiveNode, "build", own(LiveNode.build))
    monkeypatch.setattr(LiveNodeBuilder, "build", own(LiveNodeBuilder.build))
    yield
    try:
        for node in list(nodes):
            node.release()
    finally:
        nodes.clear()
        gc.collect()
