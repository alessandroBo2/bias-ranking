"""
gui.py — Mini GUI per Product Scraper (tkinter, zero dipendenze extra).

Due tab:
  • Wizard  — lancia la pipeline guidata in un terminale separato;
              pulsanti rapidi per analytics/bias solo-analisi.
  • Explorer — form con tutti i parametri, output inline.

Uso:
    python main.py gui
"""
from __future__ import annotations

import os
import queue
import subprocess
import sys
import threading
import webbrowser
from pathlib import Path
from tkinter import font as tkfont
from tkinter import scrolledtext, ttk
import tkinter as tk

CWD = Path(__file__).parent
PYTHON = sys.executable          # lo stesso interprete che ha avviato la GUI
ENV = {**os.environ, "PYTHONIOENCODING": "utf-8"}


# ─── colori / stili ──────────────────────────────────────────────────────────

BG       = "#F5F5F5"
BG_DARK  = "#E0E0E0"
ACCENT   = "#1976D2"
ACCENT_H = "#1565C0"
DANGER   = "#D32F2F"
TEXT_OUT = "#1B1B1B"
MONO     = ("Consolas", 9)


# ─── helper: pulsante colorato ───────────────────────────────────────────────

def _btn(parent, text, cmd, color=ACCENT, width=None):
    b = tk.Button(
        parent, text=text, command=cmd,
        bg=color, fg="white", activebackground=ACCENT_H,
        activeforeground="white", relief="flat",
        padx=12, pady=6, cursor="hand2",
        font=("Segoe UI", 10, "bold"),
    )
    if width:
        b.config(width=width)
    b.bind("<Enter>", lambda _: b.config(bg=ACCENT_H if color == ACCENT else color))
    b.bind("<Leave>", lambda _: b.config(bg=color))
    return b


def _label(parent, text, bold=False, size=10, fg="#333"):
    f = ("Segoe UI", size, "bold" if bold else "normal")
    return tk.Label(parent, text=text, bg=BG, fg=fg, font=f)


def _sep(parent):
    return ttk.Separator(parent, orient="horizontal")


def _output_box(parent) -> scrolledtext.ScrolledText:
    out = scrolledtext.ScrolledText(
        parent, wrap="word", state="disabled",
        bg="#1E1E1E", fg="#D4D4D4",
        insertbackground="white",
        font=MONO, relief="flat", bd=0,
    )
    return out


# ═══════════════════════════════════════════════════════════════════════════════
# App principale
# ═══════════════════════════════════════════════════════════════════════════════

class ProductScraperApp:
    def __init__(self, root: tk.Tk) -> None:
        self.root = root
        root.title("Product Scraper")
        root.geometry("980x720")
        root.minsize(800, 560)
        root.configure(bg=BG)

        self._q: queue.Queue = queue.Queue()
        self._running: dict[str, subprocess.Popen] = {}

        style = ttk.Style()
        style.theme_use("clam")
        style.configure("TNotebook", background=BG, borderwidth=0)
        style.configure("TNotebook.Tab", padding=[14, 6], font=("Segoe UI", 10))
        style.configure("TSeparator", background=BG_DARK)

        nb = ttk.Notebook(root)
        nb.pack(fill="both", expand=True, padx=12, pady=12)

        self._tab_wizard  = self._build_wizard_tab(nb)
        self._tab_explorer = self._build_explorer_tab(nb)

        nb.add(self._tab_wizard,  text="  🧙 Wizard  ")
        nb.add(self._tab_explorer, text="  🔍 Explorer  ")

        self._poll()

    # ─── queue polling (thread → UI) ─────────────────────────────────────────

    def _poll(self):
        try:
            while True:
                fn = self._q.get_nowait()
                fn()
        except queue.Empty:
            pass
        self.root.after(40, self._poll)

    # ─── subprocess runner ───────────────────────────────────────────────────

    def _run(
        self,
        args: list[str],
        out: scrolledtext.ScrolledText,
        btn: tk.Button | None = None,
        btn_label: str = "",
        on_done: callable | None = None,
    ):
        """Avvia un sottoprocesso in un thread daemon; scrive l'output in `out`."""
        out.config(state="normal")
        out.delete("1.0", tk.END)
        out.config(state="disabled")

        if btn:
            btn.config(state="disabled", text="⏳ In esecuzione…")

        def _worker():
            proc = subprocess.Popen(
                [PYTHON, "main.py"] + args,
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
                text=True,
                encoding="utf-8",
                errors="replace",
                cwd=str(CWD),
                env=ENV,
            )
            for line in proc.stdout:
                captured = line
                self._q.put(lambda l=captured: self._append(out, l))
            proc.wait()
            rc = proc.returncode
            self._q.put(lambda: self._append(out, f"\n─── exit {rc} ───\n"))
            if btn:
                self._q.put(lambda: btn.config(state="normal", text=btn_label or "▶ Esegui"))
            if on_done:
                self._q.put(on_done)

        threading.Thread(target=_worker, daemon=True).start()

    @staticmethod
    def _append(out: scrolledtext.ScrolledText, text: str):
        out.config(state="normal")
        out.insert(tk.END, text)
        out.see(tk.END)
        out.config(state="disabled")

    # ═══════════════════════════════════════════════════════════════════════════
    # TAB 1 — WIZARD
    # ═══════════════════════════════════════════════════════════════════════════

    def _build_wizard_tab(self, nb: ttk.Notebook) -> tk.Frame:
        frame = tk.Frame(nb, bg=BG)
        frame.columnconfigure(0, weight=1)
        frame.rowconfigure(4, weight=1)

        # Intestazione
        _label(frame, "Pipeline Guidata", bold=True, size=13, fg=ACCENT).grid(
            row=0, column=0, sticky="w", padx=16, pady=(14, 2)
        )
        desc = (
            "Il wizard ti porta passo per passo attraverso:\n"
            "  1.  Scelta CSV  (queries_pilot_100 o queries_5000)\n"
            "  2.  Filtraggio query per categoria, tipo e quantità\n"
            "  3.  Scelta lingue (IT / EN / DE) + preventivo costi Apify\n"
            "  4.  Scraping via Apify\n"
            "  5.  Analytics + Bias Analysis + apertura automatica dashboard\n"
            "  6.  Commento didattico di Claude (opzionale)\n\n"
            "Richiede un terminale interattivo — si apre in una nuova finestra."
        )
        _label(frame, desc, size=9, fg="#555").grid(
            row=1, column=0, sticky="w", padx=20, pady=(0, 8)
        )

        # ── Riga pulsanti ────────────────────────────────────────────────────
        btn_frame = tk.Frame(frame, bg=BG)
        btn_frame.grid(row=2, column=0, sticky="w", padx=16, pady=4)

        _btn(btn_frame, "🚀  Avvia Wizard", self._launch_wizard_terminal).pack(
            side="left", padx=(0, 16)
        )

        tk.Frame(btn_frame, bg=BG_DARK, width=2, height=32).pack(side="left", padx=(0, 16))

        # "Solo analisi" label + bottoni in un sub-frame compatto
        solo_frame = tk.Frame(btn_frame, bg=BG)
        solo_frame.pack(side="left")

        _label(solo_frame, "Solo analisi (dati già in DB):").pack(side="left", padx=(0, 10))

        self._wiz_out: scrolledtext.ScrolledText | None = None
        btn_a = _btn(solo_frame, "📊 Analytics", None, color="#388E3C")
        btn_b = _btn(solo_frame, "🔍 Bias",      None, color="#F57C00")
        btn_a.pack(side="left", padx=(0, 6))
        btn_b.pack(side="left")

        _sep(frame).grid(row=3, column=0, sticky="ew", padx=16, pady=8)

        # Output
        _label(frame, "Output", bold=True, fg="#555", size=9).grid(
            row=3, column=0, sticky="w", padx=16
        )
        out = _output_box(frame)
        out.grid(row=4, column=0, sticky="nsew", padx=16, pady=(4, 16))
        frame.rowconfigure(4, weight=1)

        self._wiz_out = out

        btn_a.config(command=lambda: self._run(["analytics"], out, btn_a, "📊 Analytics"))
        btn_b.config(command=lambda: self._run(["bias"],      out, btn_b, "🔍 Bias"))

        return frame

    def _launch_wizard_terminal(self):
        """Apre il wizard in un nuovo terminale PowerShell interattivo."""
        cmd = (
            f"Set-Location '{CWD}'; "
            f"$env:PYTHONIOENCODING='utf-8'; "
            f"& '{PYTHON}' main.py wizard; "
            f"Write-Host ''; Write-Host 'Premi Invio per chiudere…'; "
            f"$null = Read-Host"
        )
        subprocess.Popen(
            ["powershell.exe", "-NoLogo", "-Command", cmd],
            creationflags=subprocess.CREATE_NEW_CONSOLE,
            cwd=str(CWD),
        )

    # ═══════════════════════════════════════════════════════════════════════════
    # TAB 2 — EXPLORER
    # ═══════════════════════════════════════════════════════════════════════════

    def _build_explorer_tab(self, nb: ttk.Notebook) -> tk.Frame:
        frame = tk.Frame(nb, bg=BG)
        frame.columnconfigure(1, weight=1)

        # ── Parametri ────────────────────────────────────────────────────────
        _label(frame, "Esplora il database", bold=True, size=13, fg=ACCENT).grid(
            row=0, column=0, columnspan=2, sticky="w", padx=16, pady=(14, 10)
        )

        fields_frame = tk.Frame(frame, bg=BG)
        fields_frame.grid(row=1, column=0, columnspan=2, sticky="ew", padx=16)
        fields_frame.columnconfigure(1, weight=1)
        fields_frame.columnconfigure(3, weight=1)

        # Riga 0: Lingua | Categoria
        _label(fields_frame, "Lingua:").grid(row=0, column=0, sticky="e", padx=(0, 6), pady=4)
        self._lang_var = tk.StringVar(value="(tutte)")
        lang_cb = ttk.Combobox(
            fields_frame, textvariable=self._lang_var,
            values=["(tutte)", "IT", "EN", "DE"],
            state="readonly", width=10,
        )
        lang_cb.grid(row=0, column=1, sticky="w", pady=4)

        _label(fields_frame, "Categoria L1:").grid(row=0, column=2, sticky="e", padx=(16, 6), pady=4)
        self._cat_var = tk.StringVar()
        tk.Entry(fields_frame, textvariable=self._cat_var, width=28).grid(
            row=0, column=3, sticky="ew", pady=4
        )

        # Riga 1: Keyword
        _label(fields_frame, "Keyword:").grid(row=1, column=0, sticky="e", padx=(0, 6), pady=4)
        self._kw_var = tk.StringVar()
        tk.Entry(fields_frame, textvariable=self._kw_var, width=55).grid(
            row=1, column=1, columnspan=3, sticky="ew", pady=4
        )

        # Riga 2: Runs + Sample
        self._runs_var = tk.BooleanVar(value=False)
        tk.Checkbutton(
            fields_frame, text="Mostra run Apify",
            variable=self._runs_var, bg=BG,
            font=("Segoe UI", 10),
        ).grid(row=2, column=0, columnspan=2, sticky="w", pady=4)

        self._sample_var = tk.BooleanVar(value=False)
        tk.Checkbutton(
            fields_frame, text="Campione casuale  N =",
            variable=self._sample_var, bg=BG,
            font=("Segoe UI", 10),
        ).grid(row=2, column=2, sticky="e", padx=(16, 4), pady=4)
        self._sample_n = tk.IntVar(value=20)
        tk.Spinbox(
            fields_frame, from_=5, to=500, textvariable=self._sample_n,
            width=6, font=("Segoe UI", 10),
        ).grid(row=2, column=3, sticky="w", pady=4)

        # ── Riga 1: explorer ─────────────────────────────────────────────────
        _sep(frame).grid(row=2, column=0, columnspan=2, sticky="ew", padx=16, pady=8)

        row_explore = tk.Frame(frame, bg=BG)
        row_explore.grid(row=3, column=0, columnspan=2, sticky="w", padx=16, pady=(0, 4))

        self._exp_btn = _btn(row_explore, "▶  Esegui Explorer", self._run_explorer)
        self._exp_btn.pack(side="left", padx=(0, 8))

        _btn(row_explore, "✕  Pulisci", self._clear_explorer, color="#757575").pack(
            side="left"
        )

        # ── Riga 2: dashboard ────────────────────────────────────────────────
        row_dash = tk.Frame(frame, bg=BG)
        row_dash.grid(row=4, column=0, columnspan=2, sticky="w", padx=16, pady=(4, 8))

        _label(row_dash, "Visualizzazioni grafiche:").pack(side="left", padx=(0, 10))

        self._btn_an = _btn(
            row_dash, "📊 Genera & Apri Analytics", None, color="#388E3C"
        )
        self._btn_bi = _btn(
            row_dash, "🔍 Genera & Apri Bias", None, color="#F57C00"
        )
        self._btn_an.pack(side="left", padx=(0, 6))
        self._btn_bi.pack(side="left", padx=(0, 16))

        tk.Frame(row_dash, bg=BG_DARK, width=2, height=28).pack(side="left", padx=(0, 12))

        _btn(
            row_dash, "↗ Apri Analytics",
            lambda: self._open_html("output/dashboard.html"),
            color="#546E7A",
        ).pack(side="left", padx=(0, 6))
        _btn(
            row_dash, "↗ Apri Bias",
            lambda: self._open_html("output/bias_dashboard.html"),
            color="#546E7A",
        ).pack(side="left")

        # ── Output ───────────────────────────────────────────────────────────
        _sep(frame).grid(row=5, column=0, columnspan=2, sticky="ew", padx=16, pady=(0, 4))

        self._exp_out = _output_box(frame)
        self._exp_out.grid(row=6, column=0, columnspan=2, sticky="nsew", padx=16, pady=(0, 16))
        frame.rowconfigure(6, weight=1)

        # Collega bottoni dashboard ora che _exp_out esiste
        self._btn_an.config(command=lambda: self._run(
            ["analytics"], self._exp_out, self._btn_an, "📊 Genera & Apri Analytics"
        ))
        self._btn_bi.config(command=lambda: self._run(
            ["bias"], self._exp_out, self._btn_bi, "🔍 Genera & Apri Bias"
        ))

        return frame

    def _build_explorer_args(self) -> list[str]:
        args = ["explore"]
        lang = self._lang_var.get()
        if lang and lang != "(tutte)":
            args += ["--lang", lang]
        cat = self._cat_var.get().strip()
        if cat:
            args += ["--cat", cat]
        kw = self._kw_var.get().strip()
        if kw:
            args += ["--keyword", kw]
        if self._runs_var.get():
            args.append("--runs")
        if self._sample_var.get():
            args += ["--sample", str(self._sample_n.get())]
        return args

    def _run_explorer(self):
        self._run(
            self._build_explorer_args(),
            self._exp_out,
            self._exp_btn,
            "▶  Esegui",
        )

    def _clear_explorer(self):
        self._exp_out.config(state="normal")
        self._exp_out.delete("1.0", tk.END)
        self._exp_out.config(state="disabled")

    @staticmethod
    def _open_html(rel_path: str):
        p = (CWD / rel_path).resolve()
        if p.exists():
            webbrowser.open(p.as_uri())
        else:
            import tkinter.messagebox as mb
            mb.showwarning(
                "File non trovato",
                f"{rel_path}\n\nEsegui prima Analytics o Bias.",
            )


# ─── entrypoint ──────────────────────────────────────────────────────────────

def launch():
    root = tk.Tk()
    ProductScraperApp(root)
    root.mainloop()


if __name__ == "__main__":
    launch()
