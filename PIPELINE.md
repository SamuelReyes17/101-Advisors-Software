# Pipeline — Guía de operación

## ¿Qué hace?

Cada día (cron en GitHub Actions), el pipeline:

1. Lee `pipeline/config.yaml` para saber qué condados/categorías/property types incluir.
2. Ejecuta los collectors habilitados (uno por fuente).
3. Enriquece cada lead con datos del Property Appraiser (property type, units, beds).
4. Filtra propiedades que NO encajan (excluye condos, townhomes, apts).
5. Deduplica contra el historial — solo marca como NEW las que aparecen por primera vez.
6. Skip-trace top-100 nuevos leads (cap configurable).
7. Escribe `data/leads.csv` (lo que el dashboard lee).
8. Hace commit automático al repo con la nueva data.
9. Streamlit Cloud detecta el commit y rebuild el dashboard.

## Estructura

```
pipeline/
├── __init__.py
├── config.yaml                       ← reglas editables (no requiere código)
├── run.py                            ← orquestador (este es el que corre el cron)
├── collectors/
│   ├── base.py                       ← Lead dataclass + Collector ABC
│   ├── property_appraiser.py         ← ENRIQUECE leads (no descubre)
│   ├── miami_dade_clerk.py           ← STUB: Foreclosure / Lis Pendens / Probate
│   ├── miami_dade_tax.py             ← STUB: Tax Delinquent
│   └── batch_skip.py                 ← Skip-tracing API
└── utils/
    ├── state.py                      ← SQLite tracking de leads vistos
    └── csv_writer.py                 ← exporta data/leads.csv
```

## Correr el pipeline en tu compu (testing)

```bash
cd "/Users/samuelreyes/Documents/Claude/Projects/101 Advisor Real State Project"
pip install -r requirements.txt
python -m pipeline.run
```

Output esperado: el log dice "Pipeline done." y crea `data/leads.csv` (vacío hasta que terminemos los collectors).

## Probar el Property Appraiser solo

```bash
python -m pipeline.collectors.property_appraiser
```

Si ves "OK — got property data:" con folio, units, beds — el endpoint funciona. Si dice FAILED, hay que investigar el endpoint actual del Property Appraiser.

## Configurar el cron en GitHub Actions

1. Andá a tu repo en GitHub: `Settings → Secrets and variables → Actions`.
2. Click `New repository secret` y agregá:
   - **Name**: `BATCH_SKIP_API_KEY`
   - **Value**: tu API key de BatchSkipTracing (cuando la tengas)
3. El workflow `.github/workflows/daily_pipeline.yml` ya está configurado para correr a las 6 AM ET diario. Pestaña `Actions` lo verás listado.
4. Click `Daily Pipeline → Run workflow` para correrlo manualmente la primera vez y ver que todo OK.

## Editar criterios sin tocar código

Editá `pipeline/config.yaml` y commit + push:

- Cambiar refresh a cada 2 días: cambiar `cron: "0 10 * * *"` por `cron: "0 10 */2 * *"` en el workflow.
- Activar más condados: descomentar líneas en `counties:`.
- Cambiar property types incluidos: editar `include_property_types`.
- Cambiar caps de skip-tracing: editar `limits:`.

## Estado de los collectors

| Collector | Status | Falta |
|-----------|--------|-------|
| Property Appraiser (enrichment) | ✅ Funcional | Validar endpoint con 3 folios reales |
| Miami-Dade Foreclosure | 🟡 Stub | Investigar HTML del portal OCS, escribir parser |
| Miami-Dade Lis Pendens | 🟡 Stub | Mismo portal, distinto case type |
| Miami-Dade Probate | 🟡 Stub | Mismo portal, case type "Probate" |
| Miami-Dade Tax Delinquent | 🟡 Stub | Encontrar PDF list, parser con pdfplumber |
| Broward Clerk | 🔴 No implementado | Scrape Web2 portal |
| Palm Beach Clerk | 🔴 No implementado | eCaseView scrape |
| BatchSkipTracing | ✅ Funcional | Validar con API key real |

## Próximo paso recomendado

Cuando tengas tu API key de BatchSkipTracing y validés el Property Appraiser:

1. Yo investigo el HTML del portal Miami-Dade OCS y completo el `MiamiDadeForeclosureCollector`.
2. Lo testeamos local — debería traer leads reales el primer día.
3. Activamos el cron de GitHub Actions.
4. Tu cliente ve leads reales en el dashboard al día siguiente.

Después se replica el patrón para los otros collectors.
