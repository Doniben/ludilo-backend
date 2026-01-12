#!/usr/bin/env python3
"""Sube archivos Guitar Pro depurados a Azure Blob Storage."""
import os
import re
import json
import subprocess
from pathlib import Path
from collections import defaultdict

BASE = "/Users/doniben/Documents/Guitar Pro tabs"
EXTENSIONS = {".gp3", ".gp4", ".gp5", ".gtp"}
CONTAINER = "library"
ACCOUNT = "stludilo"


def normalize(text):
    text = text.lower().strip()
    text = re.sub(r'\(\d+\)', '', text)
    text = re.sub(r'[_\-]+', ' ', text)
    text = re.sub(r'\s+', ' ', text).strip()
    text = re.sub(r'[^\w\s]', '', text)
    return text


def extract_artist_song(filepath):
    name = Path(filepath).stem
    parts = filepath.split("/")
    if "Tabs.pack.3" in filepath:
        genre_idx = parts.index("Tabs.pack.3")
        if len(parts) > genre_idx + 2:
            artist = parts[genre_idx + 2]
            return normalize(artist), normalize(name)
    if " - " in name:
        artist, song = name.split(" - ", 1)
        return normalize(artist), normalize(song)
    return "unknown", normalize(name)


def get_selected_files():
    """Selecciona el archivo más pesado por cada artista/canción."""
    songs = defaultdict(list)
    for root, dirs, files in os.walk(BASE):
        for f in files:
            ext = Path(f).suffix.lower()
            if ext not in EXTENSIONS:
                continue
            filepath = os.path.join(root, f)
            size = os.path.getsize(filepath)
            artist, song = extract_artist_song(filepath)
            key = f"{artist}/{song}"
            songs[key].append({"path": filepath, "size": size, "artist": artist, "song": song, "ext": ext})

    selected = []
    for key, versions in songs.items():
        versions.sort(key=lambda x: x["size"], reverse=True)
        selected.append(versions[0])
    return selected


def upload():
    selected = get_selected_files()
    print(f"Subiendo {len(selected)} archivos a Blob Storage...")

    # Get connection string
    conn = subprocess.run(
        ["az", "storage", "account", "show-connection-string", "--name", ACCOUNT, "--resource-group", "rg-ludilo", "--query", "connectionString", "-o", "tsv"],
        capture_output=True, text=True
    ).stdout.strip()

    uploaded = 0
    errors = 0
    for i, f in enumerate(selected):
        blob_name = f"guitarpro/{f['artist']}/{f['song']}{f['ext']}"
        result = subprocess.run(
            ["az", "storage", "blob", "upload", "--container-name", CONTAINER, "--name", blob_name, "--file", f["path"], "--connection-string", conn, "--overwrite", "--only-show-errors"],
            capture_output=True, text=True
        )
        if result.returncode == 0:
            uploaded += 1
        else:
            errors += 1

        if (i + 1) % 500 == 0:
            print(f"  Progreso: {i+1}/{len(selected)} ({uploaded} ok, {errors} errores)")

    print(f"\n✅ Completado: {uploaded} subidos, {errors} errores de {len(selected)} total")


if __name__ == "__main__":
    upload()
