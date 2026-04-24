"""
percussion.py — módulo de percussão para Markov-Abjad Composer

Referências:
  Weinberg "Guide to Standardized Drumset Notation" (PAS, 1998)
  Gould "Behind Bars" pp. 600-650
  Blatter "Instrumentation and Orchestration" cap. Percussion
"""
from __future__ import annotations
from dataclasses import dataclass
from typing import Optional


@dataclass(frozen=True)
class DrumVoice:
    """
    Instrumento de percussão de altura indefinida.
    staff_pos: posição na pauta (+6=linha aux. sup. ... -6=linha aux. inf.)
    note_head: estilo de cabeça LilyPond
    stem_dir : "up" | "down" | "neutral"
    midi_note: MIDI GM canal 10
    """
    name      : str
    name_pt   : str
    staff_pos : int
    note_head : str
    stem_dir  : str
    midi_note : int
    lily_kw   : str
    group     : str = ""


# Posições de referência (Weinberg / Gould / imagens fornecidas):
#  +6 linha aux. superior  → Crash, Triângulo, Splash
#  +5 espaço acima 1ª      → Prato Suspenso, Pratos a 2
#  +4 1ª linha             → Hi-Hat, Ride
#  +3 espaço 1ª–2ª         → Cowbell, Woodblock ag., Efeitos
#  +2 2ª linha             → Tom Agudo
#  +1 espaço 2ª–3ª         → Tom Médio
#   0 3ª linha central     → Tam-Tam
#  -1 espaço 3ª–4ª         → Tom Grave
#  -2 4ª linha             → Caixa Clara
#  -3 espaço 4ª–5ª         → Tom de Chão, Tantã, Woodblock gr.
#  -5 espaço abaixo 5ª     → Gongo
#  -6 linha aux. inferior  → Bumbo, Hi-Hat de pé

DRUM_VOICES: dict[str, DrumVoice] = {
    # Pratos
    "crash":        DrumVoice("Crash Cymbal",     "Prato Crash",    6, "triangle","up",  49,"cymc",  "cymbal"),
    "splash":       DrumVoice("China/Splash",     "China/Splash",   6, "diamond", "up",  52,"cymca", "cymbal"),
    "suspended":    DrumVoice("Suspended Cymbal", "Prato Suspenso", 5, "triangle","up",  57,"cymca", "cymbal"),
    "pratos_a2":    DrumVoice("Cymbals (clash)",  "Pratos a 2",     5, "cross",   "up",  49,"cymc",  "cymbal"),
    "ride":         DrumVoice("Ride Cymbal",      "Prato Ride",     4, "cross",   "up",  51,"cymr",  "cymbal"),
    "ride_bell":    DrumVoice("Bell of Ride",     "Campainha Ride", 4, "xcircle", "up",  53,"rb",    "cymbal"),
    "hihat":        DrumVoice("Hi-Hat (closed)",  "Hi-Hat Fechado", 4, "cross",   "up",  42,"hh",    "cymbal"),
    "hihat_open":   DrumVoice("Hi-Hat (open)",    "Hi-Hat Aberto",  4, "xcircle", "up",  46,"hhho",  "cymbal"),
    "hihat_foot":   DrumVoice("Hi-Hat (foot)",    "Hi-Hat com Pé", -6, "cross",  "down", 44,"hhp",   "cymbal"),
    "tamtam":       DrumVoice("Tam-Tam",          "Tam-Tam",        0, "triangle","up",  49,"cymc",  "cymbal"),
    # Peles
    "snare":        DrumVoice("Snare Drum",       "Caixa Clara",   -2, "default", "up",  38,"sn",    "drum"),
    "snare_rim":    DrumVoice("Rim Shot",         "Borda/Rimshot", -2, "cross",   "up",  37,"ss",    "drum"),
    "bass_drum":    DrumVoice("Bass Drum",        "Bumbo",         -6, "default","down", 36,"bd",    "drum"),
    "tantan":       DrumVoice("Tan-Tan",          "Tantã",         -3, "default","down", 41,"tomfl", "drum"),
    "gongo":        DrumVoice("Gong",             "Gongo",         -5, "default","down", 39,"bd",    "drum"),
    "tom_high":     DrumVoice("High Tom",         "Tom Agudo",      2, "default", "up",  50,"tomh",  "drum"),
    "tom_mid":      DrumVoice("Mid Tom",          "Tom Médio",      1, "default", "up",  47,"tommh", "drum"),
    "tom_low":      DrumVoice("Low Tom",          "Tom Grave",     -1, "default", "up",  45,"toml",  "drum"),
    "tom_floor":    DrumVoice("Floor Tom",        "Tom de Chão",   -3, "default", "up",  41,"tomfl", "drum"),
    # Efeitos
    "triangle":     DrumVoice("Triangle (open)", "Triângulo",       6, "triangle","up",  81,"tri",   "effect"),
    "tri_muted":    DrumVoice("Triangle (muted)","Triângulo Abaf.", 6, "cross",   "up",  80,"tri",   "effect"),
    "woodblock_h":  DrumVoice("Woodblock (high)","Woodblock Ag.",   3, "do",      "up",  76,"wbh",   "effect"),
    "woodblock_l":  DrumVoice("Woodblock (low)", "Woodblock Gr.",   2, "do",      "up",  77,"wbl",   "effect"),
    "cowbell":      DrumVoice("Cowbell",          "Cowbell",         3, "la",      "up",  56,"cb",    "effect"),
    "tambourine":   DrumVoice("Tambourine",       "Pandeiro",        3, "default", "up",  54,"tamb",  "effect"),
    "claves":       DrumVoice("Claves",           "Claves",          3, "do",      "up",  75,"wbh",   "effect"),
    "crotales_u":   DrumVoice("Crotales",         "Crotales",        6, "diamond", "up",  76,"tri",   "effect"),
    "vibraslap":    DrumVoice("Vibraslap",        "Vibraslap",       2, "default", "up",  58,"wbl",   "effect"),
}

DRUM_ALIASES: dict[str, str] = {
    "Snare Drum":"snare",    "Caixa Clara":"snare",   "Caixa":"snare",
    "Rim Shot":"snare_rim",  "Borda":"snare_rim",
    "Bass Drum":"bass_drum", "Bumbo":"bass_drum",
    "Tan-Tan":"tantan",      "Tantã":"tantan",
    "Tom High":"tom_high",   "Tom Agudo":"tom_high",
    "Tom Mid":"tom_mid",     "Tom Médio":"tom_mid",
    "Tom Low":"tom_low",     "Tom Grave":"tom_low",
    "Floor Tom":"tom_floor", "Tom de Chão":"tom_floor",
    "Gong":"gongo",          "Gongo":"gongo",
    "Hi-Hat":"hihat",        "Hi-Hat Fechado":"hihat",  "Closed Hi-Hat":"hihat",
    "Hi-Hat Aberto":"hihat_open",  "Open Hi-Hat":"hihat_open",
    "Hi-Hat com Pé":"hihat_foot",  "Pedal Hi-Hat":"hihat_foot",
    "Ride Cymbal":"ride",    "Ride":"ride",             "Prato Ride":"ride",
    "Bell of Ride":"ride_bell",
    "Crash Cymbal":"crash",  "Crash":"crash",           "Prato Crash":"crash",
    "Suspended Cymbal":"suspended", "Prato Suspenso":"suspended",
    "Cymbals (clash)":"pratos_a2",  "Pratos a 2":"pratos_a2",
    "China/Splash":"splash", "Splash":"splash",
    "Tam-Tam":"tamtam",
    "Triangle":"triangle",   "Triângulo":"triangle",
    "Woodblock":"woodblock_h","Woodblock Agudo":"woodblock_h","Woodblock Grave":"woodblock_l",
    "Cowbell":"cowbell",
    "Tambourine":"tambourine","Pandeiro":"tambourine",
    "Claves":"claves",
    "Crotales":"crotales_u",
    "Vibraslap":"vibraslap",
}


def resolve_drum_voice(name: str) -> Optional[DrumVoice]:
    key = DRUM_ALIASES.get(name) or name.lower().replace(" ", "_")
    return DRUM_VOICES.get(key)


# ─────────────────────────────────────────────────────────────
#  Percussão de ALTURA DEFINIDA
# ─────────────────────────────────────────────────────────────

PITCHED_PERCUSSION: dict[str, tuple[int, int]] = {
    "Vibraphone":   (53,  89),
    "Marimba":      (36,  96),
    "Xylophone":    (60,  96),
    "Glockenspiel": (79, 108),
    "Timpani":      (40,  65),
    "Crotales":     (60,  84),
}

PITCHED_PERCUSSION_ALIASES: dict[str, str] = {
    "Vibrafone":"Vibraphone", "Vibraphone":"Vibraphone",
    "Marimba":"Marimba",
    "Tímpano":"Timpani",   "Timpani":"Timpani",   "Timp.":"Timpani",
    "Glockenspiel":"Glockenspiel",
    "Xilofone":"Xylophone","Xylophone":"Xylophone",
    "Crotales":"Crotales",
}

PITCHED_PERCUSSION_CLEF: dict[str, str] = {
    "Vibraphone":"treble", "Marimba":"treble", "Xylophone":"treble",
    "Glockenspiel":"treble", "Timpani":"bass",  "Crotales":"treble",
}


def is_pitched_percussion(name: str) -> bool:
    canonical = PITCHED_PERCUSSION_ALIASES.get(name, name)
    return canonical in PITCHED_PERCUSSION


def is_unpitched_percussion(name: str) -> bool:
    return resolve_drum_voice(name) is not None


# ─────────────────────────────────────────────────────────────
#  NoteHead overrides LilyPond
# ─────────────────────────────────────────────────────────────

NOTEHEAD_OVERRIDE: dict[str, str] = {
    "cross":    r"\override NoteHead.style = #'cross",
    "xcircle":  r"\override NoteHead.style = #'xcircle",
    "triangle": r"\override NoteHead.style = #'triangle",
    "diamond":  r"\override NoteHead.style = #'diamond",
    "slash":    r"\override NoteHead.style = #'slash",
    "la":       r"\override NoteHead.style = #'la",
    "do":       r"\override NoteHead.style = #'do",
    "open":     r"\override NoteHead.style = #'xcircle",
    "default":  r"\revert NoteHead.style",
}
NOTEHEAD_REVERT = r"\revert NoteHead.style"


# ─────────────────────────────────────────────────────────────
#  Posição de pauta → pitch LilyPond
# ─────────────────────────────────────────────────────────────

_STAFF_POS_TO_LILY: dict[int, str] = {
     6:"a''",  5:"g''",  4:"f''",  3:"e''",  2:"d''",  1:"c''",
     0:"b'",  -1:"a'",  -2:"g'",  -3:"f'",  -4:"e'",  -5:"d'", -6:"c'",
}


def drum_voice_to_lily_pitch(voice: DrumVoice) -> str:
    return _STAFF_POS_TO_LILY.get(voice.staff_pos, "b'")


# ─────────────────────────────────────────────────────────────
#  Catálogo para a GUI
# ─────────────────────────────────────────────────────────────

PERCUSSION_BY_CATEGORY: dict[str, list[str]] = {
    "Perc. Altura Def.": ["Vibraphone","Marimba","Timpani","Xylophone","Glockenspiel","Crotales"],
    "Peles":             ["Snare Drum","Bass Drum","Tan-Tan","Tom High","Tom Mid","Tom Low","Floor Tom","Gong"],
    "Pratos":            ["Hi-Hat","Ride Cymbal","Crash Cymbal","Suspended Cymbal","Cymbals (clash)","Tam-Tam","China/Splash"],
    "Perc. Efeitos":     ["Triangle","Woodblock","Cowbell","Tambourine","Claves","Vibraslap"],
}
