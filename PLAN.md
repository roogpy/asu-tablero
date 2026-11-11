# Plan — Tablero diario del Aeropuerto Silvio Pettirossi (Android)

Todo corre en la nube: GitHub Actions junta los datos cada noche y GitHub Pages sirve la app. Tu PC solo se usa para programar.

| Fase | Qué se construye | Criterio de listo | Consultas a la API |
|---|---|---|---|
| 0 · Sonda | `probe.py` corrido una vez desde tu PC: 1 consulta de llegadas y 1 de salidas, guarda el JSON crudo y reporta cantidad, codeshares, estados y horas cubiertas | Sabemos si el plan gratis devuelve el día completo de ASU | 2 |
| 1 · Recolector | `collect.py` + presupuesto en `data/budget.json`; genera `data/AAAA-MM-DD.json` limpio y `data/index.json` | `pytest` verde usando los JSON de la sonda como fixtures | 0 |
| 2 · App móvil | PWA con pestañas Llegadas / Salidas / Resumen, lee los JSON del día | Se ve bien en ancho de celular (captura a 390 px), sin errores de consola, totales iguales a los del JSON | 0 |
| 3 · Nube | Repo en GitHub, secreto `AVIATIONSTACK_KEY`, workflow nocturno que corre `collect.py` y hace commit; GitHub Pages activado | 3 noches seguidas con datos nuevos sin tocar nada | 2 por día |
| 4 · Instalar | Manifest + íconos + service worker; "Agregar a pantalla de inicio" en Android | Abre como app y muestra el último día sin conexión | 0 |
| 5 · Historial | Pestaña con tendencias: vuelos por día, % cancelados y demorados, rutas y aerolíneas más frecuentes | Gráficos con al menos 7 días reales | 0 |

## Decisiones tomadas
- El celular no llama a la API: el plan gratis es solo HTTP (una página HTTPS no puede pedir datos por HTTP) y la clave quedaría expuesta.
- Una foto por día a las 23:30 (hora de Paraguay), para ver el estado final de cada vuelo. No es un tablero en vivo.
- Presupuesto: ~60 consultas al mes de uso normal + ~35 de margen.
- Repo público: GitHub Pages gratis requiere repo público en una cuenta personal. Los datos de vuelos son información pública; la clave queda protegida en los secretos de GitHub.

## Riesgos a vigilar
- La sonda puede mostrar que una consulta trae solo una ventana de horas y no el día completo. Se decide con esos datos.
- GitHub puede retrasar las tareas programadas y las desactiva en repos públicos tras 60 días sin actividad. El commit diario de datos cuenta como actividad; si un día falla, el workflow manual permite reanudar.
