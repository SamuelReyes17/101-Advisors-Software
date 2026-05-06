"""
101 Advisors — Distressed Property Lead Generation Dashboard
=============================================================
MVP version with sample data. Once collectors are built, the data source
switches from CSV to Google Sheets without changing the UI.

Deploy: push this repo to GitHub, connect at share.streamlit.io.
Run locally: `streamlit run streamlit_app.py`
"""

import streamlit as st
import pandas as pd
from datetime import datetime, timedelta
from pathlib import Path

# =========================================================================
# Page config
# =========================================================================
st.set_page_config(
    page_title="101 Advisors · Lead Generator",
    page_icon="🏠",
    layout="wide",
    initial_sidebar_state="expanded",
    menu_items={
        "About": "101 Advisors Distressed Property Lead Generator · MVP v0.1"
    },
)

# =========================================================================
# Custom CSS — clean & minimal
# =========================================================================
st.markdown(
    """
    <style>
    #MainMenu {visibility: hidden;}
    footer {visibility: hidden;}
    .block-container {padding-top: 2rem; padding-bottom: 2rem; max-width: 1400px;}
    div[data-testid="stMetricValue"] {font-size: 2rem; font-weight: 600;}
    div[data-testid="stMetricLabel"] {font-size: 0.85rem; color: #5F5E5A;}
    .stTabs [data-baseweb="tab-list"] {gap: 4px;}
    .stTabs [data-baseweb="tab"] {height: 40px; padding: 0 16px; font-size: 0.95rem;}
    .stButton button {border-radius: 8px;}
    .badge {display: inline-block; padding: 3px 10px; border-radius: 8px;
            font-size: 0.78rem; font-weight: 500;}
    .badge-foreclosure {background: #FCEBEB; color: #791F1F;}
    .badge-probate {background: #FAEEDA; color: #633806;}
    .badge-lispendens {background: #FBEAF0; color: #72243E;}
    .badge-tax {background: #EAF3DE; color: #27500A;}
    .badge-liens {background: #EEEDFE; color: #3C3489;}
    .badge-new {background: #E6F1FB; color: #0C447C;}
    .badge-pending {background: #FAEEDA; color: #633806;}
    .badge-contacted {background: #E2F0D9; color: #27500A;}
    .badge-scheduled {background: #EEEDFE; color: #3C3489;}
    .badge-closed {background: #F1EFE8; color: #2C2C2A;}
    </style>
    """,
    unsafe_allow_html=True,
)

# =========================================================================
# Authentication — single shared password
# =========================================================================
def check_password() -> bool:
    """Returns True if the user has entered a correct password."""

    def _password_entered():
        # Read the expected password from secrets, fall back to demo.
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

    # Login screen
    _, mid, _ = st.columns([1, 1.2, 1])
    with mid:
        st.markdown("# 🏠 101 Advisors")
        st.markdown("### Lead Generation Platform")
        st.markdown("Ingrese la contraseña del equipo para continuar:")
        st.text_input(
            "Password",
            type="password",
            on_change=_password_entered,
            key="password",
            label_visibility="collapsed",
        )
        if st.session_state.get("auth_error"):
            st.error("Contraseña incorrecta. Intentá de nuevo.")
        st.caption("MVP v0.1 · datos de demostración")
        st.caption("La contraseña por defecto es: `demo101` (se cambia antes de producción)")
    return False


if not check_password():
    st.stop()

# =========================================================================
# Data loading
# =========================================================================
@st.cache_data(ttl=300)
def load_data() -> pd.DataFrame:
    """Load leads from CSV. Once Google Sheets is wired up, swap this fn."""
    path = Path(__file__).parent / "data" / "sample_leads.csv"
    df = pd.read_csv(path, parse_dates=["first_seen", "last_updated"])
    df["full_address"] = df["property_address"] + ", " + df["city"] + " " + df["zip"].astype(str)
    df["owner_name"] = df["owner_first"] + " " + df["owner_last"]
    df["total_unpaid_taxes"] = df["unpaid_taxes_2024"].fillna(0) + df["unpaid_taxes_2025"].fillna(0)
    return df


def fmt_currency(value) -> str:
    if pd.isna(value):
        return "—"
    return f"${value:,.0f}"


def category_badge(cat: str) -> str:
    cls_map = {
        "Foreclosure": "badge-foreclosure",
        "Probate": "badge-probate",
        "Lis Pendens": "badge-lispendens",
        "Tax Delinquent": "badge-tax",
        "Liens": "badge-liens",
    }
    cls = cls_map.get(cat, "badge-new")
    return f'<span class="badge {cls}">{cat}</span>'


def status_badge(status: str) -> str:
    cls = "badge-" + status.lower().replace(" ", "")
    return f'<span class="badge {cls}">{status}</span>'


df = load_data()

# =========================================================================
# Header
# =========================================================================
hcol1, hcol2 = st.columns([4, 1])
with hcol1:
    st.title("101 Advisors · Distressed Property Leads")
    st.caption(
        f"Last refresh: {datetime.now().strftime('%Y-%m-%d %H:%M')} ET · "
        "Próximo refresh automático: mañana 6:00 AM"
    )
with hcol2:
    st.write("")
    bcol1, bcol2 = st.columns(2)
    with bcol1:
        if st.button("🔄 Refresh", use_container_width=True):
            st.cache_data.clear()
            st.rerun()
    with bcol2:
        if st.button("Logout", use_container_width=True):
            st.session_state.clear()
            st.rerun()

st.divider()

# =========================================================================
# Sidebar filters
# =========================================================================
with st.sidebar:
    st.markdown("### 🔍 Filtros")

    counties = st.multiselect(
        "County",
        options=["Miami-Dade", "Broward", "Palm Beach"],
        default=["Miami-Dade", "Broward", "Palm Beach"],
    )

    categories = st.multiselect(
        "Categoría",
        options=["Foreclosure", "Probate", "Lis Pendens", "Tax Delinquent", "Liens"],
        default=["Foreclosure", "Probate", "Lis Pendens", "Tax Delinquent", "Liens"],
    )

    property_types = st.multiselect(
        "Property type",
        options=["Single Family", "Multi Family", "Duplex", "Triplex", "Fourplex"],
        default=["Single Family", "Multi Family", "Duplex", "Triplex", "Fourplex"],
    )

    statuses = st.multiselect(
        "Status",
        options=["New", "Pending", "Contacted", "Scheduled", "Closed"],
        default=["New", "Pending", "Scheduled"],
    )

    st.markdown("---")

    max_equity_val = int(df["equity"].max())
    min_equity = st.slider(
        "Min equity",
        min_value=0,
        max_value=max_equity_val,
        value=0,
        step=10000,
        format="$%d",
    )

    st.markdown("---")
    st.caption("Los filtros se aplican a todas las vistas")
    st.caption(f"Total leads en sistema: **{len(df)}**")


# =========================================================================
# Apply filters
# =========================================================================
mask = (
    df["county"].isin(counties)
    & df["category"].isin(categories)
    & df["property_type"].isin(property_types)
    & df["status"].isin(statuses)
    & (df["equity"] >= min_equity)
)
filtered = df[mask].copy()

# =========================================================================
# KPIs
# =========================================================================
today = pd.Timestamp.today().normalize()
new_today_count = (filtered["first_seen"] >= today).sum()
pending_count = (filtered["status"].isin(["New", "Pending"])).sum()
contacted_week_count = (
    (filtered["status"] == "Contacted")
    & (filtered["last_updated"] >= today - pd.Timedelta(days=7))
).sum()
scheduled_count = (filtered["status"] == "Scheduled").sum()
avg_equity = filtered["equity"].mean() if len(filtered) > 0 else 0

k1, k2, k3, k4, k5 = st.columns(5)
k1.metric("New today", int(new_today_count))
k2.metric("Pending followup", int(pending_count))
k3.metric("Contacted this week", int(contacted_week_count))
k4.metric("Calls scheduled", int(scheduled_count))
k5.metric(
    "Avg equity",
    f"${avg_equity / 1000:.0f}K" if avg_equity else "—",
)

st.divider()

# =========================================================================
# Tabs: Today / Pipeline / History / Stats
# =========================================================================
today_df = filtered[filtered["first_seen"] >= today]
pipeline_df = filtered[filtered["status"].isin(["New", "Pending", "Scheduled"])]
history_df = filtered[filtered["status"].isin(["Contacted", "Closed"])]

t_today, t_pipe, t_hist, t_stats = st.tabs(
    [
        f"📍 Today ({len(today_df)})",
        f"⏳ Pipeline ({len(pipeline_df)})",
        f"✅ History ({len(history_df)})",
        "📊 Stats",
    ]
)


def render_table(view_df: pd.DataFrame, view_name: str):
    """Render filtered leads as an interactive table + detail panel."""
    if len(view_df) == 0:
        st.info("No hay leads que coincidan con los filtros actuales.")
        return

    # Show as styled dataframe with selectable row
    display = view_df.copy()
    display = display.sort_values(["first_seen", "equity"], ascending=[False, False])
    display["Address"] = display["full_address"]
    display["Category"] = display["category"]
    display["Owner"] = display["owner_name"]
    display["Phone"] = display["owner_phone"]
    display["Type"] = display["property_type"]
    display["Equity"] = display["equity"]
    display["Status"] = display["status"]
    display["Days in pipeline"] = (today - display["first_seen"]).dt.days

    st.markdown(
        f"**{len(display)} leads** · ordenados por más nuevo + mayor equity"
    )

    selection = st.dataframe(
        display[
            [
                "lead_id",
                "Address",
                "Category",
                "Owner",
                "Phone",
                "Type",
                "Equity",
                "Status",
                "Days in pipeline",
            ]
        ],
        column_config={
            "lead_id": st.column_config.TextColumn("ID", width="small"),
            "Address": st.column_config.TextColumn("Address", width="large"),
            "Category": st.column_config.TextColumn("Category", width="medium"),
            "Owner": st.column_config.TextColumn("Owner", width="medium"),
            "Phone": st.column_config.TextColumn("Phone", width="small"),
            "Type": st.column_config.TextColumn("Type", width="small"),
            "Equity": st.column_config.NumberColumn(
                "Equity", format="$%d", width="small"
            ),
            "Status": st.column_config.TextColumn("Status", width="small"),
            "Days in pipeline": st.column_config.NumberColumn(
                "Days", width="small"
            ),
        },
        hide_index=True,
        use_container_width=True,
        on_select="rerun",
        selection_mode="single-row",
        key=f"table_{view_name}",
    )

    # Action bar
    bcol1, bcol2, bcol3, _ = st.columns([1, 1, 1, 3])
    with bcol1:
        st.download_button(
            label="📥 Export CSV",
            data=display.to_csv(index=False).encode("utf-8"),
            file_name=f"101advisors_leads_{view_name}_{today.strftime('%Y%m%d')}.csv",
            mime="text/csv",
            use_container_width=True,
        )
    with bcol2:
        if st.button("✅ Mark contacted", key=f"contact_{view_name}", use_container_width=True):
            st.toast("(Demo) En producción esto actualiza el Sheet")
    with bcol3:
        if st.button("👤 Assign agent", key=f"assign_{view_name}", use_container_width=True):
            st.toast("(Demo) En producción abre selector de agente")

    # Detail panel
    if selection.selection.rows:
        idx = selection.selection.rows[0]
        lead = display.iloc[idx]
        st.divider()
        st.markdown(f"### 📋 Detalle del lead `{lead['lead_id']}`")

        d1, d2, d3 = st.columns(3)
        with d1:
            st.markdown("**Propiedad**")
            st.markdown(category_badge(lead["category"]), unsafe_allow_html=True)
            st.write("")
            st.write(f"📍 {lead['Address']}")
            st.write(f"🏠 {lead['Type']} · {lead['bedrooms']} bedrooms · {lead['units']} unit(s)")
            st.metric("Equity estimado", fmt_currency(lead["equity"]))

        with d2:
            st.markdown("**Owner**")
            st.write(f"👤 {lead['Owner']}")
            st.write(f"📞 {lead['Phone']}")
            st.write(f"✉️ {lead['owner_email']}")

        with d3:
            st.markdown("**Lender / Bank**")
            st.write(f"🏦 {lead['lender_name']}")
            st.write(f"📞 {lead['lender_phone']}")
            st.write(f"✉️ {lead['lender_email']}")
            st.caption(lead["bank_address"])

        st.divider()
        f1, f2, f3, f4 = st.columns(4)
        f1.metric("Outstanding debt", fmt_currency(lead["outstanding_debt"]))
        f2.metric("Unpaid taxes 2024", fmt_currency(lead["unpaid_taxes_2024"]))
        f3.metric("Unpaid taxes 2025", fmt_currency(lead["unpaid_taxes_2025"]))
        f4.metric("Status", lead["Status"])

        if lead["notes"] and not pd.isna(lead["notes"]):
            st.markdown(f"**Notas:** {lead['notes']}")
        if lead["assigned_to"] and not pd.isna(lead["assigned_to"]):
            st.caption(f"Asignado a: {lead['assigned_to']}")


with t_today:
    render_table(today_df, "today")

with t_pipe:
    render_table(pipeline_df, "pipeline")

with t_hist:
    render_table(history_df, "history")

with t_stats:
    if len(filtered) == 0:
        st.info("No hay datos para mostrar con los filtros actuales.")
    else:
        st.markdown("### Distribución por categoría")
        cat_counts = filtered["category"].value_counts().reset_index()
        cat_counts.columns = ["Categoría", "Leads"]
        c1, c2 = st.columns(2)
        with c1:
            st.bar_chart(cat_counts, x="Categoría", y="Leads", height=280)
        with c2:
            county_counts = filtered["county"].value_counts().reset_index()
            county_counts.columns = ["County", "Leads"]
            st.markdown("### Distribución por County")
            st.bar_chart(county_counts, x="County", y="Leads", height=280)

        st.divider()
        st.markdown("### Status pipeline")
        status_counts = filtered["status"].value_counts().reset_index()
        status_counts.columns = ["Status", "Leads"]
        st.bar_chart(status_counts, x="Status", y="Leads", height=240)

        st.divider()
        st.markdown("### Top 10 leads por equity")
        top = (
            filtered.nlargest(10, "equity")[
                ["lead_id", "full_address", "category", "owner_name", "equity"]
            ]
            .rename(
                columns={
                    "lead_id": "ID",
                    "full_address": "Address",
                    "category": "Category",
                    "owner_name": "Owner",
                    "equity": "Equity",
                }
            )
        )
        st.dataframe(
            top,
            hide_index=True,
            use_container_width=True,
            column_config={
                "Equity": st.column_config.NumberColumn("Equity", format="$%d")
            },
        )

# =========================================================================
# Footer
# =========================================================================
st.divider()
fcol1, fcol2 = st.columns([3, 1])
with fcol1:
    st.caption(
        "101 Advisors · Lead Generation MVP v0.1 · "
        "Datos de prueba. En producción los leads vienen de Miami-Dade Clerk, "
        "Broward Clerk, Palm Beach Clerk + Tax Collectors + Property Appraisers + BatchSkipTracing."
    )
with fcol2:
    st.caption(f"Total leads: **{len(df)}** · filtrados: **{len(filtered)}**")
