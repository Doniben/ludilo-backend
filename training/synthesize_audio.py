#!/usr/bin/env python3
"""
synthesize_audio.py — Sintetiza audio WAV desde archivos Guitar Pro para training.

Pipeline: GP → MIDI (por track de guitarra) → FluidSynth + SoundFont → WAV
Genera múltiples variantes por GP (diferentes soundfonts + augmentation).

Requiere:
    pip install guitarpro pretty_midi midi2audio audiomentations pedalboard numpy
    brew install fluidsynth  (macOS)
    sudo apt-get install fluidsynth  (Linux/A1000)

Uso:
    python synthesize_audio.py --input data/selected_gps.json --output data/audio/
    python synthesize_audio.py --input data/selected_gps.json --output data/audio/ --soundfonts sf2/

Output:
    data/audio/{level}/{gp_hash}/
        mix_sf{N}.wav          — Mezcla completa (para pasar por Demucs)
        guitar_sf{N}.wav       — Solo guitarra (ground truth aislada)
        labels.json            — Notas, posiciones, técnicas (por frame)
"""
import os
import sys
import json
import hashlib
import argparse
import logging
import tempfile
from pathlib import Path
from typing import List, Dict, Optional, Tuple
from dataclasses import dataclass

try:
    import guitarpro
    import pretty_midi
    import numpy as np
except ImportError as e:
    print(f"ERROR: {e}. Instalar dependencias: pip install guitarpro pretty_midi numpy")
    sys.exit(1)

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
log = logging.getLogger(__name__)

# --- Constantes ---

SAMPLE_RATE = 44100             # Para síntesis (luego Demucs re-muestrea a 44100)
GUITAR_PROGRAMS = list(range(24, 32))  # GM Guitar programs
BASS_PROGRAMS = list(range(32, 40))
DRUM_CHANNEL = 9                # GM drums siempre en canal 10 (0-indexed = 9)

# SoundFont default (GeneralUser ya está en el proyecto)
DEFAULT_SOUNDFONTS = [
    # Se buscan en este orden; el usuario puede agregar más con --soundfonts
    "/Users/doniben/Documents/PROGRAMMING-GIT/Ludilo/ludilo-frontend/public/soundfont/GeneralUser.sf2",
    "/usr/share/sounds/sf2/FluidR3_GM.sf2",
    "/usr/share/soundfonts/FluidR3_GM.sf2",
]


@dataclass
class NoteEvent:
    """Una nota extraída del GP con toda su metadata."""
    onset_sec: float
    offset_sec: float
    pitch: int              # MIDI pitch (0-127)
    velocity: int           # 0-127
    string: int             # 1-6 (guitarra) o 0 si no aplica
    fret: int               # 0-24
    technique: str          # "normal", "slide", "hammer", "pull", "bend", "harmonic", "tap"
    track_name: str
    track_index: int


def gp_to_midi(gp_path: str) -> Tuple[pretty_midi.PrettyMIDI, pretty_midi.PrettyMIDI, List[NoteEvent]]:
    """
    Convierte un archivo Guitar Pro a:
    1. MIDI completo (todos los instrumentos) — para síntesis de mezcla
    2. MIDI solo guitarra — para ground truth
    3. Lista de NoteEvents con metadata completa — para labels

    Returns:
        (full_midi, guitar_midi, note_events)
    """
    song = guitarpro.parse(gp_path)
    
    tempo = song.tempo if hasattr(song, 'tempo') else 120
    tpq = 960  # ticks per quarter note estándar
    
    full_midi = pretty_midi.PrettyMIDI(initial_tempo=tempo)
    guitar_midi = pretty_midi.PrettyMIDI(initial_tempo=tempo)
    note_events = []
    
    for track_idx, track in enumerate(song.tracks):
        # Determinar tipo de instrumento
        is_guitar = _is_guitar_track(track)
        is_drum = track.isPercussionTrack if hasattr(track, 'isPercussionTrack') else False
        
        # Programa MIDI
        if is_drum:
            program = 0
            is_drum_flag = True
        else:
            program = _get_program(track)
            is_drum_flag = False
        
        # Crear instrumento MIDI
        instrument = pretty_midi.Instrument(
            program=program,
            is_drum=is_drum_flag,
            name=track.name or f"Track {track_idx}"
        )
        
        # Convertir notas
        current_tick = 0
        for measure in track.measures:
            for voice in measure.voices:
                beat_tick = current_tick
                for beat in voice.beats:
                    beat_duration_ticks = beat.duration.time if hasattr(beat.duration, 'time') else (tpq // beat.duration.value * 4)
                    
                    onset_sec = _ticks_to_seconds(beat_tick, tempo, tpq)
                    duration_sec = _ticks_to_seconds(beat_duration_ticks, tempo, tpq)
                    offset_sec = onset_sec + duration_sec
                    
                    for note in beat.notes:
                        midi_pitch = _note_to_midi(note, track)
                        if midi_pitch < 0 or midi_pitch > 127:
                            continue
                        
                        velocity = note.velocity if hasattr(note, 'velocity') else 80
                        velocity = max(1, min(127, velocity))
                        
                        # Crear nota MIDI
                        midi_note = pretty_midi.Note(
                            velocity=velocity,
                            pitch=midi_pitch,
                            start=onset_sec,
                            end=offset_sec
                        )
                        instrument.notes.append(midi_note)
                        
                        # Extraer metadata completa para guitarra
                        if is_guitar:
                            technique = _detect_technique(note)
                            string_num = note.string if hasattr(note, 'string') else 0
                            fret_num = note.value if hasattr(note, 'value') else 0
                            
                            note_events.append(NoteEvent(
                                onset_sec=round(onset_sec, 4),
                                offset_sec=round(offset_sec, 4),
                                pitch=midi_pitch,
                                velocity=velocity,
                                string=string_num,
                                fret=fret_num,
                                technique=technique,
                                track_name=track.name or f"Track {track_idx}",
                                track_index=track_idx,
                            ))
                    
                    beat_tick += beat_duration_ticks
            
            # Avanzar por el compás
            current_tick += measure.header.length
        
        # Agregar instrumento
        if instrument.notes:
            full_midi.instruments.append(instrument)
            if is_guitar:
                guitar_instrument = pretty_midi.Instrument(
                    program=program, is_drum=False, name=track.name
                )
                guitar_instrument.notes = instrument.notes.copy()
                guitar_midi.instruments.append(guitar_instrument)
    
    return full_midi, guitar_midi, note_events


def _is_guitar_track(track) -> bool:
    """Determina si un track es de guitarra."""
    name = (track.name or "").lower()
    hints = ["guitar", "gtr", "guitarra", "rhythm", "lead", "acoustic", "electric", "clean", "distort"]
    for h in hints:
        if h in name:
            return True
    if hasattr(track, 'strings') and len(track.strings) in (6, 7):
        if "bass" not in name and "bajo" not in name:
            return True
    if hasattr(track, 'channel') and track.channel:
        if track.channel.instrument in GUITAR_PROGRAMS:
            return True
    return False


def _get_program(track) -> int:
    """Obtiene el programa MIDI del track."""
    if hasattr(track, 'channel') and track.channel:
        return track.channel.instrument
    name = (track.name or "").lower()
    if "bass" in name or "bajo" in name:
        return 33  # Finger Bass
    if "distort" in name:
        return 30  # Distortion Guitar
    if "clean" in name:
        return 27  # Electric Guitar Clean
    if "acoustic" in name or "nylon" in name:
        return 24  # Acoustic Nylon
    return 25  # Acoustic Steel (default guitarra)


def _note_to_midi(note, track) -> int:
    """Convierte una nota de Guitar Pro a pitch MIDI."""
    if hasattr(note, 'value') and hasattr(note, 'string'):
        # Usar string + fret para calcular pitch
        if hasattr(track, 'strings') and note.string <= len(track.strings):
            string_midi = track.strings[note.string - 1].value
            return string_midi + note.value
    # Fallback: si tiene realValue
    if hasattr(note, 'realValue'):
        return note.realValue
    return -1


def _ticks_to_seconds(ticks: int, tempo: int, tpq: int) -> float:
    """Convierte ticks MIDI a segundos."""
    return (ticks / tpq) * (60.0 / tempo)


def _detect_technique(note) -> str:
    """Detecta la técnica usada en una nota."""
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
    if hasattr(effect, 'staccato') and effect.staccato:
        return "staccato"
    return "normal"


def synthesize_midi_to_wav(midi_path: str, output_wav: str, soundfont: str) -> bool:
    """Sintetiza un archivo MIDI a WAV usando FluidSynth."""
    import subprocess
    
    cmd = [
        "fluidsynth",
        "-ni",                          # No interactive, no MIDI input
        "-g", "1.0",                    # Gain
        "-r", str(SAMPLE_RATE),         # Sample rate
        soundfont,                      # SoundFont
        midi_path,                      # MIDI input
        "-F", output_wav,               # Output WAV
        "-T", "wav"                     # Format
    ]
    
    try:
        result = subprocess.run(cmd, capture_output=True, text=True, timeout=120)
        if result.returncode != 0:
            log.debug(f"FluidSynth error: {result.stderr[:200]}")
            return False
        return os.path.exists(output_wav) and os.path.getsize(output_wav) > 1000
    except (subprocess.TimeoutExpired, FileNotFoundError) as e:
        log.debug(f"FluidSynth failed: {e}")
        return False


def process_single_gp(gp_info: dict, output_dir: str, soundfonts: List[str]) -> Optional[dict]:
    """
    Procesa un GP completo:
    1. Extrae MIDI (full + guitar only)
    2. Sintetiza con cada soundfont
    3. Guarda labels

    Returns:
        dict con paths generados o None si falla
    """
    gp_path = gp_info["path"]
    level = gp_info["level"]
    
    # Hash único para este GP
    gp_hash = hashlib.md5(gp_path.encode()).hexdigest()[:12]
    item_dir = os.path.join(output_dir, f"level{level}", gp_hash)
    os.makedirs(item_dir, exist_ok=True)
    
    # Ya procesado?
    labels_path = os.path.join(item_dir, "labels.json")
    if os.path.exists(labels_path):
        log.debug(f"Ya procesado: {gp_hash}")
        return {"dir": item_dir, "hash": gp_hash, "skipped": True}
    
    try:
        # Paso 1: GP → MIDI + labels
        full_midi, guitar_midi, note_events = gp_to_midi(gp_path)
        
        if not guitar_midi.instruments or not note_events:
            return None
        
        # Guardar MIDIs
        full_midi_path = os.path.join(item_dir, "full.mid")
        guitar_midi_path = os.path.join(item_dir, "guitar.mid")
        full_midi.write(full_midi_path)
        guitar_midi.write(guitar_midi_path)
        
        # Paso 2: Sintetizar con cada soundfont
        generated_wavs = []
        for sf_idx, sf_path in enumerate(soundfonts):
            if not os.path.exists(sf_path):
                continue
            
            # Mezcla completa (para Demucs)
            mix_wav = os.path.join(item_dir, f"mix_sf{sf_idx}.wav")
            if synthesize_midi_to_wav(full_midi_path, mix_wav, sf_path):
                generated_wavs.append({"type": "mix", "sf": sf_idx, "path": mix_wav})
            
            # Solo guitarra (ground truth de audio)
            guitar_wav = os.path.join(item_dir, f"guitar_sf{sf_idx}.wav")
            if synthesize_midi_to_wav(guitar_midi_path, guitar_wav, sf_path):
                generated_wavs.append({"type": "guitar", "sf": sf_idx, "path": guitar_wav})
        
        if not generated_wavs:
            log.warning(f"No se pudo sintetizar ningún WAV para {gp_hash}")
            return None
        
        # Paso 3: Guardar labels
        labels = {
            "gp_path": gp_path,
            "gp_hash": gp_hash,
            "level": level,
            "artist": gp_info.get("artist", "Unknown"),
            "title": gp_info.get("title", "Unknown"),
            "tempo": gp_info.get("tempo", 120),
            "duration_sec": gp_info.get("duration_sec", 0),
            "notes": [
                {
                    "onset": n.onset_sec,
                    "offset": n.offset_sec,
                    "pitch": n.pitch,
                    "velocity": n.velocity,
                    "string": n.string,
                    "fret": n.fret,
                    "technique": n.technique,
                    "track": n.track_name,
                }
                for n in note_events
            ],
            "generated_wavs": generated_wavs,
        }
        
        with open(labels_path, "w") as f:
            json.dump(labels, f, indent=2)
        
        return {"dir": item_dir, "hash": gp_hash, "n_notes": len(note_events), "n_wavs": len(generated_wavs)}
    
    except Exception as e:
        log.warning(f"Error procesando {gp_path}: {e}")
        return None


def find_soundfonts(sf_dir: Optional[str] = None) -> List[str]:
    """Busca soundfonts disponibles."""
    found = []
    
    # Soundfonts del argumento
    if sf_dir and os.path.isdir(sf_dir):
        for f in os.listdir(sf_dir):
            if f.lower().endswith(('.sf2', '.sf3')):
                found.append(os.path.join(sf_dir, f))
    
    # Soundfonts por defecto
    for sf in DEFAULT_SOUNDFONTS:
        if os.path.exists(sf) and sf not in found:
            found.append(sf)
    
    return found


def main():
    parser = argparse.ArgumentParser(description="Sintetizar audio desde GPs para training")
    parser.add_argument("--input", required=True, help="JSON con GPs seleccionados")
    parser.add_argument("--output", default="training/data/audio", help="Directorio de salida")
    parser.add_argument("--soundfonts", default=None, help="Directorio con soundfonts .sf2")
    parser.add_argument("--max-items", type=int, default=0, help="Máximo de GPs a procesar (0=todos)")
    parser.add_argument("--start-from", type=int, default=0, help="Empezar desde el índice N")
    args = parser.parse_args()
    
    # Cargar selección
    with open(args.input) as f:
        data = json.load(f)
    
    selected = data["selected"]
    log.info(f"GPs a procesar: {len(selected)}")
    
    # Buscar soundfonts
    soundfonts = find_soundfonts(args.soundfonts)
    if not soundfonts:
        log.error("No se encontraron soundfonts. Usa --soundfonts /path/to/sf2/")
        log.error("Necesitas al menos 1 archivo .sf2. Descarga GeneralUser GS de:")
        log.error("  https://schristiancollins.com/generaluser.php")
        sys.exit(1)
    
    log.info(f"SoundFonts disponibles: {len(soundfonts)}")
    for sf in soundfonts:
        log.info(f"  - {sf}")
    
    # Crear directorio de salida
    output_dir = args.output
    os.makedirs(output_dir, exist_ok=True)
    
    # Procesar
    items = selected[args.start_from:]
    if args.max_items > 0:
        items = items[:args.max_items]
    
    log.info(f"Procesando {len(items)} GPs...")
    
    success = 0
    errors = 0
    for i, gp_info in enumerate(items):
        if (i + 1) % 50 == 0:
            log.info(f"  Progreso: {i+1}/{len(items)} ({success} OK, {errors} errores)")
        
        result = process_single_gp(gp_info, output_dir, soundfonts)
        if result:
            success += 1
        else:
            errors += 1
    
    log.info(f"\nSíntesis completa:")
    log.info(f"  Exitosos: {success}")
    log.info(f"  Errores: {errors}")
    log.info(f"  Output: {output_dir}")


if __name__ == "__main__":
    main()
