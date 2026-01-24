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
    blob_path = body.get("blobPath")  # If provided, generate fingerprint server-side

    api_key = os.environ.get("ACOUSTID_API_KEY", "")
    if not api_key:
        return response({"error": "AcoustID not configured"}, 503)

    try:
        # If no fingerprint provided but blobPath given, generate with fpcalc
        if not fingerprint and blob_path:
            import tempfile
            import subprocess as sp
            from azure.storage.blob import BlobServiceClient

            conn_str = os.environ["STORAGE_CONNECTION_STRING"]
            blob_service = BlobServiceClient.from_connection_string(conn_str)
            container_name = "audio"
            blob_client = blob_service.get_blob_client(container_name, blob_path)

            with tempfile.NamedTemporaryFile(suffix=".mp3", delete=False) as tmp:
                tmp.write(blob_client.download_blob().readall())
                tmp_path = tmp.name

            try:
                fpcalc_path = os.path.join(os.path.dirname(os.path.dirname(__file__)), "bin", "fpcalc")
                result = sp.run([fpcalc_path, "-json", "-length", "120", tmp_path],
                               capture_output=True, text=True, timeout=30)
                if result.returncode == 0:
                    fpcalc_data = json.loads(result.stdout)
                    fingerprint = fpcalc_data.get("fingerprint")
                    duration = fpcalc_data.get("duration")
            finally:
                os.unlink(tmp_path)

        if not fingerprint or not duration:
            return response({"match": False, "error": "Could not generate fingerprint"})

        # Query AcoustID (POST because fingerprints are large)
        params = urllib.parse.urlencode({
            "client": api_key,
            "duration": int(duration),
            "fingerprint": fingerprint,
            "meta": "recordings",
        }).encode()
        req_acoustid = urllib.request.Request(
            "https://api.acoustid.org/v2/lookup",
            data=params,
            headers={"Content-Type": "application/x-www-form-urlencoded"},
        )
        with urllib.request.urlopen(req_acoustid, timeout=15) as resp:
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

        # Search in our library - try all recordings from all results
        library_match = None
        container = get_container("library_index")
        for result in acoustid_data["results"]:
            if result.get("score", 0) < 0.7:
                break
            for rec in result.get("recordings", []):
                q = rec.get("title", "")
                if not q:
                    continue
                items = list(container.query_items(
                    query="SELECT TOP 1 c.id, c.title, c.artist, c.source, c.format, c.blobPath FROM c WHERE CONTAINS(c.title, @q, true)",
                    parameters=[{"name": "@q", "value": q}],
                    enable_cross_partition_query=True
                ))
                if items:
                    library_match = items[0]
                    title = rec.get("title", "")
                    artist = rec["artists"][0]["name"] if rec.get("artists") else ""
                    break
            if library_match:
                break

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
            if source == "midi":
                conditions.append("(c.source = 'lakh' OR c.source = 'la-midi')")
            else:
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
        # Prioritize: guitarpro > lakh > la-midi
        source_order = {"guitarpro": 0, "lakh": 1, "la-midi": 2}
        items.sort(key=lambda x: source_order.get(x.get("source", ""), 9))

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


@bp.route(route="library/use", methods=["POST", "OPTIONS"])
def library_use(req: func.HttpRequest) -> func.HttpResponse:
    """Registra una canción de biblioteca como 'done' para el usuario."""
    if req.method == "OPTIONS":
        return func.HttpResponse("", status_code=204, headers=CORS_HEADERS)

    from datetime import datetime, timezone
    import secrets
    from routes.upload import get_user_from_token

    user = get_user_from_token(req)
    if not user:
        return response({"error": "Unauthorized"}, 401)

    try:
        body = req.get_json()
    except ValueError:
        return response({"error": "Invalid JSON"}, 400)

    blob_path = body.get("blobPath")
    title = body.get("title", "")
    artist = body.get("artist", "")
    source = body.get("source", "")
    fmt = body.get("format", "")

    if not blob_path:
        return response({"error": "blobPath required"}, 400)

    song_id = secrets.token_hex(16)
    song = {
        "id": song_id,
        "userId": user["id"],
        "title": f"{artist} - {title}" if artist else title,
        "status": "done",
        "source": "library",
        "librarySource": source,
        "originalBlobPath": blob_path,
        "format": fmt,
        "stems": [],
        "midiFiles": [blob_path],
        "createdAt": datetime.now(timezone.utc).isoformat(),
    }
    get_container("songs").create_item(body=song)

    return response({"songId": song_id, "status": "done"}, 201)


@bp.route(route="library/preview", methods=["GET", "OPTIONS"])
def library_preview(req: func.HttpRequest) -> func.HttpResponse:
    """Genera URL temporal para previsualizar un archivo de la biblioteca."""
    if req.method == "OPTIONS":
        return func.HttpResponse("", status_code=204, headers=CORS_HEADERS)

    from datetime import datetime, timezone, timedelta
    from azure.storage.blob import BlobServiceClient, generate_blob_sas, BlobSasPermissions

    blob_path = req.params.get("blobPath")
    if not blob_path:
        return response({"error": "blobPath required"}, 400)

    try:
        conn_str = os.environ["STORAGE_CONNECTION_STRING"]
        blob_service = BlobServiceClient.from_connection_string(conn_str)
        account_name = blob_service.account_name
        account_key = conn_str.split("AccountKey=")[1].split(";")[0]

        # Fix Lakh paths: index has "lakh/x/..." but blob has "lakh/lmd_full/x/..."
        actual_path = blob_path
        if blob_path.startswith("lakh/") and not blob_path.startswith("lakh/lmd_full/"):
            actual_path = blob_path.replace("lakh/", "lakh/lmd_full/", 1)

        sas = generate_blob_sas(
            account_name=account_name,
            container_name="library",
            blob_name=actual_path,
            account_key=account_key,
            permission=BlobSasPermissions(read=True),
            expiry=datetime.now(timezone.utc) + timedelta(minutes=10),
        )
        url = f"https://{account_name}.blob.core.windows.net/library/{actual_path}?{sas}"
        return response({"url": url})
    except Exception as e:
        logging.error(f"Library preview error: {e}")
        return response({"error": str(e)}, 500)


@bp.route(route="library/musicxml", methods=["GET", "OPTIONS"])
def library_musicxml(req: func.HttpRequest) -> func.HttpResponse:
    """Convierte MIDI a MusicXML. Cachea el resultado en Blob Storage."""
    if req.method == "OPTIONS":
        return func.HttpResponse("", status_code=204, headers=CORS_HEADERS)

    blob_path = req.params.get("blobPath")
    if not blob_path:
        return response({"error": "blobPath required"}, 400)

    try:
        from datetime import datetime, timezone, timedelta
        from azure.storage.blob import BlobServiceClient, generate_blob_sas, BlobSasPermissions
        import tempfile

        conn_str = os.environ["STORAGE_CONNECTION_STRING"]
        blob_service = BlobServiceClient.from_connection_string(conn_str)
        account_name = blob_service.account_name
        account_key = conn_str.split("AccountKey=")[1].split(";")[0]

        # Check if MusicXML already cached
        musicxml_path = blob_path.rsplit(".", 1)[0] + ".musicxml"
        cache_container = blob_service.get_container_client("library")
        cache_blob = cache_container.get_blob_client(f"musicxml/{musicxml_path}")

        try:
            cache_blob.get_blob_properties()
            # Cached! Return URL
            sas = generate_blob_sas(
                account_name=account_name,
                container_name="library",
                blob_name=f"musicxml/{musicxml_path}",
                account_key=account_key,
                permission=BlobSasPermissions(read=True),
                expiry=datetime.now(timezone.utc) + timedelta(minutes=30),
            )
            url = f"https://{account_name}.blob.core.windows.net/library/musicxml/{musicxml_path}?{sas}"
            return response({"url": url, "cached": True})
        except Exception:
            pass  # Not cached, generate

        # Download MIDI
        source_container = blob_service.get_container_client("library")
        # Fix Lakh paths
        actual_blob_path = blob_path
        if blob_path.startswith("lakh/") and not blob_path.startswith("lakh/lmd_full/"):
            actual_blob_path = blob_path.replace("lakh/", "lakh/lmd_full/", 1)

        source_blob = source_container.get_blob_client(actual_blob_path)
        midi_data = source_blob.download_blob().readall()

        # Convert with music21
        import music21
        with tempfile.NamedTemporaryFile(suffix=".mid", delete=False) as tmp:
            tmp.write(midi_data)
            tmp_path = tmp.name

        try:
            score = music21.converter.parse(tmp_path)
            # Remove Unpitched notes (percussion) that cause export errors
            for el in list(score.recurse().getElementsByClass('Unpitched')):
                el.activeSite.remove(el)
            musicxml_str = music21.musicxml.m21ToXml.GeneralObjectExporter(score).parse().decode("utf-8")
        finally:
            os.unlink(tmp_path)

        # Cache the MusicXML
        from azure.storage.blob import ContentSettings
        cache_blob.upload_blob(musicxml_str.encode("utf-8"), overwrite=True, content_settings=ContentSettings(content_type="application/xml"))

        # Return URL
        sas = generate_blob_sas(
            account_name=account_name,
            container_name="library",
            blob_name=f"musicxml/{musicxml_path}",
            account_key=account_key,
            permission=BlobSasPermissions(read=True),
            expiry=datetime.now(timezone.utc) + timedelta(minutes=30),
        )
        url = f"https://{account_name}.blob.core.windows.net/library/musicxml/{musicxml_path}?{sas}"
        return response({"url": url, "cached": False})

    except Exception as e:
        logging.error(f"MusicXML conversion error: {e}")
        return response({"error": str(e)}, 500)
