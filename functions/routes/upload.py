import azure.functions as func
import json
import os
import secrets
from datetime import datetime, timezone, timedelta
from azure.storage.blob import BlobServiceClient, generate_blob_sas, BlobSasPermissions
from azure.storage.queue import QueueClient
from shared.db import get_container
from shared.response import response, CORS_HEADERS

bp = func.Blueprint()

ALLOWED_FORMATS = {"mp3", "wav", "m4a", "flac", "ogg"}
MAX_SIZE_FREE = 50 * 1024 * 1024      # 50MB
MAX_SIZE_PREMIUM = 200 * 1024 * 1024   # 200MB


def get_user_from_token(req):
    auth = req.headers.get("Authorization", "")
    if not auth.startswith("Bearer "):
        return None
    token = auth[7:]
    user_id = token.split(":")[0] if ":" in token else None
    if not user_id:
        return None
    container = get_container("users")
    try:
        return container.read_item(item=user_id, partition_key=user_id)
    except Exception:
        return None


@bp.route(route="upload", methods=["POST", "OPTIONS"])
def upload(req: func.HttpRequest) -> func.HttpResponse:
    if req.method == "OPTIONS":
        return func.HttpResponse("", status_code=204, headers=CORS_HEADERS)

    user = get_user_from_token(req)
    if not user:
        return response({"error": "Unauthorized"}, 401)

    try:
        body = req.get_json()
    except ValueError:
        return response({"error": "Invalid JSON"}, 400)

    filename = body.get("filename", "")
    file_size = body.get("fileSize", 0)
    title = body.get("title", filename.rsplit(".", 1)[0] if "." in filename else filename)

    # Validate format
    ext = filename.rsplit(".", 1)[-1].lower() if "." in filename else ""
    if ext not in ALLOWED_FORMATS:
        return response({"error": f"Formato no soportado. Usa: {', '.join(ALLOWED_FORMATS)}"}, 400)

    # Validate size
    max_size = MAX_SIZE_PREMIUM if user["plan"] == "premium" else MAX_SIZE_FREE
    if file_size > max_size:
        limit_mb = max_size // (1024 * 1024)
        return response({"error": f"Archivo muy grande. Límite: {limit_mb}MB"}, 400)

    # Check upload limits
    if user["plan"] == "free":
        last_upload = user.get("lastUpload")
        if last_upload:
            last_dt = datetime.fromisoformat(last_upload)
            if (datetime.now(timezone.utc) - last_dt).days < 3:
                return response({"error": "Plan free: 1 canción cada 3 días"}, 429)

    # Create song record
    song_id = secrets.token_hex(16)
    blob_path = f"{user['id']}/{song_id}.{ext}"

    song = {
        "id": song_id,
        "userId": user["id"],
        "title": title,
        "originalBlobPath": blob_path,
        "format": ext,
        "fileSize": file_size,
        "status": "uploading",
        "stems": [],
        "midiFiles": [],
        "createdAt": datetime.now(timezone.utc).isoformat(),
    }
    get_container("songs").create_item(body=song)

    # Generate SAS token for direct upload
    conn_str = os.environ["STORAGE_CONNECTION_STRING"]
    blob_service = BlobServiceClient.from_connection_string(conn_str)
    account_name = blob_service.account_name
    account_key = conn_str.split("AccountKey=")[1].split(";")[0]

    sas = generate_blob_sas(
        account_name=account_name,
        container_name="audio",
        blob_name=blob_path,
        account_key=account_key,
        permission=BlobSasPermissions(write=True, create=True),
        expiry=datetime.now(timezone.utc) + timedelta(minutes=30),
    )

    upload_url = f"https://{account_name}.blob.core.windows.net/audio/{blob_path}?{sas}"

    return response({"songId": song_id, "uploadUrl": upload_url}, 201)


@bp.route(route="songs/{songId}/process", methods=["POST", "OPTIONS"])
def process_song(req: func.HttpRequest) -> func.HttpResponse:
    if req.method == "OPTIONS":
        return func.HttpResponse("", status_code=204, headers=CORS_HEADERS)

    user = get_user_from_token(req)
    if not user:
        return response({"error": "Unauthorized"}, 401)

    song_id = req.route_params.get("songId")
    songs_container = get_container("songs")

    try:
        song = songs_container.read_item(item=song_id, partition_key=user["id"])
    except Exception:
        return response({"error": "Song not found"}, 404)

    # Update status
    song["status"] = "queued"
    songs_container.upsert_item(body=song)

    # Update user lastUpload
    users_container = get_container("users")
    user["lastUpload"] = datetime.now(timezone.utc).isoformat()
    users_container.upsert_item(body=user)

    # Enqueue - priority queue for premium
    conn_str = os.environ["STORAGE_CONNECTION_STRING"]
    queue_name = "audio-processing-priority" if user["plan"] == "premium" else "audio-processing-queue"
    queue_client = QueueClient.from_connection_string(conn_str, queue_name)

    message = json.dumps({"songId": song_id, "userId": user["id"], "blobPath": song["originalBlobPath"]})
    queue_client.send_message(message)

    # Count position in queue
    props = queue_client.get_queue_properties()
    position = props.approximate_message_count

    return response({"status": "queued", "position": position})


@bp.route(route="songs/{songId}/status", methods=["GET", "OPTIONS"])
def song_status(req: func.HttpRequest) -> func.HttpResponse:
    if req.method == "OPTIONS":
        return func.HttpResponse("", status_code=204, headers=CORS_HEADERS)

    user = get_user_from_token(req)
    if not user:
        return response({"error": "Unauthorized"}, 401)

    song_id = req.route_params.get("songId")

    try:
        song = get_container("songs").read_item(item=song_id, partition_key=user["id"])
    except Exception:
        return response({"error": "Song not found"}, 404)

    return response({
        "id": song["id"],
        "title": song["title"],
        "status": song["status"],
        "stems": song.get("stems", []),
        "midiFiles": song.get("midiFiles", []),
    })


@bp.route(route="songs", methods=["GET", "OPTIONS"])
def list_songs(req: func.HttpRequest) -> func.HttpResponse:
    if req.method == "OPTIONS":
        return func.HttpResponse("", status_code=204, headers=CORS_HEADERS)

    user = get_user_from_token(req)
    if not user:
        return response({"error": "Unauthorized"}, 401)

    container = get_container("songs")
    query = "SELECT c.id, c.title, c.status, c.format, c.createdAt FROM c WHERE c.userId = @userId ORDER BY c.createdAt DESC"
    songs = list(container.query_items(query=query, parameters=[{"name": "@userId", "value": user["id"]}], enable_cross_partition_query=True))

    return response({"songs": songs})
