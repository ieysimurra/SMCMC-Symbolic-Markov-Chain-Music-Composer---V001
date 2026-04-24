"""
midi_trainer.py
===============
Treina o MarkovEngine a partir de um arquivo MIDI real.

Fluxo:
  arquivo.mid → parse → sequências (pitch, duration, velocity, interval)
              → MarkovEngine.train_from_sequences()
              → matrizes de probabilidade reais

Dependências: mido (pip install mido)
O music21 NÃO é usado aqui — mido é leve e sem dependências externas.

Uso:
    from midi_trainer import MidiTrainer
    trainer = MidiTrainer("bach_cello.mid")
    trainer.load()
    engine = trainer.train_engine(order=2)
    events = engine.generate(64, "Violoncello")
"""

from __future__ import annotations

import os
from collections import defaultdict
from fractions import Fraction
from pathlib import Path
from typing import Optional

# mido é a única dependência — leve e sem C extensions
try:
    import mido
    MIDO_AVAILABLE = True
except ImportError:
    MIDO_AVAILABLE = False


from note_event import Dynamic, Microtone, NoteEvent, Technique
from markov_engine import MarkovEngine, MarkovMatrix, InstrumentFamily


# ─────────────────────────────────────────────────────────────────────────────
#  Conversores MIDI ↔ domínio musical
# ─────────────────────────────────────────────────────────────────────────────

# Nomes de notas cromáticas (sistema LilyPond / holandês)
_MIDI_TO_LILY_NAME = [
    "c", "cis", "d", "ees", "e", "f",
    "fis", "g", "aes", "a", "bes", "b"
]

# Oitavas LilyPond: MIDI 60 = c' (oitava 4)
_LILY_OCTAVE = {
    0: ",,,,", 1: ",,,", 2: ",,", 3: ",",
    4: "'",    5: "''",  6: "'''", 7: "''''",
    8: "'''''",
}


def midi_to_lily(midi_note: int) -> str:
    """Converte número MIDI (0–127) para nome LilyPond. Ex: 60 → c'"""
    pc    = midi_note % 12
    octave = midi_note // 12 - 1   # MIDI 60 → oitava 4 → "'"
    name  = _MIDI_TO_LILY_NAME[pc]
    oct_str = _LILY_OCTAVE.get(octave, "'")
    return f"{name}{oct_str}"


def velocity_to_dynamic(velocity: int) -> Dynamic:
    """Mapeia velocity MIDI (0–127) para Dynamic."""
    if velocity == 0:   return Dynamic.NIENTE
    if velocity < 16:   return Dynamic.PPP
    if velocity < 32:   return Dynamic.PP
    if velocity < 48:   return Dynamic.P
    if velocity < 64:   return Dynamic.MP
    if velocity < 80:   return Dynamic.MF
    if velocity < 96:   return Dynamic.F
    if velocity < 112:  return Dynamic.FF
    return Dynamic.FFF


# Grade de durações válidas em quartos (quarter = 1.0)
_DURATION_GRID_QUARTERS = sorted([
    0.0625,   # 1/64
    0.125,    # 1/32
    0.1875,   # 3/64
    0.25,     # 1/16
    0.375,    # 3/32
    0.5,      # 1/8
    0.75,     # 3/16
    1.0,      # 1/4
    1.5,      # 3/8
    2.0,      # 1/2
    3.0,      # 3/4
    4.0,      # 1 (semibreve)
])


def snap_duration(quarters: float) -> Fraction:
    """Quantiza duração em quarters para fração LilyPond mais próxima."""
    quarters = max(0.0625, min(4.0, quarters))
    closest = min(_DURATION_GRID_QUARTERS, key=lambda g: abs(g - quarters))
    return Fraction(closest).limit_denominator(64)


# ─────────────────────────────────────────────────────────────────────────────
#  Extrator de eventos MIDI
# ─────────────────────────────────────────────────────────────────────────────

class MidiNote:
    """Nota extraída de um arquivo MIDI (antes de converter para NoteEvent)."""
    __slots__ = ("midi_pitch", "start_tick", "end_tick",
                 "velocity", "channel", "track")

    def __init__(self, midi_pitch, start_tick, end_tick,
                 velocity, channel=0, track=0):
        self.midi_pitch  = midi_pitch
        self.start_tick  = start_tick
        self.end_tick    = end_tick
        self.velocity    = velocity
        self.channel     = channel
        self.track       = track

    @property
    def duration_ticks(self) -> int:
        return self.end_tick - self.start_tick


def extract_midi_notes(path: str) -> tuple[list[MidiNote], int]:
    """
    Extrai todas as notas de um arquivo MIDI.

    Retorna (lista_de_MidiNote, ticks_por_quarter).
    Trata arquivos tipo 0 (canal único) e tipo 1 (múltiplas tracks).
    """
    if not MIDO_AVAILABLE:
        raise ImportError(
            "mido não instalado. Execute: pip install mido"
        )

    mid  = mido.MidiFile(path)
    tpq  = mid.ticks_per_beat  # ticks por quarter note

    all_notes: list[MidiNote] = []

    for track_idx, track in enumerate(mid.tracks):
        # note_on pendentes: {(channel, pitch): (start_tick, velocity)}
        pending: dict = {}
        current_tick = 0

        for msg in track:
            current_tick += msg.time

            if msg.type == "note_on" and msg.velocity > 0:
                key = (msg.channel, msg.note)
                pending[key] = (current_tick, msg.velocity)

            elif msg.type == "note_off" or (
                msg.type == "note_on" and msg.velocity == 0
            ):
                key = (msg.channel, msg.note)
                if key in pending:
                    start_tick, vel = pending.pop(key)
                    all_notes.append(MidiNote(
                        midi_pitch  = msg.note,
                        start_tick  = start_tick,
                        end_tick    = current_tick,
                        velocity    = vel,
                        channel     = msg.channel,
                        track       = track_idx,
                    ))

    # Ordenar por início temporal
    all_notes.sort(key=lambda n: (n.start_tick, n.midi_pitch))
    return all_notes, tpq


# ─────────────────────────────────────────────────────────────────────────────
#  MidiTrainer: análise e treinamento
# ─────────────────────────────────────────────────────────────────────────────

class MidiTrainer:
    """
    Analisa um arquivo MIDI e treina um MarkovEngine com as probabilidades
    extraídas das sequências reais de pitch, duração, dinâmica e intervalo.

    Uso básico:
        trainer = MidiTrainer("entrada.mid")
        trainer.load()
        engine = trainer.train_engine(order=2)
        events = engine.generate(64, "Violin")
    """

    def __init__(self, midi_path: str):
        self.midi_path = Path(midi_path)
        self._notes: list[MidiNote] = []
        self._tpq: int = 480
        self._loaded = False

        # Sequências extraídas (preenchidas por load())
        self.pitches:    list[str]     = []
        self.durations:  list[Fraction]= []
        self.dynamics:   list[Dynamic] = []
        self.intervals:  list[int]     = []   # semitones entre notas consecutivas
        self.velocities: list[int]     = []

        # Estatísticas
        self.stats: dict = {}

    # ── Carregamento ──────────────────────────────────────────────

    def load(self, track_filter: Optional[int] = None,
             channel_filter: Optional[int] = None) -> "MidiTrainer":
        """
        Carrega e parseia o arquivo MIDI.

        track_filter   : se fornecido, usa só essa track (0-indexed)
        channel_filter : se fornecido, usa só esse canal MIDI (0-indexed)
        """
        if not self.midi_path.exists():
            raise FileNotFoundError(f"MIDI não encontrado: {self.midi_path}")

        self._notes, self._tpq = extract_midi_notes(str(self.midi_path))

        # Filtros
        notes = self._notes
        if track_filter is not None:
            notes = [n for n in notes if n.track == track_filter]
        if channel_filter is not None:
            notes = [n for n in notes if n.channel == channel_filter]

        if not notes:
            raise ValueError(
                f"Nenhuma nota encontrada com track={track_filter}, "
                f"channel={channel_filter}."
            )

        # Extrair sequências
        self._extract_sequences(notes)
        self._loaded = True
        self._compute_stats()
        return self

    def _extract_sequences(self, notes: list[MidiNote]):
        """Converte lista de MidiNote em sequências de atributos."""
        prev_pitch = None
        prev_end   = 0

        for note in notes:
            # Pitch
            lily = midi_to_lily(note.midi_pitch)
            self.pitches.append(lily)
            self.velocities.append(note.velocity)
            self.dynamics.append(velocity_to_dynamic(note.velocity))

            # Duração em quarters
            dur_quarters = note.duration_ticks / self._tpq
            self.durations.append(snap_duration(dur_quarters))

            # Intervalo melódico (em semitons, para análise)
            if prev_pitch is not None:
                interval = note.midi_pitch - prev_pitch
                self.intervals.append(interval)
            prev_pitch = note.midi_pitch

    def _compute_stats(self):
        """Calcula estatísticas básicas para exibição."""
        from collections import Counter

        self.stats = {
            "total_notes":   len(self.pitches),
            "unique_pitches": len(set(self.pitches)),
            "pitch_freq":    Counter(self.pitches).most_common(10),
            "duration_freq": Counter(str(d) for d in self.durations).most_common(8),
            "dynamic_freq":  Counter(d.name for d in self.dynamics).most_common(),
            "avg_velocity":  sum(self.velocities) / len(self.velocities)
                             if self.velocities else 64,
            "pitch_range":   (
                midi_to_lily(min(n.midi_pitch for n in self._notes)),
                midi_to_lily(max(n.midi_pitch for n in self._notes)),
            ) if self._notes else ("?", "?"),
        }

    # ── Treinamento ───────────────────────────────────────────────

    def train_engine(
        self,
        order: int = 1,
        instrument_name: str = "Violin",
        add_microtone_layer: bool = True,
        microtone_probability: float = 0.10,
    ) -> MarkovEngine:
        """
        Cria e treina um MarkovEngine a partir das sequências extraídas.

        order              : ordem da cadeia de Markov (1–3)
        instrument_name    : instrumento alvo (filtra técnicas por família)
        add_microtone_layer: adiciona camada microtonal (não treinada por MIDI)
        microtone_probability: probabilidade de microtom (0–0.5)

        Retorna MarkovEngine pronto para gerar eventos.
        """
        if not self._loaded:
            raise RuntimeError("Chame load() antes de train_engine().")

        from note_event import Microtone
        import random as _rnd

        engine = MarkovEngine(order=order)

        # ── Técnicas: distribuição por família (MIDI não codifica) ─
        # Usar objetos Technique (não strings) — compatível com generate()
        valid_techs  = list(InstrumentFamily.valid_techniques(instrument_name))
        tech_weights = [4.0 if t == Technique.ORDINARIO else 1.0
                        for t in valid_techs]
        total_w = sum(tech_weights)
        cumulative = []
        acc = 0.0
        for w in tech_weights:
            acc += w / total_w
            cumulative.append(acc)
        # Gerar sequência de objetos Technique com comprimento = len(pitches)
        tech_seq = []
        for _ in range(len(self.pitches)):
            r = _rnd.random()
            for i, threshold in enumerate(cumulative):
                if r <= threshold:
                    tech_seq.append(valid_techs[i])
                    break
            else:
                tech_seq.append(valid_techs[-1])

        # ── Microtons: camada independente ────────────────────────
        # Usar objetos Microtone (não strings)
        all_micros     = list(Microtone)
        if add_microtone_layer:
            p_micro = microtone_probability / (len(all_micros) - 1)
            p_none  = 1.0 - microtone_probability
            micro_weights_raw = [p_none] + [p_micro] * (len(all_micros) - 1)
        else:
            micro_weights_raw = [1.0] + [0.0] * (len(all_micros) - 1)
        total_mw = sum(micro_weights_raw)
        cumulative_m = []
        acc = 0.0
        for w in micro_weights_raw:
            acc += w / total_mw
            cumulative_m.append(acc)
        micro_seq = []
        for _ in range(len(self.pitches)):
            r = _rnd.random()
            for i, threshold in enumerate(cumulative_m):
                if r <= threshold:
                    micro_seq.append(all_micros[i])
                    break
            else:
                micro_seq.append(Microtone.NONE)

        # ── Durações: converter Fraction → Fraction (já correto) ──
        # train_from_sequences aceita qualquer tipo hashável

        # ── Treinar via train_from_sequences ──────────────────────
        # Passa objetos enum e Fraction diretamente (como train_uniform faz)
        engine.train_from_sequences(
            pitches    = self.pitches,            # list[str]      ex: "a'"
            durations  = self.durations,          # list[Fraction]
            dynamics   = self.dynamics,           # list[Dynamic]  (objetos enum)
            techniques = tech_seq,                # list[Technique] (objetos enum)
            microtones = micro_seq,               # list[Microtone] (objetos enum)
        )

        return engine

    # ── Informações ───────────────────────────────────────────────

    def summary(self) -> str:
        """Retorna string formatada com resumo da análise do MIDI."""
        if not self._loaded:
            return "MIDI não carregado. Chame load() primeiro."

        s = self.stats
        lines = [
            f"MIDI: {self.midi_path.name}",
            f"  Notas total:     {s['total_notes']}",
            f"  Pitches únicos:  {s['unique_pitches']}",
            f"  Velocidade média:{s['avg_velocity']:.1f}",
            f"  Âmbito:          {s['pitch_range'][0]} – {s['pitch_range'][1]}",
            "",
            "  Pitches mais frequentes:",
        ]
        for pitch, count in s["pitch_freq"]:
            bar = "█" * min(20, count // max(1, s["total_notes"] // 40))
            lines.append(f"    {pitch:8} {count:4}  {bar}")

        lines += ["", "  Durações mais frequentes:"]
        for dur, count in s["duration_freq"]:
            lines.append(f"    {dur:8} {count:4}")

        lines += ["", "  Dinâmicas:"]
        for dyn, count in s["dynamic_freq"]:
            lines.append(f"    {dyn:6} {count:4}")

        return "\n".join(lines)

    def export_sequences_csv(self, output_dir: str = "output") -> str:
        """Exporta as sequências extraídas como CSV para inspeção."""
        if not self._loaded:
            raise RuntimeError("Chame load() primeiro.")

        Path(output_dir).mkdir(parents=True, exist_ok=True)
        path = Path(output_dir) / f"{self.midi_path.stem}_sequences.csv"

        with open(path, "w", encoding="utf-8") as f:
            f.write("index,pitch,duration,dynamic,velocity\n")
            for i, (p, d, dyn, v) in enumerate(zip(
                self.pitches, self.durations, self.dynamics, self.velocities
            )):
                f.write(f"{i},{p},{d},{dyn.name},{v}\n")

        return str(path)

    # ── Corpus multi-MIDI ─────────────────────────────────────────

    @staticmethod
    def merge_and_train(
        trainers: list["MidiTrainer"],
        order: int = 1,
        instrument_name: str = "Violin",
        add_microtone_layer: bool = True,
        microtone_probability: float = 0.10,
    ) -> "MarkovEngine":
        """
        Treina um único MarkovEngine a partir do corpus combinado de
        múltiplos MidiTrainers já carregados (load() chamado em cada um).

        As sequências de pitch e duration são concatenadas antes do
        treinamento — a cadeia de Markov vê todos os MIDIs como um
        único fluxo contínuo de eventos, ponderando suas probabilidades
        proporcionalmente ao tamanho de cada arquivo.

        Técnicas e microtons seguem a mesma lógica de train_engine()
        (distribuição por família — MIDI não os codifica).

        Args:
            trainers:             Lista de MidiTrainer já carregados.
            order:                Ordem da cadeia de Markov (1–3).
            instrument_name:      Instrumento alvo (define técnicas válidas).
            add_microtone_layer:  Inclui camada microtonal independente.
            microtone_probability: Probabilidade de microtom por nota (0–0.5).

        Returns:
            MarkovEngine pronto para gerar eventos.

        Raises:
            ValueError: se nenhum trainer tiver sido carregado.
        """
        if not trainers:
            raise ValueError("merge_and_train() requer ao menos um MidiTrainer.")

        loaded = [t for t in trainers if t._loaded]
        if not loaded:
            raise ValueError(
                "Nenhum MidiTrainer foi carregado. Chame load() em cada um."
            )

        # Concatenar sequências de todos os trainers
        all_pitches:   list = []
        all_durations: list = []
        all_dynamics:  list = []

        for t in loaded:
            all_pitches.extend(t.pitches)
            all_durations.extend(t.durations)
            all_dynamics.extend(t.dynamics)

        total = len(all_pitches)
        if total == 0:
            raise ValueError("Corpus vazio — nenhuma nota encontrada nos MIDIs.")

        # Técnicas: distribuição por família (MIDI não codifica)
        import random as _rnd
        valid_techs  = list(InstrumentFamily.valid_techniques(instrument_name))
        tech_weights = [4.0 if t == Technique.ORDINARIO else 1.0
                        for t in valid_techs]
        total_w = sum(tech_weights)
        cumulative = []
        acc = 0.0
        for w in tech_weights:
            acc += w / total_w
            cumulative.append(acc)

        tech_seq = []
        for _ in range(total):
            r = _rnd.random()
            for i, threshold in enumerate(cumulative):
                if r <= threshold:
                    tech_seq.append(valid_techs[i])
                    break
            else:
                tech_seq.append(valid_techs[-1])

        # Microtons: camada independente
        all_micros_list = list(Microtone)
        if add_microtone_layer:
            p_micro = microtone_probability / max(1, len(all_micros_list) - 1)
            p_none  = 1.0 - microtone_probability
            micro_w = [p_none] + [p_micro] * (len(all_micros_list) - 1)
        else:
            micro_w = [1.0] + [0.0] * (len(all_micros_list) - 1)

        total_mw = sum(micro_w)
        cumulative_m = []
        acc = 0.0
        for w in micro_w:
            acc += w / total_mw
            cumulative_m.append(acc)

        micro_seq = []
        for _ in range(total):
            r = _rnd.random()
            for i, threshold in enumerate(cumulative_m):
                if r <= threshold:
                    micro_seq.append(all_micros_list[i])
                    break
            else:
                micro_seq.append(Microtone.NONE)

        # Treinar engine com corpus combinado
        engine = MarkovEngine(order=order)
        engine.train_from_sequences(
            pitches    = all_pitches,
            durations  = all_durations,
            dynamics   = all_dynamics,
            techniques = tech_seq,
            microtones = micro_seq,
        )

        return engine

    @staticmethod
    def corpus_summary(trainers: list["MidiTrainer"]) -> str:
        """
        Retorna um sumário textual do corpus formado por múltiplos trainers.
        Exibe estatísticas por arquivo e totais consolidados.
        """
        loaded = [t for t in trainers if t._loaded]
        if not loaded:
            return "Nenhum MIDI carregado."

        lines = [
            f"Corpus: {len(loaded)} arquivo(s)",
            "─" * 42,
        ]

        total_notes = 0
        all_pitches:   list = []
        all_durations: list = []
        all_dynamics:  list = []

        for t in loaded:
            n = len(t.pitches)
            total_notes += n
            all_pitches.extend(t.pitches)
            all_durations.extend(t.durations)
            all_dynamics.extend(t.dynamics)

            lines.append(f"▸ {t.midi_path.name}")
            lines.append(f"  Notas:    {n}")
            if t.stats:
                s = t.stats
                lines.append(f"  Pitches:  {s['unique_pitches']} únicos")
                lines.append(
                    f"  Âmbito:   {s['pitch_range'][0]} – {s['pitch_range'][1]}"
                )
                lines.append(
                    f"  Vel. média: {s['avg_velocity']:.1f}"
                )
            lines.append("")

        if len(loaded) > 1:
            from collections import Counter
            lines += [
                "─" * 42,
                f"CORPUS TOTAL: {total_notes} notas",
                f"  Pitches únicos: {len(set(all_pitches))}",
                "",
                "  Pitches mais frequentes:",
            ]
            for pitch, count in Counter(all_pitches).most_common(8):
                bar = "█" * min(16, count * 16 // max(1, total_notes))
                lines.append(f"    {pitch:8} {count:5}  {bar}")
            lines += ["", "  Durações mais frequentes:"]
            for dur, count in Counter(str(d) for d in all_durations).most_common(6):
                lines.append(f"    {dur:8} {count:5}")

        return "\n".join(lines)

    # ── Tracks disponíveis ────────────────────────────────────────

    @staticmethod
    def list_tracks(midi_path: str) -> list[dict]:
        """
        Lista as tracks disponíveis num arquivo MIDI com contagem de notas.
        Útil para escolher qual track treinar na interface.
        """
        if not MIDO_AVAILABLE:
            raise ImportError("pip install mido")

        mid = mido.MidiFile(midi_path)
        result = []
        tpq = mid.ticks_per_beat

        for i, track in enumerate(mid.tracks):
            note_count = sum(
                1 for msg in track
                if msg.type == "note_on" and msg.velocity > 0
            )
            name = getattr(track, "name", "") or f"Track {i}"
            result.append({
                "index":      i,
                "name":       name.strip(),
                "note_count": note_count,
            })

        return result


# ─────────────────────────────────────────────────────────────────────────────
#  Teste standalone
# ─────────────────────────────────────────────────────────────────────────────

if __name__ == "__main__":
    import sys

    print("=" * 58)
    print("  MidiTrainer — Teste")
    print("=" * 58)

    if not MIDO_AVAILABLE:
        print("❌ mido não instalado.")
        print("   Execute: pip install mido")
        sys.exit(1)

    # Verificar se foi passado um MIDI como argumento
    if len(sys.argv) < 2:
        print("\nUso: python midi_trainer.py arquivo.mid [track] [instrumento]")
        print("\nExemplo sem MIDI: demonstrando apenas conversores")
        print()

        # Demo dos conversores
        for midi_n in [36, 48, 60, 69, 72, 81]:
            print(f"  MIDI {midi_n:3} → {midi_to_lily(midi_n)}")

        print()
        for vel in [10, 30, 50, 65, 80, 96, 112]:
            print(f"  vel {vel:3} → {velocity_to_dynamic(vel).name}")

        print()
        for q in [0.25, 0.5, 0.75, 1.0, 1.5, 2.0, 0.333]:
            snapped = snap_duration(q)
            print(f"  {q:.3f} quarters → {snapped}")

        sys.exit(0)

    # Carregar MIDI real
    midi_path = sys.argv[1]
    track_idx = int(sys.argv[2]) if len(sys.argv) > 2 else None
    instrument = sys.argv[3] if len(sys.argv) > 3 else "Violin"

    print(f"\nArquivo: {midi_path}")

    # Listar tracks
    tracks = MidiTrainer.list_tracks(midi_path)
    print(f"\nTracks disponíveis:")
    for t in tracks:
        print(f"  [{t['index']}] {t['name']:20} {t['note_count']:4} notas")

    # Carregar e treinar
    trainer = MidiTrainer(midi_path)
    trainer.load(track_filter=track_idx)
    print()
    print(trainer.summary())

    # Exportar CSV
    csv_path = trainer.export_sequences_csv("output")
    print(f"\n✅ Sequências exportadas: {csv_path}")

    # Treinar engine e gerar
    engine = trainer.train_engine(order=2, instrument_name=instrument)
    events = engine.generate(32, instrument)
    print(f"\n✅ Engine treinado — {len(events)} eventos gerados")
    print(f"   Pitches únicos usados: {len(set(e.pitch_name for e in events if not e.is_rest))}")

    # Exportar matrizes
    engine.export_matrices("output/matrices_midi")
    print(f"✅ Matrizes exportadas em output/matrices_midi/")
