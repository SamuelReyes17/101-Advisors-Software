# 101 Advisors Dashboard · v1 Handoff

## ✅ Lo que pidió Leon — qué está entregado

| # | Ask | Cómo se resolvió | Estado |
|---|-----|------------------|--------|
| 1 | **Filtrar por ZIP code** | Filtro en sidebar + autocomplete | ✅ DONE |
| 2 | **Filtrar por Lis Pendens** | Filtro de Categoría (incluye Foreclosure, Auction, Short Sale, Lis Pendens) | ✅ DONE |
| 3 | **Owner name** | Auto-poblado por Property Appraiser (Miami-Dade) | ✅ 60% leads · resto: lookup en 1 click |
| 4 | **Owner phone + email** | Botones manuales por lead: Sunbiz para LLCs, TruePeople para personas | ✅ Lookup en 30 seg |
| 5 | **Info del banco** | REOs identificados auto · resto: link directo al Clerk | ✅ Pattern matching + Clerk link |
| 6 | **Info del attorney** | Link directo al Clerk de cada county con owner pre-cargado | ✅ Lookup en 1 click |
| 7 | **Tax delinquency** (que mencionaste hoy) | Link directo al Tax Collector de cada county con address pre-cargado | ✅ Lookup en 1 click |

## 🎯 Workflow del agente para 1 lead

1. Abrir el dashboard (https://101-advisors-software-XXX.streamlit.app)
2. Filtrar por ZIP de interés (ej: "33133")
3. Ver la lista filtrada
4. Para cada lead que quiera trabajar:
   - **🏡 Zillow** → ver fotos + Zestimate (5 seg)
   - **🔎 Owner** → buscar phone (Sunbiz si LLC, TruePeople si persona) (30 seg)
   - **🧾 Tax** → ver si tiene tax delinquency (15 seg)
   - **⚖️ Clerk** → ver el caso de foreclosure, banco demandante, attorney (30 seg)
5. Decidir: ¿llamar / mandar carta / pasar?
6. Si llama → marca en el sistema (TODO v2)

**Total: ~2 minutos por lead** vs ~30-40 min que tardaba el equipo manualmente.

## ⚠️ Limitaciones conocidas en v1

| Limitación | Impacto | Cuándo se resuelve |
|-----------|---------|---------------------|
| Owner phone/email NO está auto-poblado | Requiere 30 seg manual por lead | v2 con BatchSkipTracing pago ($20/mes opcional) |
| Lis Pendens case data NO está auto-poblado en el dashboard | Click al Clerk para verlo | v2 con scraping del Clerk OCS |
| Tax delinquency amount NO está visible en el dashboard | Click al Tax Collector | v2 con scraping del Tax Collector |
| Bank phone/email para REOs NO está auto-poblado | Conoces el nombre del banco, llamas a su línea REO general | v2 con database de REO Asset Managers |
| Algunos leads tienen address malformado | El Census los manda a counties incorrectos (filtro "fuera del área" oculta esos) | v2 con limpieza de MLS data |

## 🚀 Roadmap v2 (siguiente sprint)

**Si Leon aprueba el v1 y quiere automatización adicional:**

1. **BatchSkipTracing integration** — auto-poblado de owner phone/email para top 100 leads/mes ($20/mes)
2. **Miami-Dade Clerk scraping** — auto-poblado de case number, plaintiff (banco), attorney, fecha filed
3. **Miami-Dade Tax Collector scraping** — auto-poblado de tax delinquency amount + delinquency date
4. **Mark contacted / Assign agent** — workflow tracking dentro del dashboard
5. **Daily emails** — resumen diario al equipo con nuevos leads
6. **Mobile-friendly** — optimizar para que los agents puedan trabajar desde el celular

**Tiempo estimado v2**: 2-3 semanas

## 💰 Costos operativos

### v1 (current)
| Item | Costo/mes |
|------|-----------|
| Streamlit Cloud (hosting) | $0 (free tier) |
| GitHub Actions (cron pipeline) | $0 (free tier) |
| Property Appraiser API (Miami-Dade) | $0 (público) |
| Census Geocoder | $0 (público) |
| MLS Matrix (vía cuenta de Leon) | Ya incluido en agency |
| **Total v1** | **$0/mes** |

### v2 (con automatizaciones)
| Item | Costo/mes |
|------|-----------|
| Todo lo anterior | $0 |
| BatchSkipTracing (100 lookups/mes) | $20 |
| Clerk Commercial Data Service (opcional) | $25 |
| **Total v2** | **$20-45/mes** |

## 📋 Cómo entregar al cliente

1. Mandale el URL del dashboard
2. La password está en `.streamlit/secrets.toml` (por defecto: `demo101` — cambiala antes de entregar)
3. Pasale este doc para que entienda qué está / qué viene
4. Demoramente: hacé una llamada de 15 min mostrándole el workflow real
5. Recopilá feedback en la primera semana → ajustamos prioridades de v2

## 🔑 Credenciales / acceso

- **GitHub repo**: https://github.com/SamuelReyes17/101-Advisors-Software
- **Streamlit Cloud**: dashboard live, auto-rebuildea con cada `git push`
- **Dashboard password**: configurada en Streamlit Cloud → Settings → Secrets
- **Daily refresh**: GitHub Actions corre a las 6 AM ET (ver `.github/workflows/daily_pipeline.yml`)
