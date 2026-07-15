#!/usr/bin/env python3
"""
select_training_gps.py — Selecciona y clasifica archivos Guitar Pro para training de LudiloNet.

Analiza los 66K GPs en Blob Storage (o locales) y selecciona los mejores candidatos
para el dataset de entrenamiento, clasificándolos en 3 niveles de dificultad.

Requiere:
    pip install guitarpro azure-storage-blob

Uso:
    python select_training_gps.py --source local --gp-dir "/path/to/gps"
    python select_training_gps.py --source blob --container library

Output:
    training/data/selected_gps.json — Lista de GPs seleccionados con metadata
"""
import os
import sys
import json
import argparse
import logging
from pathlib import Path
from collections import defaultdict
from dataclasses import dataclass, asdict
from typing import Optional, List, Tuple

try:
    import guitarpro
except ImportError:
    print("ERROR: pip install guitarpro")
    sys.exit(1)

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
log = logging.getLogger(__name__)

# --- Constantes ---

MIN_FILE_SIZE = 5_000           # bytes — GPs < 5KB suelen estar incompletos
MIN_NOTES_GUITAR = 50           # al menos 50 notas en pistas de guitarra
MIN_DURATION_SEC = 60           # mínimo 1 minuto
MAX_DURATION_SEC = 600          # máximo 10 minutos
TARGET_PER_LEVEL = {
    1: 800,     # Guitarra sola / dúo acústico
    2: 500,     # Trío, mezcla moderada
    3: 400,     # Banda completa, complejidad alta
}

GUITAR_PROGRAMS = range(24, 32)   # GM: Acoustic Nylon=24 ... Guitar Harmonics=31
BASS_PROGRAMS = range(32, 40)     # GM: Acoustic Bass=32 ... Synth Bass 2=39

# Tipos de pista que consideramos "guitarra"
GUITAR_TRACK_HINTS = [
    "guitar", "gtr", "guitarra", "guit", "rhythm", "lead", "acustic",
    "acoustic", "electric", "clean", "distort", "overdriv"
]


@dataclass
class GPInfo:
    """Metadata extraída de un archivo Guitar Pro."""
    path: str
    size_bytes: int
    artist: str
    title: str
    tempo: int
    duration_sec: float
    time_signatures: List[str]
    n_tracks: int
    n_guitar_tracks: int
    n_other_tracks: int
    total_guitar_notes: int
    max_polyphony: int
    has_techniques: bool    # slide, hammer, bend, etc.
    tunings: List[str]
    level: int              # 1, 2, 3
    level_reason: str


def is_guitar_track(track) -> bool:
    """Determina si un track de Guitar Pro es de guitarra."""
    name = track.name.lower()
    
    # Chequear por nombre
    for hint in GUITAR_TRACK_HINTS:
        if hint in name:
            return True
    
    # Chequear por canal MIDI (program change)
    if hasattr(track, 'channel') and track.channel:
        program = track.channel.instrument
        if program in GUITAR_PROGRAMS:
            return True
    
    # Si tiene cuerdas definidas (6 o 7 cuerdas típico de guitarra)
    if hasattr(track, 'strings') and len(track.strings) in (6, 7):
        # Verificar que no sea bajo (4-5 cuerdas, pero algunos bajos tienen 6)
        if "bass" not in name and "bajo" not in name:
            return True
    
    return False


def count_notes_and_polyphony(track) -> Tuple[int, int]:
    """Cuenta notas y polifonía máxima en un track."""
    total_notes = 0
    max_poly = 0
    
    for measure in track.measures:
        for voice in measure.voices:
            for beat in voice.beats:
                n_notes = len(beat.notes)
                total_notes += n_notes
                if n_notes > max_poly:
                    max_poly = n_notes
    
    return total_notes, max_poly


def has_advanced_techniques(track) -> bool:
    """Detecta si un track usa técnicas avanzadas."""
    for measure in track.measures:
        for voice in measure.voices:
            for beat in voice.beats:
                for note in beat.notes:
                    effect = note.effect
                    if hasattr(effect, 'slide') and effect.slide:
                        return True
                    if hasattr(effect, 'hammer') and effect.hammer:
                        return True
                    if hasattr(effect, 'bend') and effect.bend:
                        return True
                    if hasattr(effect, 'harmonic') and effect.harmonic:
                        return True
                    if hasattr(effect, 'trill') and effect.trill:
                        return True
    return False


def get_tuning_str(track) -> str:
    """Obtiene la afinación del track como string."""
    if hasattr(track, 'strings') and track.strings:
        notes = []
        note_names = ['C', 'C#', 'D', 'D#', 'E', 'F', 'F#', 'G', 'G#', 'A', 'A#', 'B']
        for s in track.strings:
            midi_val = s.value
            name = note_names[midi_val % 12]
            octave = midi_val // 12 - 1
            notes.append(f"{name}{octave}")
        return ",".join(notes)
    return "standard"


def calculate_duration(song) -> float:
    """Calcula la duración aproximada del GP en segundos."""
    if not song.tracks or not song.tracks[0].measures:
        return 0
    
    total_ticks = 0
    for measure in song.tracks[0].measures:
        header = measure.header
        total_ticks += header.length
    
    # Tempo del header (puede cambiar, usamos el primero)
    tempo = song.tempo if hasattr(song, 'tempo') else 120
    
    # Ticks per quarter = song.ticksPerQuarterNote (default 960)
    tpq = 960
    if hasattr(song, 'ticksPerQuarterNote'):
        tpq = song.ticksPerQuarterNote
    
    duration_sec = (total_ticks / tpq) * (60.0 / tempo)
    return duration_sec


def classify_level(n_guitar_tracks: int, n_other_tracks: int, tempo: int,
                   max_poly: int, has_tech: bool, total_notes: int) -> Tuple[int, str]:
    """Clasifica un GP en nivel 1, 2 o 3."""
    total_tracks = n_guitar_tracks + n_other_tracks
    
    # Nivel 3: Banda completa, complejidad alta
    if total_tracks >= 4 and (tempo > 140 or has_tech or max_poly >= 6):
        return 3, f"tracks={total_tracks}, tempo={tempo}, poly={max_poly}, tech={has_tech}"
    
    # Nivel 3: Shred / muchas notas
    if tempo > 160 or total_notes > 2000:
        return 3, f"tempo={tempo}, notes={total_notes}"
    
    # Nivel 2: Moderado
    if total_tracks >= 3 or (tempo > 120 and max_poly >= 4) or n_guitar_tracks >= 2:
        return 2, f"tracks={total_tracks}, guitars={n_guitar_tracks}, tempo={tempo}"
    
    # Nivel 1: Simple
    return 1, f"tracks={total_tracks}, guitars={n_guitar_tracks}, tempo={tempo}, poly={max_poly}"


def analyze_gp(filepath: str) -> Optional[GPInfo]:
    """Analiza un archivo GP y extrae su metadata."""
    try:
        size = os.path.getsize(filepath)
        if size < MIN_FILE_SIZE:
            return None
        
        song = guitarpro.parse(filepath)
        
        # Metadata básica
        artist = song.artist or "Unknown"
        title = song.title or Path(filepath).stem
        tempo = song.tempo if hasattr(song, 'tempo') else 120
        
        # Duración
        duration = calculate_duration(song)
        if duration < MIN_DURATION_SEC or duration > MAX_DURATION_SEC:
            return None
        
        # Time signatures
        time_sigs = set()
        for track in song.tracks:
            for measure in track.measures:
                ts = measure.header.timeSignature
                time_sigs.add(f"{ts.numerator}/{ts.denominator.value}")
                break  # solo primer compás por track
        
        # Analizar tracks
        n_guitar = 0
        n_other = 0
        total_guitar_notes = 0
        max_poly = 0
        has_tech = False
        tunings = []
        
        for track in song.tracks:
            if is_guitar_track(track):
                n_guitar += 1
                notes, poly = count_notes_and_polyphony(track)
                total_guitar_notes += notes
                max_poly = max(max_poly, poly)
                if not has_tech:
                    has_tech = has_advanced_techniques(track)
                tunings.append(get_tuning_str(track))
            else:
                n_other += 1
        
        if total_guitar_notes < MIN_NOTES_GUITAR:
            return None
        
        if n_guitar == 0:
            return None
        
        # Clasificar nivel
        level, reason = classify_level(
            n_guitar, n_other, tempo, max_poly, has_tech, total_guitar_notes
        )
        
        return GPInfo(
            path=filepath,
            size_bytes=size,
            artist=artist,
            title=title,
            tempo=tempo,
            duration_sec=round(duration, 1),
            time_signatures=list(time_sigs),
            n_tracks=len(song.tracks),
            n_guitar_tracks=n_guitar,
            n_other_tracks=n_other,
            total_guitar_notes=total_guitar_notes,
            max_polyphony=max_poly,
            has_techniques=has_tech,
            tunings=tunings,
            level=level,
            level_reason=reason,
        )
    
    except Exception as e:
        log.debug(f"Error parsing {filepath}: {e}")
        return None


def scan_local_directory(gp_dir: str) -> List[str]:
    """Escanea directorio local buscando archivos GP."""
    extensions = {".gp3", ".gp4", ".gp5", ".gp", ".gtp"}
    files = []
    for root, _, filenames in os.walk(gp_dir):
        for f in filenames:
            if Path(f).suffix.lower() in extensions:
                files.append(os.path.join(root, f))
    return files


def select_balanced(candidates: List[GPInfo]) -> List[GPInfo]:
    """
    Selecciona candidatos balanceados por nivel, priorizando canciones populares.
    
    Criterio de prioridad:
    1. Deduplicar: 1 GP por canción (el más grande). Max 2 para score ≥9.
    2. Canciones que aparecen en listas de popularidad (Rolling Stone, Ultimate Guitar, etc.)
    3. Artistas top (cualquier canción de ellos tiene más peso)
    4. Tamaño del archivo (más grande = más completo)
    5. Diversidad de artistas (máx 8 canciones por artista)
    """
    from popularity_data import get_popularity_score, normalize_for_matching
    
    by_level = defaultdict(list)
    for c in candidates:
        by_level[c.level].append(c)
    
    selected = []
    popular_count = 0
    
    for level, target in TARGET_PER_LEVEL.items():
        pool = by_level[level]
        
        # Calcular score de popularidad para cada candidato
        for gp in pool:
            gp._popularity = get_popularity_score(gp.artist, gp.title)
        
        # Ordenar por: popularidad (desc) → tamaño (desc)
        pool.sort(key=lambda x: (x._popularity, x.size_bytes), reverse=True)
        
        # --- DEDUPLICACIÓN ---
        # Quedarse con el mejor GP por cada combinación artista+canción.
        # Excepción: canciones con score ≥9 pueden tener hasta 2 versiones
        # (aporta ver distintas interpretaciones de los clásicos más icónicos).
        song_count = defaultdict(int)  # key: "artista_norm/cancion_norm" → cuántas ya elegidas
        artist_count = defaultdict(int)
        level_selected = []
        level_popular = 0
        
        for gp in pool:
            # Generar key de deduplicación
            artist_norm = normalize_for_matching(gp.artist)
            title_norm = normalize_for_matching(gp.title)
            song_key = f"{artist_norm}/{title_norm}"
            
            # Máximo por canción: 1 normalmente, 2 si score ≥ 9
            max_per_song = 2 if gp._popularity >= 9 else 1
            
            if song_count[song_key] >= max_per_song:
                continue
            
            # Máximo 8 canciones por artista (para diversidad)
            if artist_count[artist_norm] >= 8:
                continue
            
            level_selected.append(gp)
            song_count[song_key] += 1
            artist_count[artist_norm] += 1
            if gp._popularity >= 5:
                level_popular += 1
            
            if len(level_selected) >= target:
                break
        
        selected.extend(level_selected)
        popular_count += level_popular
        unique_songs = len(song_count)
        log.info(f"  Nivel {level}: {len(level_selected)}/{target} seleccionados "
                 f"({unique_songs} canciones únicas, {len(artist_count)} artistas, "
                 f"{level_popular} populares)")
    
    log.info(f"  Total canciones populares (score ≥5): {popular_count}")
    return selected


def _generate_summary_md(selected: List[GPInfo], metadata: dict, md_path: str):
    """Genera un resumen en Markdown de la selección."""
    from collections import Counter
    
    lines = []
    lines.append("# LudiloNet — Canciones Seleccionadas para Training\n")
    lines.append(f"> Generado automáticamente por `select_training_gps.py`\n")
    lines.append(f"## Resumen\n")
    lines.append(f"| Métrica | Valor |")
    lines.append(f"|---------|-------|")
    lines.append(f"| Total seleccionadas | {metadata['total_selected']} |")
    lines.append(f"| Duración total | {metadata['duration_hours']}h |")
    lines.append(f"| Con augmentation (×4) | ~{metadata['duration_hours']*4:.0f}h |")
    lines.append(f"| Canciones populares (score≥5) | {metadata.get('popular_songs_count', 'N/A')} |")
    lines.append(f"| Escaneados | {metadata['total_scanned']} |")
    lines.append(f"| Candidatos válidos | {metadata['total_candidates']} |")
    lines.append("")
    
    # Por nivel
    by_level = defaultdict(list)
    for g in selected:
        by_level[g.level].append(g)
    
    lines.append("## Por nivel de dificultad\n")
    for level in [1, 2, 3]:
        items = by_level[level]
        level_names = {1: "Fácil (guitarra sola/dúo)", 2: "Medio (trío/cuarteto)", 3: "Difícil (banda completa)"}
        lines.append(f"### Nivel {level}: {level_names[level]} ({len(items)} canciones)\n")
        
        # Top 20 populares del nivel
        popular = sorted(items, key=lambda x: getattr(x, '_popularity', 0), reverse=True)[:20]
        if popular and getattr(popular[0], '_popularity', 0) > 0:
            lines.append(f"**Top canciones populares (nivel {level}):**\n")
            lines.append(f"| # | Artista | Canción | Tempo | Notas | Score |")
            lines.append(f"|---|---------|---------|-------|-------|-------|")
            for i, g in enumerate(popular[:20], 1):
                score = getattr(g, '_popularity', 0)
                if score > 0:
                    lines.append(f"| {i} | {g.artist} | {g.title} | {g.tempo} | {g.total_guitar_notes} | {score}/10 |")
            lines.append("")
    
    # Top artistas
    artist_counts = Counter(g.artist for g in selected)
    top_artists = artist_counts.most_common(30)
    lines.append("## Top 30 artistas representados\n")
    lines.append(f"| Artista | Canciones |")
    lines.append(f"|---------|-----------|")
    for artist, count in top_artists:
        lines.append(f"| {artist} | {count} |")
    lines.append("")
    
    # Estadísticas
    tempos = [g.tempo for g in selected]
    durations = [g.duration_sec for g in selected]
    notes = [g.total_guitar_notes for g in selected]
    
    lines.append("## Estadísticas del dataset\n")
    lines.append(f"| Métrica | Min | Promedio | Max |")
    lines.append(f"|---------|-----|----------|-----|")
    lines.append(f"| Tempo (BPM) | {min(tempos)} | {sum(tempos)//len(tempos)} | {max(tempos)} |")
    lines.append(f"| Duración (seg) | {min(durations):.0f} | {sum(durations)/len(durations):.0f} | {max(durations):.0f} |")
    lines.append(f"| Notas guitarra | {min(notes)} | {sum(notes)//len(notes)} | {max(notes)} |")
    lines.append("")
    
    with open(md_path, "w") as f:
        f.write("\n".join(lines))


def main():
    parser = argparse.ArgumentParser(description="Seleccionar GPs para training de LudiloNet")
    parser.add_argument("--source", choices=["local", "blob"], default="local",
                       help="Fuente de archivos GP")
    parser.add_argument("--gp-dir", default="/Users/doniben/Documents/Guitar Pro tabs",
                       help="Directorio local con GPs")
    parser.add_argument("--output", default=None,
                       help="Archivo de salida JSON")
    parser.add_argument("--max-scan", type=int, default=0,
                       help="Máximo de archivos a escanear (0=todos)")
    parser.add_argument("--reselect-only", action="store_true",
                       help="Solo re-ejecutar selección desde all_candidates.json (no re-escanear)")
    args = parser.parse_args()
    
    # Output path
    script_dir = Path(__file__).parent
    output_path = args.output or str(script_dir / "data" / "selected_gps.json")
    os.makedirs(os.path.dirname(output_path), exist_ok=True)
    
    # --- Modo re-selección (sin re-escanear) ---
    if args.reselect_only:
        all_candidates_path = os.path.join(os.path.dirname(output_path), "all_candidates.json")
        if not os.path.exists(all_candidates_path):
            log.error(f"No existe {all_candidates_path}. Corre sin --reselect-only primero.")
            sys.exit(1)
        
        log.info(f"Cargando candidatos de: {all_candidates_path}")
        with open(all_candidates_path) as f:
            all_data = json.load(f)
        
        candidates = [GPInfo(**item) for item in all_data["candidates"]]
        log.info(f"  Candidatos cargados: {len(candidates)}")
        
        # Distribución por nivel
        levels = defaultdict(int)
        for c in candidates:
            levels[c.level] += 1
        log.info(f"  Nivel 1 (fácil): {levels[1]}")
        log.info(f"  Nivel 2 (medio): {levels[2]}")
        log.info(f"  Nivel 3 (difícil): {levels[3]}")
        
        # Selección balanceada con deduplicación
        log.info("\nSeleccionando candidatos (deduplicado)...")
        selected = select_balanced(candidates)
        
        # Estadísticas finales
        total_duration = sum(g.duration_sec for g in selected) / 3600
        log.info(f"\nSelección final:")
        log.info(f"  Total seleccionados: {len(selected)}")
        log.info(f"  Duración total: {total_duration:.1f} horas")
        log.info(f"  Con augmentation (×4): {total_duration*4:.0f} horas estimadas")
        
        # Guardar
        output_data = {
            "metadata": {
                "total_scanned": all_data.get("total_scanned", 94109),
                "total_candidates": len(candidates),
                "total_selected": len(selected),
                "duration_hours": round(total_duration, 1),
                "target_per_level": TARGET_PER_LEVEL,
                "popular_songs_count": sum(1 for g in selected if hasattr(g, '_popularity') and g._popularity >= 5),
                "deduplicated": True,
            },
            "selected": [
                {**asdict(g), "popularity_score": getattr(g, '_popularity', 0)}
                for g in selected
            ],
        }
        
        with open(output_path, "w") as f:
            json.dump(output_data, f, indent=2, ensure_ascii=False)
        log.info(f"\nGuardado en: {output_path}")
        
        md_path = output_path.replace(".json", "_summary.md")
        _generate_summary_md(selected, output_data["metadata"], md_path)
        log.info(f"Resumen MD: {md_path}")
        return
    
    if args.source == "blob":
        log.error("Modo blob no implementado aún. Usa --source local con los GPs descargados.")
        sys.exit(1)
    
    # Escanear directorio
    log.info(f"Escaneando {args.gp_dir} ...")
    all_files = scan_local_directory(args.gp_dir)
    log.info(f"  Encontrados: {len(all_files)} archivos GP")
    
    if args.max_scan > 0:
        all_files = all_files[:args.max_scan]
        log.info(f"  Limitado a: {args.max_scan} archivos")
    
    # Archivo de progreso para monitoreo externo
    progress_file = os.path.join(os.path.dirname(output_path), "selection_progress.json")
    
    # Analizar cada archivo
    log.info("Analizando archivos (esto puede tomar 1-2 horas)...")
    log.info(f"  Progreso en: {progress_file}")
    candidates = []
    errors = 0
    import time as _time
    t_start = _time.time()
    
    for i, filepath in enumerate(all_files):
        if (i + 1) % 100 == 0:
            elapsed = _time.time() - t_start
            pct = (i + 1) / len(all_files) * 100
            rate = (i + 1) / elapsed
            eta_sec = (len(all_files) - i - 1) / rate if rate > 0 else 0
            eta_min = eta_sec / 60
            
            # Escribir progreso a archivo
            progress_data = {
                "status": "running",
                "scanned": i + 1,
                "total": len(all_files),
                "percent": round(pct, 1),
                "candidates": len(candidates),
                "errors": errors,
                "elapsed_sec": round(elapsed, 1),
                "rate_per_sec": round(rate, 2),
                "eta_minutes": round(eta_min, 1),
                "last_update": _time.strftime("%H:%M:%S"),
            }
            with open(progress_file, "w") as pf:
                json.dump(progress_data, pf, indent=2)
        
        if (i + 1) % 2000 == 0:
            log.info(f"  Progreso: {i+1}/{len(all_files)} ({pct:.1f}%) "
                     f"| {len(candidates)} candidatos | {errors} errores "
                     f"| ETA: {eta_min:.0f} min")
        
        info = analyze_gp(filepath)
        if info:
            candidates.append(info)
        else:
            errors += 1
    
    # Marcar como completo
    elapsed_total = _time.time() - t_start
    progress_data = {
        "status": "completed",
        "scanned": len(all_files),
        "total": len(all_files),
        "percent": 100.0,
        "candidates": len(candidates),
        "errors": errors,
        "elapsed_sec": round(elapsed_total, 1),
        "elapsed_minutes": round(elapsed_total / 60, 1),
        "last_update": _time.strftime("%H:%M:%S"),
    }
    with open(progress_file, "w") as pf:
        json.dump(progress_data, pf, indent=2)
    
    log.info(f"\nAnálisis completo:")
    log.info(f"  Total escaneados: {len(all_files)}")
    log.info(f"  Candidatos válidos: {len(candidates)}")
    log.info(f"  Descartados/errores: {errors}")
    
    # Guardar TODOS los candidatos para re-selección futura
    all_candidates_path = os.path.join(os.path.dirname(output_path), "all_candidates.json")
    log.info(f"  Guardando todos los candidatos en: {all_candidates_path}")
    with open(all_candidates_path, "w") as f:
        json.dump({
            "total_scanned": len(all_files),
            "candidates": [asdict(g) for g in candidates]
        }, f, ensure_ascii=False)
    # indent omitido para ahorrar espacio (archivo grande)
    
    # Distribución por nivel
    levels = defaultdict(int)
    for c in candidates:
        levels[c.level] += 1
    log.info(f"  Nivel 1 (fácil): {levels[1]}")
    log.info(f"  Nivel 2 (medio): {levels[2]}")
    log.info(f"  Nivel 3 (difícil): {levels[3]}")
    
    # Selección balanceada
    log.info("\nSeleccionando candidatos balanceados...")
    selected = select_balanced(candidates)
    
    # Estadísticas finales
    total_duration = sum(g.duration_sec for g in selected) / 3600
    log.info(f"\nSelección final:")
    log.info(f"  Total seleccionados: {len(selected)}")
    log.info(f"  Duración total: {total_duration:.1f} horas")
    log.info(f"  Con augmentation (×3-5): {total_duration*4:.0f} horas estimadas")
    
    # Guardar
    output_data = {
        "metadata": {
            "total_scanned": len(all_files),
            "total_candidates": len(candidates),
            "total_selected": len(selected),
            "duration_hours": round(total_duration, 1),
            "target_per_level": TARGET_PER_LEVEL,
            "popular_songs_count": sum(1 for g in selected if hasattr(g, '_popularity') and g._popularity >= 5),
        },
        "selected": [
            {**asdict(g), "popularity_score": getattr(g, '_popularity', 0)}
            for g in selected
        ],
    }
    
    with open(output_path, "w") as f:
        json.dump(output_data, f, indent=2, ensure_ascii=False)
    
    log.info(f"\nGuardado en: {output_path}")
    
    # Generar resumen MD
    md_path = output_path.replace(".json", "_summary.md")
    _generate_summary_md(selected, output_data["metadata"], md_path)
    log.info(f"Resumen MD: {md_path}")


if __name__ == "__main__":
    main()
