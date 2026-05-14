"""
101 Advisors — Property Leads Platform
Dashboard estructurado con la información clave de cada lead.
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
        st.markdown("### Property Leads Platform")
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

# Leon's Criterio Búsqueda categories (Auction + Short Sale are separate buckets)
LEON_CATEGORIES = [
    "Foreclosure", "Auction", "Short Sale", "Lis Pendens",
    "Probate", "Tax Delinquent", "Liens",
]

# Our internal categories (from MLS) → Leon's bucket (kept granular)
MLS_TO_LEON_CATEGORY = {
    "Foreclosure":    "Foreclosure",   # REOs (bank-owned)
    "Auction":        "Auction",       # Court auctions — own bucket
    "Short Sale":     "Short Sale",    # Pre-foreclosure — own bucket
    "Lis Pendens":    "Lis Pendens",
    "Probate":        "Probate",
    "Tax Delinquent": "Tax Delinquent",
    "Liens":          "Liens",
}

# Tax URLs — TESTED working URLs.
# For Miami-Dade we have folio so we deep-link to the PA SPA (which shows
# tax info in the Taxes tab). For Broward/PB we open the public search.
TAX_URLS_FOLIO = {
    "Miami-Dade": "https://apps.miamidadepa.gov/propertysearch/#/property?folio=",
}
TAX_URLS_ADDRESS = {
    "Broward":    "https://web.bcpa.net/bcpaclient/#/Record-Search",
    "Palm Beach": "https://pbctax.gov/property-tax/",
}

# Clerk URLs — public portals. Most are SPAs that don't accept deep links,
# so we open the home page; the agent does ~2 clicks to reach case search.
CLERK_URLS = {
    "Miami-Dade": "https://www2.miamidadeclerk.gov/ocs/#/Search",
    "Broward":    "https://www.browardclerk.org/Web/case_search/",
    "Palm Beach": "https://applications.mypalmbeachclerk.com/CourtCaseSearch/",
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
                "owner_mailing_address", "is_absentee_owner", "folio",
                "clerk_case_number", "clerk_filing_date", "clerk_case_type",
                "clerk_case_status", "clerk_section", "clerk_plaintiff",
                "clerk_defendant", "clerk_match_confidence"):
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


def build_owner_lookup_url(owner_name: str, city: str = "", zip_code: str = "",
                            mailing_address: str = "") -> str:
    """For LLCs → Sunbiz search. For persons → TruePeopleSearch with the
    MAILING address (more specific than just city — finds the right person)."""
    if not owner_name:
        return ""
    name_q = urllib.parse.quote_plus(owner_name.strip())
    if is_llc(owner_name):
        return f"https://search.sunbiz.org/Inquiry/CorporationSearch/ByName?searchTerm={name_q}"

    # Use mailing address (if available) — much more specific than just city
    # Mailing address looks like "2735 SW 36 AVE, MIAMI, FL 33133"
    if mailing_address and "," in mailing_address:
        # Extract just city+state+zip from mailing address for TruePeopleSearch
        parts = [p.strip() for p in mailing_address.split(",")]
        if len(parts) >= 2:
            # Last 2 parts are usually city + "STATE ZIP"
            citystatezip = urllib.parse.quote_plus(", ".join(parts[-2:]))
            return f"https://www.truepeoplesearch.com/results?name={name_q}&citystatezip={citystatezip}"

    # Fallback: city + state + ZIP
    citystate = (city or "Miami").strip()
    if zip_code:
        citystatezip = urllib.parse.quote_plus(f"{citystate}, FL {zip_code}")
    else:
        citystatezip = urllib.parse.quote_plus(f"{citystate}, FL")
    return f"https://www.truepeoplesearch.com/results?name={name_q}&citystatezip={citystatezip}"


def build_fastpeople_url(owner_name: str, city: str = "") -> str:
    """FastPeopleSearch — alternative free people-search engine."""
    if not owner_name or is_llc(owner_name):
        return ""
    name_slug = owner_name.strip().lower().replace(" ", "-")
    city_slug = (city or "miami").strip().lower().replace(" ", "-")
    return f"https://www.fastpeoplesearch.com/name/{name_slug}_{city_slug}-fl"


def build_whitepages_url(owner_name: str, city: str = "") -> str:
    """WhitePages — third option for cross-checking."""
    if not owner_name or is_llc(owner_name):
        return ""
    name_slug = owner_name.strip().replace(" ", "-")
    if city:
        return f"https://www.whitepages.com/name/{urllib.parse.quote(name_slug)}/{urllib.parse.quote(city)}-FL"
    return f"https://www.whitepages.com/name/{urllib.parse.quote(name_slug)}"


def build_tax_url(county: str, address: str, folio: str = "") -> str:
    """For Miami-Dade with folio, deep-link to the PA SPA on that property
    (tax info is visible in the Taxes tab). For Broward/PB, open the county
    tax search portal."""
    # Miami-Dade — best deep link via folio
    if county == "Miami-Dade" and folio:
        return TAX_URLS_FOLIO["Miami-Dade"] + folio.strip()
    # Broward — BCPA search
    if county == "Broward":
        return TAX_URLS_ADDRESS["Broward"]
    # Palm Beach
    if county == "Palm Beach":
        return TAX_URLS_ADDRESS["Palm Beach"]
    # Fallback: Miami-Dade PA SPA home (user can search address there)
    return "https://apps.miamidadepa.gov/propertysearch/"


def build_clerk_url(county: str, owner_name: str = "") -> str:
    """Open the Clerk's case search page. Deep links into searches don't
    work for these SPAs — the agent needs to type the owner name once
    they're on the search page."""
    return CLERK_URLS.get(county, CLERK_URLS["Miami-Dade"])


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

    only_with_clerk_case = st.checkbox(
        "🎯 Solo con caso Clerk identificado",
        value=False,
        help="Filtra los ~40 leads donde detectamos un caso de foreclosure activo en el Clerk de Miami-Dade",
    )

    hide_empty_cols = st.checkbox(
        "🧹 Ocultar columnas sin data",
        value=True,
        help="Por defecto ocultamos Phone/Email/Attorney (data no disponible auto). Destildar para verlas vacías.",
    )

    # ── Date Added filter — para ver solo los leads nuevos del día/semana ──
    st.markdown("**📅 Date Added**")
    date_filter = st.selectbox(
        "Cuándo se agregaron",
        options=["Todos", "Hoy", "Ayer", "Últimos 7 días", "Últimos 30 días"],
        index=0,
        help="Filtrá leads por cuándo entraron al sistema. Útil para enfocarse en los nuevos del día.",
    )

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

if only_with_clerk_case:
    mask = mask & (df["clerk_case_number"].astype(str).str.strip() != "")

# Date Added filter
if date_filter != "Todos":
    today_ts = pd.Timestamp.today().normalize()
    df_first_seen = pd.to_datetime(df["first_seen"], errors="coerce")
    if date_filter == "Hoy":
        mask = mask & (df_first_seen == today_ts)
    elif date_filter == "Ayer":
        mask = mask & (df_first_seen == today_ts - pd.Timedelta(days=1))
    elif date_filter == "Últimos 7 días":
        mask = mask & (df_first_seen >= today_ts - pd.Timedelta(days=7))
    elif date_filter == "Últimos 30 días":
        mask = mask & (df_first_seen >= today_ts - pd.Timedelta(days=30))

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

# Compute link URLs (using folio + zip + mailing address for better targeting)
display["zillow_url"] = display["full_address"].apply(build_zillow_url)
display["owner_lookup_url"] = display.apply(
    lambda r: build_owner_lookup_url(
        r["owner_name"], r["city"], r["zip"], r.get("owner_mailing_address", "")
    ),
    axis=1,
)
display["fastpeople_url"] = display.apply(
    lambda r: build_fastpeople_url(r["owner_name"], r["city"]), axis=1,
)
display["whitepages_url"] = display.apply(
    lambda r: build_whitepages_url(r["owner_name"], r["city"]), axis=1,
)
display["tax_url"] = display.apply(
    lambda r: build_tax_url(r["county"], r["full_address"], r.get("folio", "")), axis=1
)
display["clerk_url"] = display["county"].apply(build_clerk_url)

# Filter out non-actionable Clerk cases:
#   - "Z DO NOT USE" / Z LEGACY: deprecated records
#   - "Replevin": personal property recovery (typically cars, not real estate)
LEGACY_PATTERNS = ("Z DO NOT USE", "Z LEGACY", "Z OLD", "REPLEVIN")
display["_legacy_case"] = display["clerk_case_type"].astype(str).str.upper().str.startswith(LEGACY_PATTERNS)
# Clear the clerk fields for legacy cases (keep the lead, just hide the bad data)
legacy_mask = display["_legacy_case"]
for col in ("clerk_case_number", "clerk_filing_date", "clerk_case_status",
            "clerk_case_type", "clerk_plaintiff", "clerk_defendant", "lender_name"):
    if col in display.columns:
        display.loc[legacy_mask, col] = ""

# Sort priority (most important first):
#   1. Leads added TODAY first (so the daily new ones appear on top)
#   2. Then leads with active Clerk case OPEN
#   3. Then leads with any Clerk case
#   4. Then leads with owner data
#   5. Then by tax descending
today_str = pd.Timestamp.today().strftime("%Y-%m-%d")
display["_sort_is_new_today"] = display["first_seen"].astype(str).str.startswith(today_str).astype(int)
display["_sort_clerk_open"] = (display["clerk_case_status"].str.upper() == "OPEN").astype(int)
display["_sort_has_case"]   = (display["clerk_case_number"].astype(str).str.strip() != "").astype(int)
display["_sort_has_owner"]  = (display["owner_name"].str.strip() != "").astype(int)
display["_sort_tax"] = pd.to_numeric(display.get("unpaid_taxes_2025", 0), errors="coerce").fillna(0)
display = display.sort_values(
    ["_sort_is_new_today", "_sort_clerk_open", "_sort_has_case", "_sort_has_owner", "_sort_tax"],
    ascending=[False, False, False, False, False],
)

# Add 🆕 marker to address for today's new leads (visible at a glance)
display.loc[display["_sort_is_new_today"] == 1, "full_address"] = (
    "🆕 " + display.loc[display["_sort_is_new_today"] == 1, "full_address"]
)
display.loc[display["_sort_is_new_today"] == 1, "property_address"] = (
    "🆕 " + display.loc[display["_sort_is_new_today"] == 1, "property_address"]
)

# Format Date Added column nicely (MM/DD/YYYY) so Leon ve fácil cuándo entró cada lead
display["date_added_display"] = pd.to_datetime(
    display["first_seen"], errors="coerce"
).dt.strftime("%m/%d/%Y").fillna("")

# Bank/Plaintiff: for REOs, the owner is the bank itself.
# For active cases, the lender_name column holds the foreclosure plaintiff
# (which can be a bank, HOA, contractor, or other lender).
display["bank_name_display"] = display.apply(
    lambda r: r["owner_name"] if is_bank_owned(r["owner_name"]) else (r.get("lender_name") or ""),
    axis=1,
)

# Classify the plaintiff type so Leon's team knows what kind of foreclosure it is
def _classify_plaintiff(name: str) -> str:
    if not name or not name.strip():
        return ""
    upper = name.upper()
    if any(k in upper for k in ("BANK", "MORTGAGE", "JPMORGAN", "CHASE",
                                "WELLS FARGO", "US BANK", "CITIBANK",
                                "FEDERAL NATIONAL", "FANNIE", "FREDDIE",
                                "DEUTSCHE", "AURORA LOAN", "WACHOVIA",
                                "SUNTRUST", "TRUIST", "HSBC", "WILMINGTON")):
        return "🏦 Bank"
    if any(k in upper for k in ("CONDO", "CONDOMINIUM", "ASSOCIATION",
                                "HOMEOWNERS", "HOA", "TOWNHOMES", "VILLAS",
                                "TOWERS", "MASTER MAINTENANCE")):
        return "🏘️ HOA/Condo"
    if any(k in upper for k in ("CREDIT UNION", "FCU", "CU")):
        return "🏦 Credit Union"
    if any(k in upper for k in ("MOTOR CREDIT", "AUTO", "LEASING", "LEASE")):
        return "🚗 Auto Lender"
    if any(k in upper for k in ("CONSTRUCTION", "CONTRACTOR", "REPAIR",
                                "ELECTRICAL", "PLUMBING", "ROOFING",
                                "WINDOWS", "DOORS")):
        return "🔨 Contractor"
    if "TRUST" in upper:
        return "📋 Trust"
    return "🏢 Other"

display["plaintiff_type"] = display["bank_name_display"].apply(_classify_plaintiff)

# Add emoji prefix to the Criterio column so it pops visually in the table
CRITERIO_EMOJI = {
    "Foreclosure":    "🏦 Foreclosure",
    "Auction":        "🔨 Auction",
    "Short Sale":     "🏠 Short Sale",
    "Lis Pendens":    "⚖️ Lis Pendens",
    "Probate":        "📜 Probate",
    "Tax Delinquent": "🧾 Tax Delinquent",
    "Liens":          "🔗 Liens",
}
display["leon_category"] = display["leon_category"].map(CRITERIO_EMOJI).fillna(display["leon_category"])

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
    # ⭐ Criterio PRIMERO — siempre visible sin scroll
    "leon_category",
    # 📅 Date Added — cuándo entró al sistema (útil para ver nuevos diarios)
    "date_added_display",
    "property_address",
    # 🎯 Lookup buttons
    "zillow_url", "owner_lookup_url", "tax_url", "clerk_url",
    # Datos
    "zip", "purchase_price", "purchase_date", "property_type",
    "units", "bedrooms", "owner_first", "owner_last", "owner_phone", "owner_email",
    # Plaintiff / Bank info
    "bank_name_display", "plaintiff_type",
    "lender_phone", "lender_email", "bank_address",
    "outstanding_debt_col", "attorney_name", "attorney_phone", "attorney_email",
    "unpaid_taxes_2024", "unpaid_taxes_2025",
    # 🆕 Clerk data
    "clerk_case_number", "clerk_filing_date", "clerk_case_status", "clerk_case_type",
]

# Hide columns that are 100% empty if user toggled it (default ON)
# These are fields we don't auto-populate: phone, email, attorney info, etc.
if hide_empty_cols:
    cols_with_data = []
    for c in final_cols:
        if c.endswith("_url"):
            cols_with_data.append(c)  # always keep link columns
            continue
        if c not in display_renamed.columns:
            continue
        col_vals = display_renamed[c]
        # Check if column has any non-empty / non-zero values
        if col_vals.dtype.kind in ("i", "f"):
            has_data = (col_vals != 0).any()
        else:
            has_data = col_vals.astype(str).str.strip().replace("nan", "").ne("").any()
        if has_data:
            cols_with_data.append(c)
    hidden = [c for c in final_cols if c not in cols_with_data]
    if hidden:
        st.caption(
            f"🧹 Ocultando {len(hidden)} columna(s) sin data: "
            f"{', '.join(c.replace('_', ' ').title() for c in hidden[:8])}"
            + ("..." if len(hidden) > 8 else "")
        )
    final_cols = cols_with_data

selection = st.dataframe(
    display_renamed[final_cols],
    column_config={
        "leon_category":      st.column_config.TextColumn(
            "Criterio", width="medium", pinned=True,
            help="Tipo de propiedad distressed — Foreclosure / Auction / Short Sale / Lis Pendens",
        ),
        "date_added_display": st.column_config.TextColumn(
            "Date Added", width="small",
            help="Fecha en que el lead entró al sistema. Útil para filtrar los nuevos del día.",
        ),
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
        "bank_name_display":  st.column_config.TextColumn(
            "Plaintiff (Bank/HOA/Lien)", width="medium",
            help="El demandante del caso de foreclosure. Puede ser un banco, "
                 "una asociación de condo/HOA, un contractor con lien, o un auto lender.",
        ),
        "plaintiff_type":     st.column_config.TextColumn("Type", width="small"),
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
        # 🆕 Clerk data columns
        "clerk_case_number":  st.column_config.TextColumn("Case Number", width="medium",
            help="Caso de foreclosure/Lis Pendens en Miami-Dade Clerk OCS"),
        "clerk_filing_date":  st.column_config.TextColumn("Case Filed", width="small"),
        "clerk_case_status":  st.column_config.TextColumn("Case Status", width="small"),
        "clerk_case_type":    st.column_config.TextColumn("Case Type", width="medium"),
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

# Build Excel (.xlsx) file in memory for download
import io as _io
_excel_buf = _io.BytesIO()
with pd.ExcelWriter(_excel_buf, engine="openpyxl") as _writer:
    display_renamed[final_cols].to_excel(_writer, index=False, sheet_name="Leads")
_excel_buf.seek(0)

dl_col1, dl_col2 = st.columns([1, 4])
with dl_col1:
    st.download_button(
        "📥 Exportar a Excel",
        data=_excel_buf.getvalue(),
        file_name=f"101advisors_leads_{datetime.now().strftime('%Y%m%d')}.xlsx",
        mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        use_container_width=True,
    )
with dl_col2:
    # Keep CSV as backup option in case Excel doesn't open somewhere
    st.download_button(
        "Export CSV",
        data=display_renamed[final_cols].to_csv(index=False).encode("utf-8"),
        file_name=f"101advisors_leads_{datetime.now().strftime('%Y%m%d')}.csv",
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

    # Owner block + Skip-Trace Toolkit
    o1, o2 = st.columns([2, 1])
    with o1:
        st.markdown("**👤 Owner**")
        st.write(f"Nombre: {lead['owner_name'] or '—'}")
        st.write(f"Phone: {lead['owner_phone'] or '— (skip-trace)'}")
        st.write(f"Email: {lead['owner_email'] or '— (skip-trace)'}")
        if lead.get("owner_mailing_address"):
            st.write(f"📬 Mailing: {lead['owner_mailing_address']}")
        if lead.get("is_absentee_owner") == "yes":
            st.warning("🚨 **ABSENTEE OWNER** — el dueño no vive ahí. Mejor lead para cold call.")
    with o2:
        st.markdown("**Property**")
        if lead["zillow_url"]:
            st.link_button("🏡 Zillow", lead["zillow_url"], use_container_width=True)

    # ── Skip-Trace Toolkit — phones/emails buscando en sitios gratis ───
    st.markdown("**📞 Skip-Trace Toolkit** — buscar phone + email del owner")
    if is_llc(lead["owner_name"]):
        # LLC owner — Sunbiz is the right place
        if lead.get("owner_lookup_url"):
            st.link_button(
                "🏢 Sunbiz — ver officers + mailing address del LLC",
                lead["owner_lookup_url"],
            )
        st.caption(
            "Click para ver los oficiales reales detrás del LLC en el registro de FL. "
            "Después podés buscar a esa persona física en TruePeople/FastPeople."
        )
    else:
        # Person — show all 3 free sites side-by-side
        st1, st2, st3 = st.columns(3)
        with st1:
            if lead.get("owner_lookup_url"):
                st.link_button("🔎 TruePeople", lead["owner_lookup_url"],
                               use_container_width=True)
        with st2:
            if lead.get("fastpeople_url"):
                st.link_button("🔎 FastPeople", lead["fastpeople_url"],
                               use_container_width=True)
        with st3:
            if lead.get("whitepages_url"):
                st.link_button("🔎 WhitePages", lead["whitepages_url"],
                               use_container_width=True)
        st.caption(
            "👆 3 sitios gratis. Si TruePeople no muestra phone, probá FastPeople o WhitePages. "
            "Suelen tener data complementaria. ~30 segundos de búsqueda por lead."
        )

    # ── Honest disclosure: el upgrade pago ─────────────────────────────
    with st.expander("ℹ️ Why is phone/email not auto-populated?"):
        st.markdown("""
**Reality of phone/email data in Florida:**

Phone numbers and emails are **NOT public records**. They live in private databases
that aggregate from utility companies, credit bureaus, social media, etc. These
databases are licensed and cost money.

**Free options** (manual, ~30 sec/lead):
- TruePeopleSearch — best free, ~70% match rate
- FastPeopleSearch — backup, sometimes has data TPS doesn't
- WhitePages — third option

**Paid options to automate** (for the 101 Advisors team):
- **BatchSkipTracing** — $0.20/lookup pay-as-you-go. ~$20/mes para 100 leads.
  Most popular among real estate wholesalers in FL.
- **PropStream** — $99/mes flat, unlimited skip-trace + filters + lists.
  Industry standard for big firms.
- **REISkip** — $0.10/lookup, similar to BatchSkipTracing.

We can wire any of these into the dashboard in 1 hour of code if you choose to subscribe.
        """)

    # Bank + Clerk case (auto-fetched from Miami-Dade Clerk OCS)
    st.markdown("**🏦 Bank / Foreclosure Case**")
    clerk_case = (lead.get("clerk_case_number") or "").strip()
    if clerk_case:
        # We have a Clerk case auto-detected
        status = (lead.get("clerk_case_status") or "").strip()
        status_icon = "🔴 OPEN" if status == "OPEN" else f"⚪ {status}"
        c1, c2 = st.columns([2, 1])
        with c1:
            st.success(f"**🏦 Plaintiff**: {lead.get('clerk_plaintiff') or lead.get('lender_name', '—')}")
            st.write(f"**📋 Case**: `{clerk_case}` · {status_icon}")
            st.write(f"**📅 Filed**: {lead.get('clerk_filing_date', '—')}")
            st.write(f"**⚖️ Type**: {lead.get('clerk_case_type', '—')}")
            st.write(f"**👥 Defendant**: {lead.get('clerk_defendant', '—')}")
        with c2:
            if lead["clerk_url"]:
                st.link_button("⚖️ Ver en Clerk", lead["clerk_url"], use_container_width=True)
    elif is_bank_owned(lead["owner_name"]):
        st.info(f"REO — el owner ES el banco: **{lead['owner_name']}**")
    elif lead["leon_category"] in ("Lis Pendens", "Foreclosure"):
        st.caption("No detectamos caso Clerk activo. Click ⚖️ para buscar manualmente.")
        if lead["clerk_url"]:
            st.link_button("⚖️ Buscar en el Clerk", lead["clerk_url"])
    else:
        st.caption("Sin caso de foreclosure asociado")

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
