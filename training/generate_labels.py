#!/usr/bin/env python3
"""
generate_labels.py — Genera matrices de labels (piano-roll) para training de LudiloNet.

Convierte las notas de los labels.json a matrices frame-by-frame compatibles
con el formato de Basic Pitch:
  - contour: [n_frames, 264] — multipitch (3 bins per semitone × 88 semitones)
  - note: [n_frames, 88] — nota activa (1 bin per semitone)
  - onset: [n_frames, 88] — onset (1 bin per semitone)
  - string_fret: [n_frames, 150] — posición en diapasón (6 cuerdas × 25 trastes)
  - technique: [n_frames, 5] — técnica (normal, slide, hammer, pull, bend)

Requiere:
    pip install numpy librosa

Uso:
    python generate_labels.py --input training/data/stems/ --output training/data/dataset/
"""
import os
import sys
import json
import argparse
import logging
from pathlib import Path
from typing import List, Dict, Tuple

try:
    import numpy as np
    import librosa
except ImportError as e:
    print(f"ERROR: {e}. pip install numpy librosa")
    sys.exit(1)

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
log = logging.getLogger(__name__)

# --- Constantes (matching Basic Pitch) ---

AUDIO_SAMPLE_RATE = 22050
FFT_HOP = 256
ANNOTATIONS_FPS = AUDIO_SAMPLE_RATE // FFT_HOP     # ~86 frames/sec
AUDIO_WINDOW_LENGTH = 2                             # seconds per training example
ANNOT_N_FRAMES = ANNOTATIONS_FPS * AUDIO_WINDOW_LENGTH  # 172 frames per window

# Pitch range
ANNOTATIONS_BASE_FREQUENCY = 27.5   # A0 (MIDI 21)
ANNOTATIONS_N_SEMITONES = 88        # Piano keys A0-C8
MIDI_OFFSET = 21                    # MIDI note 21 = A0 = index 0

# Contour: 3 bins per semitone (matching BP)
CONTOURS_BINS_PER_SEMITONE = 3
N_CONTOUR_BINS = ANNOTATIONS_N_SEMITONES * CONTOURS_BINS_PER_SEMITONE  # 264

# Tablatura
N_STRINGS = 6
N_FRETS = 25    # 0 (open) to 24
N_STRING_FRET_BINS = N_STRINGS * N_FRETS  # 150

# Técnicas
TECHNIQUES = ["normal", "slide", "hammer", "pull", "bend"]
N_TECHNIQUE_BINS = len(TECHNIQUES)
TECHNIQUE_TO_IDX = {t: i for i, t in enumerate(TECHNIQUES)}

# Onset spread: cuántos frames alrededor del onset marcar (gaussian-like)
ONSET_SPREAD_FRAMES = 1  # ±1 frame alrededor del onset


def notes_to_frames(notes: List[dict], duration_sec: float) -> Dict[str, np.ndarray]:
    """
    Convierte lista de notas a matrices frame-by-frame.

    Args:
        notes: Lista de dicts con {onset, offset, pitch, velocity, string, fret, technique}
        duration_sec: Duración total del audio en segundos

    Returns:
        Dict con matrices: contour, note, onset, string_fret, technique
    """
    n_frames = int(np.ceil(duration_sec * ANNOTATIONS_FPS))
    
    # Inicializar matrices
    contour = np.zeros((n_frames, N_CONTOUR_BINS), dtype=np.float32)
    note = np.zeros((n_frames, ANNOTATIONS_N_SEMITONES), dtype=np.float32)
    onset = np.zeros((n_frames, ANNOTATIONS_N_SEMITONES), dtype=np.float32)
    string_fret = np.zeros((n_frames, N_STRING_FRET_BINS), dtype=np.float32)
    technique = np.zeros((n_frames, N_TECHNIQUE_BINS), dtype=np.float32)
    
    for n in notes:
        pitch = n["pitch"]
        
        # Validar rango
        pitch_idx = pitch - MIDI_OFFSET
        if pitch_idx < 0 or pitch_idx >= ANNOTATIONS_N_SEMITONES:
            continue
        
        # Frames de onset y offset
        onset_frame = int(n["onset"] * ANNOTATIONS_FPS)
        offset_frame = int(n["offset"] * ANNOTATIONS_FPS)
        
        if onset_frame >= n_frames:
            continue
        offset_frame = min(offset_frame, n_frames - 1)
        
        # Velocity normalizada como peso (0-1)
        vel_weight = n.get("velocity", 80) / 127.0
        
        # --- Note matrix ---
        # Marca 1.0 desde onset hasta offset
        note[onset_frame:offset_frame + 1, pitch_idx] = vel_weight
        
        # --- Onset matrix ---
        # Marca 1.0 en el frame de onset (con spread opcional)
        for spread in range(-ONSET_SPREAD_FRAMES, ONSET_SPREAD_FRAMES + 1):
            f = onset_frame + spread
            if 0 <= f < n_frames:
                weight = 1.0 if spread == 0 else 0.5
                onset[f, pitch_idx] = max(onset[f, pitch_idx], weight)
        
        # --- Contour matrix (3 bins per semitone) ---
        # El bin central es pitch_idx * 3 + 1
        contour_center = pitch_idx * CONTOURS_BINS_PER_SEMITONE + 1
        for frame in range(onset_frame, min(offset_frame + 1, n_frames)):
            # Bin central = activación completa
            contour[frame, contour_center] = vel_weight
            # Bins adyacentes = activación parcial (para pitch refinado)
            if contour_center > 0:
                contour[frame, contour_center - 1] = vel_weight * 0.25
            if contour_center < N_CONTOUR_BINS - 1:
                contour[frame, contour_center + 1] = vel_weight * 0.25
        
        # --- String/Fret matrix ---
        string_num = n.get("string", 0)
        fret_num = n.get("fret", 0)
        if 1 <= string_num <= N_STRINGS and 0 <= fret_num < N_FRETS:
            sf_idx = (string_num - 1) * N_FRETS + fret_num
            for frame in range(onset_frame, min(offset_frame + 1, n_frames)):
                string_fret[frame, sf_idx] = 1.0
        
        # --- Technique matrix ---
        tech = n.get("technique", "normal")
        # Mapear técnicas similares
        if tech in ("hammer", "pull"):
            tech_idx = TECHNIQUE_TO_IDX.get(tech, 0)
        elif tech in ("harmonic", "trill", "staccato", "tap"):
            tech_idx = 0  # Mapear a "normal" por ahora
        else:
            tech_idx = TECHNIQUE_TO_IDX.get(tech, 0)
        
        for frame in range(onset_frame, min(offset_frame + 1, n_frames)):
            technique[frame, tech_idx] = 1.0
    
    return {
        "contour": contour,
        "note": note,
        "onset": onset,
        "string_fret": string_fret,
        "technique": technique,
    }


def create_training_windows(audio_path: str, labels_matrices: Dict[str, np.ndarray],
                           window_sec: float = AUDIO_WINDOW_LENGTH,
                           hop_sec: float = 1.0) -> List[Dict]:
    """
    Divide el audio y labels en ventanas de tamaño fijo para training.

    Args:
        audio_path: Path al archivo de audio (stem de Demucs)
        labels_matrices: Matrices de labels completas
        window_sec: Duración de cada ventana en segundos
        hop_sec: Desplazamiento entre ventanas

    Returns:
        Lista de dicts con {audio_window, labels_window} indexados por frame
    """
    # Cargar audio
    audio, sr = librosa.load(audio_path, sr=AUDIO_SAMPLE_RATE, mono=True)
    
    # Parámetros de ventana
    window_samples = int(window_sec * AUDIO_SAMPLE_RATE) - FFT_HOP  # Matching BP: AUDIO_N_SAMPLES
    hop_samples = int(hop_sec * AUDIO_SAMPLE_RATE)
    window_frames = int(window_sec * ANNOTATIONS_FPS)
    hop_frames = int(hop_sec * ANNOTATIONS_FPS)
    
    windows = []
    n_frames_total = labels_matrices["note"].shape[0]
    
    audio_pos = 0
    frame_pos = 0
    
    while audio_pos + window_samples <= len(audio) and frame_pos + window_frames <= n_frames_total:
        # Audio window
        audio_window = audio[audio_pos:audio_pos + window_samples]
        
        # Labels windows
        labels_window = {}
        for key, matrix in labels_matrices.items():
            labels_window[key] = matrix[frame_pos:frame_pos + window_frames]
        
        # Verificar que hay contenido (no ventanas vacías)
        if np.any(labels_window["note"] > 0):
            windows.append({
                "audio": audio_window,
                "labels": labels_window,
                "start_sec": audio_pos / AUDIO_SAMPLE_RATE,
            })
        
        audio_pos += hop_samples
        frame_pos += hop_frames
    
    return windows


def process_item(item_dir: str, output_dir: str) -> Optional[dict]:
    """
    Procesa un item completo: genera labels y divide en ventanas de training.

    Args:
        item_dir: Directorio del item (con labels.json y stems)
        output_dir: Directorio de salida para el dataset

    Returns:
        dict con estadísticas o None
    """
    labels_path = os.path.join(item_dir, "labels.json")
    if not os.path.exists(labels_path):
        return None
    
    with open(labels_path) as f:
        labels = json.load(f)
    
    gp_hash = labels["gp_hash"]
    level = labels["level"]
    notes = labels["notes"]
    duration = labels["duration_sec"]
    
    if not notes or duration <= 0:
        return None
    
    # Buscar stems disponibles
    stem_files = [f for f in os.listdir(item_dir) if f.startswith("guitar_stem") and f.endswith(".wav")]
    if not stem_files:
        return None
    
    # Generar matrices de labels
    label_matrices = notes_to_frames(notes, duration)
    
    # Procesar cada stem (cada soundfont variant)
    total_windows = 0
    item_output_dir = os.path.join(output_dir, f"level{level}", gp_hash)
    os.makedirs(item_output_dir, exist_ok=True)
    
    for stem_file in stem_files:
        stem_path = os.path.join(item_dir, stem_file)
        sf_id = stem_file.replace("guitar_stem_sf", "").replace(".wav", "")
        
        try:
            # Dividir en ventanas
            windows = create_training_windows(stem_path, label_matrices)
            
            # Guardar cada ventana como un ejemplo de training
            for w_idx, window in enumerate(windows):
                example_path = os.path.join(item_output_dir, f"sf{sf_id}_w{w_idx:04d}.npz")
                
                np.savez_compressed(
                    example_path,
                    audio=window["audio"],
                    contour=window["labels"]["contour"],
                    note=window["labels"]["note"],
                    onset=window["labels"]["onset"],
                    string_fret=window["labels"]["string_fret"],
                    technique=window["labels"]["technique"],
                    # Metadata
                    start_sec=np.float32(window["start_sec"]),
                    level=np.int32(level),
                )
                total_windows += 1
        
        except Exception as e:
            log.debug(f"Error procesando {stem_path}: {e}")
            continue
    
    if total_windows == 0:
        return None
    
    return {"hash": gp_hash, "level": level, "windows": total_windows}


def create_split_manifest(dataset_dir: str, train_ratio: float = 0.8,
                          val_ratio: float = 0.1) -> Dict:
    """
    Crea manifest de train/val/test split.
    Split por item (no por ventana) para evitar data leakage.
    """
    # Recoger todos los items
    items_by_level = {1: [], 2: [], 3: []}
    
    for level_dir in sorted(Path(dataset_dir).glob("level*")):
        level = int(level_dir.name.replace("level", ""))
        for item_dir in sorted(level_dir.iterdir()):
            if item_dir.is_dir():
                npz_files = list(item_dir.glob("*.npz"))
                if npz_files:
                    items_by_level[level].append({
                        "hash": item_dir.name,
                        "level": level,
                        "files": [str(f) for f in sorted(npz_files)],
                        "n_windows": len(npz_files),
                    })
    
    # Split estratificado por nivel
    manifest = {"train": [], "val": [], "test": []}
    
    for level, items in items_by_level.items():
        np.random.shuffle(items)
        n = len(items)
        n_train = int(n * train_ratio)
        n_val = int(n * val_ratio)
        
        manifest["train"].extend(items[:n_train])
        manifest["val"].extend(items[n_train:n_train + n_val])
        manifest["test"].extend(items[n_train + n_val:])
    
    # Estadísticas
    stats = {}
    for split, items in manifest.items():
        total_windows = sum(i["n_windows"] for i in items)
        stats[split] = {"items": len(items), "windows": total_windows}
    
    # Guardar
    manifest_path = os.path.join(dataset_dir, "manifest.json")
    with open(manifest_path, "w") as f:
        json.dump({"splits": manifest, "stats": stats}, f, indent=2)
    
    return stats


def main():
    parser = argparse.ArgumentParser(description="Generar labels de training para LudiloNet")
    parser.add_argument("--input", required=True, help="Directorio con stems procesados")
    parser.add_argument("--output", default="training/data/dataset", help="Directorio de salida")
    parser.add_argument("--max-items", type=int, default=0, help="Máximo de items (0=todos)")
    parser.add_argument("--window-sec", type=float, default=2.0, help="Ventana de training (seg)")
    parser.add_argument("--hop-sec", type=float, default=1.0, help="Hop entre ventanas (seg)")
    args = parser.parse_args()
    
    input_dir = args.input
    output_dir = args.output
    os.makedirs(output_dir, exist_ok=True)
    
    # Encontrar items
    items = []
    for level_dir in sorted(Path(input_dir).glob("level*")):
        for item_dir in sorted(level_dir.iterdir()):
            if item_dir.is_dir() and (item_dir / "labels.json").exists():
                items.append(str(item_dir))
    
    if args.max_items > 0:
        items = items[:args.max_items]
    
    log.info(f"Items a procesar: {len(items)}")
    log.info(f"Ventana: {args.window_sec}s, Hop: {args.hop_sec}s")
    log.info(f"Output: {output_dir}")
    
    # Procesar
    success = 0
    total_windows = 0
    errors = 0
    
    for i, item_dir in enumerate(items):
        if (i + 1) % 50 == 0:
            log.info(f"  Progreso: {i+1}/{len(items)} ({success} OK, {total_windows} windows)")
        
        result = process_item(item_dir, output_dir)
        if result:
            success += 1
            total_windows += result["windows"]
        else:
            errors += 1
    
    log.info(f"\nLabel generation completa:")
    log.info(f"  Items procesados: {success}")
    log.info(f"  Total ventanas de training: {total_windows}")
    log.info(f"  Errores: {errors}")
    
    # Crear splits
    log.info("\nCreando train/val/test splits...")
    stats = create_split_manifest(output_dir)
    for split, s in stats.items():
        log.info(f"  {split}: {s['items']} items, {s['windows']} windows")
    
    # Estimación
    hours_of_data = total_windows * args.window_sec / 3600
    log.info(f"\n  Total horas de datos: {hours_of_data:.1f}h")
    log.info(f"  Tamaño estimado en disco: {total_windows * 0.35:.0f} MB (comprimido)")


if __name__ == "__main__":
    main()
