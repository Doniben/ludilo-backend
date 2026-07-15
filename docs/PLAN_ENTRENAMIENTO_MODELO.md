# Plan de Entrenamiento: LudiloNet

> Fine-tune de Basic Pitch para transcripción especializada en guitarra con tablatura y acordes

## Resumen

Entrenar un modelo de transcripción audio→MIDI+TAB+CHORDS especializado en guitarra, partiendo de Basic Pitch (CNN ligera, ~2M params) y usando nuestra biblioteca de 66K archivos Guitar Pro como ground truth. Los GP contienen la canción completa (todos los instrumentos con sus notas), lo que permite entrenar para guitarra primero y replicar para otros instrumentos después.

El audio de entrenamiento se sintetiza desde los GP y se pasa por Demucs para simular las condiciones reales de producción. Se evalúa siempre contra audio real (MP3 originales).

**Meta:** pasar de 28-30% F1 (500ms) actual a 55-70% F1, eliminando la dependencia de madmom/Chordino para acordes.

---

## Justificación: ¿Por qué fine-tune de Basic Pitch?

| Criterio             | Desde cero    | Fine-tune BP                 | Fine-tune MT3       |
| -------------------- | ------------- | ---------------------------- | ------------------- |
| VRAM necesaria       | 24-80 GB      | **6 GB (A1000)**       | 40-80 GB            |
| Datos necesarios     | 500+ horas    | **50-100 horas**       | 200+ horas          |
| Tiempo training      | Semanas/meses | **3-5 días**          | Semanas             |
| Código training     | Escribir todo | **Publicado (v0.4.0)** | Existe (YourMT3)    |
| Velocidad inferencia | Variable      | **5s/stem**            | 1-3 min/stem        |
| Compatibilidad A1000 | No (6GB)      | **Sí**                | No (necesita 40GB+) |

Basic Pitch:

- Arquitectura CNN con encoder de espectrograma + 3 cabezas (contour/pitch, onset, note)
- ~2M parámetros → cabe cómodamente en 6GB VRAM
- Ya sabe "qué es una nota" — necesita aprender mejor guitarra
- Inferencia en 5s — no rompe el flujo de usuario
- Training code oficial publicado en v0.4.0 (Apache 2.0)
- Puerto PyTorch disponible (basic-pitch-torch por gudgud96)

---

## Problema actual con detección de acordes

El worker usa 3 modelos en cascada, todos con problemas:

| Modelo                               | Estado           | Problema                                                  |
| ------------------------------------ | ---------------- | --------------------------------------------------------- |
| **madmom** (DeepChroma)        | Falla            | Incompatible con numpy==1.26.4 (pinned por Demucs/scipy)  |
| **chord-extractor** (Chordino) | Funciona parcial | Resultados mediocres, muchos acordes mal clasificados     |
| **autochord**                  | Descartado       | Requiere TensorFlow (desinstalado por romper Basic Pitch) |

**Solución**: agregar una cabeza de acordes a LudiloNet. El modelo ya tiene toda la información que necesita (las notas que está detectando frame-by-frame) — solo necesita una capa que agrupe esas notas en acordes. Esto elimina una dependencia rota y mejora resultados porque los acordes salen directamente de las notas detectadas, no de un análisis cromático independiente.

---

## Ground Truth: Los GP tienen TODO

Los archivos Guitar Pro contienen la canción completa con todos los instrumentos:

```
Ejemplo: "Nothing Else Matters" (.gp4)
  Pista 1: Guitar (James Hetfield) → notas + cuerda + traste + técnicas
  Pista 2: Guitar (Kirk Hammett) → notas + cuerda + traste + técnicas
  Pista 3: Bass → notas + cuerda + traste
  Pista 4: Drums → percusión GM
  Pista 5: Orchestra/Strings → notas
  Pista 6: Vocals (a veces) → melodía
```

| Instrumento   | Qué nos da el GP                                | Uso                                     |
| ------------- | ------------------------------------------------ | --------------------------------------- |
| Guitar        | Notas + cuerda + traste + técnicas + afinación | LudiloNet-Guitar (primera prioridad)    |
| Bass          | Notas + cuerda + traste                          | LudiloNet-Bass (futuro)                 |
| Drums         | Notas + GM drum map                              | Mapping directo (no necesita IA)        |
| Piano/Keys    | Notas + velocity                                 | LudiloNet-Piano o BP genérico (futuro) |
| Vocals        | Melodía (a veces)                               | BP funciona aceptable aquí             |
| Strings/Other | Notas                                            | MT3+ o BP (futuro)                      |

**Implicación**: la inversión en preparar datos sirve para TODOS los instrumentos, no solo guitarra.

---

## Arquitectura: LudiloNet

Basado en Basic Pitch, extendido con cabezas adicionales:

```
Input: CQT/Mel spectrogram del stem (post-Demucs)
       22050 Hz, hop=256, n_bins=264

Encoder: CNN con residual blocks (heredado de BP)
         - Harmonic stacking (8 armónicos)
         - Bloques convolucionales con BatchNorm + ReLU
         - ~2M parámetros base

Cabezas de salida (frame-by-frame):
  1. Contour (264 bins) → multipitch activo, 3 bins/semitono [heredada de BP]
  2. Onset (88 bins)    → detección de inicio [heredada de BP]
  3. Note (88 bins)     → nota activa (onset→offset) [heredada de BP]
  ─── NUEVAS ───
  4. String/Fret (150 bins = 6 cuerdas × 25 trastes) → posición en diapasón
  5. Technique (6 clases) → normal / slide / hammer / pull / bend / strum
  6. Chord (25 clases)  → acorde activo en cada frame (12 roots × 12 types + "N")

Loss total:
  L = L_contour + L_onset + L_note + λ₁·L_string + λ₂·L_technique + λ₃·L_chord
  
  donde:
  - L_contour, L_onset, L_note = Binary Cross-Entropy (como BP original)
  - L_string = Cross-Entropy sobre posiciones válidas para cada pitch
  - L_technique = Cross-Entropy multi-clase (6 clases)
  - L_chord = Cross-Entropy sobre vocabulario de acordes
  - λ₁ = 0.3, λ₂ = 0.1, λ₃ = 0.2 (hiperparámetros a calibrar)
```

### Cabeza de acordes — Diseño

Los acordes se infieren directamente de las notas detectadas por el propio modelo:

```python
# Input: note output [batch, frames, 88] + contour features
# Output: chord label por frame [batch, frames, n_chord_classes]

# Vocabulario de acordes (25 clases mínimo):
CHORD_VOCAB = [
    "N",        # No chord / silencio
    "maj", "min", "7", "maj7", "min7",
    "dim", "aug", "sus4", "sus2",
    "min7b5", "6", "min6",
    # × 12 roots (C, C#, D, ..., B)
    # Total: 12 × 12 + 1 = 145 clases (o reducido a ~25 más comunes)
]

# La ventaja vs madmom/Chordino:
# - Los acordes son CONSISTENTES con las notas detectadas
# - No hay contradicción entre "el modelo dice Em" y "las notas son E-G-B"
# - Se entrena con ground truth perfecto (los acordes del GP son exactos)
```

### Técnicas — 6 clases

| Clase           | Descripción                              | Detección del GP                             |
| --------------- | ----------------------------------------- | --------------------------------------------- |
| normal          | Nota individual atacada                   | Default                                       |
| slide           | Nota que se desliza a otra                | `note.effect.slide`                         |
| hammer          | Ligado ascendente sin re-atacar           | `note.effect.hammer`                        |
| pull            | Ligado descendente                        | Hammer + dirección descendente               |
| bend            | Estiramiento de cuerda                    | `note.effect.bend`                          |
| **strum** | **Rasgueo (3+ notas simultáneas)** | **3+ notas en mismo beat, onset <30ms** |

### Fases de entrenamiento

1. **Fase 1 (fine-tune base):** Congelar encoder, entrenar cabezas note/contour/onset con datos de guitarra
2. **Fase 2 (end-to-end):** Descongelar encoder con lr bajo (1e-5), fine-tune completo
3. **Fase 3 (cabezas nuevas):** Agregar string/technique/chord heads, entrenar con encoder congelado
4. **Fase 4 (end-to-end final):** Todo junto, lr muy bajo (5e-6)

---

## Datos de Entrenamiento

### Fuente: Biblioteca Guitar Pro (66,435 archivos) — TODOS LOS INSTRUMENTOS

| Nivel                              | Canciones       | Criterios                                             | Horas estimadas           |
| ---------------------------------- | --------------- | ----------------------------------------------------- | ------------------------- |
| 1: Guitarra sola                   | 800             | 1 instrumento melódico, tempo ≤120, sin distorsión | ~35h                      |
| 2: Dúo/Trío                      | 500             | 2-3 pistas, mezcla acústica, fingerpicking + voz     | ~25h                      |
| 3: Banda completa                  | 400             | 4+ pistas, eléctrica, distorsión, velocidad alta    | ~20h                      |
| **Total selección**         | **1,700** |                                                       | ~**80h** base       |
| **Con augmentation (×3-5)** |                 | 3-5 variantes por GP                                  | ~**300h** efectivas |

### Criterios de selección de GP

```python
CRITERIOS = {
    "tamano_minimo": 5_000,       # bytes (GPs < 5KB suelen ser incompletos)
    "pistas_guitarra": True,       # debe tener al menos 1 pista de guitarra
    "duracion_minima": 60,         # segundos
    "duracion_maxima": 600,        # segundos (evitar medleys de 20 min)
    "notas_minimas": 50,           # al menos 50 notas en guitarra
}
```

### Clasificación por dificultad

| Nivel | Pistas | Tempo     | Polifonía max | Técnicas                   | Ejemplos                           |
| ----- | ------ | --------- | -------------- | --------------------------- | ---------------------------------- |
| 1     | 1-2    | ≤120 BPM | 4 notas        | Arpeggio, strumming básico | Dust in the Wind, Lagrima          |
| 2     | 2-3    | ≤140 BPM | 6 notas        | Fingerpicking, harmonics    | Hotel California, Stairway (intro) |
| 3     | 4+     | >140 BPM  | 6 notas        | Shred, tapping, sweep       | Master of Puppets, Eruption        |

### Deduplicación y priorización por popularidad

**Problema identificado:** sin deduplicación, el 56% de los slots se desperdiciaban con versiones repetidas de la misma canción (ej: 18 versiones de Toxicity, 12 de Hotel California).

**Solución implementada:**
- **1 GP por canción** (el más grande/completo). Máximo 2 para canciones con score ≥9.
- **Máximo 8 canciones por artista** (diversidad).
- **Priorización por popularidad** usando rankings de:
  - Rolling Stone 500 Greatest Songs
  - Ultimate Guitar (canciones más buscadas all-time)
  - Guitar World (mejores riffs y solos)
  - Listas de canciones más aprendidas por guitarristas

**Sistema de scoring (0-10):**
| Score | Significado | Ejemplos |
|-------|-------------|----------|
| 10 | Top absoluto mundial | Stairway to Heaven, Hotel California, Nothing Else Matters |
| 9 | Icono de guitarra | Enter Sandman, Thunderstruck, Californication |
| 8 | Clásico reconocido | Paranoid Android, Fear of the Dark, Zombie |
| 7 | Muy popular/buscada | Fade to Black, Holy Wars, Seven Nation Army |
| 6 | Icónica educativa | Lagrima (Tárrega), Classical Gas, Hallelujah |
| 5 | Artista top, canción conocida | Dani California, Learn to Fly, Duality |
| 3-4 | Artista prioritario (cualquier canción) | Cualquier Metallica, Iron Maiden, etc. |
| 0 | No en listas | Se elige por calidad técnica del GP |

**Resultado:** ~33% del dataset son canciones populares conocidas (las que más probablemente subirán los usuarios), el resto aporta diversidad de géneros, técnicas y complejidades.

**Base de datos:** 256 canciones específicas + 46 artistas prioritarios en `training/popularity_data.py`.

---

## Pipeline de Generación de Datos

### Paso 1: GP → MIDI alineado (labels)

```
PyGuitarPro → extrae por pista:
  - Notas: pitch, onset (en ticks → segundos), duration, velocity
  - Posición: string, fret (para guitarra/bass)
  - Técnica: slide, hammer, pull, bend, strum (del GP)
  - Acordes: se infieren agrupando notas simultáneas del GP por compás
  - Metadata: tempo, time_signature, tuning
```

### Paso 2: MIDI → Audio sintetizado

```
MIDI (TODOS los instrumentos) → FluidSynth + SoundFont → WAV (44100 Hz)

SoundFonts a usar (diversidad tímbrica):
  1. GeneralUser GS (GM, gratuito, buena calidad general)
  2. Acoustic Guitar Steel (sampled, más realista)
  3. Nylon Guitar (para clásica/fingerpicking)
  4. Electric Guitar Clean (para limpias)
  5. Electric Guitar Distortion (para heavy/metal)
  
Cada GP se renderiza con 3-5 SoundFonts diferentes → multiplicador de datos
Se renderiza la canción COMPLETA (todos los instrumentos) para que Demucs
tenga algo realista que separar.
```

### Paso 3: Augmentation

```
Para cada WAV sintetizado:
  - Pitch shift: ±1, ±2 semitonos (transponer sin cambiar tempo)
  - Tempo stretch: ±5%, ±10% (sin cambiar pitch)
  - Ruido: añadir ruido rosa a -30dB, -20dB
  - Reverb: room, hall (distintas cantidades)
  - EQ: variaciones de brillo/calidez
  
Resultado: 3-5 variantes por WAV original
```

### Paso 4: Demucs (simular producción)

```
WAV mezcla completa → Demucs htdemucs_6s → 6 stems

CLAVE: El modelo ENTRENA sobre stems de Demucs, no audio limpio.
Esto cierra el domain gap entre training y producción.

Para cada stem de guitarra extraído:
  - El label corresponde SOLO a las pistas de guitarra del GP
  - Los acordes se calculan sobre TODAS las notas del GP en ese rango temporal

Para Nivel 1 (guitarra sola):
  - La mezcla incluye backing tracks (drums+bass) de la misma canción
  - Demucs separa → el stem guitar es "realista"
```

### Paso 5: Generar labels (piano-roll matrix)

```
Del MIDI original (Paso 1), generar matrices frame-by-frame:
  - Sample rate: 22050 Hz, hop: 256 → ~86 frames/segundo
  - Contour: [frames × 264] float — multipitch (3 bins/semitono × 88)
  - Onset: [frames × 88] binary — 1 en frame de inicio
  - Note: [frames × 88] binary — 1 mientras la nota suena
  - String/Fret: [frames × 150] — posición (6 cuerdas × 25 trastes)
  - Technique: [frames × 6] — clase de técnica
  - Chord: [frames × N] — acorde activo (one-hot)
```

### Paso 6 (NUEVO): Integrar audio real

```
Para 10% del dataset final:
  - Usar canciones de MUSDB18 (150 masters con stems reales)
  - Usar canciones propias procesadas que tienen match en biblioteca GP
  - Alinear GP con audio real usando DTW sobre chromagrams
  - Esto cierra el domain gap entre audio sintético y real
```

---

## Estrategia de Integración en el Worker

### Principio: Quirúrgica. Solo reemplazar lo que mejora.

```python
# Flujo actual:
audio → Demucs → stems → BP (todos) → MIDI
                       → chord-extractor/madmom → chords (BROKEN)

# Flujo con LudiloNet (primera versión):
audio → Demucs → stems → LudiloNet (guitar stem) → MIDI + tab + chords
                       → BP (bass, piano, vocals, other) → MIDI
                       → MT3+ (drums, clasificación) → MIDI

# Flujo futuro:
audio → Demucs → stems → LudiloNet-Guitar → MIDI + tab + chords
                       → LudiloNet-Bass → MIDI + tab
                       → BP/nuevo modelo (piano, vocals)
                       → MT3+ (drums)
```

### Cambio en el worker (1 condicional)

```python
# En process_job():
if instrument == "guitar":
    midi_path, tab_data, chords = ludilonet_predict(guitar_stem)
else:
    midi_path = basic_pitch_predict(stem)
    chords = []  # Ya no necesitamos madmom/chordino — LudiloNet da los acordes
```

### Cambios en frontend: NINGUNO o mínimos

| Aspecto     | Antes                             | Después                     | Cambio frontend                      |
| ----------- | --------------------------------- | ---------------------------- | ------------------------------------ |
| MIDI output | Archivo .mid                      | Archivo .mid                 | Ninguno                              |
| Acordes     | `song.chords[]` en Cosmos       | `song.chords[]` en Cosmos  | Ninguno (mismo formato)              |
| Tablatura   | `song.tab_data` con heurística | `song.tab_data` del modelo | Ninguno (mejor calidad)              |
| Técnicas   | Solo slides/strums                | +hammer, pull, bend, strum   | Agregar iconos en TabView (opcional) |
| Velocidad   | ~5s/stem                          | ~5s/stem                     | Ninguno                              |

---

## Infraestructura y Dependencias

### Hardware

| Recurso     | Especificación           | Disponible     |
| ----------- | ------------------------- | -------------- |
| GPU         | NVIDIA A1000 6GB VRAM     | ✅             |
| RAM sistema | 16-32 GB                  | ✅ (verificar) |
| Disco       | ~100 GB para datos        | ✅             |
| CPU         | Para síntesis FluidSynth | ✅             |

### Software a instalar

```bash
# En la A1000 (worker existente ya tiene CUDA + PyTorch)
pip install basic-pitch-torch       # Modelo PyTorch (para fine-tune)
pip install pyfluidsynth            # Síntesis MIDI → WAV
pip install guitarpro               # Lectura de archivos .gp
pip install librosa                 # Audio processing
pip install mir_eval                # Evaluación
pip install pretty_midi             # Manipulación MIDI
pip install torch torchvision       # (ya instalado)
pip install tensorboard             # Monitoreo de training
pip install audiomentations         # Data augmentation
pip install pedalboard              # Efectos de audio (Spotify)

# FluidSynth (sistema)
# macOS:
brew install fluidsynth
# Linux (A1000):
sudo apt-get install fluidsynth
```

### SoundFonts a descargar

| SoundFont               | Tamaño | URL/Fuente                  | Uso                  |
| ----------------------- | ------- | --------------------------- | -------------------- |
| GeneralUser GS          | ~30 MB  | generaluser.sourceforge.net | GM completo, base    |
| FluidR3_GM              | ~140 MB | github.com/FluidSynth       | Alternativa GM       |
| Acoustic Guitar (Steel) | ~5 MB   | musical-artifacts.com       | Guitarra acústica   |
| Nylon Guitar            | ~3 MB   | musical-artifacts.com       | Guitarra clásica    |
| SGM-V2.01               | ~200 MB | archive.org                 | Alta calidad general |

**NOTA:** Ya tienes `GeneralUser.sf2` en el frontend (`public/soundfont/`). Puedes usarlo como base.

---

## Estimación de Tiempos

| Fase            | Tarea                                        | Tiempo estimado       |
| --------------- | -------------------------------------------- | --------------------- |
| 0               | Preparación de datos (scripts + ejecución) | 3-5 días             |
| 0a              | Selección de 1700 GPs                       | 2-3 horas (script)    |
| 0b              | Síntesis de audio (FluidSynth)              | 8-12 horas (batch)    |
| 0c              | Augmentation                                 | 4-6 horas (batch)     |
| 0d              | Demucs sobre todo el dataset                 | 24-48 horas (A1000)   |
| 0e              | Generación de labels (incluyendo acordes)   | 2-3 horas (script)    |
| 1               | Fine-tune cabezas pitch (encoder frozen)     | 12-24 horas GPU       |
| 2               | Fine-tune end-to-end                         | 24-48 horas GPU       |
| 3               | Agregar cabezas string/technique/chord       | 12-24 horas GPU       |
| 4               | Fine-tune final con audio real (MUSDB18)     | 24-48 horas GPU       |
| **Total** |                                              | **~7-12 días** |

---

## Métricas de Éxito

### Evaluación con canciones de audio REAL (MP3 originales)

Siempre se evalúa contra audio real, nunca contra sintético.

| Métrica            | Actual (BP raw) | Meta Fine-tune | Meta Final     |
| ------------------- | --------------- | -------------- | -------------- |
| F1 guitarra (500ms) | 28%             | 50%            | **65%+** |
| F1 guitarra (200ms) | 17%             | 35%            | **50%+** |
| F1 guitarra (100ms) | 9.5%            | 25%            | **40%+** |
| Precision           | 21%             | 50%            | **70%+** |
| Recall              | 42%             | 60%            | **70%+** |
| Falsos positivos    | 56%             | <25%           | **<15%** |
| String accuracy     | N/A             | —             | **80%+** |
| Chord accuracy      | ~50% (Chordino) | 70%            | **85%+** |

### Evaluación de acordes vs modelos actuales

| Modelo                         | Funciona   | Calidad estimada          | Velocidad                             |
| ------------------------------ | ---------- | ------------------------- | ------------------------------------- |
| madmom (actual)                | ❌ No      | Buena (cuando funciona)   | ~5s                                   |
| Chordino (fallback)            | ✅ Parcial | Mediocre                  | ~7s                                   |
| **LudiloNet chord head** | ✅         | **Buena-Excelente** | **0s (incluido en inferencia)** |

Ventaja de la chord head integrada: no agrega tiempo de procesamiento (sale del mismo forward pass que las notas).

### Set de evaluación

- **Benchmark principal**: 4 canciones actuales (NEM, Lagrima, Entertainer, Malagueña) + 6-10 nuevas
- **Audio real obligatorio**: MUSDB18 stems + canciones procesadas con GP match
- **Evaluación automática**: corre cada 5 epochs durante training
- **Evaluación perceptual**: ¿se puede tocar la tablatura? ¿los acordes suenan bien?

---

## Datos: cuánto es suficiente y escalado futuro

### Relación datos → calidad (basado en papers)

| Dataset                | Horas                         | Instrumento        | F1 reportado         |
| ---------------------- | ----------------------------- | ------------------ | -------------------- |
| GuitarSet              | 3h                            | Guitarra           | ~65% (state of art)  |
| MAPS                   | 65h                           | Piano              | ~85%                 |
| MAESTRO                | 200h                          | Piano              | ~88%                 |
| GAPS                   | 14h                           | Guitarra clásica  | ~70%                 |
| **LudiloNet v1** | **~300h (sintéticas)** | **Guitarra** | **Meta: 65%+** |

### Escalado

| Fase                    | GPs usados      | Horas efectivas | F1 esperado      | Inversión          |
| ----------------------- | --------------- | --------------- | ---------------- | ------------------- |
| v1 (validación)        | 1,700           | ~300h           | 55-65%           | 7-12 días          |
| v2 (mejora)             | 5,000           | ~900h           | 65-75%           | +3-5 días de datos |
| v3 (máximo sintético) | 20,000          | ~3,500h         | 75-80%           | +1-2 semanas datos  |
| v4 (+audio real)        | 20K + 200h real | ~3,700h         | **80-85%** | +evaluación manual |

Empezamos con 1700 para **validar que el approach funciona** antes de invertir semanas en procesamiento.

---

## Plan de Ejecución (Sprints)

### Sprint T1: Preparación de datos (Semana 1)

- [x] T1-01: Script `select_training_gps.py` — seleccionar y clasificar 1700 GPs (con deduplicación + popularidad)
- [ ] T1-02: Descargar e instalar 3-5 soundfonts de guitarra
- [x] T1-03: Script `synthesize_audio.py` — GP → MIDI → WAV (FluidSynth, todos los instrumentos)
- [ ] T1-04: Script `augment_audio.py` — pitch shift, tempo, reverb, noise
- [x] T1-05: Script `process_demucs.py` — pasar mezclas por Demucs, extraer guitar stem
- [x] T1-06: Script `generate_labels.py` — MIDI → piano-roll + string/fret + technique + chord
- [ ] T1-07: Script `build_dataset.py` — empaquetar en formato de training (.npz)
- [ ] T1-08: Verificar dataset: estadísticas, balance, sanity checks
- [x] T1-09: Prueba de síntesis FluidSynth (escuchar calidad) ✅ Nothing Else Matters S&M sintetizado OK

### Sprint T2: Fine-tune Basic Pitch (Semana 2)

- [ ] T2-01: Clonar basic-pitch-torch, verificar que funciona con pesos originales
- [ ] T2-02: Implementar dataloader para nuestro formato de dataset
- [ ] T2-03: Configurar training loop (PyTorch, mixed precision para A1000)
- [ ] T2-04: Fine-tune Fase 1: solo cabezas pitch, encoder congelado
- [ ] T2-05: Evaluar con benchmark (audio real: NEM, Lagrima, Entertainer, Malagueña)
- [ ] T2-06: Fine-tune Fase 2: end-to-end con lr bajo
- [ ] T2-07: Evaluar de nuevo — comparar con baseline BP
- [ ] T2-08: Agregar datos Nivel 2 y 3, re-entrenar
- [ ] T2-09: Checkpoint del mejor modelo

### Sprint T3: Cabezas de tablatura y acordes (Semana 3)

- [ ] T3-01: Implementar string/fret head (150 bins)
- [ ] T3-02: Implementar technique head (6 clases: normal, slide, hammer, pull, bend, strum)
- [ ] T3-03: Implementar chord head (vocabulario de acordes del GP)
- [ ] T3-04: Entrenar solo cabezas nuevas (encoder + note heads congeladas)
- [ ] T3-05: Evaluar string accuracy vs GP ground truth
- [ ] T3-06: Evaluar chord accuracy vs GP ground truth y vs Chordino actual
- [ ] T3-07: Fine-tune final end-to-end completo
- [ ] T3-08: Exportar modelo final (ONNX para producción)

### Sprint T4: Integración y evaluación con audio real (Semana 4)

- [ ] T4-01: Fine-tune final con 10% audio real (MUSDB18 + canciones con GP match)
- [ ] T4-02: Integrar LudiloNet en worker (solo guitar stem)
- [ ] T4-03: Worker sigue con BP+MT3+ para el resto de instrumentos
- [ ] T4-04: Eliminar dependencia de madmom/chord-extractor (LudiloNet da los acordes)
- [ ] T4-05: Test end-to-end: audio → worker → Cosmos DB → frontend
- [ ] T4-06: A/B test: BP original vs LudiloNet en 10+ canciones reales
- [ ] T4-07: Deploy a producción si métricas superan 28% F1 actual

---

## Riesgos y Mitigaciones

| Riesgo                                       | Probabilidad | Impacto | Mitigación                                                       |
| -------------------------------------------- | ------------ | ------- | ----------------------------------------------------------------- |
| Audio sintetizado ≠ audio real (domain gap) | Media        | Alto    | Pasar por Demucs + 10% datos reales + fine-tune final con MUSDB18 |
| A1000 no tiene suficiente VRAM para training | Baja         | Alto    | BP ~20MB; batch 4-8 cabe en 6GB; gradient accumulation            |
| Overfitting a soundfonts específicos        | Media        | Medio   | 5+ soundfonts + augmentation agresivo                             |
| Labels de GP tienen errores (GPs mal hechos) | Baja         | Bajo    | Filtrar por tamaño + validar con PyGuitarPro                     |
| Demucs introduce artefactos que confunden    | Media        | Medio   | Es lo que verá en producción; feature, no bug                   |
| Acordes del GP no siempre están explícitos | Media        | Bajo    | Inferir de notas simultáneas + chord templates                   |
| LudiloNet no supera a BP                     | Baja         | Medio   | Si pasa: revertir, seguir con BP. Cero riesgo al deploy           |

---

## Notas sobre el código de training

### Basic Pitch Training (v0.4.0, Apache 2.0)

- El training code oficial usa TensorFlow/Keras
- El port PyTorch (basic-pitch-torch) solo tiene inferencia, NO training
- **Decisión:** Training loop propio en PyTorch usando el modelo de basic-pitch-torch como base
- Razón: PyTorch más flexible para cabezas nuevas, A1000 ya tiene PyTorch+CUDA

### Formato del modelo de entrada

```python
# Basic Pitch espera:
# Input: audio → Harmonic CQT → [batch, channels, time, freq_bins]
# Output: 3 matrices de [batch, time_frames, 88]

# Harmonic CQT settings (del paper ICASSP 2022):
SAMPLE_RATE = 22050
HOP_LENGTH = 256    # ~11.6 ms por frame
N_HARMONICS = 8     # Harmonic stacking
FMIN = 27.5         # A0
BINS_PER_OCTAVE = 36
N_SEMITONES = 88    # A0 a C8
```

### Datasets de referencia usados por BP original

- MusicNet (330 recordings, ~34 hours, mixed instruments)
- GuitarSet (360 recordings, ~3 hours, guitar only)
- MAESTRO (piano, 200+ hours — no usado para guitarra)
- MedleyDB (mixed, ~7 hours)

Nosotros tendremos **~300 horas** de guitarra sintetizada + Demucs, lo cual es **100× más guitarra** que lo que BP vio en su entrenamiento original (~3 horas de GuitarSet).

---

## Referencia: Papers y Repos

| Recurso                         | URL                                   | Relevancia                  |
| ------------------------------- | ------------------------------------- | --------------------------- |
| Basic Pitch paper (ICASSP 2022) | arxiv.org/abs/2202.09038              | Arquitectura base           |
| Basic Pitch repo                | github.com/spotify/basic-pitch        | Training code (TF)          |
| basic-pitch-torch               | github.com/gudgud96/basic-pitch-torch | Modelo PyTorch              |
| SynthTab (ICASSP 2024)          | github.com/yongyizang/SynthTab        | Datos sintetizados para tab |
| GOAT dataset                    | arxiv.org/abs/2509.22655              | 5.9h guitarra real + tabs   |
| GAPS dataset                    | arxiv.org/abs/2408.08653              | 14h guitarra clásica       |
| DadaGP                          | arxiv.org/abs/2107.14653              | 26K GPs tokenizados         |
| MR-MT3                          | github.com/gudgud96/MR-MT3            | Fine-tune de MT3            |

---

## Ventaja competitiva

1. **66K archivos GP** con todos los instrumentos, posiciones de diapasón, técnicas, acordes implícitos
2. **FluidSynth** para sintetizar audio variado con múltiples soundfonts
3. **Demucs en la pipeline** para cerrar el domain gap training↔producción
4. **Worker con A1000** para entrenar y servir el modelo
5. **Evaluación con audio real** (benchmark ya armado + MUSDB18)
6. **Integración quirúrgica**: solo reemplazar guitar stem, cero riesgo

El resultado:

- Más preciso que BP para guitarra (×100 más datos de guitarra)
- Da posiciones de diapasón directamente (ningún otro modelo lo hace)
- Detecta técnicas (slide, hammer, pull, bend, strum)
- Detecta acordes (elimina madmom/Chordino roto)
- Corre igual de rápido (~5s/stem)
- Se puede escalar a más instrumentos (bass, piano) con el mismo pipeline
