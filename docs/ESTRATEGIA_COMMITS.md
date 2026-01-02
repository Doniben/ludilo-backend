# Ludilo — Estrategia de Commits

## Regla

- **Los push a GitHub se distribuyen a lo largo de la semana** (no el mismo día que se desarrolla).
- **Deploy a Azure sí se hace inmediato** (Functions, Static Web Apps). El deploy no depende de GitHub.
- Aplica tanto para frontend como para backend.
- Cada sábado se prepara el batch de commits de la semana entrante.

## Flujo de trabajo

1. **Sábado (sesión de desarrollo):** trabajar local, hacer commits locales sin push.
2. **Domingo a viernes:** el script `publish.sh` sube 1-2 commits por día (distribuidos).
3. **Siguiente sábado:** nueva sesión, nuevo batch de commits.

## Cómo funciona publish.sh

El script usa `git push` programado con fechas. Los commits ya están hechos localmente con sus mensajes reales. El script simplemente los pushea en los días indicados.

**Opción A (manual):** correr `./publish.sh` cada día y sube lo que toca ese día.
**Opción B (cron):** programar un cron que lo corra automáticamente cada día.

## Uso

```bash
# Desde la carpeta del proyecto
cd /Users/doniben/Documents/PROGRAMMING-GIT/Ludilo
./publish.sh
```

El script verifica qué día es y pushea los commits correspondientes a ese día.
