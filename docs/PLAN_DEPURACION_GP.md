# Plan de Depuración — Guitar Pro Tabs

## Estado actual

| Pack | Estructura | Archivos | Organización |
|------|-----------|----------|--------------|
| Pack 1 | Por letra (A-Z) | 20,323 | `Artista - Canción.gp3/gp4` |
| Pack 2 | Mixto (letras + sueltos) | 30,081 | Similar a Pack 1 pero más desordenado |
| Pack 3 | Por género | 43,749 | `Género/Artista/Canción.gp3` |
| **Total** | | **94,153** | |

**Extensiones:** 58,147 gp3 + 33,483 gp4 + 2,422 gtp + 57 gp5
**Tamaño total:** 2.5 GB

## Problema

- Muchas pistas repetidas entre los 3 packs (misma canción, mismo artista)
- Versiones duplicadas: `Judith.gp3`, `Judith (2).gp3`, `Judith (3).gp3`
- Queremos quedarnos con **1 sola versión por canción** (la más pesada = más completa)

## Plan de depuración

### Paso 1: Normalizar nombres
- Extraer `artista` y `canción` del nombre de archivo
- Pack 1 y 2: formato `Artista - Canción.ext` → split por ` - `
- Pack 3: formato `Género/Artista/Canción.ext` → carpeta padre = artista
- Normalizar: lowercase, quitar `(2)`, `(3)`, espacios extra, caracteres especiales

### Paso 2: Agrupar por artista + canción
- Key: `{artista_normalizado}/{cancion_normalizada}`
- Si hay múltiples versiones → quedarse con la de mayor tamaño (más pistas/info)

### Paso 3: Organizar para subida
```
library/guitarpro/{artista}/{cancion}.gp{3,4,5}
```
- Si no se puede extraer artista → usar género del Pack 3 como carpeta

### Paso 4: Subir a Blob Storage
- Subir los archivos seleccionados a `stludilo/library/guitarpro/`
- Indexar metadata en Cosmos DB (library_index)

## Resultado esperado

- De ~94K archivos → estimado ~40-50K únicos (eliminando duplicados)
- Organizados por artista
- Sin duplicados

## Script

Ejecutar: `python3 deduplicate_gp.py`
- Input: `/Users/doniben/Documents/Guitar Pro tabs/`
- Output: reporte de duplicados + lista final de archivos a subir
- No borra nada, solo genera el plan de subida

## Notas

- Los archivos .gp tienen metadata interna (PyGuitarPro puede leerla) pero es lento para 94K archivos
- Mejor usar nombre de archivo para deduplicar (rápido) y PyGuitarPro solo para indexar metadata al subir
