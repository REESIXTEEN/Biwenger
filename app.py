import streamlit as st
import requests
import pandas as pd
import statistics
import json
import os
import time
from datetime import datetime

st.set_page_config(page_title="Biwenger Analyzer", page_icon="⚽", layout="wide")

# ──────────────────────────────────────────────
# Helpers
# ──────────────────────────────────────────────
POSITION_MAP = {1: "Portero", 2: "Defensa", 3: "Centro", 4: "Delantero"}
CONFIG_PATH = os.path.join(os.path.dirname(__file__), "config.json")


def format_price(x):
    """Format an integer price with dots as thousands separator."""
    try:
        return f"{int(x):,}".replace(",", ".")
    except (ValueError, TypeError):
        return str(x)


def compute_player_stats(fitness):
    """From a fitness array, compute recent-match statistics."""
    if not fitness:
        fitness = []
    last_5 = fitness[-8:]
    played_5 = sum(1 for m in last_5 if isinstance(m, (int, float)))

    last_10 = fitness[-10:]
    pts_10 = sum(m for m in last_10 if isinstance(m, (int, float)))

    # Median over the last 8 matches: if the player didn't play, count as 0
    last_5_pts = [m if isinstance(m, (int, float)) else 0 for m in last_5]
    median = statistics.median(last_5_pts) if last_5_pts else 0

    return played_5, pts_10, median


def load_config():
    """Load saved credentials from Streamlit secrets (cloud) or config.json (local)."""
    # 1. Try to load from Streamlit Secrets (used in Cloud)
    try:
        if "token" in st.secrets and "league_id" in st.secrets:
            return {
                "token": st.secrets["token"],
                "league_id": str(st.secrets["league_id"]),
                "user_id": str(st.secrets.get("user_id", ""))
            }
    except Exception:
        pass # Ignore errors if not running in a context where secrets are available

    # 2. Fall back to local config.json
    if os.path.exists(CONFIG_PATH):
        with open(CONFIG_PATH, "r") as f:
            return json.load(f)
            
    return None


# ──────────────────────────────────────────────
# Data fetching – PUBLIC (no auth needed)
# ──────────────────────────────────────────────
@st.cache_data(ttl=3600)
def fetch_all_players():
    """Fetch the public list of all La Liga players (no auth required)."""
    url = "https://cf.biwenger.com/api/v2/competitions/la-liga/data?lang=es&score=2"
    headers = {
        "Referer": "https://biwenger.as.com/players",
        "User-Agent": "Mozilla/5.0",
        "Accept": "application/json",
    }
    resp = requests.get(url, headers=headers)
    resp.raise_for_status()
    data = resp.json()
    players_dict = data.get("data", {}).get("players", {})

    rows = []
    for pid, p in players_dict.items():
        played_5, pts_10, median = compute_player_stats(p.get("fitness", []))
        rows.append({
            "ID": int(pid),
            "Nombre": p.get("name"),
            "Puntos": p.get("points", 0),
            "Precio": p.get("price", 0),
            "Posición": POSITION_MAP.get(p.get("position"), p.get("position")),
            "Estado": p.get("status"),
            "Jugados últimos 5": played_5,
            "Puntos últimos 10": pts_10,
            "Mediana": median,
        })
    return pd.DataFrame(rows)


# ──────────────────────────────────────────────
# Data fetching – AUTHENTICATED
# ──────────────────────────────────────────────
def biwenger_login(email: str, password: str):
    """Login to Biwenger and return the Bearer token."""
    url = "https://biwenger.as.com/api/v2/auth/login"
    resp = requests.post(url, json={"email": email, "password": password},
                         headers={"Content-Type": "application/json"})
    resp.raise_for_status()
    data = resp.json()
    return data.get("token") or data.get("login", {}).get("token")


def _auth_headers(token: str, league_id: str, user_id: str = ""):
    h = {
        "Content-Type": "application/json",
        "Authorization": f"Bearer {token}",
        "x-lang": "es",
        "x-league": str(league_id),
        "x-version": "658",
        "User-Agent": "Mozilla/5.0",
        "Accept": "application/json, text/plain, */*",
        "Referer": "https://biwenger.as.com/",
    }
    if user_id:
        h["x-user"] = str(user_id)
    return h


def fetch_market(token: str, league_id: str, user_id: str = ""):
    """Fetch the current market (sales) of the league."""
    url = "https://biwenger.as.com/api/v2/market"
    headers = _auth_headers(token, league_id, user_id)
    resp = requests.get(url, headers=headers)
    resp.raise_for_status()
    return resp.json()


def fetch_user_players(token: str, league_id: str, user_id: str = ""):
    """Fetch the current user's ID and players."""
    url = "https://biwenger.as.com/api/v2/user?fields=*,players(*,fitness,team,owner)"
    headers = _auth_headers(token, league_id, user_id)
    resp = requests.get(url, headers=headers)
    resp.raise_for_status()
    return resp.json()


def fetch_league_data(token: str, league_id: str, user_id: str = ""):
    """Fetch league standings (user IDs, names, points)."""
    url = "https://biwenger.as.com/api/v2/league?fields=*,standings,group"
    headers = _auth_headers(token, league_id, user_id)
    resp = requests.get(url, headers=headers)
    resp.raise_for_status()
    return resp.json()


def fetch_rival_players(token: str, league_id: str, user_id: str, rival_id: int):
    """Fetch a specific rival's players with ownership and clause info."""
    url = f"https://biwenger.as.com/api/v2/user/{rival_id}?fields=*,players(*,fitness,team,owner)"
    headers = _auth_headers(token, league_id, user_id)
    resp = requests.get(url, headers=headers)
    resp.raise_for_status()
    return resp.json()


# ──────────────────────────────────────────────
# Session state initialization – auto-load config
# ──────────────────────────────────────────────
if "token" not in st.session_state:
    config = load_config()
    if config:
        st.session_state.token = config.get("token")
        st.session_state.league_id = config.get("league_id")
        st.session_state.my_user_id = config.get("user_id")
    else:
        st.session_state.token = None
        st.session_state.league_id = None
        st.session_state.my_user_id = None


# ──────────────────────────────────────────────
# Sidebar – Login (hidden inside an expander)
# ──────────────────────────────────────────────
with st.sidebar:
    if st.session_state.token:
        st.success("✅ Conectado a Biwenger")
        st.caption(f"Liga: {st.session_state.league_id}")
        if st.button("Desconectar"):
            st.session_state.token = None
            st.session_state.league_id = None
            st.session_state.my_user_id = None
            st.rerun()
    
    with st.expander("🔐 Login manual", expanded=st.session_state.token is None):
        with st.form("login_form"):
            email = st.text_input("Email")
            password = st.text_input("Contraseña", type="password")
            league_id = st.text_input("League ID (x-league)")
            submitted = st.form_submit_button("Conectar")
        if submitted:
            if not email or not password or not league_id:
                st.error("Rellena todos los campos.")
            else:
                try:
                    token = biwenger_login(email, password)
                    if token:
                        st.session_state.token = token
                        st.session_state.league_id = league_id
                        try:
                            user_data = fetch_user_players(token, league_id)
                            st.session_state.my_user_id = str(user_data.get("data", {}).get("id", ""))
                        except Exception:
                            pass
                        st.rerun()
                    else:
                        st.error("No se pudo obtener el token.")
                except Exception as e:
                    st.error(f"Error: {e}")


# ──────────────────────────────────────────────
# Main Content
# ──────────────────────────────────────────────
st.title("⚽ Biwenger Analyzer")

# Fetch public data once (used by both tabs)
with st.spinner("Conectando con Biwenger..."):
    try:
        df = fetch_all_players()
    except Exception as e:
        st.error(f"Error al obtener los datos de Biwenger: {e}")
        df = pd.DataFrame()

if not df.empty:
    # Ensure Posición is always string to avoid ArrowTypeError
    df["Posición"] = df["Posición"].astype(str)

    # Calculate derived metrics
    precio_m = df["Precio"] / 1_000_000
    df["Mediana por Millón"] = (df["Mediana"] / precio_m.replace(0, pd.NA)).fillna(0).round(2)
    df["Precio (€)"] = df["Precio"].apply(format_price)

    # Score Top (needed by public tab)
    max_p = df["Puntos"].max() or 1
    max_m = df["Mediana"].max() or 1
    df["Score Top"] = (((df["Puntos"] / max_p) + (df["Mediana"] / max_m)) / 2 * 10).round(2)

# ── TABS ──
if st.session_state.token:
    tab_public, tab_liga = st.tabs(["📊 Análisis General", "🏟️ Tu Liga"])
else:
    tab_public, = st.tabs(["📊 Análisis General"])
    tab_liga = None

# ──────────────────────────────────────────────
# TAB 1: Análisis General (público)
# ──────────────────────────────────────────────
with tab_public:
    if not df.empty:
        # ── TABLE 1: Jugadores Top ──
        st.subheader("Jugadores Top (Puntos × Mediana)")
        df_top = df.sort_values("Score Top", ascending=False).reset_index(drop=True)

        st.dataframe(
            df_top[["Nombre", "Score Top", "Puntos", "Mediana", "Precio (€)", "Posición", "Estado"]],
            use_container_width=True, hide_index=True,
            column_config={
                "Score Top": st.column_config.NumberColumn("Score", help="Puntuación combinada (sobre 10)"),
            },
        )

        st.divider()

        # ── TABLE 2: Jugadores Calientes ──
        st.subheader("🔥 Jugadores Calientes (Últimos 10 Partidos)")
        df_hot = df[df["Puntos últimos 10"] > 0].sort_values("Puntos últimos 10", ascending=False).reset_index(drop=True)
        st.dataframe(
            df_hot[["Nombre", "Puntos últimos 10", "Precio (€)", "Posición", "Estado"]],
            use_container_width=True, hide_index=True,
            column_config={
                "Puntos últimos 10": st.column_config.NumberColumn("Pts (10)", help="Puntos en los últimos 10 partidos"),
            },
        )

        st.divider()

        # ── TABLE 3: Calidad / Precio ──
        st.subheader("💰 Jugadores Top Calidad/Precio (Mediana)")
        df_val = df[(df["Precio"] > 0) & (df["Puntos"] >= 10) & (df["Jugados últimos 5"] >= 4)]
        df_val = df_val.sort_values("Mediana por Millón", ascending=False).reset_index(drop=True)
        st.dataframe(
            df_val[["Nombre", "Mediana por Millón", "Mediana", "Jugados últimos 5", "Precio (€)", "Posición", "Estado"]],
            use_container_width=True, hide_index=True,
            column_config={
                "Mediana por Millón": st.column_config.NumberColumn("Med / M€", help="Mediana de puntos por millón de euros"),
                "Jugados últimos 5": st.column_config.NumberColumn("Jugados", help="Jugados de los últimos 5"),
            },
        )

        st.caption(f"Total de jugadores analizados: {len(df)}")
    else:
        st.warning("No se pudieron cargar los jugadores.")

# ──────────────────────────────────────────────
# TAB 2: Tu Liga (autenticado)
# ──────────────────────────────────────────────
if tab_liga is not None:
    with tab_liga:
        token = st.session_state.token
        lid = st.session_state.league_id
        uid = st.session_state.my_user_id or ""

        # Build a lookup from the public data
        if not df.empty:
            player_lookup = df.set_index("ID").to_dict("index")
        else:
            player_lookup = {}

        # ── MARKET (solo jugadores libres) ──
        st.subheader("🛒 Mercado del Día (Jugadores Libres)")
        try:
            market_data = fetch_market(token, lid, uid)
            sales = market_data.get("data", {}).get("sales", [])
            free_sales = [s for s in sales if s.get("user") is None]
            if free_sales:
                market_rows = []
                for sale in free_sales:
                    pid = sale.get("player", {}).get("id") if isinstance(sale.get("player"), dict) else sale.get("player")
                    sell_price = sale.get("price", 0)

                    info = player_lookup.get(pid, {})
                    name = info.get("Nombre", f"Jugador #{pid}")
                    puntos = info.get("Puntos", 0)
                    mediana = info.get("Mediana", 0)
                    pos = info.get("Posición", "")
                    market_price = info.get("Precio", 0)
                    estado = info.get("Estado", "")

                    market_rows.append({
                        "Nombre": name,
                        "Precio (€)": format_price(sell_price),
                        "Valor Mercado (€)": format_price(market_price),
                        "Puntos": puntos,
                        "Mediana": mediana,
                        "Posición": str(pos),
                        "Estado": estado,
                    })

                df_market = pd.DataFrame(market_rows).sort_values("Mediana", ascending=False).reset_index(drop=True)

                st.dataframe(
                    df_market[["Nombre", "Precio (€)", "Valor Mercado (€)", "Puntos", "Mediana", "Posición", "Estado"]],
                    use_container_width=True, hide_index=True,
                    column_config={
                        "Precio (€)": st.column_config.TextColumn("Precio", help="Precio del jugador libre"),
                        "Valor Mercado (€)": st.column_config.TextColumn("Valor Mercado", help="Valor oficial de mercado"),
                    },
                )
                st.caption(f"Jugadores libres en el mercado: {len(df_market)}")
            else:
                st.info("No hay jugadores libres en el mercado ahora mismo.")
        except requests.exceptions.HTTPError as e:
            st.error(f"Error al obtener el mercado: {e}")
        except Exception as e:
            st.error(f"Error inesperado al obtener el mercado: {e}")

        st.divider()

        # ── RIVAL PLAYERS ──
        st.subheader("👥 Jugadores de Rivales")
        try:
            league_data = fetch_league_data(token, lid, uid)
            standings = league_data.get("data", {}).get("standings", [])

            rivals = [s for s in standings if str(s.get("id")) != str(uid)]

            if rivals:
                rival_rows = []
                progress = st.progress(0, text="Cargando jugadores de rivales...")
                for i, rival in enumerate(rivals):
                    rival_id = rival.get("id")
                    rival_name = rival.get("name", f"User #{rival_id}")
                    try:
                        rival_data = fetch_rival_players(token, lid, uid, rival_id)
                        players = rival_data.get("data", {}).get("players", [])
                        now_ts = int(time.time())
                        for pl in players:
                            if isinstance(pl, dict):
                                pid = pl.get("id")
                                owner = pl.get("owner", {})
                                clause = owner.get("clause", 0) if isinstance(owner, dict) else 0
                                locked_until = owner.get("clauseLockedUntil", 0) if isinstance(owner, dict) else 0
                            else:
                                pid = pl
                                clause = 0
                                locked_until = 0

                            if locked_until and locked_until > now_ts:
                                unlock_date = datetime.fromtimestamp(locked_until).strftime("%d/%m")
                                disponible = f"🔒 hasta {unlock_date}"
                            else:
                                disponible = "✅ Sí"

                            info = player_lookup.get(pid, {})
                            name = info.get("Nombre", f"Jugador #{pid}")
                            puntos = info.get("Puntos", 0)
                            mediana = info.get("Mediana", 0)
                            pos = info.get("Posición", "")
                            market_price = info.get("Precio", 0)

                            rival_rows.append({
                                "Rival": rival_name,
                                "Nombre": name,
                                "Cláusula (€)": format_price(clause) if clause else "—",
                                "Disponible": disponible,
                                "Valor Mercado (€)": format_price(market_price),
                                "Puntos": puntos,
                                "Mediana": mediana,
                                "Posición": str(pos),
                            })
                    except Exception:
                        pass
                    progress.progress((i + 1) / len(rivals), text=f"Cargando: {rival_name}...")
                progress.empty()

                if rival_rows:
                    df_rivals = pd.DataFrame(rival_rows)

                    rival_names = sorted(df_rivals["Rival"].unique())
                    selected_rival = st.selectbox("Filtrar por rival:", ["Todos"] + list(rival_names))
                    if selected_rival != "Todos":
                        df_rivals = df_rivals[df_rivals["Rival"] == selected_rival]

                    df_rivals = df_rivals.sort_values("Mediana", ascending=False).reset_index(drop=True)

                    st.dataframe(
                        df_rivals,
                        use_container_width=True, hide_index=True,
                        column_config={
                            "Cláusula (€)": st.column_config.TextColumn("Cláusula", help="Cláusula de rescisión del jugador"),
                            "Valor Mercado (€)": st.column_config.TextColumn("Valor Mercado"),
                        },
                    )
                    st.caption(f"Jugadores de rivales mostrados: {len(df_rivals)}")
                else:
                    st.info("No se encontraron jugadores de rivales.")
            else:
                st.info("No se pudieron obtener los standings de la liga.")
        except requests.exceptions.HTTPError as e:
            st.error(f"Error al obtener datos de rivales: {e}")
        except Exception as e:
            st.error(f"Error inesperado: {e}")
