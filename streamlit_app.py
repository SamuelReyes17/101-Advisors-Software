"""
101 Advisors — Distressed Property Leads
Dashboard estructurado IDÉNTICO al Google Sheet de Leon (21 columnas Scrape).
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
    .block-container {padding-top: 1.5rem; padding-bottom: 2rem; max-width: 100%;}
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
# Constants — matched to Leon's sheet
# =========================================================================
TRI_COUNTY = {"Miami-Dade", "Broward", "Palm Beach"}

# Property types to EXCLUDE by default (Leon's "Properties of Focus" rule):
# "Exclude Condominiums, Exclude Apartments, Exclude Townhomes"
DEFAULT_EXCLUDE_TYPES = {"Condominium", "Apartment", "Townhouse"}

# Leon's 5 Criterio Búsqueda categories
LEON_CATEGORIES = ["Probate", "Lis Pendens", "Foreclosure", "Tax Delinquent", "Liens"]

# Our internal categories (from MLS) → Leon's bucket
MLS_TO_LEON_CATEGORY = {
    "Foreclosure": "Foreclosure",
    "Auction":     "Foreclosure",   # Auctions are a stage of foreclosure
    "Short Sale":  "Foreclosure",   # Pre-foreclosure
    "Lis Pendens": "Lis Pendens",
    "Probate":     "Probate",
    "Tax Delinquent": "Tax Delinquent",
    "Liens":       "Liens",
}

TAX_URLS = {
    "Miami-Dade": "https://www.miamidade.gov/Apps/PA/PropertySearch/#/?folio=",
    "Broward":    "https://broward.county-taxes.com/public/real_estate/searches?search=",
    "Palm Beach": "https://pbctax.gov/property-tax/",
}

CLERK_URLS = {
    "Miami-Dade": "https://www2.miamidadeclerk.gov/ocs/Search.aspx?q=",
    "Broward":    "https://www.browardclerk.org/Web/case_search/?DataType=PartyName&SearchName=",
    "Palm Beach": "https://applications.mypalmbeachclerk.com/CourtCaseSearch/?Name=",
}


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

    # Fillna for string cols
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

    # Numeric fields
    for c in ["outstanding_debt", "equity", "units", "bedrooms",
              "unpaid_taxes_2024", "unpaid_taxes_2025",
              "year_built", "assessed_value", "lot_size_sqft",
              "heated_area_sqft", "bathrooms"]:
        if c in df.columns:
            df[c] = pd.to_numeric(df[c], errors="coerce").fillna(0)
        else:
            df[c] = 0

    # ── String fields ─────────────────────────────────────────────────
    for col in ("purchase_date", "attorney_name", "attorney_phone", "attorney_email",
                "owner_mailing_address", "is_absentee_owner", "folio"):
        if col not in df.columns:
            df[col] = ""
        else:
            df[col] = df[col].fillna("").astype(str)

    # ── Leon's category mapping ──────────────────────────────────────────
    df["leon_category"] = df["category"].map(MLS_TO_LEON_CATEGORY).fillna(df["category"])

    df["in_target_area"] = (
        df["county"].isin(TRI_COUNTY) | df["county"].isna() | (df["county"] == "")
    )

    return df, source_label


def is_llc(name: str) -> bool:
    return bool(re.search(r"\b(LLC|INC|CORP|TRUST|TRS|LTD|LP|LLP|PA|HOLDINGS|GROUP|ASSOC|ASSN)\b",
                          name or "", re.IGNORECASE))


def is_bank_owned(name: str) -> bool:
    return any(k in (name or "").upper() for k in (
        "BANK", "MORTGAGE", "WELLS FARGO", "JPMORGAN", "CHASE",
        "US BANK", "FEDERAL NATIONAL", "FANNIE", "FREDDIE", "WILMINGTON TRUST"
    ))


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
    city_q = urllib.parse.quote_plus(city) if city else ""
    suffix = f"&citystatezip={city_q}+FL" if city_q else ""
    return f"https://www.truepeoplesearch.com/results?name={name_q}{suffix}"


def build_tax_url(county: str, address: str) -> str:
    if not address:
        return ""
    base = TAX_URLS.get(county, TAX_URLS["Miami-Dade"])
    return base + urllib.parse.quote_plus(address)


def build_clerk_url(county: str, owner_name: str) -> str:
    if not owner_name:
        return ""
    base = CLERK_URLS.get(county, CLERK_URLS["Miami-Dade"])
    return base + urllib.parse.quote_plus(owner_name)


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
# Sidebar
# =========================================================================
with st.sidebar:
    st.markdown("### 📤 Subir CSV de MLS")
    uploaded = st.file_uploader("CSV de Matrix", type=["csv"], label_visibility="collapsed")
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
    st.markdown("### 🔍 Filtros (Criterio Búsqueda)")

    # ── Criterio (Leon's 5 buckets) ─────────────────────────────────────
    available_leon_cats = sorted(set(df["leon_category"].dropna()) & set(LEON_CATEGORIES))
    if not available_leon_cats:
        available_leon_cats = LEON_CATEGORIES
    leon_categories = st.multiselect(
        "Criterio Búsqueda",
        options=LEON_CATEGORIES,
        default=available_leon_cats,
    )

    # ── Property type EXCLUSION (Leon's "Properties of Focus" rule) ────
    available_types = sorted(p for p in df["property_type"].dropna().unique() if p.strip())
    excluded_types = st.multiselect(
        "Excluir Property Types",
        options=available_types,
        default=[t for t in DEFAULT_EXCLUDE_TYPES if t in available_types],
        help="Leon excluye Condominios, Apartments, Townhomes por defecto",
    )

    # ── ZIP ──────────────────────────────────────────────────────────────
    zip_input = st.text_input("ZIP code", placeholder="33133, 33156, ...")
    selected_zips = [z.strip() for z in zip_input.split(",") if z.strip()] if zip_input else []

    # ── County ───────────────────────────────────────────────────────────
    counties = st.multiselect(
        "County",
        options=["Miami-Dade", "Broward", "Palm Beach"],
        default=["Miami-Dade", "Broward", "Palm Beach"],
    )

    show_offtarget = st.checkbox("Mostrar leads fuera del área", value=False)

# =========================================================================
# Apply filters
# =========================================================================
mask = pd.Series([True] * len(df), index=df.index)

if leon_categories:
    mask = mask & df["leon_category"].isin(leon_categories)

if excluded_types:
    mask = mask & ~df["property_type"].isin(excluded_types)

if selected_zips:
    mask = mask & df["zip"].astype(str).isin(selected_zips)

if counties:
    county_mask = df["county"].isin(counties) | df["county"].isna() | (df["county"] == "")
    mask = mask & county_mask

if not show_offtarget:
    mask = mask & df["in_target_area"]

filtered = df[mask].copy()

# =========================================================================
# Single metric
# =========================================================================
st.metric("Leads", len(filtered))
st.divider()

# =========================================================================
# Main table — 21 columnas exactas del Sheet de Leon + 4 links de lookup
# =========================================================================
if len(filtered) == 0:
    st.info("No hay leads con esos filtros.")
    st.stop()

display = filtered.copy()

# Compute link URLs
display["zillow_url"] = display["full_address"].apply(build_zillow_url)
display["owner_lookup_url"] = display.apply(
    lambda r: build_owner_lookup_url(r["owner_name"], r["city"]), axis=1
)
display["tax_url"] = display.apply(
    lambda r: build_tax_url(r["county"], r["full_address"]), axis=1
)
display["clerk_url"] = display.apply(
    lambda r: build_clerk_url(r["county"], r["owner_name"]), axis=1
)

# Sort: Miami-Dade leads first (most data), then by tax estimate descending
# (high-value leads on top). Empty rows last.
display["_sort_has_owner"] = (display["owner_name"].str.strip() != "").astype(int)
display["_sort_tax"] = pd.to_numeric(display.get("unpaid_taxes_2025", 0), errors="coerce").fillna(0)
display = display.sort_values(
    ["_sort_has_owner", "_sort_tax"],
    ascending=[False, False],
)

# Bank: para REOs, el owner es el banco
display["bank_name_display"] = display.apply(
    lambda r: r["owner_name"] if is_bank_owned(r["owner_name"]) else (r.get("lender_name") or ""),
    axis=1,
)

st.caption(
    f"📋 **{len(display)} leads** · estructura idéntica al Sheet de Leon · "
    "click 🏡/🔎/🧾/⚖️ para abrir lookups"
)

# Column order matches Leon's sheet exactly (scrape section)
table_columns = [
    "property_address",         # Property Address
    "zip",                      # Zipcode
    "outstanding_debt",         # Purchase Price (MLS list price)
    "purchase_date",            # Property Purchase Date
    "property_type",            # Property Type
    "units",                    # How many units?
    "bedrooms",                 # How many bedrooms?
    "owner_first",              # Owner First Name
    "owner_last",               # Owner Last Name
    "owner_phone",              # Owner Phone
    "owner_email",              # Owner Email Address
    "bank_name_display",        # Bank / Lender Name
    "lender_phone",             # Bank / Lender Contact Phone
    "lender_email",             # Bank / Lender Contact Email
    "bank_address",             # Bank Address
    "outstanding_debt",         # Outstanding Debt / Loan (reuses col)
    "attorney_name",            # Case Attorney name
    "attorney_phone",           # Case attorney phone
    "attorney_email",           # Case attorney email
    "unpaid_taxes_2024",        # Unpaid Taxes 2024
    "unpaid_taxes_2025",        # Unpaid Taxes 2025
    # Lookup columns (al final)
    "zillow_url",
    "owner_lookup_url",
    "tax_url",
    "clerk_url",
]

# Duplicate columns can't be in dataframe; rename for display
display_renamed = display.copy()
display_renamed = display_renamed.rename(columns={"outstanding_debt": "purchase_price"})
display_renamed["outstanding_debt_col"] = display["outstanding_debt"]

# Final columns to show — botones de lookup PRIMERO para que sean visibles
# sin necesidad de scrollar horizontalmente.
final_cols = [
    "property_address",
    # 🎯 Lookup buttons al principio
    "zillow_url", "owner_lookup_url", "tax_url", "clerk_url",
    # Datos
    "zip", "purchase_price", "purchase_date", "property_type",
    "units", "bedrooms", "owner_first", "owner_last", "owner_phone", "owner_email",
    "bank_name_display", "lender_phone", "lender_email", "bank_address",
    "outstanding_debt_col", "attorney_name", "attorney_phone", "attorney_email",
    "unpaid_taxes_2024", "unpaid_taxes_2025",
]

selection = st.dataframe(
    display_renamed[final_cols],
    column_config={
        "property_address":   st.column_config.TextColumn("Property Address", width="large"),
        "zip":                st.column_config.TextColumn("Zipcode", width="small"),
        "purchase_price":     st.column_config.NumberColumn("Purchase Price", format="$%d", width="small"),
        "purchase_date":      st.column_config.TextColumn("Purchase Date", width="small"),
        "property_type":      st.column_config.TextColumn("Property Type", width="small"),
        "units":              st.column_config.NumberColumn("Units", width="small"),
        "bedrooms":           st.column_config.NumberColumn("Bedrooms", width="small"),
        "owner_first":        st.column_config.TextColumn("Owner First Name", width="medium"),
        "owner_last":         st.column_config.TextColumn("Owner Last Name", width="medium"),
        "owner_phone":        st.column_config.TextColumn("Owner Phone", width="small"),
        "owner_email":        st.column_config.TextColumn("Owner Email", width="medium"),
        "bank_name_display":  st.column_config.TextColumn("Bank / Lender Name", width="medium"),
        "lender_phone":       st.column_config.TextColumn("Bank Phone", width="small"),
        "lender_email":       st.column_config.TextColumn("Bank Email", width="medium"),
        "bank_address":       st.column_config.TextColumn("Bank Address", width="medium"),
        "outstanding_debt_col": st.column_config.NumberColumn("Outstanding Debt / Loan", format="$%d", width="small"),
        "attorney_name":      st.column_config.TextColumn("Attorney Name", width="medium"),
        "attorney_phone":     st.column_config.TextColumn("Attorney Phone", width="small"),
        "attorney_email":     st.column_config.TextColumn("Attorney Email", width="medium"),
        "unpaid_taxes_2024":  st.column_config.NumberColumn(
            "Est. Tax 2024", format="$%d", width="small",
            help="Estimado del tax bill anual (Taxable Value × 22 mills). "
                 "Para delinquency real click 🧾 Tax.",
        ),
        "unpaid_taxes_2025":  st.column_config.NumberColumn(
            "Est. Tax 2025", format="$%d", width="small",
            help="Estimado del tax bill anual (Taxable Value × 22 mills). "
                 "Para delinquency real click 🧾 Tax.",
        ),
        # Lookup buttons al final
        "zillow_url":         st.column_config.LinkColumn("🏡", display_text="Zillow", width="small"),
        "owner_lookup_url":   st.column_config.LinkColumn(
            "🔎 Owner", display_text="Buscar",
            help="LLC → Sunbiz · Persona → TruePeople", width="small",
        ),
        "tax_url":            st.column_config.LinkColumn(
            "🧾 Tax", display_text="Tax",
            help="Tax delinquency en el county tax collector", width="small",
        ),
        "clerk_url":          st.column_config.LinkColumn(
            "⚖️ Clerk", display_text="Clerk",
            help="Lis Pendens + plaintiff + attorney en el Clerk", width="small",
        ),
    },
    hide_index=True,
    use_container_width=True,
    on_select="rerun",
    selection_mode="single-row",
    key="main_table",
)

st.download_button(
    "📥 Export CSV (formato Leon)",
    data=display_renamed[final_cols].to_csv(index=False).encode("utf-8"),
    file_name=f"101advisors_{datetime.now().strftime('%Y%m%d')}.csv",
    mime="text/csv",
)

# =========================================================================
# Detail panel
# =========================================================================
if selection.selection.rows:
    idx = selection.selection.rows[0]
    lead = display.iloc[idx]

    st.divider()
    st.markdown(f"### {lead['property_address']}")
    st.caption(
        f"{lead['city']} · ZIP {lead['zip']} · {lead['leon_category']} · "
        f"{lead['property_type']} · {lead['county']}"
    )

    # Property details (de Property Appraiser)
    p1, p2, p3, p4 = st.columns(4)
    yb = int(lead.get("year_built") or 0)
    if yb:
        p1.metric("Year built", yb)
    if int(lead.get("assessed_value") or 0):
        p2.metric("Assessed value", f"${int(lead['assessed_value']):,}")
    if float(lead.get("heated_area_sqft") or 0):
        p3.metric("Heated sqft", f"{int(lead['heated_area_sqft']):,}")
    if float(lead.get("lot_size_sqft") or 0):
        p4.metric("Lot sqft", f"{int(lead['lot_size_sqft']):,}")

    # Owner block + Lookup buttons
    o1, o2 = st.columns([2, 1])
    with o1:
        st.markdown("**👤 Owner**")
        st.write(f"Nombre: {lead['owner_name'] or '—'}")
        st.write(f"Phone: {lead['owner_phone'] or '— (click 🔎 abajo)'}")
        st.write(f"Email: {lead['owner_email'] or '—'}")
        if lead.get("owner_mailing_address"):
            st.write(f"📬 Mailing: {lead['owner_mailing_address']}")
        if lead.get("is_absentee_owner") == "yes":
            st.warning("🚨 **ABSENTEE OWNER** — el dueño no vive ahí (oro para cold call)")
    with o2:
        st.markdown("**Lookups directos**")
        if lead["zillow_url"]:
            st.link_button("🏡 Zillow", lead["zillow_url"], use_container_width=True)
        if lead["owner_lookup_url"]:
            label = "🏢 Sunbiz" if is_llc(lead["owner_name"]) else "🔎 TruePeople"
            st.link_button(label, lead["owner_lookup_url"], use_container_width=True)

    # Bank
    st.markdown("**🏦 Bank**")
    if is_bank_owned(lead["owner_name"]):
        st.info(f"REO — el owner ES el banco: **{lead['owner_name']}**")
    elif lead["leon_category"] in ("Lis Pendens", "Foreclosure"):
        st.caption("Banco demandante + número de caso → click ⚖️ Clerk")
        if lead["clerk_url"]:
            st.link_button("⚖️ Ver caso en el Clerk", lead["clerk_url"])
    else:
        st.caption("Sin banco asociado")

    # Tax
    st.markdown("**🧾 Tax Delinquency**")
    tax_2024 = float(lead.get("unpaid_taxes_2024") or 0)
    tax_2025 = float(lead.get("unpaid_taxes_2025") or 0)
    if tax_2024 or tax_2025:
        t1, t2 = st.columns(2)
        t1.metric("Tax 2024 vencido", f"${tax_2024:,.0f}")
        t2.metric("Tax 2025 vencido", f"${tax_2025:,.0f}")
    else:
        st.caption("Datos de tax no auto-populados aún. Click 🧾 Tax para verificar manualmente.")
    if lead["tax_url"]:
        st.link_button("🧾 Verificar tax delinquency", lead["tax_url"])

    # Attorney + Lis Pendens
    if lead["leon_category"] in ("Lis Pendens", "Foreclosure"):
        st.markdown("**⚖️ Attorney + Case info**")
        if lead.get("attorney_name"):
            st.write(f"Attorney: {lead['attorney_name']}")
            st.write(f"Phone: {lead.get('attorney_phone') or '—'}")
            st.write(f"Email: {lead.get('attorney_email') or '—'}")
        else:
            st.caption("Click ⚖️ Clerk para ver case number + plaintiff (banco) + attorney")
        if lead["clerk_url"]:
            st.link_button("⚖️ Buscar caso en el Clerk", lead["clerk_url"], key="clerk_attorney_btn")

    if lead.get("notes") and not pd.isna(lead["notes"]):
        st.caption(f"💬 {lead['notes']}")
