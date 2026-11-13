"""Write the two tool_suggest tool specs of Codex 0.167.2 (ListTool presentation) as Responses-API
function-tool JSON. Texts transcribed from codex-rs/core/src/tools/handlers/
list_available_plugins_to_install_spec.rs and request_plugin_install_spec.rs at ce21072.
Envelope ({"type":"function",...}) is the Responses API layout; key order follows the Rust structs.
Usage: py -3 -I tool_specs.py OUT_DIR
"""
import json
import sys
from pathlib import Path

LIST_DESC = (
    "# List plugin/connector install candidates\n\nUse this tool only when both are true:\n"
    "- The user explicitly asks to use a specific plugin or connector that is not already available "
    "in the current context or active `tools` list.\n- `tool_search` is not available, or it has "
    "already been called and did not find or make the requested tool callable.\n\nReturns known "
    "plugins and connectors that can be passed to `request_plugin_install`. When both a plugin and a "
    "connector match, prefer the plugin; use the connector only when its corresponding plugin is "
    "already installed.\n"
)
REQ_DESC = (
    "# Request plugin/connector install\n\nUse this tool only after `list_available_plugins_to_install` "
    "returns a plugin or connector that exactly matches the user's explicit request.\n\nDo not use it "
    "for adjacent capabilities, broad recommendations, or tools that merely seem useful. Pass the "
    "returned `tool_type` through directly, and pass the returned `id` as `tool_id`.\n\nIMPORTANT: DO "
    "NOT call this tool in parallel with other tools."
)
# BTreeMap -> keys sorted.
REQ_PROPS = {
    "action_type": {"type": "string", "description": "Suggested action for the tool. Use \"install\"."},
    "suggest_reason": {"type": "string", "description": "Concise one-line user-facing reason why this plugin or connector can help with the current request."},
    "tool_id": {"type": "string", "description": "Connector or plugin id to suggest."},
    "tool_type": {"type": "string", "description": "Type of discoverable tool to suggest. Use \"connector\" or \"plugin\"."},
}
REQ_REQUIRED = ["tool_type", "action_type", "tool_id", "suggest_reason"]


def main():
    out = Path(sys.argv[1])
    a = {"type": "function", "name": "list_available_plugins_to_install", "description": LIST_DESC,
         "strict": False, "parameters": {"type": "object", "properties": {}, "required": [], "additionalProperties": False}}
    b = {"type": "function", "name": "request_plugin_install", "description": REQ_DESC, "strict": False,
         "parameters": {"type": "object", "properties": REQ_PROPS, "required": REQ_REQUIRED, "additionalProperties": False}}
    (out / "tool-list_available_plugins_to_install.json").write_bytes(json.dumps(a).encode("utf-8"))
    (out / "tool-request_plugin_install-listtool.json").write_bytes(json.dumps(b).encode("utf-8"))


if __name__ == "__main__":
    main()
