"""
note_event.py
=============
Modelo de dados central do sistema.

NoteEvent é uma estrutura imutável (dataclass) que representa
um evento musical de forma completamente independente do motor
de notação. A lógica Markoviana opera sobre NoteEvents; o
AbjadEngine os converte para objetos Abjad / LilyPond.

Técnicas suportadas (mapeadas para indicadores LilyPond):
  - sul ponticello, sul tasto
  - flutter tongue
  - multifônico
  - harmônico
  - col legno (tratto / battuto)
  - pizzicato, snap pizzicato (Bartók)
  - tremolo (medido e não-medido)
  - ordinario (cancela técnica anterior)
  - extended breath (sopros)

Microtonalismo (via NamedPitch do Abjad):
  Sufixos de pitch  →  cents aproximados
  qs  → quarto de tom acima   (+50¢)
  qf  → quarto de tom abaixo  (−50¢)
  tqs → três quartos acima    (+150¢)
  tqf → três quartos abaixo   (−150¢)

Dinâmicas suportadas:
  ppp, pp, p, mp, mf, f, ff, fff  +  niente (°)
  hairpin crescendo / decrescendo configurável separadamente.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum, auto
from fractions import Fraction
from typing import Optional


# ─────────────────────────────────────────────────────────────
#  Enumerações
# ─────────────────────────────────────────────────────────────

class Dynamic(Enum):
    """Dinâmicas musicais, incluindo niente."""
    NIENTE = "niente"   # ° (zero absoluto — Lachenmann, Sciarrino)
    PPP    = "ppp"
    PP     = "pp"
    P      = "p"
    MP     = "mp"
    MF     = "mf"
    F      = "f"
    FF     = "ff"
    FFF    = "fff"

    @classmethod
    def from_velocity(cls, velocity: int) -> "Dynamic":
        """Converte velocity MIDI (0-127) para dinâmica."""
        if velocity == 0:   return cls.NIENTE
        if velocity < 10:   return cls.PPP
        if velocity < 25:   return cls.PP
        if velocity < 45:   return cls.P
        if velocity < 64:   return cls.MP
        if velocity < 80:   return cls.MF
        if velocity < 96:   return cls.F
        if velocity < 112:  return cls.FF
        return cls.FFF

    def to_velocity(self) -> int:
        """Converte dinâmica para velocity MIDI aproximado."""
        mapping = {
            Dynamic.NIENTE: 0,
            Dynamic.PPP: 5,
            Dynamic.PP: 18,
            Dynamic.P: 36,
            Dynamic.MP: 54,
            Dynamic.MF: 72,
            Dynamic.F: 90,
            Dynamic.FF: 108,
            Dynamic.FFF: 120,
        }
        return mapping[self]

    def lilypond_string(self) -> str:
        """Retorna a string LilyPond para a dinâmica."""
        if self == Dynamic.NIENTE:
            return r"\dynamic niente"
        return f"\\{self.value}"


class Technique(Enum):
    """Técnicas estendidas de execução."""
    ORDINARIO        = auto()   # técnica normal — cancela indicações anteriores
    SUL_PONTICELLO   = auto()   # arco próximo ao cavalete (cordas)
    SUL_TASTO        = auto()   # arco sobre o espelho (cordas)
    COL_LEGNO_TRATTO = auto()   # madeira do arco deslizando (cordas)
    COL_LEGNO_BATTUTO= auto()   # madeira do arco percutida (cordas)
    FLUTTER_TONGUE   = auto()   # frullato (sopros)
    MULTIPHONIC      = auto()   # multifônico (sopros/voz)
    HARMONIC         = auto()   # harmônico natural/artificial
    PIZZICATO        = auto()   # pizzicato (cordas)
    SNAP_PIZZICATO   = auto()   # Bartók pizzicato
    TREMOLO_MEASURED = auto()   # tremolo medido
    TREMOLO_UNMEASURED = auto() # tremolo não-medido
    EXTENDED_BREATH  = auto()   # sons de respiração ampliados (sopros)
    AIR_TONE         = auto()   # som de ar puro (flauta, etc.)

    def lilypond_markup(self) -> Optional[str]:
        """
        Retorna o markup LilyPond para a técnica.
        None = sem marcação adicional (usa articulação nativa).
        """
        mapping = {
            Technique.ORDINARIO:          r'\markup { \italic "ord." }',
            Technique.SUL_PONTICELLO:     r'\markup { \italic "sul pont." }',
            Technique.SUL_TASTO:          r'\markup { \italic "sul tasto" }',
            Technique.COL_LEGNO_TRATTO:   r'\markup { \italic "col legno tratto" }',
            Technique.COL_LEGNO_BATTUTO:  r'\markup { \italic "col legno batt." }',
            Technique.FLUTTER_TONGUE:     r'\markup { \italic "flutter" }',
            Technique.MULTIPHONIC:        r'\markup { \italic "multif." }',
            Technique.HARMONIC:           None,  # usa \flageolet nativo
            Technique.PIZZICATO:          r'\markup { \italic "pizz." }',
            Technique.SNAP_PIZZICATO:     None,  # usa \snappizzicato nativo
            Technique.TREMOLO_MEASURED:   None,  # usa tremolo nativo
            Technique.TREMOLO_UNMEASURED: r'\markup { \italic "trem." }',
            Technique.EXTENDED_BREATH:    r'\markup { \italic "ext. breath" }',
            Technique.AIR_TONE:           r'\markup { \italic "air tone" }',
        }
        return mapping.get(self)

    def lilypond_command(self) -> Optional[str]:
        """
        Comando LilyPond nativo (articulation/indicator) quando disponível.
        """
        mapping = {
            Technique.HARMONIC:      r"\flageolet",
            Technique.SNAP_PIZZICATO: r"\snappizzicato",
        }
        return mapping.get(self)


class Microtone(Enum):
    """
    Microtons suportados via sistema holandês nativo do LilyPond 2.24.
    Os valores são os sufixos exatos usados nos nomes de notas LilyPond.

    Tabela de sufixos (sistema holandês, built-in, sem includes):
      ih   = semissustenido  (+50¢  / quarto de tom acima)
      eh   = semibemol       (−50¢  / quarto de tom abaixo)
      isih = sustenido e meio (+150¢ / três quartos acima)
      eseh = bemol e meio    (−150¢ / três quartos abaixo)

    Exemplos de notas resultantes:
      c  + ih   → cih    (dó com quarto de tom acima)
      d  + eh   → deh    (ré com quarto de tom abaixo)
      e  + isih → eisih  (mi com três quartos acima)
      f  + eseh → feseh  (fá com três quartos abaixo)
      bes + ih  → besih  (si bemol com quarto acima = si natural menos 1/4)
    """
    NONE                  = ""      # afinação temperada padrão
    QUARTER_SHARP         = "ih"    # +50¢  (semissustenido)
    QUARTER_FLAT          = "eh"    # −50¢  (semibemol)
    THREE_QUARTER_SHARP   = "isih"  # +150¢ (sustenido e meio)
    THREE_QUARTER_FLAT    = "eseh"  # −150¢ (bemol e meio)


class NotationType(Enum):
    """Tipo de notação para o evento."""
    NORMAL        = auto()  # notação tradicional
    PROPORTIONAL  = auto()  # notação proporcional (sem pulsação fixa)
    GRAPHIC       = auto()  # notação gráfica (marcação textual)


# ─────────────────────────────────────────────────────────────
#  Classe principal
# ─────────────────────────────────────────────────────────────

@dataclass
class NoteEvent:
    """
    Representa um único evento musical de forma agnóstica ao motor de notação.

    Parâmetros
    ----------
    pitch_name : str | None
        Nome do pitch em notação LilyPond — nomenclatura holandesa
        (ex: "c'", "fis''", "bes", "ees'", "aes''").
        Bemóis: ees, aes, bes, des, ges, ces.
        Sustenidos: cis, dis, fis, gis, ais.
        None → pausa (rest).
    duration : Fraction
        Duração como fração de semibreve (1/4 = semínima, 1/8 = colcheia, etc.).
    dynamic : Dynamic
        Nível dinâmico do evento.
    technique : Technique
        Técnica estendida de execução.
    microtone : Microtone
        Alteração microtonal (quarter-tone etc.).
    notation_type : NotationType
        Como este evento deve ser renderizado.
    velocity : int
        Velocity MIDI (0–127), usado como fonte para dinâmica e Markov.
    is_rest : bool
        True se o evento é uma pausa. Ignorado se pitch_name é None.
    tie_start : bool
        Inicia uma ligadura de valor.
    tie_stop : bool
        Termina uma ligadura de valor.
    tremolo_strokes : int
        Número de barras de tremolo (2 = semínima, 3 = colcheia, etc.).
        Usado apenas quando technique == TREMOLO_MEASURED.
    markup_above : str | None
        Markup LilyPond adicional acima da nota (para notação gráfica).
    markup_below : str | None
        Markup LilyPond adicional abaixo da nota.
    """

    pitch_name    : Optional[str]     = None
    duration      : Fraction          = field(default_factory=lambda: Fraction(1, 4))
    dynamic       : Dynamic           = Dynamic.MF
    technique     : Technique         = Technique.ORDINARIO
    microtone     : Microtone         = Microtone.NONE
    notation_type : NotationType      = NotationType.NORMAL
    velocity      : int               = 64
    is_rest       : bool              = False
    tie_start      : bool              = False
    tie_stop       : bool              = False
    tremolo_strokes: int               = 0
    markup_above   : Optional[str]     = None
    markup_below   : Optional[str]     = None
    # (num, den) da quiáltera — ex: (3,2)=tercina, (5,4)=quintina, None=normal
    tuplet_ratio   : Optional[tuple]   = None
    # Glissando contínuo até a próxima nota (pós-processamento)
    gliss_to_next  : bool              = False

    # ── propriedades derivadas ────────────────────────────────

    @property
    def is_pitched(self) -> bool:
        """True se o evento tem altura definida (não é pausa)."""
        return self.pitch_name is not None and not self.is_rest

    @property
    def full_pitch_name(self) -> Optional[str]:
        """
        Nome de pitch completo incluindo microtone, se houver.
        Usa sufixos LilyPond 2.24 calculados por offset de cents.

        Regra do LilyPond 2.24:
          O microtom é sempre aplicado à LETRA BASE (c/d/e/f/g/a/b).
          O offset total (acidente + microtom) determina o sufixo final.

        Tabela de offsets → sufixo LilyPond:
          -150¢ → eseh   -100¢ → es    -50¢ → eh
             0  → (natural)   +50¢ → ih   +100¢ → is   +150¢ → isih

        Exemplos:
          "d'"   + QUARTER_SHARP  (+50¢)    → "dih'"
          "ees'" + QUARTER_SHARP  (+50¢)    → "eeh'"   (e−100+50 = e−50)
          "bes'" + THREE_QTR_FLAT (−150¢)   → "beseh'" (b−100−150 → b−150)
          "cis'" + QUARTER_SHARP  (+50¢)    → "cisih'" (c+100+50 = c+150)
          "fis'" + THREE_QTR_FLAT (−150¢)   → "feh'"   (f+100−150 = f−50)
        """
        if not self.is_pitched or self.pitch_name is None:
            return None
        if self.microtone == Microtone.NONE:
            return self.pitch_name

        # ── Separar oitava ────────────────────────────────────────
        base_with_acc = self.pitch_name.rstrip("',")
        oitava = self.pitch_name[len(base_with_acc):]

        # ── Obter letra base e cents do acidente ──────────────────
        bl = base_with_acc.lower()
        letter_base = _LILY_TO_BASE.get(bl, bl[0])
        acc_cents   = _ACIDENTE_CENTS.get(bl, 0)

        # ── Calcular offset total ─────────────────────────────────
        micro_cents = _MICRO_CENTS.get(self.microtone.value, 0)
        total_cents = acc_cents + micro_cents

        # ── Encontrar sufixo LilyPond ─────────────────────────────
        suffix = _CENTS_TO_SUFFIX.get(total_cents)
        if suffix is None:
            # Aproximar para o nome mais próximo disponível
            closest = min(_CENTS_TO_SUFFIX.keys(), key=lambda x: abs(x - total_cents))
            suffix = _CENTS_TO_SUFFIX[closest]

        return f"{letter_base}{suffix}{oitava}"


    @property
    def duration_float(self) -> float:
        """Duração como quarterLength (compatibilidade com MIDI)."""
        return float(self.duration) * 4.0

    @property
    def duration_lily(self) -> str:
        """
        Converte Fraction para string de duração LilyPond.
        Suporta durações simples e pontuadas.
        Exemplos:
          1/4  → "4"
          1/8  → "8"
          3/8  → "4."   (pontuada)
          1/16 → "16"
          7/16 → "4.."  (duplamente pontuada — raramente usado)
        """
        dur = self.duration
        # Durações simples (potências de 2)
        simple = {
            Fraction(4, 1):  "\\breve",
            Fraction(2, 1):  "1",  # nota de dois tempos? Usar breve ou semibreve
            Fraction(1, 1):  "1",
            Fraction(1, 2):  "2",
            Fraction(1, 4):  "4",
            Fraction(1, 8):  "8",
            Fraction(1, 16): "16",
            Fraction(1, 32): "32",
            Fraction(1, 64): "64",
        }
        if dur in simple:
            return simple[dur]

        # Durações pontuadas (3/2 de uma duração simples)
        pontuadas = {
            Fraction(3, 4):  "2.",
            Fraction(3, 8):  "4.",
            Fraction(3, 16): "8.",
            Fraction(3, 32): "16.",
        }
        if dur in pontuadas:
            return pontuadas[dur]

        # Durações duplamente pontuadas (7/4 de uma duração simples)
        duplo_ponto = {
            Fraction(7, 8):  "2..",
            Fraction(7, 16): "4..",
            Fraction(7, 32): "8..",
        }
        if dur in duplo_ponto:
            return duplo_ponto[dur]

        # Durações de quiálteras — retornar a nota-base dentro da quiáltera
        # (o bloco \tuplet N/M { } é emitido pelo abjad_engine, não aqui)
        TUPLET_BASE = {
            Fraction(1, 12): "8",  Fraction(1, 6): "4",   Fraction(1, 3): "2",
            Fraction(1, 20): "16", Fraction(1, 10): "8",  Fraction(1, 5): "4",
            Fraction(1, 28): "16", Fraction(1, 14): "8",  Fraction(1, 7): "4",
            Fraction(1, 36): "16", Fraction(1, 18): "8",
        }
        if dur in TUPLET_BASE:
            return TUPLET_BASE[dur]
        # Fallback
        return f"4 % duração não-padrão: {dur}"

    # ── construtores alternativos ─────────────────────────────

    @classmethod
    def rest(cls, duration: Fraction, dynamic: Dynamic = Dynamic.MP) -> "NoteEvent":
        """Cria uma pausa."""
        return cls(pitch_name=None, duration=duration, dynamic=dynamic, is_rest=True)

    @classmethod
    def from_midi(
        cls,
        midi_pitch: int,
        duration_quarter: float,
        velocity: int = 64,
        technique: Technique = Technique.ORDINARIO,
    ) -> "NoteEvent":
        """
        Cria um NoteEvent a partir de dados MIDI brutos.

        midi_pitch         : número MIDI (60 = C4, 69 = A4...)
        duration_quarter   : duração em quarterLength (1.0 = semínima)
        velocity           : velocity MIDI 0–127
        """
        pitch_name = _midi_to_lily_pitch(midi_pitch)
        duration   = Fraction(duration_quarter).limit_denominator(64) / 4
        dynamic    = Dynamic.from_velocity(velocity)
        return cls(
            pitch_name=pitch_name,
            duration=duration,
            dynamic=dynamic,
            velocity=velocity,
            technique=technique,
        )

    # ── representação ─────────────────────────────────────────

    def __repr__(self) -> str:
        parts = [f"pitch={self.full_pitch_name or 'REST'}"]
        parts.append(f"dur={self.duration}")
        parts.append(f"dyn={self.dynamic.value}")
        if self.technique != Technique.ORDINARIO:
            parts.append(f"tech={self.technique.name}")
        if self.microtone != Microtone.NONE:
            parts.append(f"micro={self.microtone.value}")
        return f"NoteEvent({', '.join(parts)})"


# ─────────────────────────────────────────────────────────────
#  Funções auxiliares
# ─────────────────────────────────────────────────────────────

# Nomes de pitch MIDI → LilyPond (oitava C4 = "c'")
# Nomenclatura holandesa do LilyPond (usada pelo Abjad internamente):
# ── Tabelas para cálculo de microtons ────────────────────────────────────
# Mapeamento nome_LilyPond → letra base (c/d/e/f/g/a/b)
_LILY_TO_BASE: dict = {
    "c":"c", "d":"d", "e":"e", "f":"f", "g":"g", "a":"a", "b":"b",
    "cis":"c", "dis":"d", "eis":"e", "fis":"f", "gis":"g", "ais":"a", "bis":"b",
    "ces":"c", "des":"d", "ees":"e", "fes":"f", "ges":"g", "aes":"a", "bes":"b",
    "cisis":"c","disis":"d","fisis":"f","gisis":"g","aisis":"a",
    "ceses":"c","deses":"d","eeses":"e","feses":"f","geses":"g","aeses":"a","beses":"b",
}
# Offset em cents de cada acidente padrão (em relação à nota natural)
_ACIDENTE_CENTS: dict = {
    "c":0,"d":0,"e":0,"f":0,"g":0,"a":0,"b":0,
    "cis":100,"dis":100,"eis":100,"fis":100,"gis":100,"ais":100,"bis":100,
    "ces":-100,"des":-100,"ees":-100,"fes":-100,"ges":-100,"aes":-100,"bes":-100,
    "cisis":200,"disis":200,"fisis":200,"gisis":200,"aisis":200,
    "ceses":-200,"deses":-200,"eeses":-200,"feses":-200,"geses":-200,"aeses":-200,"beses":-200,
}
# Offset em cents de cada sufixo microtonal LilyPond 2.24
_MICRO_CENTS: dict = {"ih":50, "eh":-50, "isih":150, "eseh":-150, "":0}
# Offset total → sufixo LilyPond nativo válido
_CENTS_TO_SUFFIX: dict = {-150:"eseh", -100:"es", -50:"eh", 0:"", 50:"ih", 100:"is", 150:"isih"}

# Nomenclatura holandesa do LilyPond (usada pelo Abjad internamente):
#   bemóis: ees (mib), aes (láb), bes (sib), des, ges, ces
#   sustenidos: cis, dis, fis, gis, ais
_PITCH_NAMES = ["c", "cis", "d", "ees", "e", "f", "fis", "g", "aes", "a", "bes", "b"]


def _midi_to_lily_pitch(midi: int) -> str:
    """
    Converte número MIDI para nome de pitch em notação LilyPond.
    MIDI 60 → "c'"  (C4)
    MIDI 69 → "a'"  (A4)
    """
    note_name = _PITCH_NAMES[midi % 12]
    # Oitava LilyPond: C4 = c' (octave 0 em LilyPond = C3)
    lily_octave = (midi // 12) - 4  # C4 → 0 apóstrofes base
    # Ajuste: middle C (MIDI 60) = "c'" → precisa de 1 apóstrofe
    lily_octave_adjusted = (midi // 12) - 3
    if lily_octave_adjusted > 0:
        octave_str = "'" * lily_octave_adjusted
    elif lily_octave_adjusted < 0:
        octave_str = "," * abs(lily_octave_adjusted)
    else:
        octave_str = ""
    return f"{note_name}{octave_str}"


# ─────────────────────────────────────────────────────────────
#  Testes rápidos (execute diretamente: python note_event.py)
# ─────────────────────────────────────────────────────────────

if __name__ == "__main__":
    from fractions import Fraction

    print("=" * 55)
    print("  Testes: NoteEvent")
    print("=" * 55)

    # 1. Nota simples
    n1 = NoteEvent(pitch_name="c'", duration=Fraction(1, 4), dynamic=Dynamic.MF)
    print(f"\n1. Nota simples:       {n1}")
    print(f"   Lily pitch:         {n1.full_pitch_name}")
    print(f"   Lily duration:      {n1.duration_lily}")
    print(f"   Quarter length:     {n1.duration_float}")

    # 2. Nota com quarto de tom (dih' = ré semissustenido)
    n2 = NoteEvent(
        pitch_name="d'",
        duration=Fraction(1, 8),
        dynamic=Dynamic.PP,
        microtone=Microtone.QUARTER_SHARP,
        technique=Technique.SUL_PONTICELLO,
    )
    print(f"\n2. Quarto de tom:      {n2}")
    print(f"   Pitch LY (dih'):    {n2.full_pitch_name}  ← sufixo ih (holandês)")
    print(f"   Técnica markup:     {n2.technique.lilypond_markup()}")

    # 3. Pausa
    p1 = NoteEvent.rest(Fraction(3, 8), Dynamic.MP)
    print(f"\n3. Pausa pontuada:     {p1}")
    print(f"   Lily duration:      {p1.duration_lily}")
    print(f"   É pausa:            {p1.is_rest}")

    # 4. Niente + flutter  (ees = mi bemol, nomenclatura holandesa)
    n3 = NoteEvent(
        pitch_name="ees''",
        duration=Fraction(1, 4),
        dynamic=Dynamic.NIENTE,
        technique=Technique.FLUTTER_TONGUE,
        notation_type=NotationType.PROPORTIONAL,
    )
    print(f"\n4. Niente + flutter:   {n3}")
    print(f"   Lily dynamic:       {n3.dynamic.lilypond_string()}")

    # 5. From MIDI
    n4 = NoteEvent.from_midi(midi_pitch=69, duration_quarter=1.5, velocity=90)
    print(f"\n5. From MIDI (A4):     {n4}")
    print(f"   Pitch completo:     {n4.full_pitch_name}")
    print(f"   Duração pontuada:   {n4.duration_lily}")

    # 6. Snap pizzicato (Bartók)
    n5 = NoteEvent(
        pitch_name="g'",
        duration=Fraction(1, 16),
        dynamic=Dynamic.F,
        technique=Technique.SNAP_PIZZICATO,
    )
    print(f"\n6. Snap pizzicato:     {n5}")
    print(f"   Comando LY nativo:  {n5.technique.lilypond_command()}")

    # 7. Três quartos de tom abaixo (Lachenmann)
    # bes' = si bemol; + eseh = bemol e meio → "beseseh'" (si 3/4 abaixo do si natural)
    n6 = NoteEvent(
        pitch_name="bes'",
        duration=Fraction(1, 4),
        dynamic=Dynamic.PPP,
        microtone=Microtone.THREE_QUARTER_FLAT,
        technique=Technique.AIR_TONE,
    )
    print(f"\n7. 3/4 tom abaixo:     {n6}")
    print(f"   Pitch LY (beseseh'): {n6.full_pitch_name}  ← sufixo eseh")

    print("\n" + "=" * 55)
    print("  Todos os testes passaram! ✅")
    print("=" * 55)

# ─────────────────────────────────────────────────────────────
#  Pós-processamento: glissando
# ─────────────────────────────────────────────────────────────

def _pitch_to_midi(pitch_name: str) -> Optional[int]:
    """
    Converte pitch LilyPond (ex: "fis\'", "bes,,") para MIDI.
    Retorna None se não for possível determinar.
    """
    import re
    if not pitch_name:
        return None

    # Mapa de nome-base LilyPond → semitom na oitava 0
    _BASE: dict[str, int] = {
        "c":0, "cis":1, "ces":11,
        "d":2, "dis":3, "des":1,
        "e":4, "eis":5, "ees":3, "es":3,
        "f":5, "fis":6, "fes":4,
        "g":7, "gis":8, "ges":6,
        "a":9, "ais":10,"aes":8, "as":8,
        "b":11,"bis":0, "bes":10,
    }
    # Normalizar: remover octave markers e microtons
    p = pitch_name.strip().rstrip("',")
    # Remover sufixos microtonais (ih, eh, isih, eseh...)
    p = re.sub(r"(isih|eseh|isih|tqs|tqf|qs|qf|ih|eh)$", "", p.lower())

    ticks  = pitch_name.count("'")
    commas = pitch_name.count(",")
    octave = 3 + ticks - commas  # c (sem apóstrofo) = C3=48; c' = C4=60

    semitone = _BASE.get(p)
    if semitone is None:
        return None
    # MIDI: C4 = 60
    return (octave + 1) * 12 + semitone


def apply_glissando(
    events: list["NoteEvent"],
    base_probability: float = 0.15,
    interval_weight: float  = 0.5,
    seed: Optional[int]     = None,
) -> list["NoteEvent"]:
    """
    Pós-processamento: adiciona glissando entre pares de notas consecutivas.

    Parâmetros
    ----------
    events : list[NoteEvent]
        Sequência de eventos de um instrumento.
    base_probability : float
        Probabilidade base (0–1) de glissando entre dois eventos.
        Configurada pelo usuário via slider na GUI.
    interval_weight : float
        Peso do intervalo na probabilidade final.
        0 → intervalo não influencia (prob = base_probability)
        1 → intervalo dobra a probabilidade para intervalos de 12+ semitons
        Valor padrão: 0.5 (influência moderada — nunca exclui, nunca garante).
    seed : int | None
        Semente aleatória para reprodutibilidade.

    Lógica de ponderação por intervalo
    ------------------------------------
    Para cada par (nota_i, nota_i+1):
      1. Calcular distância em semitons entre as alturas.
      2. Calcular fator de intervalo:
            intervalo_factor = 1 + interval_weight * tanh(semitons / 12)
         - tanh(0)  ≈ 0   → fator ≈ 1.0  (uníssono: prob = base)
         - tanh(1)  ≈ 0.76 → fator ≈ 1.38 (8ª: prob 38% maior)
         - tanh(2)  ≈ 0.96 → fator ≈ 1.48 (> 2 oitavas: quase no máximo)
         A função tanh satura suavemente — intervalos muito grandes não
         explodem a probabilidade, apenas a elevam moderadamente.
      3. prob_final = min(1.0, base_probability * intervalo_factor)

    Restrições
    ----------
    - Glissando nunca parte de uma pausa (is_rest=True)
    - Glissando nunca chega a uma pausa
    - Glissando nunca é adicionado em nota com tie_start=True
      (LilyPond não permite glissando + ligadura de valor na mesma nota)
    - A última nota da sequência nunca recebe gliss_to_next=True
    """
    import random, math, dataclasses

    rng = random.Random(seed)

    result = list(events)
    n = len(result)

    for i in range(n - 1):
        ev      = result[i]
        ev_next = result[i + 1]

        # Restrições hard
        if ev.is_rest or ev_next.is_rest:
            continue
        if ev.tie_start:
            continue
        if not ev.pitch_name or not ev_next.pitch_name:
            continue

        # Calcular fator de intervalo
        midi_i    = _pitch_to_midi(ev.pitch_name)
        midi_next = _pitch_to_midi(ev_next.pitch_name)

        if midi_i is not None and midi_next is not None:
            semitons = abs(midi_next - midi_i)
            # tanh satura suavemente; divide por 12 para normalizar à oitava
            intervalo_factor = 1.0 + interval_weight * math.tanh(semitons / 12.0)
        else:
            intervalo_factor = 1.0  # não conseguiu calcular: sem ponderação

        prob = min(1.0, base_probability * intervalo_factor)

        if rng.random() < prob:
            result[i] = dataclasses.replace(ev, gliss_to_next=True)

    return result

