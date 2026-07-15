# LudiloNet — Training

Fine-tune de Basic Pitch para transcripción de guitarra con tablatura.

## Requisitos

- **GPU:** NVIDIA A1000 6GB (o superior)
- **CUDA:** 11.8+
- **Python:** 3.10+
- **FluidSynth:** `brew install fluidsynth` (macOS) / `apt install fluidsynth` (Linux)
- **SoundFonts:** Al menos 1 archivo .sf2 (GeneralUser GS recomendado)

## Pipeline de datos

```
1. select_training_gps.py    →  Selecciona 1700 GPs de los 66K
2. synthesize_audio.py       →  GP → MIDI → WAV (FluidSynth)
3. process_demucs.py         →  WAV → Demucs → guitar stem
4. generate_labels.py        →  Notes → piano-roll matrices → .npz
```

## Training

```bash
# Fase 1: Encoder congelado, solo cabezas de pitch
python train.py --phase 1 --dataset data/dataset/manifest.json --bp-weights basic_pitch_pytorch.pth

# Fase 2: Fine-tune end-to-end
python train.py --phase 2 --dataset data/dataset/manifest.json --resume checkpoints/phase1_best.pt

# Fase 3: Agregar tablatura
python train.py --phase 3 --dataset data/dataset/manifest.json --resume checkpoints/phase2_best.pt

# Fase 4: Final
python train.py --phase 4 --dataset data/dataset/manifest.json --resume checkpoints/phase3_best.pt
```

## Estructura

```
training/
├── README.md
├── requirements.txt
├── select_training_gps.py      # Paso 1: selección
├── synthesize_audio.py         # Paso 2: síntesis
├── process_demucs.py           # Paso 3: separación
├── generate_labels.py          # Paso 4: labels
├── model.py                    # LudiloNet (arquitectura)
├── dataset.py                  # Dataset + DataLoader
├── train.py                    # Training loop
├── data/                       # Datos generados (gitignored)
│   ├── selected_gps.json
│   ├── audio/
│   ├── stems/
│   └── dataset/
└── checkpoints/                # Modelos entrenados (gitignored)
```

## Metas

| Métrica | BP actual | Meta |
|---------|----------|------|
| F1 guitar (500ms) | 28% | 65%+ |
| F1 guitar (200ms) | 17% | 50%+ |
| Precision | 21% | 70%+ |
| String accuracy | N/A | 80%+ |
