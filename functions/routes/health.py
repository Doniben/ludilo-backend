import azure.functions as func
import json

bp = func.Blueprint()

@bp.route(route="health", methods=["GET"])
def health(req: func.HttpRequest) -> func.HttpResponse:
    return func.HttpResponse(
        json.dumps({"status": "ok", "service": "ludilo-api"}),
        mimetype="application/json",
    )
