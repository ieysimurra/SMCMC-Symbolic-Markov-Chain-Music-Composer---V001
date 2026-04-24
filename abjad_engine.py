"""
abjad_engine.py
===============
Motor de notação: converte NoteEvent → objetos Abjad → código LilyPond → PDF.

Responsabilidades:
  - Traduzir NoteEvent para abjad.Note / abjad.Rest / abjad.Chord
  - Aplicar dinâmicas, técnicas e marcações microtônicas
  - Montar Staff, Score e bloco LilyPond completo
  - Compilar para PDF via subprocess (LilyPond local)
  - Suporte a notação proporcional

NÃO usa music21.lily.translate — geração 100% manual.

Dependências: abjad 3.x, LilyPond 2.24+ instalado localmente.
"""

from __future__ import annotations

import subprocess
import tempfile
import os
import shutil
from fractions import Fraction
from pathlib import Path
from typing import List, Dict, Optional, Tuple

import abjad
from percussion import (
    resolve_drum_voice, drum_voice_to_lily_pitch,
    NOTEHEAD_OVERRIDE, NOTEHEAD_REVERT,
    is_unpitched_percussion,
)

from note_event import (
    NoteEvent, Dynamic, Technique, Microtone, NotationType
)


# ─────────────────────────────────────────────────────────────
#  Constantes
# ─────────────────────────────────────────────────────────────

LILY_VERSION = "2.24.4"

# Claves padrão por instrumento (nome canônico)
_INSTRUMENT_CLEF_CANONICAL: Dict[str, str] = {
    "Flute":        "treble",
    "Oboe":         "treble",
    "Clarinet":     "treble",
    "Bassoon":      "bass",
    "Horn":         "treble",
    "Trumpet":      "treble",
    "Trombone":     "bass",
    "Tuba":         "bass",
    "Violin":       "treble",
    "Viola":        "alto",
    "Violoncello":  "bass",
    "Double Bass":  "bass",
    "Piano":        "treble",
    "Harp":         "treble",
    # Percussão de altura definida
    "Vibraphone":   "treble",
    "Marimba":      "treble",
    "Xylophone":    "treble",
    "Glockenspiel": "treble",
    "Timpani":      "bass",
    "Crotales":     "treble",
    # Percussão de altura indefinida → clave de percussão
    "Snare Drum":       "percussion",
    "Bass Drum":        "percussion",
    "Tan-Tan":          "percussion",
    "Tom High":         "percussion",
    "Tom Mid":          "percussion",
    "Tom Low":          "percussion",
    "Floor Tom":        "percussion",
    "Gong":             "percussion",
    "Hi-Hat":           "percussion",
    "Ride Cymbal":      "percussion",
    "Crash Cymbal":     "percussion",
    "Suspended Cymbal": "percussion",
    "Cymbals (clash)":  "percussion",
    "Tam-Tam":          "percussion",
    "China/Splash":     "percussion",
    "Triangle":         "percussion",
    "Woodblock":        "percussion",
    "Cowbell":          "percussion",
    "Tambourine":       "percussion",
    "Claves":           "percussion",
    "Vibraslap":        "percussion",
}

def _resolve_clef(instrument_name: str) -> str:
    """
    Retorna a clave para um instrumento, resolvendo variantes como
    "Violin #1", "Viola #2", "Clarinet #3" para o nome canônico.
    """
    # Remover sufixo de dobra: "Violin #2" → "Violin"
    base = instrument_name.split(" #")[0].strip()
    return _INSTRUMENT_CLEF_CANONICAL.get(base, "treble")

# Manter compatibilidade — usado em alguns lugares como dict
INSTRUMENT_CLEF: Dict[str, str] = _INSTRUMENT_CLEF_CANONICAL


# ─────────────────────────────────────────────────────────────
#  Conversor NoteEvent → Abjad
# ─────────────────────────────────────────────────────────────

def note_event_to_abjad(event: NoteEvent) -> abjad.Leaf:
    """
    Converte um NoteEvent para um objeto Abjad (Note, Rest ou Chord).

    Aplica:
      - Pitch com microtone (via NamedPitch do Abjad)
      - Duração (via abjad.Duration com fração exata)
      - Dinâmica
      - Técnica estendida (markup e/ou command nativo)
      - Ligaduras de valor (tie)
      - Tremolo (barras)
    """
    # Duração Abjad (requer numerador/denominador)
    frac = event.duration
    abjad_duration = abjad.Duration(frac.numerator, frac.denominator)

    # ── Criar o objeto folha (leaf) ────────────────────────────
    if event.is_rest or not event.is_pitched:
        leaf = abjad.Rest(abjad_duration)
    else:
        # Pitch com microtone
        pitch_str = event.full_pitch_name
        try:
            named_pitch = abjad.NamedPitch(pitch_str)
            leaf = abjad.Note(named_pitch, abjad_duration)
        except Exception:
            # Fallback: ignorar microtone se inválido
            leaf = abjad.Note(abjad.NamedPitch(event.pitch_name), abjad_duration)

    # ── Dinâmica ───────────────────────────────────────────────
    if not event.is_rest:
        _attach_dynamic(leaf, event.dynamic)

    # ── Técnica estendida ──────────────────────────────────────
    if event.technique != Technique.ORDINARIO and not event.is_rest:
        _attach_technique(leaf, event.technique, event.tremolo_strokes)

    # ── Markup adicional ───────────────────────────────────────
    if event.markup_above:
        markup = abjad.Markup(event.markup_above, direction=abjad.UP)
        abjad.attach(markup, leaf)
    if event.markup_below:
        markup = abjad.Markup(event.markup_below, direction=abjad.DOWN)
        abjad.attach(markup, leaf)

    return leaf


def _attach_dynamic(leaf: abjad.Leaf, dynamic: Dynamic) -> None:
    """Anexa indicação dinâmica ao leaf Abjad."""
    if dynamic == Dynamic.NIENTE:
        # Niente: círculo (°) — usamos markup simples abaixo da nota
        markup = abjad.Markup(r'\markup { "°" }', direction=abjad.DOWN)
        try:
            abjad.attach(markup, leaf)
        except Exception:
            pass
    else:
        try:
            dyn = abjad.Dynamic(dynamic.value)
            abjad.attach(dyn, leaf)
        except Exception:
            pass


def _attach_technique(
    leaf: abjad.Leaf,
    technique: Technique,
    tremolo_strokes: int = 0
) -> None:
    """
    Anexa indicação de técnica estendida ao leaf.
    Usa comandos nativos do Abjad quando disponíveis;
    markup textual nos demais casos.
    """
    # Harmônico: flageolet nativo
    if technique == Technique.HARMONIC:
        try:
            abjad.attach(abjad.Articulation("flageolet"), leaf)
        except Exception:
            pass

    # Snap pizzicato nativo
    elif technique == Technique.SNAP_PIZZICATO:
        try:
            abjad.attach(abjad.Articulation("snappizzicato"), leaf)
        except Exception:
            pass

    # Tremolo medido (barras)
    elif technique == Technique.TREMOLO_MEASURED and tremolo_strokes > 0:
        try:
            cmd = abjad.LilyPondLiteral(
                f":{ 2 ** (tremolo_strokes + 1) }",
                format_slot="after"
            )
            abjad.attach(cmd, leaf)
        except Exception:
            pass

    # Todas as outras técnicas: markup textual (acima)
    else:
        markup_str = technique.lilypond_markup()
        if markup_str:
            try:
                markup = abjad.Markup(markup_str, direction=abjad.UP)
                abjad.attach(markup, leaf)
            except Exception:
                pass


# ─────────────────────────────────────────────────────────────
#  Montagem da partitura
# ─────────────────────────────────────────────────────────────

def build_staff(
    events: List[NoteEvent],
    instrument_name: str = "Violin",
    time_signature: Tuple[int, int] = (4, 4),
    clef: str = "treble",
) -> abjad.Staff:
    """
    Constrói um abjad.Staff a partir de uma lista de NoteEvents.

    Gerencia:
      - Conversão de cada evento
      - Preenchimento de compassos (medidas)
      - Inserção de indicações de tempo e clave
    """
    staff = abjad.Staff(name=instrument_name)

    # Clave
    clef_name = _resolve_clef(instrument_name)
    abjad.attach(abjad.Clef(clef_name), staff)

    # Fórmula de compasso
    ts_num, ts_den = time_signature
    abjad_ts = abjad.TimeSignature((ts_num, ts_den))
    measure_duration = Fraction(ts_num, ts_den)

    # Converter todos os eventos em leaves
    leaves = [note_event_to_abjad(ev) for ev in events]

    # Preencher staff com leaves diretamente (Abjad gerencia medidas internamente)
    staff.extend(leaves)

    # Inserir fórmula de compasso no primeiro leaf
    if len(staff) > 0:
        abjad.attach(abjad_ts, staff[0])

    return staff


def build_score(
    parts: List[Tuple[str, List[NoteEvent]]],
    title: str = "Composição Algorítmica",
    composer: str = "",
    tempo_bpm: int = 60,
    time_signature: Tuple[int, int] = (4, 4),
    proportional: bool = False,
) -> abjad.Score:
    """
    Constrói um abjad.Score a partir de múltiplas partes.

    parts : lista de (nome_instrumento, lista_de_NoteEvents)
    """
    score = abjad.Score(name="Score")

    for instrument_name, events in parts:
        staff = build_staff(
            events,
            instrument_name=instrument_name,
            time_signature=time_signature,
        )
        score.append(staff)

    return score


# ─────────────────────────────────────────────────────────────
#  Geração do código LilyPond (manual, sem music21.lily.translate)
# ─────────────────────────────────────────────────────────────


# ─────────────────────────────────────────────────────────────
#  Auxiliares: quiálteras e hairpins
# ─────────────────────────────────────────────────────────────

def _group_tuplet_blocks(events: List) -> List[tuple]:
    """
    Agrupa eventos consecutivos em blocos:
      ("normal", [ev, ev, ...])
      ((num, den), [ev, ev, ...])  ← quiáltera

    Eventos com mesmo tuplet_ratio consecutivos são agrupados no mesmo bloco.
    """
    if not events:
        return []

    blocks = []
    i = 0
    while i < len(events):
        ev = events[i]
        ratio = ev.tuplet_ratio  # (num, den) ou None
        j = i + 1
        while j < len(events) and events[j].tuplet_ratio == ratio:
            j += 1
        block_events = events[i:j]
        block_type   = "normal" if ratio is None else ratio
        blocks.append((block_type, block_events))
        i = j
    return blocks


def _compute_hairpin(event, prev_dynamic: Optional["Dynamic"]) -> Optional[str]:
    """
    Decide se emite um hairpin antes deste evento.

    Regra:
      - Se a dinâmica cresce (ex: pp → mf)  → \\<  (crescendo)
      - Se a dinâmica cai   (ex: f → pp)    → \\>  (decrescendo)
      - Se é a primeira nota ou dinâmica igual → None

    O hairpin começa NA nota anterior e fecha \\! na nota onde
    a nova dinâmica é declarada (LilyPond faz isso automaticamente
    quando encontra a próxima marcação dinâmica).
    """
    if prev_dynamic is None or event.is_rest:
        return None
    if event.dynamic == prev_dynamic:
        return None

    # Ordem crescente de intensidade
    ORDER = ["NIENTE", "PPP", "PP", "P", "MP", "MF", "F", "FF", "FFF"]
    try:
        prev_idx = ORDER.index(prev_dynamic.name)
        curr_idx = ORDER.index(event.dynamic.name)
    except ValueError:
        return None

    if curr_idx > prev_idx:
        return r"\<"   # crescendo
    else:
        return r"\>"   # decrescendo



# ─────────────────────────────────────────────────────────────
#  Helpers: percussão de altura indefinida
# ─────────────────────────────────────────────────────────────

def _is_perc_unpitched(instrument_name: str) -> bool:
    """Retorna True se o instrumento usa notação de percussão indefinida."""
    base = instrument_name.split(" #")[0].strip()
    return is_unpitched_percussion(base)


def _render_perc_unpitched_voice(
    instrument_name: str,
    events: list,
    use_hairpins: bool = True,
) -> List[str]:
    """
    Gera linhas LilyPond para percussão de altura indefinida.

    Cada instrumento tem posição fixa na pauta (DrumVoice.staff_pos)
    e cabeça de nota específica (DrumVoice.note_head), conforme as
    referências de notação de percussão (Weinberg, Gould).

    Usa Staff normal com NoteHead overrides em vez de drummode,
    para máxima flexibilidade e compatibilidade com o pipeline existente.
    """
    base = instrument_name.split(" #")[0].strip()
    voice = resolve_drum_voice(base)
    if not voice:
        from percussion import DRUM_VOICES
        voice = DRUM_VOICES["snare"]  # fallback neutro

    lily_pitch  = drum_voice_to_lily_pitch(voice)
    head_style  = voice.note_head
    override_cmd = NOTEHEAD_OVERRIDE.get(head_style, "")
    needs_revert = (head_style not in ("default",))

    stem_up   = r"\stemUp"
    stem_down = r"\stemDown"
    stem_neut = r"\stemNeutral"

    lines: List[str] = []

    # Override de cabeça e stem no início do bloco
    if override_cmd and needs_revert:
        lines.append(f"  {override_cmd}")
    if voice.stem_dir == "up":
        lines.append(f"  {stem_up}")
    elif voice.stem_dir == "down":
        lines.append(f"  {stem_down}")

    prev_dynamic = None
    is_first     = True

    for ev in events:
        dur_str = ev.duration_lily
        if ev.is_rest:
            lines.append(f"  r{dur_str}")
        else:
            # Montar nota na posição fixa de pauta
            note_str = f"{lily_pitch}{dur_str}"

            # Dinâmica quando muda
            show_dyn = is_first or (ev.dynamic != prev_dynamic)
            if show_dyn and ev.dynamic:
                if ev.dynamic.value == "niente":
                    note_str += r' ^\markup { \dynamic "o" }'
                else:
                    note_str += f" {ev.dynamic.lilypond_string()}"
                prev_dynamic = ev.dynamic

            lines.append(f"  {note_str}")
            is_first = False

    # Reverter ao final do bloco
    if needs_revert:
        lines.append(f"  {NOTEHEAD_REVERT}")
    if voice.stem_dir in ("up", "down"):
        lines.append(f"  {stem_neut}")

    return lines


def generate_lilypond_code(
    parts: List[Tuple[str, List[NoteEvent]]],
    title: str = "Composição Algorítmica",
    composer: str = "",
    tempo_bpm: int = 60,
    time_signature: Tuple[int, int] = (4, 4),
    proportional: bool = False,
    use_hairpins: bool = True,
    landscape: bool = False,
    time_sig_sequence: list = None,
    glissando_probability: float = 0.0,
    glissando_seed: int = None,
) -> str:
    """
    Gera código LilyPond completo e compilável, 100% manual.

    Args:
        landscape:         True = A4 paisagem · False = A4 retrato (padrão)
        time_sig_sequence: Lista de (measure_number, ts_str) para mudanças
                           sincronizadas de compasso.  Ex: [(1,"4/4"),(5,"3/4")]
    """
    import re as _re

    ts_num, ts_den = time_signature
    measure_dur = Fraction(ts_num, ts_den)
    lines = []

    # ── Cabeçalho ──────────────────────────────────────────────
    lines += [
        f'\\version "{LILY_VERSION}"',
        "",
        "% Gerado por Markov-Abjad Composer",
        "",
        "\\header {",
        f'  title    = "{title}"',
        f'  composer = "{composer}"',
        '  tagline  = ##f',   # sem tagline padrão do LilyPond
        "}",
        "",
    ]

    # ── Paper: paginação automática ────────────────────────────
    _paper_size = "a4landscape" if landscape else "a4"
    lines += [
        "\\paper {",
        f'  #(set-paper-size "{_paper_size}")',
        "  top-margin        = 15\\mm",
        "  bottom-margin     = 15\\mm",
        "  left-margin       = 15\\mm",
        "  right-margin      = 15\\mm",
        "  indent            = 22\\mm",
        "  short-indent      = 12\\mm",
        "  ragged-last       = ##f",
        "  ragged-bottom     = ##t",
        "  system-separator-markup = \\slashSeparator",
    ]
    if proportional:
        # Na notação proporcional o espaçamento base é menor (mais espaço por evento)
        lines += [
            "  proportionalNotationDuration = #(ly:make-moment 1/16)",
        ]
    lines += ["}", ""]

    # ── Layout global ──────────────────────────────────────────
    lines += [
        "\\layout {",
        "  \\context {",
        "    \\Score",
    ]
    if proportional:
        lines += [
            # ── Notação proporcional gráfica (estética contemporânea) ──────────
            # Espaçamento proporcional: cada evento ocupa espaço proporcional à sua duração
            "    proportionalNotationDuration = #(ly:make-moment 1/16)",
            # Remover engravers que conflitam com notação proporcional/gráfica
            "    \\remove Metronome_mark_engraver",
            "    \\remove Timing_translator",
            "    \\remove Default_bar_line_engraver",
            # Suprimir barras de compasso — notação de tempo contínuo (Feldman/Cardew)
            "    \\override BarLine.transparent = ##t",
            "    \\override BarNumber.transparent = ##t",
            # Remover armadura de clave — notação atonal/microtonal sem referência tonal
            "    \\override KeySignature.transparent = ##t",
            # Remover fórmula de compasso (tempo contínuo sem métrica)
            "    \\override TimeSignature.transparent = ##t",
            # Hastes mais finas — visual mais leve/gráfico
            "    \\override Stem.thickness = 0.8",
            # Colchetes de quiáltera mais finos
            "    \\override TupletBracket.thickness = 0.6",
            "    \\override TupletNumber.font-size = -2",
            # Ligaturas de expressão mais finas
            "    \\override Slur.thickness = 1.2",
            # Dinâmicas em itálico menor — menos intrusivo
            "    \\override DynamicText.font-size = -1",
            "    \\override Hairpin.thickness = 0.8",
        ]
    else:
        lines += [
            "    \\override SpacingSpanner.base-shortest-duration =",
            "      #(ly:make-moment 1/16)",
        ]
    lines += [
        "  }",
        "  \\context {",
        "    \\Staff",
        "    \\override VerticalAxisGroup.staff-staff-spacing =",
        "      #'((basic-distance . 10)(minimum-distance . 8)(padding . 1))",
        # Glissando: linha reta contínua
        "    \\override Glissando.style = #'line",
    ]
    if proportional:
        lines += [
            # Clave mais fina/abstrata
            "    \\override Clef.font-size = -1",
            # Notas mais compactas verticalmente (visual mais denso/gráfico)
            "    \\override NoteHead.font-size = -0.5",
            # Stafflines mais finas
            "    \\override StaffSymbol.thickness = 0.6",
        ]
    lines += [
        "  }",
        "}",
        "",
    ]

    # ── Variáveis por instrumento ──────────────────────────────
    # Mapa de dígito → algarismo romano (para nomes de variáveis LilyPond)
    # Romanos minúsculos (LilyPond aceita [a-zA-Z]; usamos minúsculas para consistência)
    _ROMAN = {"1":"i","2":"ii","3":"iii","4":"iv","5":"v",
              "6":"vi","7":"vii","8":"viii","9":"ix","0":""}

    def _make_var_name(instrument_name: str, used: set) -> str:
        """
        Converte nome de instrumento em identificador LilyPond válido.
        LilyPond só aceita letras ([a-zA-Z]+) em identificadores de variável.
          "Violin #1"   → "violini"
          "Violin #2"   → "violinii"
          "Double Bass" → "doublebass"
          "Violoncello" → "violoncello"
        """
        clean = instrument_name.lower()
        # "#N" → romano minúsculo (feito ANTES de strip, pois são letras)
        clean = _re.sub(r'\s*#\s*(\d)', lambda m: _ROMAN.get(m.group(1),""), clean)
        # Remover tudo que não seja letra minúscula
        clean = _re.sub(r'[^a-z]', '', clean)
        # Fallback se ficou vazio
        if not clean:
            clean = f"voice"
        # Garantir unicidade sem usar números (adicionar letras)
        base = clean
        suffix_letters = "abcdefghijklmnopqrstuvwxyz"
        idx = 0
        while clean in used:
            clean = base + suffix_letters[idx % 26]
            idx += 1
        used.add(clean)
        return clean

    # ── Pós-processamento: glissando ─────────────────────────────────────────
    if glissando_probability > 0.0:
        from note_event import apply_glissando as _apply_glissando
        parts = [
            (name, _apply_glissando(
                evs,
                base_probability=glissando_probability,
                interval_weight=0.5,
                seed=(glissando_seed + idx) if glissando_seed is not None else None,
            ))
            for idx, (name, evs) in enumerate(parts)
        ]

    var_names = []
    _used_var_names: set = set()

    for part_idx, (instrument_name, events) in enumerate(parts):
        var_name = _make_var_name(instrument_name, _used_var_names)
        var_names.append((var_name, instrument_name))

        clef_name = _resolve_clef(instrument_name)
        is_first_part = (part_idx == 0)
        _perc = _is_perc_unpitched(instrument_name)

        lines += [
            f"% ── {instrument_name} ──",
            f"{var_name} = {{",
            f'  \\clef "{clef_name}"',
        ]

        # Em notação proporcional/gráfica: sem \time (suprimido no layout)
        # Em notação normal: emitir fórmula de compasso
        if not proportional:
            lines.append(f"  \\time {ts_num}/{ts_den}")

        # \tempo apenas na primeira voz (e só em notação normal)
        if is_first_part and not proportional:
            lines.append(f"  \\tempo 4 = {tempo_bpm}")

        # ── Percussão de altura indefinida: pipeline especializado ────
        if _perc:
            perc_lines = _render_perc_unpitched_voice(
                instrument_name, events, use_hairpins=use_hairpins
            )
            lines.extend(perc_lines)
            # Fechar hairpin pendente se houver
            if any("\\<" in l or "\\>" in l for l in lines[-20:]):
                open_hp = False
                for l in reversed(lines[-20:]):
                    if "\\!" in l: break
                    if "\\<" in l or "\\>" in l:
                        open_hp = True; break
                if open_hp:
                    lines.append("  \\!")
            lines += ["  \\bar \"|.\"", "}", ""]
            continue

        prev_dynamic   = None
        prev_technique = None
        is_very_first  = True

        if proportional:
            # ── Notação proporcional/gráfica: fluxo contínuo sem compassos ──
            # Os eventos são emitidos diretamente sem divisão em compassos.
            # Barras, 	ime e métricas são suprimidos no \layout (Timing_translator
            # e Default_bar_line_engraver removidos).
            # Pausas são emitidas como spacer 's' para não interromper o fluxo
            # visual (pausa espacial em vez de pausa notada).
            _all_blocks = _group_tuplet_blocks(events)
            for block_type, block_events in _all_blocks:
                if block_type == "normal":
                    for ev in block_events:
                        hairpin  = _compute_hairpin(ev, prev_dynamic) if use_hairpins else None
                        note_str = _event_to_lily_string(
                            ev, prev_dynamic, prev_technique, is_very_first, hairpin,
                            spacer_rests=True,
                        )
                        lines.append(f"  {note_str}")
                        if not ev.is_rest:
                            prev_dynamic   = ev.dynamic
                            prev_technique = ev.technique
                        is_very_first = False
                else:
                    num, den = block_type
                    lines.append(f"  \\tuplet {num}/{den} {{")
                    for ev in block_events:
                        hairpin  = _compute_hairpin(ev, prev_dynamic) if use_hairpins else None
                        note_str = _event_to_lily_string(
                            ev, prev_dynamic, prev_technique, is_very_first, hairpin,
                            spacer_rests=True,
                        )
                        lines.append(f"    {note_str}")
                        if not ev.is_rest:
                            prev_dynamic   = ev.dynamic
                            prev_technique = ev.technique
                        is_very_first = False
                    lines.append("  }")
            lines += ["}", ""]

        else:
            # ── Notação normal: quantização em compassos ──────────────────
            _est_measures = max(32, len(events) + 16)
            if time_sig_sequence and len(time_sig_sequence) > 1:
                _measure_durs = _build_measure_dur_list(
                    time_sig_sequence, _est_measures, measure_dur
                )
                measures = _split_into_measures_variable(events, _measure_durs)
            else:
                _measure_durs = None
                measures = _split_into_measures(events, measure_dur)

            _ts_map: dict = {}
            if time_sig_sequence and len(time_sig_sequence) > 1:
                for _mn, _ts in time_sig_sequence:
                    _ts_map[int(_mn)] = _ts

            prev_ts_str = f"{ts_num}/{ts_den}"

            for m_idx, measure_events in enumerate(measures):
                m_num = m_idx + 1
                lines.append(f"  % compasso {m_num}")

                if m_num in _ts_map and _ts_map[m_num] != prev_ts_str:
                    _new_ts = _ts_map[m_num]
                    lines.append(f"  \\time {_new_ts}")
                    prev_ts_str = _new_ts

                blocks = _group_tuplet_blocks(measure_events)

                for block_type, block_events in blocks:
                    if block_type == "normal":
                        for ev in block_events:
                            hairpin  = _compute_hairpin(ev, prev_dynamic) if use_hairpins else None
                            note_str = _event_to_lily_string(
                                ev, prev_dynamic, prev_technique, is_very_first, hairpin
                            )
                            lines.append(f"  {note_str}")
                            if not ev.is_rest:
                                prev_dynamic   = ev.dynamic
                                prev_technique = ev.technique
                            is_very_first = False
                    else:
                        num, den = block_type
                        lines.append(f"  \\tuplet {num}/{den} {{")
                        for ev in block_events:
                            hairpin  = _compute_hairpin(ev, prev_dynamic) if use_hairpins else None
                            note_str = _event_to_lily_string(
                                ev, prev_dynamic, prev_technique, is_very_first, hairpin
                            )
                            lines.append(f"    {note_str}")
                            if not ev.is_rest:
                                prev_dynamic   = ev.dynamic
                                prev_technique = ev.technique
                            is_very_first = False
                        lines.append("  }")

                if m_idx < len(measures) - 1:
                    lines.append("  \\bar \"|\"")

            # Fechar hairpin pendente e barra final
            if lines and any("\\<" in l or "\\>" in l for l in lines[-50:]):
                open_hairpin = False
                for l in reversed(lines):
                    if "\\!" in l:
                        break
                    if "\\<" in l or "\\>" in l:
                        open_hairpin = True
                        break
                if open_hairpin:
                    lines.append("  \\!")
            lines += ["  \\bar \"|.\"", "}", ""]


    # ── Score ──────────────────────────────────────────────────
    lines += ["\\score {", "  <<"]

    for var_name, instrument_name in var_names:
        abbrev = instrument_name[:4] + "."
        lines += [
            "    \\new Staff {",
            f'      \\set Staff.instrumentName = #"{instrument_name}"',
            f'      \\set Staff.shortInstrumentName = #"{abbrev}"',
            f"      \\{var_name}",
            "    }",
        ]

    lines += [
        "  >>",
        "  \\layout { }",   # activa saída PDF
        "  \\midi { }",     # activa saída MIDI
        "}",
    ]

    return "\n".join(lines)


# Durações de quiálteras reconhecidas — jamais decompor
_TUPLET_DURATIONS: frozenset = frozenset([
    Fraction(1,12), Fraction(1,6),  Fraction(1,3),   # tercinas  3:2
    Fraction(1,20), Fraction(1,10), Fraction(1,5),   # quintinas 5:4
    Fraction(1,28), Fraction(1,14), Fraction(1,7),   # sétimas   7:4
    Fraction(1,36), Fraction(1,18),                  # nônimas   9:8
])

def _decompose_duration(dur: Fraction) -> List[Fraction]:
    """
    Decompõe qualquer duração em lista de durações LilyPond válidas (greedy).
    Ex: 5/8 → [1/2, 1/8]   7/8 → [3/4, 1/8]   5/16 → [1/4, 1/16]

    Durações de quiálteras são retornadas intactas — a nota-base correta
    já está mapeada em NoteEvent.duration_lily via TUPLET_BASE.
    """
    if dur in _TUPLET_DURATIONS:
        return [dur]

    VALID = sorted([
        Fraction(1,1), Fraction(3,4), Fraction(1,2), Fraction(3,8),
        Fraction(1,4), Fraction(3,16), Fraction(1,8), Fraction(3,32),
        Fraction(1,16), Fraction(1,32),
    ], reverse=True)

    result: List[Fraction] = []
    remaining = dur
    while remaining > Fraction(0):
        best = next((d for d in VALID if d <= remaining), None)
        if best is None:
            break
        result.append(best)
        remaining -= best
        if remaining < Fraction(1, 64):
            break
    return result if result else [Fraction(1, 4)]


def _build_measure_dur_list(
    time_sig_sequence: list,
    n_measures: int,
    default_dur: Fraction,
) -> List[Fraction]:
    """
    Constrói lista de durações por compasso a partir da time_sig_sequence.

    time_sig_sequence: [(measure_1based, "4/4"), (5, "3/4"), ...]
    Retorna lista de tamanho n_measures onde cada índice i corresponde
    ao compasso i+1 (1-based).
    """
    from fractions import Fraction as _F
    # Mapear measure_number → Fraction
    sig_map: dict = {}
    for m_num, ts_str in (time_sig_sequence or []):
        num, den = ts_str.split("/")
        sig_map[int(m_num)] = _F(int(num), int(den))

    result: List[Fraction] = []
    current = default_dur
    for m in range(1, n_measures + 1):
        if m in sig_map:
            current = sig_map[m]
        result.append(current)
    return result


def _split_into_measures_variable(
    events: List[NoteEvent],
    measure_durs: List[Fraction],
) -> List[List[NoteEvent]]:
    """
    Variante de _split_into_measures com duração variável por compasso.
    measure_durs[i] = duração do compasso i.
    Quando os eventos excedem len(measure_durs), a última duração é repetida.
    """
    measures: List[List[NoteEvent]] = []
    current_measure: List[NoteEvent] = []
    pos          = Fraction(0)
    measure_idx  = 0

    def _cur_dur():
        if measure_idx < len(measure_durs):
            return measure_durs[measure_idx]
        return measure_durs[-1] if measure_durs else Fraction(1, 1)

    def flush_measure():
        nonlocal current_measure, pos, measure_idx
        remaining = _cur_dur() - pos
        if remaining > Fraction(1, 32):
            for d in _decompose_duration(remaining):
                current_measure.append(NoteEvent.rest(d))
        measures.append(current_measure)
        current_measure = []
        pos = Fraction(0)
        measure_idx += 1

    def emit_segment(ev, seg_dur, tie_in, tie_out):
        nonlocal current_measure, pos
        durs = _decompose_duration(seg_dur)
        for i, d in enumerate(durs):
            is_last_sub  = (i == len(durs) - 1)
            is_first_sub = (i == 0)
            seg = _clone_event(
                ev, d,
                tie_stop  = tie_in and is_first_sub,
                tie_start = tie_out if is_last_sub else True,
            )
            current_measure.append(seg)
            pos += d

    for ev in events:
        is_tuplet = ev.duration in _TUPLET_DURATIONS  # nunca cortar quiálteras
        ev_dur = ev.duration if is_tuplet else max(ev.duration, Fraction(1, 32))
        space  = _cur_dur() - pos

        if is_tuplet or ev_dur <= space:
            # Quiálteras: emitir inteiras mesmo ultrapassando levemente
            emit_segment(ev, ev_dur, tie_in=False, tie_out=False)
            if pos >= _cur_dur():
                measures.append(current_measure)
                current_measure = []
                pos = Fraction(0)
                measure_idx += 1
        else:
            if space >= Fraction(1, 32):
                emit_segment(ev, space, tie_in=False, tie_out=(not ev.is_rest))
            flush_measure()
            leftover = ev_dur - space
            while leftover > Fraction(0):
                space2 = _cur_dur() - pos
                chunk  = min(leftover, space2)
                has_more = (leftover - chunk) > Fraction(1, 64)
                if chunk >= Fraction(1, 32):
                    emit_segment(ev, chunk,
                                 tie_in  = (not ev.is_rest),
                                 tie_out = (not ev.is_rest) and has_more)
                if pos >= _cur_dur():
                    flush_measure()
                leftover -= chunk
                if leftover < Fraction(1, 64):
                    break

    if current_measure:
        remaining = _cur_dur() - pos
        if remaining > Fraction(1, 32):
            for d in _decompose_duration(remaining):
                current_measure.append(NoteEvent.rest(d))
        measures.append(current_measure)

    return measures if measures else [[NoteEvent.rest(_cur_dur())]]


def _split_into_measures(
    events: List[NoteEvent],
    measure_dur: Fraction,
) -> List[List[NoteEvent]]:
    """
    Divide NoteEvents em sub-listas por compasso (quantização por barra).

    Regras:
      - Notas que cruzam barra → segmento pré-barra + segmento pós-barra com tie
      - Segmentos com duração não-padrão → decompostos em durações válidas ligadas
      - Último compasso incompleto → preenchido com pausa
    """
    measures: List[List[NoteEvent]] = []
    current_measure: List[NoteEvent] = []
    pos = Fraction(0)   # posição dentro do compasso atual

    def flush_measure():
        """Fecha compasso atual e abre novo."""
        nonlocal current_measure, pos
        # Preencher espaço restante com pausa se necessário
        remaining = measure_dur - pos
        if remaining > Fraction(1, 32):
            for d in _decompose_duration(remaining):
                current_measure.append(NoteEvent.rest(d))
        measures.append(current_measure)
        current_measure = []
        pos = Fraction(0)

    def emit_segment(ev: NoteEvent, seg_dur: Fraction,
                     tie_in: bool, tie_out: bool):
        """Emite um segmento, decompondo se necessário em durações válidas."""
        nonlocal current_measure, pos
        durs = _decompose_duration(seg_dur)
        for i, d in enumerate(durs):
            is_last_sub  = (i == len(durs) - 1)
            is_first_sub = (i == 0)
            seg = _clone_event(
                ev, d,
                tie_stop  = tie_in and is_first_sub,
                tie_start = tie_out if is_last_sub else True,
            )
            current_measure.append(seg)
            pos += d

    for ev in events:
        ev_dur = ev.duration
        is_tuplet = ev_dur in _TUPLET_DURATIONS  # nunca cortar quiálteras

        # Validar duração mínima (só para notas normais)
        if not is_tuplet and ev_dur < Fraction(1, 32):
            ev_dur = Fraction(1, 32)

        # Quanto cabe no compasso atual?
        space = measure_dur - pos

        if is_tuplet or ev_dur <= space:
            # Quiálteras: sempre inteiras (emitir mesmo se ultrapassar levemente)
            # Notas normais: cabem no espaço restante
            emit_segment(ev, ev_dur, tie_in=False, tie_out=False)
            if pos >= measure_dur:
                measures.append(current_measure)
                current_measure = []
                pos = Fraction(0)
        else:
            # Cruza barra: primeira parte até o fim do compasso
            if space >= Fraction(1, 32):
                emit_segment(ev, space, tie_in=False, tie_out=(not ev.is_rest))
            flush_measure()

            # Resto do evento (pode cruzar mais compassos)
            leftover = ev_dur - space
            while leftover > Fraction(0):
                space2 = measure_dur - pos
                chunk  = min(leftover, space2)
                has_more = (leftover - chunk) > Fraction(1, 64)
                if chunk >= Fraction(1, 32):
                    emit_segment(ev, chunk,
                                 tie_in  = (not ev.is_rest),
                                 tie_out = (not ev.is_rest) and has_more)
                if pos >= measure_dur:
                    flush_measure()
                leftover -= chunk
                if leftover < Fraction(1, 64):
                    break

    # Fechar último compasso
    if current_measure:
        remaining = measure_dur - pos
        if remaining > Fraction(1, 32):
            for d in _decompose_duration(remaining):
                current_measure.append(NoteEvent.rest(d))
        measures.append(current_measure)

    return measures if measures else [[NoteEvent.rest(measure_dur)]]


def _clone_event(
    ev: NoteEvent,
    new_duration: Fraction,
    tie_stop: bool = False,
    tie_start: bool = False,
) -> NoteEvent:
    """Clona um NoteEvent com nova duração e flags de ligadura."""
    from dataclasses import replace
    return replace(ev,
                   duration=new_duration,
                   tie_start=tie_start,
                   tie_stop=tie_stop)


def _event_to_lily_string(
    event: NoteEvent,
    prev_dynamic: Optional[Dynamic],
    prev_technique: Optional[Technique],
    is_first: bool,
    hairpin_cmd: Optional[str] = None,
    spacer_rests: bool = False,
) -> str:
    """
    Converte um único NoteEvent para string LilyPond.

    hairpin_cmd  : crescendo (\\<) ou decrescendo (\\>) ou None.
    spacer_rests : se True, usa 's' (spacer) em vez de 'r' (pausa notada).
                   Usado na notação proporcional/gráfica para pausas invisíveis
                   que preservam o espaçamento temporal sem marcar a pausa.
    """
    parts = []

    # Pausa
    if event.is_rest:
        prefix = "s" if spacer_rests else "r"
        parts.append(f"{prefix}{event.duration_lily}")
        if hairpin_cmd:
            parts.append(hairpin_cmd)
        return " ".join(parts)

    # Pitch + duração
    pitch    = event.full_pitch_name or "c'"
    note_str = f"{pitch}{event.duration_lily}"
    if event.tie_start:
        note_str += "~"
    parts.append(note_str)

    # Glissando: emitido logo após a nota, antes de dinâmica/markup
    # Não compatível com tie_start (ligadura de valor tem prioridade)
    if getattr(event, "gliss_to_next", False) and not event.tie_start:
        parts.append(r"\glissando")

    # Técnica estendida — comando nativo
    cmd = event.technique.lilypond_command()
    if cmd and event.technique != (prev_technique or Technique.ORDINARIO):
        parts.append(cmd)

    # Dinâmica (só quando muda ou primeira nota)
    show_dynamic = is_first or (event.dynamic != prev_dynamic)
    if show_dynamic:
        if event.dynamic == Dynamic.NIENTE:
            parts.append(r'^\markup { \dynamic "°" }')
        else:
            parts.append(event.dynamic.lilypond_string())

    # Hairpin APÓS dinâmica (ordem LilyPond: nota \mp \< )
    if hairpin_cmd:
        parts.append(hairpin_cmd)

    # Técnica estendida — markup textual
    markup = event.technique.lilypond_markup()
    changed_technique  = (prev_technique is None or event.technique != prev_technique)
    is_returning_to_ord = (
        prev_technique is not None
        and prev_technique != Technique.ORDINARIO
        and event.technique == Technique.ORDINARIO
    )
    if markup and changed_technique and not is_returning_to_ord:
        parts.append(f"^{markup}")
    if is_returning_to_ord:
        parts.append(r'^\markup { \italic "ord." }')

    if event.markup_above:
        parts.append(f"^{event.markup_above}")
    if event.markup_below:
        parts.append(f"_{event.markup_below}")

    return " ".join(parts)


# ─────────────────────────────────────────────────────────────
#  Compilação LilyPond → PDF
# ─────────────────────────────────────────────────────────────

def _estimate_lilypond_timeout(lilypond_code: str) -> int:
    """
    Estima timeout em segundos com base no tamanho e complexidade do código.

    Fatores agravantes além do tamanho:
      - Notação proporcional: LilyPond calcula espaçamento por evento (~40% mais pesado)
      - Quiálteras densas: cada beam group é resolvido individualmente
      - Hairpins: cada spanner é verificado contra o contexto

    Thresholds calibrados para partituras contemporâneas densas
    (5 instrumentos, 1024 notas, quiálteras + proporcional):
    """
    kb = len(lilypond_code.encode("utf-8")) / 1024

    # Detectar fatores agravantes
    is_proportional = "proportionalNotationDuration" in lilypond_code
    tuplet_count    = lilypond_code.count("\\tuplet")
    # Hairpin count não precisa ser exato — só detectar densidade alta
    dense_hairpins  = (lilypond_code.count("\\<") + lilypond_code.count("\\>")) > 300

    # Base por tamanho (aumentada em relação à versão anterior)
    if kb < 80:
        base = 150
    elif kb < 200:
        base = 270
    elif kb < 400:
        base = 480    # era 300 — aumentado para cenário 5 instrs × 1024 notas
    elif kb < 700:
        base = 720
    elif kb < 1200:
        base = 1080
    elif kb < 2000:
        base = 1440
    else:
        base = 1800

    # Multiplicadores por fatores agravantes
    mult = 1.0
    if is_proportional:
        mult *= 1.4
    if tuplet_count > 200:
        mult *= 1.2
    if tuplet_count > 600:
        mult *= 1.15  # adicional para quiálteras muito densas
    if dense_hairpins:
        mult *= 1.1

    return min(1800, int(base * mult))


def compile_to_pdf(
    lilypond_code: str,
    output_path: str,
    open_after: bool = False,
) -> Tuple[bool, str]:
    """
    Compila código LilyPond para PDF.

    Retorna (sucesso: bool, mensagem: str).

    open_after : abre o PDF no visualizador padrão do macOS após compilar.

    Nota sobre --output no LilyPond:
      --output PREFIXO  → gera PREFIXO.pdf  (NÃO um diretório)
      --output DIRETORIO/  → comportamento indefinido/varia por versão

    Timeout: calculado dinamicamente pelo tamanho do código LilyPond
    (partituras longas exigem mais tempo de engraving).
    """
    lily_path = shutil.which("lilypond")
    if not lily_path:
        import platform as _plt
        _sys = _plt.system()
        if _sys == "Windows":
            _install_msg = (
                "LilyPond não encontrado.\n"
                "Instale em: https://lilypond.org/download.html\n"
                "Após instalar, adicione ao PATH do Windows:\n"
                "  Painel de Controle → Sistema → Variáveis de Ambiente → PATH\n"
                "  Adicione: C:\\Program Files (x86)\\LilyPond\\usr\\bin"
            )
        elif _sys == "Darwin":
            _install_msg = "LilyPond não encontrado. Instale com: brew install lilypond"
        else:
            _install_msg = "LilyPond não encontrado. Instale com: sudo apt install lilypond"
        return False, _install_msg

    output_path = Path(output_path)
    output_path.parent.mkdir(parents=True, exist_ok=True)

    timeout = _estimate_lilypond_timeout(lilypond_code)

    with tempfile.TemporaryDirectory() as tmpdir:
        tmpdir_path = Path(tmpdir)
        ly_file = tmpdir_path / "score.ly"
        ly_file.write_text(lilypond_code, encoding="utf-8")

        # CRÍTICO: --output recebe PREFIXO do arquivo, não diretório
        # LilyPond gera: {prefixo}.pdf, {prefixo}.midi
        output_prefix = str(tmpdir_path / "score")

        try:
            result = subprocess.run(
                [lily_path, "--output", output_prefix, str(ly_file)],
                capture_output=True,
                text=True,
                timeout=timeout,
            )
        except subprocess.TimeoutExpired:
            kb = len(lilypond_code.encode("utf-8")) / 1024
            msg = (
                f"LilyPond excedeu o tempo máximo de compilação ({timeout}s).\n"
                f"Tamanho do código: {kb:.0f} KB\n\n"
                f"Sugestões:\n"
                f"  • Reduza o número de notas por instrumento\n"
                f"  • Reduza o número de instrumentos\n"
                f"  • Desative quiálteras complexas (diminui densidade notacional)\n"
                f"  • O arquivo .ly foi salvo e pode ser compilado manualmente"
            )
            debug_ly = output_path.parent / (output_path.stem + "_timeout.ly")
            try:
                debug_ly.write_text(lilypond_code, encoding="utf-8")
                msg += f"\n  • Arquivo salvo: {debug_ly}"
            except Exception:
                pass
            return False, msg

        # Localizar o PDF gerado (nome exato pode variar)
        pdf_temp = tmpdir_path / "score.pdf"
        if not pdf_temp.exists():
            # Busca recursiva como fallback
            pdfs = list(tmpdir_path.glob("**/*.pdf"))
            if pdfs:
                pdf_temp = pdfs[0]

        if result.returncode == 0 and pdf_temp.exists():
            shutil.copy(str(pdf_temp), str(output_path))

            if open_after:
                import platform as _platform
                _sys = _platform.system()
                if _sys == "Darwin":
                    # macOS: -F força o Finder a reabrir mesmo que já esteja aberto
                    subprocess.Popen(["open", "-F", str(output_path)])
                elif _sys == "Windows":
                    os.startfile(str(output_path))  # type: ignore[attr-defined]
                else:
                    # Linux / outros
                    subprocess.Popen(["xdg-open", str(output_path)])

            return True, f"PDF gerado: {output_path}"
        else:
            # Capturar saída completa para diagnóstico
            saida = (result.stdout or "") + (result.stderr or "")
            linhas = saida.splitlines()

            import re as _re
            erros_reais = [l for l in linhas if _re.search(r'\.ly:\d+:', l)]
            erros_kw    = [l for l in linhas if any(
                kw in l.lower() for kw in ["error:", "warning:", "fatal", "unknown"]
            )]
            erros = erros_reais + [l for l in erros_kw if l not in erros_reais]
            resumo = "\n".join(erros[:30]) if erros else "\n".join(linhas[-25:])

            # Adicionar diagnóstico extra
            arquivos = list(tmpdir_path.iterdir())
            resumo += f"\n\n[returncode={result.returncode}]"
            resumo += f"\n[arquivos gerados: {[f.name for f in arquivos]}]"

            # Salvar .ly para inspeção manual
            debug_ly = output_path.parent / (output_path.stem + "_debug.ly")
            try:
                debug_ly.write_text(lilypond_code, encoding="utf-8")
                resumo += f"\n[.ly salvo: {debug_ly}]"
            except Exception:
                pass

            return False, f"Erro na compilação LilyPond:\n{resumo}"


def save_lilypond_file(lilypond_code: str, output_path: str) -> str:
    """Salva o código LilyPond como arquivo .ly."""
    path = Path(output_path)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(lilypond_code, encoding="utf-8")
    return str(path)


# ─────────────────────────────────────────────────────────────
#  Teste de integração (execute: python abjad_engine.py)
# ─────────────────────────────────────────────────────────────

if __name__ == "__main__":
    from fractions import Fraction

    print("=" * 55)
    print("  Teste de Integração: AbjadEngine")
    print("=" * 55)

    # Sequência de NoteEvents — nomenclatura holandesa LilyPond
    # Microtons: sufixos ih (quarter sharp), eh (quarter flat),
    #            isih (3/4 sharp), eseh (3/4 flat)  — sistema holandês nativo 2.24
    events_violino = [
        NoteEvent("c'",   Fraction(1,4),  Dynamic.PP,     Technique.SUL_PONTICELLO),
        # dih' = ré com quarto de tom acima (+50¢)
        NoteEvent("d'",   Fraction(1,8),  Dynamic.PP,     Technique.SUL_PONTICELLO,  Microtone.QUARTER_SHARP),
        NoteEvent("ees'", Fraction(1,8),  Dynamic.P,      Technique.SUL_PONTICELLO),
        NoteEvent("f'",   Fraction(1,4),  Dynamic.MP,     Technique.ORDINARIO),
        NoteEvent("g'",   Fraction(3,8),  Dynamic.MF,     Technique.HARMONIC),
        NoteEvent.rest(    Fraction(1,8),  Dynamic.MP),
        NoteEvent("a'",   Fraction(1,4),  Dynamic.F,      Technique.FLUTTER_TONGUE),
        # beseseh' = si bemol com três quartos abaixo (−150¢ do si natural)
        NoteEvent("bes'", Fraction(1,4),  Dynamic.FF,     Technique.ORDINARIO,       Microtone.THREE_QUARTER_FLAT),
        NoteEvent("c''", Fraction(1,2),  Dynamic.NIENTE, Technique.ORDINARIO),
    ]

    events_viola = [
        NoteEvent("c",    Fraction(1,4),  Dynamic.MP,     Technique.COL_LEGNO_TRATTO),
        NoteEvent("d",    Fraction(1,4),  Dynamic.MP,     Technique.COL_LEGNO_TRATTO),
        NoteEvent("ees",  Fraction(1,4),  Dynamic.MF,     Technique.ORDINARIO),
        NoteEvent("f",    Fraction(1,4),  Dynamic.MF,     Technique.ORDINARIO),
        NoteEvent("g",    Fraction(1,2),  Dynamic.F,      Technique.PIZZICATO),
        NoteEvent("a",    Fraction(1,4),  Dynamic.PP,     Technique.SNAP_PIZZICATO),
        NoteEvent.rest(   Fraction(1,4)),
        NoteEvent("g",    Fraction(1,2),  Dynamic.PPP,    Technique.ORDINARIO),
    ]

    parts = [
        ("Violin I", events_violino),
        ("Viola",    events_viola),
    ]

    # Gerar código LilyPond
    print("\n1. Gerando código LilyPond...")
    ly_code = generate_lilypond_code(
        parts,
        title="Estudo em Técnicas Estendidas",
        composer="Markov-Abjad Engine",
        tempo_bpm=60,
        time_signature=(4, 4),
        proportional=False,
    )

    # Salvar .ly
    ly_path = "output/teste_engine.ly"
    save_lilypond_file(ly_code, ly_path)
    print(f"   ✅ Arquivo .ly salvo: {ly_path}")

    # Compilar para PDF
    print("\n2. Compilando para PDF...")
    ok, msg = compile_to_pdf(ly_code, "output/teste_engine.pdf", open_after=True)
    if ok:
        print(f"   ✅ {msg}")
    else:
        print(f"   ❌ {msg}")

    # Mostrar trecho do código gerado
    print("\n3. Trecho do código LilyPond gerado:")
    print("-" * 55)
    for linha in ly_code.split("\n")[:30]:
        print(f"  {linha}")
    print("  ...")
    print("-" * 55)
    print("\n✅ Teste de integração concluído!")
