#!/usr/bin/env python3
"""Deduplica archivos Guitar Pro de los 3 packs. No borra nada, genera reporte."""
import os
import re
import json
from collections import defaultdict
from pathlib import Path

BASE = "/Users/doniben/Documents/Guitar Pro tabs"
EXTENSIONS = {".gp3", ".gp4", ".gp5", ".gtp"}
OUTPUT = "/Users/doniben/Documents/PROGRAMMING-GIT/Ludilo/ludilo-backend/docs/gp_dedup_report.json"


def normalize(text):
    """Normaliza texto para comparación."""
    text = text.lower().strip()
    text = re.sub(r'\(\d+\)', '', text)  # quitar (2), (3)
    text = re.sub(r'[_\-]+', ' ', text)
    text = re.sub(r'\s+', ' ', text).strip()
    text = re.sub(r'[^\w\s]', '', text)
    return text


def extract_artist_song(filepath):
    """Extrae artista y canción del path."""
    name = Path(filepath).stem
    parts = filepath.split("/")

    # Pack 3: Género/Artista/archivo
    if "Tabs.pack.3" in filepath and len(parts) >= 3:
        genre_idx = parts.index("Tabs.pack.3")
        if len(parts) > genre_idx + 2:
            artist = parts[genre_idx + 2] if len(parts) > genre_idx + 2 else "unknown"
            song = name
            return normalize(artist), normalize(song), parts[genre_idx + 1]

    # Pack 1 y 2: "Artista - Canción.ext"
    if " - " in name:
        artist, song = name.split(" - ", 1)
        return normalize(artist), normalize(song), None

    return "unknown", normalize(name), None


def scan():
    songs = defaultdict(list)  # key: "artista/cancion" -> [files]
    total = 0

    for root, dirs, files in os.walk(BASE):
        for f in files:
            ext = Path(f).suffix.lower()
            if ext not in EXTENSIONS:
                continue
            total += 1
            filepath = os.path.join(root, f)
            size = os.path.getsize(filepath)
            artist, song, genre = extract_artist_song(filepath)
            key = f"{artist}/{song}"
            songs[key].append({"path": filepath, "size": size, "artist": artist, "song": song, "genre": genre})

    # Seleccionar el más pesado de cada grupo
    selected = []
    duplicates_removed = 0
    for key, versions in songs.items():
        versions.sort(key=lambda x: x["size"], reverse=True)
        selected.append(versions[0])
        duplicates_removed += len(versions) - 1

    # Stats
    artists = set(s["artist"] for s in selected if s["artist"] != "unknown")
    genres = set(s["genre"] for s in selected if s["genre"])

    report = {
        "total_files_scanned": total,
        "unique_songs": len(selected),
        "duplicates_removed": duplicates_removed,
        "unique_artists": len(artists),
        "genres_found": sorted(genres),
        "top_artists": sorted(
            [(a, sum(1 for s in selected if s["artist"] == a)) for a in artists],
            key=lambda x: -x[1]
        )[:30],
        "size_total_mb": round(sum(s["size"] for s in selected) / (1024*1024), 1),
    }

    # Guardar reporte
    with open(OUTPUT, "w") as f:
        json.dump(report, f, indent=2, ensure_ascii=False)

    print(f"Total archivos escaneados: {total}")
    print(f"Canciones únicas: {len(selected)}")
    print(f"Duplicados eliminados: {duplicates_removed}")
    print(f"Artistas únicos: {len(artists)}")
    print(f"Tamaño final: {report['size_total_mb']} MB")
    print(f"Reporte guardado en: {OUTPUT}")


if __name__ == "__main__":
    scan()
