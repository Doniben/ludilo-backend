#!/usr/bin/env python3
"""
generate_labels_from_gp.py — Genera labels.json para cada item del dataset.

Lee el meta.json de cada carpeta, abre el GP original, extrae notas con
string/fret/technique, y guarda labels.json.

Uso:
    python generate_labels_from_gp.py --input training/data/audio/
"""
import os
import sys
import json
import argparse
import logging
import time
from pathlib import Path
from typing import Optional, List

try:
    import guitarpro
except ImportError:
    print("ERROR: pip install PyGuitarPro")
    sys.exit(1)

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
log = logging.getLogger(__name__)

GUITAR_PROGRAMS = list(range(24, 32))
GUITAR_TRACK_HINTS = ["guitar", "gtr", "guitarra", "guit", "rhythm", "lead",
                      "acoustic", "electric", "clean", "distort", "overdriv"]


def is_guitar_track(track) -> bool:
    name = (track.name or "").lower()
    for hint in GUITAR_TRACK_HINTS:
        if hint in name:
            return True
    if hasattr(track, 'channel') and track.channel:
        if track.channel.instrument in GUITAR_PROGRAMS:
            return True
    if hasattr(track, 'strings') and len(track.strings) in (6, 7):
        if "bass" not in name and "bajo" not in name:
            return True
    return False


def detect_technique(note) -> str:
    if not hasattr(note, 'effect'):
        return "normal"
    effect = note.effect
    if hasattr(effect, 'slide') and effect.slide:
        return "slide"
    if hasattr(effect, 'hammer') and effect.hammer:
        return "hammer"
    if hasattr(effect, 'bend') and effect.bend and effect.bend.points:
        return "bend"
    if hasattr(effect, 'harmonic') and effect.harmonic:
        return "harmonic"
    if hasattr(effect, 'trill') and effect.trill:
        return "trill"
    return "normal"


def extract_labels_from_gp(gp_path: str) -> Optional[dict]:
    """Extrae notas con metadata completa del GP."""
    try:
        song = guitarpro.parse(gp_path)
        tempo = song.tempo if hasattr(song, 'tempo') else 120
        tpq = 960

        notes = []
        duration_sec = 0

        for track_idx, track in enumerate(song.tracks):
            if not is_guitar_track(track):
                continue

            current_tick = 0
            for measure in track.measures:
                for voice in measure.voices:
                    beat_tick = current_tick
                    for beat in voice.beats:
                        beat_duration = int(tpq * 4 / beat.duration.value)
                        if beat.duration.isDotted:
                            beat_duration = int(beat_duration * 1.5)

                        onset_sec = (beat_tick / tpq) * (60.0 / tempo)
                        duration_beat_sec = (beat_duration / tpq) * (60.0 / tempo)

                        # Detectar strum: 3+ notas en el mismo beat
                        n_notes_in_beat = len(beat.notes)
                        is_strum = n_notes_in_beat >= 3

                        for note_idx, note in enumerate(beat.notes):
                            if hasattr(track, 'strings') and note.string <= len(track.strings):
                                midi_pitch = track.strings[note.string - 1].value + note.value
                            else:
                                continue
                            if midi_pitch < 0 or midi_pitch > 127:
                                continue

                            velocity = note.velocity if hasattr(note, 'velocity') else 80
                            velocity = max(1, min(127, velocity))

                            # Technique
                            technique = detect_technique(note)
                            if is_strum and technique == "normal":
                                technique = "strum"

                            # Strum offset: escalonar ligeramente las notas
                            strum_offset = (note_idx * 0.005) if is_strum else 0

                            string_num = note.string if hasattr(note, 'string') else 0
                            fret_num = note.value if hasattr(note, 'value') else 0

                            notes.append({
                                "onset": round(onset_sec + strum_offset, 4),
                                "offset": round(onset_sec + duration_beat_sec, 4),
                                "pitch": midi_pitch,
                                "velocity": velocity,
                                "string": string_num,
                                "fret": fret_num,
                                "technique": technique,
                                "track": track.name or f"Track {track_idx}",
                            })

                        beat_tick += beat_duration
                current_tick += measure.header.length

            # Calcular duración total
            track_duration = (current_tick / tpq) * (60.0 / tempo)
            duration_sec = max(duration_sec, track_duration)

        if not notes:
            return None

        return {
            "notes": notes,
            "duration_sec": round(duration_sec, 1),
            "tempo": tempo,
            "n_guitar_notes": len(notes),
        }

    except Exception as e:
        log.debug(f"Error parsing {gp_path}: {e}")
        return None


def main():
    parser = argparse.ArgumentParser(description="Generar labels.json desde GPs originales")
    parser.add_argument("--input", required=True, help="Directorio de audio (con level*/hash/meta.json)")
    parser.add_argument("--max-items", type=int, default=0, help="Limitar (0=todos)")
    args = parser.parse_args()

    input_dir = args.input
    progress_file = os.path.join(input_dir, "../labels_progress.json")

    # Encontrar todos los items
    items = []
    for level_dir in sorted(Path(input_dir).glob("level*")):
        for item_dir in sorted(level_dir.iterdir()):
            meta_path = item_dir / "meta.json"
            if item_dir.is_dir() and meta_path.exists():
                items.append(str(item_dir))

    if args.max_items > 0:
        items = items[:args.max_items]

    log.info(f"Items a procesar: {len(items)}")
    log.info(f"Generando labels.json desde archivos GP originales...")

    success = 0
    skipped = 0
    errors = 0
    t_start = time.time()

    for i, item_dir in enumerate(items):
        # Ya tiene labels.json?
        labels_path = os.path.join(item_dir, "labels.json")
        if os.path.exists(labels_path) and os.path.getsize(labels_path) > 100:
            skipped += 1
            continue

        # Leer meta.json para obtener gp_path
        meta_path = os.path.join(item_dir, "meta.json")
        try:
            with open(meta_path) as f:
                meta = json.load(f)
        except:
            errors += 1
            continue

        gp_path = meta.get("gp_path", "")
        if not os.path.exists(gp_path):
            errors += 1
            continue

        # Extraer labels del GP
        labels_data = extract_labels_from_gp(gp_path)
        if labels_data is None:
            errors += 1
            continue

        # Agregar metadata del meta.json
        labels_data["gp_path"] = gp_path
        labels_data["gp_hash"] = meta.get("gp_hash", "")
        labels_data["level"] = meta.get("level", 0)
        labels_data["artist"] = meta.get("artist", "")
        labels_data["title"] = meta.get("title", "")

        # Guardar
        with open(labels_path, "w") as f:
            json.dump(labels_data, f)

        success += 1

        # Progreso cada 100
        if (i + 1) % 100 == 0:
            elapsed = time.time() - t_start
            rate = (success + skipped) / elapsed if elapsed > 0 else 0
            remaining = len(items) - i - 1
            eta = remaining / rate / 60 if rate > 0 else 0
            pct = (i + 1) / len(items) * 100

            log.info(f"  [{pct:.0f}%] {i+1}/{len(items)} | OK: {success} | Skip: {skipped} | Err: {errors} | ETA: {eta:.0f} min")

            with open(progress_file, "w") as f:
                json.dump({
                    "status": "running",
                    "completed": i + 1,
                    "total": len(items),
                    "percent": round(pct, 1),
                    "success": success,
                    "skipped": skipped,
                    "errors": errors,
                }, f)

    elapsed = time.time() - t_start
    log.info(f"\nCompleto en {elapsed:.0f}s:")
    log.info(f"  Labels generados: {success}")
    log.info(f"  Skipped (ya existían): {skipped}")
    log.info(f"  Errores: {errors}")
    log.info(f"  Total items: {len(items)}")


if __name__ == "__main__":
    main()
