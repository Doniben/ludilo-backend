# 🎸 Ludilo Backend

Backend de Ludilo — Guitar Pro online con separación de stems, conversión a MIDI, y visualización interactiva.

## Stack

- **Azure Functions** (Python v4) — API serverless
- **Cosmos DB** (Serverless) — Base de datos
- **Blob Storage** — Audio, stems, MIDI, biblioteca
- **Queue Storage** — Cola de procesamiento
- **Worker GPU** — Demucs + Basic Pitch (local NVIDIA A1000 + fallback Azure Container Instances)

## Estructura

```
├── docs/              # Documentación del proyecto
│   └── PLAN.md        # Plan maestro con sprints
├── functions/         # Azure Functions (API)
├── worker/            # Worker GPU local
└── README.md
```

## Documentación

Ver [docs/PLAN.md](docs/PLAN.md) para el plan completo del proyecto.

## Proyecto

Tablero de tareas: https://github.com/users/Doniben/projects/1
