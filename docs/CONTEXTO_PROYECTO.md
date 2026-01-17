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
- [x] S1-03: Setup backend (Azure Functions Python v4)
- [x] S1-08/09/10: Auth (registro, Google OAuth, login)
- [x] S1-12/13: Frontend (login, registro, dashboard)
- [x] S2-01/02/03/04: Endpoints upload, process, status, list songs
- [x] S2-05/06: Upload integrado en dashboard con drag&drop
- [x] S2-07/11: Indicador de progreso + posición en cola
- [x] S5-03/04/05/06: Timer trigger ACI, heartbeat, email notificación
- [x] S5-07/08: Levantar/apagar ACI según heartbeat y cola
- [x] S6-05: Indexar metadata GP en Cosmos DB (66,435 docs)
- [x] S6-08: Frontend - Modal "encontramos esta canción" en upload
- [x] S6-10: API búsqueda en biblioteca (GET /library/search?q=)
- [x] S6-12: Frontend - Explorar biblioteca (/library)
- [x] S6-14: Importar biblioteca Guitar Pro (66K archivos en Blob)

### En Progreso (background, 16 mayo 2026)
- [ ] S6-01: Lakh MIDI — 178K subidos a Blob, indexación en Cosmos DB ~80% (PID 46548)
- [ ] S6-02: LA MIDI — 404K archivos procesándose desde zip (subir + indexar, ~24h, PID 8581)

### Procesos en Background
- **Lakh indexación**: `tail -1 /tmp/ludilo-midi/lakh_index.log`
- **LA MIDI (subir + indexar)**: `tail -1 /tmp/ludilo-midi/la_process.log`
- Cuando terminen, verificar con: `python3 -c "from azure.cosmos import CosmosClient; ..."`

### Siguiente (próxima sesión)
- [ ] S6-04: Verificar que Lakh y LA MIDI estén completos en Blob Storage
- [ ] S6-07: Matching audio → biblioteca MIDI (Chromaprint/AcoustID)
- [ ] S6-09: Flujo normal si no hay match
- [ ] S6-11: Frontend - Buscador de canciones (redundante con S6-12, cerrar)
- [ ] Corregir artista en indexación GP (sale "Ludilo-Gp-Upload" en vez del artista real)
- [ ] S6-03: Enriquecer metadata de GP con PyGuitarPro (tarea background futura)

### Commits sin push (distribuir con publish.sh)
- Backend: 10 commits adelante de origin/main
- Frontend: 5 commits adelante de origin/main

### Deploy
- Backend desplegado en Azure Functions (incluye /library/search)
- Frontend NO desplegado (tiene cambios de biblioteca + upload matching)

## Decisiones Tomadas

1. **2 repos** (no 4): frontend y backend. Worker vive en backend/worker/
2. **Node 22** requerido (Vite 8 lo necesita)
3. **Sin referencia a Guitar Pro** — Ludilo es marca propia
4. **Flujo de trabajo**: probar local primero, commit/push solo cuando funciona
5. **Fallback Azure**: Timer trigger cada 2h, solo si local offline + cola > 0
6. **Presupuesto ACI**: alerta a $10/mes
7. **Bibliotecas MIDI**: Lakh (176K) + Los Angeles (405K) + GigaMIDI (1.4M) + .gp personales
8. **Archivos .gp**: PyGuitarPro para leer, GuitarPro-to-Midi para convertir
9. **Commits distribuidos**: no push el mismo día. Se acumulan y publish.sh los distribuye en la semana
10. **Issues**: se mueven a Done en el tablero inmediato, pero se cierran distribuidos (cuenta como contribución)
11. **Deploy a Azure**: inmediato, no depende de los commits a GitHub
12. **Backend se prueba en Azure**: Python 3.12 en Azure, local no compatible con func tools 4.0.6821. No correr func start local.
13. **Frontend apunta a Azure**: .env tiene `VITE_API_URL=https://ludilo-api.azurewebsites.net/api`
14. **Errores i18n**: backend envía códigos (INVALID_CREDENTIALS, etc), frontend los traduce según idioma
15. **Sin emojis en UI**: usar Heroicons (ya instalado @heroicons/react)
16. **Light mode**: usa ludilo-700 (teal oscuro) en vez de neon-cyan. Clase utilitaria `text-accent`
17. **Auth state en Navbar**: se actualiza con evento custom `ludilo-auth` (dispatchEvent)
18. **Azure Functions modelo v2** (blueprints): function_app.py registra blueprints de routes/
19. **CORS**: configurado en Azure (`*`) + headers en código (shared/response.py)
20. **Heartbeat worker**: cada 60 segundos (no 30)

## Hallazgos Técnicos

- **Vite 8** requiere Node ≥20.19 o ≥22.12. Usar Node 22 con nvm.
- **Azure Functions Core Tools 4.0.6821** no tiene worker para Python 3.12 en macOS. No se puede correr local.
- **CORS en Azure Functions**: configurar `*` en portal NO es suficiente si hay otros orígenes listados. Dejar solo `*`. Además agregar headers en código.
- **localStorage + React**: cambios en localStorage no disparan re-render en otros componentes. Usar eventos custom.
- **Static Web Apps**: al vincular con GitHub, Azure crea un commit automático con el workflow de GitHub Actions.
- **Vite .env**: `.env.local` tiene prioridad sobre `.env`. Si existe, sobreescribe variables.
- **Vite puerto**: no siempre usa 5173, puede asignar 5174, 5175, etc. si el puerto está ocupado.

## URLs de Producción

- **Frontend**: https://green-flower-089c5500f.7.azurestaticapps.net
- **Backend API**: https://ludilo-api.azurewebsites.net/api
- **Health check**: https://ludilo-api.azurewebsites.net/api/health
- **Cosmos DB**: https://ludilodb.documents.azure.com:443/
- **Blob Storage**: https://stludilo.blob.core.windows.net/
- **Proyecto GitHub**: https://github.com/users/Doniben/projects/1

## Comandos Útiles

```bash
# Frontend
cd /Users/doniben/Documents/PROGRAMMING-GIT/Ludilo/ludilo-frontend
export NVM_DIR="$HOME/.nvm" && . "$NVM_DIR/nvm.sh" && nvm use 22
npm run dev    # http://localhost:5173 (apunta a Azure backend)
npm run build  # verificar build

# Backend - deploy a Azure
cd /Users/doniben/Documents/PROGRAMMING-GIT/Ludilo/ludilo-backend/functions
func azure functionapp publish ludilo-api

# Backend - NO se corre local (Python 3.12 en Azure, local no compatible)
# Todo se prueba contra: https://ludilo-api.azurewebsites.net/api

# GitHub
gh issue list --repo Doniben/ludilo-backend --milestone "Sprint 1 - Setup & Auth"
```

## Cuentas y Accesos

- **GitHub**: Doniben (gh CLI autenticado)
- **Azure**: az CLI logueado en terminal
- **Región Azure preferida**: por definir (eastus2 propuesto)
- **Email notificaciones**: doniben@esperanto.co

## Estrategia de Formatos de Biblioteca

### Por qué indexamos .gp (Guitar Pro) además de MIDI

Los archivos `.gp` son **más ricos** que MIDI para nuestro caso de uso:

| Dato | .gp | MIDI |
|------|-----|------|
| Notas y timing | ✅ | ✅ |
| Posición en diapasón (cuerda + traste) | ✅ | ❌ |
| Afinación por cuerda | ✅ | ❌ |
| Técnicas (bend, slide, hammer-on, etc.) | ✅ | ❌ |
| Estructura (secciones) | ✅ | ❌ |

### Flujo de entrega al frontend

| Fuente | Piano roll / Partitura | Tablatura |
|--------|----------------------|-----------|
| .gp | Convertir a MIDI (trivial, GuitarPro-to-Midi) | Leer directo con PyGuitarPro ✅ |
| MIDI (Lakh/LA) | Usar directo ✅ | Requiere algoritmo S8-05 (asignar posiciones en diapasón) |

### Prioridad de entrega

1. Si hay `.gp` → preferir siempre (tablatura precisa + MIDI derivado para piano roll)
2. Si solo hay MIDI → piano roll directo, tablatura con heurística (S8-05)

### Pre-procesamiento futuro

- Generar MIDI derivado de cada .gp (batch o on-demand) para servir piano roll sin conversión en tiempo real
- Enriquecer metadata de .gp con PyGuitarPro (instrumentos, afinación, tempo) — tarea background
