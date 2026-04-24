# Guia de Notação / Notation Guide

## Técnicas Estendidas / Extended Techniques

| Enum | Símbolo na partitura | Instrumento |
|------|---------------------|-------------|
| `ORDINARIO` | `ord.` | Todos |
| `SUL_PONTICELLO` | `s.p.` | Cordas |
| `SUL_TASTO` | `s.t.` | Cordas |
| `COL_LEGNO` | `c.l.` | Cordas |
| `PIZZICATO` | `pizz.` | Cordas |
| `HARMONICO` | `harm.` + cabeça de losango | Cordas |
| `FLUTTER_TONGUE` | `flatt.` | Madeiras, Metais |
| `MULTIFONICO` | `mult.` | Madeiras |
| `TREMOLO_MEASURED` | `trem.` | Todos |
| `TREMOLO_UNMEASURED` | `trem.~~~` | Todos |

## Microtonalismo

| Enum | Sufixo LilyPond | Simbologia | Valor |
|------|----------------|------------|-------|
| `NONE` | — | ♮ | natural |
| `QS` | `qs` | ↑¼ | +¼ tom (quarter-sharp) |
| `QF` | `qf` | ↓¼ | −¼ tom (quarter-flat) |
| `TQS` | `tqs` | ↑¾ | +¾ tom (three-quarter-sharp) |
| `TQF` | `tqf` | ↓¾ | −¾ tom (three-quarter-flat) |

Requer `\language "english"` no preâmbulo LilyPond.

## Dinâmicas

| Enum | LilyPond | Simbologia |
|------|----------|------------|
| `NIENTE` | `^\markup { \dynamic "o" }` | ° |
| `PPP` | `\ppp` | ppp |
| `PP` | `\pp` | pp |
| `P` | `\p` | p |
| `MP` | `\mp` | mp |
| `MF` | `\mf` | mf |
| `F` | `\f` | f |
| `FF` | `\ff` | ff |
| `FFF` | `\fff` | fff |

## Cabeças de Nota — Percussão Indefinida

| Estilo | Override LilyPond | Símbolo | Uso |
|--------|------------------|---------|-----|
| `default` | `\revert NoteHead.style` | ● oval | Peles, altura definida |
| `cross` | `\override NoteHead.style = #'cross` | × | Hi-Hat, Ride, Pratos a 2 |
| `xcircle` | `\override NoteHead.style = #'xcircle` | ⊗ | Hi-Hat aberto, Bell of Ride |
| `triangle` | `\override NoteHead.style = #'triangle` | △ | Crash, Triângulo, Tam-Tam |
| `diamond` | `\override NoteHead.style = #'diamond` | ◇ | Splash, Crotales |
| `la` | `\override NoteHead.style = #'la` | ▲ | Cowbell |
| `do` | `\override NoteHead.style = #'do` | □ | Woodblock, Claves |

## Posições de Pauta — Percussão Indefinida

```
Linha 6 (aux. sup.)  a''  → Crash △  Triângulo △  Splash ◇  Crotales ◇
Espaço 5             g''  → Prato Suspenso △  Pratos a 2 ×
Linha 4 (1ª)         f''  → Hi-Hat ×/⊗  Ride ×  Bell of Ride ⊗
Espaço 3             e''  → Cowbell ▲  Woodblock ag. □  Claves □
Linha 2 (2ª)         d''  → Tom Agudo ●  Woodblock gr. □
Espaço 1             c''  → Tom Médio ●
Linha 0 (3ª central) b'   → Tam-Tam △
Espaço -1            a'   → Tom Grave ●
Linha -2 (4ª)        g'   → Caixa Clara ●
Espaço -3            f'   → Tom de Chão ●  Tantã ●
Espaço -5            d'   → Gongo ●
Linha -6 (aux. inf.) c'   → Bumbo ●  Hi-Hat de Pé ×
```

## Notação Proporcional — Layout LilyPond

```lilypond
\layout {
  \context {
    \Score
    proportionalNotationDuration = #(ly:make-moment 1/16)
    \remove Timing_translator
    \remove Default_bar_line_engraver
    \override BarLine.transparent = ##t
    \override BarNumber.transparent = ##t
    \override KeySignature.transparent = ##t
    \override TimeSignature.transparent = ##t
    \override Stem.thickness = 0.8
    \override TupletBracket.thickness = 0.6
    \override TupletNumber.font-size = -2
    \override DynamicText.font-size = -1
    \override Hairpin.thickness = 0.8
  }
  \context {
    \Staff
    \override Glissando.style = #'line
    \override Clef.font-size = -1
    \override NoteHead.font-size = -0.5
    \override StaffSymbol.thickness = 0.6
  }
}
```

## Claves por Instrumento

| Família | Instrumento | Clave LilyPond |
|---------|-------------|----------------|
| Madeiras | Flute, Oboe, Clarinet | `treble` |
| Madeiras | Bassoon | `bass` |
| Metais | Horn, Trumpet | `treble` |
| Metais | Trombone, Tuba | `bass` |
| Cordas | Violin | `treble` |
| Cordas | Viola | `alto` |
| Cordas | Violoncello | `tenor` / `bass` |
| Cordas | Double Bass | `bass` |
| Perc. def. | Vibraphone, Marimba, Xylophone, Glockenspiel, Crotales | `treble` |
| Perc. def. | Timpani | `bass` |
| Perc. indef. | Todos | `percussion` |
