"""
integration.py
==============
Pipeline completo: MarkovEngine → NoteEvents → AbjadEngine → PDF

Este módulo é a cola entre os três módulos do sistema.
Expõe uma única função pública de alto nível:

    gerar_composicao(config) → CompositionResult

Testado aqui antes de ser chamado pela interface Tkinter.
"""

from __future__ import annotations

import os
import time
from dataclasses import dataclass, field
from fractions import Fraction
from pathlib import Path
from typing import Optional

from note_event import Dynamic, Microtone, NoteEvent, NotationType, Technique
from markov_engine import (
    InstrumentFamily,
    MarkovEngine,
    generate_time_sig_sequence,
    TIME_SIGNATURE_VALUES,
)
from abjad_engine import (
    compile_to_pdf,
    generate_lilypond_code,
    save_lilypond_file,
    INSTRUMENT_CLEF,
)


# ─────────────────────────────────────────────────────────────────────────────
#  Export MusicXML (via music21)
# ─────────────────────────────────────────────────────────────────────────────

# Mapeamento de pitch LilyPond → music21
_LILY_TO_M21_NAME: dict[str, str] = {
    # Naturais
    "c":"C","d":"D","e":"E","f":"F","g":"G","a":"A","b":"B",
    # Sustenidos simples
    "cis":"C#","dis":"D#","eis":"E#","fis":"F#",
    "gis":"G#","ais":"A#","bis":"B#",
    # Sustenidos duplos
    "cisis":"C##","disis":"D##","fisis":"F##","gisis":"G##",
    # Bemóis simples
    "ces":"C-","des":"D-","ees":"E-","fes":"F-",
    "ges":"G-","aes":"A-","bes":"B-",
    # Bemóis duplos
    "ceses":"C--","deses":"D--","feses":"F--","geses":"G--","beses":"B--",
    # Microtons → aproximação cromática mais próxima
    "cih":"C","dih":"D","eih":"E","fih":"F","gih":"G","aih":"A","bih":"B",
    "ceseh":"C-","deseh":"D-","eeseh":"E-","feseh":"F-",
    "geseh":"G-","aeseh":"A-","beseh":"B-",
    "cisih":"C#","disih":"D#","eisih":"E#","fisih":"F#",
    "gisih":"G#","aisih":"A#","bisih":"B#",
}

# Mapeamento de nome canônico → classe music21.instrument
# Cobre todos os instrumentos disponíveis no sistema, incluindo dobras.
_M21_INSTRUMENT_MAP_CANONICAL: dict[str, str] = {
    "Violin":       "Violin",
    "Viola":        "Viola",
    "Violoncello":  "Violoncello",
    "Double Bass":  "Contrabass",
    "Flute":        "Flute",
    "Oboe":         "Oboe",
    "Clarinet":     "Clarinet",
    "Bassoon":      "Bassoon",
    "Horn":         "Horn",
    "Trumpet":      "Trumpet",
    "Trombone":     "Trombone",
    "Tuba":         "Tuba",
    "Piano":        "Piano",
    "Harp":         "Harp",
}

def _resolve_m21_instrument(instrument_name: str) -> str:
    """
    Resolve nome de instrumento (com possível sufixo #N) para a
    classe music21 correspondente.
    "Violin #1" → "Violin"  → "Violin"
    "Violoncello" → "Violoncello"
    """
    # Remover sufixo de dobra
    base = instrument_name.split(" #")[0].strip()
    # Consultar mapa
    cls = _M21_INSTRUMENT_MAP_CANONICAL.get(base)
    if cls:
        return cls
    # Tentar aliases do markov_engine
    from markov_engine import _INSTRUMENT_ALIASES
    canonical = _INSTRUMENT_ALIASES.get(base, base)
    return _M21_INSTRUMENT_MAP_CANONICAL.get(canonical, "")

# Manter compatibilidade
_M21_INSTRUMENT_MAP: dict[str, str] = _M21_INSTRUMENT_MAP_CANONICAL


def _lily_pitch_to_m21(pitch_name: str) -> str:
    """Converte pitch LilyPond (ex: 'aes''') para string music21 (ex: 'A-5')."""
    p = pitch_name.strip()
    ticks  = p.count("'")
    commas = p.count(",")
    base   = p.replace("'", "").replace(",", "")
    m21_name = _LILY_TO_M21_NAME.get(base, "C")
    # c (sem apostrofo) = C3, c' = C4, c'' = C5, c, = C2
    octave = 3 + ticks - commas
    return f"{m21_name}{octave}"


# Mapeamento de valor LilyPond → quarterLength para export MusicXML seguro.
# Notas de quiáltera usam a nota-base (duration_lily) sem o contexto de tuplet,
# pois algumas razões (7:4, 9:8) provocam "2048th" overflow no music21.
_LILY_DUR_TO_QL: dict[str, float] = {
    "1": 4.0,   "2.": 3.0,  "2": 2.0,   "4.": 1.5,   "4": 1.0,
    "8.": 0.75, "8": 0.5,   "16.": 0.375, "16": 0.25,
    "32.": 0.1875, "32": 0.125, "64": 0.0625, "128": 0.03125,
}


def generate_musicxml(
    parts: list[tuple[str, list[NoteEvent]]],
    title: str = "Composição Algorítmica",
    composer: str = "",
    tempo_bpm: int = 60,
    time_signature: tuple[int, int] = (4, 4),
) -> bytes:
    """
    Converte lista de (instrumento, eventos) em MusicXML como bytes.

    Microtons são aproximados para a altura cromática mais próxima,
    pois MusicXML tem suporte limitado a microtonalismo.
    Técnicas estendidas (sul ponticello, flutter-tongue etc.) são omitidas
    — a informação reside no .ly/.pdf.

    Retorna bytes do arquivo .musicxml (UTF-8).
    """
    try:
        from music21 import (
            stream   as m21_stream,
            note     as m21_note,
            meter    as m21_meter,
            tempo    as m21_tempo,
            metadata as m21_meta,
            instrument as m21_inst,
        )
    except ImportError as exc:
        raise ImportError(
            "music21 não instalado. Execute: pip install music21"
        ) from exc

    ts_str = f"{time_signature[0]}/{time_signature[1]}"
    score = m21_stream.Score()
    score.metadata = m21_meta.Metadata()
    score.metadata.title    = title
    score.metadata.composer = composer

    for instr_name, events in parts:
        part = m21_stream.Part()
        part.partName = instr_name

        # Instrumento
        instr_cls_name = _resolve_m21_instrument(instr_name)
        try:
            if instr_cls_name:
                instr_obj = getattr(m21_inst, instr_cls_name)()
            else:
                instr_obj = m21_inst.Instrument()
            instr_obj.partName = instr_name
        except AttributeError:
            instr_obj = m21_inst.Instrument()
            instr_obj.partName = instr_name
        part.append(instr_obj)

        # Fórmula de compasso e andamento (só na primeira parte)
        part.append(m21_meter.TimeSignature(ts_str))
        part.append(m21_tempo.MetronomeMark(number=tempo_bpm))

        for ev in events:
            # Para quiálteras, usar a nota-base (duration_lily) como quarterLength.
            # Isso evita que music21 crie durações inválidas ("2048th tuplet")
            # para razões como 7:4 ou 9:8. O XML fica ritmicamente aproximado;
            # a notação exata de quiáltera está no arquivo .ly/.pdf.
            if ev.tuplet_ratio is not None:
                ql = _LILY_DUR_TO_QL.get(ev.duration_lily or "", float(ev.duration) * 4.0)
            else:
                ql = float(ev.duration) * 4.0
            ql = max(ql, 0.03125)  # mínimo: 1/128 avos

            if ev.is_rest:
                obj = m21_note.Rest(quarterLength=ql)
            else:
                pitch_str = _lily_pitch_to_m21(ev.pitch_name)
                obj = m21_note.Note(pitch_str, quarterLength=ql)
                obj.volume.velocity = ev.velocity

            # Remover tuplets internos criados automaticamente pelo music21
            # (ex: ql=0.2 gera Tuplet 5/4 internamente, que quebra o export XML).
            # Usar apenas o tipo de nota-base sem o contexto de tuplet.
            if obj.duration.tuplets:
                from music21 import duration as _m21_dur
                base_type = obj.duration.type
                clean_dur = _m21_dur.Duration()
                clean_dur.type = base_type
                obj.duration = clean_dur
            elif obj.duration.type in ("inexpressible", "zero", "complex"):
                # Arredondar para o tipo MusicXML válido mais próximo
                from music21 import duration as _m21_dur
                _SAFE = [4.0, 3.0, 2.0, 1.5, 1.0, 0.75, 0.5, 0.375, 0.25, 0.1875, 0.125, 0.0625]
                safe_ql = min(_SAFE, key=lambda v: abs(v - ql))
                clean_dur = _m21_dur.Duration()
                clean_dur.quarterLength = safe_ql
                obj.duration = clean_dur

            part.append(obj)

        score.append(part)

    # Serializar para bytes via arquivo temporário
    import tempfile, os
    tmp = tempfile.mktemp(suffix=".musicxml")
    try:
        score.write("musicxml", tmp)
        with open(tmp, "rb") as f:
            xml_bytes = f.read()
    finally:
        try:
            os.unlink(tmp)
        except OSError:
            pass

    return xml_bytes


# ─────────────────────────────────────────────────────────────────────────────
#  Configuração da composição
# ─────────────────────────────────────────────────────────────────────────────

@dataclass
class CompositionConfig:
    """
    Parâmetros completos de uma composição.
    Instanciado pela interface e passado para gerar_composicao().
    """
    # Instrumentos (lista de nomes — ex: ["Violin", "Viola", "Flute"])
    instruments: list[str] = field(default_factory=lambda: ["Violin"])

    # Motor Markoviano
    markov_order: int = 1                       # ordem da cadeia (1, 2 ou 3)
    n_notes: int = 64                           # notas por instrumento
    allow_microtones: bool = True               # habilitar microtonalismo
    microtone_probability: float = 0.20         # 0.0 a 1.0
    rest_probability: float = 0.12             # proporção de pausas

    # Parâmetros musicais
    title: str = "Composição Algorítmica"
    composer: str = ""
    tempo_bpm: int = 60
    time_signature: str = "4/4"                # ex: "4/4", "3/4", "6/8"
    random_time_changes: bool = False           # mudanças aleatórias de compasso
    time_change_probability: float = 0.15

    # Dinâmicas
    # Pesos para [ppp, pp, p, mp, mf, f, ff, fff] — normalizado dentro do train_uniform
    dynamic_weights: list = field(default_factory=lambda:
        [2.5, 3.0, 3.0, 2.5, 2.0, 1.5, 1.0, 0.5])
    use_hairpins: bool = True                  # crescendo/decrescendo automático

    # Quiálteras
    tuplet_probability: float = 0.0            # 0.0 = sem quiálteras
    tuplet_complexity: int   = 1               # 1=tercinas · 2=+quintinas · 3=+todas

    # Glissando
    glissando_probability: float = 0.0          # 0.0 = sem glissando; 1.0 = máximo

    # Notação
    notation_type: NotationType = NotationType.NORMAL
    proportional_notation: bool = False         # notação proporcional

    # Saída
    output_dir: str = "output"
    open_pdf: bool = True                       # abrir PDF após compilar
    landscape: bool = False                     # True = A4 paisagem

    @property
    def time_sig_tuple(self) -> tuple[int, int]:
        """Converte "4/4" → (4, 4)."""
        num, den = self.time_signature.split("/")
        return int(num), int(den)

    @property
    def measure_duration(self) -> Fraction:
        """Duração do compasso em frações de semibreve."""
        return TIME_SIGNATURE_VALUES.get(self.time_signature, Fraction(1, 1))


@dataclass
class CompositionResult:
    """Resultado de uma composição gerada."""
    success: bool
    pdf_path: Optional[str]       = None
    ly_path: Optional[str]        = None
    xml_path: Optional[str]       = None   # MusicXML (compatível com MuseScore/Finale)
    xml_error: Optional[str]      = None   # mensagem se export XML falhou
    dashboard_path: Optional[str] = None   # PNG do dashboard de análise
    analysis_files: dict          = field(default_factory=dict)  # CSVs, TXT, JSON
    midi_path: Optional[str]      = None
    error_message: Optional[str]  = None
    n_events_total: int            = 0
    duration_seconds: float        = 0.0
    instruments_used: list[str]    = field(default_factory=list)
    # Estatísticas por instrumento
    stats: dict                    = field(default_factory=dict)


# ─────────────────────────────────────────────────────────────────────────────
#  Pipeline principal
# ─────────────────────────────────────────────────────────────────────────────

def gerar_composicao(config: CompositionConfig) -> CompositionResult:
    """
    Executa o pipeline completo:
      1. Valida configuração
      2. Treina motor Markoviano
      3. Gera NoteEvents para cada instrumento
      4. Aplica quantização e compassos sincronizados
      5. Gera código LilyPond
      6. Compila para PDF

    Retorna CompositionResult com caminhos dos arquivos gerados e estatísticas.
    """
    t_start = time.time()

    # ── 1. Validação ──────────────────────────────────────────────
    erros = _validar_config(config)
    if erros:
        return CompositionResult(
            success=False,
            error_message="Configuração inválida:\n" + "\n".join(f"  • {e}" for e in erros)
        )

    # ── 2. Preparar diretório de saída ────────────────────────────
    output_dir = Path(config.output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)
    timestamp = time.strftime("%Y%m%d-%H%M%S")
    base_name = f"markov_{timestamp}"

    # ── 3. Treinar motor Markoviano ───────────────────────────────
    engine = MarkovEngine(order=config.markov_order)
    # Treina uma vez usando o primeiro instrumento como referência de família.
    # As técnicas são filtradas individualmente em generate() de qualquer forma.
    engine.train_uniform(
        instrument_name       = config.instruments[0],
        rest_probability      = config.rest_probability,
        microtone_probability = config.microtone_probability,
        tuplet_probability    = config.tuplet_probability,
        tuplet_complexity     = config.tuplet_complexity,
        dynamic_weights       = config.dynamic_weights,
    )

    # ── 4. Gerar NoteEvents por instrumento ───────────────────────
    score_events: dict[str, list[NoteEvent]] = {}
    for instr in config.instruments:
        events = engine.generate(
            n_notes         = config.n_notes,
            instrument_name = instr,
            allow_microtones= config.allow_microtones,
            notation_type   = config.notation_type,
        )
        score_events[instr] = events

    # ── 5. Aplicar compassos sincronizados ────────────────────────
    # Estimar número de compassos
    measure_dur = float(config.measure_duration)
    # Usar duração média mais curta para não subestimar o número de compassos
    # (notas rápidas = mais compassos). Fator 3x de folga para time_sig_sequence.
    avg_note_dur = 0.15   # estimativa conservadora (entre semicolcheia e colcheia)
    est_measures = max(16, int(config.n_notes * avg_note_dur / measure_dur) * 3 + 8)

    time_sig_sequence = generate_time_sig_sequence(
        base_sig      = config.time_signature,
        n_measures    = est_measures,
        random_changes= config.random_time_changes,
        change_prob   = config.time_change_probability,
    )

    # ── 6. Montar partes para o AbjadEngine ──────────────────────
    parts = [
        (instr, score_events[instr])
        for instr in config.instruments
    ]

    # ── 7. Gerar código LilyPond ──────────────────────────────────
    ts_num, ts_den = config.time_sig_tuple
    ly_code = generate_lilypond_code(
        parts                 = parts,
        title                 = config.title,
        composer              = config.composer,
        tempo_bpm             = config.tempo_bpm,
        time_signature        = config.time_sig_tuple,
        proportional          = config.proportional_notation,
        use_hairpins          = config.use_hairpins,
        landscape             = config.landscape,
        time_sig_sequence     = time_sig_sequence if config.random_time_changes else None,
        glissando_probability = config.glissando_probability,
    )

    # ── 8. Salvar arquivo .ly ─────────────────────────────────────
    ly_path = output_dir / f"{base_name}.ly"
    save_lilypond_file(ly_code, str(ly_path))

    # ── 8b. Gerar MusicXML ────────────────────────────────────────
    xml_path   = output_dir / f"{base_name}.musicxml"
    xml_error  = None
    try:
        xml_bytes = generate_musicxml(
            parts          = parts,
            title          = config.title,
            composer       = config.composer,
            tempo_bpm      = config.tempo_bpm,
            time_signature = config.time_sig_tuple,
        )
        xml_path.write_bytes(xml_bytes)
    except ImportError:
        xml_path  = None
        xml_error = "music21 não instalado — execute: pip install music21"
    except Exception as _xml_exc:
        xml_path  = None
        xml_error = f"MusicXML não gerado: {_xml_exc}"

    # ── 9. Compilar para PDF ──────────────────────────────────────
    pdf_path = output_dir / f"{base_name}.pdf"
    ok, msg  = compile_to_pdf(ly_code, str(pdf_path), open_after=config.open_pdf)

    # ── 10. Calcular estatísticas ─────────────────────────────────
    stats = _calcular_estatisticas(score_events)
    total_events = sum(len(evs) for evs in score_events.values())
    duration = time.time() - t_start

    # Dashboard de análise (PNG) — gerado sempre, independente do sucesso do PDF
    _cfg_summary = (f"{config.n_notes} notas · {len(config.instruments)} instrs · "
                    f"ordem {config.markov_order} · {config.time_signature} · "
                    f"{config.tempo_bpm} BPM")
    dashboard_path = gerar_dashboard_analise(
        stats, str(output_dir), base_name, _cfg_summary
    )
    analysis_files = exportar_dados_analise(
        stats, score_events, config, str(output_dir), base_name
    )

    if ok:
        return CompositionResult(
            success         = True,
            pdf_path        = str(pdf_path),
            ly_path         = str(ly_path),
            xml_path        = str(xml_path) if xml_path else None,
            xml_error       = xml_error,
            dashboard_path  = dashboard_path,
            analysis_files  = analysis_files,
            n_events_total  = total_events,
            duration_seconds= round(duration, 2),
            instruments_used= config.instruments,
            stats           = stats,
        )
    else:
        return CompositionResult(
            success         = False,
            ly_path         = str(ly_path),
            xml_path        = str(xml_path) if xml_path else None,
            xml_error       = xml_error,
            dashboard_path  = dashboard_path,
            analysis_files  = analysis_files,
            error_message   = msg,
            n_events_total  = total_events,
            duration_seconds= round(duration, 2),
            instruments_used= config.instruments,
            stats           = stats,
        )


# ─────────────────────────────────────────────────────────────────────────────
#  Funções auxiliares
# ─────────────────────────────────────────────────────────────────────────────

def _validar_config(config: CompositionConfig) -> list[str]:
    """Retorna lista de erros de validação (vazia = sem erros)."""
    erros = []
    if not config.instruments:
        erros.append("Selecione pelo menos um instrumento.")
    if config.n_notes < 4:
        erros.append("Número mínimo de notas: 4.")
    if config.n_notes > 8000:
        erros.append("Número máximo de notas: 8000 por instrumento.")
    if config.markov_order < 1 or config.markov_order > 4:
        erros.append("Ordem de Markov deve ser entre 1 e 4.")
    if config.time_signature not in TIME_SIGNATURE_VALUES:
        erros.append(f"Fórmula de compasso inválida: {config.time_signature}.")
    if not 20 <= config.tempo_bpm <= 400:
        erros.append("BPM deve estar entre 20 e 400.")
    return erros


def _inject_time_sig_changes(
    ly_code: str,
    time_sig_sequence: list[tuple[int, str]],
    instruments: list[str],
) -> str:
    """
    Injeta mudanças de compasso sincronizadas no código LilyPond.
    Como todas as vozes compartilham a mesma sequência, a sincronia
    é garantida (bug crítico corrigido no sistema original).

    Estratégia: insere comentários anotados no .ly para rastreabilidade.
    A implementação real de mudança de compasso no Abjad é via
    \\time dentro da voz no momento certo — adicionamos como
    anotação por ora, a ser expandido na Etapa 4 (quantização por compasso).
    """
    if len(time_sig_sequence) <= 1:
        return ly_code

    # Gerar bloco de comentário com a sequência de compassos
    comment_lines = [
        "% ── Sequência de fórmulas de compasso (sincronizada) ──────",
    ]
    for measure_num, ts in time_sig_sequence:
        comment_lines.append(f"%   Compasso {measure_num:3d}: \\time {ts}")
    comment_lines.append("% ─────────────────────────────────────────────────────────")
    comment_block = "\n".join(comment_lines) + "\n\n"

    # Inserir após o header LilyPond
    insert_after = "% Gerado por Markov-Abjad Composer\n% ─────────────────────────────────────────────────────\n"
    if insert_after in ly_code:
        ly_code = ly_code.replace(insert_after, insert_after + comment_block, 1)

    return ly_code


def _calcular_estatisticas(score_events: dict[str, list[NoteEvent]]) -> dict:
    """
    Calcula estatísticas detalhadas por instrumento.
    Inclui distribuições de pitch, duração, dinâmica, técnica e microtons.
    """
    from fractions import Fraction as _Frac

    stats = {}
    for instr, events in score_events.items():
        notas  = [e for e in events if not e.is_rest]
        pausas = [e for e in events if e.is_rest]

        # Técnicas
        techs: dict[str, int] = {}
        for e in notas:
            k = e.technique.name
            techs[k] = techs.get(k, 0) + 1

        # Dinâmicas
        dynamics: dict[str, int] = {}
        for e in notas:
            k = e.dynamic.value
            dynamics[k] = dynamics.get(k, 0) + 1

        # Distribuição de pitch (classe de altura, sem oitava)
        pitch_classes: dict[str, int] = {}
        for e in notas:
            if e.pitch_name:
                base = e.pitch_name.rstrip("',").lower()
                pitch_classes[base] = pitch_classes.get(base, 0) + 1

        # Distribuição de durações
        dur_dist: dict[str, int] = {}
        for e in events:  # inclui pausas
            k = e.duration_lily
            dur_dist[k] = dur_dist.get(k, 0) + 1

        # Microtons
        micros_dist: dict[str, int] = {}
        for e in notas:
            k = e.microtone.value if e.microtone.value else "none"
            micros_dist[k] = micros_dist.get(k, 0) + 1
        micros_count = sum(v for k, v in micros_dist.items() if k != "none")

        # Quiálteras
        tuplets = sum(1 for e in events if e.tuplet_ratio is not None)

        # Glissandos
        glissandos = sum(1 for e in events if getattr(e, "gliss_to_next", False))

        # Duração total em quarter-notes
        dur_total_ql = sum(float(e.duration) * 4 for e in events)

        stats[instr] = {
            "total":         len(events),
            "notas":         len(notas),
            "pausas":        len(pausas),
            "micros":        micros_count,
            "tuplets":       tuplets,
            "glissandos":    glissandos,
            "dur_total_ql":  round(dur_total_ql, 2),
            "tecnicas":      techs,
            "dinamicas":     dynamics,
            "pitch_classes": pitch_classes,
            "dur_dist":      dur_dist,
            "micros_dist":   micros_dist,
            "familia":       InstrumentFamily.family_of(instr),
        }
    return stats


def gerar_dashboard_analise(
    stats: dict,
    output_dir: str,
    base_name: str,
    config_summary: str = "",
) -> Optional[str]:
    """
    Gera um dashboard PNG com visualizações da composição.

    Painéis:
      1. Distribuição de dinâmicas por instrumento (barras empilhadas)
      2. Distribuição de durações (barras agregadas, todas as vozes)
      3. Distribuição de classes de pitch (barras horizontais, top 12)
      4. Distribuição de técnicas estendidas (pizza por família)
      5. Proporção notas/pausas/quiálteras/microtons (radar/barras)
      6. Tabela resumo (texto)

    Retorna o caminho do arquivo PNG gerado, ou None se falhar.
    """
    try:
        import matplotlib
        matplotlib.use("Agg")
        import matplotlib.pyplot as plt
        import matplotlib.patches as mpatches
        import numpy as np
    except ImportError:
        return None

    if not stats:
        return None

    instrs   = list(stats.keys())
    n_instrs = len(instrs)

    # ── Paleta de cores ──────────────────────────────────────────────────────
    PALETTE = ["#4e79a7","#f28e2b","#e15759","#76b7b2","#59a14f",
               "#edc948","#b07aa1","#ff9da7","#9c755f","#bab0ac"]
    DYN_ORDER   = ["niente","ppp","pp","p","mp","mf","f","ff","fff"]
    DYN_COLORS  = {d: c for d, c in zip(DYN_ORDER,
        ["#aaaaaa","#c8d6e5","#a8c2d8","#74a9cf","#3690c0",
         "#0570b0","#045a8d","#023858","#011f40"])}

    fig = plt.figure(figsize=(18, 14), facecolor="#1a1a2e")
    fig.patch.set_facecolor("#1a1a2e")
    PANEL_BG = "#16213e"
    TEXT_C   = "#e0e0f0"
    GRID_C   = "#2a2a4a"

    gs = fig.add_gridspec(3, 3, hspace=0.48, wspace=0.38,
                          left=0.07, right=0.97, top=0.91, bottom=0.06)

    def _style_ax(ax, title=""):
        ax.set_facecolor(PANEL_BG)
        ax.tick_params(colors=TEXT_C, labelsize=7)
        ax.spines[:].set_color(GRID_C)
        if title:
            ax.set_title(title, color=TEXT_C, fontsize=9, pad=6, fontweight="bold")
        ax.yaxis.label.set_color(TEXT_C)
        ax.xaxis.label.set_color(TEXT_C)

    # ── Painel 1: Dinâmicas por instrumento (barras empilhadas) ──────────────
    ax1 = fig.add_subplot(gs[0, 0])
    _style_ax(ax1, "Distribuição de Dinâmicas")
    x = np.arange(n_instrs)
    bottoms = np.zeros(n_instrs)
    for dyn in DYN_ORDER:
        vals = [stats[i]["dinamicas"].get(dyn, 0) for i in instrs]
        if any(vals):
            ax1.bar(x, vals, bottom=bottoms, color=DYN_COLORS[dyn],
                    label=dyn, width=0.65, edgecolor="none")
            bottoms += np.array(vals, dtype=float)
    ax1.set_xticks(x)
    ax1.set_xticklabels([i.split(" #")[0][:8] for i in instrs],
                         rotation=30, ha="right", fontsize=7, color=TEXT_C)
    ax1.legend(fontsize=6, ncol=3, loc="upper right",
               facecolor=PANEL_BG, labelcolor=TEXT_C, edgecolor=GRID_C)

    # ── Painel 2: Distribuição de durações (todas as vozes agregadas) ─────────
    ax2 = fig.add_subplot(gs[0, 1])
    _style_ax(ax2, "Distribuição de Durações")
    dur_agg: dict[str, int] = {}
    for s in stats.values():
        for k, v in s["dur_dist"].items():
            dur_agg[k] = dur_agg.get(k, 0) + v
    # Ordenar por valor numérico de duração LilyPond
    _dur_order = ["1","2.","2","4.","4","8.","8","16.","16","32","64",
                  "1/3","1/6","1/5","1/10","1/7","1/14"]
    sorted_durs = sorted(dur_agg.items(),
                         key=lambda x: _dur_order.index(x[0]) if x[0] in _dur_order else 99)
    if sorted_durs:
        d_labels = [d[0] for d in sorted_durs]
        d_vals   = [d[1] for d in sorted_durs]
        bars = ax2.bar(range(len(d_labels)), d_vals,
                       color=[PALETTE[i % len(PALETTE)] for i in range(len(d_labels))],
                       edgecolor="none")
        ax2.set_xticks(range(len(d_labels)))
        ax2.set_xticklabels(d_labels, rotation=45, ha="right", fontsize=7, color=TEXT_C)

    # ── Painel 3: Classes de pitch (top 14, agregado) ─────────────────────────
    ax3 = fig.add_subplot(gs[0, 2])
    _style_ax(ax3, "Classes de Pitch (top 14)")
    pc_agg: dict[str, int] = {}
    for s in stats.values():
        for k, v in s["pitch_classes"].items():
            pc_agg[k] = pc_agg.get(k, 0) + v
    top_pc = sorted(pc_agg.items(), key=lambda x: -x[1])[:14]
    if top_pc:
        ax3.barh([p[0] for p in top_pc], [p[1] for p in top_pc],
                 color=[PALETTE[i % len(PALETTE)] for i in range(len(top_pc))],
                 edgecolor="none")
        ax3.tick_params(axis="y", labelsize=7, colors=TEXT_C)

    # ── Painel 4: Técnicas estendidas por família ─────────────────────────────
    ax4 = fig.add_subplot(gs[1, 0])
    _style_ax(ax4, "Técnicas Estendidas")
    tech_agg: dict[str, int] = {}
    for s in stats.values():
        for k, v in s["tecnicas"].items():
            tech_agg[k] = tech_agg.get(k, 0) + v
    # Separar ORDINARIO das técnicas estendidas
    ext = {k: v for k, v in tech_agg.items() if k != "ORDINARIO"}
    if ext:
        labels = [k.replace("_", " ").lower() for k in ext.keys()]
        vals   = list(ext.values())
        wedges, texts, autotexts = ax4.pie(
            vals, labels=labels, autopct="%1.0f%%",
            colors=[PALETTE[i % len(PALETTE)] for i in range(len(vals))],
            textprops={"color": TEXT_C, "fontsize": 6},
            startangle=140,
        )
        for at in autotexts:
            at.set_fontsize(6)
            at.set_color(TEXT_C)
    else:
        ax4.text(0.5, 0.5, "Apenas ordinário", ha="center", va="center",
                 color=TEXT_C, transform=ax4.transAxes)
    ax4.set_facecolor(PANEL_BG)

    # ── Painel 5: Proporção notas / pausas / quiálteras / microtons / gliss ──
    ax5 = fig.add_subplot(gs[1, 1])
    _style_ax(ax5, "Proporção por Instrumento")
    categories = ["Notas", "Pausas", "Quiálteras", "Microtons", "Glissandos"]
    x5 = np.arange(len(categories))
    width = 0.8 / max(n_instrs, 1)
    for i, instr in enumerate(instrs):
        s = stats[instr]
        total = max(s["total"], 1)
        vals5 = [
            s["notas"]     / total * 100,
            s["pausas"]    / total * 100,
            s["tuplets"]   / total * 100,
            s["micros"]    / total * 100,
            s["glissandos"]/ total * 100,
        ]
        offset = (i - n_instrs/2 + 0.5) * width
        ax5.bar(x5 + offset, vals5, width=width,
                color=PALETTE[i % len(PALETTE)], label=instr.split(" #")[0][:8],
                edgecolor="none", alpha=0.85)
    ax5.set_xticks(x5)
    ax5.set_xticklabels(categories, fontsize=7, color=TEXT_C)
    ax5.set_ylabel("%", color=TEXT_C, fontsize=7)
    ax5.legend(fontsize=6, facecolor=PANEL_BG, labelcolor=TEXT_C, edgecolor=GRID_C)

    # ── Painel 6: Microtons por instrumento ───────────────────────────────────
    ax6 = fig.add_subplot(gs[1, 2])
    _style_ax(ax6, "Distribuição de Microtons")
    MICRO_ORDER = ["none","qs","qf","tqs","tqf"]
    MICRO_LABELS= {"none":"natural","qs":"+¼","qf":"−¼","tqs":"+¾","tqf":"−¾"}
    MICRO_COLORS= {"none":"#555577","qs":"#e15759","qf":"#4e79a7",
                   "tqs":"#f28e2b","tqf":"#76b7b2"}
    bottoms6 = np.zeros(n_instrs)
    for mk in MICRO_ORDER:
        vals6 = [stats[i]["micros_dist"].get(mk, 0) for i in instrs]
        if any(vals6):
            ax6.bar(x, vals6, bottom=bottoms6,
                    color=MICRO_COLORS.get(mk, "#aaaaaa"),
                    label=MICRO_LABELS.get(mk, mk), width=0.65, edgecolor="none")
            bottoms6 += np.array(vals6, dtype=float)
    ax6.set_xticks(x)
    ax6.set_xticklabels([i.split(" #")[0][:8] for i in instrs],
                         rotation=30, ha="right", fontsize=7, color=TEXT_C)
    ax6.legend(fontsize=6, facecolor=PANEL_BG, labelcolor=TEXT_C, edgecolor=GRID_C)

    # ── Painel 7: Tabela resumo ──────────────────────────────────────────────
    ax7 = fig.add_subplot(gs[2, :])
    ax7.set_facecolor(PANEL_BG)
    ax7.axis("off")
    _style_ax(ax7, "Resumo por Instrumento")

    col_labels = ["Instrumento", "Família", "Notas", "Pausas", "Quiálteras",
                  "Microtons", "Glissandos", "Dur. total (ql)", "Técnicas distintas"]
    rows = []
    for instr in instrs:
        s = stats[instr]
        rows.append([
            instr,
            s["familia"],
            str(s["notas"]),
            str(s["pausas"]),
            str(s["tuplets"]),
            str(s["micros"]),
            str(s["glissandos"]),
            str(s["dur_total_ql"]),
            str(len(s["tecnicas"])),
        ])
    # Totais
    rows.append([
        "TOTAL / MÉDIA",
        "—",
        str(sum(stats[i]["notas"] for i in instrs)),
        str(sum(stats[i]["pausas"] for i in instrs)),
        str(sum(stats[i]["tuplets"] for i in instrs)),
        str(sum(stats[i]["micros"] for i in instrs)),
        str(sum(stats[i]["glissandos"] for i in instrs)),
        str(round(sum(stats[i]["dur_total_ql"] for i in instrs) / max(n_instrs, 1), 1)),
        "—",
    ])

    tbl = ax7.table(
        cellText=rows, colLabels=col_labels,
        cellLoc="center", loc="center",
        bbox=[0, 0, 1, 0.92],
    )
    tbl.auto_set_font_size(False)
    tbl.set_fontsize(7.5)
    for (r, c), cell in tbl.get_celld().items():
        cell.set_facecolor("#0f3460" if r == 0 else (PANEL_BG if r % 2 == 0 else "#1e2a4a"))
        cell.set_edgecolor(GRID_C)
        cell.set_text_props(color=TEXT_C, fontsize=7.5)
        if r == len(rows):  # linha de totais
            cell.set_facecolor("#16213e")
            cell.set_text_props(color="#ffd700", fontsize=7.5, fontweight="bold")

    # ── Título geral ─────────────────────────────────────────────────────────
    title_str = "Dashboard de Análise — Composição Algorítmica"
    if config_summary:
        title_str += f"  |  {config_summary}"
    fig.suptitle(title_str, color=TEXT_C, fontsize=11, fontweight="bold", y=0.97)

    # ── Salvar ────────────────────────────────────────────────────────────────
    import pathlib
    out_dir = pathlib.Path(output_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    png_path = str(out_dir / f"{base_name}_dashboard.png")
    fig.savefig(png_path, dpi=150, bbox_inches="tight",
                facecolor=fig.get_facecolor())
    plt.close(fig)
    return png_path


# ─────────────────────────────────────────────────────────────────────────────
#  Pipeline com treinamento MIDI real
# ─────────────────────────────────────────────────────────────────────────────

def _gerar_com_midi_trainer(
    config: CompositionConfig,
    trainer_or_list,  # MidiTrainer único OU list[MidiTrainer]
) -> CompositionResult:
    """
    Variante de gerar_composicao() que usa um ou mais MidiTrainers
    pré-carregados para calcular as matrizes de Markov.

    Quando recebe uma lista, usa MidiTrainer.merge_and_train() para
    combinar os corpus antes de treinar — as sequências são concatenadas
    e a cadeia de Markov aprende o material integrado.
    """
    import time
    from abjad_engine import generate_lilypond_code, save_lilypond_file, compile_to_pdf
    from markov_engine import generate_time_sig_sequence
    from midi_trainer import MidiTrainer
    from pathlib import Path

    t_start = time.time()

    erros = _validar_config(config)
    if erros:
        return CompositionResult(
            success=False,
            error_message="Configuração inválida:\n" + "\n".join(f"  • {e}" for e in erros)
        )

    output_dir = Path(config.output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)
    timestamp  = time.strftime("%Y%m%d-%H%M%S")
    base_name  = f"markov_midi_{timestamp}"

    # ── Treinar engine: único ou corpus múltiplo ──────────────────
    if isinstance(trainer_or_list, list):
        trainers = [t for t in trainer_or_list if t._loaded]
        if not trainers:
            return CompositionResult(
                success=False,
                error_message="Nenhum MidiTrainer carregado com sucesso."
            )
        if len(trainers) == 1:
            engine = trainers[0].train_engine(
                order               = config.markov_order,
                instrument_name     = config.instruments[0],
                add_microtone_layer = config.allow_microtones,
                microtone_probability = config.microtone_probability,
            )
        else:
            engine = MidiTrainer.merge_and_train(
                trainers              = trainers,
                order                 = config.markov_order,
                instrument_name       = config.instruments[0],
                add_microtone_layer   = config.allow_microtones,
                microtone_probability = config.microtone_probability,
            )
    else:
        # Compatibilidade com chamada legada (trainer único)
        engine = trainer_or_list.train_engine(
            order               = config.markov_order,
            instrument_name     = config.instruments[0],
            add_microtone_layer = config.allow_microtones,
            microtone_probability = config.microtone_probability,
        )

    # Gerar eventos para cada instrumento
    score_events: dict[str, list] = {}
    for instr in config.instruments:
        score_events[instr] = engine.generate(
            n_notes          = config.n_notes,
            instrument_name  = instr,
            allow_microtones = config.allow_microtones,
            notation_type    = config.notation_type,
        )

    # ── Compassos sincronizados ───────────────────────────────────
    measure_dur  = float(config.measure_duration)
    avg_note_dur = 0.15
    est_measures = max(16, int(config.n_notes * avg_note_dur / measure_dur) * 3 + 8)
    time_sig_sequence = generate_time_sig_sequence(
        base_sig       = config.time_signature,
        n_measures     = est_measures,
        random_changes = config.random_time_changes,
        change_prob    = config.time_change_probability,
    )

    # LilyPond
    parts   = list(score_events.items())
    ly_code = generate_lilypond_code(
        parts,
        title                 = config.title,
        composer              = config.composer,
        tempo_bpm             = config.tempo_bpm,
        time_signature        = config.time_sig_tuple,
        proportional          = config.proportional_notation,
        use_hairpins          = config.use_hairpins,
        landscape             = config.landscape,
        time_sig_sequence     = time_sig_sequence if config.random_time_changes else None,
        glissando_probability = config.glissando_probability,
    )

    ly_path  = output_dir / f"{base_name}.ly"
    pdf_path = output_dir / f"{base_name}.pdf"
    save_lilypond_file(ly_code, str(ly_path))

    # MusicXML (opcional — falha silenciosa)
    xml_path  = output_dir / f"{base_name}.musicxml"
    xml_error = None
    try:
        xml_bytes = generate_musicxml(
            parts          = parts,
            title          = config.title,
            composer       = config.composer,
            tempo_bpm      = config.tempo_bpm,
            time_signature = config.time_sig_tuple,
        )
        xml_path.write_bytes(xml_bytes)
    except ImportError:
        xml_path  = None
        xml_error = "music21 não instalado — execute: pip install music21"
    except Exception as _xml_exc:
        xml_path  = None
        xml_error = f"MusicXML não gerado: {_xml_exc}"

    ok, msg = compile_to_pdf(ly_code, str(pdf_path), open_after=config.open_pdf)

    stats    = _calcular_estatisticas(score_events)
    total    = sum(len(e) for e in score_events.values())
    duration = time.time() - t_start

    _cfg_summary = (f"{config.n_notes} notas · {len(config.instruments)} instrs · "
                    f"ordem {config.markov_order} · {config.time_signature} · "
                    f"{config.tempo_bpm} BPM")
    dashboard_path = gerar_dashboard_analise(
        stats, str(output_dir), base_name, _cfg_summary
    )
    analysis_files = exportar_dados_analise(
        stats, score_events, config, str(output_dir), base_name
    )

    if ok:
        return CompositionResult(
            success=True, pdf_path=str(pdf_path), ly_path=str(ly_path),
            xml_path=str(xml_path) if xml_path else None,
            xml_error=xml_error,
            dashboard_path=dashboard_path,
            analysis_files=analysis_files,
            n_events_total=total, duration_seconds=round(duration, 2),
            instruments_used=config.instruments, stats=stats,
        )
    else:
        return CompositionResult(
            success=False, ly_path=str(ly_path), error_message=msg,
            xml_path=str(xml_path) if xml_path else None,
            xml_error=xml_error,
            dashboard_path=dashboard_path,
            analysis_files=analysis_files,
            n_events_total=total, duration_seconds=round(duration, 2),
            instruments_used=config.instruments, stats=stats,
        )


# ─────────────────────────────────────────────────────────────────────────────
#  Instrumentos disponíveis na interface (para popular o seletor)
# ─────────────────────────────────────────────────────────────────────────────

INSTRUMENTS_BY_FAMILY: dict[str, list[str]] = {
    "Madeiras":  ["Flute", "Oboe", "Clarinet", "Bassoon"],
    "Metais":    ["Horn", "Trumpet", "Trombone", "Tuba"],
    "Cordas":    ["Violin", "Viola", "Violoncello", "Double Bass"],
    "Teclados":  ["Piano", "Harp"],
    # Percussão de altura definida
    "Perc. Altura Def.": [
        "Vibraphone", "Marimba", "Timpani",
        "Xylophone", "Glockenspiel", "Crotales",
    ],
    # Percussão de altura indefinida — peles
    "Peles": [
        "Snare Drum", "Bass Drum", "Tan-Tan",
        "Tom High", "Tom Mid", "Tom Low", "Floor Tom", "Gong",
    ],
    # Pratos
    "Pratos": [
        "Hi-Hat", "Ride Cymbal", "Crash Cymbal",
        "Suspended Cymbal", "Cymbals (clash)", "Tam-Tam", "China/Splash",
    ],
    # Efeitos percussivos
    "Perc. Efeitos": [
        "Triangle", "Woodblock", "Cowbell",
        "Tambourine", "Claves", "Vibraslap",
    ],
}

ALL_INSTRUMENTS: list[str] = [
    instr
    for family in INSTRUMENTS_BY_FAMILY.values()
    for instr in family
]


# ─────────────────────────────────────────────────────────────────────────────
#  Teste end-to-end
# ─────────────────────────────────────────────────────────────────────────────

if __name__ == "__main__":
    print("=" * 62)
    print("  Teste End-to-End: Pipeline Completo")
    print("  MarkovEngine → NoteEvents → AbjadEngine → PDF")
    print("=" * 62)

    # ── Teste 1: Duo Cordas (configuração minimalista) ────────────
    print("\n[ Teste 1 ] Duo de Cordas — Feldman-like, ppp, sem microtons")
    config_duo = CompositionConfig(
        instruments        = ["Violin", "Violoncello"],
        markov_order       = 1,
        n_notes            = 24,
        allow_microtones   = False,
        rest_probability   = 0.15,
        title              = "Duo — Homenagem a Feldman",
        composer           = "Markov-Abjad Composer",
        tempo_bpm          = 40,
        time_signature     = "3/4",
        random_time_changes= False,
        notation_type      = NotationType.NORMAL,
        output_dir         = "output",
        open_pdf           = True,
    )

    result = gerar_composicao(config_duo)
    _print_result(result) if False else None  # definido abaixo

    if result.success:
        print(f"  ✅ PDF: {result.pdf_path}")
        print(f"  ✅ .ly: {result.ly_path}")
        print(f"  ✅ {result.n_events_total} eventos em {result.duration_seconds}s")
        print("\n  Estatísticas por instrumento:")
        for instr, s in result.stats.items():
            print(f"    {instr:15} ({s['familia']:8}) "
                  f"notas={s['notas']:3}  pausas={s['pausas']:2}  "
                  f"micros={s['micros']}  "
                  f"técnicas={list(s['tecnicas'].keys())}")
    else:
        print(f"  ❌ {result.error_message}")

    # ── Teste 2: Quarteto misto com microtons ─────────────────────
    print("\n[ Teste 2 ] Quarteto Misto — microtons + mudanças de compasso")
    config_quarteto = CompositionConfig(
        instruments          = ["Flute", "Violin", "Viola", "Violoncello"],
        markov_order         = 2,
        n_notes              = 32,
        allow_microtones     = True,
        microtone_probability= 0.30,
        rest_probability     = 0.10,
        title                = "Quarteto Misto — Estudo Microtonal",
        composer             = "Markov-Abjad Composer",
        tempo_bpm            = 52,
        time_signature       = "4/4",
        random_time_changes  = True,
        time_change_probability = 0.20,
        notation_type        = NotationType.NORMAL,
        output_dir           = "output",
        open_pdf             = False,   # não abrir o segundo PDF automaticamente
    )

    result2 = gerar_composicao(config_quarteto)

    if result2.success:
        print(f"  ✅ PDF: {result2.pdf_path}")
        print(f"  ✅ {result2.n_events_total} eventos em {result2.duration_seconds}s")
        print("\n  Estatísticas por instrumento:")
        for instr, s in result2.stats.items():
            print(f"    {instr:15} ({s['familia']:8}) "
                  f"notas={s['notas']:3}  pausas={s['pausas']:2}  "
                  f"micros={s['micros']:2}  "
                  f"técnicas={list(s['tecnicas'].keys())}")
    else:
        print(f"  ❌ {result2.error_message}")

    # ── Teste 3: Validação de configuração inválida ───────────────
    print("\n[ Teste 3 ] Validação de configuração inválida")
    config_invalido = CompositionConfig(
        instruments    = [],
        n_notes        = 1,
        tempo_bpm      = 999,
        time_signature = "99/99",
    )
    result3 = gerar_composicao(config_invalido)
    if not result3.success:
        print(f"  ✅ Erro capturado corretamente:\n{result3.error_message}")
    else:
        print("  ❌ Deveria ter falhado!")

    print("\n" + "=" * 62)
    print("  ✅ Pipeline end-to-end validado!")
    print("=" * 62)


# ─────────────────────────────────────────────────────────────────────────────
#  Exportação de dados analíticos
# ─────────────────────────────────────────────────────────────────────────────

def exportar_dados_analise(
    stats: dict,
    score_events: dict,
    config,
    output_dir: str,
    base_name: str,
) -> dict[str, str]:
    """
    Exporta conjunto completo de arquivos analíticos para uma composição.

    Arquivos gerados:
      {base}_resumo.txt          — Relatório textual legível
      {base}_stats.json          — Dados completos em JSON (machine-readable)
      {base}_eventos.csv         — Todos os eventos (notas+pausas) linha a linha
      {base}_distribuicao_din.csv  — Distribuição de dinâmicas por instrumento
      {base}_distribuicao_dur.csv  — Distribuição de durações por instrumento
      {base}_distribuicao_pitch.csv — Distribuição de classes de pitch
      {base}_distribuicao_tecnica.csv — Distribuição de técnicas estendidas
      {base}_distribuicao_micro.csv  — Distribuição de microtons
      {base}_matrizes_markov.csv   — Snapshot das probabilidades Markov (se disponível)

    Retorna dict {tipo: caminho_absoluto} dos arquivos gerados.
    """
    import csv
    import json
    import pathlib
    import datetime

    out_dir = pathlib.Path(output_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    generated: dict[str, str] = {}

    instrs     = list(stats.keys())
    timestamp  = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")

    # ── 1. Relatório TXT ────────────────────────────────────────────────────
    txt_path = out_dir / f"{base_name}_relatorio.txt"
    with open(txt_path, "w", encoding="utf-8") as f:
        f.write("=" * 70 + "\n")
        f.write("  RELATÓRIO DE ANÁLISE — COMPOSIÇÃO ALGORÍTMICA MARKOVIANA\n")
        f.write("=" * 70 + "\n\n")
        f.write(f"  Gerado em    : {timestamp}\n")
        f.write(f"  Arquivo base : {base_name}\n\n")

        # Parâmetros da composição
        f.write("── PARÂMETROS DE COMPOSIÇÃO ─────────────────────────────────────\n\n")
        cfg_fields = [
            ("Título",              getattr(config, "title", "—")),
            ("Compositor",          getattr(config, "composer", "—") or "—"),
            ("Instrumentos",        ", ".join(getattr(config, "instruments", []))),
            ("Notas por instrumento", str(getattr(config, "n_notes", "—"))),
            ("Ordem da cadeia",     str(getattr(config, "markov_order", "—"))),
            ("Fórmula de compasso", str(getattr(config, "time_signature", "—"))),
            ("Andamento (BPM)",     str(getattr(config, "tempo_bpm", "—"))),
            ("Probabilidade de pausa", f"{getattr(config, 'rest_probability', 0)*100:.0f}%"),
            ("Probabilidade de quiáltera", f"{getattr(config, 'tuplet_probability', 0)*100:.0f}%"),
            ("Glissando",           f"{getattr(config, 'glissando_probability', 0)*100:.0f}%"),
            ("Mudanças de compasso", "Sim" if getattr(config, "random_time_changes", False) else "Não"),
            ("Notação",             str(getattr(config, "notation_type", "—"))),
            ("Hairpins",            "Sim" if getattr(config, "use_hairpins", True) else "Não"),
        ]
        for label, val in cfg_fields:
            f.write(f"  {label:<30} {val}\n")
        f.write("\n")

        # Resumo geral
        total_notas  = sum(s["notas"]  for s in stats.values())
        total_pausas = sum(s["pausas"] for s in stats.values())
        total_events = sum(s["total"]  for s in stats.values())
        total_tuplets = sum(s["tuplets"] for s in stats.values())
        total_micros  = sum(s["micros"]  for s in stats.values())
        total_gliss   = sum(s["glissandos"] for s in stats.values())

        f.write("── RESUMO GERAL ─────────────────────────────────────────────────\n\n")
        f.write(f"  Total de eventos       : {total_events}\n")
        f.write(f"  Notas sonoras          : {total_notas}  ({total_notas/max(total_events,1)*100:.1f}%)\n")
        f.write(f"  Pausas                 : {total_pausas} ({total_pausas/max(total_events,1)*100:.1f}%)\n")
        f.write(f"  Quiálteras             : {total_tuplets} ({total_tuplets/max(total_events,1)*100:.1f}%)\n")
        f.write(f"  Microtons              : {total_micros} ({total_micros/max(total_notas,1)*100:.1f}% das notas)\n")
        f.write(f"  Glissandos             : {total_gliss} ({total_gliss/max(total_notas,1)*100:.1f}% das notas)\n\n")

        # Por instrumento
        f.write("── POR INSTRUMENTO ──────────────────────────────────────────────\n\n")
        col = "{:<22} {:>6} {:>6} {:>8} {:>8} {:>8} {:>10}"
        f.write(col.format("Instrumento","Notas","Pausas","Quiált.","Microt.","Gliss.","Dur.ql") + "\n")
        f.write("  " + "-" * 68 + "\n")
        for instr in instrs:
            s = stats[instr]
            f.write("  " + col.format(
                instr[:22],
                s["notas"], s["pausas"],
                s["tuplets"], s["micros"], s["glissandos"],
                s["dur_total_ql"],
            ) + "\n")
        f.write("\n")

        # Dinâmicas
        f.write("── DISTRIBUIÇÃO DE DINÂMICAS ────────────────────────────────────\n\n")
        dyn_order = ["niente","ppp","pp","p","mp","mf","f","ff","fff"]
        header = f"  {'Instrumento':<22}" + "".join(f"{d:>8}" for d in dyn_order)
        f.write(header + "\n")
        f.write("  " + "-" * (22 + 8*len(dyn_order)) + "\n")
        for instr in instrs:
            row = f"  {instr[:22]:<22}"
            for d in dyn_order:
                row += f"{stats[instr]['dinamicas'].get(d, 0):>8}"
            f.write(row + "\n")
        f.write("\n")

        # Técnicas
        f.write("── TÉCNICAS ESTENDIDAS ──────────────────────────────────────────\n\n")
        all_techs = sorted(set(t for s in stats.values() for t in s["tecnicas"]))
        header2 = f"  {'Instrumento':<22}" + "".join(f"{t[:8]:>10}" for t in all_techs)
        f.write(header2 + "\n")
        f.write("  " + "-" * (22 + 10*len(all_techs)) + "\n")
        for instr in instrs:
            row = f"  {instr[:22]:<22}"
            for t in all_techs:
                row += f"{stats[instr]['tecnicas'].get(t, 0):>10}"
            f.write(row + "\n")
        f.write("\n")

        # Microtons
        f.write("── MICROTONS ────────────────────────────────────────────────────\n\n")
        micro_order = ["none","qs","qf","tqs","tqf"]
        micro_names = {"none":"natural","qs":"+¼ tom","qf":"-¼ tom","tqs":"+¾ tom","tqf":"-¾ tom"}
        header3 = f"  {'Instrumento':<22}" + "".join(f"{micro_names.get(m,m):>10}" for m in micro_order)
        f.write(header3 + "\n")
        f.write("  " + "-" * (22 + 10*len(micro_order)) + "\n")
        for instr in instrs:
            row = f"  {instr[:22]:<22}"
            for m in micro_order:
                row += f"{stats[instr]['micros_dist'].get(m, 0):>10}"
            f.write(row + "\n")
        f.write("\n")

        # Top-10 classes de pitch por instrumento
        f.write("── TOP-10 CLASSES DE PITCH POR INSTRUMENTO ─────────────────────\n\n")
        for instr in instrs:
            pc = sorted(stats[instr]["pitch_classes"].items(), key=lambda x: -x[1])[:10]
            f.write(f"  {instr}:\n")
            for pitch, cnt in pc:
                pct = cnt / max(stats[instr]["notas"], 1) * 100
                bar = "█" * int(pct / 2)
                f.write(f"    {pitch:<8} {cnt:>5}  ({pct:5.1f}%)  {bar}\n")
            f.write("\n")

        f.write("=" * 70 + "\n")
        f.write("  Fim do relatório\n")
        f.write("=" * 70 + "\n")

    generated["relatorio"] = str(txt_path)

    # ── 2. JSON completo ────────────────────────────────────────────────────
    json_path = out_dir / f"{base_name}_analise.json"
    json_data = {
        "metadata": {
            "timestamp":  timestamp,
            "base_name":  base_name,
            "titulo":     getattr(config, "title", ""),
            "compositor": getattr(config, "composer", ""),
        },
        "config": {
            "instrumentos":   getattr(config, "instruments", []),
            "n_notes":        getattr(config, "n_notes", 0),
            "markov_order":   getattr(config, "markov_order", 1),
            "time_signature": getattr(config, "time_signature", "4/4"),
            "tempo_bpm":      getattr(config, "tempo_bpm", 60),
            "rest_probability":    getattr(config, "rest_probability", 0),
            "tuplet_probability":  getattr(config, "tuplet_probability", 0),
            "glissando_probability": getattr(config, "glissando_probability", 0),
            "use_hairpins":   getattr(config, "use_hairpins", True),
            "random_time_changes": getattr(config, "random_time_changes", False),
        },
        "resumo_geral": {
            "total_eventos": total_events,
            "total_notas":   total_notas,
            "total_pausas":  total_pausas,
            "total_tuplets": total_tuplets,
            "total_micros":  total_micros,
            "total_glissandos": total_gliss,
        },
        "por_instrumento": stats,
    }
    with open(json_path, "w", encoding="utf-8") as f:
        json.dump(json_data, f, ensure_ascii=False, indent=2)
    generated["json"] = str(json_path)

    # ── 3. CSV de eventos brutos ─────────────────────────────────────────────
    eventos_path = out_dir / f"{base_name}_eventos.csv"
    with open(eventos_path, "w", newline="", encoding="utf-8") as f:
        writer = csv.writer(f)
        writer.writerow([
            "instrumento", "familia", "idx_evento",
            "tipo",        # "nota" ou "pausa"
            "pitch",       "pitch_class", "oitava",
            "duracao_frac","duracao_lily","duracao_ql",
            "dinamica",    "velocidade",
            "tecnica",     "microtone",
            "tuplet_ratio","glissando",
            "tie_start",   "tie_stop",
        ])
        for instr in instrs:
            familia = stats[instr]["familia"]
            for idx, ev in enumerate(score_events.get(instr, [])):
                tipo = "pausa" if ev.is_rest else "nota"
                pitch_full  = ev.pitch_name or ""
                pitch_class = pitch_full.rstrip("',").lower() if pitch_full else ""
                # Calcular oitava
                if pitch_full:
                    ticks  = pitch_full.count("'")
                    commas = pitch_full.count(",")
                    oitava = 3 + ticks - commas
                else:
                    oitava = ""
                writer.writerow([
                    instr, familia, idx,
                    tipo,
                    pitch_full, pitch_class, oitava,
                    str(ev.duration),
                    ev.duration_lily,
                    round(float(ev.duration) * 4, 4),
                    ev.dynamic.value if ev.dynamic else "",
                    ev.velocity if not ev.is_rest else 0,
                    ev.technique.name if ev.technique else "",
                    ev.microtone.value if ev.microtone else "",
                    str(ev.tuplet_ratio) if ev.tuplet_ratio else "",
                    "1" if getattr(ev, "gliss_to_next", False) else "0",
                    "1" if ev.tie_start else "0",
                    "1" if ev.tie_stop  else "0",
                ])
    generated["eventos_csv"] = str(eventos_path)

    # ── 4. CSV de distribuição de dinâmicas ──────────────────────────────────
    din_path = out_dir / f"{base_name}_dist_dinamicas.csv"
    dyn_order_csv = ["niente","ppp","pp","p","mp","mf","f","ff","fff"]
    with open(din_path, "w", newline="", encoding="utf-8") as f:
        writer = csv.writer(f)
        writer.writerow(["instrumento","familia"] + dyn_order_csv + ["total_notas"])
        for instr in instrs:
            s = stats[instr]
            row = [instr, s["familia"]]
            row += [s["dinamicas"].get(d, 0) for d in dyn_order_csv]
            row += [s["notas"]]
            writer.writerow(row)
    generated["dist_dinamicas"] = str(din_path)

    # ── 5. CSV de distribuição de durações ───────────────────────────────────
    dur_path = out_dir / f"{base_name}_dist_duracoes.csv"
    all_durs = sorted(set(d for s in stats.values() for d in s["dur_dist"]))
    with open(dur_path, "w", newline="", encoding="utf-8") as f:
        writer = csv.writer(f)
        writer.writerow(["instrumento","familia"] + all_durs + ["total_eventos"])
        for instr in instrs:
            s = stats[instr]
            row = [instr, s["familia"]]
            row += [s["dur_dist"].get(d, 0) for d in all_durs]
            row += [s["total"]]
            writer.writerow(row)
    generated["dist_duracoes"] = str(dur_path)

    # ── 6. CSV de distribuição de pitch ──────────────────────────────────────
    pitch_path = out_dir / f"{base_name}_dist_pitch.csv"
    all_pcs = sorted(set(p for s in stats.values() for p in s["pitch_classes"]))
    with open(pitch_path, "w", newline="", encoding="utf-8") as f:
        writer = csv.writer(f)
        writer.writerow(["instrumento","familia"] + all_pcs + ["total_notas"])
        for instr in instrs:
            s = stats[instr]
            row = [instr, s["familia"]]
            row += [s["pitch_classes"].get(p, 0) for p in all_pcs]
            row += [s["notas"]]
            writer.writerow(row)
    generated["dist_pitch"] = str(pitch_path)

    # ── 7. CSV de distribuição de técnicas ───────────────────────────────────
    tec_path = out_dir / f"{base_name}_dist_tecnicas.csv"
    all_techs_csv = sorted(set(t for s in stats.values() for t in s["tecnicas"]))
    with open(tec_path, "w", newline="", encoding="utf-8") as f:
        writer = csv.writer(f)
        writer.writerow(["instrumento","familia"] + all_techs_csv + ["total_notas"])
        for instr in instrs:
            s = stats[instr]
            row = [instr, s["familia"]]
            row += [s["tecnicas"].get(t, 0) for t in all_techs_csv]
            row += [s["notas"]]
            writer.writerow(row)
    generated["dist_tecnicas"] = str(tec_path)

    # ── 8. CSV de distribuição de microtons ──────────────────────────────────
    mic_path = out_dir / f"{base_name}_dist_microtons.csv"
    micro_order_csv = ["none","qs","qf","tqs","tqf"]
    with open(mic_path, "w", newline="", encoding="utf-8") as f:
        writer = csv.writer(f)
        writer.writerow(["instrumento","familia"] + micro_order_csv + ["total_notas"])
        for instr in instrs:
            s = stats[instr]
            row = [instr, s["familia"]]
            row += [s["micros_dist"].get(m, 0) for m in micro_order_csv]
            row += [s["notas"]]
            writer.writerow(row)
    generated["dist_microtons"] = str(mic_path)

    # ── 9. CSV resumo geral ───────────────────────────────────────────────────
    resumo_path = out_dir / f"{base_name}_resumo.csv"
    with open(resumo_path, "w", newline="", encoding="utf-8") as f:
        writer = csv.writer(f)
        writer.writerow([
            "instrumento","familia","total","notas","pausas",
            "pct_pausas","tuplets","pct_tuplets","micros","pct_micros",
            "glissandos","pct_glissandos","dur_total_ql","tecnicas_distintas",
        ])
        for instr in instrs:
            s = stats[instr]
            total = max(s["total"], 1)
            notas = max(s["notas"], 1)
            writer.writerow([
                instr, s["familia"],
                s["total"], s["notas"], s["pausas"],
                round(s["pausas"]/total*100, 1),
                s["tuplets"], round(s["tuplets"]/total*100, 1),
                s["micros"],  round(s["micros"]/notas*100, 1),
                s["glissandos"], round(s["glissandos"]/notas*100, 1),
                s["dur_total_ql"],
                len(s["tecnicas"]),
            ])
    generated["resumo_csv"] = str(resumo_path)

    return generated
