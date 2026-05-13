#!/bin/bash
# =============================================================================
# update_leads.sh — Daily flow to push fresh MLS leads to the dashboard.
#
# Use this every morning after exporting the CSV from Matrix:
#   1. Download the CSV from Matrix (Actions → Export → CSV).
#   2. Save it as ~/Downloads/mls_leads.csv (or pass another path as $1).
#   3. Run:   bash scripts/update_leads.sh
#
# What it does:
#   - Copies the CSV to data/leads.csv (the dashboard reads this).
#   - Runs the parser locally to validate it.
#   - Commits to git and pushes.
#   - Streamlit Cloud auto-rebuilds; dashboard shows fresh leads in 2 min.
# =============================================================================
set -e

CSV_SOURCE="${1:-$HOME/Downloads/mls_leads.csv}"
PROJECT_DIR="$(cd "$(dirname "$0")/.." && pwd)"
TARGET="$PROJECT_DIR/data/leads.csv"

echo "🔍 Looking for CSV: $CSV_SOURCE"

if [ ! -f "$CSV_SOURCE" ]; then
    echo "❌ ERROR: no se encontró el CSV en $CSV_SOURCE"
    echo "   Descargalo de Matrix y guardalo ahí, o pasá el path como argumento:"
    echo "   bash scripts/update_leads.sh /path/al/archivo.csv"
    exit 1
fi

ROW_COUNT=$(($(wc -l < "$CSV_SOURCE") - 1))
echo "📋 CSV tiene $ROW_COUNT filas de datos"

echo "📁 Copiando a $TARGET"
cp "$CSV_SOURCE" "$TARGET"

echo "🧪 Validando que el parser lo lee bien..."
cd "$PROJECT_DIR"
python3 -c "
from pipeline.collectors.matrix_csv import parse_matrix_csv
with open('data/leads.csv') as f:
    leads = parse_matrix_csv(f.read())
print(f'✅ Parser OK · {len(leads)} leads detectados')
if leads:
    print(f'   Primero: {leads[0].property_address} · {leads[0].category}')
"

echo "💾 Commit + push al repo..."
git add data/leads.csv
git commit -m "data: leads del MLS $(date +%Y-%m-%d)" || {
    echo "⚠️  No hubo cambios (mismo CSV que la última vez)"
    exit 0
}
git push

echo ""
echo "🎉 ¡LISTO! Streamlit Cloud va a rebuildear el dashboard en 1-2 minutos."
echo "   URL: https://101-advisors-software-XXXX.streamlit.app"
echo "   El cliente verá los nuevos leads automáticamente."
