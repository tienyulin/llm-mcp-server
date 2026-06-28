"""Read endpoints. HTTP concerns only — fallback logic lives in QueryService."""

from fastapi import APIRouter, Depends, HTTPException

from http_api.deps import get_query_service
from services.query_service import QueryService

router = APIRouter()


@router.get("/list_apis")
async def list_apis(module: str = "", svc: QueryService = Depends(get_query_service)):
    """
    List all API endpoints.

    Args:
        module: Optional module name to filter

    Returns:
        Dict mapping module names to list of API keys
    """
    result = await svc.list_apis(module)
    if not result:
        msg = f"No APIs found for module '{module}'" if module.strip() else "Wiki is empty"
        raise HTTPException(status_code=404, detail=msg)
    return {"modules": result}


@router.get("/search_apis")
async def search_apis(query: str, svc: QueryService = Depends(get_query_service)):
    """
    Search API endpoints by keyword.

    Args:
        query: Search keyword (searches path, description, parameters)

    Returns:
        List of matching API records
    """
    if not query.strip():
        raise HTTPException(status_code=400, detail="Query cannot be empty")

    results, mode = await svc.search_apis(query)
    return {"results": results, "count": len(results), "mode": mode}


@router.get("/semantic_search")
async def semantic_search(
    query: str, top_k: int = 10, svc: QueryService = Depends(get_query_service)
):
    """
    Semantic (vector) search over API entries.

    Requires the PG+pgvector index and a configured embeddings provider.
    Degrades to keyword search (mode=keyword_fallback) instead of erroring
    when either is unavailable — a degraded-but-answerable query never 5xxs.

    Returns:
        Matching entries with a cosine-similarity score (semantic mode only).
    """
    if not query.strip():
        raise HTTPException(status_code=400, detail="Query cannot be empty")
    top_k = max(1, min(top_k, 50))

    results, mode = await svc.semantic_search(query, top_k)
    return {"results": results, "count": len(results), "mode": mode}


@router.get("/get_api_detail")
async def get_api_detail(module: str, api_key: str, svc: QueryService = Depends(get_query_service)):
    """
    Get full details of a specific API endpoint.

    Args:
        module: Module name (e.g., 'inventory')
        api_key: API key (e.g., 'GET /inventory/{id}')

    Returns:
        Full API details or 404 if not found
    """
    detail = await svc.get_api_detail(module, api_key)
    if detail is None:
        raise HTTPException(
            status_code=404,
            detail=f"API '{api_key}' not found in module '{module}'",
        )
    return {"detail": detail}


@router.get("/wiki_info")
async def wiki_info(svc: QueryService = Depends(get_query_service)):
    """Get wiki statistics."""
    return await svc.wiki_info()


@router.get("/list_concepts")
async def list_concepts(svc: QueryService = Depends(get_query_service)):
    """Cross-app concepts (summary). Empty when concepts haven't been built."""
    return {"concepts": await svc.list_concepts()}


@router.get("/get_concept")
async def get_concept(name: str, svc: QueryService = Depends(get_query_service)):
    """Full concept record (description, related endpoints, apps)."""
    concept = await svc.get_concept(name)
    if concept is None:
        raise HTTPException(status_code=404, detail=f"Concept '{name}' not found")
    return {"concept": concept}


@router.get("/get_overview")
async def get_overview(app: str, svc: QueryService = Depends(get_query_service)):
    """Per-app overview synthesized at ingest."""
    overview = await svc.get_overview(app)
    if overview is None:
        raise HTTPException(status_code=404, detail=f"No overview for app '{app}'")
    return {"overview": overview}


@router.get("/list_knowledge")
# `type` is the public query-param name (Diataxis doc_type); renaming changes the HTTP API.
async def list_knowledge(  # pylint: disable=redefined-builtin
    type: str = "", svc: QueryService = Depends(get_query_service)
):
    """Knowledge documents (prose/reference) ingested into the wiki.
    Optional `type` filters by Diataxis doc_type (tutorial/how-to/reference/explanation)."""
    return {"knowledge": await svc.list_knowledge(type=type)}


@router.get("/get_knowledge")
async def get_knowledge(doc_id: str, svc: QueryService = Depends(get_query_service)):
    """Full knowledge entry (title, summary, topics, key_points, provenance)."""
    entry = await svc.get_knowledge(doc_id)
    if entry is None:
        raise HTTPException(status_code=404, detail=f"Knowledge doc '{doc_id}' not found")
    return {"knowledge": entry}


@router.get("/search_knowledge")
# `type` is the public query-param name (Diataxis doc_type); renaming changes the HTTP API.
async def search_knowledge(  # pylint: disable=redefined-builtin
    query: str, type: str = "", svc: QueryService = Depends(get_query_service)
):
    """Hybrid search across knowledge docs. Optional `type` filters by Diataxis doc_type."""
    if not query.strip():
        raise HTTPException(status_code=400, detail="Query cannot be empty")
    results, mode = await svc.search_knowledge(query, type=type)
    return {"results": results, "count": len(results), "mode": mode}


@router.get("/skill")
async def skill(name: str = "wiki-expert", svc: QueryService = Depends(get_query_service)):
    """Package the wiki into an Anthropic Skill folder ({file_path: content})."""
    return {"files": await svc.build_skill(name)}


@router.get("/graph")
async def graph(svc: QueryService = Depends(get_query_service)):
    """Knowledge graph: endpoint + concept nodes with weighted edges."""
    return await svc.build_graph()
