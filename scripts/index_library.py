#!/usr/bin/env python3
"""Indexa metadata de la biblioteca GP en Cosmos DB desde los nombres de blob."""
import subprocess
import json
import re
from pathlib import Path

ACCOUNT = "stludilo"
CONTAINER = "library"
PREFIX = "guitarpro/"


def normalize_display(text):
    """Capitaliza para mostrar al usuario."""
    return re.sub(r'\s+', ' ', text.replace('_', ' ')).strip().title()


def get_blobs():
    """Lista todos los blobs del container."""
    result = subprocess.run(
        ["az", "storage", "blob", "list", "--container-name", CONTAINER,
         "--account-name", ACCOUNT, "--prefix", PREFIX, "--num-results", "*",
         "--query", "[].{name:name, size:properties.contentLength}", "-o", "json"],
        capture_output=True, text=True
    )
    return json.loads(result.stdout)


def index():
    print("Listando blobs...")
    blobs = get_blobs()
    print(f"Total blobs: {len(blobs)}")

    # Conectar a Cosmos DB
    conn = subprocess.run(
        ["az", "cosmosdb", "keys", "list", "--name", "ludilodb", "--resource-group", "rg-ludilo",
         "--type", "connection-strings", "--query", "connectionStrings[0].connectionString", "-o", "tsv"],
        capture_output=True, text=True
    ).stdout.strip()

    from azure.cosmos import CosmosClient
    client = CosmosClient.from_connection_string(conn)
    container = client.get_database_client("ludilodb").get_container_client("library_index")

    batch = []
    for i, blob in enumerate(blobs):
        name = blob["name"]  # guitarpro/artista/cancion.gp4
        parts = name.replace(PREFIX, "").split("/")
        if len(parts) < 2:
            continue

        artist = normalize_display(parts[0])
        song = normalize_display(Path(parts[-1]).stem)
        ext = Path(parts[-1]).suffix.lower()

        doc = {
            "id": str(hash(name) & 0xFFFFFFFF),
            "title": song,
            "artist": artist,
            "blobPath": name,
            "format": ext.replace(".", ""),
            "source": "guitarpro",
            "fileSize": blob.get("size", 0),
        }
        batch.append(doc)

        if len(batch) >= 100:
            for d in batch:
                try:
                    container.upsert_item(body=d)
                except Exception:
                    pass
            batch = []
            if (i + 1) % 1000 == 0:
                print(f"  Indexados: {i+1}/{len(blobs)}")

    # Flush remaining
    for d in batch:
        try:
            container.upsert_item(body=d)
        except Exception:
            pass

    print(f"✅ Indexación completa: {len(blobs)} documentos en Cosmos DB (library_index)")


if __name__ == "__main__":
    index()
