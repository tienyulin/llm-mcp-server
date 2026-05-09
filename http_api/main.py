"""
LLM Wiki HTTP Server — Karpathy-style browsing interface.

Exposes list_directory and read_file tools for LLMs to browse the wiki.
"""

import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI, HTTPException
from pydantic import BaseModel

from services.wiki_service import WikiService
from storage.minio_client import MinioReader

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

TOOLS_SCHEMA = [
    {
        "name": "list_directory",
        "description": "Browse the wiki file structure. Start with '/' to see all sections (api, architecture, workflows, concepts, guides). Use this to explore and understand what documentation exists.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "path": {
                    "type": "string",
                    "description": "Directory path. Start with '/' to see top-level items, then navigate deeper (e.g., 'api/', 'architecture/'). Default is '/'.",
                }
            },
        },
    },
    {
        "name": "read_file",
        "description": "Read a markdown wiki file's complete content. Files contain [[wikilinks]] to other docs. Read complete files to build context, not snippets.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "path": {
                    "type": "string",
                    "description": "File path discovered through browsing, e.g., 'api/users.md', 'overview.md', 'architecture/system.md'. Always read complete files for full context.",
                }
            },
            "required": ["path"],
        },
    },
]

WIKI_SYSTEM_PROMPT = """You have access to a Karpathy-style wiki knowledge base.

## Core Principle: Knowledge Accumulation, Not Search

This is NOT a search-based system like typical RAG. Instead, you ACCUMULATE knowledge:

1. **First question:** Read relevant complete files (api/users.md, overview.md, workflows/auth.md)
2. **Build mental model:** Keep this context in your understanding
3. **Subsequent questions:** Answer based on accumulated context (no need to re-read)
4. **Grow understanding:** Follow [[wikilinks]] to deepen knowledge as needed

This way, the longer a conversation goes, the better you understand the entire system.

## How to Use the Wiki

### Step 1: Browse the Structure
list_directory("/")
→ See: api/, architecture/, workflows/, concepts/, guides/

### Step 2: Understand Project First
read_file("overview.md")
→ Understand what the system is about

### Step 3: Navigate by Interest
For API questions:
  list_directory("/api")
  read_file("api/users.md")
  → Read COMPLETE file, not snippets

### Step 4: Follow Wikilinks to Deepen
Within files you'll see [[links]] like [[Orders Module]] or [[Authentication Flow]]
→ Follow them to build complete understanding

### Key Principles

- **Read complete files:** Not snippets or summaries. Full context matters.
- **Build understanding:** First question takes longer (read multiple files), but context accumulates.
- **Follow wikilinks:** They guide you to related concepts and modules naturally.
- **Natural exploration:** Like browsing Wikipedia - you learn more as you follow links.
- **Reuse context:** In the same conversation, use previously read information rather than re-reading.

## Real Example: How Context Accumulation Works

User Q1: "How do I create a user?"
→ You read:
   - read_file("overview.md")           # Understand project
   - read_file("api/users.md")          # See POST /users endpoint
   - See [[Authentication Flow]] link
   - read_file("workflows/auth.md")     # Understand authentication
   Time: ~500ms (initial file reading)
   Context: Now you understand users, API, and authentication

User Q2: "How does authentication work?"
→ You answer based on already-read workflows/auth.md
   No need to re-read!
   Time: Fast (reuse context)
   Context: Already in your understanding

User Q3: "What about the Orders API?"
→ You already understand the system from Q1 and Q2
   read_file("api/orders.md")           # Only read new module
   You can compare orders/users similarities immediately
   Time: ~200ms (only read one new file)
   Context: Continues to grow

User Q4: "How do these systems interact?"
→ You can answer complex design questions because you've read:
   overview.md, api/users.md, api/orders.md, workflows/auth.md
   You see the big picture!

## Context Window Strategy

When you have 200K token context window, use it strategically:

For a typical conversation:
1. INITIALIZE (first question)
   - read_file("overview.md")          [~2KB, builds foundation]
   - read_file("api/users.md")         [~5KB, user API details]
   - read_file("workflows/auth.md")    [~4KB, authentication logic]
   Total: ~11KB of rich context in your understanding

2. SUBSEQUENT QUESTIONS
   - Based on already-read context     [~0KB new reads, instant]
   - Or follow [[wikilinks]] for new info [selective file reads]

3. GROW UNDERSTANDING
   - After 10-20 questions on different topics
   - You've read: overview, 3-4 API modules, 2-3 workflows, several concepts
   - Total: ~50KB of curated knowledge
   - You understand the ENTIRE SYSTEM

This is exponentially better than searching for snippets 20 times.

## Why This Approach

Traditional RAG (search-based):
- Every query: "find relevant chunks"
- Agent starts fresh each time
- Limited context understanding
- Good for isolated questions, bad for complex reasoning

Karpathy Wiki (accumulation-based):
- First query: "read relevant complete files"
- Subsequent queries: "use what you've learned"
- Rich context understanding
- Perfect for complex system design questions

Your job: Read complete files, build understanding, answer complex questions.
"""


wiki_reader = None


@asynccontextmanager
async def lifespan(app: FastAPI):
    global wiki_reader
    wiki_reader = MinioReader()
    logger.info("Wiki HTTP Server started")
    yield
    logger.info("Wiki HTTP Server shutdown")


app = FastAPI(
    title="LLM Wiki HTTP API",
    version="2.0.0",
    description="Karpathy-style browsing interface for wiki queries",
    lifespan=lifespan,
)


class ToolCallRequest(BaseModel):
    path: str = "/"


@app.get("/health")
async def health():
    return {"status": "ok"}


@app.get("/tools")
async def get_tools():
    """Return available tool schemas."""
    return {"tools": TOOLS_SCHEMA, "system_prompt": WIKI_SYSTEM_PROMPT}


@app.post("/tools/{tool_name}")
async def handle_tool_call(tool_name: str, request: ToolCallRequest):
    """Dispatch a tool call to list_directory or read_file."""
    service = WikiService(wiki_reader)

    if tool_name == "list_directory":
        items = service.list_directory(request.path)
        return {"items": items}

    elif tool_name == "read_file":
        if not request.path or request.path == "/":
            raise HTTPException(status_code=400, detail="path is required for read_file")
        try:
            content = service.read_file(request.path)
            frontmatter, body = service.parse_frontmatter(content)
            return {"path": request.path, "frontmatter": frontmatter, "content": body}
        except FileNotFoundError as e:
            raise HTTPException(status_code=404, detail=str(e))

    else:
        raise HTTPException(status_code=404, detail=f"Unknown tool: {tool_name}")


if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8002)
