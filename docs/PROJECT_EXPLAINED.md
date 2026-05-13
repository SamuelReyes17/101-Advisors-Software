# 101 Advisors Lead Gen — Explicación Detallada del Proyecto

Esta es una guía completa de TODO lo que construimos, desde la decisión más alta de arquitectura hasta cada función específica. Léelo de arriba abajo o saltá a la sección que necesites.

---

## Tabla de contenidos

1. [El problema que resolvemos](#1-el-problema-que-resolvemos)
2. [La solución en una página](#2-la-solución-en-una-página)
3. [Arquitectura — dónde vive cada cosa](#3-arquitectura--dónde-vive-cada-cosa)
4. [Tecnologías elegidas y por qué](#4-tecnologías-elegidas-y-por-qué)
5. [Estructura del repo — archivo por archivo](#5-estructura-del-repo--archivo-por-archivo)
6. [El pipeline — cómo fluyen los datos paso a paso](#6-el-pipeline--cómo-fluyen-los-datos-paso-a-paso)
7. [APIs externas — cómo las descubrimos y cómo funcionan](#7-apis-externas--cómo-las-descubrimos-y-cómo-funcionan)
8. [Tests smoke — qué prueban y por qué](#8-tests-smoke--qué-prueban-y-por-qué)
9. [Despliegue — cómo el código llega a producción](#9-despliegue--cómo-el-código-llega-a-producción)
10. [Decisiones técnicas clave](#10-decisiones-técnicas-clave)
11. [Estado actual y próximos pasos](#11-estado-actual-y-próximos-pasos)

---

## 1. El problema que resolvemos

**101 Advisors** es una agencia de real estate en South Florida que se especializa en comprar propiedades distressed (en problemas financieros) para revender o alquilar. Su trabajo competitivo es:

1. Encontrar propiedades en estado de Foreclosure, Probate, Lis Pendens, Tax Delinquent o Liens.
2. Filtrar las que califican según sus criterios (single/multi/duplex/triplex/fourplex; excluir condos y townhomes).
3. Conseguir el contacto del dueño (phone + email).
4. Llamar antes que la competencia.

Hoy ese trabajo lo hacen MANUALMENTE: alguien del equipo abre 5 sitios diferentes (Miami-Dade Clerk of Court, Broward Clerk, Palm Beach Clerk, Zillow Foreclosures, Florida Public Records), busca, filtra, copia direcciones, busca el dueño, llama. **Esto les toma ~40 minutos por día**, y para cuando llaman, la competencia ya pasó.

**Lo que perdíamos:** velocidad. En distressed real estate el primero en contactar al dueño gana.

---

## 2. La solución en una página

Construimos un **sistema automatizado** que cada mañana:

1. Consulta las fuentes públicas (y eventualmente la plataforma comercial que paga el cliente).
2. Filtra automáticamente solo las propiedades que califican.
3. Enriquece cada propiedad con datos del Property Appraiser (tipo, owner, units, year built, valor).
4. Identifica leads NUEVOS (los que aparecen por primera vez vs. los ya vistos).
5. Contacta a BatchSkipTracing para conseguir phone/email del dueño.
6. Publica todo en un dashboard web accesible desde cualquier dispositivo.

El equipo entra al dashboard a las 7 AM, ve los leads del día ya filtrados y enriquecidos, y empieza a llamar. **0 minutos de búsqueda.**

**Costo operativo:** $0 hoy (mientras los discovery collectors están en stub) → $30-50/mes cuando se active todo.

---

## 3. Arquitectura — dónde vive cada cosa

```
┌─────────────────────────────────────────────────────────────────┐
│                    FUENTES (en internet, públicas)              │
│  Miami-Dade Clerk · Broward Clerk · Palm Beach · Tax Coll.      │
│  Property Appraiser · BatchSkipTracing · Plataforma Cliente     │
└───────────────────────────┬─────────────────────────────────────┘
                            │ pull diario 6 AM ET
                            ↓
┌─────────────────────────────────────────────────────────────────┐
│                  SERVIDOR (GitHub Actions, gratis)               │
│   Python pipeline · prende → corre → escribe CSV → apaga         │
└───────────────────────────┬─────────────────────────────────────┘
                            │ commit data/leads.csv al repo
                            ↓
┌─────────────────────────────────────────────────────────────────┐
│              DATA STORE (Google Sheets + repo CSV)               │
│   Tabs: Today · Pipeline · History · State (SQLite)              │
└───────────────────────────┬─────────────────────────────────────┘
                            │ Streamlit auto-detecta cambios
                            ↓
┌─────────────────────────────────────────────────────────────────┐
│         DASHBOARD (Streamlit Cloud, URL pública, gratis)         │
│   Login con password · filtros · tablas · export CSV             │
└───────────────────────────┬─────────────────────────────────────┘
                            │ HTTPS desde browser
                            ↓
┌─────────────────────────────────────────────────────────────────┐
│           USUARIOS (equipo de 101 Advisors, donde sea)          │
│   Laptop · celular · tablet · cualquier browser                  │
└─────────────────────────────────────────────────────────────────┘
```

**Punto importante:** NADA vive en tu computadora local. Todo está en internet:

- Código y CSVs → GitHub
- Cron y ejecución del pipeline → GitHub Actions
- Dashboard y UI → Streamlit Cloud
- Datos → Google Sheets (futuro) y CSV en el repo

Si tu compu se rompe, el sistema sigue corriendo. Si el equipo del cliente está fuera de la oficina, igual lo accede.

---

## 4. Tecnologías elegidas y por qué

### Python 3.12 (lenguaje del pipeline)

**Por qué:** ecosistema maduro para web scraping, data manipulation (pandas), y APIs HTTP (requests). Library más rica del mundo para trabajar con datos.

**Alternativas descartadas:**
- Node.js: más rápido para I/O pero menos rico en data tools.
- Go: más performante pero overkill para este volumen de datos.
- Bash + curl: imposible para la lógica de filtrado y dedup.

### Streamlit (dashboard)

**Por qué:** permite construir un dashboard interactivo en Python puro, ~300 líneas, sin separar backend de frontend. Streamlit Community Cloud lo hostea gratis.

**Alternativas descartadas:**
- Next.js / React: 2-3 semanas extra de trabajo, dos lenguajes (TS + Python para backend), hosting más complejo.
- Tableau / Power BI: requieren licencia paga, no son código.
- Google Sheets como UI: menos profesional, peor experiencia móvil.

### Streamlit Community Cloud (hosting)

**Por qué:** gratis, conectado directo a GitHub (push → deploy automático), maneja HTTPS y dominios, soporta secrets para passwords.

**Alternativas descartadas:**
- Vercel / Netlify: optimizadas para Next.js, no para Streamlit.
- Render / Railway: gratis pero con límites más restrictivos.
- VPS propio (DigitalOcean): $5/mes pero requiere mantenimiento.

### GitHub Actions (cron scheduler)

**Por qué:** gratis para repos públicos y privados (con tier free generoso), cron nativo, integrado al repo, logs persistentes, alertas por email automáticas.

**Alternativas descartadas:**
- Cron en VPS: $5/mes + mantener el server.
- AWS Lambda + EventBridge: más complejo, requiere AWS account.
- Scheduled tasks en Streamlit Cloud: no existe.

### Google Sheets + SQLite + CSV (storage)

**Por qué:** capa híbrida.
- **CSV en repo** (`data/leads.csv`): el dashboard lee de acá. Versionado en Git.
- **SQLite** (`data/state.sqlite`): tracking de qué leads ya vimos antes (para identificar los NEW de hoy).
- **Google Sheets** (futuro): si el cliente quiere editar/marcar leads desde Sheets directamente, se sincroniza.

**Alternativa descartada:** PostgreSQL en Render → $7/mes y overkill para 100-500 leads/mes.

### BatchSkipTracing (skip-tracing)

**Por qué:** API REST documentada, paga solo cuando hay match (~$0.10-0.25 por lookup), 60-75% de phones reachable. Bajo budget.

**Alternativas descartadas:**
- ATTOM Data ($299/mes): demasiado caro.
- LexisNexis: enterprise pricing.
- Skip Genie: similar pero menos API-friendly.

---

## 5. Estructura del repo — archivo por archivo

```
101 Advisor Real State Project/
├── streamlit_app.py              ← Dashboard principal (lee CSV, muestra UI)
├── requirements.txt              ← Dependencias Python
├── README.md                     ← Quickstart + deploy
├── PIPELINE.md                   ← Cómo correr el pipeline
├── .gitignore                    ← Qué NO subir a Git
│
├── .streamlit/
│   ├── config.toml               ← Tema visual (colores corporativos)
│   ├── secrets.toml.example      ← Template de password
│   └── secrets.toml              ← Password real (gitignored)
│
├── .github/
│   └── workflows/
│       └── daily_pipeline.yml    ← Cron diario en GitHub Actions
│
├── pipeline/                     ← BACKEND DEL SISTEMA
│   ├── __init__.py
│   ├── config.yaml               ← Reglas de filtrado (editable sin código)
│   ├── run.py                    ← Orquestador: corre todos los collectors
│   ├── collectors/
│   │   ├── __init__.py
│   │   ├── base.py               ← Lead dataclass + Collector ABC
│   │   ├── property_appraiser.py ← Enriquece con DOR code, owner, units
│   │   ├── miami_dade_clerk.py   ← Foreclosure / Lis Pendens / Probate (stubs)
│   │   ├── miami_dade_tax.py     ← Tax Delinquent (stub)
│   │   ├── batch_skip.py         ← Skip-tracing API
│   │   └── platform_adapter.py   ← Interface genérica para plataforma cliente
│   └── utils/
│       ├── __init__.py
│       ├── state.py              ← SQLite tracker de leads vistos
│       └── csv_writer.py         ← Exporta data/leads.csv
│
├── scripts/                      ← HERRAMIENTAS DE INVESTIGACIÓN
│   ├── __init__.py
│   ├── probe_miami_dade.py       ← Diagnostica los portales del Clerk
│   ├── inspect_html.py           ← Analiza HTML capturado
│   ├── probe_property_appraiser.py
│   ├── probe_arcgis_services.py  ← Encuentra el endpoint correcto del PA
│   ├── probe_landinfo_layer24.py ← Confirma DOR code endpoint
│   ├── discover_pa_endpoint.py   ← Auto-discovery de APIs
│   └── captures/                 ← HTML guardado por los probes
│
├── data/
│   ├── sample_leads.csv          ← 30 leads de prueba (fallback del dashboard)
│   ├── leads.csv                 ← Leads reales (escrito por el pipeline)
│   ├── history.csv               ← Archivo histórico de leads
│   └── state.sqlite              ← DB de leads ya vistos
│
└── docs/
    ├── CREDENTIALS_NEEDED.md     ← Checklist para pedir al cliente
    └── PROJECT_EXPLAINED.md      ← este archivo
```

### Archivo por archivo en detalle

#### `streamlit_app.py`

**Qué hace:** corre el dashboard web. Es lo que ve el equipo de 101 Advisors cuando entra a la URL.

**Estructura:**
- **Page config**: setea título, icono, layout wide.
- **Custom CSS**: estilos para badges, tablas, métricas.
- **`check_password()`**: pantalla de login. Lee la password de `st.secrets["dashboard_password"]` y compara con lo que el usuario tipea.
- **`load_data()`**: lee el CSV (preferencia: `data/leads.csv`; fallback: `data/sample_leads.csv`). Aplica `fillna()` y `astype(str)` para evitar errores de tipo. Devuelve `(df, source_label)`.
- **Header**: título + última actualización + botones Refresh/Logout.
- **Sidebar filters**: county, category, property type, status, equity slider.
- **KPIs**: 5 métricas (New today, Pending, Contacted this week, Calls scheduled, Avg equity).
- **Tabs**: Today / Pipeline / History / Stats.
- **`render_table()`**: dibuja la tabla filtrada, con detalle al click de una row.

**Por qué así:** Streamlit ejecuta TODO el script desde arriba en cada interacción del usuario. Por eso la lógica está en funciones puras, y `@st.cache_data` evita re-leer el CSV en cada click.

#### `pipeline/__init__.py`

**Qué hace:** marca la carpeta `pipeline/` como un paquete Python. Define `__version__`.

**Por qué:** sin este archivo, Python no reconoce `pipeline.run` como módulo.

#### `pipeline/config.yaml`

**Qué hace:** las reglas de filtrado, listas de counties, caps de costo, paths de output. Editable sin tocar código.

**Por qué:** separar configuración de lógica. Si el cliente cambia criterios (ej: agregar Broward), solo se edita este archivo y se hace push — el código no cambia.

**Campos clave:**
- `counties`: qué condados activar.
- `include_property_types` / `exclude_property_types`: filtros de tipo.
- `categories`: cuáles de las 5 (foreclosure/probate/etc) están activas.
- `limits`: caps de costo (Miami-Dade API, BatchSkipTracing).
- `output`: paths de CSV y SQLite.

#### `pipeline/run.py`

**Qué hace:** **el orquestador.** Es la función `run()` que GitHub Actions ejecuta cada día.

**Pasos:**
1. `load_config()` → lee `config.yaml`.
2. `select_collectors(config)` → instancia los collectors habilitados.
3. Por cada collector → llama `collector.fetch()` y agrega los Lead objects a una lista.
4. Por cada Lead → `enrich_lead()` cruza con Property Appraiser para llenar property_type/units/beds.
5. `passes_filter()` → tira los que no califican (condos, townhomes, etc).
6. Dedup contra SQLite — marca cuáles son NEW vs. ya vistos.
7. Skip-trace solo a los NEW (cap de 100/mes).
8. `write_csv()` → escribe `data/leads.csv` (lo que el dashboard lee).
9. `append_csv()` → agrega los NEW a `data/history.csv` (archivo histórico).

**Por qué así:** pipeline lineal y predecible. Cada etapa es una función pura que puede testearse aislada.

#### `pipeline/collectors/base.py`

**Qué hace:** define dos cosas críticas:

1. **`Lead` dataclass**: el "schema" de cada lead. 25+ campos: lead_id, property_address, owner_first/last, units, bedrooms, equity, status, etc. **Todo el sistema usa esta forma de Lead** — los collectors devuelven Lead, el filter recibe Lead, el csv_writer escribe Lead.

2. **`Collector` ABC (Abstract Base Class)**: la "forma" que todo collector debe tener. Cada subclase debe implementar `fetch() -> Iterable[Lead]`.

**Por qué así:** estandarización. Una vez definido `Lead`, agregar un collector nuevo es "implementá `fetch()` que devuelva Leads". El orquestador no sabe ni le importa de dónde vienen los datos.

#### `pipeline/collectors/property_appraiser.py`

**Qué hace:** enriquece propiedades con datos del Miami-Dade Property Appraiser.

**Endpoints que usa:**
- `MD_LandInformation/MapServer/24/query` (PaGis Property layer): owner, address, DOR code, bedrooms, units, year built, lot size.
- `AddressSearchMap_PropertiesWithZip/MapServer/0/query` (address → folio lookup).

**Funciones clave:**
- `enrich_by_folio(folio)`: query principal. Recibe un folio (parcel ID), devuelve dict con todos los datos.
- `enrich_by_address(address, city)`: cuando solo tenés la dirección, primero busca el folio, después llama enrich_by_folio.
- `_classify_from_dor(dor_desc, condo_flag, units)`: traduce "RESIDENTIAL - SINGLE FAMILY : 1 UNIT" → "Single Family".
- `is_target_property_type(info, include, exclude)`: filtro final.

**Por qué dos funciones de enrich:** los collectors discovery a veces dan folio (más confiable) y a veces solo dirección (más común). Tener ambos paths te da flexibilidad.

#### `pipeline/collectors/miami_dade_clerk.py`

**Qué hace:** discovery de leads — Foreclosure, Lis Pendens, Probate cases del Miami-Dade Clerk.

**Estado actual:** **STUBS.** La razón es que el portal OCS del Clerk migró a un Single Page App (React) que no se puede scrapear con HTTP simple. Hay que reverse-engineer el API backend O activar el Commercial Data Services API ($0.20/req) O usar la plataforma comercial del cliente.

**Cuándo se completan:** cuando el cliente confirme cuál plataforma comercial paga.

#### `pipeline/collectors/miami_dade_tax.py`

**Qué hace:** discovery de leads Tax Delinquent del Tax Collector de Miami-Dade.

**Estado actual:** **STUB.** Porque la lista oficial de delinquent properties se publica como PDF anual, requiere parsear con `pdfplumber`. Pendiente la fecha de publicación 2026 (típicamente mayo-junio).

#### `pipeline/collectors/batch_skip.py`

**Qué hace:** llamadas a la API de BatchSkipTracing para enriquecer leads con phone/email del dueño.

**Cómo funciona:**
1. Toma un Lead.
2. Hace POST a `https://api.batchdata.com/api/v1/property/skip-trace` con la dirección.
3. Recibe JSON con phones[] y emails[] sorted por confidence score.
4. Llena `lead.owner_phone` y `lead.owner_email`.
5. Si la API key no está configurada, hace warning y devuelve el Lead sin modificar.

**Por qué pay-per-result:** solo pagás por matches exitosos. Si BatchData no encuentra el dueño, no cobra.

#### `pipeline/collectors/platform_adapter.py`

**Qué hace:** interfaz genérica para integrar con cualquier plataforma comercial (PropStream, BatchLeads, etc.).

**Diseño clave:** ABC `PlatformAdapter` con dos métodos:
- `authenticate()` → login o set API key.
- `search_distressed(county, categories, property_types)` → devuelve Leads.

**Por qué genérico:** no sabemos todavía qué plataforma usa el cliente. Cuando confirmen, agregamos una subclase (ej: `PropStreamAdapter(PlatformAdapter)`) sin tocar el orquestador. El switching es una línea en `config.yaml`.

#### `pipeline/utils/state.py`

**Qué hace:** SQLite database simple con una tabla `leads_seen`.

**Métodos:**
- `seen(lead_id)` → True/False si ya vimos este lead.
- `remember(lead_id, payload, today)` → INSERT or UPDATE. Devuelve True si era NEW.
- `first_seen_for(lead_id)` → cuándo apareció por primera vez.

**Por qué SQLite:** simple, file-based, viaja con el repo. Cuando GitHub Actions corre, lee el state.sqlite del último commit, lo actualiza, y commitea de vuelta. Memoria entre runs gratis.

#### `pipeline/utils/csv_writer.py`

**Qué hace:** convierte una lista de `Lead` objects a CSV con el schema canónico que el dashboard espera.

**Funciones:**
- `write_csv(leads, path)`: sobrescribe (para `data/leads.csv` que se reemplaza diario).
- `append_csv(leads, path)`: agrega al final (para `data/history.csv` que crece).

**Por qué dos funciones:** el dashboard solo necesita "los leads de HOY", pero queremos historial completo para stats.

#### `.github/workflows/daily_pipeline.yml`

**Qué hace:** define el cron diario en GitHub Actions.

**Pasos:**
1. Trigger: `cron: "0 10 * * *"` (10 UTC = 6 AM ET) + `workflow_dispatch` (manual button).
2. Permissions: `contents: write` (para que el bot pueda commitear).
3. Job `run-pipeline`:
   - Checkout repo.
   - Setup Python 3.12.
   - `pip install -r requirements.txt`.
   - Run `python -m pipeline.run` (con env var `BATCH_SKIP_API_KEY` desde secrets).
   - Si hubo cambios → commit + push.

**Por qué `workflow_dispatch`:** te permite triggerearlo manualmente desde la UI de GitHub Actions sin esperar al cron. Útil para testing.

#### `scripts/probe_miami_dade.py` y similares

**Qué hacen:** herramientas de DESCUBRIMIENTO. No son parte del pipeline en producción — son para investigar APIs.

Cada probe:
1. Hace GET a uno o más URLs candidatos.
2. Guarda el HTML/JSON capturado en `scripts/captures/`.
3. Imprime un resumen (tablas, classes, IDs, fields).

**Por qué los necesitamos:** los portales públicos no documentan sus APIs. Hay que probar URLs candidatos y ver qué responde. Una vez identificado el endpoint correcto, lo metemos en el código de producción.

---

## 6. El pipeline — cómo fluyen los datos paso a paso

Imaginate un día típico (las 6 AM ET):

### Etapa 1 — INGEST (descubrir leads)

`pipeline.run.run()` arranca. Itera sobre los collectors:

```python
for collector in select_collectors(config):
    for lead in collector.fetch():
        raw_leads.append(lead)
```

Cada `collector.fetch()` hace una HTTP request a su fuente:

- `MiamiDadeForeclosureCollector` → request al Clerk (TODO: pendiente plataforma cliente).
- `MiamiDadeProbateCollector` → idem.
- `MiamiDadeTaxDelinquentCollector` → idem.

**Cuando esté activa la plataforma del cliente:** `PlatformCollector` reemplaza a estos. Hace UNA query a la plataforma comercial y devuelve TODOS los leads en un viaje.

### Etapa 2 — ENRICH (rellenar datos faltantes)

Cada Lead que llega tiene **address mínimo**. Falta property_type, units, owner, etc.

```python
for lead in raw_leads:
    info = enrich_by_address(lead.property_address, lead.city)
    if info:
        lead.property_type = info["property_type"]
        lead.units = info["units"]
        lead.bedrooms = info["bedrooms"]
        lead.owner_first = info["owner_first"]
        # ... etc
```

`enrich_by_address` internamente hace 2 HTTP requests al Property Appraiser:
1. AddressSearchMap → encuentra el FOLIO.
2. PaGis Property layer → trae todo lo demás.

Total: ~50ms por lead. Para 50 leads = ~2.5 segundos. Aceptable.

### Etapa 3 — FILTER (descartar lo que no califica)

```python
filtered = [l for l in enriched if passes_filter(l, config)]
```

`passes_filter` chequea:
- `lead.property_type` está en `include_property_types` (Single Family / Multi Family / etc).
- NO está en `exclude_property_types` (Condominium / Townhouse / etc).

Esto elimina típicamente **70-85% de los matches**. El cliente solo ve lo viable.

### Etapa 4 — DEDUP (identificar leads NEW)

```python
state = StateDB("data/state.sqlite")
for lead in filtered:
    is_new = state.remember(lead.lead_id, lead.to_dict(), today)
    if is_new:
        lead.first_seen = today
        new_leads.append(lead)
```

Esto cruza cada lead contra el SQLite. Si NUNCA lo vimos antes, lo marca como NEW. Si ya estaba, solo actualiza `last_seen`.

**Por qué importa:** el equipo debe ver UNA VEZ cada lead. No 30 días seguidos del mismo. Solo lo nuevo o el cambio.

### Etapa 5 — SKIP-TRACE (conseguir phone/email)

```python
to_trace = prioritize_for_skip_trace(new_leads, config)[:cap]
for lead in to_trace:
    skip_trace(lead)  # llama a BatchData API
```

Solo se hace skip-trace de los NEW del día. Y limita el cap mensual ($20/mes ≈ 100 lookups). Si hay más leads que el cap, prioriza por categoría: Foreclosure > Probate > Tax > Lis Pendens > Liens.

### Etapa 6 — DELIVER (publicar al dashboard)

```python
write_csv(filtered, "data/leads.csv")          # lo que el dashboard lee
append_csv(new_leads, "data/history.csv")      # historial
state.close()
```

Después de eso, el workflow de GitHub Actions:

```yaml
- name: Commit updated data
  run: |
    git add data/leads.csv data/history.csv data/state.sqlite
    git commit -m "chore(pipeline): daily update"
    git push
```

GitHub recibe el commit. Streamlit Cloud detecta el cambio en el repo y rebuild el dashboard. El equipo ve los nuevos leads sin hacer nada.

---

## 7. APIs externas — cómo las descubrimos y cómo funcionan

### El método: probes iterativos

Las APIs públicas de los portales del gobierno no están documentadas. Para descubrirlas hicimos:

1. **Probe 1** (`scripts/probe_miami_dade.py`): probar URLs candidatos del Clerk de Court y RealAuction. Resultado: RealAuction requiere login (paywall). OCS es SPA con React. Foreclosure Registry es solo lookup, no listado.

2. **Probe 2** (`scripts/inspect_html.py`): analizar el HTML capturado para identificar selectores CSS, formularios ASP.NET, campos. Confirmó que RealAuction está bloqueado por login.

3. **Probe 3** (`scripts/discover_pa_endpoint.py`): buscar el endpoint del Property Appraiser. Encontramos que el dominio correcto es `gisweb.miamidade.gov` (NO `gisweb.miamidadepa.gov` como asumí inicialmente). El SPA usa basemaps-api.arcgis.com pero la data real viene de `gisweb.miamidade.gov`.

4. **Probe 4** (`scripts/probe_arcgis_services.py`): probar los servicios ArcGIS individuales. Encontramos `MD_NSPApp` (owner + address), `MD_LandInformation` (units + premise), `AddressSearchMap_PropertiesWithZip` (address → folio).

5. **Probe 5** (`scripts/probe_landinfo_layer24.py`): el layer 24 de MD_LandInformation tiene 44 fields incluyendo DOR_CODE_CUR, BEDROOM_COUNT, UNIT_COUNT, YEAR_BUILT, etc. **JACKPOT.**

### ArcGIS REST API explicada

El Property Appraiser usa **ArcGIS Server**, una plataforma estándar de gobiernos para servir mapas + data tabular. Cada layer es como una "tabla" con columnas y rows geoespaciales.

**URL pattern:**
```
https://gisweb.miamidade.gov/arcgis/rest/services/{folder}/{service}/{type}/{layer}/{operation}
```

Ejemplo nuestro:
```
https://gisweb.miamidade.gov/arcgis/rest/services/MD_LandInformation/MapServer/24/query
```

Donde:
- `MD_LandInformation` = el folder/service.
- `MapServer/24` = el layer 24 de ese map service.
- `query` = la operación de consulta SQL-like.

**Parameters de query:**
- `where=FOLIO='0141160040250'` → filtro WHERE clause.
- `outFields=*` → todos los fields.
- `f=json` → respuesta en JSON (no HTML).

**Response:**
```json
{
  "features": [
    {
      "attributes": {
        "FOLIO": "0141160040250",
        "TRUE_SITE_ADDR": "2735 SW 36 AVE",
        "TRUE_OWNER1": "HERNANDO AMIL LE",
        "DOR_CODE_CUR": "0101",
        "DOR_DESC": "RESIDENTIAL - SINGLE FAMILY : 1 UNIT",
        "BEDROOM_COUNT": 3,
        "UNIT_COUNT": 1,
        "YEAR_BUILT": 1946,
        ...
      }
    }
  ]
}
```

### Cómo escribimos cada función

**Patrón general en `property_appraiser.py`:**

```python
def _http_get_json(url, params, timeout=15):
    """Wrapper around requests for SSL robustness."""
    headers = {"User-Agent": "...", "Accept": "application/json"}
    resp = requests.get(url, params=params, headers=headers, timeout=timeout)
    resp.raise_for_status()
    return resp.json()


def _query_first_feature(url, where, out_fields="*"):
    """Run an ArcGIS query and return the first feature's attributes."""
    try:
        data = _http_get_json(url, {"where": where, "outFields": out_fields, "f": "json"})
    except Exception as e:
        log.warning("ArcGIS query failed: %s", e)
        return None
    if "error" in data:
        return None
    feats = data.get("features", [])
    return feats[0]["attributes"] if feats else None


def enrich_by_folio(folio):
    """Look up a property by its folio."""
    folio = folio.replace("-", "").strip()
    where = f"FOLIO='{folio}'"
    attrs = _query_first_feature(PAGIS_QUERY_URL, where)
    if not attrs:
        return None
    
    # Map ArcGIS field names to our canonical schema
    return {
        "folio": folio,
        "property_address": attrs.get("TRUE_SITE_ADDR", "").strip(),
        "city": attrs.get("TRUE_SITE_CITY", "").strip(),
        # ... etc
    }
```

**Lo importante:**
- `requests.get` con timeout siempre.
- `headers["User-Agent"]` para que no nos bloqueen como bot.
- `resp.raise_for_status()` levanta excepción si HTTP >= 400.
- Try/except en los wrappers para que un endpoint roto no rompa el pipeline.
- Mapping explícito de field names externos a schema interno.

### SSL en Mac

Encontramos un problema: Python en Mac no instala los certificados SSL del sistema. Solución estándar:

```bash
/Applications/Python\ 3.12/Install\ Certificates.command
```

Si eso falla, usamos `requests` library (que respeta `certifi` automáticamente) en lugar de `urllib`. Por eso en el código tenés:

```python
def _http_get_json(url, params, timeout=15):
    try:
        import requests
    except ImportError:
        # Fallback to urllib for sandboxes
        ...
    resp = requests.get(url, params=params, headers=headers, timeout=timeout)
```

---

## 8. Tests smoke — qué prueban y por qué

"Smoke test" = un test rápido que verifica que el sistema NO está fundamentalmente roto. No prueba toda la lógica, solo "¿al menos arranca?".

Hicimos varios:

### Smoke 1 — imports

```python
from pipeline.collectors.base import Lead, Collector
from pipeline.collectors.property_appraiser import enrich_by_folio
# ... etc
print("All imports OK")
```

**Qué prueba:** que los archivos no tienen errores de syntax, que las dependencias están instaladas, que no hay import circulares.

**Por qué:** un typo en el módulo rompe todo el pipeline. Detectarlo antes de correr en producción.

### Smoke 2 — Lead dataclass + roundtrip

```python
lead = Lead(lead_id="T0001", first_seen=date.today(), ...)
print(f"Lead created: {lead.lead_id}")
print(f"Schema cols: {len(COLUMNS)} match {len(lead.to_dict())} fields")
```

**Qué prueba:** podemos crear un Lead, convertirlo a dict, el dict tiene todos los campos esperados.

### Smoke 3 — config + collectors selection

```python
config = load_config()
collectors = select_collectors(config)
print(f"{len(collectors)} collectors selected: {[c.name for c in collectors]}")
```

**Qué prueba:** el YAML parsea, los collectors se instancian sin errores, los nombres son los esperados.

### Smoke 4 — StateDB roundtrip

```python
state = StateDB("/tmp/test.sqlite")
state.remember("T0001", lead.to_dict(), date.today())
assert state.seen("T0001") == True
```

**Qué prueba:** SQLite escribe + lee correctamente. La lógica de "ya vimos este lead" funciona.

### Smoke 5 — address parser

```python
test_addresses = [
    "2735 SW 36 AVE",
    "123 NW 5th St",
    "4521 SW 92nd Ave",
    ...
]
for addr in test_addresses:
    parsed = pattern.match(addr.upper())
    assert parsed is not None
```

**Qué prueba:** el regex de parsing de direcciones maneja todos los formatos típicos de Miami (con/sin direction, ordinal suffixes como "92nd", abreviaciones AVE/ST/RD/etc).

### Smoke 6 — DOR classifier

```python
cases = [
    ("RESIDENTIAL - SINGLE FAMILY : 1 UNIT", "N", 1, "Single Family"),
    ("RESIDENTIAL - CONDOMINIUM : 1 UNIT", "Y", 1, "Condominium"),
    ("MULTIFAMILY - 2-9 UNITS", "N", 2, "Duplex"),
    ...
]
for desc, condo, units, expected in cases:
    got = _classify_from_dor(desc, condo, units)
    assert got == expected
```

**Qué prueba:** el clasificador maneja todos los casos típicos de DOR_DESC + CONDO_FLAG, incluyendo edge cases (multifamily con units=2 → Duplex, etc).

### Smoke 7 — pipeline end-to-end (con stubs)

```bash
python3 -m pipeline.run
```

**Qué prueba:** todo el orquestador corre sin crashear. Los collectors stub devuelven 0 leads pero el pipeline NO falla — escribe el CSV vacío, cierra el state, termina con "Pipeline done.".

**Esto es crítico** porque cuando los collectors reales se activen, lo único que cambia es la cantidad de leads que devuelven — el resto del pipeline ya está validado.

### Smoke 8 — Property Appraiser query real

```bash
python3 -m pipeline.collectors.property_appraiser
```

**Qué prueba:** la URL es correcta, la query retorna data, el field mapping funciona, el classifier devuelve "Single Family" para el folio de prueba.

**Output esperado:**
```
=== Folio 0141160040250 ===
  property_type: Single Family
  dor_code: 0101
  bedrooms: 3
  ...
```

---

## 9. Despliegue — cómo el código llega a producción

### Flujo end-to-end:

```
Tu laptop
  ↓ (vos editás código)
git commit
  ↓
git push
  ↓
GitHub repo
  ↓ (webhook)         ↓ (webhook)
Streamlit Cloud      GitHub Actions
  ↓                     ↓
Build & deploy        Trigger cron
  ↓                     ↓
Dashboard live        Pipeline corre
                       ↓
                      git commit data/leads.csv
                       ↓
                      git push (back to repo)
                       ↓
                      Streamlit Cloud detecta cambio
                       ↓
                      Dashboard se actualiza solo
```

### Los 3 servicios externos que usamos (todos gratis):

**1. GitHub:**
- Hostea el código fuente.
- Tracking de cambios (Git).
- Distribución a los otros 2 servicios.
- Free para repos privados.

**2. Streamlit Community Cloud:**
- Hostea el dashboard como app web.
- URL pública (`*.streamlit.app`).
- Auto-deploy desde GitHub.
- Login con password via secrets.
- Free tier: tier suficiente para 5-10 usuarios concurrentes.

**3. GitHub Actions:**
- Cron scheduler integrado al repo.
- Provisiona servidores Linux temporales (~minutos por run).
- Permite secrets para credenciales (BATCH_SKIP_API_KEY).
- Free tier: 2,000 min/mes para repos privados — suficiente para 1 corrida diaria de ~3 min × 30 días = 90 min/mes.

### Por qué este setup es robusto:

- Si tu laptop se rompe → el sistema sigue corriendo.
- Si te vas de vacaciones → el cron sigue corriendo.
- Si Streamlit Cloud cae → reemplazás con Render/Railway en 1 hora.
- Si GitHub cae → todo el internet también.

---

## 10. Decisiones técnicas clave

### Por qué CSV en repo en lugar de DB

**Pros del CSV:**
- Versionado en Git (puedes ver el histórico).
- Sin servidor, sin password.
- Diff lindo en GitHub UI.
- Streamlit auto-detecta cambios.

**Cons:**
- No escala a millones de rows.
- Sin queries complejas.

**Conclusión:** para 100-500 leads/mes, CSV es ideal. Si crece a 100k+ cambiamos a Postgres.

### Por qué password compartida en lugar de OAuth

**Pros:**
- Setup en 5 minutos.
- 1 password para todo el equipo (5-10 personas).
- Si la pierden, se rota en 30 segundos.

**Cons:**
- No tracking de quién hizo qué.
- Si una persona se va, hay que rotar para todos.

**Conclusión:** para una agencia chica, OAuth es overkill. Si crece a 30+ usuarios, migramos a Google Workspace SSO.

### Por qué scraping vs API oficial (ahora Platform Adapter)

**Inicialmente:** intentamos scrapear los Clerks de Court directos. Descubrimos que el OCS es SPA y RealAuction requiere login pago.

**Pivot:** activamos `PlatformAdapter` genérico. Cuando el cliente confirme cuál plataforma comercial paga (PropStream/BatchLeads/etc), usamos su API. Más limpio, más confiable, más rápido.

### Por qué Streamlit en lugar de Next.js

- Streamlit: 1 lenguaje (Python), 300 líneas, gratis.
- Next.js: 2 lenguajes (TS + Python backend), 2000+ líneas, costo de hosting.

Para una herramienta interna de 5-10 usuarios, Streamlit es la elección obvia.

### Por qué cron en GitHub Actions en lugar de servidor propio

- GitHub Actions: $0/mes, mantenimiento $0.
- VPS propio: $5-10/mes, mantenimiento del SO, certificados, etc.

Si necesitamos correr cada hora (no diario), reconsideramos.

---

## 11. Estado actual y próximos pasos

### ✅ Completado

- Plan técnico (Word + Excel) entregable al cliente.
- Dashboard live en Streamlit Cloud.
- Pipeline Python end-to-end funcional.
- Property Appraiser enrichment validado con folios reales.
- GitHub Actions cron diario corriendo (6 AM ET).
- Skip-tracing module listo (espera API key).
- Platform adapter interface lista para integrar plataforma comercial.
- Robustez contra empty CSVs y mixed dtypes en Python 3.14.

### ⏸️ Esperando

- **Credenciales del cliente** para su plataforma comercial. Una vez confirmadas:
  - Implementamos el adaptador específico (~1-3 días según la plataforma).
  - Activamos los discovery collectors.
  - Leads reales empiezan a fluir al dashboard.
- **API key de BatchSkipTracing** para enrichment de phone/email (cuando vos decidas).

### 🎯 Próximos pasos cuando responda el cliente

1. Confirmar plataforma exacta (PropStream / BatchLeads / etc).
2. Conseguir API key o login.
3. Implementar `PlatformAdapter` específico.
4. Activar `PlatformCollector` en `config.yaml`.
5. Test end-to-end con datos reales.
6. Push → cron diario empieza a producir leads reales.

### Sin la plataforma del cliente, podemos avanzar con

- Mejoras al dashboard (badges para absentee owner, year built, owners múltiples).
- Investigar Broward Property Appraiser equivalente.
- Configurar email digest diario (cuando haya leads).
- Limpieza de polish (favicon custom, tema corporativo, etc).

---

## Apéndice — Comandos útiles

```bash
# Correr el dashboard local
streamlit run streamlit_app.py

# Correr el pipeline manualmente
python3 -m pipeline.run

# Probar el Property Appraiser con un folio
python3 -m pipeline.collectors.property_appraiser

# Probar BatchSkipTracing (necesita BATCH_SKIP_API_KEY env var)
BATCH_SKIP_API_KEY=tu-key python3 -m pipeline.collectors.batch_skip

# Investigar APIs nuevas
python3 -m scripts.probe_miami_dade
python3 -m scripts.inspect_html
python3 -m scripts.probe_arcgis_services

# Subir cambios
git add .
git commit -m "..."
git push

# Ver el log del último cron run en GitHub Actions
# (ir a: github.com/SamuelReyes17/101-Advisors-Software/actions)
```

---

**Mantenimiento:** Samuel Reyes  
**Última actualización:** Mayo 2026  
**Versión del proyecto:** v0.2 (post-Property Appraiser integration)
