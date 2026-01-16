import azure.functions as func
import logging
from shared.db import get_container
from shared.response import response, CORS_HEADERS

bp = func.Blueprint()


@bp.route(route="library/search", methods=["GET", "OPTIONS"])
def library_search(req: func.HttpRequest) -> func.HttpResponse:
    if req.method == "OPTIONS":
        return func.HttpResponse("", status_code=204, headers=CORS_HEADERS)

    q = req.params.get("q", "").strip()
    if not q or len(q) < 2:
        return response({"error": "Query must be at least 2 characters"}, 400)

    page = int(req.params.get("page", "1"))
    page_size = min(int(req.params.get("pageSize", "20")), 50)
    source = req.params.get("source")
    offset = (page - 1) * page_size

    try:
        container = get_container("library_index")

        conditions = ["(CONTAINS(c.title, @q, true) OR CONTAINS(c.artist, @q, true))"]
        params = [{"name": "@q", "value": q}]

        if source:
            conditions.append("c.source = @source")
            params.append({"name": "@source", "value": source})

        where = " AND ".join(conditions)

        # Count
        count_query = f"SELECT VALUE COUNT(1) FROM c WHERE {where}"
        total = list(container.query_items(
            query=count_query, parameters=params, enable_cross_partition_query=True
        ))[0]

        # Fetch page
        data_query = f"SELECT c.id, c.title, c.artist, c.source, c.format, c.blobPath FROM c WHERE {where} OFFSET {offset} LIMIT {page_size}"
        items = list(container.query_items(
            query=data_query, parameters=params, enable_cross_partition_query=True
        ))

        return response({
            "results": items,
            "total": total,
            "page": page,
            "pageSize": page_size,
            "totalPages": (total + page_size - 1) // page_size,
        })
    except Exception as e:
        logging.error(f"Library search error: {e}")
        return response({"error": str(e)}, 500)
