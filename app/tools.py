"""Tools specialists can use. Each tool is an async function plus a JSON schema.

File tools are sandboxed to the workspace directory.
"""

import html
import re
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from pathlib import Path
from urllib.parse import parse_qs, unquote, urlparse

import httpx

MAX_TOOL_OUTPUT = 12_000
_UA = {"User-Agent": "Mozilla/5.0 (compatible; AgentTeam/0.1)"}


@dataclass
class Tool:
    name: str
    description: str
    parameters: dict
    fn: Callable[..., Awaitable[str]]

    def schema(self) -> dict:
        return {
            "type": "function",
            "function": {
                "name": self.name,
                "description": self.description,
                "parameters": self.parameters,
            },
        }


def _truncate(text: str) -> str:
    if len(text) <= MAX_TOOL_OUTPUT:
        return text
    return text[:MAX_TOOL_OUTPUT] + f"\n... [truncated {len(text) - MAX_TOOL_OUTPUT} chars]"


def html_to_text(raw: str) -> str:
    raw = re.sub(r"(?is)<(script|style|noscript|svg).*?</\1>", " ", raw)
    raw = re.sub(r"(?i)<br\s*/?>|</p>|</div>|</li>|</h\d>", "\n", raw)
    text = html.unescape(re.sub(r"<[^>]+>", " ", raw))
    text = re.sub(r"[ \t]+", " ", text)
    return re.sub(r"\n\s*\n+", "\n\n", text).strip()


class Workspace:
    def __init__(self, root: Path):
        self.root = root.resolve()
        self.root.mkdir(parents=True, exist_ok=True)

    def path(self, rel: str) -> Path:
        # Models often write "workspace/x.py" meaning the workspace root, not a subfolder.
        rel = rel.replace("\\", "/").removeprefix("./").removeprefix(f"{self.root.name}/")
        target = (self.root / rel).resolve()
        if not target.is_relative_to(self.root):
            raise PermissionError(f"Path '{rel}' is outside the workspace")
        return target


def build_tools(workspace: Workspace) -> dict[str, Tool]:
    async def list_files(path: str = ".") -> str:
        base = workspace.path(path)
        if not base.exists():
            return f"'{path}' does not exist."
        files = [
            str(p.relative_to(workspace.root)).replace("\\", "/")
            for p in sorted(base.rglob("*"))
            if p.is_file()
        ]
        return "\n".join(files[:500]) or "(empty)"

    async def read_file(path: str) -> str:
        target = workspace.path(path)
        if not target.is_file():
            return f"File '{path}' not found."
        return _truncate(target.read_text(encoding="utf-8", errors="replace"))

    async def write_file(path: str, content: str) -> str:
        target = workspace.path(path)
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(content, encoding="utf-8")
        return f"Wrote {len(content)} chars to {path}"

    async def fetch_url(url: str) -> str:
        if urlparse(url).scheme not in ("http", "https"):
            return "Only http(s) URLs are allowed."
        async with httpx.AsyncClient(timeout=20, follow_redirects=True, headers=_UA) as client:
            r = await client.get(url)
        if "html" in r.headers.get("content-type", ""):
            return _truncate(f"[{r.status_code}] {url}\n\n{html_to_text(r.text)}")
        return _truncate(f"[{r.status_code}] {url}\n\n{r.text}")

    async def web_search(query: str, max_results: int = 8) -> str:
        # DuckDuckGo's HTML endpoint: no API key needed. Best-effort parsing.
        async with httpx.AsyncClient(timeout=20, follow_redirects=True, headers=_UA) as client:
            r = await client.post("https://html.duckduckgo.com/html/", data={"q": query})
        results = []
        pattern = (
            r'class="result__a"[^>]*href="([^"]+)"[^>]*>(.*?)</a>'
            r'.*?class="result__snippet"[^>]*>(.*?)</a>'
        )
        for href, title, snippet in re.findall(pattern, r.text, re.DOTALL)[:max_results]:
            if "uddg=" in href:
                href = unquote(parse_qs(urlparse(href).query).get("uddg", [href])[0])
            results.append(f"- {html_to_text(title)}\n  {href}\n  {html_to_text(snippet)}")
        return "\n".join(results) or "No results (the search endpoint may be rate limiting)."

    path_param = {"type": "string", "description": "Path relative to the workspace root"}
    tools = [
        Tool("list_files", "List files in the shared workspace.",
             {"type": "object", "properties": {"path": path_param}}, list_files),
        Tool("read_file", "Read a text file from the shared workspace.",
             {"type": "object", "properties": {"path": path_param}, "required": ["path"]},
             read_file),
        Tool("write_file", "Create or overwrite a text file in the shared workspace.",
             {"type": "object",
              "properties": {"path": path_param, "content": {"type": "string"}},
              "required": ["path", "content"]},
             write_file),
        Tool("fetch_url", "Download a web page and return its readable text.",
             {"type": "object", "properties": {"url": {"type": "string"}}, "required": ["url"]},
             fetch_url),
        Tool("web_search", "Search the web. Returns titles, URLs and snippets.",
             {"type": "object",
              "properties": {"query": {"type": "string"},
                             "max_results": {"type": "integer", "default": 8}},
              "required": ["query"]},
             web_search),
    ]
    return {t.name: t for t in tools}
