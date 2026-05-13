# BatchData (Skip-Tracing) — Setup Guide

Este servicio nos da **teléfono + email del owner** de cada propiedad. Es el último paso
para convertir un lead en una llamada real.

## Pricing

- **$0.20 por lookup exitoso** (más barato que TransUnion / WhitePages Pro)
- No cobra por lookups que no devuelven match
- Setup gratis, sin minimum mensual
- Crédito inicial de prueba (~$10 según promociones vigentes)

Con el cap default de 100 lookups/mes = **~$20 USD/mes**.

## Paso a paso

### 1. Crear cuenta

1. Andá a https://batchdata.io
2. Click **Sign up** (esquina superior derecha)
3. Llená: email, password, nombre, empresa
4. Te van a pedir tarjeta de crédito — necesario para activar el API key

### 2. Generar API key

1. Login → vas al dashboard
2. Menú lateral: **API Keys**
3. Click **Create API Key**
4. Nombre sugerido: `101advisors-prod`
5. Copiá el key — empieza con algo tipo `bD_live_xxxxxxxxxxxxxxxxxxxxxxxxxxxx`

### 3. Configurar el key en el proyecto

Tenés 2 opciones:

**Opción A — Variable de entorno** (mejor para local):
```bash
export BATCH_SKIP_API_KEY=bD_live_xxxxxxxxxxxxx
```
Para que persista entre sesiones, agregalo a `~/.zshrc` o `~/.bashrc`.

**Opción B — Streamlit secrets** (mejor para Streamlit Cloud):
Editá `.streamlit/secrets.toml` (creá el archivo si no existe):
```toml
BATCH_SKIP_API_KEY = "bD_live_xxxxxxxxxxxxx"
```
Y agregalo en Streamlit Cloud Settings → Secrets también para que funcione el dashboard live.

⚠️ **Importante**: `.streamlit/secrets.toml` ya está en `.gitignore` (verificá), así que el key NO se commitea al repo público.

### 4. Probar con 5 leads (costo: ~$1)

```bash
python3 -m scripts.skip_trace_leads --cap 5
```

Esperás ver:
```
[  1/5] ✅ Short Sale  2319 NE 35th Dr                          📞 (954) 555-1234 · ✉️ owner@email.com
[  2/5] ✅ Short Sale  812 NW 26th Street                       📞 (954) 555-5678
...
✅ Con phone/email: 4/5
💵 Costo real: ~$0.80
```

### 5. Skip-trace full batch (costo: ~$20)

```bash
python3 -m scripts.skip_trace_leads --cap 100
```

Hace lookup de los top 100 leads ordenados por: **Short Sale > Auction > Foreclosure**, y dentro de cada categoría por **equity descendente**.

Cuando termine, push al repo:
```bash
git add data/leads.csv
git commit -m "data: skip-traced 100 leads"
git push
```

Y el dashboard live va a mostrar phones + emails en cada lead detail panel.

## Recomendación de uso mensual

- **Mes 1**: Skip-trace 100 leads. Ver cuántas llamadas concretas salen.
- **Mes 2+**: Ajustar cap según conversion rate. Si los Short Sale convierten 5%, vale la pena scaler a 200/mes ($40). Si convierten 0.5%, dejar en 50/mes ($10).
- **Re-skip-trace cada 6 meses**: phones cambian. Volver a llamar BatchData para los leads que siguen activos.

## Si BatchData no funciona

Alternativas similares:
- **REISkip** ($0.15-0.20): otro proveedor del mismo nicho real estate
- **SkipForce** ($0.10): más barato pero menor match rate
- **PeopleDataLabs** ($0.30-0.50): más caro pero también devuelve LinkedIn data

Todas tienen API parecida, podemos swapear cambiando solo el URL + auth en `pipeline/collectors/batch_skip.py`.
