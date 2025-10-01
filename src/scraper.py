# scraper.py
# requirements: requests beautifulsoup4 pandas
import os, re, time, csv, argparse
import requests
import pandas as pd
from bs4 import BeautifulSoup, NavigableString
from urllib.parse import urljoin, urlparse
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry
from concurrent.futures import ThreadPoolExecutor, as_completed

BASE = "https://playshoptitans.com"

# --- SEMILLAS (puedes añadir más cuando quieras) ---
LIST_STARTS = [
    # --- WEAPONS ---
    "https://playshoptitans.com/blueprints/weapons/ws",  # espadas
    "https://playshoptitans.com/blueprints/weapons/wa",  # hachas
    "https://playshoptitans.com/blueprints/weapons/wd",  # cuchillos
    "https://playshoptitans.com/blueprints/weapons/wm",  # mazas
    "https://playshoptitans.com/blueprints/weapons/wp",  # lanzas
    "https://playshoptitans.com/blueprints/weapons/wb",  # arcos
    "https://playshoptitans.com/blueprints/weapons/wt",  # varitas

    # --- ARMOR ---
    "https://playshoptitans.com/blueprints/armor/ah",    # armadura pesada
    "https://playshoptitans.com/blueprints/armor/am",    # armadura ligera
    "https://playshoptitans.com/blueprints/armor/al",    # ropa
    "https://playshoptitans.com/blueprints/armor/hh",    # casco
    "https://playshoptitans.com/blueprints/armor/hm",    # sombrero (picado)
    "https://playshoptitans.com/blueprints/armor/hl",    # sombrero de mago
    "https://playshoptitans.com/blueprints/armor/gh",    # guanteletes
    "https://playshoptitans.com/blueprints/armor/gl",    # guantes
    "https://playshoptitans.com/blueprints/armor/bh",    # calzado pesado
    "https://playshoptitans.com/blueprints/armor/bl",    # calzado ligero

    # --- ACCESSORIES ---
    "https://playshoptitans.com/blueprints/accessories/uh",  # medicina herbaria
    "https://playshoptitans.com/blueprints/accessories/up",  # poción
    "https://playshoptitans.com/blueprints/accessories/us",  # pergaminos
    "https://playshoptitans.com/blueprints/accessories/xs",  # escudos
    "https://playshoptitans.com/blueprints/accessories/xr",  # anillo
    "https://playshoptitans.com/blueprints/accessories/xa",  # colgante
    "https://playshoptitans.com/blueprints/accessories/xx",  # canción de aura
    "https://playshoptitans.com/blueprints/accessories/fm",  # comida

    # --- STONES ---
    "https://playshoptitans.com/blueprints/stones/xu",   # piedra rúnica
    "https://playshoptitans.com/blueprints/stones/xm",   # piedra de la luna

    # --- ENCHANTMENTS ---
    "https://playshoptitans.com/blueprints/enchantments/fire",   # fuego
    "https://playshoptitans.com/blueprints/enchantments/water",  # agua
    "https://playshoptitans.com/blueprints/enchantments/earth",  # tierra
    "https://playshoptitans.com/blueprints/enchantments/air",    # aire
    "https://playshoptitans.com/blueprints/enchantments/light",  # luz
    "https://playshoptitans.com/blueprints/enchantments/dark",   # noche
]

SUBTYPE_MAP_EN = {
    # weapons
    "ws": "swords", "wa": "axes", "wd": "daggers", "wm": "maces",
    "wp": "spears", "wb": "bows", "wt": "wands",
    # armor
    "ah": "heavy armor", "am": "light armor", "al": "clothes",
    "hh": "helmet", "hm": "hat", "hl": "wizard hat",
    "gh": "gauntlets", "gl": "gloves", "bh": "heavy footwear", "bl": "light footwear",
    # accessories
    "uh": "herbal medicine", "up": "potion", "us": "scrolls", "xs": "shields",
    "xr": "ring", "xa": "amulet", "xx": "aura song", "fm": "food",
    # stones
    "xu": "runic stone", "xm": "moonstone",
    # enchantments
    "fire":"fire","water":"water","earth":"earth","air":"air","light":"light","dark":"dark",
}
SUBTYPE_MAP_ES = {
    # weapons
    "ws": "espadas", "wa": "hachas", "wd": "cuchillos", "wm": "mazas",
    "wp": "lanzas", "wb": "arcos", "wt": "varitas",
    # armor
    "ah": "armadura pesada", "am": "armadura ligera", "al": "ropa",
    "hh": "casco", "hm": "sombrero", "hl": "sombrero de mago",
    "gh": "guanteletes", "gl": "guantes", "bh": "calzado pesado", "bl": "calzado ligero",
    # accessories
    "uh": "medicina herbaria", "up": "poción", "us": "pergaminos", "xs": "escudos",
    "xr": "anillo", "xa": "colgante", "xx": "canción de aura", "fm": "comida",
    # stones
    "xu": "piedra rúnica", "xm": "piedra de la luna",
    # enchantments
    "fire":"fuego","water":"agua","earth":"tierra","air":"aire","light":"luz","dark":"noche",
}

# UA de navegador para evitar HTML capado
HEADERS = {"User-Agent": "Mozilla/5.0"}

RX_VALUE = re.compile(r'\bValue\b[:\s]*([0-9][\d,\.]*)', re.I)
RX_TIME  = re.compile(r'\bCrafting\s*Time\b[:\s]*([0-9hms\s:]+)', re.I)
RX_MXP   = re.compile(r'\bMerchant\s*XP\b[:\s]*([0-9][\d,\.]*)', re.I)
RX_WXP   = re.compile(r'\bWorker\s*XP\b[:\s]*([0-9][\d,\.]*)', re.I)

# --- TIER robusto ---
RX_TIER_CELL     = re.compile(r'^\s*T(?:ier)?\s*:?$', re.I)
RX_TIER_FROM_H1  = re.compile(r'^\s*T(?:ier)?\s*[:\-]?\s*([0-9IVXLC]+)\b', re.I)
RX_TIER_IN_PATH  = re.compile(r'/t(\d{1,2})', re.I)
RX_TIER_BADGE    = re.compile(r'\bT(?:ier)?\s*([0-9]{1,2}|[IVXLC]+)\b', re.I)

# --- PREMIUM (paquetes/monedas antiguas/antigüedades) ---
RX_PREMIUM_SECTION   = re.compile(r'(Fuentes\s+premium|Premium\s+Sources)', re.I)
RX_PREMIUM_PACKAGE   = re.compile(r'\b(Paquete|Package)\b', re.I)
RX_PREMIUM_ANC_COIN  = re.compile(r'\b(Ficha\s+antigua|Ancient\s+Coin)\b', re.I)
RX_PREMIUM_ANTIQUES  = re.compile(r'\b(tienda\s+de\s+antig(?:ü|u)edades|Antique\s+store)\b', re.I)

def roman_to_int(s):
    if not s: return None
    s = s.upper()
    vals = dict(I=1,V=5,X=10,L=50,C=100,D=500,M=1000)
    total=0; prev=0
    for ch in reversed(s):
        v = vals.get(ch,0)
        if v < prev: total -= v
        else: total += v; prev = v
    return total or None

def normalize_tier(t):
    if t is None: return None
    try: n = int(t)
    except Exception: return None
    return n if 1 <= n <= 15 else None

def num_or_roman_to_int(s):
    if not s: return None
    s = str(s).strip()
    m = re.search(r'([0-9]{1,2}|[IVXLC]+)', s, re.I)
    if not m: return None
    g = m.group(1)
    return int(g) if g.isdigit() else roman_to_int(g)

def detect_premium(soup, full_text: str):
    """
    Devuelve (is_premium, tags) detectando fuentes premium.
    tags ∈ {'package', 'ancient_coin', 'antiques_shop'}
    """
    tags = set()
    # Marcamos si aparecen términos de esa sección
    if RX_PREMIUM_SECTION.search(full_text) or \
       RX_PREMIUM_PACKAGE.search(full_text) or \
       RX_PREMIUM_ANC_COIN.search(full_text) or \
       RX_PREMIUM_ANTIQUES.search(full_text):
        if RX_PREMIUM_PACKAGE.search(full_text):
            tags.add("package")
        if RX_PREMIUM_ANC_COIN.search(full_text):
            tags.add("ancient_coin")
        if RX_PREMIUM_ANTIQUES.search(full_text):
            tags.add("antiques_shop")
    return (len(tags) > 0), sorted(tags)

# ---------- Session con reintentos ----------
def setup_session():
    s = requests.Session()
    retries = Retry(
        total=3, backoff_factor=0.3,
        status_forcelist=[429, 500, 502, 503, 504],
        allowed_methods=frozenset(["GET"])
    )
    adapter = HTTPAdapter(max_retries=retries, pool_connections=10, pool_maxsize=10)
    s.mount("https://", adapter)
    s.mount("http://", adapter)
    s.headers.update(HEADERS)
    return s

def _soup(session, url):
    r = session.get(url, timeout=20)
    r.raise_for_status()
    return BeautifulSoup(r.text, "html.parser")

def _clean_int(s):
    if not s: return None
    s = s.replace(',', '').replace(' ', '')
    try: return int(float(s))
    except: return None

# ---------- Link discovery ----------
def collect_links(session):
    links = set()
    for list_url in LIST_STARTS:
        print(f"[COLLECT] Semilla -> {list_url}")
        soup = _soup(session, list_url)
        for a in soup.select('a[href]'):
            href = a['href']
            if '/blueprints/' not in href:
                continue
            url = urljoin(BASE, href)
            path = urlparse(url).path.strip('/').split('/')
            # esperamos /blueprints/<cat>/<code o texto>/<slug>
            if len(path) >= 4 and path[0] == 'blueprints':
                links.add(url)
    links = sorted(links)
    print(f"[COLLECT] Blueprints únicos: {len(links)}")
    return links

# ---------- Tier extractor ----------
def extract_tier(soup, url):
    """
    Prioridad:
    0) Burbuja numérica del tier en ficha: cualquier [class*="tierValue"]
    0b) Texto "Tier N ..." en [class*="itemTierType"]
    1) Tabla/lista <th>Tier</th><td>...</td> o <dt>Tier</dt><dd>...</dd>
    2) H1 que empieza por "Tier N ..."
    3) Fallback por URL '/tNN'
    """
    # 0) burbuja numérica
    bubble = soup.select_one('[class*="tierValue"]')
    if bubble:
        txt = bubble.get_text(" ", strip=True)
        m = re.search(r'([0-9]{1,2})', txt)
        if m:
            val = normalize_tier(int(m.group(1)))
            if val is not None:
                return val, "tierValue"

    # 0b) texto tipo "Tier 3 Helmet"
    badge = soup.select_one('[class*="itemTierType"]')
    if badge:
        txt = badge.get_text(" ", strip=True)
        m = RX_TIER_BADGE.search(txt)
        if m:
            raw = m.group(1)
            val = normalize_tier(int(raw)) if raw.isdigit() else normalize_tier(roman_to_int(raw))
            if val is not None:
                return val, "itemTierType"

    # 1) th/td o dt/dd
    for lab in soup.find_all(["th", "td", "dt"]):
        txt = lab.get_text(" ", strip=True)
        if not txt:
            continue
        if RX_TIER_CELL.match(txt):
            sib = lab.find_next_sibling(["td", "dd"])
            if sib:
                val = num_or_roman_to_int(sib.get_text(" ", strip=True))
                val = normalize_tier(val)
                if val is not None:
                    return val, "table"

    # 2) H1 que empieza por "Tier ..."
    h1 = soup.find("h1")
    if h1:
        m = RX_TIER_FROM_H1.search(h1.get_text(" ", strip=True))
        if m:
            val = num_or_roman_to_int(m.group(1))
            val = normalize_tier(val)
            if val is not None:
                return val, "h1"

    # 3) Fallback URL
    m2 = RX_TIER_IN_PATH.search(url)
    if m2:
        val = normalize_tier(int(m2.group(1)))
        if val is not None:
            return val, "url"

    return None, "unknown"

# ---------- Parser de detalle ----------
def parse_blueprint(session, url):
    soup = _soup(session, url)
    text = soup.get_text(" ", strip=True)

    # Premium
    is_premium, premium_tags = detect_premium(soup, text)

    # Nombre
    h1 = soup.find('h1')
    name = h1.get_text(strip=True) if h1 else None

    # Partes de la URL -> category + subtype
    parts = urlparse(url).path.strip('/').split('/')
    category = parts[1] if len(parts) > 1 else None
    subtype  = parts[2] if len(parts) > 2 else None
    subtype_en = SUBTYPE_MAP_EN.get(subtype, subtype)
    subtype_es = SUBTYPE_MAP_ES.get(subtype, subtype)

    # Tier
    tier, tier_source = extract_tier(soup, url)
    tier = normalize_tier(tier)

    # Stats
    value = _clean_int((RX_VALUE.search(text) or [None, None])[1])
    ctime = (RX_TIME.search(text)  or [None, None])[1]
    mxp   = _clean_int((RX_MXP.search(text)  or [None, None])[1])
    wxp   = _clean_int((RX_WXP.search(text)  or [None, None])[1])

    return dict(
        name=name, url=url, category=category,
        subtype=subtype, subtype_name_en=subtype_en, subtype_name_es=subtype_es,
        tier=tier, tier_source=tier_source,
        value=value, crafting_time=ctime, merchant_xp=mxp, worker_xp=wxp,
        # nuevos:
        is_premium=is_premium,
        premium_tags=",".join(premium_tags),
    )

# ---------- Runner con modo rápido / concurrencia / caché ----------
def run_scraper(
    outfile="datoscsv.csv",
    pause=0.0,
    limit_links=None,         # e.g., 80 para pruebas rápidas
    max_workers=1,            # >1 activa concurrencia
    skip_existing=True        # salta URLs ya presentes en outfile
):
    session = setup_session()
    links = collect_links(session)
    if not links:
        print("[SCRAPER] No se encontraron enlaces desde las semillas.")
        return pd.DataFrame()

    if limit_links:
        links = links[:int(limit_links)]
        print(f"[SCRAPER] Modo rápido: limit_links={limit_links} -> {len(links)} enlaces.")

    # caché básica: salta URLs ya en el CSV
    seen = set()
    existing_df = None
    if skip_existing and os.path.exists(outfile):
        try:
            existing_df = pd.read_csv(outfile)
            if "url" in existing_df.columns:
                seen = set(existing_df["url"].dropna().astype(str).values)
                print(f"[CACHE] Saltando {len(seen)} URLs ya scrapeadas.")
        except Exception as e:
            print(f"[CACHE] No se pudo leer {outfile}: {e}")

    targets = [u for u in links if u not in seen]
    if not targets:
        print("[SCRAPER] No hay URLs nuevas para procesar.")
        return existing_df if existing_df is not None else pd.DataFrame()

    rows = []
    errors = 0

    def _work(url):
        try:
            return parse_blueprint(session, url)
        except Exception as e:
            return {"__error__": f"{url} -> {e}"}

    if max_workers > 1:
        print(f"[SCRAPER] Concurrencia: max_workers={max_workers}")
        with ThreadPoolExecutor(max_workers=max_workers) as ex:
            futs = {ex.submit(_work, url): url for url in targets}
            for i, fut in enumerate(as_completed(futs), 1):
                rec = fut.result()
                if "__error__" in rec:
                    errors += 1
                    print(f"[WARN] {rec['__error__']}")
                else:
                    rows.append(rec)
                if pause:
                    time.sleep(pause)
                if i % 20 == 0:
                    print(f"[PROGRESS] {i}/{len(targets)}")
    else:
        for i, url in enumerate(targets, 1):
            rec = _work(url)
            if "__error__" in rec:
                errors += 1
                print(f"[WARN] {rec['__error__']}")
            else:
                rows.append(rec)
            if pause:
                time.sleep(pause)
            if i % 20 == 0:
                print(f"[PROGRESS] {i}/{len(targets)}")

    new_df = pd.DataFrame(rows)
    if not new_df.empty:
        new_df = new_df.dropna(subset=["name"]).drop_duplicates(subset=["name","url"])
    # fusiona con existente
    if existing_df is not None and not existing_df.empty:
        df = pd.concat([existing_df, new_df], ignore_index=True)
        df = df.drop_duplicates(subset=["name","url"])
    else:
        df = new_df

    df.to_csv(outfile, index=False, encoding="utf-8")
    print(f"[SCRAPER] Guardado {outfile} con {len(df)} filas (nuevas: {len(new_df)}, errores: {errors})")
    return df

# ---- CLI simple para pruebas rápidas ----
if __name__ == "__main__":
    ap = argparse.ArgumentParser(description="Shop Titans Scraper")
    ap.add_argument("--out", default="datoscsv.csv")
    ap.add_argument("--limit", type=int, default=None, help="Límite de enlaces a procesar")
    ap.add_argument("--workers", type=int, default=1, help="Número de hilos (1 = secuencial)")
    ap.add_argument("--pause", type=float, default=0.0, help="Pausa entre items (seg)")
    ap.add_argument("--no-skip", action="store_true", help="No saltar URLs ya presentes en el CSV")
    args = ap.parse_args()

    run_scraper(
        outfile=args.out,
        pause=args.pause,
        limit_links=args.limit,
        max_workers=args.workers,
        skip_existing=not args.no_skip
    )
