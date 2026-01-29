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

## Sesión 16-17 mayo 2026 — Resumen

### Sprint 6 (Biblioteca) — Completado
- Biblioteca GP: 66K archivos indexados con artista/título/format/source
- Biblioteca Lakh: 178K MIDIs re-indexados con pretty_midi (72% con título)
- Biblioteca LA MIDI: 404K en progreso (48%, ~8h restantes)
- AcoustID integrado con fpcalc server-side en Azure Functions
- Matching: por nombre de archivo + AcoustID post-upload
- Endpoint /library/search con filtros (source=guitarpro|midi|ludilo)
- Endpoint /library/identify (fpcalc + AcoustID)
- Endpoint /library/use (registrar canción de biblioteca)
- Endpoint /library/preview (URL temporal SAS)
- Endpoint /library/musicxml (MIDI → MusicXML con music21, cacheado)
- Fix: Lakh paths (lakh/ → lakh/lmd_full/ en preview/musicxml)
- Priorización: GP > Lakh > LA MIDI en resultados

### Sprint 8 (Partitura & Tab) — En progreso
- AlphaTabView: renderiza .gp con tablatura/partitura/piano roll
- SpessaSynth: playback con soundfont (5 opciones: Fast→Ultra, cacheados)
- Mixer: control de volumen por track con mute
- Cursor sincronizado con time signatures reales
- Control de velocidad (25-150%)
- Loop básico (10s desde posición actual)
- Piano Roll Synthesia: notas cayendo + teclado HTML con glow
- ScoreView: OSMD renderiza MusicXML para archivos MIDI
- MidiPlayer: reproductor SpessaSynth para archivos MIDI
- MidiPreview: preview inline en biblioteca (GP + MIDI) con SpessaSynth singleton
- QualityBadge: indicador visual de calidad (5 barras GP, 3 barras MIDI, L Ludilo)
- Library viewer: /library/view con botón "Agregar a mis canciones"

### Pendientes inmediatos
- Cursor OSMD sincronizado con SpessaSynth (implementado, por probar)
- Fix: programa inicial SpessaSynth (piano suena como otro instrumento primera vez)
- Piano Roll para MIDI (PianoRollView con fileUrl)
- Sprint 3: Worker GPU (Demucs + Basic Pitch)
- Deploy frontend
- Quitar console.logs de debug

### Archivos clave modificados
- Backend: functions/routes/library.py (todos los endpoints de biblioteca)
- Backend: functions/routes/upload.py (delete song, blobPath en response)
- Backend: functions/requirements.txt (music21 agregado)
- Backend: bin/fpcalc (binario Linux para Azure Functions)
- Frontend: src/components/AlphaTabView.jsx (visor GP completo)
- Frontend: src/components/MidiPlayer.jsx (reproductor MIDI)
- Frontend: src/components/MidiPreview.jsx (preview inline con SpessaSynth singleton)
- Frontend: src/components/ScoreView.jsx (OSMD + cursor)
- Frontend: src/components/PianoRollView.jsx (canvas horizontal)
- Frontend: src/components/QualityBadge.jsx (indicador de calidad)
- Frontend: src/pages/SongView.jsx (visor unificado GP/MIDI)
- Frontend: src/pages/Library.jsx (búsqueda + filtros + preview)
- Frontend: src/pages/Dashboard.jsx (matching + upload flow)

### Procesos background (17 mayo)
- LA MIDI: 193K/404K (48%) — corriendo PID 65138
- Lakh re-index: ✅ completo
- GP source fix: ✅ completo

### Commits sin push
- Backend: 15 commits
- Frontend: 19 commits

## Colección Balkan MIDI (subida 18 mayo 2026)

Archivos en Blob Storage: `library/balkan-midi/`

| Archivo | Artista | Canción | Info |
|---------|---------|---------|------|
| Poso_Kuca_Birtija.mid | Zabranjeno Pušenje | Pos'o, Kuća, Birtija | Album: Agent tajne sile (1999). Banda de Sarajevo, rock/punk balcánico. |
| Zeni_Nam_Se_Vukota.mid | Traditional (Balkan folk) | Ženi Nam Se Vukota | Canción folk tradicional balcánica (boda). |
| Pristao_Sam_Bicu_Sve_Sto_Hoce.mid | Centar Film / Televizija Beograd | Pristao Sam, Biću Sve Što Hoće | Canción serbia popular. |
| Sanjao_Sam_Nocas_Da_Te_Nemam.kar | Bijelo Dugme (Goran Bregović) | Sanjao Sam Noćas Da Te Nemam | Compilación "Velike Rock Balade" (1984). Bijelo Dugme = banda más importante de Yugoslavia. Formato .kar (MIDI karaoke con letra). |

Fuente original: descargados de una página web (no recordada). Buscar más en sitios de MIDI karaoke balcánicos.


## Sesión 18-20 mayo 2026 — Resumen

### Sprint 3 (Worker) — Completado
- Worker node: ludilo-worker repo en GitHub (Doniben/ludilo-worker)
- Pipeline: Demucs htdemucs_ft (4 stems) + htdemucs_6s (guitar/piano) → Basic Pitch ONNX → Upload
- Detección de silencio: stems vacíos no se suben ni procesan
- Conversión WAV→MP3 192kbps antes de subir (~92% menos peso)
- Chord detection: chord-extractor (Chordino) — acordes con timestamps
- Retries en upload (3 intentos)
- Probado en A1000 con CUDA: ~2-3 min por canción
- Polling cada 2 min cuando no hay jobs
- Dependencias: numpy==1.26.4 (pinned), basic-pitch[onnx], demucs, chord-extractor

### Sprint 4 (Stem Player) — Completado (8/9)
- StemPlayer: Web Audio API, 6 stems simultáneos
- Solo/Mute/Volume por instrumento con colores
- Barra de progreso con seek
- Speed control (25-150%)
- Cache API para stems (no re-descarga)
- Spacebar play/pause
- Selector de instrumento (cambia MIDI visualizado)
- Fake seqRef para sincronizar visores con stems
- Falta: waveform (nice-to-have)

### Sprint 5 (ACI) — Parcial
- Timer cada 5 min: envía email si hay audios en cola
- Timer cada hora: activa/desactiva flag, apaga ACI si cola vacía
- Endpoint /aci/start: levanta ACI desde link en email
- Email al usuario cuando su canción empieza a procesarse
- PENDIENTE: Dockerfile, ACR, container group con GPU T4

### Sprint 8 (Partitura/Tab MIDI) — Mejoras
- TabView: acordes arriba de la tablatura (cyan/verde)
- ScoreView: reset al cambiar instrumento
- PianoRollView: cambio inmediato de instrumento (refs)
- Filtros biblioteca: All, Pro, High, Our Own

### Biblioteca
- LA MIDI: ✅ Completa (404,714 indexados)
- MUSDB18: 150 masters subidos a blob (library/masters/musdb18/)
- 4 MIDIs balcánicos subidos e indexados
- Canciones procesadas se agregan automáticamente a library_index (source=ludilo)
- QualityBadge: mini logo gradiente para Ludilo

### Worker — Problemas resueltos
- numpy 2.x incompatible con scipy/vamp del sistema → pin numpy==1.26.4
- TensorFlow rompe Basic Pitch → desinstalado, Basic Pitch usa ONNX
- autochord incompatible (necesita TF) → reemplazado por chord-extractor
- Upload connection refused → retries 3x con 5s delay
- Stems vacíos → detección RMS < 0.001, skip

### Próxima sesión: ACI
- Dockerfile: Python 3.10 + CUDA + Demucs + Basic Pitch + chord-extractor
- Azure Container Registry: subir imagen (~8-10 GB)
- Container group: GPU T4, restart policy Never
- Costo estimado: ~$0.02/canción, ~$2/mes para 100 canciones
- Worker auto-stop: si no hay jobs por 10 min, exit(0)
