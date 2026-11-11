# Prompt fase 0 — Sonda de datos

Antes: crear cuenta gratis en aviationstack.com y poner la clave en un archivo `.env` como `AVIATIONSTACK_KEY=...`. Pegar este prompt en Claude Code en modo Plan.

---

**Intención**
Quiero saber si el plan gratis de AviationStack alcanza para un tablero diario de llegadas y salidas del aeropuerto ASU. Crea `probe.py` que haga exactamente una consulta a `/v1/flights` con `arr_iata=ASU&limit=100` y otra con `dep_iata=ASU&limit=100`, y guarde cada respuesta cruda en `data/raw/`.

**Forma de revisión**
El script imprime un reporte por dirección con: total de registros, cuántos tienen `flight.codeshared` distinto de null, vuelos únicos tras quitar codeshares, conteo por `flight_status`, fecha y hora (en America/Asuncion) del primer y último vuelo programado, y el valor de `pagination.total`. Además crea `.gitignore` con `.env` y `data/`.

**Límites**
Máximo 2 llamadas a la API en total: si algo falla, no reintentes; muéstrame el error y para. No imprimas la URL completa ni la clave. No instales nada global; usa un entorno virtual.

**Criterio de listo**
Dos archivos JSON en `data/raw/` y el reporte impreso. Al final, dime en dos líneas si una consulta por dirección cubre el día completo o solo una ventana de horas.
