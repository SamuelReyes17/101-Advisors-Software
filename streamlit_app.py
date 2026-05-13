"""
101 Advisors — Distressed Property Lead Generation Dashboard
=============================================================
Simplified version focused on the 5 features Leon requested:
    1. Filter by ZIP code
    2. Filter by Lis Pendens (and other distressed categories)
    3. Owner name + phone + email
    4. Bank info
    5. Attorney info (placeholder — requires Clerk integration)
"""

import streamlit as st
import pandas as pd
import re
import urllib.parse
from datetime import datetime
from pathlib import Path

# =========================================================================
# Page config
# =========================================================================
st.set_page_config(
    page_title="101 Advisors · Lead Generator",
    page_icon="🏠",
    layout="wide",
    initial_sidebar_state="expanded",
)

st.markdown(
    """
    <style>
    #MainMenu {visibility: hidden;}
    footer {visibility: hidden;}
    .block-container {padding-top: 2rem; padding-bottom: 2rem; max-width: 1400px;}
    div[data-testid="stMetricValue"] {font-size: 2rem; font-weight: 600;}
    div[data-testid="stMetricLabel"] {font-size: 0.85rem; color: #5F5E5A;}
    .stButton button {border-radius: 8px;}
    .badge {display: inline-block; padding: 3px 10px; border-radius: 8px;
            font-size: 0.78rem; font-weight: 500;}
    .badge-foreclosure {background: #FCEBEB; color: #791F1F;}
    .badge-auction {background: #FFE8D6; color: #8B3A00;}
    .badge-shortsale {background: #E2F0D9; color: #27500A;}
    .badge-lispendens {background: #FBEAF0; color: #72243E;}
    .badge-probate {background: #FAEEDA; color: #633806;}
    </style>
    """,
    unsafe_allow_html=True,
)

# =========================================================================
# Authentication
# =========================================================================
def check_password() -> bool:
    def _password_entered():
        try:
            expected = st.secrets["dashboard_password"]
        except (KeyError, FileNotFoundError):
            expected = "demo101"
        if st.session_state.get("password") == expected:
            st.session_state["authenticated"] = True
            del st.session_state["password"]
            st.session_state.pop("auth_error", None)
        else:
            st.session_state["authenticated"] = False
            st.session_state["auth_error"] = True

    if st.session_state.get("authenticated"):
        return True

    _, mid, _ = st.columns([1, 1.2, 1])
    with mid:
        st.markdown("# 🏠 101 Advisors")
        st.markdown("### Distressed Property Leads")
        st.markdown("Ingrese la contraseña del equipo para continuar:")
        st.text_input("Password", type="password", on_change=_password_entered,
                      key="password", label_visibility="collapsed")
        if st.session_state.get("auth_error"):
            st.error("Contraseña incorrecta.")
    return False


if not check_password():
    st.stop()

# =========================================================================
# Data loading
# =========================================================================
@st.cache_data(ttl=300)
def load_data() -> tuple[pd.DataFrame, str]:
    base = Path(__file__).parent / "data"
    real = base / "leads.csv"
    sample = base / "sample_leads.csv"

    def _read(p):
        return pd.read_csv(
            p,
            parse_dates=["first_seen", "last_updated"],
            dtype={
                "lead_id": str, "county": str, "category": str,
                "property_address": str, "city": str, "zip": str,
                "property_type": str, "owner_first": str, "owner_last": str,
                "owner_phone": str, "owner_email": str, "lender_name": str,
                "lender_phone": str, "lender_email": str, "bank_address": str,
                "status": str, "assigned_to": str, "notes": str,
            },
        )

    df = None
    source_label = "demo"
    if real.exists():
        try:
            candidate = _read(real)
            if len(candidate) > 0:
                df = candidate
                source_label = "production"
        except Exception:
            df = None
    if df is None:
        df = _read(sample)

    string_cols = [
        "property_address", "city", "zip", "owner_first", "owner_last",
        "owner_phone", "owner_email", "lender_name", "lender_phone",
        "lender_email", "bank_address", "status", "notes",
        "property_type", "category", "county",
    ]
    for c in string_cols:
        if c in df.columns:
            df[c] = df[c].fillna("").astype(str)
        else:
            df[c] = ""

    df["full_address"] = (df["property_address"] + ", " + df["city"] + " " + df["zip"]).str.strip(" ,")
    df["owner_name"] = (df["owner_first"] + " " + df["owner_last"]).str.strip()

    for c in ["outstanding_debt", "equity", "units", "bedrooms"]:
        if c in df.columns:
            df[c] = pd.to_numeric(df[c], errors="coerce").fillna(0)
        else:
            df[c] = 0

    return df, source_label


def fmt_currency(value) -> str:
    if pd.isna(value) or value == 0:
        return "—"
    return f"${value:,.0f}"


def category_badge(cat: str) -> str:
    cls_map = {
        "Foreclosure": "badge-foreclosure",
        "Auction": "badge-auction",
        "Short Sale": "badge-shortsale",
        "Lis Pendens": "badge-lispendens",
        "Probate": "badge-probate",
    }
    cls = cls_map.get(cat, "badge-foreclosure")
    return f'<span class="badge {cls}">{cat}</span>'


df, data_source = load_data()

# =========================================================================
# Header
# =========================================================================
hcol1, hcol2 = st.columns([4, 1])
with hcol1:
    st.title("101 Advisors · Distressed Property Leads")
    st.caption(
        f"Última actualización: {datetime.now().strftime('%Y-%m-%d %H:%M')} ET · "
        f"{'🟢 Datos reales' if data_source == 'production' else '🟡 Preview (sample data)'}"
    )

with hcol2:
    st.write("")
    if st.button("🔄 Refresh", use_container_width=True):
        st.cache_data.clear()
        st.rerun()
    if st.button("Logout", use_container_width=True):
        st.session_state.clear()
        st.rerun()

st.divider()

# =========================================================================
# Sidebar — solo los filtros que pidió Leon
# =========================================================================
with st.sidebar:
    st.markdown("### 📤 Subir leads de MLS")
    uploaded = st.file_uploader(
        "Arrastrá el CSV de Matrix",
        type=["csv"],
        help="Exportá los resultados de tu Saved Search en Matrix y subilo acá.",
        key="mls_upload",
    )

    if uploaded is not None:
        try:
            from pipeline.collectors.matrix_csv import parse_matrix_csv
            content = uploaded.read().decode("utf-8", errors="ignore")
            new_leads = parse_matrix_csv(content)
            if not new_leads:
                st.warning("No se encontraron leads en el CSV.")
            else:
                rows = [l.to_dict() for l in new_leads]
                new_df = pd.DataFrame(rows)
                for col in ("first_seen", "last_updated"):
                    new_df[col] = pd.to_datetime(new_df[col])
                target_path = Path(__file__).parent / "data" / "leads.csv"
                target_path.parent.mkdir(parents=True, exist_ok=True)
                new_df.to_csv(target_path, index=False)
                st.success(f"✅ {len(new_leads)} leads cargados. Click 'Refresh'.")
                st.cache_data.clear()
        except Exception as e:
            st.error(f"Error procesando el CSV: {e}")

    st.markdown("---")
    st.markdown("### 🔍 Filtros")

    # ── 1. Category (incluye Lis Pendens) ──────────────────────────────
    available_cats = sorted(df["category"].dropna().unique())
    available_cats = [c for c in available_cats if c.strip()]
    categories = st.multiselect(
        "Categoría",
        options=available_cats,
        default=available_cats,
        help="Lis Pendens incluido. Filtrá por tipo de propiedad distressed.",
    )

    # ── 2. ZIP code (lo más importante para Leon) ───────────────────────
    st.markdown("**📍 ZIP code**")
    available_zips = sorted(
        z for z in df["zip"].dropna().astype(str).unique()
        if z and z != "nan" and z.strip()
    )
    zip_input = st.text_input(
        "Buscar por ZIP (separar con coma)",
        placeholder="ej: 33133, 33156, 33184",
        help="Filtrá por uno o varios ZIPs.",
    )
    selected_zips: list[str] = []
    if zip_input.strip():
        selected_zips = [z.strip() for z in zip_input.split(",") if z.strip()]

    if available_zips:
        with st.expander(f"Ver los {len(available_zips)} ZIPs disponibles"):
            st.caption(", ".join(available_zips))

    # ── 3. County (opcional, por si quiere focus en un county) ──────────
    available_counties = sorted(
        c for c in df["county"].dropna().unique() if c.strip()
    )
    if available_counties:
        counties = st.multiselect(
            "County",
            options=available_counties,
            default=available_counties,
        )
    else:
        counties = []

    st.markdown("---")
    st.caption(f"Total leads en sistema: **{len(df)}**")


# =========================================================================
# Apply filters
# =========================================================================
mask = df["category"].isin(categories) if categories else pd.Series([True] * len(df), index=df.index)

if selected_zips:
    mask = mask & df["zip"].astype(str).isin(selected_zips)

if counties:
    county_mask = df["county"].isin(counties) | df["county"].isna() | (df["county"] == "")
    mask = mask & county_mask

filtered = df[mask].copy()

# =========================================================================
# Top: simple count
# =========================================================================
mc1, mc2, mc3 = st.columns(3)
mc1.metric("Leads que matchean", len(filtered))
mc2.metric("Con phone del owner", int((filtered["owner_phone"] != "").sum()))
mc3.metric("ZIPs únicos", filtered["zip"].nunique())

st.divider()

# =========================================================================
# Main table
# =========================================================================
if len(filtered) == 0:
    st.info("No hay leads que coincidan con los filtros actuales.")
    st.stop()

display = filtered.copy()
display = display.sort_values(["category", "zip"], ascending=[True, True])
display["Address"] = display["full_address"]
display["ZIP"] = display["zip"]
display["City"] = display["city"]
display["Owner"] = display["owner_name"]
display["Phone"] = display["owner_phone"]
display["Email"] = display["owner_email"]
display["Category"] = display["category"]
display["Type"] = display["property_type"]

st.markdown(f"**{len(display)} leads** · click una fila para ver detalles")

selection = st.dataframe(
    display[["lead_id", "Address", "ZIP", "City", "Category", "Owner", "Phone", "Type"]],
    column_config={
        "lead_id": st.column_config.TextColumn("ID", width="small"),
        "Address": st.column_config.TextColumn("Address", width="large"),
        "ZIP": st.column_config.TextColumn("ZIP", width="small"),
        "City": st.column_config.TextColumn("City", width="small"),
        "Category": st.column_config.TextColumn("Categoría", width="small"),
        "Owner": st.column_config.TextColumn("Owner", width="medium"),
        "Phone": st.column_config.TextColumn("Phone", width="small"),
        "Type": st.column_config.TextColumn("Type", width="small"),
    },
    hide_index=True,
    use_container_width=True,
    on_select="rerun",
    selection_mode="single-row",
    key="main_table",
)

st.download_button(
    label="📥 Export CSV filtrado",
    data=display.to_csv(index=False).encode("utf-8"),
    file_name=f"101advisors_leads_{datetime.now().strftime('%Y%m%d')}.csv",
    mime="text/csv",
)

# =========================================================================
# Detail panel (cuando se selecciona una fila)
# =========================================================================
if selection.selection.rows:
    idx = selection.selection.rows[0]
    lead = display.iloc[idx]

    st.divider()
    st.markdown(f"## 📋 Detalle · `{lead['lead_id']}`")

    # ── PROPIEDAD ──────────────────────────────────────────────────────
    st.markdown("### 🏠 Propiedad")
    p1, p2 = st.columns([2, 1])
    with p1:
        st.markdown(category_badge(lead["category"]), unsafe_allow_html=True)
        st.write("")
        st.write(f"**📍 {lead['Address']}**")
        st.write(f"{lead['Type']} · {int(lead['bedrooms'])} bedrooms · {int(lead['units'])} unit(s)")

        full_addr_q = urllib.parse.quote_plus(str(lead.get("Address", "")))
        st.markdown(
            f"""
            <div style="margin-top:12px; display:flex; gap:8px; flex-wrap:wrap;">
                <a href="https://www.zillow.com/homes/{full_addr_q}_rb/" target="_blank"
                   style="background:#006AFF;color:white;padding:6px 14px;
                          border-radius:6px;text-decoration:none;font-size:0.88rem;">
                    🏡 Ver en Zillow
                </a>
                <a href="https://www.google.com/maps/search/?api=1&query={full_addr_q}" target="_blank"
                   style="background:#34A853;color:white;padding:6px 14px;
                          border-radius:6px;text-decoration:none;font-size:0.88rem;">
                    🗺️ Ver en Maps
                </a>
            </div>
            """,
            unsafe_allow_html=True,
        )

    with p2:
        st.metric("List price", fmt_currency(lead.get("outstanding_debt", 0)))

    st.divider()

    # ── OWNER ──────────────────────────────────────────────────────────
    st.markdown("### 👤 Owner")
    o1, o2 = st.columns([1, 1])
    with o1:
        owner_name = str(lead.get("Owner", "")).strip()
        st.write(f"**Nombre**: {owner_name or '—'}")
        st.write(f"**Phone**: {lead['Phone'] or '—'}")
        st.write(f"**Email**: {lead['Email'] or '—'}")

    with o2:
        owner_city = str(lead.get("city", "")).strip()
        is_llc = bool(re.search(r"\b(LLC|INC|CORP|TRUST|TRS|LTD|LP|LLP|PA)\b",
                                 owner_name, re.IGNORECASE))
        if owner_name and owner_name not in ("", "—", "nan"):
            name_q = urllib.parse.quote_plus(owner_name)
            city_q = urllib.parse.quote_plus(owner_city) if owner_city else ""

            if is_llc:
                sunbiz_url = f"https://search.sunbiz.org/Inquiry/CorporationSearch/ByName?searchTerm={name_q}"
                st.markdown(
                    f"""
                    <div style="margin-top:8px;">
                        <strong>Buscar contacto:</strong><br>
                        <a href="{sunbiz_url}" target="_blank"
                           style="background:#005A8B;color:white;padding:6px 14px;
                                  border-radius:6px;text-decoration:none;font-size:0.88rem;
                                  display:inline-block;margin-top:6px;">
                            🏢 Sunbiz — ver officers + mailing
                        </a>
                    </div>
                    <div style="font-size:0.78rem;color:#777;margin-top:6px;">
                        LLC — Sunbiz te muestra quién está detrás (officer real + address)
                    </div>
                    """,
                    unsafe_allow_html=True,
                )
            else:
                tps_url = (f"https://www.truepeoplesearch.com/results?name={name_q}"
                           + (f"&citystatezip={city_q}+FL" if city_q else ""))
                fps_url = f"https://www.fastpeoplesearch.com/name/{owner_name.lower().replace(' ', '-')}"
                st.markdown(
                    f"""
                    <div style="margin-top:8px;">
                        <strong>Buscar phone:</strong><br>
                        <div style="display:flex;gap:6px;flex-wrap:wrap;margin-top:6px;">
                            <a href="{tps_url}" target="_blank"
                               style="background:#0072CE;color:white;padding:6px 14px;
                                      border-radius:6px;text-decoration:none;font-size:0.88rem;">
                                🔎 TruePeopleSearch
                            </a>
                            <a href="{fps_url}" target="_blank"
                               style="background:#E5404B;color:white;padding:6px 14px;
                                      border-radius:6px;text-decoration:none;font-size:0.88rem;">
                                🔎 FastPeopleSearch
                            </a>
                        </div>
                    </div>
                    <div style="font-size:0.78rem;color:#777;margin-top:6px;">
                        Persona física — click para buscar phone gratis
                    </div>
                    """,
                    unsafe_allow_html=True,
                )

    st.divider()

    # ── BANK / LENDER ──────────────────────────────────────────────────
    st.markdown("### 🏦 Banco / Lender")
    if lead.get("lender_name"):
        b1, b2 = st.columns([1, 1])
        with b1:
            st.write(f"**Banco**: {lead['lender_name']}")
            st.write(f"**Phone**: {lead.get('lender_phone') or '—'}")
            st.write(f"**Email**: {lead.get('lender_email') or '—'}")
        with b2:
            if lead.get('bank_address'):
                st.write(f"**Dirección**: {lead['bank_address']}")
    else:
        # Si el lead es un REO, el owner ES el banco
        owner = str(lead.get("Owner", "")).strip().upper()
        if any(k in owner for k in ("BANK", "MORTGAGE", "WELLS FARGO", "JPMORGAN",
                                     "CHASE", "US BANK", "FEDERAL NATIONAL", "FANNIE",
                                     "FREDDIE", "WILMINGTON TRUST")):
            st.info(f"🏦 Este lead es un REO. El owner actual es el banco: **{lead['Owner']}**")
            st.caption("Para detalles del REO Asset Manager, contactá al banco vía su línea de REO.")
        else:
            st.caption("⏳ Info del banco no disponible. Se obtiene del Miami-Dade Clerk en el caso de Lis Pendens.")

    st.divider()

    # ── ATTORNEY + LIS PENDENS ─────────────────────────────────────────
    st.markdown("### ⚖️ Attorney + Lis Pendens")
    if lead["category"] in ("Lis Pendens", "Foreclosure", "Auction"):
        st.caption(
            "⏳ Info de attorney + case number pendiente — viene del Miami-Dade Clerk of Court."
        )
        # Quick link to manually search the Clerk
        if owner_name:
            clerk_search = (
                "https://www2.miamidadeclerk.gov/ocs/Search.aspx?"
                f"q={urllib.parse.quote_plus(owner_name)}"
            )
            st.markdown(
                f"""
                <a href="{clerk_search}" target="_blank"
                   style="background:#5F5E5A;color:white;padding:6px 14px;
                          border-radius:6px;text-decoration:none;font-size:0.88rem;
                          display:inline-block;">
                    ⚖️ Buscar caso en Miami-Dade Clerk
                </a>
                """,
                unsafe_allow_html=True,
            )
    else:
        st.caption("No aplica para esta categoría.")

    if lead.get("notes") and not pd.isna(lead["notes"]):
        st.divider()
        st.caption(f"**Notas internas**: {lead['notes']}")
