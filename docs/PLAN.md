# 🎸 Ludilo — Plan de Desarrollo

> "Instrumento musical" en esperanto. Guitar Pro online con separación de stems, conversión a MIDI, y visualización interactiva.

## Visión del Producto

Aplicación web freemium que permite:
1. Subir audio (mp3, wav, m4a, flac) → separar instrumentos automáticamente
2. Convertir stems a MIDI
3. Mixer interactivo (volumen, solo, mute por pista)
4. Visualización en tiempo real: partitura, tablatura, piano roll (falling notes)
5. Biblioteca masiva de MIDIs (~2M archivos) con matching automático
6. Soporte de archivos Guitar Pro (.gp3-.gp7)
7. Reemplazo de instrumento (ej: voz → violín)

---

## Arquitectura

```
┌─────────────────────────────────────────────────────────────┐
│  Frontend (React + Vite + Tailwind)                         │
│  Azure Static Web Apps                                      │
│  - Player/Mixer (Tone.js + Web Audio API)                   │
│  - Piano Roll (Canvas/WebGL)                                │
│  - Partitura (OpenSheetMusicDisplay)                        │
│  - Tablatura (generada desde MIDI)                          │
└────────────────────────┬────────────────────────────────────┘
                         │ HTTPS
┌────────────────────────▼────────────────────────────────────┐
│  Backend (Python Azure Functions)                           │
│  - API REST (auth, upload, status, library, user mgmt)      │
│  - Orquestación de procesamiento                            │
│  - Notificaciones por email                                 │
└────────┬──────────────┬──────────────────┬──────────────────┘
         │              │                  │
         ▼              ▼                  ▼
┌──────────────┐ ┌─────────────┐ ┌────────────────────────────┐
│ Blob Storage │ │ Queue       │ │ Worker GPU                  │
│ - audio/     │ │ Storage     │ │                             │
│ - stems/     │ │ (cola de    │ │ Prioridad 1: Máquina local  │
│ - midi/      │ │  proceso)   │ │   NVIDIA A1000 6GB          │
│ - library/   │ │             │ │   Servicio Python siempre   │
└──────────────┘ └─────────────┘ │   escuchando la cola        │
                                 │                             │
                                 │ Prioridad 2: Azure Container│
                                 │   Instances (fallback)      │
                                 │   Se levanta cada 2h si:    │
                                 │   - Máquina local NO está   │
                                 │     procesando              │
                                 │   - Hay items en la cola    │
                                 │   Envía email a             │
                                 │   doniben@esperanto.co      │
                                 │   con # de audios en cola   │
                                 │   Se apaga si máquina local │
                                 │   se conecta                │
                                 └────────────────────────────────┘

┌──────────────┐
│ Cosmos DB    │
│ (serverless) │
│ - users      │
│ - songs      │
│ - library    │
│ - processing │
│   _jobs      │
└──────────────┘
```

---

## Stack Tecnológico

### Frontend
| Tecnología | Uso |
|-----------|-----|
| React 18 | UI framework |
| Vite | Build tool |
| Tailwind CSS | Estilos |
| Flowbite React | Componentes UI |
| Tone.js | Playback, síntesis, samplers |
| @tonejs/midi | Parsing MIDI |
| Web Audio API | Mixer, volumen por stem |
| OpenSheetMusicDisplay | Renderizado de partitura |
| Canvas/WebGL | Piano roll (falling notes) |
| @react-oauth/google | Auth Google |
| React Router | Navegación |
| React Query | Estado servidor |
| i18next | Internacionalización |

### Backend (Azure Functions - Python)
| Tecnología | Uso |
|-----------|-----|
| Azure Functions v4 | API serverless |
| azure-cosmos | Base de datos |
| azure-storage-blob | Almacenamiento de archivos |
| azure-storage-queue | Cola de procesamiento |
| google-auth | Verificación OAuth |
| stripe | Pagos |
| chromaprint/pyacoustid | Fingerprinting de audio |
| PyGuitarPro | Lectura de archivos .gp |
| sendgrid/azure-communication | Emails |

### Worker GPU (Python - Local + Azure Container Instances)
| Tecnología | Uso |
|-----------|-----|
| Demucs (htdemucs_6s) | Separación de stems (6 pistas) |
| Basic Pitch (Spotify) | Audio → MIDI |
| PyGuitarPro | .gp → MIDI |
| azure-storage-queue | Consumir cola |
| azure-storage-blob | Descargar/subir archivos |
| torch + CUDA | Aceleración GPU |

### Infraestructura Azure
| Servicio | Uso | Pricing |
|---------|-----|---------|
| Static Web Apps | Frontend | Free tier |
| Functions (Consumption) | API | Pay per execution |
| Cosmos DB (Serverless) | DB | Pay per RU |
| Blob Storage | Audio/MIDI/Stems | Pay per GB |
| Queue Storage | Cola de procesamiento | ~$0.00 (muy barato) |
| Container Instances | Fallback GPU | Pay per second |
| Timer Trigger (Function) | Verificar cola cada 2h | Incluido en Functions |
| Communication Services | Emails | Pay per email |

---

## Lógica del Worker GPU (Fallback Azure)

```
Cada 2 horas (Azure Function Timer Trigger):
  1. Verificar si máquina local está activa (heartbeat endpoint)
  2. SI máquina local está procesando → no hacer nada
  3. SI máquina local NO responde Y hay items en cola:
     a. Enviar email a doniben@esperanto.co:
        "Ludilo: X audios en cola. Levantando Azure Container Instance."
     b. Levantar Azure Container Instance con Demucs
     c. Procesar cola
     d. Al terminar, apagar instancia
  4. SI durante procesamiento Azure, máquina local envía heartbeat:
     a. Azure Container Instance termina el audio actual
     b. Se apaga
     c. Máquina local toma el control
```

### Heartbeat de máquina local
- El worker local envía un heartbeat cada 30 segundos a un endpoint del backend
- El backend guarda el timestamp del último heartbeat en Cosmos DB
- Si el heartbeat tiene más de 2 minutos de antigüedad → máquina considerada offline

---

## Bibliotecas MIDI

| Dataset | Archivos | Fuente |
|---------|----------|--------|
| Lakh MIDI | 176,581 | HuggingFace/colinraffel |
| Los Angeles MIDI | ~405,000 | HuggingFace |
| GigaMIDI | 1,437,304 | Verificar licencia |
| Biblioteca personal .gp | Variable | Tu colección |
| **Total estimado** | **~2M+** | |

### Indexación
- Cada MIDI se indexa con: título, artista (si disponible), instrumentos, duración, género, hash
- Se genera fingerprint para matching con audio subido
- Se almacena metadata en Cosmos DB, archivos en Blob Storage

---

## Modelo Freemium

| Feature | Free | Premium ($X/mes) |
|---------|------|-------------------|
| Canciones procesadas/mes | 3 | Ilimitadas |
| Biblioteca MIDI | Búsqueda limitada | Completa |
| Visualización | Piano roll básico | Partitura + Tab + Piano roll |
| Exportar MIDI/Partitura | ❌ | ✅ |
| Velocidad de playback | 1x | 0.25x - 2x |
| Loop de secciones | ❌ | ✅ |
| Reemplazo de instrumento | ❌ | ✅ |
| Ads | Sí | No |
| Calidad de stems | Standard | Alta (6 stems) |

---

## Repos

| Repo | Contenido |
|------|-----------|
| `ludilo-frontend` | React + Vite SPA |
| `ludilo-backend` | Azure Functions (API + Worker local + Timer triggers) |

El worker local vive en el mismo repo del backend (carpeta `worker/`) porque comparte dependencias y lógica con las Functions.

---

## Plan por Sprints

### Sprint 1 — Setup & Auth (Semana 1-2)
- [ ] S1-01: Crear repos en GitHub (ludilo-frontend, ludilo-backend)
- [ ] S1-02: Setup proyecto frontend (React + Vite + Tailwind + Flowbite)
- [ ] S1-03: Setup proyecto backend (Azure Functions Python v4)
- [ ] S1-04: Crear Resource Group en Azure (rg-ludilo)
- [ ] S1-05: Crear Cosmos DB serverless (ludilodb)
- [ ] S1-06: Crear Storage Account (stludilo) con containers: audio, stems, midi, library
- [ ] S1-07: Crear Queue Storage (audio-processing-queue)
- [ ] S1-08: Implementar registro de usuario (email + password)
- [ ] S1-09: Implementar login con Google OAuth
- [ ] S1-10: Implementar login con email/password
- [ ] S1-11: Frontend: Landing page básica
- [ ] S1-12: Frontend: Páginas de login/registro
- [ ] S1-13: Frontend: Dashboard vacío (post-login)
- [ ] S1-14: Deploy frontend a Azure Static Web Apps
- [ ] S1-15: Deploy backend a Azure Functions

### Sprint 2 — Upload & Cola (Semana 3-4)
- [ ] S2-01: API: Endpoint de upload de audio (genera SAS token → Blob)
- [ ] S2-02: API: Endpoint para encolar procesamiento (agrega mensaje a Queue)
- [ ] S2-03: API: Endpoint de status de procesamiento (polling)
- [ ] S2-04: Modelo Cosmos DB: songs (id, userId, title, status, stems[], midi[], metadata)
- [ ] S2-05: Frontend: Componente de upload con drag & drop
- [ ] S2-06: Frontend: Lista de canciones del usuario con status
- [ ] S2-07: Frontend: Indicador de progreso de procesamiento
- [ ] S2-08: Validación de formatos soportados (mp3, wav, m4a, flac, ogg)
- [ ] S2-09: Límite de tamaño de archivo (50MB free, 200MB premium)

### Sprint 3 — Worker Local (Semana 5-6)
- [ ] S3-01: Setup worker Python con consumo de Azure Queue
- [ ] S3-02: Integrar Demucs (htdemucs_6s) para separación de stems
- [ ] S3-03: Descargar audio de Blob → procesar → subir stems a Blob
- [ ] S3-04: Integrar Basic Pitch para conversión stems → MIDI
- [ ] S3-05: Subir archivos MIDI generados a Blob Storage
- [ ] S3-06: Actualizar status en Cosmos DB al completar
- [ ] S3-07: Implementar heartbeat del worker local (cada 30s)
- [ ] S3-08: API: Endpoint de heartbeat (POST /worker/heartbeat)
- [ ] S3-09: Manejo de errores y reintentos (max 3 intentos por audio)
- [ ] S3-10: Logging y monitoreo del worker
- [ ] S3-11: Script de instalación del worker (setup CUDA, dependencias)
- [ ] S3-12: Pruebas con canciones de diferentes duraciones en A1000

### Sprint 4 — Mixer & Player (Semana 7-8)
- [ ] S4-01: Frontend: Componente Player con Web Audio API
- [ ] S4-02: Frontend: Cargar stems desde Blob Storage (SAS URLs)
- [ ] S4-03: Frontend: Control de volumen individual por stem
- [ ] S4-04: Frontend: Botones Solo/Mute por stem
- [ ] S4-05: Frontend: Barra de progreso con seek
- [ ] S4-06: Frontend: Play/Pause/Stop
- [ ] S4-07: Frontend: Visualización de waveform por stem
- [ ] S4-08: Frontend: Indicador de qué instrumento es cada stem
- [ ] S4-09: API: Endpoint para obtener URLs de stems de una canción

### Sprint 5 — Fallback Azure Container Instances (Semana 9-10)
- [ ] S5-01: Crear Dockerfile con Demucs + Basic Pitch + CUDA
- [ ] S5-02: Subir imagen a Azure Container Registry
- [ ] S5-03: Azure Function Timer Trigger (cada 2 horas)
- [ ] S5-04: Lógica: verificar heartbeat de máquina local
- [ ] S5-05: Lógica: contar items en cola
- [ ] S5-06: Lógica: enviar email con # de audios en cola
- [ ] S5-07: Lógica: levantar Azure Container Instance solo si local offline + cola > 0
- [ ] S5-08: Lógica: apagar ACI si máquina local envía heartbeat
- [ ] S5-09: Configurar alertas de costo en Azure (budget $10/mes para ACI)
- [ ] S5-10: Pruebas controladas: 1 audio con ACI, verificar costos
- [ ] S5-11: Pruebas: simular máquina local offline → ACI se levanta
- [ ] S5-12: Pruebas: máquina local se conecta → ACI se apaga

### Sprint 6 — Biblioteca MIDI & Matching (Semana 11-12)
- [ ] S6-01: Descargar Lakh MIDI Dataset (176K archivos)
- [ ] S6-02: Descargar Los Angeles MIDI Dataset (405K archivos)
- [ ] S6-03: Script de indexación: extraer metadata de cada MIDI
- [ ] S6-04: Subir MIDIs a Blob Storage (container: library)
- [ ] S6-05: Indexar metadata en Cosmos DB (título, instrumentos, duración)
- [ ] S6-06: Integrar Chromaprint/AcoustID para fingerprinting
- [ ] S6-07: Al subir audio: generar fingerprint → buscar match en biblioteca
- [ ] S6-08: Si hay match: proponer al usuario usar MIDI de biblioteca (gratis, instantáneo)
- [ ] S6-09: Si no hay match: ir por flujo normal (Demucs → Basic Pitch)
- [ ] S6-10: API: Endpoint de búsqueda en biblioteca (por título, artista)
- [ ] S6-11: Frontend: Buscador de canciones en biblioteca
- [ ] S6-12: Frontend: Modal "Encontramos esta canción en nuestra biblioteca"
- [ ] S6-13: Importador de archivos .gp (PyGuitarPro → MIDI + metadata tab)
- [ ] S6-14: Script para importar tu biblioteca personal de Guitar Pro

### Sprint 7 — Piano Roll & Visualización Básica (Semana 13-14)
- [ ] S7-01: Frontend: Componente PianoRoll con Canvas
- [ ] S7-02: Renderizado de notas MIDI como rectángulos (falling notes)
- [ ] S7-03: Sincronización piano roll ↔ playback de audio
- [ ] S7-04: Colores por instrumento/pista
- [ ] S7-05: Scroll automático siguiendo la posición actual
- [ ] S7-06: Zoom horizontal (compresión/expansión temporal)
- [ ] S7-07: Teclado de piano lateral como referencia visual
- [ ] S7-08: Highlight de nota activa durante playback
- [ ] S7-09: Frontend: Selector de pista a visualizar

### Sprint 8 — Partitura & Tablatura (Semana 15-16)
- [ ] S8-01: Integrar OpenSheetMusicDisplay para renderizado de partitura
- [ ] S8-02: Convertir MIDI → MusicXML para partitura
- [ ] S8-03: Sincronización partitura ↔ playback
- [ ] S8-04: Highlight de nota actual en partitura
- [ ] S8-05: Generación de tablatura desde MIDI (lógica de posiciones en diapasón)
- [ ] S8-06: Renderizado de tablatura (6 líneas, números de traste)
- [ ] S8-07: Sincronización tablatura ↔ playback
- [ ] S8-08: Selector de vista: Piano Roll / Partitura / Tablatura
- [ ] S8-09: Configuración de afinación para tablatura (standard, drop D, etc.)

### Sprint 9 — Reemplazo de Instrumento & Features Avanzados (Semana 17-18)
- [ ] S9-01: Selector de instrumento por pista (piano, violín, guitarra, flauta, etc.)
- [ ] S9-02: Integrar Tone.js Sampler con soundfonts por instrumento
- [ ] S9-03: Reproducir MIDI con instrumento seleccionado (reemplazar stem de audio)
- [ ] S9-04: Control de velocidad de playback (0.25x, 0.5x, 0.75x, 1x, 1.25x, 1.5x, 2x)
- [ ] S9-05: Loop de secciones (seleccionar inicio/fin en timeline)
- [ ] S9-06: Marcadores de secciones (intro, verso, coro, etc.) — manual
- [ ] S9-07: Metrónomo integrado (BPM desde MIDI)
- [ ] S9-08: Contador de compases

### Sprint 10 — Freemium & Pagos (Semana 19-20)
- [ ] S10-01: Integrar Stripe (crear cuenta, configurar productos)
- [ ] S10-02: API: Endpoints de suscripción (crear, cancelar, verificar)
- [ ] S10-03: Webhook de Stripe para actualizar status de usuario
- [ ] S10-04: Frontend: Página de planes y precios
- [ ] S10-05: Frontend: Checkout con Stripe
- [ ] S10-06: Implementar límites por plan (canciones/mes, features)
- [ ] S10-07: Middleware de verificación de plan en endpoints premium
- [ ] S10-08: Frontend: Indicador de uso (X/3 canciones este mes)
- [ ] S10-09: Ads para usuarios free (Google AdSense o similar)
- [ ] S10-10: Landing page final con pricing, features, demo

### Sprint 11 — Pulido & Launch (Semana 21-22)
- [ ] S11-01: SEO y meta tags
- [ ] S11-02: PWA (manifest, service worker básico)
- [ ] S11-03: Onboarding para nuevos usuarios (tour guiado)
- [ ] S11-04: Página de FAQ
- [ ] S11-05: Términos de servicio y política de privacidad
- [ ] S11-06: Optimización de performance (lazy loading, code splitting)
- [ ] S11-07: Testing E2E del flujo completo
- [ ] S11-08: Monitoreo con Application Insights
- [ ] S11-09: Dominio personalizado (ludilo.co o similar)
- [ ] S11-10: Launch 🚀

### Sprint 12+ — Post-Launch (Ongoing)
- [ ] S12-01: Detección automática de acordes
- [ ] S12-02: Modo práctica (silenciar instrumento, tocar encima con micrófono)
- [ ] S12-03: Compartir arreglos entre usuarios
- [ ] S12-04: Comunidad: correcciones a tabs generados
- [ ] S12-05: App móvil (PWA mejorada o React Native)
- [ ] S12-06: Integración con YouTube (pegar URL → extraer audio)
- [ ] S12-07: Detección automática de secciones (IA)
- [ ] S12-08: Modo karaoke (letra sincronizada)

---

## Estimación de Costos Azure (Mensual, uso bajo-medio)

| Servicio | Estimación |
|---------|-----------|
| Static Web Apps | $0 (free tier) |
| Functions (Consumption) | $0-5 |
| Cosmos DB (Serverless) | $1-10 |
| Blob Storage (50GB) | $1-2 |
| Queue Storage | ~$0 |
| Container Instances (fallback, ~2h/mes) | $2-5 |
| Communication Services (emails) | ~$0 |
| **Total estimado** | **$5-25/mes** |

> Nota: El costo principal es tu máquina local (electricidad). Azure es solo fallback.

---

## Decisiones Técnicas

1. **Worker en mismo repo que backend** — Comparten dependencias Azure, modelos de datos, y configuración
2. **Queue Storage sobre Service Bus** — Más simple y barato para este caso de uso
3. **Cosmos DB Serverless** — Pay per request, ideal para tráfico variable
4. **Demucs htdemucs_6s** — 6 stems (vocals, drums, bass, guitar, piano, other) vs 4 del modelo base
5. **Basic Pitch sobre Omnizart** — Más ligero, mejor para GPU limitada
6. **OpenSheetMusicDisplay sobre VexFlow** — Más completo para partituras, soporta MusicXML nativo
7. **Tone.js** — Ecosistema completo: playback, síntesis, samplers, MIDI
8. **Chromaprint** — Fingerprinting estándar de la industria, base de datos AcoustID gratuita
