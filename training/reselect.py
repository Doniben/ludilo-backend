#!/usr/bin/env python3
"""
reselect.py — Re-ejecuta la selección sobre los datos ya analizados.
No re-escanea los archivos GP, solo aplica nuevos criterios de selección.

Uso:
    python reselect.py
"""
import json
import sys
import os
sys.path.insert(0, os.path.dirname(__file__))

from pathlib import Path
from collections import defaultdict
from dataclasses import dataclass, asdict
from typing import List
import logging

from popularity_data import get_popularity_score, normalize_for_matching
from select_training_gps import GPInfo, _generate_summary_md, TARGET_PER_LEVEL

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
log = logging.getLogger(__name__)

def main():
    data_dir = Path(__file__).parent / "data"
    input_path = data_dir / "selected_gps.json"
    
    if not input_path.exists():
        log.error(f"No existe {input_path}. Corre select_training_gps.py primero.")
        sys.exit(1)
    
    # Cargar todos los candidatos del JSON anterior
    # Necesitamos el JSON completo con TODOS los candidatos, no solo los seleccionados.
    # Como solo guardamos los seleccionados, re-carguemos del JSON existente
    # y apliquemos la nueva lógica.
    
    # En realidad, el JSON solo tiene los 1700 seleccionados.
    # Necesitamos los 73K candidatos. Vamos a re-ejecutar la selección
    # cargando el JSON y regenerando desde ahí.
    
    log.info("Cargando datos existentes...")
    with open(input_path) as f:
        data = json.load(f)
    
    # Los candidatos están en "selected" pero necesitamos TODOS.
    # Chequemos si hay un archivo con todos los candidatos
    all_candidates_path = data_dir / "all_candidates.json"
    
    if not all_candidates_path.exists():
        log.error("No existe all_candidates.json.")
        log.error("Necesitamos regenerar: corriendo select_training_gps.py con --save-all")
        sys.exit(1)
    
    with open(all_candidates_path) as f:
        all_data = json.load(f)
    
    candidates = [GPInfo(**item) for item in all_data["candidates"]]
    log.info(f"Candidatos cargados: {len(candidates)}")
    
    # Aplicar nueva selección con deduplicación
    selected = select_balanced_dedup(candidates)
    
    # Estadísticas
    total_duration = sum(g.duration_sec for g in selected) / 3600
    
    log.info(f"\nSelección final (deduplicada):")
    log.info(f"  Total seleccionados: {len(selected)}")
    log.info(f"  Duración total: {total_duration:.1f} horas")
    log.info(f"  Con augmentation (×4): {total_duration*4:.0f} horas estimadas")
    
    # Guardar
    output_path = data_dir / "selected_gps.json"
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
    log.info(f"Guardado: {output_path}")
    
    # MD
    md_path = str(output_path).replace(".json", "_summary.md")
    _generate_summary_md(selected, output_data["metadata"], md_path)
    log.info(f"Resumen: {md_path}")


def select_balanced_dedup(candidates: List[GPInfo]) -> List[GPInfo]:
    """Selección con deduplicación por artista+canción."""
    by_level = defaultdict(list)
    for c in candidates:
        by_level[c.level].append(c)
    
    selected = []
    popular_count = 0
    
    for level, target in TARGET_PER_LEVEL.items():
        pool = by_level[level]
        
        for gp in pool:
            gp._popularity = get_popularity_score(gp.artist, gp.title)
        
        pool.sort(key=lambda x: (x._popularity, x.size_bytes), reverse=True)
        
        song_count = defaultdict(int)
        artist_count = defaultdict(int)
        level_selected = []
        level_popular = 0
        
        for gp in pool:
            artist_norm = normalize_for_matching(gp.artist)
            title_norm = normalize_for_matching(gp.title)
            song_key = f"{artist_norm}/{title_norm}"
            
            max_per_song = 2 if gp._popularity >= 9 else 1
            
            if song_count[song_key] >= max_per_song:
                continue
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
        log.info(f"  Nivel {level}: {len(level_selected)}/{target} "
                 f"({unique_songs} únicas, {len(artist_count)} artistas, "
                 f"{level_popular} populares)")
    
    log.info(f"  Total populares (score ≥5): {popular_count}")
    return selected


if __name__ == "__main__":
    main()
