# Markov-Abjad Composer — Full Documentation

**Prof. Ivan Eiji Simurra · NICS / UNICAMP · 2026**

---

## Table of Contents

1. [Context and Motivation](#1-context-and-motivation)
2. [Markov Chains in Musical Composition](#2-markov-chains-in-musical-composition)
3. [System Architecture](#3-system-architecture)
4. [Instrumentation and Ranges](#4-instrumentation-and-ranges)
5. [Notation System](#5-notation-system)
6. [Installation and Setup](#6-installation-and-setup)
7. [Interface User Manual](#7-interface-user-manual)
8. [Output Files](#8-output-files)
9. [References](#9-references)
10. [Glossary](#10-glossary)

---

## 1. Context and Motivation

Algorithmic composition occupies a central space in musical thought of the 20th and 21st centuries, sitting at the intersection of music theory, mathematics, cognitive science, and technology. By delegating aspects of the creative process to formal systems, the composer does not abdicate their role but repositions it: from direct articulator of pitches and durations to architect of systems that generate musical material according to explicitly defined rules.

**Markov-Abjad Composer** enters this tradition with a specific focus: exploring stochastic processes — in particular Markov Chains — as a musical material generation engine, combining them with a high-precision contemporary notation system based on LilyPond and Abjad. The result is an environment where the controlled unpredictability of the Markov chain dialogues with the notational demands of contemporary chamber and orchestral music.

From an aesthetic standpoint, the system was conceived in dialogue with composers such as Morton Feldman (indeterminism and temporal density), Brian Ferneyhough (rhythmic complexity and nested tuplets), György Ligeti (micropolyphony and texture), Salvatore Sciarrino (extended techniques and extreme dynamics), and Helmut Lachenmann (musique concrète instrumentale).

---

## 2. Markov Chains in Musical Composition

### 2.1 Mathematical Foundations

A Markov Chain is a discrete stochastic process satisfying the **Markov property**: the probability of transitioning to a future state depends exclusively on the current state, not the history of previous states:

```
P(Sₙ₊₁ = s | S₁, S₂, ..., Sₙ) = P(Sₙ₊₁ = s | Sₙ)
```

The chain is described by a **transition matrix T**, where each element Tᵢⱼ represents the probability of transitioning from state i to state j. For **order-N chains**, the relevant context is formed by the N preceding states, expanding the context space to |S|ᴺ possible combinations.

### 2.2 Five Independent Matrices

The system uses five independent Markov matrices, each governing a distinct musical parameter:

| Parameter | State Space | Description |
|-----------|-------------|-------------|
| **Pitch** | 12 chromatic classes + microtones + rest R | Transitions between pitches |
| **Duration** | Whole, half, quarter, eighth, sixteenth, thirty-second (+ dotted) | Transitions between rhythmic values |
| **Dynamic** | ppp, pp, p, mp, mf, f, ff, fff, niente | Transitions between dynamic levels |
| **Technique** | ord., s.p., s.t., col legno, flutter, multiphonic, harm., tremolo, pizz. | Transitions between techniques |
| **Microtone** | natural, +¼, −¼, +¾, −¾ | Transitions between microtonal modifiers |

The **independence of matrices** is a deliberate architectural choice: rhythm and harmony evolve with their own internal logic, without forced correlation.

### 2.3 Training Modes

**Uniform Mode (default)**

Matrices are built with deterministically normalized weights using `itertools.product` to fill all possible N-gram contexts. This guarantees statistical precision: configuring 30% rests produces effectively ~30% rests. The chain's stochastic variance produces different sequences each generation.

**MIDI Mode (corpus)**

MIDI files are loaded and analyzed. Observed transitions feed the count matrices, which are then normalized. Multiple files can be combined (merge). A **progressive backoff** mechanism handles unobserved contexts:

1. Exact order-N context lookup
2. Backoff to order N−1 suffix
3. Continue down to order 1
4. Final fallback with `_default_weights` (preserves user parameters)

### 2.4 Generation: n_notes Counts Only Sounding Notes

The `n_notes` parameter defines the number of **sounding notes** (not including rests). The generation loop iterates until exactly `n_notes` sounding notes are produced, regardless of how many rests the chain inserts. A `safety_limit` based on `rest_probability` prevents infinite loops in extreme configurations.

---

## 3. System Architecture

### 3.1 Modules

| Module | Responsibility |
|--------|---------------|
| `gui.py` | Tkinter interface, parameters, threading, log, output buttons |
| `integration.py` | CompositionConfig, CompositionResult, pipelines, statistics, dashboard, export |
| `markov_engine.py` | MarkovMatrix, MarkovEngine, training, generation, InstrumentFamily, ranges |
| `abjad_engine.py` | Manual LilyPond generation, quantization, tuplets, hairpins, glissando, compilation |
| `note_event.py` | NoteEvent dataclass, enums, apply_glissando, _pitch_to_midi |
| `percussion.py` | DrumVoice, 29 instruments, PITCHED_PERCUSSION, NoteHead overrides |
| `midi_trainer.py` | MidiTrainer, MIDI analysis, corpus merge |

### 3.2 NoteEvent — Central Data Structure

```python
@dataclass(frozen=True)
class NoteEvent:
    pitch_name    : Optional[str]    # LilyPond pitch (e.g. "fis''", "bes,")
    duration      : Fraction          # exact duration (1/4 = quarter note)
    dynamic       : Dynamic           # enum: PPP...FFF, NIENTE
    technique     : Technique         # enum: ORDINARIO, SUL_PONTICELLO...
    microtone     : Microtone         # enum: NONE, QS, QF, TQS, TQF
    notation_type : NotationType      # NORMAL or PROPORTIONAL
    velocity      : int               # MIDI velocity (0–127)
    is_rest       : bool = False
    tuplet_ratio  : Optional[tuple] = None   # (num, den) e.g. (3,2)
    tie_start     : bool = False
    tie_stop      : bool = False
    gliss_to_next : bool = False
```

---

## 4. Instrumentation and Ranges

All ranges in **concert pitch** (sounding pitch), based on Adler (3rd ed.), Gould, and Blatter.

### Woodwinds
| Instrument | Range |
|------------|-------|
| Flute | B3–D7 |
| Oboe | Bb3–G6 |
| Clarinet | D3–Bb6 |
| Bassoon | Bb1–Eb5 |

### Brass
| Instrument | Range |
|------------|-------|
| Horn | B1–F5 |
| Trumpet | F#3–Bb5 |
| Trombone | E2–F5 |
| Tuba | D1–F4 |

### Strings
| Instrument | Range |
|------------|-------|
| Violin | G3–E7 |
| Viola | C3–E6 |
| Violoncello | C2–C6 |
| Double Bass | E1–C5 |
| Harp | C1–G7 |

### Pitched Percussion
| Instrument | Range | Clef |
|------------|-------|------|
| Vibraphone | F3–F6 | Treble |
| Marimba | C2–C7 | Treble |
| Timpani | E2–F4 | Bass |
| Xylophone | C4–C7 | Treble |
| Glockenspiel | G5–C8 (written) | Treble |
| Crotales | C4–C6 (written) | Treble |

### Unpitched Percussion

Staff positions and noteheads based on Weinberg (PAS, 1998) and Gould (Behind Bars, pp. 600–650):

| Instrument | Staff Position | Notehead |
|------------|---------------|----------|
| Crash Cymbal | Aux. line above | △ triangle |
| China/Splash | Aux. line above | ◇ diamond |
| Suspended Cymbal | Space above 1st line | △ triangle |
| Cymbals (clash) | Space above 1st line | × cross |
| Ride Cymbal | 1st line | × cross |
| Bell of Ride | 1st line | ⊗ xcircle |
| Hi-Hat (closed) | 1st line | × cross |
| Hi-Hat (open) | 1st line | ⊗ xcircle |
| Hi-Hat (foot) | Aux. line below | × cross |
| Tam-Tam | Middle (3rd) line | △ triangle |
| Snare Drum | 4th line | ● default |
| Bass Drum | Aux. line below | ● default |
| Tan-Tan | Space 4th–5th | ● default |
| High Tom | 2nd line | ● default |
| Mid Tom | Space 2nd–3rd | ● default |
| Low Tom | Space 3rd–4th | ● default |
| Floor Tom | Space 4th–5th | ● default |
| Gong | Space below 5th | ● default |
| Triangle | Aux. line above | △ triangle |
| Woodblock | Space 1st–2nd | □ do |
| Cowbell | Space 1st–2nd | ▲ la |
| Crotales | Aux. line above | ◇ diamond |
| Claves | Space 1st–2nd | □ do |

---

## 5. Notation System

### 5.1 Manual LilyPond Pipeline

LilyPond code is generated 100% manually (without `music21.lily.translate`), ensuring:
- Full control over every notational element
- Compatibility with remote deployment
- Significantly faster generation speed

Pipeline steps per instrument:
1. Clef resolution by family
2. Measure quantization with `Fraction` arithmetic
3. Event grouping into normal and tuplet blocks
4. Note emission with pitch, duration, dynamics, technique, and special markings
5. Spanner closure before barlines
6. Compilation with adaptive dynamic timeout

### 5.2 Proportional Graphical Notation

Activated via the "Proportional Notation" checkbox, produces Feldman/Cardew-style scores:

- `Timing_translator` and `Default_bar_line_engraver` removed → no bar lines
- `TimeSignature`, `KeySignature`, `BarNumber` transparent
- `proportionalNotationDuration` active → proportional horizontal spacing
- Rests emitted as spacers (`s`) → invisible, preserve temporal spacing
- Thinner stems, brackets, and dynamics → lighter, more abstract visual

### 5.3 Glissando Weighting Formula

```
P_final = min(1.0, P_base × (1 + w × tanh(Δsemitones / 12)))
```

where `P_base` is the Density slider and `w = 0.5` is the interval weight. Constraints: never leaves a rest, never arrives at a rest, never coexists with a tie.

---

## 6. Installation and Setup

### macOS

```bash
brew install lilypond
python3 -m venv venv
source venv/bin/activate
pip install -r requirements.txt
python gui.py
```

### Windows

```powershell
# Install Python from python.org (check "Add Python to PATH")
# Install LilyPond from lilypond.org
# Add to PATH: C:\Program Files (x86)\LilyPond\usr\bin

python -m venv venv
venv\Scripts\activate
pip install -r requirements.txt
python gui.py
```

### Linux

```bash
sudo apt install lilypond
python3 -m venv venv
source venv/bin/activate
pip install -r requirements.txt
python gui.py
```

---

## 7. Interface User Manual

### 7.1 Instrument Panel (left)

- Instruments grouped by family
- Click to select (amber highlight) / click again to deselect
- Multiple instances of the same instrument supported
- Buttons: Select All / Clear

### 7.2 MIDI Tab

| Control | Function |
|---------|----------|
| Add File/Folder | Load .mid files for training |
| Select track | Choose which track to analyze |
| Analyze Corpus | Process and train matrices |
| Clear Corpus | Return to uniform mode |

### 7.3 Musical Tab

| Parameter | Description |
|-----------|-------------|
| Chain Order | 1–4. Higher orders = more memory, more local coherence |
| Notes / instrument | Sounding notes per instrument (rests excluded) |
| Rests (%) | Proportion of rest events |
| Dynamics (weights) | Relative weight of each dynamic level (ppp to fff) |
| Hairpins | Auto crescendo/decrescendo between dynamic transitions |
| Tuplets | Density (%) and Complexity (1–4) |
| Glissando | Density (%) of glissandos between consecutive notes |
| BPM | Tempo in beats per minute |
| Time Signature | 4/4, 3/4, 2/4, 6/8, 5/4, 7/8 |
| Time Changes | Synchronized random meter changes across instruments |

### 7.4 Result Buttons

| Button | Action |
|--------|--------|
| Open PDF | Score in default viewer |
| Open .ly | LilyPond source code |
| Open MusicXML | Compatible with Sibelius, Finale, MuseScore |
| 📊 Dashboard | Visual analysis dashboard (PNG) |
| 📁 Analysis | Folder with all exported files |
| Export Matrices CSV | Markov matrices as CSV |

---

## 8. Output Files

### Score
| File | Content |
|------|---------|
| `{base}.ly` | LilyPond source code |
| `{base}.pdf` | PDF score |
| `{base}.xml` | MusicXML |

### Analysis
| File | Content |
|------|---------|
| `{base}_relatorio.txt` | Complete report with ASCII tables |
| `{base}_analise.json` | Full structured data |
| `{base}_eventos.csv` | One row per event with all parameters |
| `{base}_resumo.csv` | Summary per instrument |
| `{base}_dist_dinamicas.csv` | Dynamics distribution |
| `{base}_dist_duracoes.csv` | Duration values distribution |
| `{base}_dist_pitch.csv` | Pitch class distribution |
| `{base}_dist_tecnicas.csv` | Extended techniques distribution |
| `{base}_dist_microtons.csv` | Microtone distribution |
| `{base}_dashboard.png` | Visual dashboard (7 panels, 150 DPI) |

---

## 9. References

### Algorithmic Composition
- Xenakis, I. (1992). *Formalized Music*. Pendragon Press.
- Nierhaus, G. (2009). *Algorithmic Composition*. Springer.
- Roads, C. (1996). *The Computer Music Tutorial*. MIT Press.

### Markov Chains
- Norris, J. R. (1997). *Markov Chains*. Cambridge University Press.
- Pinkerton, R. C. (1956). Information Theory and Melody. *Scientific American*, 194(2), 77–86.

### Contemporary Notation
- Gould, E. (2011). *Behind Bars*. Faber Music.
- Stone, K. (1980). *Music Notation in the 20th Century*. W. W. Norton.
- Adler, S. (2002). *The Study of Orchestration* (3rd ed.). W. W. Norton.
- Weinberg, N. (1998). *Guide to Standardized Drumset Notation*. PAS Publications.

### Tools
- LilyPond Music Engraver (2.24+). [lilypond.org](https://lilypond.org)
- Abjad API (3.x). [abjad-api.readthedocs.io](https://abjad-api.readthedocs.io)
- mido. [mido.readthedocs.io](https://mido.readthedocs.io)

---

## 10. Glossary

| Term | Definition |
|------|------------|
| Markov Chain | Stochastic process where transition probability depends only on the current state |
| Transition matrix | Table of state-to-state transition probabilities |
| Backoff | Fallback strategy: when order-N context not observed, try lower orders |
| NoteEvent | Immutable dataclass representing a single musical event |
| LilyPond | Open-source music engraving system compiling text files into high-quality scores |
| Abjad | Python library for formalized LilyPond score control |
| Proportional notation | System without bar lines where horizontal space is proportional to duration |
| Tuplet | Irregular rhythmic subdivision: triplet (3:2), quintuplet (5:4), septuplet (7:4) |
| Microtone | Pitch between chromatic semitones. The system supports quarter tones (±¼, ±¾) |
| Hairpin | Crescendo (< ) or decrescendo (>) dynamic change symbol |
| Glissando | Continuous pitch slide between two notes |
| DrumVoice | Structure defining staff position and notehead for unpitched percussion |
| Concert pitch | Actual sounding pitch, regardless of notational transposition |
| n_notes | Number of **sounding** notes per instrument (rests are excluded from the count) |
