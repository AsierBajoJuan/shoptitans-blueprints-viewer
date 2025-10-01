# gui.py
# requirements: pandas xlsxwriter requests beautifulsoup4
import os, sys, webbrowser, threading
from datetime import datetime
import pandas as pd
import tkinter as tk
from tkinter import ttk, messagebox, filedialog



# ---------- import robusto del scraper ----------
try:
    # si se ejecuta como paquete: python -m src.gui
    from . import scraper
except Exception:
    # si se ejecuta como script: python src/gui.py
    import scraper

# ---------- paths base / data / assets ----------
def _app_base_dir() -> str:
    # PyInstaller
    if getattr(sys, "frozen", False):
        return os.path.dirname(sys.executable)
    # archivo dentro de src/ -> sube a la raíz del proyecto
    return os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))

BASE_DIR = _app_base_dir()

DATA_DIR = os.path.join(BASE_DIR, "data")
os.makedirs(DATA_DIR, exist_ok=True)

CSV_NAME  = os.path.join(DATA_DIR, "datoscsv.csv")
XLSX_NAME = os.path.join(DATA_DIR, "datoscsv.xlsx")

def resource_path(rel_path: str) -> str:
    if getattr(sys, "frozen", False) and hasattr(sys, "_MEIPASS"):
        base = sys._MEIPASS  # carpeta temporal de PyInstaller
    else:
        base = BASE_DIR
    return os.path.join(base, rel_path)

# ---------- formateos ----------
def fmt_eur(x):
    try:
        if pd.isna(x): return ""
        return f"{int(float(x)):,} €".replace(",", ".")
    except Exception:
        return ""

def fmt_thousands(x):
    try:
        if pd.isna(x): return ""
        return f"{int(float(x)):,}".replace(",", ".")
    except Exception:
        return ""

def parse_crafting_minutes(s: str):
    """'1d 2h 30m 15s' / '6h 10m' / '55m' / '15s' -> minutos (int)."""
    if not isinstance(s, str) or not s.strip():
        return None
    t = s.lower().replace("min", "m")
    total_sec = 0
    for tok in t.replace(":", " ").split():
        if tok.endswith("d") and tok[:-1].isdigit(): total_sec += int(tok[:-1]) * 86400
        elif tok.endswith("h") and tok[:-1].isdigit(): total_sec += int(tok[:-1]) * 3600
        elif tok.endswith("m") and tok[:-1].isdigit(): total_sec += int(tok[:-1]) * 60
        elif tok.endswith("s") and tok[:-1].isdigit(): total_sec += int(tok[:-1])
        elif tok.isdigit(): total_sec += int(tok)
    return int(round(total_sec / 60)) if total_sec else None

def format_minutes_compact(m):
    if m is None or pd.isna(m): return ""
    m = int(m)
    d, rem = divmod(m, 1440)
    h, mm = divmod(rem, 60)
    parts = []
    if d: parts.append(f"{d}d")
    if h: parts.append(f"{h}h")
    if mm or not parts: parts.append(f"{mm}m")
    return " ".join(parts)

def to_excel(df, path=XLSX_NAME):
    cols = [
        "name","category","subtype_name_es","tier","value",
        "crafting_minutes","crafting_time_fmt",
        "merchant_xp","worker_xp",
        "is_premium","premium_tags",
        "url"
    ]
    df_x = df.copy()
    for c in cols:
        if c not in df_x.columns: df_x[c] = ""
    df_x = df_x[cols]
    with pd.ExcelWriter(path, engine="xlsxwriter") as w:
        df_x.to_excel(w, index=False, sheet_name="blueprints")
        wb, ws = w.book, w.sheets["blueprints"]
        num = wb.add_format({"num_format": "#,##0"})
        eur = wb.add_format({"num_format": '#,##0 "€"'})
        widths = {"A":32,"B":14,"C":18,"D":8,"E":14,"F":12,"G":14,"H":14,"I":14,"J":12,"K":24,"L":70}
        for col, wid in widths.items():
            fmt = eur if col=="E" else (num if col in ("F","H","I") else None)
            ws.set_column(f"{col}:{col}", wid, fmt)
    return path

def safe_read_csv(path):
    for enc in ("utf-8","utf-8-sig","cp1252"):
        try: return pd.read_csv(path, encoding=enc)
        except Exception: pass
    return pd.DataFrame()

def load_csv():
    return safe_read_csv(CSV_NAME) if os.path.exists(CSV_NAME) else pd.DataFrame()

# ---------- app ----------
class App(tk.Tk):
    def __init__(self):
        super().__init__()
        # Icono
        try:
            self.iconbitmap(default=resource_path("assets/app.ico"))
        except Exception:
            try:
                _ico = tk.PhotoImage(file=resource_path("assets/app.png"))
                self.iconphoto(True, _ico)
                self._ico_ref = _ico
            except Exception:
                pass

        self.title("Shop Titans – Blueprints Viewer")
        self.geometry("1600x900")
        self.minsize(1200, 700)

        self.dark_mode = False
        self._build_styles()

        root = ttk.Frame(self, style="TFrame", padding=12)
        root.pack(fill="both", expand=True)

        # datos
        self.df_orig = load_csv()
        self.prepare_dataframe()
        self.df_view = self.df_orig.copy()
        self.row_url = {}

        # barra 0: tema
        bar0 = ttk.Frame(root, style="Card.TFrame", padding=(10,8))
        bar0.pack(fill="x")
        ttk.Button(bar0, text="Modo oscuro", command=self.toggle_theme).grid(row=0, column=0, sticky="w")

        # barra 1: acciones + progreso
        bar1 = ttk.Frame(root, style="Card.TFrame", padding=10)
        bar1.pack(fill="x"); bar1.columnconfigure(0, weight=1)
        self.btn_export = ttk.Button(bar1, text="Exportar Excel (filtro)", command=self.export_filtered)
        self.btn_export.grid(row=0, column=1, padx=6, sticky="e")
        self.btn_update = ttk.Button(bar1, text="Actualizar (re-scrapear)", command=self.update_data)
        self.btn_update.grid(row=0, column=2, padx=(6,0), sticky="e")
        self.prog = ttk.Progressbar(bar1, mode="indeterminate", length=180)
        self.prog.grid(row=0, column=3, padx=(12,0), sticky="e"); self.prog.grid_remove()

        # barra 2: filtros
        bar2 = ttk.Frame(root, style="Card.TFrame", padding=10)
        bar2.pack(fill="x", pady=(10,8))

        ttk.Label(bar2, text="Nombre contiene:").grid(row=0, column=0, sticky="w")
        self.var_name = tk.StringVar()
        ttk.Entry(bar2, textvariable=self.var_name, width=28).grid(row=0, column=1, padx=6)

        ttk.Label(bar2, text="Categoría:").grid(row=0, column=2, sticky="e", padx=(16,0))
        cats = ["(todas)"] + (sorted(self.df_orig["category"].dropna().unique()) if not self.df_orig.empty else [])
        self.var_cat = tk.StringVar(value="(todas)")
        ttk.Combobox(bar2, textvariable=self.var_cat, values=cats, width=16, state="readonly").grid(row=0, column=3, padx=6)

        ttk.Label(bar2, text="Subtipo:").grid(row=0, column=4, sticky="e", padx=(16,0))
        subs = ["(todos)"] + (sorted(self.df_orig["subtype_name_es"].dropna().unique()) if not self.df_orig.empty else [])
        self.var_sub = tk.StringVar(value="(todos)")
        ttk.Combobox(bar2, textvariable=self.var_sub, values=subs, width=18, state="readonly").grid(row=0, column=5, padx=6)

        ttk.Label(bar2, text="Tier mín:").grid(row=0, column=6, sticky="e", padx=(16,0))
        self.var_tmin = tk.StringVar()
        ttk.Combobox(bar2, textvariable=self.var_tmin, values=[str(i) for i in range(1,16)], width=4, state="readonly").grid(row=0, column=7)

        ttk.Label(bar2, text="Tier máx:").grid(row=0, column=8, sticky="e", padx=(12,0))
        self.var_tmax = tk.StringVar()
        ttk.Combobox(bar2, textvariable=self.var_tmax, values=[str(i) for i in range(1,16)], width=4, state="readonly").grid(row=0, column=9)

        ttk.Label(bar2, text="Premium:").grid(row=0, column=10, sticky="e", padx=(16,0))
        self.var_premium = tk.StringVar(value="(todos)")
        ttk.Combobox(bar2, textvariable=self.var_premium, values=["(todos)","Sí","No"], width=10, state="readonly").grid(row=0, column=11, padx=6)

        ttk.Label(bar2, text="Ordenar por:").grid(row=0, column=12, sticky="e", padx=(16,0))
        self.var_sort = tk.StringVar(value="name")
        sort_fields = ["name","tier","value","merchant_xp","worker_xp","crafting_minutes","is_premium"]
        ttk.Combobox(bar2, textvariable=self.var_sort, values=sort_fields, width=18, state="readonly").grid(row=0, column=13, padx=6)
        self.var_desc = tk.BooleanVar(value=False)
        ttk.Checkbutton(bar2, text="Desc", variable=self.var_desc).grid(row=0, column=14, padx=(0,8))

        ttk.Button(bar2, text="Aplicar filtros", command=self.apply_filters).grid(row=0, column=15, padx=(14,6))
        ttk.Button(bar2, text="Limpiar filtros", command=self.clear_filters).grid(row=0, column=16)

        # tabla
        table_wrap = ttk.Frame(root, style="Card.TFrame", padding=10)
        table_wrap.pack(fill="both", expand=True, pady=(8,0))

        # columnas visibles (ocultamos category/subtype/premium)
        self.columns = ["name","tier","value_fmt","crafting_time_fmt","merchant_xp_fmt","worker_xp_fmt","url_label"]
        headers      = ["name","tier","value","crafting_time","merchant_xp","worker_xp","URL"]

        self.tree = ttk.Treeview(table_wrap, columns=self.columns, show="headings")
        for c,h in zip(self.columns, headers):
            self.tree.heading(c, text=h, command=lambda col=c: self.sort_by(col))
        widths = [360, 80, 140, 140, 140, 140, 70]
        for c,w in zip(self.columns, widths):
            self.tree.column(c, width=w, anchor=("center" if c in ("tier","url_label") else "w"))

        vsb = ttk.Scrollbar(table_wrap, orient="vertical", command=self.tree.yview)
        self.tree.configure(yscroll=vsb.set)
        self.tree.pack(fill="both", expand=True, side="left")
        vsb.pack(fill="y", side="right")

        self.tree.bind("<Double-1>", self.open_url)

        # barra de estado
        status = ttk.Frame(root, style="Card.TFrame", padding=(10,6))
        status.pack(fill="x", pady=(6,0))
        status.columnconfigure(0, weight=1)

        self.label_last = ttk.Label(status, text=self._initial_last_update_text()); self.label_last.grid(row=0, column=0, sticky="w")
        self.status_label = ttk.Label(status, text="0 / 0 ítems"); self.status_label.grid(row=0, column=1, sticky="e")

        # carga inicial
        self.populate(self.df_view)
        self.update_counter()

        if self.df_orig.empty:
            messagebox.showinfo("Sin datos", f"No encontré {CSV_NAME}. Pulsa 'Actualizar' para generar el CSV.")

    # ---------- estilos / tema ----------
    def _build_styles(self):
        style = ttk.Style(self)
        try: style.theme_use("clam")
        except: pass
        self.apply_theme(self.dark_mode)

    def apply_theme(self, dark: bool):
        style = ttk.Style(self)
        if dark:
            bg, card, fg = "#0f172a", "#111827", "#e5e7eb"
            sel_bg, sel_fg = "#2563eb", "#ffffff"
        else:
            bg, card, fg = "#f3f4f6", "#ffffff", "#111827"
            sel_bg, sel_fg = "#2563eb", "#ffffff"
        style.configure("TFrame", background=bg)
        style.configure("Card.TFrame", background=card)
        style.configure("TLabel", background=card, foreground=fg)
        style.configure("TButton", padding=6)
        style.configure("Treeview", background=card, foreground=fg, fieldbackground=card, rowheight=26)
        style.map("Treeview", background=[("selected", sel_bg)], foreground=[("selected", sel_fg)])

    def toggle_theme(self):
        self.dark_mode = not self.dark_mode
        self.apply_theme(self.dark_mode)

    # ---------- preparación df ----------
    def prepare_dataframe(self):
        if self.df_orig is None or self.df_orig.empty:
            self.df_orig = pd.DataFrame(columns=[
                "name","category","subtype_name_es","tier","value","crafting_time",
                "merchant_xp","worker_xp","url"
            ])
        for col in ("tier","value","merchant_xp","worker_xp"):
            if col in self.df_orig.columns:
                self.df_orig[col] = pd.to_numeric(self.df_orig[col], errors="coerce")

        self.df_orig["crafting_minutes"] = self.df_orig.get("crafting_time","").apply(parse_crafting_minutes)
        self.df_orig["crafting_time_fmt"] = self.df_orig["crafting_minutes"].apply(format_minutes_compact)

        self.df_orig["value_fmt"]        = self.df_orig.get("value").apply(fmt_eur)
        self.df_orig["merchant_xp_fmt"]  = self.df_orig.get("merchant_xp").apply(fmt_thousands)
        self.df_orig["worker_xp_fmt"]    = self.df_orig.get("worker_xp").apply(fmt_thousands)
        self.df_orig["url_label"]        = self.df_orig.get("url").apply(lambda u: "URL" if isinstance(u, str) and u else "")

        for col in ("category","subtype_name_es"):
            if col not in self.df_orig.columns: self.df_orig[col] = ""

        if "is_premium" not in self.df_orig.columns:
            self.df_orig["is_premium"] = False
        else:
            self.df_orig["is_premium"] = self.df_orig["is_premium"].apply(
                lambda v: str(v).strip().lower() in ("true","1","yes","y","si","sí")
            )
        if "premium_tags" not in self.df_orig.columns:
            self.df_orig["premium_tags"] = ""
        self.df_orig["premium_label"] = self.df_orig["is_premium"].map(lambda b: "Sí" if bool(b) else "")

    # ---------- helpers tabla/filtros ----------
    def populate(self, df):
        self.tree.delete(*self.tree.get_children())
        self.row_url.clear()
        if df is None or df.empty: return
        for _, r in df.iterrows():
            iid = self.tree.insert("", "end", values=[r.get(c,"") for c in self.columns])
            self.row_url[iid] = r.get("url","")

    def current_filtered_df(self):
        df = self.df_orig.copy()
        name = (getattr(self, "var_name", tk.StringVar()).get() or "").strip().lower()
        cat  = getattr(self, "var_cat", tk.StringVar(value="(todas)")).get()
        sub  = getattr(self, "var_sub", tk.StringVar(value="(todos)")).get()
        tmin = (getattr(self, "var_tmin", tk.StringVar()).get() or "").strip()
        tmax = (getattr(self, "var_tmax", tk.StringVar()).get() or "").strip()
        prem = getattr(self, "var_premium", tk.StringVar(value="(todos)")).get()

        if name: df = df[df["name"].astype(str).str.lower().str.contains(name, na=False)]
        if cat and cat != "(todas)": df = df[df["category"] == cat]
        if sub and sub != "(todos)": df = df[df["subtype_name_es"] == sub]

        if prem == "Sí": df = df[df["is_premium"] == True]
        elif prem == "No": df = df[df["is_premium"].fillna(False) == False]

        if tmin.isdigit(): df = df[df["tier"].fillna(-1).astype(int) >= int(tmin)]
        if tmax.isdigit(): df = df[df["tier"].fillna(9999).astype(int) <= int(tmax)]

        col = self.var_sort.get()
        asc = not self.var_desc.get()
        if col in df.columns:
            df = df.sort_values(by=col, ascending=asc, na_position="last")
        return df

    def sort_by(self, col):
        m = {
            "value_fmt": "value",
            "merchant_xp_fmt": "merchant_xp",
            "worker_xp_fmt": "worker_xp",
            "crafting_time_fmt": "crafting_minutes",
            "tier": "tier",
            "name": "name",
        }
        if col == "url_label": return
        real = m.get(col, col)
        if self.var_sort.get() == real:
            self.var_desc.set(not self.var_desc.get())
        else:
            self.var_sort.set(real); self.var_desc.set(False)
        self.apply_filters()

    # ---------- acciones ----------
    def apply_filters(self):
        self.df_view = self.current_filtered_df()
        self.populate(self.df_view)
        self.update_counter()

    def clear_filters(self):
        self.var_name.set(""); self.var_cat.set("(todas)"); self.var_sub.set("(todos)")
        self.var_tmin.set(""); self.var_tmax.set("")
        self.var_premium.set("(todos)")
        self.var_sort.set("name"); self.var_desc.set(False)
        self.df_view = self.df_orig.copy()
        self.populate(self.df_view)
        self.update_counter()

    def export_filtered(self):
        df = self.current_filtered_df()
        if df.empty:
            messagebox.showwarning("Aviso", "No hay filas filtradas.")
            return
        path = filedialog.asksaveasfilename(
            title="Guardar Excel filtrado", defaultextension=".xlsx",
            filetypes=[("Excel","*.xlsx")], initialfile="datoscsv_filtrado.xlsx"
        )
        if not path: return
        to_excel(df, path)
        messagebox.showinfo("Exportado", f"Guardado {path}")

    def update_data(self):
        if not messagebox.askyesno("Actualizar datos","Se volverá a scrapear todo y se sobreescribirá el CSV.\n¿Continuar?"):
            return
        self.btn_update.config(state="disabled")
        self.btn_export.config(state="disabled")
        self.prog.grid(); self.prog.start(12)

        def task():
            err = None; df = None
            try:
                df = scraper.run_scraper(outfile=CSV_NAME)
            except Exception as e:
                err = e

            def done():
                self.prog.stop(); self.prog.grid_remove()
                self.btn_update.config(state="normal")
                self.btn_export.config(state="normal")
                if err:
                    messagebox.showerror("Error", f"Fallo al scrapear:\n{err}"); return
                if df is None or df.empty:
                    messagebox.showwarning("Aviso", "No se obtuvieron datos nuevos."); return
                self.df_orig = df
                self.prepare_dataframe()
                to_excel(self.df_orig, XLSX_NAME)
                self.clear_filters()
                self._set_last_update_now()
                messagebox.showinfo("Actualizado", f"CSV y Excel actualizados:\n- {CSV_NAME}\n- {XLSX_NAME}")
            self.after(0, done)

        threading.Thread(target=task, daemon=True).start()

    def open_url(self, _evt):
        item = self.tree.focus()
        if not item: return
        url = self.row_url.get(item, "")
        if url:
            try: webbrowser.open(url)
            except Exception:
                self.clipboard_clear(); self.clipboard_append(url)
                messagebox.showinfo("Copiado", "URL copiada al portapapeles.")

    # ---------- status helpers ----------
    def update_counter(self):
        total = len(self.df_orig) if self.df_orig is not None else 0
        vis   = len(self.df_view) if self.df_view is not None else 0
        self.status_label.config(text=f"{vis} / {total} ítems")

    def _initial_last_update_text(self):
        if os.path.exists(CSV_NAME):
            ts = datetime.fromtimestamp(os.path.getmtime(CSV_NAME))
            return f"Última actualización: {ts.strftime('%Y-%m-%d %H:%M')}"
        return "Última actualización: —"

    def _set_last_update_now(self):
        self.label_last.config(text=f"Última actualización: {datetime.now().strftime('%Y-%m-%d %H:%M')}")

if __name__ == "__main__":
    App().mainloop()
