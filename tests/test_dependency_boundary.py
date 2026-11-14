"""Keep test/research imports out of every production module, including lanes."""

import ast
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
RESEARCH_MODULES = {
    "hypothesis",
    "time_machine",
    "polars",
    "plotly",
    "openbb",
    "edgar",
    "financedatabase",
    "vectorbt",
    "skfolio",
    "ml4t",
    "pandera",
    "exchange_calendars",
}


def forbidden_imports(source: str) -> set[str]:
    modules = set()
    for node in ast.walk(ast.parse(source)):
        if isinstance(node, ast.Import):
            modules.update(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module:
            modules.add(node.module)
        elif isinstance(node, ast.Call):
            # Include literal dynamic imports, also when importlib is aliased.
            name = getattr(node.func, "attr", getattr(node.func, "id", ""))
            if name in {"import_module", "__import__"} and node.args:
                arg = node.args[0]
                if isinstance(arg, ast.Constant) and isinstance(arg.value, str):
                    modules.add(arg.value)
    return {
        name
        for name in modules
        if name.split(".")[0] in RESEARCH_MODULES or name.startswith("openbb_")
    }


def test_production_modules_do_not_import_test_or_research_dependencies():
    violations = {
        str(path.relative_to(ROOT)): found
        for path in (ROOT / "meridian").rglob("*.py")
        if (found := forbidden_imports(path.read_text()))
    }
    assert violations == {}


@pytest.mark.parametrize("module", sorted(RESEARCH_MODULES | {"openbb_core"}))
@pytest.mark.parametrize(
    "statement",
    [
        "import {module}",
        "from {module}.submodule import thing",
        'importlib.import_module("{module}")',
        '__import__("{module}")',
    ],
)
def test_import_guard_catches_each_dependency(module, statement):
    assert forbidden_imports(statement.format(module=module))
