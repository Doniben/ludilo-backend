#!/usr/bin/env python3
"""
run_synthesis.py — Sintetiza audio desde GPs en paralelo con FluidSynth.

Pipeline por canción:
  GP → PyGuitarPro → MIDI → FluidSynth → WAV temporal → ffmpeg → MP3 320kbps → borra WAV

Paraleliza con multiprocessing (4 workers por defecto).
Guarda progreso en progress.json para monitoreo.

Uso:
    python run_synthesis.py
    python run_synthesis.py --workers 6 --start-from 500
"""
import os
import sys
import json
import time
import hashlib
import argparse
import subprocess
import tempfile
import logging
from pathlib import Path
from multiprocessing import Pool, Manager, Lock
from dataclasses import dataclass

sys.path.insert(0, os.path.dirname(__file__))

try:
    import guitarpro
    import pretty_midi
except ImportError as e:
    print(f"ERROR: {e}")
    sys.exit(1)

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
log = logging.getLogger(__name__)

# --- Config ---
SOUNDFONT = "/tmp/ludilo-training/soundfonts/extracted/GeneralUser GS 1.471/GeneralUser GS v1.471.sf2"
SAMPLE_RATE = 44100
MP3_BITRATE = "320k"
OUTPUT_DIR = "/Users/doniben/Documents/PROGRAMMING-GIT/Ludilo/ludilo-backend/training/data/audio"
PROGRESS_FILE = "/Users/doniben/Documents/PROGRAMMING-GIT/Ludilo/ludilo-backend/training/data/synthesis_progress.json"

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


def gp_to_midi_file(gp_path: str, midi_path: str, guitar_only: bool = False) -> bool:
    """Convierte GP a archivo MIDI."""
    try:
        song = guitarpro.parse(gp_path)
        tempo = song.tempo if hasattr(song, 'tempo') else 120
        tpq = 960

        midi = pretty_midi.PrettyMIDI(initial_tempo=tempo)

        for track_idx, track in enumerate(song.tracks):
            if guitar_only and not is_guitar_track(track):
                continue

            is_drum = track.isPercussionTrack if hasattr(track, 'isPercussionTrack') else False
            program = track.channel.instrument if hasattr(track, 'channel') and track.channel else 25

            instrument = pretty_midi.Instrument(
                program=program if not is_drum else 0,
                is_drum=is_drum,
                name=track.name or f"Track {track_idx}"
            )

            current_tick = 0
            for measure in track.measures:
                for voice in measure.voices:
                    beat_tick = current_tick
                    for beat in voice.beats:
                        beat_duration = int(tpq * 4 / beat.duration.value)
                        if beat.duration.isDotted:
                            beat_duration = int(beat_duration * 1.5)

                        onset_sec = (beat_tick / tpq) * (60.0 / tempo)
                        duration_sec = (beat_duration / tpq) * (60.0 / tempo)

                        for note in beat.notes:
                            if hasattr(track, 'strings') and note.string <= len(track.strings):
                                midi_pitch = track.strings[note.string - 1].value + note.value
                            else:
                                continue
                            if midi_pitch < 0 or midi_pitch > 127:
                                continue

                            velocity = note.velocity if hasattr(note, 'velocity') else 80
                            velocity = max(1, min(127, velocity))

                            midi_note = pretty_midi.Note(
                                velocity=velocity, pitch=midi_pitch,
                                start=onset_sec, end=onset_sec + duration_sec
                            )
                            instrument.notes.append(midi_note)

                        beat_tick += beat_duration
                current_tick += measure.header.length

            if instrument.notes:
                midi.instruments.append(instrument)

        if not midi.instruments:
            return False

        midi.write(midi_path)
        return True

    except Exception as e:
        return False


def synthesize_one(args):
    """Procesa una canción: GP → MIDI → WAV → MP3."""
    idx, gp_info, output_dir, soundfont, progress_dict, lock = args

    gp_path = gp_info["path"]
    level = gp_info["level"]
    gp_hash = hashlib.md5(gp_path.encode()).hexdigest()[:12]

    # Output dir para este item
    item_dir = os.path.join(output_dir, f"level{level}", gp_hash)
    os.makedirs(item_dir, exist_ok=True)

    # Ya procesado?
    mix_mp3 = os.path.join(item_dir, "mix.mp3")
    if os.path.exists(mix_mp3) and os.path.getsize(mix_mp3) > 10000:
        with lock:
            progress_dict["completed"] += 1
            progress_dict["skipped"] += 1
        return {"hash": gp_hash, "status": "skipped"}

    try:
        # Paso 1: GP → MIDI (mix completo)
        midi_path = os.path.join(item_dir, "full.mid")
        if not gp_to_midi_file(gp_path, midi_path, guitar_only=False):
            with lock:
                progress_dict["completed"] += 1
                progress_dict["errors"] += 1
            return {"hash": gp_hash, "status": "error_midi"}

        # Paso 2: MIDI → WAV (FluidSynth)
        wav_path = os.path.join(item_dir, "mix_temp.wav")
        cmd_synth = [
            "fluidsynth", "-ni", "-g", "1.0", "-r", str(SAMPLE_RATE),
            "-F", wav_path, soundfont, midi_path
        ]
        result = subprocess.run(cmd_synth, capture_output=True, text=True, timeout=300)
        if result.returncode != 0 or not os.path.exists(wav_path):
            with lock:
                progress_dict["completed"] += 1
                progress_dict["errors"] += 1
            return {"hash": gp_hash, "status": "error_synth"}

        # Paso 3: WAV → MP3 320kbps
        cmd_mp3 = [
            "ffmpeg", "-y", "-i", wav_path,
            "-codec:a", "libmp3lame", "-b:a", MP3_BITRATE,
            "-ar", "44100", mix_mp3
        ]
        result = subprocess.run(cmd_mp3, capture_output=True, text=True, timeout=120)

        # Borrar WAV temporal
        if os.path.exists(wav_path):
            os.remove(wav_path)

        if result.returncode != 0 or not os.path.exists(mix_mp3):
            with lock:
                progress_dict["completed"] += 1
                progress_dict["errors"] += 1
            return {"hash": gp_hash, "status": "error_mp3"}

        # Paso 4: Guardar metadata
        meta = {
            "gp_path": gp_path,
            "gp_hash": gp_hash,
            "level": level,
            "artist": gp_info.get("artist", ""),
            "title": gp_info.get("title", ""),
            "tempo": gp_info.get("tempo", 120),
            "mp3_path": mix_mp3,
            "soundfont": "GeneralUser_GS_v1.471",
        }
        with open(os.path.join(item_dir, "meta.json"), "w") as f:
            json.dump(meta, f)

        # Actualizar progreso
        mp3_size = os.path.getsize(mix_mp3)
        with lock:
            progress_dict["completed"] += 1
            progress_dict["success"] += 1
            progress_dict["total_mb"] += mp3_size / 1e6

        return {"hash": gp_hash, "status": "ok", "size_mb": mp3_size / 1e6}

    except subprocess.TimeoutExpired:
        with lock:
            progress_dict["completed"] += 1
            progress_dict["errors"] += 1
        # Limpiar WAV temporal si existe
        wav_path = os.path.join(item_dir, "mix_temp.wav")
        if os.path.exists(wav_path):
            os.remove(wav_path)
        return {"hash": gp_hash, "status": "timeout"}
    except Exception as e:
        with lock:
            progress_dict["completed"] += 1
            progress_dict["errors"] += 1
        return {"hash": gp_hash, "status": f"error: {str(e)[:50]}"}


def progress_writer(progress_dict, total, start_time):
    """Escribe progreso a archivo JSON."""
    elapsed = time.time() - start_time
    completed = progress_dict["completed"]
    rate = completed / elapsed if elapsed > 0 else 0
    remaining = total - completed
    eta_min = (remaining / rate / 60) if rate > 0 else 0

    data = {
        "status": "running" if completed < total else "completed",
        "completed": completed,
        "total": total,
        "percent": round(completed / total * 100, 1),
        "success": progress_dict["success"],
        "skipped": progress_dict["skipped"],
        "errors": progress_dict["errors"],
        "total_mb": round(progress_dict["total_mb"], 1),
        "elapsed_sec": round(elapsed, 1),
        "rate_per_min": round(rate * 60, 1),
        "eta_minutes": round(eta_min, 1),
        "last_update": time.strftime("%H:%M:%S"),
    }
    with open(PROGRESS_FILE, "w") as f:
        json.dump(data, f, indent=2)


def main():
    parser = argparse.ArgumentParser(description="Sintetizar audio en paralelo")
    parser.add_argument("--workers", type=int, default=4, help="Procesos paralelos")
    parser.add_argument("--start-from", type=int, default=0, help="Empezar desde índice N")
    parser.add_argument("--max-items", type=int, default=0, help="Máximo items (0=todos)")
    parser.add_argument("--soundfont", default=SOUNDFONT, help="Path al soundfont")
    args = parser.parse_args()

    # Verificar soundfont
    if not os.path.exists(args.soundfont):
        log.error(f"SoundFont no encontrado: {args.soundfont}")
        sys.exit(1)

    # Cargar selección
    selected_path = Path(__file__).parent / "data" / "selected_gps.json"
    with open(selected_path) as f:
        data = json.load(f)

    items = data["selected"][args.start_from:]
    if args.max_items > 0:
        items = items[:args.max_items]

    total = len(items)
    log.info(f"=" * 60)
    log.info(f"Síntesis de audio — LudiloNet Training Data")
    log.info(f"=" * 60)
    log.info(f"  Canciones: {total}")
    log.info(f"  Workers: {args.workers}")
    log.info(f"  SoundFont: {os.path.basename(args.soundfont)}")
    log.info(f"  Output: {OUTPUT_DIR}")
    log.info(f"  Progreso: {PROGRESS_FILE}")
    log.info(f"  Formato: MP3 {MP3_BITRATE}")
    log.info(f"")

    os.makedirs(OUTPUT_DIR, exist_ok=True)

    # Shared progress dict
    manager = Manager()
    progress_dict = manager.dict({
        "completed": 0, "success": 0, "skipped": 0, "errors": 0, "total_mb": 0.0
    })
    lock = manager.Lock()

    # Preparar argumentos para cada worker
    work_args = [
        (i, item, OUTPUT_DIR, args.soundfont, progress_dict, lock)
        for i, item in enumerate(items)
    ]

    start_time = time.time()

    # Lanzar pool
    with Pool(processes=args.workers) as pool:
        results_iter = pool.imap_unordered(synthesize_one, work_args, chunksize=4)

        for i, result in enumerate(results_iter):
            # Escribir progreso cada 10 completados
            if (i + 1) % 10 == 0:
                progress_writer(progress_dict, total, start_time)

            # Log cada 50
            if (i + 1) % 50 == 0:
                elapsed = time.time() - start_time
                rate = (i + 1) / elapsed * 60
                pct = progress_dict["completed"] / total * 100
                log.info(f"  [{pct:.0f}%] {progress_dict['completed']}/{total} "
                         f"| OK: {progress_dict['success']} "
                         f"| Skip: {progress_dict['skipped']} "
                         f"| Err: {progress_dict['errors']} "
                         f"| {progress_dict['total_mb']:.0f}MB "
                         f"| {rate:.1f}/min")

    # Final
    elapsed = time.time() - start_time
    progress_writer(progress_dict, total, start_time)

    log.info(f"\n{'=' * 60}")
    log.info(f"SÍNTESIS COMPLETA")
    log.info(f"{'=' * 60}")
    log.info(f"  Exitosos: {progress_dict['success']}")
    log.info(f"  Skipped: {progress_dict['skipped']}")
    log.info(f"  Errores: {progress_dict['errors']}")
    log.info(f"  Total MP3: {progress_dict['total_mb']:.0f} MB")
    log.info(f"  Tiempo: {elapsed/3600:.1f} horas")
    log.info(f"  Output: {OUTPUT_DIR}")


if __name__ == "__main__":
    main()
