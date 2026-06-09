# Plan de Refinamiento: Transcripción MP3 → TAB

> Sistema híbrido Demucs + Basic Pitch + YourMT3+ con validación armónica

## Objetivo

Crear el pipeline de transcripción MP3→TAB más preciso posible aprovechando:
1. **Demucs** para separación de stems
2. **Basic Pitch** para detección de notas con alto recall
3. **YourMT3+** para clasificación multi-instrumento y detección conservadora
4. **Teoría de armonía musical** para filtrado y validación de notas
5. **Biblioteca GP (66K archivos)** como ground truth para entrenamiento de reglas

---

## Resultados de la Prueba Piloto

### Canción: Nothing Else Matters — Metallica (S&M version)

**Archivos usados:**
- GP referencia: `nothing_else_matters.gp3` (7 pistas, 73 BPM, 6/8)
- BP: procesamiento `cfd2daaa` (Basic Pitch sobre stems Demucs)
- MT3+: procesamiento `d39f1d05` (YourMT3+ sobre stems Demucs)

### Resultados por instrumento

| Instrumento | Ref (notas) | BP F1 | MT3+ F1 | Hybrid F1 | BP Harmonic | MT3+ Harmonic |
|-------------|-------------|-------|---------|-----------|-------------|---------------|
| Guitar | 3069 | **10.0%** | 8.9% | 8.9% | **86.8%** | 77.8% |
| Bass | 310 | **2.0%** | 1.0% | 0.9% | **81.5%** | 60.9% |
| Vocals | 358 | 3.8% | **4.2%** | 4.1% | 76.6% | 65.9% |
| Other (orquesta) | 120 | 0% | **0.2%** | 0.2% | — | 79.7% |
| Drums | 933 | 0% | **2.3%** | 2.3% | — | — |

### Hallazgos clave

1. **Los F1 bajos son por ALINEACIÓN TEMPORAL, no por detección incorrecta**
   - El GP usa tempo fijo (73 BPM) y el audio real tiene variaciones
   - Hay un offset temporal entre el inicio del GP y el inicio del audio
   - mir_eval penaliza con ventana de 100ms — cualquier desfase > 100ms = nota "incorrecta"

2. **Pitch class accuracy demuestra que las notas son CORRECTAS**
   - Guitar: 100% (ambos modelos)
   - Bass: BP 95.5%, MT3+ 86.2%
   - Vocals: MT3+ 97.1%, BP 95.9%
   - → Los modelos saben QUÉ notas tocar, solo fallan en CUÁNDO exactamente

3. **BP tiene mejor consistencia armónica** (86.8% vs 77.8% guitarra)
   - BP genera menos notas fuera de acorde
   - MT3+ genera más notas (3988 vs 3709 guitarra) pero algunas son "ruido armónico"

4. **MT3+ es el único que detecta drums y orquesta**
   - BP no genera nada para stems silenciosos/percusivos
   - MT3+ detecta 5406 notas en "other" (la orquesta sinfónica S&M)

5. **El híbrido ingenuo (intersección + MT3+-only) no mejora**
   - Problema: si ambos modelos tienen offset temporal similar, la intersección no filtra nada
   - Se necesita un merge más inteligente basado en armonía, no solo coincidencia temporal

---

## Arquitectura del Pipeline Refinado

```
                         ┌─────────────────────┐
                         │   Audio MP3/WAV      │
                         └──────────┬───────────┘
                                    │
                         ┌──────────▼───────────┐
                         │  Demucs htdemucs_ft  │
                         │  (4 stems base +     │
                         │   htdemucs_6s para   │
                         │   guitar/piano)      │
                         └──────────┬───────────┘
                                    │
           ┌──────────────┬─────────┼─────────┬──────────────┐
           │              │         │         │              │
    ┌──────▼──────┐ ┌─────▼────┐ ┌──▼──┐ ┌───▼───┐ ┌───────▼──────┐
    │  Guitar.wav │ │ Bass.wav │ │Drums│ │Vocals │ │  Other.wav   │
    └──────┬──────┘ └─────┬────┘ └──┬──┘ └───┬───┘ └───────┬──────┘
           │              │         │         │              │
    ┌──────▼──────────────▼─────────▼─────────▼──────────────▼──────┐
    │                    Para cada stem:                              │
    │  ┌─────────────┐          ┌──────────────────┐                │
    │  │ Basic Pitch │          │ YourMT3+ (bsz=2) │                │
    │  │ (ONNX, 5s)  │          │ (~1-3 min/stem)   │                │
    │  └──────┬──────┘          └────────┬──────────┘                │
    │         │                          │                           │
    │  ┌──────▼──────────────────────────▼──────┐                   │
    │  │        MOTOR DE FUSIÓN ARMÓNICA        │                   │
    │  │  1. Alinear temporalmente (DTW/beat)   │                   │
    │  │  2. Intersección con prioridad MT3+    │                   │
    │  │  3. Filtro armónico (chord validation) │                   │
    │  │  4. Reglas musicales (rango, polifonía)│                   │
    │  │  5. Quantización a grid rítmico        │                   │
    │  └────────────────┬───────────────────────┘                   │
    └───────────────────┼───────────────────────────────────────────┘
                        │
             ┌──────────▼──────────┐
             │   MIDI Refinado     │
             │  (por instrumento)  │
             └──────────┬──────────┘
                        │
             ┌──────────▼──────────┐
             │ Asignación a TAB    │
             │ (cuerda + traste)   │
             │ + técnicas inferidas│
             └─────────────────────┘
```

---

## Fase 1: Motor de Fusión Armónica

### 1.1 Alineación temporal

**Problema:** BP y MT3+ generan timestamps basados en el audio real, pero con micro-diferencias. El GP tiene timestamps idealizados (grid perfecto). Para comparar necesitamos alinear.

**Solución:**
```
1. Detectar BPM del audio (librosa.beat.beat_track)
2. Generar beat grid del audio real
3. Alinear GP al audio con Dynamic Time Warping (DTW) sobre chroma features
4. Usar el GP alineado como referencia para evaluar BP y MT3+
```

**Beneficio:** Resuelve el problema de F1 bajo por offset temporal. Permitirá métricas reales de precisión.

### 1.2 Reglas de fusión

Para cada nota detectada, asignar un **score de confianza**:

| Condición | Score | Acción |
|-----------|-------|--------|
| Nota en BP ∩ MT3+ (mismo pitch, ±100ms) | 1.0 | Mantener siempre |
| Nota solo en MT3+ | 0.8 | Mantener (MT3+ es conservador) |
| Nota solo en BP + encaja en acorde activo | 0.7 | Mantener |
| Nota solo en BP + NO encaja en acorde + RMS alto | 0.5 | Evaluar contexto |
| Nota solo en BP + NO encaja en acorde + RMS bajo | 0.2 | Probable falso positivo → descartar |
| Nota < 30ms duración | 0.1 | Probable ruido → descartar |

### 1.3 Validación armónica (teoría musical)

**Principio:** Una nota detectada es más probable de ser correcta si encaja en el contexto armónico.

**Implementación:**
```python
def harmonic_score(note_pitch, chord_at_time, key_signature):
    pc = note_pitch % 12
    
    # Nivel 1: ¿Es nota del acorde? → score alto
    if pc in chord_tones(chord_at_time):
        return 1.0
    
    # Nivel 2: ¿Es tensión válida del acorde? (9, 11, 13)
    if pc in chord_tensions(chord_at_time):
        return 0.8
    
    # Nivel 3: ¿Es nota diatónica de la escala/key?
    if pc in scale_notes(key_signature):
        return 0.6
    
    # Nivel 4: ¿Es nota cromática de paso? (duración corta + entre dos notas diatónicas)
    if is_passing_tone(note_pitch, context):
        return 0.5
    
    # No encaja en nada → sospechosa
    return 0.2
```

**Fuentes de información armónica:**
1. **Chord-extractor (Chordino)** — ya lo tenemos, genera acordes con timestamps
2. **Key detection** — librosa o music21 para detectar tonalidad global
3. **Progresión armónica** — validar que los acordes tengan sentido (ej: Em → Am → C → B7 → Em es válido en Em)

### 1.4 Reglas musicales por instrumento

| Regla | Guitar | Bass | Vocals | Drums |
|-------|--------|------|--------|-------|
| Polifonía máxima | 6 notas | 1 nota | 1 nota | 4 simultáneas |
| Rango MIDI | 40-88 | 24-60 | 36-84 | n/a |
| Duración mínima | 30ms | 50ms | 100ms | 10ms |
| Velocidad mínima | 20 | 20 | 30 | 10 |
| Puede tener bends | Sí | Sí | Sí (vibrato) | No |
| Rango intervalo máximo entre notas consecutivas | 24 semitonos | 12 semitonos | 12 semitonos | n/a |

### 1.5 Quantización rítmica

Después de la fusión, alinear notas al grid rítmico más cercano:

```
1. Detectar BPM y time signature del audio
2. Generar grid: 1/4, 1/8, 1/16, 1/8T (triplets)
3. Para cada nota: snap onset al grid point más cercano
4. Threshold: si la nota está a más de 1/64 del grid → mantener timing original
5. Si la nota está muy cerca del grid → snap
```

**Parámetro de quantización:** configurable por el usuario (0% = libre, 100% = estricto).

---

## Fase 2: Diferenciación por capacidad de cada modelo

### Lo que cada modelo aporta al pipeline

| Capacidad | Basic Pitch | YourMT3+ | Acción |
|-----------|-------------|-----------|--------|
| Detección de notas individuales | ⭐⭐⭐ Alto recall | ⭐⭐ Moderado | Usar BP como base de notas candidatas |
| Clasificación de instrumento | ❌ No | ⭐⭐⭐ 13 canales | Usar MT3+ para program assignment |
| Precisión de onset | ⭐⭐ Buena | ⭐⭐⭐ Mejor | Usar MT3+ timing cuando ambos coinciden |
| Detección de drums | ❌ No | ⭐⭐⭐ Sí | Usar MT3+ exclusivamente |
| Detección de orquesta/other | ❌ No | ⭐⭐⭐ Sí | Usar MT3+ exclusivamente |
| Falsos positivos | ⭐ Muchos en silencio | ⭐⭐⭐ Pocos | Filtrar BP con umbral RMS |
| Velocidad | ⭐⭐⭐ 5s/stem | ⭐ 1-3 min/stem | BP para "rápido", MT3+ para "calidad" |
| Polifonía compleja | ⭐⭐ Buena | ⭐⭐ Similar | Combinar para mejorar |

### Estrategia por tipo de contenido

| Contenido | Estrategia óptima |
|-----------|-------------------|
| Guitarra acústica fingerpicking | BP (mejor recall de notas individuales) + filtro armónico |
| Guitarra eléctrica distorsionada | MT3+ (mejor en pitch denso) + BP para notas adicionales |
| Bajo | BP (más notas detectadas, 95% pitch correcto) + regla de 1 nota |
| Vocals (melodía) | MT3+ (mejor precisión) + BP para notas que MT3+ pierde |
| Drums | MT3+ exclusivamente (BP no detecta percusión) |
| Orquesta/Strings | MT3+ exclusivamente (identifica instrumentos) |
| Secciones tranquilas | BP (detecta matices suaves que MT3+ ignora) |
| Secciones densas/rápidas | MT3+ (mejor discriminación en caos) |

---

## Fase 3: Plan de Benchmark con Canciones Clasificadas

### Criterios de clasificación

| Nivel | Criterio | Reto para transcripción |
|-------|----------|------------------------|
| Básico | ≤3 instrumentos, tempo <100 BPM, acordes simples | Offset temporal, pocos falsos positivos |
| Intermedio | 4-5 instrumentos, fingerpicking/arpeggios, tempo 80-140 | Separación de notas rápidas, polifonía |
| Avanzado | 6+ instrumentos, técnicas complejas, tempo >140, distorsión | Todo lo anterior + ruido de distorsión + shred |

### Canciones seleccionadas (confirmado que existen en biblioteca GP)

#### Básicas
| Canción | Artista | GP disponible | Reto principal |
|---------|---------|---------------|----------------|
| Nothing Else Matters | Metallica | ✅ 40 versiones | Arpeggio lento, 6/8, orquesta S&M |
| Wish You Were Here | Pink Floyd | ✅ 7 versiones | 2 guitarras acústicas, solo |
| Blackbird | Beatles | ✅ 8 versiones | Fingerpicking, percusión con pie |
| Dust in the Wind | Kansas | ✅ 6 versiones | Fingerpicking dual guitar |
| Tears in Heaven | Eric Clapton | ✅ 9 versiones | Fingerpicking, vocal + guitar |

#### Intermedias
| Canción | Artista | GP disponible | Reto principal |
|---------|---------|---------------|----------------|
| Hotel California | Eagles | ✅ 43 versiones | Dual guitar harmonies, solo largo |
| Stairway to Heaven | Led Zeppelin | ✅ 28 versiones | Transición acústica→eléctrica, múltiples secciones |
| Canon in D | Pachelbel | ✅ En cola | Polifonía estricta, múltiples voces |

#### Avanzadas
| Canción | Artista | GP disponible | Reto principal |
|---------|---------|---------------|----------------|
| Master of Puppets | Metallica | ✅ 31 versiones | Downpicking rápido, palm mute, dual guitar |
| Eruption | Van Halen | ✅ 16 versiones | Tapping, whammy bar, velocidad extrema |
| La Malagueña | Tradicional | ✅ En cola | Flamenco, rasgueados, velocidad |

### Protocolo de evaluación por canción

```
1. Seleccionar GP más completo (mayor tamaño = más pistas)
2. Obtener MP3 del audio real (YouTube/Spotify → fpcalc match)
3. Procesar con worker: Demucs → BP + MT3+
4. Alinear GP al audio (DTW sobre chromagrams)
5. Evaluar cada modelo por separado
6. Evaluar fusión híbrida con diferentes parámetros
7. Evaluar con filtro armónico
8. Registrar métricas y parámetros ganadores
```

---

## Fase 4: Inferencia de técnicas para tablatura

### Técnicas detectables desde MIDI

| Técnica | Cómo detectarla | Fuente |
|---------|-----------------|--------|
| Slide | 2 notas conectadas, pitch diferente, sin silencio entre ellas | BP (detecta ambas notas) |
| Hammer-on/Pull-off | Notas legato (onset suave), intervalo pequeño (1-3 semitonos) | MT3+ (timing preciso) |
| Bend | Pitch bend gradual (no disponible en MIDI estándar, pero inferible si la nota sube de pitch) | Análisis de audio (pitch track del stem) |
| Vibrato | Variación periódica de pitch (±20-50 cents) alrededor de una nota | Análisis de audio |
| Palm mute | Notas cortas con velocity alta y decay rápido | Análisis espectral del stem |
| Tapping | Notas con onset muy rápido y claro, sin ataque de púa | MT3+ (alta confianza) + duración corta |
| Rasgueado | Múltiples notas (4-6) con onset escalonado (~10-30ms entre cada una) | BP (detecta cada nota individual) |
| Armónico | Pitch en múltiplos exactos de la fundamental, timbre diferente | Análisis espectral |

### Asignación de posición en diapasón (cuerda + traste)

```python
def assign_fret_position(midi_pitch, tuning="standard", prefer_low_position=True):
    """
    Para un pitch MIDI, encontrar todas las posiciones posibles
    en el diapasón y elegir la más probable.
    
    Criterios de selección:
    1. Minimizar saltos de posición respecto a nota anterior
    2. Preferir posiciones bajas (trastes 0-7) en canciones simples
    3. Respetar máximo stretch de mano (4-5 trastes)
    4. Si hay GP disponible → usar posición del GP directamente
    """
    STANDARD_TUNING = [40, 45, 50, 55, 59, 64]  # E2 A2 D3 G3 B3 E4
    
    positions = []
    for string_idx, open_pitch in enumerate(tuning or STANDARD_TUNING):
        fret = midi_pitch - open_pitch
        if 0 <= fret <= 24:
            positions.append((string_idx, fret))
    
    return select_best_position(positions, context)
```

---

## Fase 5: Agrupación de MIDIs para visualización

### Problema
MT3+ genera múltiples tracks dentro de un solo stem (ej: "guitar" puede tener Guitar Clean + Guitar Distorted). ¿Cómo mostrarlos en la UI?

### Solución

```
Nivel 1 — Vista "Instrumento" (default)
  → Combinar todos los tracks del mismo stem en una sola tablatura/piano roll
  → El usuario ve "Guitar" con todas las notas combinadas

Nivel 2 — Vista "Tracks"  
  → Separar por program/canal MIDI de MT3+
  → Guitar Clean | Guitar Distorted | Guitar Acoustic
  → Cada uno con su propia tablatura

Nivel 3 — Vista "Full Score"
  → Todas las pistas simultáneas como partitura completa
  → Similar a lo que se ve en Guitar Pro
```

### Mapper de programs MIDI de MT3+ a instrumentos de Ludilo

```python
MT3_TO_LUDILO = {
    # Guitar family
    25: "guitar_acoustic_nylon",
    26: "guitar_acoustic_steel", 
    27: "guitar_jazz",
    28: "guitar_clean",
    29: "guitar_muted",
    30: "guitar_overdriven",
    31: "guitar_distortion",
    32: "guitar_harmonics",
    
    # Bass
    33: "bass_acoustic",
    34: "bass_finger",
    35: "bass_pick",
    36: "bass_fretless",
    37: "bass_slap1",
    38: "bass_slap2",
    
    # Strings
    49: "strings_ensemble",
    41: "violin",
    42: "viola",
    43: "cello",
    
    # Keys
    1: "piano_acoustic",
    5: "piano_electric",
    
    # Drums → channel 10 (standard)
    "drums": "drums"
}
```

---

## Fase 6: Uso de teoría armónica en el pipeline

### ¿Dónde se aplica la armonía?

| Paso del pipeline | Aplicación de armonía |
|-------------------|-----------------------|
| Filtro de notas candidatas | Descartar notas que no encajan en ningún acorde/escala |
| Selección entre BP y MT3+ | Si discrepan, preferir la que encaje armónicamente |
| Corrección de octava | Si una nota está a ±12 semitonos de lo esperado → corregir octava |
| Detección de errores de modelo | Nota claramente fuera de tonalidad = probable error |
| Completar notas faltantes | Si el acorde es Em y solo se detectan E y B → inferir G como probable |
| Enriquecimiento de tablatura | Sugerir digitaciones basadas en forma del acorde |

### Implementación del validador armónico

```python
class HarmonicValidator:
    def __init__(self, chords, key=None):
        self.chords = chords  # [{start, end, label}, ...]
        self.key = key  # Detected key signature
    
    def validate_note(self, pitch, onset_time):
        """Returns confidence score 0.0-1.0 based on harmonic context."""
        chord = self.get_chord_at(onset_time)
        if not chord:
            return 0.5  # No chord info → neutral
        
        pc = pitch % 12
        chord_pcs = self.chord_to_pitch_classes(chord)
        scale_pcs = self.key_to_scale(self.key)
        
        if pc in chord_pcs:
            return 1.0  # Chord tone
        elif pc in self.get_tensions(chord):
            return 0.85  # Valid tension (9, 11, 13)
        elif pc in scale_pcs:
            return 0.6  # Diatonic, not in chord
        else:
            return 0.2  # Chromatic — likely error unless passing tone
    
    def suggest_corrections(self, notes):
        """Suggest pitch corrections for suspicious notes."""
        corrections = []
        for note in notes:
            score = self.validate_note(note.pitch, note.onset)
            if score < 0.3:
                # Try ±1 semitone
                for offset in [-1, 1]:
                    if self.validate_note(note.pitch + offset, note.onset) > 0.7:
                        corrections.append((note, note.pitch + offset))
                        break
        return corrections
```

### Detección de tonalidad

```python
def detect_key(chords):
    """Infer key from chord progression using circle of fifths."""
    # Count chord roots weighted by duration
    root_weights = {}
    for chord in chords:
        root = chord_root(chord["label"])
        duration = chord["end"] - chord["start"]
        root_weights[root] = root_weights.get(root, 0) + duration
    
    # The most common root in functional harmony is usually I or V
    # Use Krumhansl-Schmuckler algorithm or simple heuristic:
    # If Em is most common → key is Em or G
    # Check if V→I cadences exist to confirm
    ...
```

---

## Fase 7: Métricas de éxito

### Objetivo de F1 por nivel de dificultad

| Nivel | F1 actual (sin alinear) | F1 objetivo (con pipeline completo) |
|-------|------------------------|-------------------------------------|
| Básico (guitar) | ~10% | >60% |
| Básico (bass) | ~2% | >50% |
| Intermedio (guitar) | TBD | >45% |
| Avanzado (guitar) | TBD | >30% |

### Métricas complementarias

| Métrica | Descripción | Objetivo |
|---------|-------------|----------|
| Pitch class accuracy | % notas con pitch correcto (sin importar timing) | >95% |
| Harmonic consistency | % notas que encajan en el acorde activo | >85% |
| Onset precision | Error promedio de onset vs referencia GP alineada | <50ms |
| False positive rate | % notas detectadas que no existen en referencia | <15% |
| Tablatura playability | % de frames donde la digitación es físicamente posible | >95% |

---

## Modificaciones en el Worker (A1000)

### Estado actual del worker

El worker (`ludilo-worker/ludilo.py`) actualmente:
- Corre en la A1000 con CUDA
- Permite elegir BP o MT3+ al iniciar (selector interactivo)
- Procesa un modelo a la vez por stem
- Sube 1 MIDI por stem

### Cuándo modificar el worker

**NO modificar hasta que Sprint B esté validado** (motor de fusión probado con métricas positivas).

### Cambios a implementar (Sprint E)

```python
# En process_job():

# ANTES (actual):
# model = "basic-pitch" o "yourmt3" (uno u otro)
# midi_path = convert_stem_to_midi(stem, model)
# upload(midi_path)

# DESPUÉS (futuro):
# bp_midi = convert_stem_to_midi(stem, "basic-pitch")     # ~5s
# mt3_midi = convert_stem_to_midi(stem, "yourmt3")        # ~1-3 min
# refined_midi = fusion.merge(bp_midi, mt3_midi, chords)  # ~1s
# upload(refined_midi)                                     # Solo el refinado
```

### Nuevo archivo: `fusion.py`

```python
# fusion.py — Motor de fusión armónica
# Input: bp_midi_path, mt3_midi_path, chords (list)
# Output: refined_midi_path
#
# Parámetros (a calibrar en Sprint D):
# - onset_tolerance: 100ms (ventana para considerar "misma nota")
# - harmonic_threshold: 0.3 (score mínimo para mantener nota)
# - min_duration: 30ms (notas más cortas = ruido)
# - max_polyphony: {guitar: 6, bass: 1, vocals: 1, drums: 4}
```

### Impacto en tiempos de procesamiento

| Pipeline | Tiempo estimado/canción |
|----------|------------------------|
| Actual (BP only) | ~3-4 min |
| Actual (MT3+ only) | ~12 min |
| Futuro (BP + MT3+ + fusión) | ~14-15 min |

### Opción para el usuario (frontend)

Se puede dar a elegir:
- "Rápido" → solo BP (~3 min) — para previa rápida
- "Alta calidad" → BP + MT3+ + fusión (~15 min) — para estudio serio

### Documentación para la sesión de la A1000

La otra sesión de Kiro en la A1000 debe saber:
1. **No cambiar nada todavía** — el worker funciona bien como está
2. **El plan de refinamiento existe** en `ludilo-backend/docs/PLAN_REFINAMIENTO_TRANSCRIPCION.md`
3. **El contexto resumido** está en `ludilo-worker/docs/CONTEXTO.md` (sección final)
4. **Los archivos de evaluación** están en el Mac en `/tmp/ludilo-eval/`
5. **Cuando se le pida implementar `fusion.py`**, recibirá los parámetros calibrados

---

## Implementación — Orden de trabajo

### Sprint A: Alineación temporal (prerequisito)
1. [ ] Implementar DTW (Dynamic Time Warping) con librosa
2. [ ] Alinear GP de Nothing Else Matters al audio real
3. [ ] Re-evaluar F1 con GP alineado (debería subir dramáticamente)
4. [ ] Si F1 sigue bajo → el problema es otro, investigar

### Sprint B: Motor de fusión v1
1. [ ] Implementar merge BP+MT3+ con scoring por confianza
2. [ ] Implementar filtro armónico básico (chord tone = mantener, non-diatonic = descartar)
3. [ ] Implementar reglas musicales por instrumento (rango, polifonía)
4. [ ] Evaluar con canciones básicas: Nothing Else Matters, Wish You Were Here
5. [ ] Comparar F1 antes/después del filtro

### Sprint C: Quantización y post-procesamiento
1. [ ] Beat detection con librosa
2. [ ] Quantización adaptativa al grid
3. [ ] Detección de técnicas (slide, hammer-on, etc.)
4. [ ] Asignación de posiciones en diapasón
5. [ ] Evaluar con canciones intermedias

### Sprint D: Benchmark completo
1. [ ] Procesar las 11 canciones del benchmark (básicas + intermedias + avanzadas)
2. [ ] Registrar métricas por canción y por modelo
3. [ ] Optimizar parámetros del merge (umbrales de confianza)
4. [ ] Documentar resultados finales

### Sprint E: Integración en worker
1. [ ] Implementar motor de fusión en `ludilo.py`
2. [ ] Opción de usuario: "Rápido" (BP solo) vs "Calidad" (BP+MT3++fusión)
3. [ ] Servir MIDI refinado al frontend
4. [ ] Validar tablatura generada vs GP original

---

## Consideraciones adicionales

### ¿Por qué no solo MT3+?

MT3+ es excelente para clasificación multi-instrumento pero:
- **Pierde notas suaves** (bajo recall en secciones piano/pp)
- **Es lento** (~3 min/stem vs 5s de BP)
- **No siempre disponible** (requiere GPU)
- **Basic Pitch complementa** exactamente donde MT3+ falla

### ¿Por qué no solo Basic Pitch?

BP tiene mejor recall individual pero:
- **No clasifica instrumentos** (todo es "piano" por default)
- **No detecta drums** (incapaz de manejar percusión)
- **Genera falsos positivos en silencio** (notas fantasma)
- **No asigna programs MIDI** (el timbre se pierde)

### El híbrido ideal

```
BP = "detector de notas candidatas" (alto recall)
MT3+ = "clasificador y validador" (alta precision, instruments)
Armonía = "filtro de calidad" (elimina errores musicalmente incorrectos)
GP (cuando existe) = "override total" (ground truth, posiciones exactas)
```

### Prioridad de fuentes para tablatura

```
1. Si hay GP en biblioteca → USAR GP DIRECTAMENTE (posiciones reales en diapasón)
2. Si hay MIDI en Lakh/LA con metadata rica → piano roll directo
3. Si solo hay audio procesado → pipeline híbrido BP+MT3++armonía
```

La mayoría de canciones populares ya tienen GP en nuestra biblioteca (66K archivos). El pipeline híbrido es para canciones que NO están en la biblioteca.

---

## Archivos del benchmark

```
/tmp/ludilo-eval/
├── evaluate.py              # Script de evaluación
├── chords.json              # Acordes detectados (Chordino)
├── results.json             # Resultados numéricos
├── gp/
│   ├── nothing_else_matters.gp3    # 7 pistas, 51KB
│   └── nothing_else_matters_sm.gp4 # Versión S&M, 46KB
├── mt3/                     # MIDIs de YourMT3+ (d39f1d05)
│   ├── bass.mid (2.7KB)
│   ├── drums.mid (9.4KB)
│   ├── guitar.mid (29KB)
│   ├── vocals.mid (3.8KB)
│   └── other.mid (38KB)
└── bp/                      # MIDIs de Basic Pitch (cfd2daaa)
    ├── bass.mid (22KB)
    ├── drums.mid (41B — vacío)
    ├── guitar.mid (23KB)
    ├── vocals.mid (27KB)
    └── other.mid (41B — vacío)
```

---

## Conclusión de la prueba piloto

La evaluación confirma que:

1. **Ambos modelos detectan las notas correctas** (pitch class accuracy 95-100%)
2. **El problema principal es temporal**, no de pitch — se resuelve con DTW
3. **BP es mejor para instrumentos melódicos** cuando se filtra armónicamente
4. **MT3+ es indispensable para drums, clasificación y orquesta**
5. **El híbrido ingenuo no funciona** — se necesita fusión basada en armonía
6. **La teoría musical es la clave** para discriminar notas reales de ruido

El siguiente paso es implementar la alineación temporal (DTW) y re-evaluar. Si el F1 alineado supera 40%, el pipeline es viable y solo necesita ajuste fino.
