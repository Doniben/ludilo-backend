"""
Worker API endpoints — Job assignment, status updates, completion
"""
import azure.functions as func
import json
import os
from datetime import datetime, timedelta, timezone
from shared.response import response, CORS_HEADERS
from shared.db import get_container

worker_bp = func.Blueprint()


@worker_bp.function_name("worker_claim")
@worker_bp.route(route="worker/claim", methods=["POST", "OPTIONS"])
def claim_job(req: func.HttpRequest) -> func.HttpResponse:
    """Assign next pending job to a worker node"""
    if req.method == "OPTIONS":
        return response({}, 200)

    try:
        body = req.get_json()
    except:
        return response({"error": "Invalid JSON"}, 400)

    node_id = body.get("node_id")
    if not node_id:
        return response({"error": "node_id required"}, 400)

    # Find next pending song
    songs = get_container("songs")
    query = "SELECT * FROM c WHERE c.status = 'queued' ORDER BY c._ts ASC OFFSET 0 LIMIT 1"
    items = list(songs.query_items(query, enable_cross_partition_query=True))

    if not items:
        return response({"error": "no_jobs"}, 200)

    song = items[0]

    # Claim it
    song["status"] = "processing"
    song["worker_node"] = node_id
    song["processing_started"] = datetime.now(timezone.utc).isoformat()
    songs.upsert_item(song)

    # Generate SAS URL for the audio blob
    from azure.storage.blob import generate_blob_sas, BlobSasPermissions
    account = os.environ.get("STORAGE_ACCOUNT", "stludilo")
    key = os.environ.get("STORAGE_KEY")
    blob_path = song.get("originalBlobPath") or song.get("blobPath", "")
    container_name = "audio"

    sas = generate_blob_sas(
        account_name=account,
        container_name=container_name,
        blob_name=blob_path,
        account_key=key,
        permission=BlobSasPermissions(read=True),
        expiry=datetime.now(timezone.utc) + timedelta(hours=2),
    )
    audio_url = f"https://{account}.blob.core.windows.net/{container_name}/{blob_path}?{sas}"

    return response({
        "song_id": song["id"],
        "user_id": song.get("userId", ""),
        "audio_url": audio_url,
        "title": song.get("title", ""),
        "format": song.get("format", ""),
    })


@worker_bp.function_name("worker_status")
@worker_bp.route(route="worker/status/{jobId}", methods=["POST", "OPTIONS"])
def update_job_status(req: func.HttpRequest) -> func.HttpResponse:
    """Update processing status for a job"""
    if req.method == "OPTIONS":
        return response({}, 200)

    job_id = req.route_params.get("jobId")
    try:
        body = req.get_json()
    except:
        return response({"error": "Invalid JSON"}, 400)

    songs = get_container("songs")
    try:
        # Read with cross-partition
        items = list(songs.query_items(
            f"SELECT * FROM c WHERE c.id = '{job_id}'",
            enable_cross_partition_query=True
        ))
        if not items:
            return response({"error": "not_found"}, 404)

        song = items[0]
        song["status"] = body.get("status", song["status"])
        if "progress" in body:
            song["progress"] = body["progress"]
        if "error" in body:
            song["error"] = body["error"]
            song["status"] = "error"
        song["last_update"] = datetime.now(timezone.utc).isoformat()
        songs.upsert_item(song)

        return response({"ok": True})
    except Exception as e:
        return response({"error": str(e)}, 500)


@worker_bp.function_name("worker_complete")
@worker_bp.route(route="worker/complete/{jobId}", methods=["POST", "OPTIONS"])
def complete_job(req: func.HttpRequest) -> func.HttpResponse:
    """Mark job as complete with results"""
    if req.method == "OPTIONS":
        return response({}, 200)

    job_id = req.route_params.get("jobId")
    try:
        body = req.get_json()
    except:
        return response({"error": "Invalid JSON"}, 400)

    songs = get_container("songs")
    try:
        items = list(songs.query_items(
            f"SELECT * FROM c WHERE c.id = '{job_id}'",
            enable_cross_partition_query=True
        ))
        if not items:
            return response({"error": "not_found"}, 404)

        song = items[0]
        results = body.get("results", {})
        song["status"] = "done"
        song["progress"] = 100
        song["stems"] = results.get("stems", {})
        song["midiFiles"] = results.get("midi", {})
        song["processing_completed"] = datetime.now(timezone.utc).isoformat()
        songs.upsert_item(song)

        return response({"ok": True, "song_id": job_id})
    except Exception as e:
        return response({"error": str(e)}, 500)


@worker_bp.function_name("worker_upload_url")
@worker_bp.route(route="worker/upload-url", methods=["POST", "OPTIONS"])
def get_upload_url(req: func.HttpRequest) -> func.HttpResponse:
    """Generate SAS URL for worker to upload results"""
    if req.method == "OPTIONS":
        return response({}, 200)

    try:
        body = req.get_json()
    except:
        return response({"error": "Invalid JSON"}, 400)

    blob_path = body.get("blob_path")
    if not blob_path:
        return response({"error": "blob_path required"}, 400)

    from azure.storage.blob import generate_blob_sas, BlobSasPermissions
    account = os.environ.get("STORAGE_ACCOUNT", "stludilo")
    key = os.environ.get("STORAGE_KEY")

    # Determine container based on path prefix
    if blob_path.startswith("stems/"):
        container = "audio"
    elif blob_path.startswith("midi/"):
        container = "midi"
    else:
        container = "audio"

    sas = generate_blob_sas(
        account_name=account,
        container_name=container,
        blob_name=blob_path,
        account_key=key,
        permission=BlobSasPermissions(write=True, create=True),
        expiry=datetime.now(timezone.utc) + timedelta(hours=1),
    )
    url = f"https://{account}.blob.core.windows.net/{container}/{blob_path}?{sas}"

    return response({"url": url})
