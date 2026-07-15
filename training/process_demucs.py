#!/usr/bin/env python3
"""
process_demucs.py — Procesa audio sintetizado con Demucs para simular el flujo de producción.

El modelo de training necesita aprender sobre STEMS de Demucs (no audio limpio),
porque eso es lo que verá en producción. Este script:
1. Toma los WAV de mezcla sintetizados
2. Los pasa por Demucs htdemucs_ft (el mismo modelo del worker)
3. Extrae el stem de guitarra
4. Lo guarda junto a los labels originales

Para Nivel 1 (guitarra sola), mezcla con backing tracks aleatorios ANTES de Demucs
para que la separación sea realista.

Requiere:
    pip install demucs torch torchaudio
    GPU recomendada (A1000 con CUDA)

Uso:
    python process_demucs.py --input training/data/audio/ --output training/data/stems/
    python process_demucs.py --input training/data/audio/ --output training/data/stems/ --device cuda
"""
import os
import sys
import json
import shutil
import random
import argparse
import logging
import subprocess
from pathlib import Path
from typing import List, Optional

try:
    import numpy as np
except ImportError:
    print("ERROR: pip install numpy")
    sys.exit(1)

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
log = logging.getLogger(__name__)

# --- Constantes ---

DEMUCS_MODEL = "htdemucs_ft"    # Mismo modelo del worker de Ludilo
STEMS_OF_INTEREST = ["guitar", "other"]  # Demucs output: vocals, drums, bass, other
# htdemucs_ft produce: vocals, drums, bass, other
# Nota: "other" incluye guitarra en htdemucs_ft (4 stems)
# htdemucs_6s produce: vocals, drums, bass, guitar, piano, other
DEMUCS_MODEL_6S = "htdemucs_6s"


def run_demucs(input_wav: str, output_dir: str, model: str = DEMUCS_MODEL,
               device: str = "cuda", two_stems: Optional[str] = None) -> Optional[str]:
    """
    Ejecuta Demucs sobre un archivo WAV.

    Args:
        input_wav: Path al WAV de entrada
        output_dir: Directorio donde Demucs guardará los stems
        model: Modelo de Demucs a usar
        device: "cuda" o "cpu"
        two_stems: Si se especifica, solo separa en 2 (ej: "vocals" separa vocals vs instrumental)

    Returns:
        Path al directorio de stems generados, o None si falla
    """
    cmd = [
        sys.executable, "-m", "demucs",
        "--name", model,
        "-o", output_dir,
        "--device", device,
    ]
    
    if two_stems:
        cmd.extend(["--two-stems", two_stems])
    
    cmd.append(input_wav)
    
    try:
        result = subprocess.run(
            cmd, capture_output=True, text=True, timeout=600  # 10 min max
        )
        if result.returncode != 0:
            log.debug(f"Demucs error: {result.stderr[:300]}")
            return None
        
        # Demucs guarda en: output_dir/model_name/track_name/
        track_name = Path(input_wav).stem
        stems_path = os.path.join(output_dir, model, track_name)
        
        if os.path.isdir(stems_path):
            return stems_path
        return None
    
    except subprocess.TimeoutExpired:
        log.warning(f"Demucs timeout para {input_wav}")
        return None
    except Exception as e:
        log.warning(f"Demucs failed: {e}")
        return None


def mix_with_backing(guitar_wav: str, backing_wavs_dir: str, output_mix: str,
                     guitar_db: float = -3, backing_db: float = -9) -> bool:
    """
    Mezcla un WAV de guitarra sola con un backing track aleatorio.
    Esto es para Nivel 1 (guitarra sola) donde Demucs necesita algo que separar.

    Args:
        guitar_wav: WAV de guitarra sola
        backing_wavs_dir: Directorio con backing tracks (drums+bass de otros MIDIs)
        output_mix: Path de salida para la mezcla
        guitar_db: Nivel de guitarra en la mezcla
        backing_db: Nivel del backing en la mezcla
    """
    try:
        import soundfile as sf

        guitar_audio, sr = sf.read(guitar_wav)
        
        # Buscar un backing aleatorio
        backings = [f for f in os.listdir(backing_wavs_dir) if f.endswith('.wav')]
        if not backings:
            # Sin backing disponible, copiar guitarra como está
            shutil.copy2(guitar_wav, output_mix)
            return True
        
        backing_path = os.path.join(backing_wavs_dir, random.choice(backings))
        backing_audio, sr_b = sf.read(backing_path)
        
        # Asegurar mono
        if len(guitar_audio.shape) > 1:
            guitar_audio = guitar_audio.mean(axis=1)
        if len(backing_audio.shape) > 1:
            backing_audio = backing_audio.mean(axis=1)
        
        # Resample si es necesario (simple repeat/truncate)
        if sr_b != sr:
            # Preferir usar librosa para resample preciso
            import librosa
            backing_audio = librosa.resample(backing_audio, orig_sr=sr_b, target_sr=sr)
        
        # Ajustar longitud
        target_len = len(guitar_audio)
        if len(backing_audio) < target_len:
            # Loop el backing
            repeats = (target_len // len(backing_audio)) + 1
            backing_audio = np.tile(backing_audio, repeats)[:target_len]
        else:
            backing_audio = backing_audio[:target_len]
        
        # Aplicar niveles (dB a linear)
        guitar_gain = 10 ** (guitar_db / 20)
        backing_gain = 10 ** (backing_db / 20)
        
        mix = guitar_audio * guitar_gain + backing_audio * backing_gain
        
        # Normalizar si clipea
        peak = np.max(np.abs(mix))
        if peak > 0.95:
            mix = mix * (0.95 / peak)
        
        sf.write(output_mix, mix, sr)
        return True
    
    except Exception as e:
        log.debug(f"Error mezclando: {e}")
        return False


def process_item(item_dir: str, stems_output_dir: str, device: str,
                 backing_dir: Optional[str] = None, use_6s: bool = True) -> Optional[dict]:
    """
    Procesa un item (un GP sintetizado) con Demucs.

    Args:
        item_dir: Directorio del item (contiene mix_sf*.wav y labels.json)
        stems_output_dir: Directorio donde guardar los stems
        device: "cuda" o "cpu"
        backing_dir: Directorio con backing tracks para mezclar con Nivel 1
        use_6s: Si True, usa htdemucs_6s (6 stems, incluye guitar separado)

    Returns:
        dict con paths de stems generados
    """
    labels_path = os.path.join(item_dir, "labels.json")
    if not os.path.exists(labels_path):
        return None
    
    with open(labels_path) as f:
        labels = json.load(f)
    
    gp_hash = labels["gp_hash"]
    level = labels["level"]
    
    # Directorio de salida para este item
    item_stems_dir = os.path.join(stems_output_dir, f"level{level}", gp_hash)
    
    # Ya procesado?
    stems_meta_path = os.path.join(item_stems_dir, "stems_meta.json")
    if os.path.exists(stems_meta_path):
        log.debug(f"Ya procesado: {gp_hash}")
        return {"hash": gp_hash, "skipped": True}
    
    os.makedirs(item_stems_dir, exist_ok=True)
    
    # Buscar WAVs de mezcla generados
    mix_wavs = sorted([
        f for f in os.listdir(item_dir) if f.startswith("mix_sf") and f.endswith(".wav")
    ])
    
    if not mix_wavs:
        return None
    
    model = DEMUCS_MODEL_6S if use_6s else DEMUCS_MODEL
    stems_results = []
    
    for mix_wav_name in mix_wavs:
        mix_wav_path = os.path.join(item_dir, mix_wav_name)
        sf_id = mix_wav_name.replace("mix_sf", "").replace(".wav", "")
        
        # Para Nivel 1 (guitarra sola): mezclar con backing antes de Demucs
        input_for_demucs = mix_wav_path
        if level == 1 and backing_dir and os.path.isdir(backing_dir):
            mixed_path = os.path.join(item_stems_dir, f"premix_sf{sf_id}.wav")
            if mix_with_backing(mix_wav_path, backing_dir, mixed_path):
                input_for_demucs = mixed_path
        
        # Ejecutar Demucs
        temp_demucs_dir = os.path.join(item_stems_dir, "demucs_temp")
        stems_path = run_demucs(input_for_demucs, temp_demucs_dir, model=model, device=device)
        
        if stems_path:
            # Copiar stem de guitarra al directorio final
            if use_6s:
                guitar_stem = os.path.join(stems_path, "guitar.wav")
            else:
                guitar_stem = os.path.join(stems_path, "other.wav")  # En 4-stem, guitar está en "other"
            
            if os.path.exists(guitar_stem):
                final_stem = os.path.join(item_stems_dir, f"guitar_stem_sf{sf_id}.wav")
                shutil.copy2(guitar_stem, final_stem)
                stems_results.append({
                    "sf_id": sf_id,
                    "stem_path": final_stem,
                    "model": model,
                })
        
        # Limpiar temp
        if os.path.exists(temp_demucs_dir):
            shutil.rmtree(temp_demucs_dir, ignore_errors=True)
    
    if not stems_results:
        return None
    
    # Copiar labels al directorio de stems
    shutil.copy2(labels_path, os.path.join(item_stems_dir, "labels.json"))
    
    # Guardar metadata de stems
    stems_meta = {
        "gp_hash": gp_hash,
        "level": level,
        "demucs_model": model,
        "stems": stems_results,
    }
    with open(stems_meta_path, "w") as f:
        json.dump(stems_meta, f, indent=2)
    
    return {"hash": gp_hash, "n_stems": len(stems_results)}


def main():
    parser = argparse.ArgumentParser(description="Procesar audio con Demucs para training")
    parser.add_argument("--input", required=True, help="Directorio con audio sintetizado")
    parser.add_argument("--output", default="training/data/stems", help="Directorio de salida")
    parser.add_argument("--device", default="cuda", choices=["cuda", "cpu"], help="Dispositivo")
    parser.add_argument("--backing-dir", default=None,
                       help="Directorio con backing tracks para mezclar con guitarra sola (Nivel 1)")
    parser.add_argument("--model", default="6s", choices=["4s", "6s"],
                       help="Modelo Demucs: 4s (htdemucs_ft) o 6s (htdemucs_6s)")
    parser.add_argument("--max-items", type=int, default=0, help="Máximo de items (0=todos)")
    args = parser.parse_args()
    
    use_6s = args.model == "6s"
    input_dir = args.input
    output_dir = args.output
    os.makedirs(output_dir, exist_ok=True)
    
    # Encontrar todos los items
    items = []
    for level_dir in sorted(Path(input_dir).glob("level*")):
        for item_dir in sorted(level_dir.iterdir()):
            if item_dir.is_dir() and (item_dir / "labels.json").exists():
                items.append(str(item_dir))
    
    if args.max_items > 0:
        items = items[:args.max_items]
    
    log.info(f"Items a procesar con Demucs: {len(items)}")
    log.info(f"Modelo: {DEMUCS_MODEL_6S if use_6s else DEMUCS_MODEL}")
    log.info(f"Device: {args.device}")
    log.info(f"Output: {output_dir}")
    
    success = 0
    errors = 0
    skipped = 0
    
    for i, item_dir in enumerate(items):
        if (i + 1) % 20 == 0:
            log.info(f"  Progreso: {i+1}/{len(items)} ({success} OK, {skipped} skip, {errors} err)")
        
        result = process_item(item_dir, output_dir, args.device, args.backing_dir, use_6s)
        if result:
            if result.get("skipped"):
                skipped += 1
            else:
                success += 1
        else:
            errors += 1
    
    log.info(f"\nDemucs processing completo:")
    log.info(f"  Exitosos: {success}")
    log.info(f"  Skipped: {skipped}")
    log.info(f"  Errores: {errors}")
    log.info(f"  Output: {output_dir}")
    
    # Estimación de tiempo
    if success > 0:
        total_remaining = len(items) - success - skipped - errors
        log.info(f"\nNota: Demucs toma ~2-3 min/canción en A1000.")
        log.info(f"  Restantes: {total_remaining} items ≈ {total_remaining * 2.5 / 60:.1f} horas")


if __name__ == "__main__":
    main()
