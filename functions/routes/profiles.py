import azure.functions as func
from shared.db import get_container
from shared.response import response, CORS_HEADERS

bp = func.Blueprint()


@bp.function_name("user_profile")
@bp.route(route="users/{userId}/profile", methods=["GET", "OPTIONS"])
def user_profile(req: func.HttpRequest) -> func.HttpResponse:
    """Public user profile."""
    if req.method == "OPTIONS":
        return func.HttpResponse("", status_code=204, headers=CORS_HEADERS)

    user_id = req.route_params.get("userId")
    try:
        user = get_container("users").read_item(item=user_id, partition_key=user_id)
    except Exception:
        return response({"error": "User not found"}, 404)

    return response({
        "id": user["id"],
        "username": user.get("username", ""),
        "plan": user.get("plan", "free"),
        "streak": user.get("streak", 0),
        "createdAt": user.get("createdAt", ""),
    })


@bp.function_name("user_songs")
@bp.route(route="users/{userId}/songs", methods=["GET", "OPTIONS"])
def user_songs(req: func.HttpRequest) -> func.HttpResponse:
    """Public list of user's completed songs."""
    if req.method == "OPTIONS":
        return func.HttpResponse("", status_code=204, headers=CORS_HEADERS)

    user_id = req.route_params.get("userId")
    songs = list(get_container("songs").query_items(
        "SELECT c.id, c.title, c.status, c.createdAt, c.source, c.format, c.stems, c.midiFiles, c.originalBlobPath FROM c WHERE c.userId = @uid AND c.status = 'done'",
        parameters=[{"name": "@uid", "value": user_id}],
        partition_key=user_id
    ))

    return response({"songs": songs, "total": len(songs)})
