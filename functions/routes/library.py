import azure.functions as func
import logging
import os
import urllib.request
import urllib.parse
import json
from shared.db import get_container
from shared.response import response, CORS_HEADERS

bp = func.Blueprint()


@bp.route(route="library/identify", methods=["POST", "OPTIONS"])
def library_identify(req: func.HttpRequest) -> func.HttpResponse:
    if req.method == "OPTIONS":
        return func.HttpResponse("", status_code=204, headers=CORS_HEADERS)

    try:
        body = req.get_json()
    except ValueError:
        return response({"error": "Invalid JSON"}, 400)

    fingerprint = body.get("fingerprint")
    duration = body.get("duration")
    if not fingerprint or not duration:
        return response({"error": "fingerprint and duration required"}, 400)

    api_key = os.environ.get("ACOUSTID_API_KEY", "")
    if not api_key:
        return response({"error": "AcoustID not configured"}, 503)

    try:
        # Query AcoustID
        params = urllib.parse.urlencode({
            "client": api_key,
            "duration": int(duration),
            "fingerprint": fingerprint,
            "meta": "recordings",
        })
        url = f"https://api.acoustid.org/v2/lookup?{params}"
        req_acoustid = urllib.request.Request(url)
        with urllib.request.urlopen(req_acoustid, timeout=10) as resp:
            acoustid_data = json.loads(resp.read())

        if acoustid_data.get("status") != "ok" or not acoustid_data.get("results"):
            return response({"match": False})

        best = acoustid_data["results"][0]
        score = best.get("score", 0)

        if score < 0.7 or not best.get("recordings"):
            return response({"match": False, "score": score})

        recording = best["recordings"][0]
        title = recording.get("title", "")
        artist = recording["artists"][0]["name"] if recording.get("artists") else ""

        # Search in our library
        library_match = None
        if title:
            container = get_container("library_index")
            q = title
            query = "SELECT TOP 3 c.id, c.title, c.artist, c.source, c.format, c.blobPath FROM c WHERE CONTAINS(c.title, @q, true)"
            items = list(container.query_items(
                query=query,
                parameters=[{"name": "@q", "value": q}],
                enable_cross_partition_query=True
            ))
            if items:
                library_match = items[0]

        return response({
            "match": True,
            "score": score,
            "title": title,
            "artist": artist,
            "libraryMatch": library_match,
        })

    except Exception as e:
        logging.error(f"AcoustID error: {e}")
        return response({"match": False, "error": str(e)})


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
