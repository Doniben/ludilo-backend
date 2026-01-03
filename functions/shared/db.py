import os
from azure.cosmos import CosmosClient

_client = None

def get_client():
    global _client
    if not _client:
        conn = os.environ.get("COSMOSDB_CONNECTION_STRING")
        _client = CosmosClient.from_connection_string(conn)
    return _client

def get_container(name):
    db = get_client().get_database_client("ludilodb")
    return db.get_container_client(name)
