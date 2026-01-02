# Ludilo — Contexto del Proyecto

> Documento de referencia para continuar el desarrollo en cualquier sesión.

## Qué es Ludilo

Plataforma web freemium de aprendizaje musical. Sube cualquier canción → separa instrumentos con IA → convierte a MIDI → visualiza en piano roll, partitura y tablatura en tiempo real. Biblioteca de 2M+ MIDIs con matching automático.

## Repos

| Repo | URL | Contenido |
|------|-----|-----------|
| Frontend | https://github.com/Doniben/ludilo-frontend | React + Vite + Tailwind |
| Backend | https://github.com/Doniben/ludilo-backend | Azure Functions + Worker GPU + Docs |

**Local:** `/Users/doniben/Documents/PROGRAMMING-GIT/Ludilo/`

## Tablero del Proyecto

https://github.com/users/Doniben/projects/1

125 issues organizados en 12 sprints con campo "Sprint" y milestones.

## Stack

### Frontend
- React 18 + Vite 8 + Tailwind 3.4 + Framer Motion
- i18n: español, esperanto, inglés
- Dark/Light theme (ThemeContext + localStorage)
- Tipografía: Clash Display + Satoshi (Fontshare)
- Estética: "Sonic Noir" — neon cyan/magenta, noise overlay, glass cards
- Node 22 (`.nvmrc`)

### Backend
- Python Azure Functions v4
- Cosmos DB serverless (ludilodb)
- Azure Blob Storage (stludilo): containers audio, stems, midi, library
- Azure Queue Storage (audio-processing-queue)
- Auth: Google OAuth + sistema propio (JWT)
- Pagos: Stripe

### Worker GPU
- Máquina local: NVIDIA A1000 6GB (prioridad)
- Fallback: Azure Container Instances (cada 2h si local offline + cola > 0)
- Demucs htdemucs_6s (6 stems: vocals, drums, bass, guitar, piano, other)
- Basic Pitch (Spotify) para audio → MIDI
- Heartbeat cada 30s al backend
- Email a doniben@esperanto.co cuando ACI se levanta

### Infraestructura Azure
- Resource Group: rg-ludilo (por crear)
- Cosmos DB serverless
- Storage Account con Blob + Queue
- Azure Functions (Consumption plan)
- Azure Static Web Apps (frontend)
- Azure Container Instances (fallback GPU)
- Azure Container Registry (imagen Docker del worker)

## Arquitectura de referencia

Basada en los proyectos de EsperantoCo (SAI):
- Frontend: React + Vite + Tailwind + Flowbite (Azure Static Web Apps)
- Backend: Python Azure Functions con Cosmos DB
- Auth: Google OAuth con `@react-oauth/google` + sistema propio
- Estructura: cada function en su carpeta con `__init__.py` + `function.json`

## Estado Actual

### Completado
- [x] S1-01: Repos creados y pusheados
- [x] S1-02: Setup frontend (React + Vite + Tailwind + i18n + theme)

### Siguiente
- [ ] S1-03: Setup backend (Azure Functions Python v4)
- [ ] S1-04: Crear Resource Group en Azure
- [ ] S1-05: Crear Cosmos DB serverless
- [ ] S1-06: Crear Storage Account con containers
- [ ] S1-07: Crear Queue Storage
- [ ] S1-08-10: Auth (registro, Google OAuth, login)
- [ ] S1-11-13: Frontend (landing ✅, login/registro, dashboard)
- [ ] S1-14-15: Deploy

## Decisiones Tomadas

1. **2 repos** (no 4): frontend y backend. Worker vive en backend/worker/
2. **Node 22** requerido (Vite 8 lo necesita)
3. **Sin referencia a Guitar Pro** — Ludilo es marca propia
4. **Flujo de trabajo**: probar local primero, commit/push solo cuando funciona
5. **Fallback Azure**: Timer trigger cada 2h, solo si local offline + cola > 0
6. **Presupuesto ACI**: alerta a $10/mes
7. **Bibliotecas MIDI**: Lakh (176K) + Los Angeles (405K) + GigaMIDI (1.4M) + .gp personales
8. **Archivos .gp**: PyGuitarPro para leer, GuitarPro-to-Midi para convertir

## Comandos Útiles

```bash
# Frontend
cd /Users/doniben/Documents/PROGRAMMING-GIT/Ludilo/ludilo-frontend
export NVM_DIR="$HOME/.nvm" && . "$NVM_DIR/nvm.sh" && nvm use 22
npm run dev    # http://localhost:5173
npm run build  # verificar build

# Backend (cuando esté listo)
cd /Users/doniben/Documents/PROGRAMMING-GIT/Ludilo/ludilo-backend
func start     # Azure Functions local

# GitHub
gh issue list --repo Doniben/ludilo-backend --milestone "Sprint 1 - Setup & Auth"
gh issue close <N> --repo Doniben/ludilo-backend
```

## Cuentas y Accesos

- **GitHub**: Doniben (gh CLI autenticado)
- **Azure**: az CLI logueado en terminal
- **Región Azure preferida**: por definir (eastus2 propuesto)
- **Email notificaciones**: doniben@esperanto.co
