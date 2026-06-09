# Resultados del Benchmark de Transcripción

> Evaluación ejecutada 8 junio 2026 | Canción: Nothing Else Matters — Metallica

## Resumen ejecutivo

| Hallazgo | Implicación |
|----------|-------------|
| Pitch class accuracy 95-100% | Ambos modelos detectan notas CORRECTAS |
| F1 con tol=500ms: BP=28%, MT3+=23.5% | BP es mejor para guitarra |
| MT3+ genera 4x más notas que la referencia | Exceso masivo de detección |
| Filtro armónico casi no impacta | Las notas ya encajan en los acordes |
| Deduplicación (0.2s) mejora F1: 28%→30.1% | Mejor técnica disponible |
| Quantización a 1/8 mejora F1: 30.1%→31.4% | Ayuda moderada |
| MT3+ solo procesó la mitad de la canción | Bug en procesamiento original |

## Datos de la canción evaluada

- **Canción**: Nothing Else Matters — Metallica (Official Music Video)
- **Duración audio**: 385.7s
- **GP referencia**: `nothing_else_matters.gp3` (7 pistas, 73 BPM, 6/8)
- **Notas ref (guitar only)**: 1877 (James Hetfield + Kirk Hammet)
- **BP ID**: `cfd2daaa` | **MT3+ ID**: `d39f1d05`

## Sprint A: Análisis de alineación temporal

El GP y el audio tienen duraciones casi idénticas (384.7s vs 385.7s). No se requiere DTW.

| Tolerancia | MT3+ P | MT3+ R | MT3+ F1 | BP P | BP R | BP F1 |
|------------|--------|--------|---------|------|------|-------|
| 50ms | 3.6 | 7.6 | 4.9 | 3.7 | 7.4 | 4.9 |
| 100ms | 6.1 | 13.0 | 8.3 | 7.1 | 14.1 | **9.5** |
| 200ms | 10.2 | 21.7 | 13.9 | 12.8 | 25.3 | **17.0** |
| 500ms | 17.3 | 36.7 | 23.5 | 21.1 | 41.7 | **28.0** |
| 1s | 24.6 | 52.4 | 33.5 | 28.7 | 56.6 | **38.1** |
| 2s | 33.2 | 70.6 | 45.2 | 37.1 | 73.4 | **49.3** |
| 5s | 42.2 | 89.7 | 57.4 | 44.9 | 88.7 | **59.6** |

**Conclusión:** BP gana en todas las tolerancias. El recall a 5s (~89%) confirma que las notas se detectan, solo con offset variable.

## Sprint B1: Filtro armónico

| Threshold | BP notas | BP F1 | MT3+ notas | MT3+ F1 |
|-----------|----------|-------|------------|---------|
| Sin filtro | 3709 | 28.0% | 3988 | 23.5% |
| ≥0.3 (no cromáticas) | 3692 | 28.1% | 3919 | 23.8% |
| ≥0.8 (solo chord tones) | 3219 | 27.0% | 3104 | 23.3% |
| =1.0 (solo chord tones estricto) | 3219 | 27.0% | 3104 | 23.3% |

**Conclusión:** Impacto mínimo. Solo 17/3709 notas de BP son cromáticas. El problema NO es pitch incorrecto — es exceso de notas que armónicamente coinciden.

## Sprint B2: Merge híbrido

### Baselines
| Modelo | Precision | Recall | F1 | Notas | Ratio vs Ref |
|--------|-----------|--------|-----|-------|--------------|
| BP solo | 21.1% | 41.7% | 28.0% | 3709 | 2.0x |
| MT3+ solo | 17.3% | 36.7% | 23.5% | 3988 | 2.1x |

### Estrategias de merge (tol=500ms)
| Estrategia | P | R | F1 | Notas |
|------------|---|---|-----|-------|
| Intersección (onset_tol=0.1s) | **32.8%** | 25.7% | 28.8% | 1473 |
| Intersección (onset_tol=0.3s) | 27.7% | 29.4% | 28.5% | 1986 |
| Unión deduplicada (0.1s) | 15.0% | **49.7%** | 23.0% | 6224 |
| Confidence ≥0.8 | 18.5% | 34.7% | 24.1% | 3524 |

### Análisis por rango temporal (primera mitad, 0-184s, donde MT3+ opera)
| Modelo | P | R | F1 |
|--------|---|---|-----|
| BP (primera mitad) | 22.1% | 43.3% | **29.3%** |
| MT3+ (toda su salida) | 9.1% | 41.1% | 14.9% |
| Intersección (0.3s) | 28.7% | 32.2% | 30.3% |

**Hallazgo clave:** MT3+ tiene precision de solo 9.1% en la primera mitad — genera ~4x más notas que la referencia. BP es significativamente mejor (F1: 29.3% vs 14.9%).

## Sprint B3: Reglas musicales y deduplicación

### Reglas musicales (rango/polifonía/duración)
| Paso | BP notas | MT3+ notas |
|------|----------|------------|
| Original | 3709 | 3988 |
| Después de rango (40-88) | 3708 (-1) | 3901 (-87) |
| Después de duración (≥30ms) | 3708 (0) | 3791 (-110) |
| Después de polifonía (≤6) | 3656 (-52) | 3283 (-508) |

**Conclusión:** Impacto mínimo en BP (53 notas eliminadas). Las notas ya son válidas musicalmente.

### Deduplicación (TÉCNICA MÁS EFECTIVA)
| Ventana | BP notas | BP F1 (500ms) | MT3+ notas | MT3+ F1 |
|---------|----------|---------------|------------|---------|
| Sin dedup | 3709 | 28.0% | 3988 | 23.5% |
| 30ms | 3709 | 28.0% | 3505 | 25.2% |
| 50ms | 3709 | 28.0% | 3390 | 25.7% |
| 100ms | 3642 | 28.3% | 3199 | 26.6% |
| **200ms** | **3207** | **30.1%** | **2745** | **28.7%** |

### Mejor pipeline: BP + dedup(0.2s)
| Tolerancia | P | R | F1 | ΔF1 vs raw |
|------------|---|---|-----|------------|
| 100ms | 7.5% | 12.7% | 9.4% | -0.1 |
| 200ms | 14.1% | 24.0% | 17.7% | +0.7 |
| 500ms | 23.8% | 40.7% | **30.1%** | **+2.1** |
| 1s | 32.1% | 54.9% | **40.6%** | **+2.5** |
| 2s | 41.8% | 71.4% | **52.7%** | **+3.4** |

## Sprint C: Quantización rítmica

BPM=73, Time sig=6/8

| Grid | Intervalo | F1 (500ms) | ΔF1 |
|------|-----------|------------|-----|
| Sin quantizar | — | 30.1% | — |
| 1/4 (quarter) | 822ms | 30.3% | +0.2 |
| **1/8 (eighth)** | **411ms** | **31.4%** | **+1.3** |
| 1/12 (eighth triplet) | 274ms | 29.4% | -0.7 |
| 1/16 (sixteenth) | 205ms | 30.4% | +0.3 |
| 1/32 (32nd) | 103ms | 28.9% | -1.2 |

Con tolerancia de 100ms, la quantización a 1/8 sube F1 de 9.4% a **14.4%** (+5 puntos).

## Resumen final: Mejor pipeline

```
BP raw → Dedup(0.2s) → Quant(1/8) = F1 31.4% (tol=500ms)
```

vs baseline BP raw = F1 28.0%

**Mejora: +3.4 puntos F1** (12% de mejora relativa)

## Pendientes identificados

1. **Re-procesar Nothing Else Matters con MT3+ completo** — la versión actual cortó a 184s (la mitad)
2. **Evaluar con más canciones** — estos resultados son de 1 sola canción
3. **El exceso de notas (2x ratio)** no se resuelve con estas técnicas — se necesita un threshold de confianza en BP (velocity/amplitude based)
4. **MT3+ no aporta al F1 de guitarra** cuando ya tienes Demucs separando — su valor está en drums y clasificación de instrumentos
5. **La quantización ayuda más con tolerancia estricta** (100ms) — útil para tablatura precisa
6. **Explorar filtrado por amplitude/velocity** como siguiente técnica para eliminar notas fantasma


---

## Sprint D: Benchmark Multi-Canción

### Resumen (tolerancia 500ms, BP guitar stem)

| Canción | Nivel | GP notas | BP notas | F1 raw | F1 +dedup | Ratio BP/GP |
|---------|-------|----------|----------|--------|-----------|-------------|
| Nothing Else Matters | Básica | 1877 | 3709 | 28.0% | **30.1%** | 2.0x |
| Lagrima (Tárrega) | Básica | 172 | 550 | 17.7% | 18.2% | 3.2x |
| The Entertainer (Joplin) | Intermedia | 1107 | 1055 | 26.3% | 26.5% | 1.0x |
| Malagueña (Ortega) | Avanzada | 993 | 852 | 24.4% | **25.4%** | 0.9x |
| **PROMEDIO** | — | — | — | **24.1%** | **25.0%** | — |

### Observaciones por canción

**Nothing Else Matters (Básica, 73 BPM, 6/8):**
- BP detecta 2x más notas que la referencia → exceso de detección
- Dedup ayuda significativamente (+2.1 F1)
- La más beneficiada por dedup (tiene arpeggio repetitivo que BP duplica)

**Lagrima (Básica, 120 BPM):**
- BP detecta **3.2x** más notas → mucho ruido
- F1 más bajo del benchmark (17.7%) pese a ser pieza sencilla
- Probable causa: pieza para guitarra clásica solo, sin acompañamiento → BP detecta armónicos y resonancias

**The Entertainer (Intermedia, 100 BPM):**
- Ratio **1.0x** — BP detecta casi las mismas notas que el GP ← ideal
- Mejor precision del benchmark (porque no hay exceso)
- Dedup casi no ayuda (+0.2) — pocas duplicaciones

**Malagueña (Avanzada, 120 BPM):**
- Ratio **0.9x** — BP detecta MENOS notas que el GP
- Recall limitado (pieza rápida, notas que BP no captura)
- Dedup ayuda más aquí (+1.0) — elimina repeticiones fantasma

### Hallazgos clave del benchmark multi-canción

1. **El ratio BP/GP varía enormemente** (0.9x a 3.2x) según el tipo de música
2. **Piezas de guitarra sola (Lagrima)** son las más difíciles — BP genera 3x más ruido
3. **Piezas con ritmo claro y banda (Entertainer)** tienen el mejor ratio (1.0x)
4. **La dedup ayuda más cuando hay exceso** (NEM +2.1, Malagueña +1.0, Entertainer +0.2)
5. **El F1 promedio es 25%** con tolerancia de 500ms — aceptable para una primera aproximación

### Conclusión final del benchmark

El pipeline **BP + dedup(0.2s)** es una mejora simple y universal:
- Mejora promedio: +0.9 F1 (24.1% → 25.0%)
- No requiere MT3+ ni fusión compleja
- Se implementa en 5 líneas de código en el worker

**Para mejorar significativamente** se necesitaría:
1. Threshold de amplitude en BP (eliminar notas con velocity < 30)
2. Análisis espectral del stem para validar que la nota realmente suena
3. Modelo fine-tuned en guitarra específicamente

Estos quedan como **pendientes para futuras iteraciones**.
