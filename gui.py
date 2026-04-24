"""
gui.py
======
Interface gráfica do Markov-Abjad Composer.

Estética: minimalismo editorial — fundo escuro neutro, tipografia
precisa, acentos em âmbar/sépia. Inspirada em partituras e editores
de notação contemporânea (não em DAWs coloridas).

Threading: geração roda em thread separada via after() thread-safe.
Tkinter não é thread-safe — toda atualização de widget passa por
self.after(0, callback).

Dependências: tkinter (stdlib), integration.py, markov_engine.py
"""

from __future__ import annotations

import os
import platform
import subprocess
import threading
import tkinter as tk
from tkinter import ttk, messagebox, filedialog
from pathlib import Path
from typing import Optional

from integration import (
    CompositionConfig,
    CompositionResult,
    INSTRUMENTS_BY_FAMILY,
    gerar_composicao,
)
from markov_engine import TIME_SIGNATURE_VALUES
from note_event import NotationType


# ─────────────────────────────────────────────────────────────────────────────
#  Paleta e constantes visuais
# ─────────────────────────────────────────────────────────────────────────────

# Tema: editorial escuro — partitura em papel envelhecido
C = {
    "bg":           "#1a1a1a",   # fundo principal
    "bg_panel":     "#222222",   # painéis/seções
    "bg_input":     "#2c2c2c",   # campos de entrada
    "border":       "#383838",   # bordas sutis
    "text":         "#e8e0d0",   # texto principal (creme)
    "text_dim":     "#807868",   # texto secundário
    "text_header":  "#f0e8d8",   # cabeçalhos
    "accent":       "#c8962a",   # âmbar — destaque principal
    "accent_hover": "#e0aa30",   # âmbar claro — hover
    "accent_dim":   "#7a5a18",   # âmbar escuro — desabilitado
    "success":      "#5a8a5a",   # verde seco — sucesso
    "error":        "#8a4a4a",   # vermelho seco — erro
    "check_on":     "#c8962a",   # checkbox ativo
    "separator":    "#2e2e2e",   # linhas divisórias
}

FONT_HEADER  = ("Georgia", 13, "bold")
FONT_SUBHEAD = ("Georgia", 10, "italic")
FONT_LABEL   = ("Courier", 9)
FONT_LABEL_B = ("Courier", 9, "bold")
FONT_MONO    = ("Courier", 9)
FONT_BTN     = ("Courier", 10, "bold")
FONT_LOG     = ("Courier", 8)
FONT_TITLE   = ("Georgia", 18, "bold")

TIME_SIGS = ["4/4", "3/4", "2/4", "3/8", "6/8", "12/8", "5/4", "7/8"]


# ─────────────────────────────────────────────────────────────────────────────
#  Aplicação principal
# ─────────────────────────────────────────────────────────────────────────────

class MarkovAbjadApp(tk.Tk):
    """Janela principal do Markov-Abjad Composer."""

    def __init__(self):
        super().__init__()

        self.title("Markov-Abjad Composer")
        self.configure(bg=C["bg"])
        self.geometry("980x820")
        self.minsize(860, 700)
        self.resizable(True, True)

        # Estado da última composição
        self._last_result: Optional[CompositionResult] = None
        self._generating = False
        self._vars: dict = {}   # armazenamento central de variáveis de parâmetros

        # Configurar ttk style
        self._setup_style()

        # Construir interface
        self._build_header()
        self._build_body()
        self._build_footer()

        # Centralizar na tela
        self.update_idletasks()
        w, h = self.winfo_width(), self.winfo_height()
        sw, sh = self.winfo_screenwidth(), self.winfo_screenheight()
        self.geometry(f"{w}x{h}+{(sw-w)//2}+{(sh-h)//2}")

    # ── Setup de style ttk ────────────────────────────────────────

    def _setup_style(self):
        style = ttk.Style(self)
        style.theme_use("clam")

        # Frame
        style.configure("Dark.TFrame",      background=C["bg"])
        style.configure("Panel.TFrame",     background=C["bg_panel"])
        style.configure("Separator.TFrame", background=C["border"])

        # Labels
        style.configure("Dark.TLabel",
            background=C["bg"], foreground=C["text"], font=FONT_LABEL)
        style.configure("Panel.TLabel",
            background=C["bg_panel"], foreground=C["text"], font=FONT_LABEL)
        style.configure("Header.TLabel",
            background=C["bg_panel"], foreground=C["text_header"],
            font=FONT_SUBHEAD)
        style.configure("Dim.TLabel",
            background=C["bg_panel"], foreground=C["text_dim"], font=FONT_LABEL)

        # LabelFrame
        style.configure("Dark.TLabelframe",
            background=C["bg_panel"], foreground=C["text_dim"],
            bordercolor=C["border"], relief="flat")
        style.configure("Dark.TLabelframe.Label",
            background=C["bg_panel"], foreground=C["text_dim"],
            font=("Courier", 8, "bold"))

        # Checkbutton
        style.configure("Dark.TCheckbutton",
            background=C["bg_panel"], foreground=C["text"],
            font=FONT_LABEL, indicatorcolor=C["bg_input"],
            selectcolor=C["accent"])
        style.map("Dark.TCheckbutton",
            background=[("active", C["bg_panel"])],
            foreground=[("active", C["accent"])])

        # Radiobutton
        style.configure("Dark.TRadiobutton",
            background=C["bg_panel"], foreground=C["text"], font=FONT_LABEL)
        style.map("Dark.TRadiobutton",
            background=[("active", C["bg_panel"])],
            foreground=[("active", C["accent"])])

        # Spinbox e Entry
        style.configure("Dark.TSpinbox",
            background=C["bg_input"], foreground=C["text"],
            fieldbackground=C["bg_input"], insertcolor=C["text"],
            bordercolor=C["border"], font=FONT_MONO)
        style.configure("Dark.TEntry",
            background=C["bg_input"], foreground=C["text"],
            fieldbackground=C["bg_input"], insertcolor=C["text"],
            bordercolor=C["border"], font=FONT_MONO)

        # Combobox
        style.configure("Dark.TCombobox",
            background=C["bg_input"], foreground=C["text"],
            fieldbackground=C["bg_input"], selectbackground=C["accent"],
            font=FONT_MONO)
        style.map("Dark.TCombobox",
            fieldbackground=[("readonly", C["bg_input"])],
            selectbackground=[("readonly", C["accent"])])

        # Progressbar — sem prefixo de layout customizado (evita TclError macOS)
        style.configure("TProgressbar",
            background=C["accent"], troughcolor=C["bg_input"])
        # TScrollbar: NÃO configurar via ttk style — usar tk.Scrollbar diretamente

    # ── Header ────────────────────────────────────────────────────

    def _build_header(self):
        hdr = tk.Frame(self, bg=C["bg"], pady=0)
        hdr.pack(fill=tk.X, padx=0, pady=0)

        # Linha decorativa superior
        tk.Frame(hdr, bg=C["accent"], height=2).pack(fill=tk.X)

        inner = tk.Frame(hdr, bg=C["bg"], pady=12)
        inner.pack(fill=tk.X, padx=24)

        tk.Label(inner, text="Markov-Abjad Composer",
                 bg=C["bg"], fg=C["text_header"], font=FONT_TITLE).pack(side=tk.LEFT)

        tk.Label(inner,
                 text="composição algorítmica · notação contemporânea · LilyPond 2.24",
                 bg=C["bg"], fg=C["text_dim"], font=FONT_SUBHEAD).pack(
                     side=tk.LEFT, padx=16, pady=(6, 0))

        # Linha divisória
        tk.Frame(hdr, bg=C["border"], height=1).pack(fill=tk.X)

    # ── Body (dois painéis lado a lado) ──────────────────────────

    def _build_body(self):
        body = tk.Frame(self, bg=C["bg"])
        body.pack(fill=tk.BOTH, expand=True, padx=16, pady=(12, 0))
        body.columnconfigure(0, weight=3, minsize=300)
        body.columnconfigure(1, weight=4, minsize=420)
        body.rowconfigure(0, weight=1)

        # Painel esquerdo: instrumentos
        self._build_panel_instruments(body)

        # Separador vertical
        tk.Frame(body, bg=C["border"], width=1).grid(
            row=0, column=0, columnspan=2, sticky="ns", padx=(302, 0))

        # Painel direito: parâmetros (notebook interno)
        self._build_panel_params(body)

    # ── Painel Esquerdo: Instrumentos ─────────────────────────────

    def _build_panel_instruments(self, parent):
        left = tk.Frame(parent, bg=C["bg_panel"])
        left.grid(row=0, column=0, sticky="nsew", padx=(0, 8))

        # Título da seção
        self._section_title(left, "I. Instrumentos")

        # Container com scroll (para futuras expansões)
        canvas = tk.Canvas(left, bg=C["bg_panel"], highlightthickness=0)
        vsb = tk.Scrollbar(left, orient="vertical", command=canvas.yview,
                           bg=C["bg_input"], troughcolor=C["bg_panel"],
                           bd=0, width=8)
        canvas.configure(yscrollcommand=vsb.set)
        vsb.pack(side=tk.RIGHT, fill=tk.Y)
        canvas.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)

        inner = tk.Frame(canvas, bg=C["bg_panel"])
        canvas.create_window((0, 0), window=inner, anchor="nw")
        inner.bind("<Configure>", lambda e: canvas.configure(
            scrollregion=canvas.bbox("all")))

        # Variáveis de estado: {instrumento: (BooleanVar, IntVar)}
        self._instr_vars: dict[str, tuple[tk.BooleanVar, tk.IntVar]] = {}

        for family, instruments in INSTRUMENTS_BY_FAMILY.items():
            # Cabeçalho de família
            fhdr = tk.Frame(inner, bg=C["bg_panel"])
            fhdr.pack(fill=tk.X, padx=8, pady=(10, 2))

            tk.Label(fhdr, text=family.upper(),
                     bg=C["bg_panel"], fg=C["accent"],
                     font=("Courier", 8, "bold")).pack(side=tk.LEFT)
            tk.Frame(fhdr, bg=C["accent_dim"], height=1).pack(
                side=tk.LEFT, fill=tk.X, expand=True, padx=(6, 0), pady=4)

            # Grade de instrumentos
            grid = tk.Frame(inner, bg=C["bg_panel"])
            grid.pack(fill=tk.X, padx=8, pady=(0, 4))

            for col, instr in enumerate(instruments):
                cell = tk.Frame(grid, bg=C["bg_panel"])
                cell.grid(row=0, column=col, padx=2, pady=2, sticky="w")

                bvar = tk.BooleanVar(value=False)
                ivar = tk.IntVar(value=1)
                self._instr_vars[instr] = (bvar, ivar)

                # Checkbox customizado (canvas para cor)
                cb_frame = tk.Frame(cell, bg=C["bg_panel"])
                cb_frame.pack(anchor="w")

                cb = tk.Checkbutton(
                    cb_frame,
                    text=self._instr_abbrev(instr),
                    variable=bvar,
                    bg=C["bg_panel"], fg=C["text"],
                    selectcolor=C["bg_input"],
                    activebackground=C["bg_panel"],
                    activeforeground=C["accent"],
                    font=FONT_LABEL,
                    bd=0, padx=2,
                    command=lambda i=instr: self._on_instr_toggle(i),
                )
                cb.pack(side=tk.LEFT)

                # Spinbox de dobras (visível apenas quando selecionado)
                spf = tk.Frame(cb_frame, bg=C["bg_panel"])
                spf.pack(side=tk.LEFT)

                sp = tk.Spinbox(
                    spf, from_=1, to=3, textvariable=ivar,
                    width=2, state="disabled",
                    bg=C["bg_input"], fg=C["text_dim"],
                    disabledbackground=C["bg_panel"],
                    disabledforeground=C["bg_panel"],
                    font=FONT_MONO, bd=0,
                    buttonbackground=C["bg_input"],
                )
                sp.pack()
                # Guardar referência para habilitar/desabilitar
                cell._sp = sp
                cell._bvar = bvar
                self._instr_vars[instr] = (bvar, ivar, sp)

        # Botões de seleção rápida
        btn_bar = tk.Frame(left, bg=C["bg_panel"], pady=6)
        btn_bar.pack(fill=tk.X, padx=8, side=tk.BOTTOM)

        self._mk_small_btn(btn_bar, "Quarteto Cordas",
                           lambda: self._preset_quartet()).pack(
                               side=tk.LEFT, padx=(0, 4))
        self._mk_small_btn(btn_bar, "Trio Madeiras",
                           lambda: self._preset_woodwind_trio()).pack(
                               side=tk.LEFT, padx=(0, 4))
        self._mk_small_btn(btn_bar, "Limpar",
                           lambda: self._clear_instruments()).pack(
                               side=tk.RIGHT)

    def _instr_abbrev(self, name: str) -> str:
        abbrevs = {
            "Flute": "Fl.", "Oboe": "Ob.", "Clarinet": "Cl.", "Bassoon": "Bn.",
            "Horn": "Hn.", "Trumpet": "Tpt.", "Trombone": "Tbn.", "Tuba": "Tba.",
            "Violin": "Vln.", "Viola": "Vla.", "Violoncello": "Vc.",
            "Double Bass": "Db.", "Piano": "Pf.", "Harp": "Hrp.",
        }
        return abbrevs.get(name, name[:4] + ".")

    def _on_instr_toggle(self, instr: str):
        bvar, ivar, sp = self._instr_vars[instr]
        if bvar.get():
            sp.config(state="normal", fg=C["text"],
                      disabledforeground=C["text"])
        else:
            sp.config(state="disabled", fg=C["bg_panel"],
                      disabledforeground=C["bg_panel"])

    def _get_selected_instruments(self) -> list[str]:
        result = []
        for instr, (bvar, ivar, _) in self._instr_vars.items():
            if bvar.get():
                n = ivar.get()
                if n == 1:
                    result.append(instr)
                else:
                    for i in range(1, n + 1):
                        result.append(f"{instr} #{i}")
        return result

    def _preset_quartet(self):
        self._clear_instruments()
        for instr in ["Violin", "Viola", "Violoncello", "Double Bass"]:
            bvar, ivar, sp = self._instr_vars[instr]
            bvar.set(True)
            sp.config(state="normal", fg=C["text"])

    def _preset_woodwind_trio(self):
        self._clear_instruments()
        for instr in ["Flute", "Oboe", "Clarinet"]:
            bvar, ivar, sp = self._instr_vars[instr]
            bvar.set(True)
            sp.config(state="normal", fg=C["text"])

    def _clear_instruments(self):
        for instr, (bvar, ivar, sp) in self._instr_vars.items():
            bvar.set(False)
            ivar.set(1)
            sp.config(state="disabled", fg=C["bg_panel"],
                      disabledforeground=C["bg_panel"])

    # ── Painel Direito: Parâmetros ────────────────────────────────

    def _build_panel_params(self, parent):
        right = tk.Frame(parent, bg=C["bg"])
        right.grid(row=0, column=1, sticky="nsew", padx=(8, 0))
        right.rowconfigure(0, weight=1)
        right.columnconfigure(0, weight=1)

        # Notebook
        nb = ttk.Notebook(right)
        nb.pack(fill=tk.BOTH, expand=True)

        # Aba 0: Treinamento MIDI  ← nova
        tab0 = tk.Frame(nb, bg=C["bg_panel"])
        nb.add(tab0, text="  Treinamento MIDI  ")
        self._build_tab_midi(tab0)

        # Aba 1: Parâmetros musicais (scrollável)
        tab1 = tk.Frame(nb, bg=C["bg_panel"])
        nb.add(tab1, text="  Parâmetros Musicais  ")
        inner1 = self._scrollable_tab(tab1)
        self._build_tab_musical(inner1)

        # Aba 2: Microtonalismo (scrollável)
        tab2 = tk.Frame(nb, bg=C["bg_panel"])
        nb.add(tab2, text="  Microtonalismo  ")
        inner2 = self._scrollable_tab(tab2)
        self._build_tab_micro(inner2)

        # Aba 3: Notação e Metadados (scrollável)
        tab3 = tk.Frame(nb, bg=C["bg_panel"])
        nb.add(tab3, text="  Notação  ")
        inner3 = self._scrollable_tab(tab3)
        self._build_tab_notation(inner3)

        # Aplicar fundo ao notebook
        style = ttk.Style()
        style.configure("TNotebook",
            background=C["bg"], bordercolor=C["border"])
        style.configure("TNotebook.Tab",
            background=C["bg_input"], foreground=C["text_dim"],
            font=FONT_LABEL, padding=(8, 4))
        style.map("TNotebook.Tab",
            background=[("selected", C["bg_panel"])],
            foreground=[("selected", C["accent"])])

    def _build_tab_midi(self, parent):
        """Aba de treinamento MIDI — suporta múltiplos arquivos."""

        # ── Estado interno ────────────────────────────────────────
        # Lista de (midi_path, track_idx, MidiTrainer|None)
        self._midi_corpus: list[dict] = []   # {"path":str, "track":int, "trainer":obj|None}
        self._midi_trained: bool = False
        self._midi_trainer = None            # mantido para compatibilidade; aponta para o primeiro

        # ── Seção: corpus de arquivos ─────────────────────────────
        grp = self._section_group(parent, "Corpus de Treinamento MIDI")

        # Cabeçalho da lista
        hdr = tk.Frame(grp, bg=C["bg_panel"])
        hdr.pack(fill=tk.X, padx=8, pady=(4, 0))
        tk.Label(hdr, text="Arquivo", bg=C["bg_panel"], fg=C["text_dim"],
                 font=FONT_LOG, width=30, anchor="w").pack(side=tk.LEFT)
        tk.Label(hdr, text="Track", bg=C["bg_panel"], fg=C["text_dim"],
                 font=FONT_LOG, width=10, anchor="w").pack(side=tk.LEFT)
        tk.Label(hdr, text="Notas", bg=C["bg_panel"], fg=C["text_dim"],
                 font=FONT_LOG, width=7, anchor="e").pack(side=tk.LEFT)

        # Listbox scrollável
        list_frame = tk.Frame(grp, bg=C["bg_input"], relief="flat", bd=1)
        list_frame.pack(fill=tk.BOTH, expand=False, padx=8, pady=2)
        self._midi_listbox = tk.Listbox(
            list_frame,
            bg=C["bg_input"], fg=C["text"],
            font=FONT_MONO, selectbackground=C["accent_dim"],
            selectforeground=C["text"], bd=0, height=5,
            activestyle="none", exportselection=False,
        )
        _vsb_list = tk.Scrollbar(list_frame, command=self._midi_listbox.yview,
                                  bg=C["bg_input"], troughcolor=C["bg_panel"],
                                  bd=0, width=8)
        self._midi_listbox.configure(yscrollcommand=_vsb_list.set)
        _vsb_list.pack(side=tk.RIGHT, fill=tk.Y)
        self._midi_listbox.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)

        # Botões de gerenciamento da lista
        btn_list = tk.Frame(grp, bg=C["bg_panel"])
        btn_list.pack(fill=tk.X, padx=8, pady=(2, 6))

        self._mk_small_btn(btn_list, "+ Adicionar .mid",
                           self._on_add_midi).pack(side=tk.LEFT, padx=(0, 4))
        self._mk_small_btn(btn_list, "− Remover selecionado",
                           self._on_remove_midi).pack(side=tk.LEFT, padx=(0, 4))
        self._mk_small_btn(btn_list, "✕ Limpar tudo",
                           self._on_clear_midi).pack(side=tk.LEFT)

        # Contador de corpus
        self._var_corpus_count = tk.StringVar(value="Corpus vazio")
        tk.Label(grp, textvariable=self._var_corpus_count,
                 bg=C["bg_panel"], fg=C["text_dim"],
                 font=FONT_LOG).pack(anchor="w", padx=10, pady=(0, 4))

        # ── Seção: configuração do item selecionado ───────────────
        grp2 = self._section_group(parent, "Configurar arquivo selecionado")

        track_row = tk.Frame(grp2, bg=C["bg_panel"])
        track_row.pack(fill=tk.X, padx=8, pady=4)
        tk.Label(track_row, text="Track MIDI:", bg=C["bg_panel"],
                 fg=C["text"], font=FONT_LABEL, width=13,
                 anchor="w").pack(side=tk.LEFT)
        self._midi_track_combo = ttk.Combobox(
            track_row, state="disabled", font=FONT_MONO, width=34,
            style="Dark.TCombobox",
        )
        self._midi_track_combo.pack(side=tk.LEFT)
        self._btn_apply_track = self._mk_small_btn(
            track_row, "Aplicar",
            self._on_apply_track)
        self._btn_apply_track.config(state="disabled")
        self._btn_apply_track.pack(side=tk.LEFT, padx=(6, 0))

        # Vincular seleção na listbox
        self._midi_listbox.bind("<<ListboxSelect>>", self._on_midi_item_select)

        # ── Seção: análise e treinamento ──────────────────────────
        grp3 = self._section_group(parent, "Análise do Corpus")

        btn_row = tk.Frame(grp3, bg=C["bg_panel"])
        btn_row.pack(fill=tk.X, padx=8, pady=(4, 2))

        self._btn_analyze = self._mk_small_btn(
            btn_row, "▶ Analisar corpus",
            self._on_analyze_corpus)
        self._btn_analyze.config(state="disabled")
        self._btn_analyze.pack(side=tk.LEFT)

        self._var_midi_status = tk.StringVar(value="")
        tk.Label(btn_row, textvariable=self._var_midi_status,
                 bg=C["bg_panel"], fg=C["success"],
                 font=FONT_LOG).pack(side=tk.LEFT, padx=8)

        self._midi_log = tk.Text(
            grp3, bg=C["bg_input"], fg=C["text_dim"],
            font=FONT_LOG, bd=0, height=10,
            state="disabled", wrap=tk.WORD,
        )
        vsb2 = tk.Scrollbar(grp3, command=self._midi_log.yview,
                            bg=C["bg_input"], troughcolor=C["bg_panel"],
                            bd=0, width=8)
        self._midi_log.configure(yscrollcommand=vsb2.set)
        vsb2.pack(side=tk.RIGHT, fill=tk.Y, padx=(0, 4))
        self._midi_log.pack(fill=tk.BOTH, expand=True, padx=4, pady=4)

        # ── Nota explicativa ──────────────────────────────────────
        note_frame = tk.Frame(parent, bg=C["bg_panel"])
        note_frame.pack(fill=tk.X, padx=12, pady=(6, 0))
        tk.Label(
            note_frame,
            text=(
                "Adicione um ou mais MIDIs. As sequências de pitch, duração\n"
                "e dinâmica são concatenadas — a cadeia de Markov aprende\n"
                "o corpus inteiro de forma integrada.\n\n"
                "Técnicas estendidas e microtons são gerados por família\n"
                "instrumental (MIDI não os codifica).\n\n"
                "Requer: pip install mido"
            ),
            bg=C["bg_panel"], fg=C["text_dim"],
            font=FONT_LOG, justify=tk.LEFT, padx=4,
        ).pack(anchor="w")

    # ── Gerenciamento do corpus MIDI ──────────────────────────────

    def _on_add_midi(self):
        """Abre diálogo para adicionar um ou mais arquivos MIDI ao corpus."""
        paths = filedialog.askopenfilenames(
            title="Adicionar arquivo(s) MIDI ao corpus",
            filetypes=[("MIDI", "*.mid *.midi"), ("Todos", "*.*")],
            parent=self,
        )
        if not paths:
            return

        from midi_trainer import MidiTrainer, MIDO_AVAILABLE
        if not MIDO_AVAILABLE:
            messagebox.showerror(
                "mido não instalado",
                "Execute:  pip install mido",
                parent=self,
            )
            return

        for path in paths:
            # Evitar duplicatas
            if any(e["path"] == path for e in self._midi_corpus):
                continue

            entry = {"path": path, "track": 0, "trainer": None, "note_count": "?"}

            # Carregar lista de tracks em background
            try:
                tracks = MidiTrainer.list_tracks(path)
                entry["tracks"] = tracks
                first_with_notes = next(
                    (t for t in tracks if t["note_count"] > 0), None
                )
                entry["track"] = first_with_notes["index"] if first_with_notes else 0
            except Exception:
                entry["tracks"] = []

            self._midi_corpus.append(entry)

        self._refresh_midi_listbox()
        self._update_corpus_count()
        if self._midi_corpus:
            self._btn_analyze.config(state="normal")

    def _on_remove_midi(self):
        """Remove o item selecionado do corpus."""
        sel = self._midi_listbox.curselection()
        if not sel:
            return
        idx = sel[0]
        if 0 <= idx < len(self._midi_corpus):
            self._midi_corpus.pop(idx)
            self._refresh_midi_listbox()
            self._update_corpus_count()
            self._midi_track_combo.config(state="disabled", values=[])
            self._btn_apply_track.config(state="disabled")
            if not self._midi_corpus:
                self._btn_analyze.config(state="disabled")
                self._midi_trained = False
                self._midi_trainer = None
                self._var_midi_status.set("")

    def _on_clear_midi(self):
        """Remove todos os arquivos do corpus."""
        if not self._midi_corpus:
            return
        if not messagebox.askyesno(
            "Limpar corpus", "Remover todos os MIDIs do corpus?", parent=self
        ):
            return
        self._midi_corpus.clear()
        self._refresh_midi_listbox()
        self._update_corpus_count()
        self._midi_track_combo.config(state="disabled", values=[])
        self._btn_apply_track.config(state="disabled")
        self._btn_analyze.config(state="disabled")
        self._midi_trained = False
        self._midi_trainer = None
        self._var_midi_status.set("")

    def _on_midi_item_select(self, _event=None):
        """Popula o combo de tracks com as tracks do item selecionado."""
        sel = self._midi_listbox.curselection()
        if not sel:
            return
        idx = sel[0]
        if idx >= len(self._midi_corpus):
            return
        entry = self._midi_corpus[idx]
        tracks = entry.get("tracks", [])
        values = [
            f"[{t['index']}] {t['name'] or 'Track '+str(t['index'])}"
            f"  ({t['note_count']} notas)"
            for t in tracks if t["note_count"] > 0
        ] or ["(sem notas detectadas)"]
        self._midi_track_combo.config(state="readonly", values=values)
        # Selecionar track atual do entry
        cur_track = entry["track"]
        for i, t in enumerate(tracks):
            if t["index"] == cur_track:
                self._midi_track_combo.current(i)
                break
        else:
            self._midi_track_combo.current(0)
        self._btn_apply_track.config(state="normal")

    def _on_apply_track(self):
        """Aplica a track selecionada ao item da lista."""
        sel = self._midi_listbox.curselection()
        if not sel:
            return
        idx = sel[0]
        if idx >= len(self._midi_corpus):
            return
        entry   = self._midi_corpus[idx]
        combo_v = self._midi_track_combo.get()
        try:
            track_idx = int(combo_v.split("]")[0].replace("[", "").strip())
        except Exception:
            track_idx = 0
        entry["track"]   = track_idx
        entry["trainer"] = None          # invalidar trainer já carregado
        self._refresh_midi_listbox()
        self._midi_trained = False
        self._var_midi_status.set("Track alterada — reanalisar o corpus")

    def _refresh_midi_listbox(self):
        """Atualiza a listbox com o estado atual do corpus."""
        self._midi_listbox.delete(0, tk.END)
        for entry in self._midi_corpus:
            name = Path(entry["path"]).name
            if len(name) > 28:
                name = name[:26] + "…"
            tr = entry.get("trainer")
            notes_str = str(len(tr.pitches)) if (tr and tr._loaded) else "–"
            track_str = f"[{entry['track']}]"
            line = f"{name:<28} {track_str:<7} {notes_str:>6}"
            self._midi_listbox.insert(tk.END, line)

    def _update_corpus_count(self):
        """Atualiza o label de contagem do corpus."""
        n = len(self._midi_corpus)
        loaded = sum(1 for e in self._midi_corpus if e.get("trainer") and e["trainer"]._loaded)
        total_notes = sum(
            len(e["trainer"].pitches)
            for e in self._midi_corpus
            if e.get("trainer") and e["trainer"]._loaded
        )
        if n == 0:
            self._var_corpus_count.set("Corpus vazio")
        elif loaded == 0:
            self._var_corpus_count.set(f"{n} arquivo(s) — pendente análise")
        else:
            self._var_corpus_count.set(
                f"{n} arquivo(s) · {loaded} analisado(s) · {total_notes} notas no corpus"
            )

    # ── Análise do corpus ─────────────────────────────────────────

    def _on_analyze_corpus(self):
        """Analisa todos os MIDIs do corpus em background."""
        if not self._midi_corpus:
            return

        self._midi_log.config(state="normal")
        self._midi_log.delete("1.0", tk.END)
        self._midi_log.insert(tk.END, f"Analisando {len(self._midi_corpus)} arquivo(s)…\n")
        self._midi_log.config(state="disabled")
        self.update_idletasks()

        corpus_snapshot = list(self._midi_corpus)  # cópia para a thread

        def worker():
            from midi_trainer import MidiTrainer
            errors = []
            for entry in corpus_snapshot:
                try:
                    trainer = MidiTrainer(entry["path"])
                    trainer.load(track_filter=entry["track"])
                    entry["trainer"] = trainer
                except Exception as e:
                    errors.append(f"{Path(entry['path']).name}: {e}")

            try:
                from midi_trainer import MidiTrainer
                trainers = [e["trainer"] for e in corpus_snapshot
                            if e.get("trainer") and e["trainer"]._loaded]
                summary = MidiTrainer.corpus_summary(trainers)
            except Exception as e:
                summary = f"Erro ao gerar sumário: {e}"

            self.after(0, lambda: self._corpus_analysis_done(summary, errors))

        threading.Thread(target=worker, daemon=True).start()

    def _corpus_analysis_done(self, summary: str, errors: list):
        """Callback pós-análise — atualiza log e estado."""
        # Atualizar trainers do corpus (a thread escreveu diretamente em cada entry)
        self._midi_log.config(state="normal")
        self._midi_log.delete("1.0", tk.END)

        if errors:
            self._midi_log.insert(tk.END, "ERROS:\n")
            for err in errors:
                self._midi_log.insert(tk.END, f"  ✗ {err}\n")
            self._midi_log.insert(tk.END, "\n")

        self._midi_log.insert(tk.END, summary)
        self._midi_log.config(state="disabled")

        # Determinar treinadores bem-sucedidos
        loaded = [e["trainer"] for e in self._midi_corpus
                  if e.get("trainer") and e["trainer"]._loaded]

        if loaded:
            self._midi_trained = True
            self._midi_trainer = loaded[0]   # compatibilidade com código legado
            n_notes = sum(len(t.pitches) for t in loaded)
            self._var_midi_status.set(
                f"✓ {len(loaded)} MIDI(s) prontos · {n_notes} notas no corpus"
            )
            self._var_corpus_count.set(
                f"{len(self._midi_corpus)} arquivo(s) · "
                f"{len(loaded)} analisado(s) · {n_notes} notas no corpus"
            )
            self._refresh_midi_listbox()
        else:
            self._midi_trained = False
            self._var_midi_status.set("✗ Nenhum MIDI carregado com sucesso")


    def _build_tab_musical(self, parent):
        pad = dict(padx=16, pady=6)

        # Markov
        grp = self._section_group(parent, "Cadeia de Markov")
        self._param_row(grp, "Ordem:", "markov_order",
                        "spinbox", from_=1, to=4, width=4,
                        tooltip="1 = local · 2 = frases · 3-4 = padrões mais longos")
        self._param_row(grp, "Notas / instrumento:", "n_notes",
                        "spinbox", from_=8, to=8000, width=6)
        self._param_row(grp, "Pausas (%):", "rest_prob",
                        "scale", from_=0, to=50, resolution=1,
                        tooltip="0 = sem pausas · 20 = ~20% dos eventos são pausas")

        # Dinâmicas
        grp_dyn = self._section_group(parent, "Dinâmicas")
        # Peso de cada nível dinâmico (0 = nunca, 10 = muito frequente)
        self._dyn_weights: dict = {}
        DYN_LABELS = [
            ("ppp",  "dyn_ppp",  1),
            ("pp",   "dyn_pp",   3),
            ("p",    "dyn_p",    3),
            ("mp",   "dyn_mp",   3),
            ("mf",   "dyn_mf",   2),
            ("f",    "dyn_f",    2),
            ("ff",   "dyn_ff",   1),
            ("fff",  "dyn_fff",  0),
        ]
        for label, key, default in DYN_LABELS:
            self._param_row(grp_dyn, f"{label}:", key,
                            "scale", from_=0, to=10, resolution=1,
                            default=default)
        # Hairpins
        self._var_hairpins = tk.BooleanVar(value=True)
        hrow = tk.Frame(grp_dyn, bg=C["bg_panel"])
        hrow.pack(fill=tk.X, padx=8, pady=4)
        tk.Checkbutton(
            hrow, text="Crescendos / decrescendos automáticos  (hairpins)",
            variable=self._var_hairpins,
            bg=C["bg_panel"], fg=C["text"],
            selectcolor=C["bg_input"],
            activebackground=C["bg_panel"], activeforeground=C["accent"],
            font=FONT_LABEL, bd=0,
        ).pack(side=tk.LEFT)

        # Quiálteras
        grp_tup = self._section_group(parent, "Quiálteras")
        self._var_tuplets = tk.BooleanVar(value=False)
        trow = tk.Frame(grp_tup, bg=C["bg_panel"])
        trow.pack(fill=tk.X, padx=8, pady=2)
        tk.Checkbutton(
            trow, text="Habilitar quiálteras",
            variable=self._var_tuplets,
            bg=C["bg_panel"], fg=C["text"],
            selectcolor=C["bg_input"],
            activebackground=C["bg_panel"], activeforeground=C["accent"],
            font=FONT_LABEL, bd=0,
            command=self._on_tuplets_toggle,
        ).pack(side=tk.LEFT)
        self._frame_tuplet_params = tk.Frame(grp_tup, bg=C["bg_panel"])
        self._frame_tuplet_params.pack(fill=tk.X, padx=8)
        self._param_row(self._frame_tuplet_params, "Densidade (%):", "tuplet_prob",
                        "scale", from_=5, to=50, resolution=1, default=20,
                        tooltip="% de durações que serão quiálteras")
        # Combobox de complexidade
        cplx_row = tk.Frame(self._frame_tuplet_params, bg=C["bg_panel"])
        cplx_row.pack(fill=tk.X, padx=0, pady=2)
        tk.Label(cplx_row, text="Complexidade:",
                 bg=C["bg_panel"], fg=C["text_dim"], font=FONT_LABEL,
                 width=20, anchor="w").pack(side=tk.LEFT)
        self._vars["tuplet_complexity"] = tk.StringVar(value="1")
        ttk.Combobox(
            cplx_row,
            textvariable=self._vars["tuplet_complexity"],
            values=["1 — tercinas", "2 — + quintinas", "3 — + sétimas / nônimas"],
            state="readonly", width=24,
            style="Dark.TCombobox",
        ).pack(side=tk.LEFT, padx=4)
        self._frame_tuplet_params.pack_forget()  # oculto até habilitar

        # Glissando
        grp_gliss = self._section_group(parent, "Glissando")
        grow = tk.Frame(grp_gliss, bg=C["bg_panel"])
        grow.pack(fill=tk.X, padx=8, pady=2)
        self._var_glissando = tk.BooleanVar(value=False)
        tk.Checkbutton(
            grow, text="Habilitar glissandos contínuos",
            variable=self._var_glissando,
            bg=C["bg_panel"], fg=C["text"],
            selectcolor=C["bg_input"],
            activebackground=C["bg_panel"], activeforeground=C["accent"],
            font=FONT_LABEL, bd=0,
            command=self._on_glissando_toggle,
        ).pack(side=tk.LEFT)
        self._frame_gliss_params = tk.Frame(grp_gliss, bg=C["bg_panel"])
        self._frame_gliss_params.pack(fill=tk.X, padx=8)
        self._param_row(
            self._frame_gliss_params, "Densidade (%):", "gliss_prob",
            "scale", from_=1, to=100, resolution=1, default=20,
            tooltip=(
                "Probabilidade base de glissando entre duas notas consecutivas.\n"
                "O intervalo entre as notas pondera levemente a probabilidade:\n"
                "  intervalos maiores têm chance ligeiramente maior,\n"
                "  mas todos os pares são elegíveis."
            ),
        )
        self._frame_gliss_params.pack_forget()  # oculto até habilitar

        # Tempo
        grp2 = self._section_group(parent, "Tempo e Compasso")
        self._param_row(grp2, "BPM:", "bpm",
                        "spinbox", from_=20, to=400, width=5)
        self._param_row(grp2, "Fórmula:", "time_sig",
                        "combobox", values=TIME_SIGS)

        # Mudanças aleatórias de compasso
        self._var_random_ts = tk.BooleanVar(value=False)
        rc = tk.Frame(grp2, bg=C["bg_panel"])
        rc.pack(fill=tk.X, padx=8, pady=2)
        tk.Checkbutton(
            rc, text="Mudanças aleatórias de compasso",
            variable=self._var_random_ts,
            bg=C["bg_panel"], fg=C["text"],
            selectcolor=C["bg_input"],
            activebackground=C["bg_panel"], activeforeground=C["accent"],
            font=FONT_LABEL, bd=0,
            command=self._on_random_ts_toggle,
        ).pack(side=tk.LEFT)

        self._frame_ts_prob = tk.Frame(grp2, bg=C["bg_panel"])
        self._frame_ts_prob.pack(fill=tk.X, padx=8)
        self._param_row(self._frame_ts_prob, "Prob. mudança (%):", "ts_change_prob",
                        "scale", from_=5, to=80, resolution=5, default=25,
                        tooltip="% de chance de mudar a formula a cada compasso.")

    def _on_random_ts_toggle(self):
        if self._var_random_ts.get():
            self._frame_ts_prob.pack(fill=tk.X, padx=8)
        else:
            self._frame_ts_prob.pack_forget()

    def _on_tuplets_toggle(self):
        if self._var_tuplets.get():
            self._frame_tuplet_params.pack(fill=tk.X, padx=8)
        else:
            self._frame_tuplet_params.pack_forget()

    def _on_glissando_toggle(self):
        if self._var_glissando.get():
            self._frame_gliss_params.pack(fill=tk.X, padx=8)
        else:
            self._frame_gliss_params.pack_forget()

    def _on_open_analise_folder(self):
        """Abre a pasta de análise no Finder/Explorer."""
        if not self._last_result:
            return
        af = getattr(self._last_result, "analysis_files", {})
        if not af:
            messagebox.showinfo("Análise", "Nenhum arquivo de análise disponível.")
            return
        # Abrir a pasta que contém os arquivos (todos estão no mesmo diretório)
        first_file = next(iter(af.values()), None)
        if not first_file:
            return
        folder = str(Path(first_file).parent)
        try:
            _sys = platform.system()
            if _sys == "Darwin":
                subprocess.Popen(["open", folder])
            elif _sys == "Windows":
                os.startfile(folder)
            else:
                subprocess.Popen(["xdg-open", folder])
        except Exception as e:
            messagebox.showerror("Erro", f"Não foi possível abrir a pasta:\n{e}")

    def _build_tab_micro(self, parent):
        grp = self._section_group(parent, "Microtonalismo")

        self._var_microtones = tk.BooleanVar(value=True)
        mc = tk.Frame(grp, bg=C["bg_panel"])
        mc.pack(fill=tk.X, padx=8, pady=4)
        tk.Checkbutton(
            mc, text="Habilitar quartos de tom (LilyPond nativo)",
            variable=self._var_microtones,
            bg=C["bg_panel"], fg=C["text"],
            selectcolor=C["bg_input"],
            activebackground=C["bg_panel"], activeforeground=C["accent"],
            font=FONT_LABEL, bd=0,
            command=self._on_micro_toggle,
        ).pack(side=tk.LEFT)

        self._frame_micro_params = tk.Frame(grp, bg=C["bg_panel"])
        self._frame_micro_params.pack(fill=tk.X)
        self._param_row(self._frame_micro_params, "Densidade (%):",
                        "micro_prob", "scale", from_=5, to=50, resolution=1)

        # Nota explicativa
        note_frame = tk.Frame(parent, bg=C["bg_panel"])
        note_frame.pack(fill=tk.X, padx=16, pady=(8, 0))
        note_text = (
            "Sistema holandês nativo do LilyPond 2.24:\n"
            "  +50¢  → sufixo ih   (ex: dih')    semissustenido\n"
            "  −50¢  → sufixo eh   (ex: deh')    semibemol\n"
            "  +150¢ → sufixo isih (ex: cisih')  sustenido e meio\n"
            "  −150¢ → sufixo eseh (ex: beseh')  bemol e meio"
        )
        tk.Label(note_frame, text=note_text,
                 bg=C["bg_panel"], fg=C["text_dim"],
                 font=FONT_LOG, justify=tk.LEFT,
                 padx=4, pady=4).pack(anchor="w")

        # Técnicas estendidas por família
        grp2 = self._section_group(parent, "Técnicas Estendidas por Família")
        families = {
            "Cordas (10)":    "sul pont. · sul tasto · col legno · harmônico\npizzicato · snap pizzicato · tremolo",
            "Madeiras (7)":   "flutter tongue · multifônico · harmônico\nextended breath · air tone · tremolo",
            "Metais (5)":     "flutter tongue · multifônico · extended breath\ntremolo",
            "Teclados (3)":   "tremolo medido / não-medido",
        }
        for fam, techs in families.items():
            row = tk.Frame(grp2, bg=C["bg_panel"])
            row.pack(fill=tk.X, padx=8, pady=2)
            tk.Label(row, text=f"{fam}:", bg=C["bg_panel"],
                     fg=C["accent"], font=FONT_LABEL_B, width=14,
                     anchor="w").pack(side=tk.LEFT)
            tk.Label(row, text=techs, bg=C["bg_panel"],
                     fg=C["text_dim"], font=FONT_LOG,
                     justify=tk.LEFT).pack(side=tk.LEFT, padx=4)

    def _on_micro_toggle(self):
        if self._var_microtones.get():
            self._frame_micro_params.pack(fill=tk.X)
        else:
            self._frame_micro_params.pack_forget()

    def _build_tab_notation(self, parent):
        grp = self._section_group(parent, "Metadados")
        self._param_row(grp, "Título:", "title", "entry", width=32)
        self._param_row(grp, "Compositor:", "composer", "entry", width=32)

        grp2 = self._section_group(parent, "Tipo de Notação")
        self._var_notation = tk.StringVar(value="NORMAL")
        for val, label, desc in [
            ("NORMAL",       "Notação tradicional",
             "barras de compasso · durações métricas"),
            ("PROPORTIONAL", "Notação proporcional",
             "espaço = tempo real · sem barras (Feldman-like)"),
        ]:
            row = tk.Frame(grp2, bg=C["bg_panel"])
            row.pack(fill=tk.X, padx=8, pady=3)
            tk.Radiobutton(
                row, text=label, variable=self._var_notation, value=val,
                bg=C["bg_panel"], fg=C["text"],
                selectcolor=C["bg_input"],
                activebackground=C["bg_panel"], activeforeground=C["accent"],
                font=FONT_LABEL, bd=0,
            ).pack(side=tk.LEFT)
            tk.Label(row, text=f"  {desc}", bg=C["bg_panel"],
                     fg=C["text_dim"], font=FONT_LOG).pack(side=tk.LEFT)

        grp3 = self._section_group(parent, "Saída")
        self._var_open_pdf = tk.BooleanVar(value=True)
        tk.Checkbutton(
            grp3, text="Abrir PDF após gerar",
            variable=self._var_open_pdf,
            bg=C["bg_panel"], fg=C["text"],
            selectcolor=C["bg_input"],
            activebackground=C["bg_panel"], activeforeground=C["accent"],
            font=FONT_LABEL, bd=0,
        ).pack(anchor="w", padx=8, pady=4)

        # Orientação PDF
        orient_row = tk.Frame(grp3, bg=C["bg_panel"])
        orient_row.pack(fill=tk.X, padx=8, pady=2)
        tk.Label(orient_row, text="Orientação PDF:",
                 bg=C["bg_panel"], fg=C["text_dim"], font=FONT_LABEL,
                 width=18, anchor="w").pack(side=tk.LEFT)
        self._var_landscape = tk.StringVar(value="retrato")
        for _txt, _val in [("Retrato (A4)", "retrato"), ("Paisagem (A4)", "paisagem")]:
            tk.Radiobutton(
                orient_row, text=_txt, variable=self._var_landscape, value=_val,
                bg=C["bg_panel"], fg=C["text"],
                selectcolor=C["bg_input"],
                activebackground=C["bg_panel"], activeforeground=C["accent"],
                font=FONT_LABEL, bd=0,
            ).pack(side=tk.LEFT, padx=6)

        # Diretório de saída
        dir_row = tk.Frame(grp3, bg=C["bg_panel"])
        dir_row.pack(fill=tk.X, padx=8, pady=4)
        tk.Label(dir_row, text="Pasta:", bg=C["bg_panel"],
                 fg=C["text"], font=FONT_LABEL, width=10,
                 anchor="w").pack(side=tk.LEFT)
        self._var_output_dir = tk.StringVar(value="output")
        tk.Entry(
            dir_row, textvariable=self._var_output_dir,
            bg=C["bg_input"], fg=C["text"],
            insertbackground=C["text"], font=FONT_MONO,
            bd=0, width=22,
        ).pack(side=tk.LEFT, padx=(0, 4))
        self._mk_small_btn(
            dir_row, "…",
            lambda: self._choose_output_dir()
        ).pack(side=tk.LEFT)

    def _choose_output_dir(self):
        d = filedialog.askdirectory(title="Selecionar pasta de saída")
        if d:
            self._var_output_dir.set(d)

    # ── Footer: botão de geração, progresso, log ──────────────────

    def _build_footer(self):
        # Linha separadora
        tk.Frame(self, bg=C["border"], height=1).pack(fill=tk.X, padx=0)

        footer = tk.Frame(self, bg=C["bg"], pady=10)
        footer.pack(fill=tk.BOTH, padx=16, pady=(0, 0))

        # Linha de ação
        action_row = tk.Frame(footer, bg=C["bg"])
        action_row.pack(fill=tk.X, pady=(0, 6))

        # Botão principal
        self._btn_generate = tk.Button(
            action_row,
            text="  ▶  GERAR COMPOSIÇÃO  ",
            command=self._on_generate,
            bg=C["accent"], fg=C["bg"],
            activebackground=C["accent_hover"], activeforeground=C["bg"],
            font=FONT_BTN, bd=0, padx=12, pady=6, cursor="hand2",
            relief="flat",
        )
        self._btn_generate.pack(side=tk.LEFT)

        # Label de status
        self._var_status = tk.StringVar(value="Pronto.")
        tk.Label(action_row, textvariable=self._var_status,
                 bg=C["bg"], fg=C["text_dim"],
                 font=FONT_LABEL).pack(side=tk.LEFT, padx=16)

        # Barra de progresso — sem style customizado (compatível macOS/clam)
        self._progress = ttk.Progressbar(
            action_row, mode="indeterminate", length=160,
        )
        self._progress.pack(side=tk.RIGHT)

        # Botões de resultado (inicialmente ocultos)
        self._result_bar = tk.Frame(footer, bg=C["bg"])
        self._result_bar.pack(fill=tk.X, pady=(0, 4))

        self._btn_open_pdf = self._mk_small_btn(
            self._result_bar, "Abrir PDF",
            lambda: self._open_file(self._last_result.pdf_path
                                    if self._last_result else None))
        self._btn_open_ly  = self._mk_small_btn(
            self._result_bar, "Ver .ly",
            lambda: self._open_file(self._last_result.ly_path
                                    if self._last_result else None))
        self._btn_open_xml = self._mk_small_btn(
            self._result_bar, "Abrir MusicXML",
            lambda: self._on_open_xml())
        self._btn_dashboard = self._mk_small_btn(
            self._result_bar, "📊 Dashboard",
            lambda: self._open_file(
                self._last_result.dashboard_path
                if self._last_result else None))
        self._btn_analise = self._mk_small_btn(
            self._result_bar, "📁 Análise",
            lambda: self._on_open_analise_folder())
        self._btn_export   = self._mk_small_btn(
            self._result_bar, "Exportar Matrizes CSV",
            lambda: self._export_matrices())

        for btn in [self._btn_open_pdf, self._btn_open_ly, self._btn_open_xml,
                    self._btn_dashboard, self._btn_analise, self._btn_export]:
            btn.pack(side=tk.LEFT, padx=(0, 6))
            btn.config(state="disabled")

        # Log
        tk.Frame(footer, bg=C["border"], height=1).pack(fill=tk.X, pady=(4, 6))
        log_frame = tk.Frame(footer, bg=C["bg"])
        log_frame.pack(fill=tk.BOTH, expand=True)

        self._log = tk.Text(
            log_frame,
            bg=C["bg_panel"], fg=C["text_dim"],
            font=FONT_LOG, bd=0,
            state="disabled",
            height=8,
            wrap=tk.WORD,
            insertbackground=C["text"],
        )
        vsb = tk.Scrollbar(log_frame, command=self._log.yview,
                           bg=C["bg_input"], troughcolor=C["bg_panel"],
                           bd=0, width=8)
        self._log.configure(yscrollcommand=vsb.set)
        vsb.pack(side=tk.RIGHT, fill=tk.Y)
        self._log.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)

        # Tags de cor no log
        self._log.tag_configure("ok",    foreground=C["success"])
        self._log.tag_configure("err",   foreground=C["error"])
        self._log.tag_configure("hdr",   foreground=C["accent"])
        self._log.tag_configure("dim",   foreground=C["text_dim"])
        self._log.tag_configure("value", foreground=C["text"])

        self._log_write("Markov-Abjad Composer inicializado.\n", "dim")
        self._log_write("Selecione instrumentos e parâmetros, depois clique em Gerar.\n", "dim")

    # ── Geração ───────────────────────────────────────────────────

    def _on_generate(self):
        if self._generating:
            return

        instruments = self._get_selected_instruments()
        if not instruments:
            messagebox.showwarning(
                "Instrumentos", "Selecione pelo menos um instrumento.",
                parent=self)
            return

        # Montar config
        config = self._build_config(instruments)
        if config is None:
            return

        # Iniciar geração em thread separada
        self._generating = True
        self._btn_generate.config(state="disabled", bg=C["accent_dim"])
        self._progress.start(12)
        self._var_status.set("Gerando composição…")

        # Desabilitar botões de resultado
        for btn in [self._btn_open_pdf, self._btn_open_ly, self._btn_open_xml,
                    self._btn_dashboard, self._btn_analise, self._btn_export]:
            btn.config(state="disabled")

        self._log_write("\n", "dim")
        self._log_write(f"▶  {config.title}\n", "hdr")
        self._log_write(
            f"   Instrumentos: {', '.join(instruments)}\n", "dim")
        self._log_write(
            f"   {config.n_notes} notas · ordem {config.markov_order} · "
            f"{config.time_signature} · {config.tempo_bpm} BPM\n", "dim")

        def worker():
            # Se MIDI foi analisado, usar trainers para treinamento real
            midi_info = ""
            if getattr(self, "_midi_trained", False):
                # Coletar todos os trainers carregados do corpus
                trainers = [
                    e["trainer"] for e in getattr(self, "_midi_corpus", [])
                    if e.get("trainer") and e["trainer"]._loaded
                ]
                # Fallback: trainer legado (compatibilidade com código antigo)
                if not trainers and self._midi_trainer:
                    trainers = [self._midi_trainer]
                try:
                    from integration import _gerar_com_midi_trainer
                    result = _gerar_com_midi_trainer(config, trainers)
                    n_notes = sum(len(t.pitches) for t in trainers)
                    nomes = ", ".join(
                        Path(t.midi_path).name for t in trainers
                    )
                    if len(nomes) > 60:
                        nomes = nomes[:58] + "…"
                    midi_info = (
                        f"   Treinamento: {len(trainers)} MIDI(s)"
                        f" · {n_notes} notas no corpus\n"
                        f"   Arquivos: {nomes}\n"
                    )
                except Exception as e:
                    # Fallback para uniforme
                    result = gerar_composicao(config)
                    midi_info = f"   Treinamento: uniforme (MIDI falhou: {e})\n"
            else:
                result = gerar_composicao(config)
                midi_info = "   Treinamento: distribuição uniforme\n"
            self.after(0, lambda: self._on_generation_done(result, midi_info))

        threading.Thread(target=worker, daemon=True).start()

    def _on_generation_done(self, result: CompositionResult, midi_info: str = ""):
        self._generating = False
        self._progress.stop()
        self._btn_generate.config(state="normal", bg=C["accent"])
        self._last_result = result

        if result.success:
            self._var_status.set(
                f"✓ PDF gerado em {result.duration_seconds}s")

            self._log_write("✓ Composição gerada com sucesso!\n", "ok")
            self._log_write(f"  PDF: {result.pdf_path}\n", "value")
            self._log_write(f"  .ly: {result.ly_path}\n", "value")
            if result.xml_path:
                self._log_write(f"  .xml: {result.xml_path}\n", "value")
            if midi_info:
                self._log_write(midi_info, "dim")
            self._log_write(
                f"  Total: {result.n_events_total} eventos · "
                f"{result.duration_seconds}s\n", "dim")

            # Estatísticas
            self._log_write("  Estatísticas:\n", "dim")
            for instr, s in result.stats.items():
                techs = list(s["tecnicas"].keys())
                self._log_write(
                    f"    {instr:16} notas={s['notas']:3}  "
                    f"pausas={s['pausas']:2}  micros={s['micros']:2}  "
                    f"técnicas={len(techs)}\n", "dim")

            # Habilitar botões de resultado
            self._btn_open_pdf.config(state="normal")
            self._btn_open_ly.config(state="normal")
            self._btn_export.config(state="normal")
            # Habilitar botão XML: mostra arquivo ou aviso de erro
            self._btn_open_xml.config(state="normal")
            if not result.xml_path:
                err = getattr(result, "xml_error", None) or "Export XML falhou."
                self._log_write(f"  ⚠ MusicXML: {err}\n", "dim")
            # Dashboard de análise
            if getattr(result, "dashboard_path", None):
                self._btn_dashboard.config(state="normal")
                self._log_write(f"  Dashboard: {result.dashboard_path}\n", "value")
            # Arquivos de análise
            if getattr(result, "analysis_files", None):
                self._btn_analise.config(state="normal")
                af = result.analysis_files
                self._log_write(f"  Arquivos de análise ({len(af)} arquivos):\n", "value")
                label_map = {
                    "relatorio":       "  Relatório (.txt)",
                    "json":            "  Dados completos (.json)",
                    "eventos_csv":     "  Eventos brutos (.csv)",
                    "resumo_csv":      "  Resumo por instrumento (.csv)",
                    "dist_dinamicas":  "  Dist. dinâmicas (.csv)",
                    "dist_duracoes":   "  Dist. durações (.csv)",
                    "dist_pitch":      "  Dist. pitch (.csv)",
                    "dist_tecnicas":   "  Dist. técnicas (.csv)",
                    "dist_microtons":  "  Dist. microtons (.csv)",
                }
                for key, path in af.items():
                    label = label_map.get(key, f"  {key}")
                    self._log_write(f"    {label}: {path}\n", "dim")

            # Abrir PDF automaticamente se o usuário marcou essa opção
            # (feito aqui na GUI, após confirmação de sucesso, não no pipeline)
            if getattr(self, "_var_open_pdf", None) and self._var_open_pdf.get():
                self._open_file(result.pdf_path)
        else:
            self._var_status.set("✗ Erro na geração")
            self._log_write(f"✗ Erro: {result.error_message}\n", "err")
            if result.ly_path:
                self._btn_open_ly.config(state="normal")

    def _build_config(self, instruments: list[str]) -> Optional[CompositionConfig]:
        try:
            notation_map = {
                "NORMAL": NotationType.NORMAL,
                "PROPORTIONAL": NotationType.PROPORTIONAL,
            }
            # Pesos de dinâmica (normalizar para soma=1 se todos > 0)
            _dyn_keys   = ["dyn_ppp","dyn_pp","dyn_p","dyn_mp",
                           "dyn_mf","dyn_f","dyn_ff","dyn_fff"]
            _dyn_raw    = [int(self._vars[k].get()) for k in _dyn_keys]
            _dyn_sum    = sum(_dyn_raw) or 1
            _dyn_norm   = [w / _dyn_sum for w in _dyn_raw]

            # Complexidade de quiálteras (extrair número do início)
            _cplx_str   = self._vars.get("tuplet_complexity", tk.StringVar(value="1")).get()
            _cplx       = int(_cplx_str[0]) if _cplx_str else 1

            return CompositionConfig(
                instruments            = instruments,
                markov_order           = int(self._vars["markov_order"].get()),
                n_notes                = int(self._vars["n_notes"].get()),
                allow_microtones       = self._var_microtones.get(),
                microtone_probability  = int(self._vars["micro_prob"].get()) / 100,
                rest_probability       = int(self._vars["rest_prob"].get()) / 100,
                dynamic_weights        = _dyn_norm,
                use_hairpins           = self._var_hairpins.get(),
                tuplet_probability     = (int(self._vars["tuplet_prob"].get()) / 100
                                          if self._var_tuplets.get() else 0.0),
                tuplet_complexity      = _cplx,
                title                  = self._vars["title"].get().strip() or
                                         "Composição Algorítmica",
                composer               = self._vars["composer"].get().strip(),
                tempo_bpm              = int(self._vars["bpm"].get()),
                time_signature         = self._vars["time_sig"].get(),
                random_time_changes    = self._var_random_ts.get(),
                time_change_probability= int(self._vars.get(
                    "ts_change_prob", tk.IntVar(value=15)).get()) / 100,
                notation_type          = notation_map.get(
                    self._var_notation.get(), NotationType.NORMAL),
                proportional_notation  = (self._var_notation.get() == "PROPORTIONAL"),
                output_dir             = self._var_output_dir.get() or "output",
                open_pdf               = False,   # GUI abre após confirmar sucesso
                landscape              = (self._var_landscape.get() == "paisagem"),
                glissando_probability  = (
                    int(self._vars["gliss_prob"].get()) / 100
                    if self._var_glissando.get() else 0.0
                ),
            )
        except Exception as e:
            messagebox.showerror("Parâmetro inválido", str(e), parent=self)
            return None

    # ── Ações de resultado ────────────────────────────────────────

    def _on_open_xml(self):
        """Abre o MusicXML ou mostra o motivo pelo qual não foi gerado."""
        if not self._last_result:
            return
        if self._last_result.xml_path and Path(self._last_result.xml_path).exists():
            self._open_file(self._last_result.xml_path)
        else:
            err = getattr(self._last_result, "xml_error", None) or "Arquivo não encontrado."
            messagebox.showwarning(
                "MusicXML indisponível",
                f"O arquivo MusicXML não foi gerado.\n\n{err}",
                parent=self,
            )

    def _open_file(self, path: Optional[str]):
        if not path or not Path(path).exists():
            messagebox.showwarning("Arquivo não encontrado",
                                   f"Arquivo não existe:\n{path}", parent=self)
            return
        system = platform.system()
        if system == "Darwin":
            subprocess.Popen(["open", path])
        elif system == "Windows":
            os.startfile(path)
        else:
            subprocess.Popen(["xdg-open", path])

    def _export_matrices(self):
        if not self._last_result:
            return
        d = filedialog.askdirectory(title="Exportar matrizes para…", parent=self)
        if not d:
            return
        # Re-gerar engine com os mesmos parâmetros para exportar matrizes
        self._log_write("⚠ Exportação de matrizes: recrie a engine via linha de comando.\n", "dim")
        messagebox.showinfo(
            "Exportar Matrizes",
            "Para exportar as matrizes CSV, use:\n\n"
            "  engine.export_matrices('pasta/')\n\n"
            "A feature de exportação direta será adicionada na próxima versão.",
            parent=self,
        )

    # ── Helpers de layout ─────────────────────────────────────────

    def _section_title(self, parent, text: str) -> tk.Label:
        f = tk.Frame(parent, bg=C["bg_panel"])
        f.pack(fill=tk.X, padx=8, pady=(10, 4))
        lbl = tk.Label(f, text=text,
                       bg=C["bg_panel"], fg=C["text_header"], font=FONT_HEADER)
        lbl.pack(side=tk.LEFT)
        tk.Frame(f, bg=C["border"], height=1).pack(
            side=tk.LEFT, fill=tk.X, expand=True, padx=(8, 0), pady=6)
        return lbl

    def _scrollable_tab(self, tab_frame: "tk.Frame") -> "tk.Frame":
        """
        Transforma um tk.Frame de tab em container scrollável.
        Retorna o Frame interno onde os widgets devem ser adicionados.
        Suporta scroll com roda do mouse (Windows, Linux, macOS).
        """
        canvas = tk.Canvas(tab_frame, bg=C["bg_panel"], highlightthickness=0)
        vsb = tk.Scrollbar(tab_frame, orient="vertical", command=canvas.yview,
                           bg=C["bg_input"], troughcolor=C["bg_panel"],
                           bd=0, width=8)
        canvas.configure(yscrollcommand=vsb.set)
        vsb.pack(side=tk.RIGHT, fill=tk.Y)
        canvas.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)

        inner = tk.Frame(canvas, bg=C["bg_panel"])
        win_id = canvas.create_window((0, 0), window=inner, anchor="nw")

        def _on_inner_configure(e):
            canvas.configure(scrollregion=canvas.bbox("all"))

        def _on_canvas_configure(e):
            canvas.itemconfig(win_id, width=e.width)

        inner.bind("<Configure>", _on_inner_configure)
        canvas.bind("<Configure>", _on_canvas_configure)

        def _on_mousewheel(e):
            canvas.yview_scroll(int(-1 * (e.delta / 120)), "units")

        def _on_linux_scroll(e):
            canvas.yview_scroll(-1 if e.num == 4 else 1, "units")

        def _bind_scroll(e=None):
            canvas.bind_all("<MouseWheel>", _on_mousewheel)
            canvas.bind_all("<Button-4>", _on_linux_scroll)
            canvas.bind_all("<Button-5>", _on_linux_scroll)

        def _unbind_scroll(e=None):
            canvas.unbind_all("<MouseWheel>")
            canvas.unbind_all("<Button-4>")
            canvas.unbind_all("<Button-5>")

        # Ativar scroll apenas quando mouse está sobre esta tab
        canvas.bind("<Enter>", _bind_scroll)
        canvas.bind("<Leave>", _unbind_scroll)
        inner.bind("<Enter>", _bind_scroll)

        return inner

    def _section_group(self, parent, title: str) -> tk.Frame:
        lf = ttk.LabelFrame(parent, text=f" {title} ",
                            style="Dark.TLabelframe", padding=(0, 4))
        lf.pack(fill=tk.X, padx=12, pady=(8, 0))
        return lf

    def _param_row(self, parent, label: str, key: str, wtype: str, **kwargs):
        row = tk.Frame(parent, bg=C["bg_panel"])
        row.pack(fill=tk.X, padx=8, pady=3)

        tk.Label(row, text=label, bg=C["bg_panel"], fg=C["text"],
                 font=FONT_LABEL, width=22, anchor="w").pack(side=tk.LEFT)

        tooltip = kwargs.pop("tooltip", None)

        if wtype == "spinbox":
            var = tk.IntVar(value=kwargs.pop("default", kwargs.get("from_", 1)))
            w = tk.Spinbox(
                row, textvariable=var,
                bg=C["bg_input"], fg=C["text"],
                buttonbackground=C["bg_input"],
                insertbackground=C["text"],
                font=FONT_MONO, bd=0,
                relief="flat",
                **kwargs,
            )
            w.pack(side=tk.LEFT)
            self._vars[key] = var

        elif wtype == "scale":
            resolution = kwargs.pop("resolution", 1)
            from_  = kwargs.pop("from_", 0)
            to     = kwargs.pop("to", 100)
            default= kwargs.pop("default", (from_ + to) // 2)
            var = tk.IntVar(value=default)
            f = tk.Frame(row, bg=C["bg_panel"])
            f.pack(side=tk.LEFT)
            sc = tk.Scale(
                f, variable=var, from_=from_, to=to,
                resolution=resolution, orient=tk.HORIZONTAL,
                length=140,
                bg=C["bg_panel"], fg=C["text"],
                activebackground=C["accent"],
                troughcolor=C["bg_input"],
                highlightthickness=0, bd=0,
                font=FONT_LOG, sliderlength=12,
            )
            sc.pack(side=tk.LEFT)
            val_lbl = tk.Label(f, textvariable=var,
                               bg=C["bg_panel"], fg=C["accent"],
                               font=FONT_LABEL_B, width=4)
            val_lbl.pack(side=tk.LEFT)
            self._vars[key] = var

        elif wtype == "combobox":
            var = tk.StringVar(value=kwargs.get("values", [""])[0])
            cb = ttk.Combobox(
                row, textvariable=var, state="readonly",
                font=FONT_MONO, width=kwargs.pop("width", 10),
                style="Dark.TCombobox",
                values=kwargs.get("values", []),
            )
            cb.pack(side=tk.LEFT)
            self._vars[key] = var

        elif wtype == "entry":
            var = tk.StringVar(value=kwargs.pop("default", ""))
            e = tk.Entry(
                row, textvariable=var,
                bg=C["bg_input"], fg=C["text"],
                insertbackground=C["text"],
                font=FONT_MONO, bd=0,
                relief="flat",
                width=kwargs.pop("width", 20),
            )
            e.pack(side=tk.LEFT)
            self._vars[key] = var

        if tooltip:
            tk.Label(row, text=f"  ↳ {tooltip}",
                     bg=C["bg_panel"], fg=C["text_dim"],
                     font=FONT_LOG).pack(side=tk.LEFT, padx=4)

    def _mk_small_btn(self, parent, text: str, command) -> tk.Button:
        return tk.Button(
            parent, text=text, command=command,
            bg=C["bg_input"], fg=C["text_dim"],
            activebackground=C["border"], activeforeground=C["text"],
            font=FONT_LOG, bd=0, padx=6, pady=2,
            cursor="hand2", relief="flat",
        )

    # ── Log ───────────────────────────────────────────────────────

    def _log_write(self, text: str, tag: str = ""):
        self._log.config(state="normal")
        if tag:
            self._log.insert(tk.END, text, tag)
        else:
            self._log.insert(tk.END, text)
        self._log.see(tk.END)
        self._log.config(state="disabled")


# ─────────────────────────────────────────────────────────────────────────────
#  Entry point
# ─────────────────────────────────────────────────────────────────────────────

def main():
    app = MarkovAbjadApp()
    app.mainloop()


if __name__ == "__main__":
    main()
