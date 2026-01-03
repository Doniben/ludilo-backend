import azure.functions as func
import json

CORS_HEADERS = {
    "Access-Control-Allow-Origin": "*",
    "Access-Control-Allow-Methods": "GET, POST, PUT, DELETE, OPTIONS",
    "Access-Control-Allow-Headers": "Content-Type, Authorization",
}


def response(body, status_code=200):
    return func.HttpResponse(
        json.dumps(body),
        status_code=status_code,
        mimetype="application/json",
        headers=CORS_HEADERS,
    )
