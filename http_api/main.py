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
        "description": "Browse the wiki file structure. Start with '/' to see top-level sections.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "path": {
                    "type": "string",
                    "description": "Directory path like '/', 'api/', 'architecture/'",
                }
            },
        },
    },
    {
        "name": "read_file",
        "description": "Read a markdown wiki file. Files contain [[wikilinks]] to related docs.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "path": {
                    "type": "string",
                    "description": "File path like 'api/users.md', 'overview.md'",
                }
            },
            "required": ["path"],
        },
    },
]

WIKI_SYSTEM_PROMPT = """You have access to a Karpathy-style wiki knowledge base.

## How to Use the Wiki

This is NOT a search-based system. Instead, BROWSE and EXPLORE:

### Step 1: Browse the Structure
list_directory("/")
→ See: api/, architecture/, workflows/, concepts/, guides/

### Step 2: Navigate by Interest
For API questions:
  list_directory("api/")
  read_file("api/users.md")

### Step 3: Follow Wikilinks
Within files you'll see [[links]] - follow them for related content.

### Key Principles
- Browse first, understand structure
- Read complete files, not snippets
- Follow [[wikilinks]] to build context
- Natural exploration like browsing Wikipedia
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
