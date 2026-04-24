"""
markov_engine.py
================
Motor de composição probabilística via Cadeias de Markov.

Arquitetura:
  MarkovMatrix   — unidade genérica: treina e amostra 1 parâmetro
  MarkovEngine   — orquestra 5 matrizes independentes:
                   pitch · duration · dynamic · technique · microtone
  InstrumentProfile — define tessitura e técnicas válidas por instrumento

Fluxo:
  1. Criar MarkovEngine com lista de instrumentos
  2. train_from_midi(path) OU train_uniform()
  3. generate(n_notes, instrument_name) → list[NoteEvent]
  4. Passar NoteEvents para AbjadEngine → PDF

Decisão de design (Opção A — Timbre fixo):
  O instrumento é escolhido pelo usuário na interface.
  A timbre_matrix filtra quais Techniques são válidas para cada
  família instrumental, mas o instrumento em si não muda
  durante a geração de uma voz.

Parâmetros com matrizes independentes:
  - pitch      : nome LilyPond (c, cis, d, ees, e, f, fis, g, aes, a, bes, b)
  - duration   : Fraction (1/8, 1/4, 3/8, 1/2, 3/4, 1, ...)
  - dynamic    : Dynamic enum
  - technique  : Technique enum (filtrado por família)
  - microtone  : Microtone enum

Referências estéticas:
  Feldman (indeterminismo controlado), Lachenmann (musique concrète
  instrumentale), Sciarrino (micropolifonia), Ferneyhough (complexidade).
"""

from __future__ import annotations

import csv
import random
from dataclasses import dataclass, field
from fractions import Fraction
from pathlib import Path
from typing import Optional, Sequence

from note_event import Dynamic, Microtone, NoteEvent, NotationType, Technique
from note_event import apply_glissando  # noqa
from percussion import (
    PITCHED_PERCUSSION, PITCHED_PERCUSSION_ALIASES,
    is_pitched_percussion, is_unpitched_percussion,
    resolve_drum_voice,
)

# ─────────────────────────────────────────────────────────────────────────────
#  Tessituras por instrumento (notação MIDI para cálculo de transposição)
#  Formato: (midi_min, midi_max)
#  Fonte: instrumentação orquestral padrão
# ─────────────────────────────────────────────────────────────────────────────

INSTRUMENT_MIDI_RANGES: dict[str, tuple[int, int]] = {
    # ── Madeiras ─────────────────────────────────────────────────
    # Fontes: Adler "Study of Orchestration", Gould "Behind Bars",
    #         Blatter "Instrumentation and Orchestration" (concert pitch).
    "Flute":       (59,  98),   # B3–D7    (B3 com extensão; Gould p.19)
    "Oboe":        (58,  93),   # Bb3–A6   (Adler p.191; Gould p.58)
    "Clarinet":    (50,  94),   # D3–Bb6   (concert pitch; Gould p.72)
    "Bassoon":     (34,  75),   # Bb1–Eb5  (Adler p.209; Gould p.86)

    # ── Metais ───────────────────────────────────────────────────
    "Horn":        (35,  77),   # B1–F5    (Adler p.130; Gould p.447)
    "Trumpet":     (54,  82),   # F#3–Bb5  (concert pitch; Gould p.444)
    "Trombone":    (40,  77),   # E2–F5    (Adler p.158; gliss. pedal excl.)
    "Tuba":        (26,  65),   # D1–F4    (Adler p.166; Gould p.459)

    # ── Cordas ───────────────────────────────────────────────────
    "Violin":      (55, 100),   # G3–E7    (Adler p.17; Gould p.35)
    "Viola":       (48,  88),   # C3–E6    (Adler p.31; Gould p.41)
    "Violoncello": (36,  84),   # C2–C6    (Adler p.46; Gould p.44)
    "Double Bass": (28,  67),   # E1–G4    (Adler p.60; concert pitch)

    # ── Teclados / Harpa ─────────────────────────────────────────
    "Piano":       (21, 108),   # A0–C8    (88 teclas padrão)
    "Harp":        (24, 103),   # C1–G7    (Adler p.85; pedal harp)

    # ── Percussão de altura definida ─────────────────────────────
    "Vibraphone":  (53,  89),   # F3–F6
    "Marimba":     (36,  96),   # C2–C7
    "Xylophone":   (60,  96),   # C4–C7
    "Glockenspiel":(79, 108),   # escrita G5–C8
    "Timpani":     (40,  65),   # E2–F4 (4 tímpanos)
    "Crotales":    (60,  84),   # C4–C6 (escrita)
}

# Alias para suportar variantes de nome (incluindo dobras "#N")
_INSTRUMENT_ALIASES: dict[str, str] = {
    # Violinos com dobras (gerados pela GUI como "Violin #1", "Violin #2"...)
    "Violin #1":  "Violin",
    "Violin #2":  "Violin",
    "Violin #3":  "Violin",
    "Violin #4":  "Violin",
    # Outros nomes históricos / abreviações
    "Violin I":   "Violin",
    "Violin II":  "Violin",
    "Vln. I":     "Violin",
    "Vln. II":    "Violin",
    # Viola com dobras
    "Viola #1":   "Viola",
    "Viola #2":   "Viola",
    # Violoncelo
    "Violoncello #1": "Violoncello",
    "Violoncello #2": "Violoncello",
    "Cello":      "Violoncello",
    "Vc.":        "Violoncello",
    # Contrabaixo
    "Double Bass #1": "Double Bass",
    "Double Bass #2": "Double Bass",
    "Db.":        "Double Bass",
    "Contrabass": "Double Bass",
    # Madeiras com dobras
    "Flute #1":   "Flute",
    "Flute #2":   "Flute",
    "Oboe #1":    "Oboe",
    "Oboe #2":    "Oboe",
    "Clarinet #1":"Clarinet",
    "Clarinet #2":"Clarinet",
    "Bassoon #1": "Bassoon",
    "Bassoon #2": "Bassoon",
    # Metais com dobras
    "Horn #1":    "Horn",
    "Horn #2":    "Horn",
    "Horn #3":    "Horn",
    "Horn #4":    "Horn",
    "Trumpet #1": "Trumpet",
    "Trumpet #2": "Trumpet",
    "Trombone #1":"Trombone",
    "Trombone #2":"Trombone",
    # Abreviações
    "Cl.":        "Clarinet",
    "Ob.":        "Oboe",
    "Fl.":        "Flute",
    "Bn.":        "Bassoon",
    "Hn.":        "Horn",
    "Tpt.":       "Trumpet",
    "Tbn.":       "Trombone",
}

# ─────────────────────────────────────────────────────────────────────────────
#  Famílias instrumentais e técnicas disponíveis
# ─────────────────────────────────────────────────────────────────────────────

class InstrumentFamily:
    """Agrupa instrumentos por família tímbrica e define técnicas válidas."""

    STRINGS  = frozenset(["Violin", "Viola", "Violoncello", "Double Bass", "Harp"])
    WOODWIND = frozenset(["Flute", "Oboe", "Clarinet", "Bassoon"])
    BRASS    = frozenset(["Horn", "Trumpet", "Trombone", "Tuba"])
    KEYBOARD = frozenset(["Piano"])
    PERC_PITCHED   = frozenset([
        "Vibraphone","Marimba","Xylophone","Glockenspiel","Timpani","Crotales",
    ])
    PERC_UNPITCHED = frozenset([
        "Snare Drum","Bass Drum","Tan-Tan","Tom High","Tom Mid","Tom Low",
        "Floor Tom","Gong","Hi-Hat","Ride Cymbal","Crash Cymbal",
        "Suspended Cymbal","Cymbals (clash)","Tam-Tam","China/Splash",
        "Triangle","Woodblock","Cowbell","Tambourine","Claves","Vibraslap",
    ])

    # Técnicas disponíveis por família
    _TECHNIQUES: dict[str, frozenset[Technique]] = {
        "strings": frozenset([
            Technique.ORDINARIO,
            Technique.SUL_PONTICELLO,
            Technique.SUL_TASTO,
            Technique.COL_LEGNO_TRATTO,
            Technique.COL_LEGNO_BATTUTO,
            Technique.HARMONIC,
            Technique.PIZZICATO,
            Technique.SNAP_PIZZICATO,
            Technique.TREMOLO_MEASURED,
            Technique.TREMOLO_UNMEASURED,
        ]),
        "woodwind": frozenset([
            Technique.ORDINARIO,
            Technique.FLUTTER_TONGUE,
            Technique.MULTIPHONIC,
            Technique.HARMONIC,
            Technique.EXTENDED_BREATH,
            Technique.AIR_TONE,        # Flauta principalmente; aceitável para outros
            Technique.TREMOLO_MEASURED,
        ]),
        "brass": frozenset([
            Technique.ORDINARIO,
            Technique.FLUTTER_TONGUE,
            Technique.MULTIPHONIC,
            Technique.EXTENDED_BREATH,
            Technique.TREMOLO_MEASURED,
        ]),
        "keyboard": frozenset([
            Technique.ORDINARIO,
            Technique.TREMOLO_MEASURED,
            Technique.TREMOLO_UNMEASURED,
        ]),
        "percussion_pitched": frozenset([
            Technique.ORDINARIO,
            Technique.TREMOLO_MEASURED,
            Technique.TREMOLO_UNMEASURED,
        ]),
        "percussion_unpitched": frozenset([
            Technique.ORDINARIO,
        ]),
    }

    @classmethod
    def resolve(cls, instrument_name: str) -> str:
        """Retorna o nome canônico do instrumento (sem sufixos de dobra)."""
        base = instrument_name.split(" #")[0].strip()
        return _INSTRUMENT_ALIASES.get(base, base)

    @classmethod
    def family_of(cls, instrument_name: str) -> str:
        """Retorna a família do instrumento."""
        canonical = cls.resolve(instrument_name)
        if canonical in cls.STRINGS:        return "strings"
        if canonical in cls.WOODWIND:       return "woodwind"
        if canonical in cls.BRASS:          return "brass"
        if canonical in cls.KEYBOARD:       return "keyboard"
        if canonical in cls.PERC_PITCHED:   return "percussion_pitched"
        if canonical in cls.PERC_UNPITCHED: return "percussion_unpitched"
        if is_pitched_percussion(instrument_name):   return "percussion_pitched"
        if is_unpitched_percussion(instrument_name): return "percussion_unpitched"
        return "strings"

    @classmethod
    def valid_techniques(cls, instrument_name: str) -> frozenset[Technique]:
        """Retorna o conjunto de técnicas válidas para o instrumento."""
        family = cls.family_of(instrument_name)
        return cls._TECHNIQUES.get(family, cls._TECHNIQUES["strings"])

    @classmethod
    def midi_range(cls, instrument_name: str) -> tuple[int, int]:
        """Retorna (midi_min, midi_max) para o instrumento."""
        canonical = cls.resolve(instrument_name)
        if canonical in INSTRUMENT_MIDI_RANGES:
            return INSTRUMENT_MIDI_RANGES[canonical]
        pc = PITCHED_PERCUSSION_ALIASES.get(canonical, canonical)
        if pc in PITCHED_PERCUSSION:
            return PITCHED_PERCUSSION[pc]
        if is_unpitched_percussion(instrument_name):
            return (36, 36)
        return (48, 84)


# ─────────────────────────────────────────────────────────────────────────────
#  Conversão pitch: MIDI ↔ LilyPond
# ─────────────────────────────────────────────────────────────────────────────

# Nomes de pitch por classe (0=C … 11=B), notação holandesa
_PITCH_CLASSES = ["c", "cis", "d", "ees", "e", "f", "fis", "g", "aes", "a", "bes", "b"]

# MIDI 60 = C4 = "c'" (oitava 1 no sistema LilyPond: c' d' e'...)
# LilyPond: C4=c', C5=c'', C3=c, C2=c, (usa vírgulas para graves)
def midi_to_lily(midi: int) -> str:
    """Converte número MIDI para nome LilyPond com oitava."""
    pitch_class = _PITCH_CLASSES[midi % 12]
    octave_num  = (midi // 12) - 1   # MIDI 60 → octave 4
    # LilyPond: oitava 4 = "'" (1 apóstrofe), 5 = "''" etc.
    # oitava 3 = "" (sem marcação), 2 = "," etc.
    if octave_num >= 4:
        oitava = "'" * (octave_num - 3)
    elif octave_num == 3:
        oitava = ""
    else:
        oitava = "," * (3 - octave_num)
    return f"{pitch_class}{oitava}"

def lily_to_midi(lily_pitch: str) -> int:
    """Converte nome LilyPond para número MIDI aproximado."""
    # Separar nome da nota e marcadores de oitava
    base = lily_pitch.rstrip("',")
    oitava_str = lily_pitch[len(base):]

    # Encontrar pitch class
    pc = -1
    for i, name in enumerate(_PITCH_CLASSES):
        if base.lower() == name:
            pc = i
            break
    if pc == -1:
        # Tentar letra base apenas
        pc = next((i for i, n in enumerate(_PITCH_CLASSES) if n[0] == base[0].lower()), 0)

    # Calcular oitava LilyPond → número
    if oitava_str.startswith("'"):
        octave_num = 3 + len(oitava_str)
    elif oitava_str.startswith(","):
        octave_num = 3 - len(oitava_str)
    else:
        octave_num = 3

    return (octave_num + 1) * 12 + pc

def adjust_to_range(lily_pitch: str, instrument_name: str) -> str:
    """
    Transpõe pitch para caber na tessitura do instrumento.
    Preserva a classe de pitch (nota), ajusta apenas a oitava.
    """
    if lily_pitch.startswith("r"):  # pausa
        return lily_pitch

    midi    = lily_to_midi(lily_pitch)
    lo, hi  = InstrumentFamily.midi_range(instrument_name)

    # Transposição por oitavas até caber no range
    while midi < lo:
        midi += 12
    while midi > hi:
        midi -= 12

    # Clamp final de segurança
    midi = max(lo, min(hi, midi))
    return midi_to_lily(midi)


# ─────────────────────────────────────────────────────────────────────────────
#  MarkovMatrix — unidade fundamental
# ─────────────────────────────────────────────────────────────────────────────

class MarkovMatrix:
    """
    Cadeia de Markov de ordem N para um único parâmetro musical.

    Estados: qualquer tipo hashável (str, Fraction, enum, int).

    Internamente armazena:
      _counts[state_tuple] = {next_state: contagem}
    Após normalização:
      _probs[state_tuple]  = {next_state: probabilidade}
    """

    def __init__(self, order: int = 1):
        self.order            = order
        self._counts          : dict = {}
        self._probs           : dict = {}
        self._states          : list = []  # todos os estados únicos observados
        self._default_weights : list = []  # pesos globais para fallback

    # ── Treinamento ──────────────────────────────────────────────

    def train(self, sequence: Sequence) -> None:
        """
        Treina a matriz a partir de uma sequência de estados.
        Pode ser chamado múltiplas vezes (acumula contagens).
        """
        if len(sequence) <= self.order:
            return

        for i in range(len(sequence) - self.order):
            context    = tuple(sequence[i : i + self.order])
            next_state = sequence[i + self.order]

            if context not in self._counts:
                self._counts[context] = {}
            self._counts[context][next_state] = (
                self._counts[context].get(next_state, 0) + 1
            )

        # Atualizar lista de estados únicos
        self._states = list(dict.fromkeys(
            s for ctx in self._counts for s in list(ctx) + list(self._counts[ctx])
        ))

        self._normalize()

    def _normalize(self) -> None:
        """Converte contagens em probabilidades."""
        self._probs = {}
        for ctx, successors in self._counts.items():
            total = sum(successors.values())
            self._probs[ctx] = {s: c / total for s, c in successors.items()}

    # ── Amostragem ───────────────────────────────────────────────

    def sample(self, context: tuple) -> object:
        """
        Amostra o próximo estado dado o contexto.

        Estratégia de fallback em cascata:
          1. Contexto exato em _probs → usa distribuição treinada
          2. Backoff: tenta sufixos menores do contexto (ordem reduzida)
          3. Fallback global: usa _default_weights se disponíveis,
             senão uniforme — preserva rest_probability mesmo em
             corpus MIDI pequenos onde muitos contextos não existem.
        """
        if context in self._probs:
            states  = list(self._probs[context].keys())
            weights = list(self._probs[context].values())
            return random.choices(states, weights=weights)[0]
        # Backoff: tentar sufixos progressivamente menores
        for trim in range(1, len(context)):
            shorter = context[trim:]
            if shorter in self._probs:
                states  = list(self._probs[shorter].keys())
                weights = list(self._probs[shorter].values())
                return random.choices(states, weights=weights)[0]
        # Fallback global com pesos
        if self._states:
            if self._default_weights:
                return random.choices(self._states, weights=self._default_weights)[0]
            return random.choice(self._states)
        return None

    def random_start(self) -> object:
        """Retorna um estado inicial aleatório ponderado pela frequência."""
        if not self._states:
            return None
        # Ponderar pela frequência de aparição como contexto
        weights = [sum(self._counts.get((s,), {}).values()) + 1
                   for s in self._states]
        return random.choices(self._states, weights=weights)[0]

    # ── Exportação CSV ───────────────────────────────────────────

    def export_csv(self, path: str | Path) -> None:
        """Exporta a matriz de probabilidades como CSV."""
        all_states = sorted(set(
            s for ctx in self._probs for s in list(ctx) + list(self._probs[ctx])
        ), key=str)

        with open(path, "w", newline="", encoding="utf-8") as f:
            writer = csv.writer(f)
            writer.writerow(["context"] + [str(s) for s in all_states])
            for ctx in sorted(self._probs.keys(), key=str):
                row = [str(ctx)] + [
                    f"{self._probs[ctx].get(s, 0):.4f}" for s in all_states
                ]
                writer.writerow(row)

    # ── Matrizes predefinidas (sem MIDI) ─────────────────────────

    @classmethod
    def uniform(cls, states: list, order: int = 1) -> "MarkovMatrix":
        """
        Cria uma matriz com probabilidades uniformes sobre os estados dados.
        Útil quando não há arquivo MIDI de treinamento.
        """
        m = cls(order=order)
        # Criar sequência sintética que visita todos os estados ciclicamente
        sequence = states * max(10, len(states))
        m.train(sequence)
        return m

    @classmethod
    def weighted(cls, states: list, weights: list[float], order: int = 1) -> "MarkovMatrix":
        """
        Cria matriz com pesos DETERMINÍSTICOS — sem amostragem aleatória.

        A abordagem anterior usava random.choices() com k pequeno, o que gerava
        alta variância: um peso de 0.30 podia resultar em 10%–45% na prática.

        Agora: cada contexto recebe a distribuição exata normalizada dos pesos.
        Como é uma matriz de ordem N, todos os contextos N-gramas recebem
        a mesma distribuição (cadeia sem memória direcional nos pesos —
        a memória emerge dos dados MIDI quando treinado com corpus real).
        """
        m = cls(order=order)

        import itertools as _it

        # Normalizar pesos
        total = sum(weights)
        if total <= 0:
            total = 1.0
        norm_weights = [w / total for w in weights]
        dist         = {s: w for s, w in zip(states, norm_weights)}
        counts_int   = {s: max(1, int(w * 1000)) for s, w in zip(states, norm_weights)}

        m._states          = list(states)
        m._default_weights = list(norm_weights)  # para fallback no sample()

        # Preencher TODOS os contextos possíveis de tamanho `order`.
        # Sem isso, order>1 cai no fallback uniforme na maioria das chamadas.
        for ctx in _it.product(states, repeat=order):
            m._probs[ctx]  = dict(dist)
            m._counts[ctx] = dict(counts_int)

        return m


# ─────────────────────────────────────────────────────────────────────────────
#  Durações disponíveis e seus pesos para música contemporânea
# ─────────────────────────────────────────────────────────────────────────────

# Durações em fração de semibreve
DURATIONS_STANDARD = [
    Fraction(1, 16),   # semicolcheia
    Fraction(1, 8),    # colcheia
    Fraction(3, 16),   # colcheia pontuada
    Fraction(1, 4),    # semínima
    Fraction(3, 8),    # semínima pontuada
    Fraction(1, 2),    # mínima
    Fraction(3, 4),    # mínima pontuada
    Fraction(1, 1),    # semibreve
]

DURATION_WEIGHTS_CONTEMPORARY = [
    0.15,  # semicolcheia
    0.20,  # colcheia
    0.10,  # colcheia pont.
    0.18,  # semínima
    0.10,  # semínima pont.
    0.13,  # mínima
    0.08,  # mínima pont.
    0.06,  # semibreve
]

# ─── Quiálteras ─────────────────────────────────────────────────────────────
# Cada entrada: (Fraction duração_real, num, den, base_lily_str)
#   num/den = razão  ex: 3/2=tercina  5/4=quintina  7/4=sétima  9/8=nônima
#   base_lily = duração da nota-base dentro da quiáltera  ex: "8", "4"
TUPLET_TABLE = [
    # tercinas ─ 3 no tempo de 2
    (Fraction(1, 12), 3, 2, "8"),   # tercina de colcheia
    (Fraction(1,  6), 3, 2, "4"),   # tercina de semínima
    (Fraction(1,  3), 3, 2, "2"),   # tercina de mínima
    # quintinas ─ 5 no tempo de 4
    (Fraction(1, 20), 5, 4, "16"),
    (Fraction(1, 10), 5, 4, "8"),
    (Fraction(1,  5), 5, 4, "4"),
    # sétimas ─ 7 no tempo de 4
    (Fraction(1, 28), 7, 4, "16"),
    (Fraction(1, 14), 7, 4, "8"),
    (Fraction(1,  7), 7, 4, "4"),
    # nônimas ─ 9 no tempo de 8  (quiálteras complexas)
    (Fraction(1, 36), 9, 8, "16"),
    (Fraction(1, 18), 9, 8, "8"),
]

# Pesos: tercinas mais frequentes, complexas mais raras
DURATION_WEIGHTS_TUPLET = [
    0.20, 0.15, 0.08,   # tercinas
    0.14, 0.11, 0.07,   # quintinas
    0.09, 0.07, 0.04,   # sétimas
    0.03, 0.02,         # nônimas
]

# Complexidade disponível por nível (1=tercinas · 2=+quintinas · 3=+sétimas+nônimas)
TUPLET_COMPLEXITY_SLICES = {1: slice(0,3), 2: slice(0,6), 3: slice(0,11)}

# Lookup rápido duração → (num, den, base_lily)
TUPLET_INFO: dict = {dur: (n, d, b) for dur, n, d, b in TUPLET_TABLE}

# Pitches cromáticos disponíveis (uma oitava neutra — ajustado por tessitura depois)
PITCH_CHROMATIC_BASE = _PITCH_CLASSES  # 12 alturas


# ─────────────────────────────────────────────────────────────────────────────
#  MarkovEngine — orquestra as 5 matrizes
# ─────────────────────────────────────────────────────────────────────────────

class MarkovEngine:
    """
    Motor principal de composição por Cadeias de Markov.

    Gerencia 5 matrizes independentes:
      - pitch     : classe de pitch cromático (c, cis, d, ees, ...)
      - duration  : duração rítmica (Fraction)
      - dynamic   : dinâmica (Dynamic enum)
      - technique : técnica estendida (Technique enum, filtrado por instrumento)
      - microtone : microtonalismo (Microtone enum)

    Uso mínimo:
        engine = MarkovEngine(order=1)
        engine.train_uniform()
        events = engine.generate(64, "Violin")

    Uso com MIDI:
        engine = MarkovEngine(order=2)
        engine.train_from_midi("piece.mid")
        events = engine.generate(128, "Cello")
    """

    def __init__(self, order: int = 1):
        self.order = order
        self.matrices: dict[str, MarkovMatrix] = {
            "pitch":     MarkovMatrix(order),
            "duration":  MarkovMatrix(order),
            "dynamic":   MarkovMatrix(order),
            "technique": MarkovMatrix(order),
            "microtone": MarkovMatrix(order),
        }
        self._trained            = False
        self._rest_probability   = 0.12   # atualizado por train_uniform()

    # ── Treinamento ──────────────────────────────────────────────

    def train_uniform(
        self,
        instrument_name: str = "Violin",
        rest_probability: float = 0.12,
        microtone_probability: float = 0.25,
        tuplet_probability: float = 0.0,
        tuplet_complexity: int = 1,
        dynamic_weights: list = None,
    ) -> None:
        """
        Inicializa matrizes com distribuições pré-definidas.

        Args:
            instrument_name:   Define quais técnicas são válidas.
            rest_probability:  Proporção de pausas (0.0–0.5).
            microtone_probability: Probabilidade de microtons.
            tuplet_probability: Fração de durações com quiáltera.
            tuplet_complexity: 1=tercinas · 2=+quintinas · 3=+sétimas/nônimas
            dynamic_weights:   Pesos para [ppp,pp,p,mp,mf,f,ff,fff].
                               None = padrão contemporâneo (favorece suave).
        """
        self._tuplet_probability = tuplet_probability
        self._tuplet_complexity  = tuplet_complexity
        self._rest_probability   = rest_probability   # guardado para safety_limit em generate()
        # ── Pitch: cromático completo + pausas ───────────────────
        # rest_probability = fração real desejada de pausas.
        # Ex: 0.20 → 20% dos eventos são pausas.
        # "r" entra como UM estado com peso = rest_probability.
        # As 12 notas cromáticas dividem os restantes (1 - rest_probability).
        harmonic_pitches = {"c", "g", "e", "bes", "d", "f"}
        pitch_states     = list(PITCH_CHROMATIC_BASE)       # 12 alturas
        raw_weights      = [1.5 if p in harmonic_pitches else 1.0
                            for p in pitch_states]
        note_share       = max(0.001, 1.0 - rest_probability)
        raw_total        = sum(raw_weights)
        note_weights     = [w / raw_total * note_share for w in raw_weights]

        self.matrices["pitch"] = MarkovMatrix.weighted(
            pitch_states + ["r"],
            note_weights + [rest_probability],
            self.order,
        )

        # ── Duração: pesos contemporâneos + quiálteras opcionais ──
        if tuplet_probability > 0.0:
            slc         = TUPLET_COMPLEXITY_SLICES.get(tuplet_complexity, slice(0,3))
            tup_durs    = [row[0] for row in TUPLET_TABLE[slc]]
            tup_wts     = DURATION_WEIGHTS_TUPLET[slc.start : slc.stop]
            scale_std   = 1.0 - tuplet_probability
            scale_tup   = tuplet_probability
            std_sum     = sum(DURATION_WEIGHTS_CONTEMPORARY)
            tup_sum     = sum(tup_wts)
            dur_states  = DURATIONS_STANDARD + tup_durs
            dur_weights = (
                [w / std_sum * scale_std for w in DURATION_WEIGHTS_CONTEMPORARY] +
                [w / tup_sum * scale_tup for w in tup_wts]
            )
        else:
            dur_states  = DURATIONS_STANDARD
            dur_weights = DURATION_WEIGHTS_CONTEMPORARY
        self.matrices["duration"] = MarkovMatrix.weighted(
            dur_states, dur_weights, self.order
        )

        # ── Dinâmica: pesos configuráveis ────────────────────────
        # dynamic_weights = [ppp, pp, p, mp, mf, f, ff, fff]
        # NIENTE mantido com peso fixo moderado (não configurável via GUI)
        _default_weights = [2.5, 3.0, 3.0, 2.5, 2.0, 1.5, 1.0, 0.5]
        _user_weights    = dynamic_weights if dynamic_weights else _default_weights
        # Garantir 8 valores — truncar ou completar com zeros
        _user_weights = (_user_weights + [0.0] * 8)[:8]
        # NIENTE: peso = média dos dois valores extremos do usuário (ppp + fff) / 2
        niente_w  = (_user_weights[0] + _user_weights[7]) / 2 + 0.5
        dyn_objs  = list(Dynamic)  # [NIENTE, PPP, PP, P, MP, MF, F, FF, FFF]
        dyn_wts   = [niente_w] + _user_weights  # 9 valores total

        self.matrices["dynamic"] = MarkovMatrix.weighted(
            dyn_objs, dyn_wts, self.order
        )

        # ── Técnica: filtrada por família instrumental ────────────
        valid_techs = list(InstrumentFamily.valid_techniques(instrument_name))
        # ORDINARIO tem peso bem maior (é o estado padrão)
        tech_weights = [
            4.0 if t == Technique.ORDINARIO else 1.0
            for t in valid_techs
        ]
        self.matrices["technique"] = MarkovMatrix.weighted(
            valid_techs, tech_weights, self.order
        )

        # ── Microtone: maioria temperada, alguns microtons ────────
        micro_list    = list(Microtone)
        n_micro_states = len(micro_list) - 1  # excluindo NONE
        w_none  = 1.0 - microtone_probability
        w_each  = microtone_probability / n_micro_states
        micro_weights = [w_none] + [w_each] * n_micro_states
        self.matrices["microtone"] = MarkovMatrix.weighted(
            micro_list, micro_weights, self.order
        )

        self._trained = True

    def train_from_sequences(
        self,
        pitches:    list,
        durations:  list,
        dynamics:   list,
        techniques: list,
        microtones: list,
    ) -> None:
        """
        Treina todas as matrizes a partir de sequências extraídas externamente
        (ex.: de um arquivo MIDI parseado pelo usuário).

        Todas as listas devem ter o mesmo comprimento.
        """
        assert len(pitches) == len(durations) == len(dynamics), \
            "Todas as sequências devem ter o mesmo comprimento."

        self.matrices["pitch"].train(pitches)
        self.matrices["duration"].train(durations)
        self.matrices["dynamic"].train(dynamics)
        self.matrices["technique"].train(techniques)
        self.matrices["microtone"].train(microtones)
        self._trained = True

    # ── Geração ──────────────────────────────────────────────────

    def generate(
        self,
        n_notes: int,
        instrument_name: str = "Violin",
        allow_microtones: bool = True,
        notation_type: NotationType = NotationType.NORMAL,
    ) -> list[NoteEvent]:
        """
        Gera uma sequência de NoteEvents para um instrumento específico.

        Args:
            n_notes:          Número de eventos a gerar.
            instrument_name:  Nome do instrumento (define tessitura e técnicas).
            allow_microtones: Se False, força todos os microtons para NONE.
            notation_type:    Tipo de notação (NORMAL, PROPORTIONAL, GRAPHIC).

        Returns:
            Lista de NoteEvent prontos para o AbjadEngine.
        """
        if not self._trained:
            raise RuntimeError(
                "Motor não treinado. Chame train_uniform() ou train_from_sequences()."
            )

        valid_techs = InstrumentFamily.valid_techniques(instrument_name)

        # ── Estado inicial de cada parâmetro ──────────────────────
        pitch_ctx    = tuple(self.matrices["pitch"].random_start()    for _ in range(self.order))
        dur_ctx      = tuple(self.matrices["duration"].random_start() for _ in range(self.order))
        dyn_ctx      = tuple(self.matrices["dynamic"].random_start()  for _ in range(self.order))
        tech_ctx     = tuple(self.matrices["technique"].random_start() for _ in range(self.order))
        micro_ctx    = tuple(self.matrices["microtone"].random_start() for _ in range(self.order))

        events: list[NoteEvent] = []
        notes_generated = 0     # conta apenas notas sonoras (não pausas)
        # safety_limit: quantas iterações máximas para gerar n_notes sonoras.
        # Com rest_probability=p, espera-se n_notes/(1-p) iterações em média.
        # Multiplicamos por 5 para cobrir variância estatística.
        # Mínimo de n_notes*8 para casos com p muito baixo.
        _rest_p = getattr(self, "_rest_probability", 0.5)
        _expected_iters = n_notes / max(0.01, 1.0 - _rest_p)
        safety_limit    = max(n_notes * 8, int(_expected_iters * 5))
        iterations      = 0

        while notes_generated < n_notes and iterations < safety_limit:
            iterations += 1
            # ── Amostrar próximo estado de cada parâmetro ─────────
            pitch_val  = self.matrices["pitch"].sample(pitch_ctx)
            dur_val    = self.matrices["duration"].sample(dur_ctx)
            _tuplet    = TUPLET_INFO.get(dur_val)  # (num, den, base) ou None
            dyn_val    = self.matrices["dynamic"].sample(dyn_ctx)
            tech_val   = self.matrices["technique"].sample(tech_ctx)
            micro_val  = self.matrices["microtone"].sample(micro_ctx)

            # ── Filtros de coerência ──────────────────────────────

            # 1. Técnica deve ser válida para o instrumento
            if tech_val not in valid_techs:
                tech_val = Technique.ORDINARIO

            # 2. Microtons: se desabilitados, forçar NONE
            if not allow_microtones:
                micro_val = Microtone.NONE

            # 3. Microtons: pausas não têm microtom
            is_rest = (pitch_val == "r") or (pitch_val is None)
            if is_rest:
                micro_val = Microtone.NONE

            # 4. Ajustar pitch à tessitura do instrumento
            if not is_rest and pitch_val is not None:
                # pitch_val é classe de pitch; precisamos de pitch completo com oitava
                # Usar oitava central do instrumento como âncora
                lo, hi   = InstrumentFamily.midi_range(instrument_name)
                mid_midi = (lo + hi) // 2
                # Partir da nota com oitava central e ajustar
                base_octave = mid_midi // 12 - 1
                # Construir pitch com oitava
                if base_octave >= 4:
                    oitava_str = "'" * (base_octave - 3)
                elif base_octave == 3:
                    oitava_str = ""
                else:
                    oitava_str = "," * (3 - base_octave)
                pitch_with_octave = f"{pitch_val}{oitava_str}"
                # Ajustar à tessitura
                pitch_final = adjust_to_range(pitch_with_octave, instrument_name)
            else:
                pitch_final = None

            # ── Construir NoteEvent ───────────────────────────────
            if is_rest:
                event = NoteEvent.rest(duration=dur_val, dynamic=dyn_val)
            else:
                event = NoteEvent(
                    pitch_name     = pitch_final,
                    duration       = dur_val,
                    dynamic        = dyn_val,
                    technique      = tech_val,
                    microtone      = micro_val,
                    notation_type  = notation_type,
                    velocity       = dyn_val.to_velocity(),
                    tuplet_ratio   = (_tuplet[0], _tuplet[1]) if _tuplet else None,
                )

            events.append(event)
            if not is_rest:
                notes_generated += 1  # só notas sonoras contam para n_notes

            # ── Avançar contexto (janela deslizante de ordem N) ───
            pitch_ctx = pitch_ctx[1:] + (pitch_val,)
            dur_ctx   = dur_ctx[1:]   + (dur_val,)
            dyn_ctx   = dyn_ctx[1:]   + (dyn_val,)
            tech_ctx  = tech_ctx[1:]  + (tech_val,)
            micro_ctx = micro_ctx[1:] + (micro_val,)

        return events

    # ── Composição multi-instrumento ─────────────────────────────

    def generate_score(
        self,
        instruments: list[str],
        n_notes: int,
        allow_microtones: bool = True,
        notation_type: NotationType = NotationType.NORMAL,
    ) -> dict[str, list[NoteEvent]]:
        """
        Gera sequências independentes para múltiplos instrumentos.
        Cada instrumento usa as MESMAS matrizes mas estados iniciais
        diferentes — garantindo diversidade textural.

        Returns:
            dict {instrument_name: [NoteEvent, ...]}
        """
        return {
            instr: self.generate(n_notes, instr, allow_microtones, notation_type)
            for instr in instruments
        }

    # ── Exportação de análise ─────────────────────────────────────

    def export_matrices(self, output_dir: str | Path) -> None:
        """Exporta todas as matrizes de transição como CSVs."""
        output_dir = Path(output_dir)
        output_dir.mkdir(parents=True, exist_ok=True)
        for name, matrix in self.matrices.items():
            matrix.export_csv(output_dir / f"matrix_{name}.csv")
        print(f"✅ Matrizes exportadas em: {output_dir.resolve()}")


# ─────────────────────────────────────────────────────────────────────────────
#  Quantização de durações respeitando compasso
#  (migrado do código original com adaptações para Fraction)
# ─────────────────────────────────────────────────────────────────────────────

TIME_SIGNATURE_VALUES: dict[str, Fraction] = {
    "4/4":  Fraction(4, 4),
    "3/4":  Fraction(3, 4),
    "2/4":  Fraction(2, 4),
    "3/8":  Fraction(3, 8),
    "6/8":  Fraction(6, 8),
    "12/8": Fraction(12, 8),
    "5/4":  Fraction(5, 4),
    "7/8":  Fraction(7, 8),
}

def quantize_duration(dur: Fraction, grid: Fraction = Fraction(1, 16)) -> Fraction:
    """Quantiza duração para a grade rítmica mais próxima."""
    if grid == 0:
        return dur
    steps     = round(float(dur / grid))
    quantized = grid * max(1, steps)
    # Clamp: mín = fusa (1/16), máx = semibreve (1/1)
    return max(Fraction(1, 16), min(Fraction(1, 1), quantized))

def generate_time_sig_sequence(
    base_sig: str,
    n_measures: int,
    random_changes: bool = False,
    change_prob: float = 0.15,
) -> list[tuple[int, str]]:
    """
    Gera sequência de fórmulas de compasso compartilhada por todos os
    instrumentos (garante sincronia).

    Returns:
        Lista de (measure_number, time_sig_str)
    """
    available = list(TIME_SIGNATURE_VALUES.keys())
    sequence  = [(1, base_sig)]
    current   = base_sig

    if not random_changes:
        return sequence

    for m in range(2, n_measures + 1):
        if random.random() < change_prob:
            others  = [s for s in available if s != current]
            current = random.choice(others)
            sequence.append((m, current))

    return sequence


# ─────────────────────────────────────────────────────────────────────────────
#  Teste de integração
# ─────────────────────────────────────────────────────────────────────────────

if __name__ == "__main__":
    print("=" * 60)
    print("  Teste: MarkovEngine")
    print("=" * 60)

    # 1. Criar motor de ordem 1
    engine = MarkovEngine(order=1)

    # 2. Treinar sem MIDI (modo uniforme)
    engine.train_uniform(
        instrument_name      = "Violin",
        rest_probability     = 0.10,
        microtone_probability= 0.20,
    )
    print("\n✅ Treinamento uniforme concluído")

    # 3. Gerar para conjunto de câmara
    instruments = ["Violin", "Viola", "Violoncello", "Flute"]
    score_data  = engine.generate_score(instruments, n_notes=12)

    print(f"\n✅ Geração: {len(instruments)} instrumentos × 12 notas\n")

    for instr, events in score_data.items():
        family  = InstrumentFamily.family_of(instr)
        techs   = {e.technique for e in events if not e.is_rest}
        pitches = [e.full_pitch_name for e in events if not e.is_rest]
        micros  = [e.microtone for e in events if e.microtone != Microtone.NONE]

        print(f"  {instr:15} ({family})")
        print(f"    Pitches:    {pitches[:6]} ...")
        print(f"    Técnicas:   {[t.name for t in techs]}")
        print(f"    Microtons:  {len(micros)} eventos com microtom")
        print()

    # 4. Verificar filtro de técnicas por família
    sep = "  " + "─" * 48
    print(sep)
    print("  Verificação de filtro de técnicas:")
    for instr in ["Violin", "Flute", "Horn", "Piano"]:
        valid = InstrumentFamily.valid_techniques(instr)
        print(f"  {instr:10}: {len(valid)} técnicas — {[t.name for t in sorted(valid, key=lambda x: x.name)]}")

    # 5. Verificar ajuste de tessitura
    print(f"\n{sep}")
    print("  Verificação de tessitura:")
    test_pitches = ["c'", "c''", "c,", "c'''", "fis''"]
    for instr in ["Violin", "Tuba", "Flute"]:
        lo, hi = InstrumentFamily.midi_range(instr)
        print(f"\n  {instr} (MIDI {lo}–{hi}):")
        for p in test_pitches:
            adjusted = adjust_to_range(p, instr)
            print(f"    {p:8} → {adjusted}")

    # 6. Teste de quantização e compassos
    print(f"\n{sep}")
    print("  Sequência de compassos (random_changes=True, 8 compassos):")
    seq = generate_time_sig_sequence("4/4", 8, random_changes=True, change_prob=0.4)
    for m, ts in seq:
        print(f"    Compasso {m}: {ts}")

    print("\n" + "=" * 60)
    print("  ✅ Todos os testes passaram!")
    print("=" * 60)
