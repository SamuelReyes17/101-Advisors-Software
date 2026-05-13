"""
101 Advisors — Distressed Property Leads
Minimalist dashboard: solo lo que Leon necesita.
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
    page_title="101 Advisors · Leads",
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
    .stButton button {border-radius: 8px;}
    </style>
    """,
    unsafe_allow_html=True,
)

# =========================================================================
# Auth
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
        st.text_input("Password", type="password", on_change=_password_entered,
                      key="password", label_visibility="collapsed",
                      placeholder="Contraseña")
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


def is_llc(name: str) -> bool:
    return bool(re.search(r"\b(LLC|INC|CORP|TRUST|TRS|LTD|LP|LLP|PA|HOLDINGS|GROUP|ASSOC|ASSN)\b",
                          name or "", re.IGNORECASE))


def build_zillow_url(address: str) -> str:
    if not address:
        return ""
    return f"https://www.zillow.com/homes/{urllib.parse.quote_plus(address)}_rb/"


def build_owner_lookup_url(owner_name: str, city: str = "") -> str:
    if not owner_name:
        return ""
    name_q = urllib.parse.quote_plus(owner_name)
    if is_llc(owner_name):
        return f"https://search.sunbiz.org/Inquiry/CorporationSearch/ByName?searchTerm={name_q}"
    else:
        city_q = urllib.parse.quote_plus(city) if city else ""
        suffix = f"&citystatezip={city_q}+FL" if city_q else ""
        return f"https://www.truepeoplesearch.com/results?name={name_q}{suffix}"


df, data_source = load_data()

# =========================================================================
# Header
# =========================================================================
hcol1, hcol2 = st.columns([4, 1])
with hcol1:
    st.title("101 Advisors")
    st.caption(
        f"{datetime.now().strftime('%Y-%m-%d %H:%M')} · "
        f"{'🟢 Live' if data_source == 'production' else '🟡 Preview'}"
    )

with hcol2:
    st.write("")
    cc1, cc2 = st.columns(2)
    with cc1:
        if st.button("🔄", help="Refresh", use_container_width=True):
            st.cache_data.clear()
            st.rerun()
    with cc2:
        if st.button("⎋", help="Logout", use_container_width=True):
            st.session_state.clear()
            st.rerun()

# =========================================================================
# Sidebar — solo lo necesario
# =========================================================================
with st.sidebar:
    st.markdown("### 📤 Subir CSV de MLS")
    uploaded = st.file_uploader(
        "CSV de Matrix",
        type=["csv"],
        label_visibility="collapsed",
    )
    if uploaded is not None:
        try:
            from pipeline.collectors.matrix_csv import parse_matrix_csv
            content = uploaded.read().decode("utf-8", errors="ignore")
            new_leads = parse_matrix_csv(content)
            if new_leads:
                rows = [l.to_dict() for l in new_leads]
                new_df = pd.DataFrame(rows)
                for col in ("first_seen", "last_updated"):
                    new_df[col] = pd.to_datetime(new_df[col])
                target = Path(__file__).parent / "data" / "leads.csv"
                target.parent.mkdir(parents=True, exist_ok=True)
                new_df.to_csv(target, index=False)
                st.success(f"✅ {len(new_leads)} leads. Click refresh.")
                st.cache_data.clear()
            else:
                st.warning("No se detectaron leads en el CSV.")
        except Exception as e:
            st.error(f"Error: {e}")

    st.markdown("---")

    # Filtro de Categoría
    available_cats = sorted(c for c in df["category"].dropna().unique() if c.strip())
    categories = st.multiselect(
        "Categoría",
        options=available_cats,
        default=available_cats,
    )

    # Filtro de ZIP
    zip_input = st.text_input(
        "ZIP code",
        placeholder="33133, 33156, ...",
    )
    selected_zips = [z.strip() for z in zip_input.split(",") if z.strip()] if zip_input else []

    available_zips = sorted(
        z for z in df["zip"].dropna().astype(str).unique()
        if z and z != "nan" and z.strip()
    )
    if available_zips:
        with st.expander(f"{len(available_zips)} ZIPs disponibles"):
            st.caption(", ".join(available_zips))

    # Filtro de County
    available_counties = sorted(c for c in df["county"].dropna().unique() if c.strip())
    if available_counties:
        counties = st.multiselect(
            "County",
            options=available_counties,
            default=available_counties,
        )
    else:
        counties = []

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
# Top: single metric only
# =========================================================================
st.metric("Leads", len(filtered))
st.divider()

# =========================================================================
# Main table — links inline como columnas clickeables
# =========================================================================
if len(filtered) == 0:
    st.info("No hay leads con esos filtros.")
    st.stop()

display = filtered.copy()
display = display.sort_values(["category", "zip"], ascending=[True, True])

# Build link columns (LinkColumn renders these as clickable hyperlinks)
display["Zillow"] = display["full_address"].apply(build_zillow_url)
display["Buscar owner"] = display.apply(
    lambda r: build_owner_lookup_url(r["owner_name"], r["city"]), axis=1
)
display["maps_url"] = display["full_address"].apply(
    lambda a: f"https://www.google.com/maps/search/?api=1&query={urllib.parse.quote_plus(a)}" if a else ""
)

selection = st.dataframe(
    display[[
        "lead_id", "property_address", "zip", "city",
        "category", "owner_name", "owner_phone", "Zillow", "Buscar owner",
    ]],
    column_config={
        "lead_id": st.column_config.TextColumn("ID", width="small"),
        "property_address": st.column_config.TextColumn("Address", width="large"),
        "zip": st.column_config.TextColumn("ZIP", width="small"),
        "city": st.column_config.TextColumn("City", width="small"),
        "category": st.column_config.TextColumn("Categoría", width="small"),
        "owner_name": st.column_config.TextColumn("Owner", width="medium"),
        "owner_phone": st.column_config.TextColumn("Phone", width="small"),
        "Zillow": st.column_config.LinkColumn(
            "🏡 Zillow",
            display_text="Ver",
            width="small",
        ),
        "Buscar owner": st.column_config.LinkColumn(
            "🔎 Buscar owner",
            display_text="Lookup",
            width="small",
            help="LLCs → Sunbiz · Personas → TruePeopleSearch",
        ),
    },
    hide_index=True,
    use_container_width=True,
    on_select="rerun",
    selection_mode="single-row",
    key="main_table",
)

# Export
st.download_button(
    "📥 Export CSV",
    data=display.to_csv(index=False).encode("utf-8"),
    file_name=f"101advisors_{datetime.now().strftime('%Y%m%d')}.csv",
    mime="text/csv",
)

# =========================================================================
# Detail panel — minimalista
# =========================================================================
if selection.selection.rows:
    idx = selection.selection.rows[0]
    lead = display.iloc[idx]

    st.divider()

    # Encabezado del lead
    c1, c2 = st.columns([3, 1])
    with c1:
        st.markdown(f"### {lead['property_address']}")
        st.caption(f"{lead['city']} · ZIP {lead['zip']} · {lead['category']} · {lead['property_type']}")
    with c2:
        st.link_button("🏡 Zillow", lead["Zillow"], use_container_width=True)
        st.link_button("🗺️ Maps", lead["maps_url"], use_container_width=True)

    st.markdown("**Owner**")
    o1, o2 = st.columns([2, 1])
    with o1:
        st.write(f"👤 {lead['owner_name'] or '—'}")
        st.write(f"📞 {lead['owner_phone'] or '—'}")
        st.write(f"✉️ {lead['owner_email'] or '—'}")
    with o2:
        if lead["Buscar owner"]:
            label = "🏢 Sunbiz" if is_llc(lead["owner_name"]) else "🔎 TruePeople"
            st.link_button(label, lead["Buscar owner"], use_container_width=True)
            if not is_llc(lead["owner_name"]) and lead["owner_name"]:
                name_q = urllib.parse.quote_plus(lead["owner_name"])
                fps_url = f"https://www.fastpeoplesearch.com/name/{lead['owner_name'].lower().replace(' ', '-')}"
                st.link_button("🔎 FastPeople", fps_url, use_container_width=True)

    # Bank info si es REO
    owner_upper = (lead["owner_name"] or "").upper()
    is_bank_owned = any(k in owner_upper for k in (
        "BANK", "MORTGAGE", "WELLS FARGO", "JPMORGAN", "CHASE",
        "US BANK", "FEDERAL NATIONAL", "FANNIE", "FREDDIE", "WILMINGTON TRUST"
    ))
    if is_bank_owned:
        st.markdown("**🏦 REO — Owner es banco**")
        st.write(f"Banco actual: **{lead['owner_name']}**")
    elif lead["category"] in ("Lis Pendens", "Foreclosure", "Auction"):
        clerk_url = (
            "https://www2.miamidadeclerk.gov/ocs/Search.aspx?"
            f"q={urllib.parse.quote_plus(lead['owner_name'] or '')}"
        )
        st.markdown("**🏦 Banco + ⚖️ Attorney**")
        st.caption("Info detallada del Clerk de Miami-Dade (case number, plaintiff, attorney)")
        st.link_button("⚖️ Buscar caso en Miami-Dade Clerk", clerk_url, use_container_width=False)

    if lead.get("notes") and not pd.isna(lead["notes"]):
        st.caption(f"💬 {lead['notes']}")
