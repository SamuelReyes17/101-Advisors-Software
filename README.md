# 101 Advisors — Distressed Property Lead Generator

Plataforma de generación de leads para propiedades distressed en South Florida (Miami-Dade, Broward, Palm Beach). Filtra automáticamente por los criterios de 101 Advisors y entrega solo leads viables al equipo a través de un dashboard web.

**Estado actual:** MVP v0.1 — solo dashboard con datos de prueba. Los collectors de datos reales se construyen en las próximas fases.

## ¿Qué hace?

1. **Ingest** (próxima fase): Pulls de Miami-Dade Clerk API, Broward Web2 portal, Palm Beach eCaseView, Tax Collectors y Property Appraisers — diariamente o cada 2 días vía GitHub Actions.
2. **Filter**: Aplica las reglas de 101 Advisors (single-family, multi-family, duplex, triplex, fourplex; excluye condos/apartments/townhomes).
3. **Skip-trace**: Enriquece con phone/email del owner vía BatchSkipTracing.
4. **Deliver**: Push a Google Sheets + dashboard Streamlit.

## Quickstart local

Instalá Python 3.10+ y luego:

```bash
# Clonar el repo
git clone <repo-url>
cd "101 Advisor Real State Project"

# Crear virtualenv (opcional pero recomendado)
python3 -m venv venv
source venv/bin/activate         # macOS/Linux
# venv\Scripts\activate          # Windows

# Instalar dependencias
pip install -r requirements.txt

# Configurar secrets para correr local
cp .streamlit/secrets.toml.example .streamlit/secrets.toml
# Editar .streamlit/secrets.toml y poner tu password

# Correr el dashboard
streamlit run streamlit_app.py
```

Abrí `http://localhost:8501` en el browser. Password por defecto: `demo101`.

## Deploy a Streamlit Community Cloud (gratis)

1. **Subí el repo a GitHub** (privado o público, da igual para Streamlit Cloud Free):
   ```bash
   git init
   git add .
   git commit -m "Initial commit: dashboard MVP"
   git remote add origin git@github.com:TU-USERNAME/101-advisors-leads.git
   git push -u origin main
   ```

2. **Conectá Streamlit Cloud al repo**:
   - Andá a [share.streamlit.io](https://share.streamlit.io) y loguéate con GitHub.
   - Click "New app" → seleccioná tu repo.
   - Branch: `main`. Main file path: `streamlit_app.py`.
   - Click "Advanced settings" → en "Secrets" pegá el contenido de `.streamlit/secrets.toml.example` con la password real:
     ```toml
     dashboard_password = "TU_PASSWORD_REAL"
     ```
   - Click "Deploy".

3. **Streamlit asigna una URL** tipo `https://101-advisors-leads.streamlit.app/` que podés compartir con el equipo de 101 Advisors.

## Estructura del proyecto

```
101 Advisor Real State Project/
├── streamlit_app.py            ← dashboard principal
├── requirements.txt            ← dependencias Python
├── README.md                   ← este archivo
├── .gitignore                  ← qué NO subir a Git
├── .streamlit/
│   ├── config.toml             ← tema visual del dashboard
│   ├── secrets.toml.example    ← template de secrets
│   └── secrets.toml            ← (gitignored) password real
├── data/
│   └── sample_leads.csv        ← 30 leads de prueba
└── .github/
    └── workflows/              ← (próxima fase) cron diario
```

## Roadmap

- ✅ **Fase 0**: Setup de repo + estructura
- ✅ **Fase 1A**: Dashboard MVP con datos de prueba (este commit)
- ⏳ **Fase 1B**: Migrar fuente de datos de CSV a Google Sheets
- ⏳ **Fase 2**: Collector Miami-Dade Clerk (Foreclosure + Lis Pendens)
- ⏳ **Fase 3**: Collectors Broward + Palm Beach
- ⏳ **Fase 4**: Tax Collectors + Property Appraisers + BatchSkipTracing
- ⏳ **Fase 5**: GitHub Actions cron diario + email digest
- ⏳ **Fase 6**: Polish + handoff (training del equipo)

## Datos de prueba

`data/sample_leads.csv` contiene 30 leads sintéticos cubriendo:
- 3 condados (Miami-Dade, Broward, Palm Beach)
- 5 categorías (Foreclosure, Probate, Lis Pendens, Tax Delinquent, Liens)
- 5 property types (Single Family, Multi Family, Duplex, Triplex, Fourplex)
- 5 estados (New, Pending, Contacted, Scheduled, Closed)

Una vez los collectors estén listos, este CSV se reemplaza automáticamente por la conexión a Google Sheets.

## Tech stack

| Componente | Tecnología | Costo |
|------------|------------|-------|
| Dashboard | Streamlit | Free |
| Hosting | Streamlit Community Cloud | Free |
| Pipeline | Python + GitHub Actions | Free |
| Storage | Google Sheets + SQLite | Free |
| Skip-tracing | BatchSkipTracing API | ~$20/mes (cap) |
| Source data | Miami-Dade API + scraping | ~$25/mes (cap) |
| **Total opex** | | **~$30-50/mes** |

## Contacto

Mantenimiento: Samuel Reyes
# 101-Advisors-Software
