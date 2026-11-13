"""
ADR 0001: does semble beat ripgrep plus pyright on a fixed question set about this repo?

Run in the distro with the throwaway environment's Python (the ADR has the full commands):

    python -I 0001_measure.py check --repo REPO --corpus DIR
    python -I 0001_measure.py run --repo REPO --corpus DIR --work DIR --rg CLAUDE_BINARY \
        --pyright LANGSERVER --semble SEMBLE_CLI --out 0001-results.json

The protocol was fixed, with the questions and the plans, before either method ran.

- Corpus: the frozen commit's tracked files (`git archive`), checked blob by blob.
- Slot 1, ripgrep plus pyright: the plan's 1 to 3 searches with the ripgrep that Claude Code
  bundles (`--hidden`, as its Grep tool also searches hidden folders; `--sort path`). Each hit
  line belongs to a unit: the innermost Python def or class (ast), a bash function, else the
  paragraph of non-blank lines around it. Units are ranked by how many of the searches hit them,
  then by hit lines, then by first appearance. The plan's one pyright lookup (definition or
  references, through pyright's language server) goes first.
- Slot 2, semble: one `semble search` with the plan's query and content type, top 5.
- Also reported, not used for the decision: slot 1 in printed order, and semble with the
  question verbatim over all content.
- A result matches an answer when it is in the answer's file and its lines overlap the
  answer's span (slot 1: the unit's hit lines; semble: the chunk's lines).

Nothing here touches the network. Only semble's one-time model download does, and that call
is logged by an audit hook along with every file semble opens for writing.
"""

import argparse
import ast
import asyncio
import hashlib
import json
import os
import platform
import re
import statistics
import subprocess
import sys
import time
from dataclasses import dataclass
from importlib import metadata
from pathlib import Path
from urllib.parse import unquote, urlparse

HERE = Path(__file__).resolve().parent
QUESTIONS = HERE / "0001-questions.json"
PLANS = HERE / "0001-plans.json"
KS = (1, 3, 5)
TOP_K = 5
REPEATS = 3
BUILD_REPEATS = 5
MARGIN_AT_3 = 5  # the decision rule in the ADR, fixed before the run
MODEL = "minishlab/potion-code-16M-v2"
_BASH_FUNCTION = re.compile(r"^([A-Za-z_][A-Za-z0-9_]*)\(\)\s*\{")

# Logs network calls, process starts and every file opened for writing, in every Python
# process that semble starts. Written into the work folder at run time.
AUDIT_HOOK = """
import os, sys
_LOG = os.environ.get("ADR0001_AUDIT_LOG")
_FD = os.open(_LOG, os.O_WRONLY | os.O_APPEND | os.O_CREAT, 0o600) if _LOG else None
_WRITING = os.O_WRONLY | os.O_RDWR | os.O_CREAT | os.O_APPEND | os.O_TRUNC
_EVENTS = {"socket.getaddrinfo", "socket.connect", "socket.bind", "socket.sendto",
           "subprocess.Popen", "os.system", "os.posix_spawn", "os.exec", "os.fork",
           "os.mkdir", "os.rename", "os.remove", "os.rmdir", "os.symlink", "shutil.rmtree"}
def _hook(event, args):
    if _FD is None:
        return
    if event == "open":
        path, mode, flags = (list(args) + [None, None, None])[:3]
        wants = (isinstance(mode, str) and any(c in mode for c in "wax+")) or (
            isinstance(flags, int) and bool(flags & _WRITING))
        if not wants:
            return
        line = "open-write\\t" + str(path)
    elif event in _EVENTS:
        line = event + "\\t" + " ".join(repr(a)[:300] for a in args)
    else:
        return
    os.write(_FD, (str(os.getpid()) + "\\t" + line.replace("\\n", " ") + "\\n").encode())
sys.addaudithook(_hook)
"""


@dataclass(frozen=True)
class Span:
    start: int
    end: int
    name: str


def _statement_label(stmt: ast.stmt) -> str:
    if isinstance(stmt, ast.Assign):
        return ",".join(ast.unparse(t) for t in stmt.targets)
    if isinstance(stmt, ast.AnnAssign):
        return ast.unparse(stmt.target)
    if isinstance(stmt, ast.Import | ast.ImportFrom):
        return "import"
    if isinstance(stmt, ast.Expr) and isinstance(stmt.value, ast.Constant):
        return "docstring"
    return type(stmt).__name__.lower()


class FileIndex:
    """The units of one file: Python defs and classes, bash functions, else paragraphs."""

    def __init__(self, root: Path, rel: str) -> None:
        self.rel = rel
        self.lines = (root / rel).read_text(encoding="utf-8", errors="replace").splitlines()
        self.defs: list[Span] = []
        self.statements: list[Span] = []
        if rel.endswith(".py"):
            self._python()
        elif rel.endswith(".sh"):
            self._bash()

    def _python(self) -> None:
        tree = ast.parse("\n".join(self.lines) + "\n")

        def visit(node: ast.AST, prefix: str) -> None:
            for child in ast.iter_child_nodes(node):
                if isinstance(child, ast.FunctionDef | ast.AsyncFunctionDef | ast.ClassDef):
                    start = min([child.lineno, *(d.lineno for d in child.decorator_list)])
                    name = prefix + child.name
                    self.defs.append(Span(start, child.end_lineno or child.lineno, name))
                    visit(child, name + ".")
                else:
                    visit(child, prefix)

        visit(tree, "")
        for stmt in tree.body:
            decorators = getattr(stmt, "decorator_list", [])
            start = min([stmt.lineno, *(d.lineno for d in decorators)])
            end = stmt.end_lineno or stmt.lineno
            self.statements.append(Span(start, end, _statement_label(stmt)))

    def _bash(self) -> None:
        for number, line in enumerate(self.lines, start=1):
            found = _BASH_FUNCTION.match(line)
            if not found:
                continue
            end = number
            if not line.rstrip().endswith("}"):
                closing = [n for n in range(number + 1, len(self.lines) + 1) if self.line(n) == "}"]
                end = closing[0] if closing else number
            self.defs.append(Span(number, end, found.group(1)))

    def line(self, number: int) -> str:
        return self.lines[number - 1].rstrip() if 0 < number <= len(self.lines) else ""

    def unit(self, number: int) -> str:
        inside = [d for d in self.defs if d.start <= number <= d.end]
        if inside:
            return max(inside, key=lambda d: (d.start, -d.end)).name
        for stmt in self.statements:
            if stmt.start <= number <= stmt.end:
                return f"<module>:{stmt.name}"
        start = number
        while start > 1 and self.line(start - 1).strip():
            start -= 1
        return f"paragraph:{start}"

    def unit_span(self, number: int) -> tuple[int, int]:
        """First and last line of the unit that holds this line (the same rules as unit)."""
        inside = [d for d in self.defs if d.start <= number <= d.end]
        if inside:
            found = max(inside, key=lambda d: (d.start, -d.end))
            return found.start, found.end
        for stmt in self.statements:
            if stmt.start <= number <= stmt.end:
                return stmt.start, stmt.end
        start = end = number
        while start > 1 and self.line(start - 1).strip():
            start -= 1
        while end < len(self.lines) and self.line(end + 1).strip():
            end += 1
        return start, end

    def definition(self, name: str) -> Span | None:
        found = [d for d in self.defs if d.name == name]
        return found[0] if len(found) == 1 else None

    def span(self, answer: dict) -> tuple[int, int]:
        if "lines" in answer:
            first, last = answer["lines"]
            if answer["anchor"] not in self.line(first):
                raise SystemExit(f"{self.rel}:{first}: anchor {answer['anchor']!r} not found")
            return first, last
        found = [d for d in self.defs if d.name == answer["symbol"]]
        if len(found) != 1:
            raise SystemExit(f"{self.rel}: {answer['symbol']!r} defined {len(found)} times")
        return found[0].start, found[0].end


def git_blob(data: bytes) -> str:
    return hashlib.sha1(b"blob %d\0" % len(data) + data, usedforsecurity=False).hexdigest()


def corpus_files(repo: Path, commit: str, corpus: Path) -> list[str]:
    """The corpus must hold exactly the commit's tracked files, byte for byte."""
    listing = subprocess.run(
        ["git", "-C", str(repo), "ls-tree", "-r", "-z", commit], capture_output=True, check=True
    ).stdout
    expected: dict[str, str] = {}
    for entry in listing.split(b"\0"):
        if entry:
            meta, path = entry.split(b"\t", 1)
            expected[os.fsdecode(path)] = meta.split()[2].decode()
    found: dict[str, str] = {}
    for path in corpus.rglob("*"):
        if path.is_symlink() or not path.is_file():
            continue  # the .venv link for pyright, added after the export, is not searched
        found[path.relative_to(corpus).as_posix()] = git_blob(path.read_bytes())
    if found != expected:
        missing, extra = sorted(set(expected) - set(found)), sorted(set(found) - set(expected))
        changed = sorted(p for p in set(found) & set(expected) if found[p] != expected[p])
        raise SystemExit(f"corpus differs from {commit}: {missing=} {extra=} {changed=}")
    return sorted(expected)


def load_inputs() -> tuple[dict, dict[str, dict]]:
    questions = json.loads(QUESTIONS.read_text(encoding="utf-8"))
    plans = {p["id"]: p for p in json.loads(PLANS.read_text(encoding="utf-8"))["plans"]}
    ids = [q["id"] for q in questions["questions"]]
    if sorted(plans) != sorted(ids):
        raise SystemExit("the plans and the questions do not have the same ids")
    return questions, plans


def answer_spans(question: dict, indexes: dict[str, FileIndex]) -> list[tuple[str, int, int]]:
    return [(a["file"], *indexes[a["file"]].span(a)) for a in question["answers"]]


# --- slot 1: ripgrep plus pyright -------------------------------------------------------------


def run_rg(binary: str, corpus: Path, search: dict, env: dict[str, str]) -> tuple[list, float, str]:
    """Hits as (file, line, text), the time, and rg's error if any. Claude Code's binary runs
    ripgrep when it is started under the name rg."""
    command = [
        "rg",
        "--json",
        "--hidden",
        "--sort",
        "path",
        "--no-config",
        *search.get("flags", []),
    ]
    if search.get("glob"):
        command += ["-g", search["glob"]]
    command += ["-e", search["pattern"], "--", search.get("path") or "."]
    started = time.perf_counter()
    done = subprocess.run(
        command, executable=binary, cwd=corpus, env=env, capture_output=True, text=True, check=False
    )
    elapsed = time.perf_counter() - started
    error = done.stderr.strip().splitlines()[0] if done.returncode not in (0, 1) else ""
    hits = []
    for raw in done.stdout.splitlines():
        message = json.loads(raw)
        if message["type"] == "match":
            data = message["data"]
            rel = os.path.normpath(data["path"]["text"])
            hits.append((rel, data["line_number"], data["lines"]["text"].rstrip("\n")))
    return hits, elapsed, error


class LanguageServer:
    """A minimal LSP client for pyright's language server, over stdio."""

    def __init__(self, command: list[str], root: Path, env: dict[str, str]) -> None:
        self.root = root
        self._next = 0
        self._opened: set[str] = set()
        self._proc = subprocess.Popen(
            command,
            cwd=root,
            env=env,
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.DEVNULL,
        )
        uri = root.as_uri()
        self.request(
            "initialize",
            {
                "processId": os.getpid(),
                "rootUri": uri,
                "workspaceFolders": [{"uri": uri, "name": "corpus"}],
                "capabilities": {
                    "workspace": {"configuration": True, "workspaceFolders": True},
                    "textDocument": {"definition": {}, "references": {}},
                },
            },
        )
        self.notify("initialized", {})

    def _write(self, message: dict) -> None:
        body = json.dumps(message).encode("utf-8")
        stdin = self._proc.stdin
        assert stdin is not None
        stdin.write(b"Content-Length: %d\r\n\r\n" % len(body) + body)
        stdin.flush()

    def _read(self) -> dict:
        stdout = self._proc.stdout
        assert stdout is not None
        length = 0
        while True:
            header = stdout.readline()
            if not header:
                raise SystemExit("pyright's language server stopped")
            if not header.strip():
                break
            name, _, value = header.decode("ascii").partition(":")
            if name.strip().lower() == "content-length":
                length = int(value)
        return json.loads(stdout.read(length))

    def notify(self, method: str, params: dict) -> None:
        self._write({"jsonrpc": "2.0", "method": method, "params": params})

    def request(self, method: str, params: dict) -> object:
        self._next += 1
        wanted = self._next
        self._write({"jsonrpc": "2.0", "id": wanted, "method": method, "params": params})
        while True:
            message = self._read()
            if "method" in message and "id" in message:  # the server asks the client
                answer = None
                if message["method"] == "workspace/configuration":
                    answer = [{} for _ in message["params"]["items"]]
                self._write({"jsonrpc": "2.0", "id": message["id"], "result": answer})
            elif message.get("id") == wanted:
                if "error" in message:
                    raise SystemExit(f"{method}: {message['error']}")
                return message.get("result")

    def close(self) -> None:
        self.request("shutdown", {})
        self.notify("exit", {})
        self._proc.wait(timeout=30)

    def _open(self, rel: str) -> str:
        uri = (self.root / rel).as_uri()
        if rel not in self._opened:
            text = (self.root / rel).read_text(encoding="utf-8")
            document = {"uri": uri, "languageId": "python", "version": 1, "text": text}
            self.notify("textDocument/didOpen", {"textDocument": document})
            self._opened.add(rel)
        return uri

    def _locations(self, result: object) -> list[tuple[str, int]]:
        found = []
        for item in result if isinstance(result, list) else [result] if result else []:
            uri = item.get("uri") or item.get("targetUri")
            span = item.get("range") or item.get("targetSelectionRange")
            path = Path(unquote(urlparse(uri).path))
            if path.is_relative_to(self.root):
                found.append((path.relative_to(self.root).as_posix(), span["start"]["line"] + 1))
        return found

    def workspace_symbols(self, name: str) -> list[tuple[str, int, int]]:
        found = []
        result = self.request("workspace/symbol", {"query": name})
        for item in result if isinstance(result, list) else []:
            if item["name"] == name:
                for rel, line in self._locations(item["location"]):
                    found.append((rel, line, self.column(rel, line, name)))
        return sorted(set(found))

    def column(self, rel: str, line: int, name: str) -> int:
        text = (self.root / rel).read_text(encoding="utf-8").splitlines()[line - 1]
        found = re.search(rf"\b{re.escape(name)}\b", text)
        return found.start() if found else 0

    def at(self, method: str, rel: str, line: int, column: int) -> list[tuple[str, int]]:
        params: dict = {
            "textDocument": {"uri": self._open(rel)},
            "position": {"line": line - 1, "character": column},
        }
        if method == "textDocument/references":
            params["context"] = {"includeDeclaration": False}
        return self._locations(self.request(method, params))


def pyright_lookup(
    server: LanguageServer,
    lookup: dict | None,
    hits: list[tuple[str, int, str]],
    ranked: list[tuple[str, str]],
    indexes: dict[str, FileIndex],
) -> tuple[list[tuple[str, int]], float]:
    """The plan's one definition or references lookup, as an agent would make it."""
    if not lookup:
        return [], 0.0
    started = time.perf_counter()
    symbol, kind = lookup["symbol"], lookup["kind"]
    positions: list[tuple[str, int, int]] = []
    from_symbol_search = False
    if symbol == "@top":
        if ranked and ranked[0][0].endswith(".py"):
            rel, unit = ranked[0]
            span = indexes[rel].definition(unit)
            if span is not None:
                name = unit.rsplit(".", 1)[-1]
                pattern = re.compile(rf"\b(?:def|class)\s+{re.escape(name)}\b")
                for number in range(span.start, span.end + 1):
                    if pattern.search(indexes[rel].line(number)):
                        positions = [(rel, number, server.column(rel, number, name))]
                        break
    else:
        positions = server.workspace_symbols(symbol)
        from_symbol_search = bool(positions)
        if not positions:  # not a workspace symbol: start from a place the searches showed
            for rel, number, text in hits:
                found = re.search(rf"\b{re.escape(symbol)}\b", text)
                if found and rel.endswith(".py"):
                    positions = [(rel, number, found.start())]
                    break
    locations: list[tuple[str, int]] = []
    for rel, number, column in positions:
        if kind == "definition" and from_symbol_search:
            locations.append((rel, number))
        elif kind == "definition":
            locations += server.at("textDocument/definition", rel, number, column)
        else:
            locations += server.at("textDocument/references", rel, number, column)
    return sorted(set(locations)), time.perf_counter() - started


@dataclass
class Unit:
    file: str
    name: str
    lines: list[int]
    searches: set[int]
    first: int


def rank_slot1(
    hits_per_search: list[list[tuple[str, int, str]]], indexes: dict[str, FileIndex]
) -> tuple[list[Unit], list[Unit]]:
    """Units ranked by searches that hit them, then hit lines, then first appearance."""
    units: dict[tuple[str, str], Unit] = {}
    seen = 0
    for search_number, hits in enumerate(hits_per_search):
        for rel, number, _ in hits:
            key = (rel, indexes[rel].unit(number))
            if key not in units:
                units[key] = Unit(rel, key[1], [], set(), seen)
                seen += 1
            units[key].lines.append(number)
            units[key].searches.add(search_number)
    ranked = sorted(units.values(), key=lambda u: (-len(u.searches), -len(u.lines), u.first))
    printed = sorted(units.values(), key=lambda u: u.first)
    return ranked, printed


def with_lookup_first(
    units: list[Unit], locations: list[tuple[str, int]], indexes: dict[str, FileIndex]
) -> list[Unit]:
    first: dict[tuple[str, str], Unit] = {}
    for rel, number in locations:
        if rel not in indexes:
            continue
        key = (rel, indexes[rel].unit(number))
        first.setdefault(key, Unit(rel, key[1], [], set(), -1)).lines.append(number)
    rest = []
    for unit in units:
        key = (unit.file, unit.name)
        if key in first:
            first[key].lines += unit.lines
        else:
            rest.append(unit)
    return [*first.values(), *rest]


def rank_of(results: list[tuple[str, int, int]], spans: list[tuple[str, int, int]]) -> int | None:
    """1-based rank of the first result whose file matches and whose lines overlap a span."""
    for rank, (rel, first, last) in enumerate(results, start=1):
        if any(rel == f and first <= b and last >= a for f, a, b in spans):
            return rank
    return None


def unit_rank(units: list[Unit], spans: list[tuple[str, int, int]]) -> int | None:
    for rank, unit in enumerate(units, start=1):
        if any(rank_of([(unit.file, n, n)], spans) for n in unit.lines):
            return rank
    return None


# --- slot 2: semble -------------------------------------------------------------------------


def run_semble(
    cli: str, corpus: Path, query: str, content: str, env: dict[str, str], cwd: Path
) -> tuple[list[tuple[str, int, int]], float, int]:
    command = [cli, "search", "--top-k", str(TOP_K), "--format", "json", "--content", content]
    command += ["--", query, str(corpus)]
    started = time.perf_counter()
    done = subprocess.run(command, env=env, cwd=cwd, capture_output=True, text=True, check=True)
    elapsed = time.perf_counter() - started
    data = json.loads(done.stdout)
    results = [(r["file_path"], r["start_line"], r["end_line"]) for r in data.get("results", [])]
    return results, elapsed, len(done.stdout)


def tree_bytes(path: Path) -> int:
    return sum(p.stat().st_size for p in path.rglob("*") if p.is_file() and not p.is_symlink())


def summarize_audit(log: Path, work: Path, home: Path) -> dict:
    """Network calls, process starts and written paths, from one audit log."""
    network: list[str] = []
    processes: list[str] = []
    written: set[str] = set()
    removed: set[str] = set()
    if log.exists():
        for raw in log.read_text(encoding="utf-8", errors="replace").splitlines():
            _, event, detail = (raw.split("\t", 2) + ["", ""])[:3]
            if event.startswith("socket."):
                network.append(f"{event} {detail}"[:200])
            elif event in ("subprocess.Popen", "os.posix_spawn", "os.exec", "os.system"):
                processes.append(f"{event} {detail}"[:200])
            elif event == "open-write":
                written.add(detail)
            elif event in ("os.mkdir", "os.rename"):
                written.update(re.findall(r"'([^']*)'", detail)[-1:])  # the path created
            elif event in ("os.remove", "os.rmdir"):
                removed.update(re.findall(r"'([^']*)'", detail)[:1])

    def shown(path: str) -> str:
        if path.startswith(str(work)):
            path = "$WORK" + path[len(str(work)) :]
        elif path.startswith(str(home)):
            path = "~" + path[len(str(home)) :]
        path = re.sub(r"/[0-9a-f]{40,64}(?=/|$)", "/<hash>", path)
        return re.sub(r"\.pyc\.[0-9]+$", ".pyc", path)

    absolute = {
        p for p in written if p.startswith("/")
    }  # fd numbers and fd-relative names left out
    inside = sorted({str(Path(shown(p)).parent) for p in absolute if p.startswith(str(work))})
    outside: dict[str, str] = {}
    for path in sorted(absolute - {p for p in absolute if p.startswith(str(work))}):
        if path == "/tmp":
            outside["/tmp (an unnamed temporary file)"] = "has no name; gone when closed"
        elif path.startswith("/tmp/") and path in removed:
            outside["/tmp/<temporary name>"] = "created and removed in the same process"
        else:
            outside[shown(path)] = "kept"
    return {
        "network": sorted(set(network)),
        "processes": processes,
        "write_folders_in_work": inside,
        "writes_outside_work": outside,
    }


def check(args: argparse.Namespace) -> None:
    questions, _ = load_inputs()
    files = corpus_files(args.repo, questions["frozen_commit"], args.corpus)
    indexes = {rel: FileIndex(args.corpus, rel) for rel in files}
    for question in questions["questions"]:
        for rel, first, last in answer_spans(question, indexes):
            names = [a["symbol"] for a in question["answers"] if a["file"] == rel]
            print(f"{question['id']}  {rel}:{first}-{last}  {', '.join(names)}")
    print(f"ok: {len(files)} files match {questions['frozen_commit']}; every answer resolves")


def run(args: argparse.Namespace) -> None:
    questions, plans = load_inputs()
    commit = questions["frozen_commit"]
    corpus, work, home = args.corpus.resolve(), args.work.resolve(), Path.home()
    files = corpus_files(args.repo, commit, corpus)
    indexes = {rel: FileIndex(corpus, rel) for rel in files}
    caches = [work / "hf", work / "xdg-cache", *work.glob("semble-cache*")]
    caches += [*work.glob("inprocess-cache*"), *work.glob("logs/audit-*")]
    if used := [p for p in caches if p.is_file() or (p.is_dir() and any(p.iterdir()))]:
        raise SystemExit(f"the run starts from empty caches; remove these first: {used}")
    audit_dir, logs = work / "audit", work / "logs"
    audit_dir.mkdir(parents=True, exist_ok=True)
    logs.mkdir(parents=True, exist_ok=True)
    (audit_dir / "sitecustomize.py").write_text(AUDIT_HOOK, encoding="utf-8")
    base_env = {"PATH": "/usr/bin:/bin", "HOME": str(home), "LANG": "C.UTF-8"}
    semble_env = {
        **base_env,
        "HF_HOME": str(work / "hf"),
        "SEMBLE_CACHE_LOCATION": str(work / "semble-cache"),
        "XDG_CACHE_HOME": str(work / "xdg-cache"),
        "PYTHONPATH": str(audit_dir),
    }

    def semble_env_for(step: str, cache: Path | None = None) -> dict[str, str]:
        env = {**semble_env, "ADR0001_AUDIT_LOG": str(logs / f"audit-{step}.log")}
        if cache is not None:
            env["SEMBLE_CACHE_LOCATION"] = str(cache)
        return env

    semble_python = str(Path(args.semble).parent / "python")
    server_env = {**base_env, "PYRIGHT_PYTHON_IGNORE_WARNINGS": "1"}
    versions = {
        "harness_blob": git_blob(Path(__file__).read_bytes()),
        "python": platform.python_version(),
        "semble": subprocess.run(
            [args.semble, "--version"], env=semble_env, capture_output=True, text=True, check=True
        ).stdout.strip(),
        "ripgrep": subprocess.run(
            ["rg", "--version"], executable=args.rg, env=base_env, capture_output=True, text=True
        ).stdout.splitlines()[0],
        "pyright": subprocess.run(
            [str(Path(args.pyright).parent / "pyright"), "--version"],
            env=server_env,
            capture_output=True,
            text=True,
            check=True,
        ).stdout.strip(),
    }

    # 1. First use: the model download, the only step that may touch the network.
    started = time.perf_counter()
    subprocess.run(
        [semble_python, "-c", "from semble.index.dense import load_model; load_model()"],
        env=semble_env_for("model-download"),
        cwd=logs,
        check=True,
    )
    model_download_s = time.perf_counter() - started
    hf_home = work / "hf"
    model_dir = hf_home / "hub" / ("models--" + MODEL.replace("/", "--"))
    xet_logs = " ".join(p.read_text(errors="replace") for p in hf_home.glob("xet/logs/*.log"))
    model = {
        "name": MODEL,
        "revision": (model_dir / "refs" / "main").read_text(encoding="utf-8").strip(),
        "snapshot_files": sorted(
            p.name for p in (model_dir / "snapshots").rglob("*") if p.is_file()
        ),
        # huggingface_hub 2.x keeps large files in a shared blob store under hub/blobs.
        "hf_home_bytes": tree_bytes(hf_home),
        "hf_home_entries": sorted(
            p.relative_to(hf_home).as_posix() for p in [*hf_home.glob("*"), *hf_home.glob("*/*")]
        ),
        "hosts_in_xet_log": sorted(set(re.findall(r"[A-Za-z0-9.-]+\.hf\.co\b", xet_logs))),
        "first_load_with_download_s": round(model_download_s, 2),
    }

    # 2. Index builds through the CLI, cold (fresh cache) and then warm, per content type used.
    variants = sorted(
        {plans[q["id"]]["semble"]["content"] for q in questions["questions"]} | {"all"}
    )
    builds = {}
    for content in variants:
        cache = work / f"semble-cache-{content}"
        env = semble_env_for(f"build-{content}", cache)
        _, cold, _ = run_semble(args.semble, corpus, "warm up", content, env, logs)
        _, warm, _ = run_semble(args.semble, corpus, "warm up", content, env, logs)
        (index_dir,) = [p for p in cache.glob("*/index*") if p.is_dir()]
        meta = json.loads((index_dir / "metadata.json").read_text(encoding="utf-8"))
        chunks = json.loads((index_dir / "chunks.json").read_text(encoding="utf-8"))
        builds[content] = {
            "first_cli_call_s": round(cold, 3),
            "warm_cli_call_s": round(warm, 3),
            "index_bytes": tree_bytes(index_dir),
            "indexed_files": len(meta["files"]),
            "chunks": len(chunks),
        }

    # 3. Every question, both methods, REPEATS times each; results must not vary.
    started = time.perf_counter()
    server = LanguageServer([args.pyright, "--stdio"], corpus, server_env)
    while not server.workspace_symbols("BoundaryError"):
        if time.perf_counter() - started > 120:
            raise SystemExit("pyright found no symbols within 120 s")
        time.sleep(0.5)
    pyright_ready_s = time.perf_counter() - started
    rg_env = {**base_env}

    def where(unit: Unit) -> str:
        """A unit as file:first-last, like semble's chunks. Not by name: a symbol name could
        trip the paper-only scan (one test's own name holds the words it looks for)."""
        first, last = indexes[unit.file].unit_span(unit.lines[0])
        return f"{unit.file}:{first}-{last}"

    per_question = []
    for question in questions["questions"]:
        qid, plan = question["id"], plans[question["id"]]
        spans = answer_spans(question, indexes)
        slot1_runs = []
        for _ in range(REPEATS):
            hits_per_search, rg_seconds, rg_errors = [], 0.0, []
            for search in plan["rg"]:
                hits, seconds, error = run_rg(args.rg, corpus, search, rg_env)
                hits_per_search.append(hits)
                rg_seconds += seconds
                if error:
                    rg_errors.append(error)
            ranked, printed = rank_slot1(hits_per_search, indexes)
            all_hits = [h for hits in hits_per_search for h in hits]
            top = [(u.file, u.name) for u in ranked]
            locations, lookup_s = pyright_lookup(server, plan["pyright"], all_hits, top, indexes)
            final = with_lookup_first(ranked, locations, indexes)
            printed_final = with_lookup_first(printed, locations, indexes)
            slot1_runs.append(
                {
                    "rank": unit_rank(final, spans),
                    "rank_printed": unit_rank(printed_final, spans),
                    "top5": [where(u) for u in final[:TOP_K]],
                    "seconds": rg_seconds + lookup_s,
                    "rg_hit_lines": len(all_hits),
                    "rg_errors": rg_errors,
                    "output_chars": sum(len(f"{r}:{n}:{t}\n") for r, n, t in all_hits)
                    + sum(len(f"{r}:{n}\n") for r, n in locations),
                    "lookup_locations": len(locations),
                }
            )
        semble_runs, verbatim_runs = [], []
        env = semble_env_for("questions", work / f"semble-cache-{plan['semble']['content']}")
        env_all = semble_env_for("questions", work / "semble-cache-all")
        for _ in range(REPEATS):
            got = run_semble(
                args.semble, corpus, plan["semble"]["query"], plan["semble"]["content"], env, logs
            )
            semble_runs.append(got)
            verbatim_runs.append(
                run_semble(args.semble, corpus, question["question"], "all", env_all, logs)
            )
        stable = (
            len({json.dumps([r["top5"], r["rank"]]) for r in slot1_runs}) == 1
            and len({json.dumps(r[0]) for r in semble_runs}) == 1
            and len({json.dumps(r[0]) for r in verbatim_runs}) == 1
        )
        s1, sem, verb = slot1_runs[0], semble_runs[0], verbatim_runs[0]
        per_question.append(
            {
                "id": qid,
                "category": question["category"],
                "names_identifier": "`" in question["question"],
                "stable_across_repeats": stable,
                "slot1": {
                    "rank": s1["rank"],
                    "rank_printed_order": s1["rank_printed"],
                    "top5": s1["top5"],
                    "median_s": round(statistics.median(r["seconds"] for r in slot1_runs), 4),
                    "rg_hit_lines": s1["rg_hit_lines"],
                    "rg_errors": s1["rg_errors"],
                    "lookup_locations": s1["lookup_locations"],
                    "output_chars": s1["output_chars"],
                },
                "semble": {
                    "rank": rank_of(sem[0], spans),
                    "top5": [f"{r}:{a}-{b}" for r, a, b in sem[0]],
                    "median_cli_s": round(statistics.median(r[1] for r in semble_runs), 4),
                    "output_chars": sem[2],
                },
                "semble_verbatim_all": {
                    "rank": rank_of(verb[0], spans),
                    "top5": [f"{r}:{a}-{b}" for r, a, b in verb[0]],
                    "median_cli_s": round(statistics.median(r[1] for r in verbatim_runs), 4),
                    "output_chars": verb[2],
                },
            }
        )
        print(qid, s1["rank"], rank_of(sem[0], spans), rank_of(verb[0], spans), flush=True)
    server.close()

    # 4. In-process: index build with the model loaded, and query latency (as in MCP mode).
    inprocess = json.loads(
        subprocess.run(
            [
                semble_python,
                "-I",
                str(Path(__file__).resolve()),
                "inprocess",
                "--corpus",
                str(corpus),
            ]
            + ["--work", str(work)],
            env=semble_env_for("inprocess"),
            cwd=logs,
            capture_output=True,
            text=True,
            check=True,
        ).stdout
    )

    def summary(key: str, field: str = "rank") -> dict:
        ranks = [q[key][field] for q in per_question]
        return {f"at_{k}": sum(1 for r in ranks if r is not None and r <= k) for k in KS}

    slot1, semble = summary("slot1"), summary("semble")
    decision = {
        "rule": f"adopt only if semble's count at 3 is at least {MARGIN_AT_3} above slot 1's and "
        "it is not lower at 1 or at 5",
        "semble_minus_slot1": {k: semble[k] - slot1[k] for k in slot1},
    }
    decision["adopt"] = bool(
        decision["semble_minus_slot1"]["at_3"] >= MARGIN_AT_3
        and decision["semble_minus_slot1"]["at_1"] >= 0
        and decision["semble_minus_slot1"]["at_5"] >= 0
    )
    by_category: dict[str, dict] = {}
    for q in per_question:
        row = by_category.setdefault(
            q["category"], {"questions": 0, "slot1_at_3": 0, "semble_at_3": 0}
        )
        row["questions"] += 1
        row["slot1_at_3"] += int(q["slot1"]["rank"] is not None and q["slot1"]["rank"] <= 3)
        row["semble_at_3"] += int(q["semble"]["rank"] is not None and q["semble"]["rank"] <= 3)

    def median_of(key: str, field: str) -> float:
        return round(statistics.median(q[key][field] for q in per_question), 4)

    results = {
        "schema": "meridian.adr-0001.results/1",
        "frozen_commit": commit,
        "questions": len(per_question),
        "measured_utc": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        "machine": {"cpus": os.cpu_count(), "system": platform.platform(terse=True)},
        "versions": versions,
        "model": model,
        "pyright_ready_s": round(pyright_ready_s, 2),
        "semble_builds": builds,
        "semble_inprocess": inprocess,
        "summary": {
            "slot1_rg_pyright": slot1,
            "slot1_printed_order": summary("slot1", "rank_printed_order"),
            "semble_plan_query": semble,
            "semble_verbatim_question_all_content": summary("semble_verbatim_all"),
            "by_category_at_3": by_category,
            "median_seconds": {
                "slot1": median_of("slot1", "median_s"),
                "semble_cli": median_of("semble", "median_cli_s"),
                "semble_inprocess_search": inprocess["median_search_s"],
            },
            "median_output_chars": {
                "slot1": median_of("slot1", "output_chars"),
                "semble_cli": median_of("semble", "output_chars"),
            },
            "all_results_stable_across_repeats": all(
                q["stable_across_repeats"] for q in per_question
            ),
        },
        "decision": decision,
        "audit": {
            step: summarize_audit(logs / f"audit-{step}.log", work, home)
            for step in ["model-download", *(f"build-{c}" for c in variants), "questions"]
        },
        "per_question": per_question,
    }
    args.out.write_text(json.dumps(results, indent=1) + "\n", encoding="utf-8")
    print(json.dumps(results["summary"], indent=1))
    print(json.dumps(decision, indent=1))


def inprocess(args: argparse.Namespace) -> None:
    """Runs under semble's own Python: build times with the model loaded, and query latency."""
    from semble import ContentType, SembleIndex  # only installed in the throwaway environment

    questions, plans = load_inputs()
    corpus, work = args.corpus.resolve(), args.work.resolve()
    content_of = {"code": [ContentType.CODE], "docs": [ContentType.DOCS]}
    content_of |= {"config": [ContentType.CONFIG], "all": list(ContentType)}
    SembleIndex.from_path(corpus, content=content_of["all"])  # loads the model once
    builds = {}
    for name, content in content_of.items():
        seconds = []
        for repeat in range(BUILD_REPEATS):
            os.environ["SEMBLE_CACHE_LOCATION"] = str(work / f"inprocess-cache-{name}-{repeat}")
            started = time.perf_counter()
            SembleIndex.from_path(corpus, content=content)
            seconds.append(time.perf_counter() - started)
        builds[name] = round(statistics.median(seconds), 4)
    os.environ["SEMBLE_CACHE_LOCATION"] = str(work / "inprocess-cache-search")
    loaded = {name: SembleIndex.from_path(corpus, content=c) for name, c in content_of.items()}
    latencies = []
    for question in questions["questions"]:
        plan = plans[question["id"]]["semble"]
        index = loaded[plan["content"]]
        seconds = []
        for _ in range(5):
            started = time.perf_counter()
            index.search(plan["query"], top_k=TOP_K)
            seconds.append(time.perf_counter() - started)
        latencies.append(statistics.median(seconds))
    packages = sorted(
        f"{d.metadata['Name'].lower()}=={d.version}" for d in metadata.distributions()
    )
    mcp_context = None
    try:  # with the mcp extra: what the MCP server gives a client, built without serving
        from semble.mcp import _IndexCache, create_server

        server = create_server(_IndexCache())
        tools = [
            t.model_dump(mode="json", exclude_none=True) for t in asyncio.run(server.list_tools())
        ]
        mcp_context = {
            "tools": [t["name"] for t in tools],
            "tool_definitions_chars": len(json.dumps(tools)),
            "server_instructions_chars": len(server.instructions or ""),
        }
    except ImportError:
        pass
    print(
        json.dumps(
            {
                "median_build_s_model_loaded": builds,
                "median_search_s": round(statistics.median(latencies), 5),
                "max_search_s": round(max(latencies), 5),
                "packages": packages,
                "mcp_context": mcp_context,
            }
        )
    )


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[1])
    sub = parser.add_subparsers(dest="command", required=True)
    for name in ("check", "run", "inprocess"):
        p = sub.add_parser(name)
        p.add_argument("--corpus", type=Path, required=True)
        if name != "inprocess":
            p.add_argument("--repo", type=Path, required=True)
        if name != "check":
            p.add_argument("--work", type=Path, required=True)
        if name == "run":
            p.add_argument("--rg", required=True, help="Claude Code's binary; run as rg")
            p.add_argument("--pyright", required=True, help="pyright-langserver")
            p.add_argument("--semble", required=True, help="the semble CLI")
            p.add_argument("--out", type=Path, required=True)
    args = parser.parse_args()
    {"check": check, "run": run, "inprocess": inprocess}[args.command](args)


if __name__ == "__main__":
    sys.exit(main())
