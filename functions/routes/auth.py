import azure.functions as func
import json
import os
import secrets
from datetime import datetime, timezone
from shared.db import get_container
from shared.auth import hash_password, generate_token

bp = func.Blueprint()


@bp.route(route="register", methods=["POST"])
def register(req: func.HttpRequest) -> func.HttpResponse:
    try:
        body = req.get_json()
    except ValueError:
        return func.HttpResponse(json.dumps({"error": "Invalid JSON"}), status_code=400, mimetype="application/json")

    email = body.get("email", "").strip().lower()
    password = body.get("password", "")
    username = body.get("username", "").strip()

    if not email or not password or not username:
        return func.HttpResponse(json.dumps({"error": "email, password, username required"}), status_code=400, mimetype="application/json")

    container = get_container("users")
    query = "SELECT c.id FROM c WHERE c.email = @email"
    existing = list(container.query_items(query=query, parameters=[{"name": "@email", "value": email}], enable_cross_partition_query=True))
    if existing:
        return func.HttpResponse(json.dumps({"error": "Email already registered"}), status_code=409, mimetype="application/json")

    user_id = secrets.token_hex(16)
    user = {
        "id": user_id,
        "email": email,
        "username": username,
        "password": hash_password(password),
        "plan": "free",
        "createdAt": datetime.now(timezone.utc).isoformat(),
        "streak": 0,
        "lastPractice": None,
        "songsProcessedToday": 0,
        "lastUpload": None,
    }
    container.create_item(body=user)
    token = generate_token(user_id)

    return func.HttpResponse(
        json.dumps({"token": token, "user": {"id": user_id, "email": email, "username": username, "plan": "free"}}),
        status_code=201, mimetype="application/json",
    )


@bp.route(route="login", methods=["POST"])
def login(req: func.HttpRequest) -> func.HttpResponse:
    try:
        body = req.get_json()
    except ValueError:
        return func.HttpResponse(json.dumps({"error": "Invalid JSON"}), status_code=400, mimetype="application/json")

    email = body.get("email", "").strip().lower()
    password = body.get("password", "")

    if not email or not password:
        return func.HttpResponse(json.dumps({"error": "email and password required"}), status_code=400, mimetype="application/json")

    container = get_container("users")
    query = "SELECT * FROM c WHERE c.email = @email"
    users = list(container.query_items(query=query, parameters=[{"name": "@email", "value": email}], enable_cross_partition_query=True))

    if not users or users[0]["password"] != hash_password(password):
        return func.HttpResponse(json.dumps({"error": "Invalid credentials"}), status_code=401, mimetype="application/json")

    user = users[0]
    token = generate_token(user["id"])

    return func.HttpResponse(
        json.dumps({"token": token, "user": {"id": user["id"], "email": user["email"], "username": user["username"], "plan": user["plan"]}}),
        mimetype="application/json",
    )


@bp.route(route="login/google", methods=["POST"])
def login_google(req: func.HttpRequest) -> func.HttpResponse:
    try:
        body = req.get_json()
    except ValueError:
        return func.HttpResponse(json.dumps({"error": "Invalid JSON"}), status_code=400, mimetype="application/json")

    google_token = body.get("token", "")
    if not google_token:
        return func.HttpResponse(json.dumps({"error": "token required"}), status_code=400, mimetype="application/json")

    from google.oauth2 import id_token
    from google.auth.transport import requests

    google_client_id = os.environ.get("GOOGLE_CLIENT_ID")
    try:
        idinfo = id_token.verify_oauth2_token(google_token, requests.Request(), google_client_id)
    except ValueError:
        return func.HttpResponse(json.dumps({"error": "Invalid Google token"}), status_code=401, mimetype="application/json")

    email = idinfo["email"]
    name = idinfo.get("name", "")
    picture = idinfo.get("picture", "")

    container = get_container("users")
    query = "SELECT * FROM c WHERE c.email = @email"
    users = list(container.query_items(query=query, parameters=[{"name": "@email", "value": email}], enable_cross_partition_query=True))

    if users:
        user = users[0]
        if picture and user.get("picture") != picture:
            user["picture"] = picture
            container.upsert_item(body=user)
    else:
        user_id = secrets.token_hex(16)
        user = {
            "id": user_id,
            "email": email,
            "username": name or email.split("@")[0],
            "password": None,
            "google_id": idinfo["sub"],
            "picture": picture,
            "plan": "free",
            "createdAt": datetime.now(timezone.utc).isoformat(),
            "streak": 0,
            "lastPractice": None,
            "songsProcessedToday": 0,
            "lastUpload": None,
        }
        container.create_item(body=user)

    token = generate_token(user["id"])

    return func.HttpResponse(
        json.dumps({"token": token, "user": {"id": user["id"], "email": user["email"], "username": user["username"], "plan": user["plan"], "picture": user.get("picture")}}),
        mimetype="application/json",
    )
