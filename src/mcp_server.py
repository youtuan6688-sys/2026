"""MCP Server that exposes the Happycode knowledge base to Claude Code.

Provides semantic search over ChromaDB + vault memory files.
Run with: python -m src.mcp_server
"""

import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from mcp.server.stdio import stdio_server
from mcp.server import Server
from mcp.types import Tool, TextContent

from config.settings import settings
from src.storage.vector_store import VectorStore
from src.storage.content_index import ContentIndex

MEMORY_DIR = Path(settings.vault_path) / "memory"
VAULT_DIR = Path(settings.vault_path)

server = Server("happycode-knowledge")


def _read_memory_files() -> dict[str, str]:
    """Read all memory files."""
    memories = {}
    if MEMORY_DIR.exists():
        for f in MEMORY_DIR.glob("*.md"):
            memories[f.name] = f.read_text(encoding="utf-8")
    return memories


def _search_vault_files(query: str) -> list[dict]:
    """Simple text search across vault markdown files."""
    results = []
    query_lower = query.lower()
    for md_file in VAULT_DIR.rglob("*.md"):
        try:
            content = md_file.read_text(encoding="utf-8")
            if query_lower in content.lower():
                results.append({
                    "file": str(md_file.relative_to(VAULT_DIR)),
                    "snippet": _extract_snippet(content, query_lower),
                })
        except Exception:
            continue
    return results[:10]


def _extract_snippet(content: str, query: str, context_chars: int = 200) -> str:
    """Extract a text snippet around the query match."""
    idx = content.lower().find(query)
    if idx == -1:
        return content[:300]
    start = max(0, idx - context_chars)
    end = min(len(content), idx + len(query) + context_chars)
    return content[start:end]


@server.list_tools()
async def list_tools():
    return [
        Tool(
            name="semantic_search",
            description="Search the knowledge base by meaning (semantic similarity). Use for finding articles, notes, and saved content related to a topic.",
            inputSchema={
                "type": "object",
                "properties": {
                    "query": {"type": "string", "description": "Search query in natural language"},
                    "top_k": {"type": "integer", "description": "Number of results (default 5)", "default": 5},
                },
                "required": ["query"],
            },
        ),
        Tool(
            name="read_memory",
            description="Read the user's long-term memory files (profile, decisions, learnings, tools, briefing digest).",
            inputSchema={
                "type": "object",
                "properties": {
                    "file": {
                        "type": "string",
                        "description": "Specific file to read (e.g. 'profile.md'). Leave empty to list all.",
                    },
                },
            },
        ),
        Tool(
            name="search_vault",
            description="Full-text search across the entire Obsidian vault (articles, social posts, memory files).",
            inputSchema={
                "type": "object",
                "properties": {
                    "query": {"type": "string", "description": "Text to search for"},
                },
                "required": ["query"],
            },
        ),
        Tool(
            name="knowledge_stats",
            description="Get statistics about the knowledge base: document count, categories, recent additions.",
            inputSchema={"type": "object", "properties": {}},
        ),
    ]


@server.call_tool()
async def call_tool(name: str, arguments: dict):
    if name == "semantic_search":
        query = arguments["query"]
        top_k = arguments.get("top_k", 5)
        vs = VectorStore(settings.chromadb_path)
        results = vs.query_similar(query, top_k=top_k)
        if not results:
            return [TextContent(type="text", text="No results found.")]
        output = []
        for r in results:
            score = 1 - r.get("distance", 0)
            output.append(f"[{score:.0%}] {r.get('title', 'Untitled')}\n  {r.get('summary', '')}")
        return [TextContent(type="text", text="\n\n".join(output))]

    elif name == "read_memory":
        file_name = arguments.get("file", "")
        memories = _read_memory_files()
        if file_name:
            content = memories.get(file_name, f"File '{file_name}' not found. Available: {list(memories.keys())}")
            return [TextContent(type="text", text=content)]
        listing = "\n".join(f"- {k} ({len(v)} chars)" for k, v in memories.items())
        return [TextContent(type="text", text=f"Memory files:\n{listing}")]

    elif name == "search_vault":
        query = arguments["query"]
        results = _search_vault_files(query)
        if not results:
            return [TextContent(type="text", text=f"No matches for '{query}'.")]
        output = [f"Found {len(results)} matches:"]
        for r in results:
            output.append(f"\n**{r['file']}**\n{r['snippet'][:300]}")
        return [TextContent(type="text", text="\n".join(output))]

    elif name == "knowledge_stats":
        vs = VectorStore(settings.chromadb_path)
        doc_count = vs.collection.count()
        ci = ContentIndex(settings.sqlite_path)
        recent = ci.get_all_summaries(limit=5)
        memories = _read_memory_files()

        stats = [
            f"Documents in vector store: {doc_count}",
            f"Memory files: {len(memories)} ({', '.join(memories.keys())})",
            "\nRecent articles:",
        ]
        for r in recent:
            stats.append(f"  - {r.get('title', 'Untitled')}")
        return [TextContent(type="text", text="\n".join(stats))]

    return [TextContent(type="text", text=f"Unknown tool: {name}")]


async def main():
    async with stdio_server() as (read_stream, write_stream):
        await server.run(read_stream, write_stream, server.create_initialization_options())


if __name__ == "__main__":
    import asyncio
    asyncio.run(main())
