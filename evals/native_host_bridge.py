"""Evaluation compatibility adapter; complete synthetic traces are explicit.

The shipped implementation defaults to hashed receipts. This evaluation-only
adapter opts into payload records for actual-read coverage and frozen scoring.
It does not start a model or broaden the tool file roots.
"""
from tools.host_bridge import (BridgeError, HostToolBridge, MAX_FILE, MAX_SEGMENT,
    READ_RESPONSE_BUDGET, MAX_LINES, WRITABLE, READABLE, dynamic_tools,
    _regular_chain, _sha, _require)


class NativeHostBridge(HostToolBridge):
    def __init__(self, package, workspace, control, expected_manifest_sha256, *, max_calls=120, image_views=()):
        super().__init__(package, workspace, control, expected_manifest_sha256,
                         max_calls=max_calls, image_views=image_views, record_payloads=True)
