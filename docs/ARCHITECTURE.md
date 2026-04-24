# Arquitetura Técnica / Technical Architecture

## Módulos e Dependências / Modules and Dependencies

```
gui.py
  └── integration.py
        ├── markov_engine.py
        │     ├── note_event.py
        │     └── percussion.py
        ├── abjad_engine.py
        │     └── percussion.py
        └── midi_trainer.py
              └── markov_engine.py
```

## Decisões Técnicas Consolidadas

### LilyPond: Geração Manual Obrigatória
- `music21.lily.translate` exige LilyPond local → quebra em deploy web
- Geração manual: 66× mais rápida, 100% confiável, sem dependências externas
- **Regra:** NUNCA usar `music21.lily.translate`

### Aritmética de Frações
- Toda quantização de compassos usa `Fraction` (módulo `fractions`)
- Comparações float para acumulação de beats geram erros compostos
- `Fraction(1,4)` é exato; `0.25` não é

### Distribuição Determinística das Matrizes
- `MarkovMatrix.weighted()` usa `itertools.product(states, repeat=order)` para preencher **todos** os contextos N-gramas
- Garante precisão: `rest_probability=0.30` produz ~30% de pausas
- Sem `itertools.product`: 85% das chamadas caem no fallback uniforme para order=2

### Threading na GUI
- Geração em thread separada via `threading.Thread`
- Tkinter não é thread-safe: toda atualização de widget usa `self.after(0, callback)`
- Nunca chamar widgets diretamente de threads de background

### Timeout Adaptativo LilyPond
```python
timeout = base_por_kb × mult_proporcional × mult_quialteras × mult_hairpins
# Máximo absoluto: 1800s (30 min)
```

### n_notes = notas sonoras
- O loop `while notes_generated < n_notes` conta apenas `not ev.is_rest`
- Pausas são geradas pela cadeia de Markov mas não consomem a cota
- `safety_limit = max(n_notes * 8, int(n_notes / (1 - rest_probability) * 5))`

### Compasso Sincronizado
- A sequência de mudanças de compasso é gerada **uma única vez** de forma centralizada
- Compartilhada entre todos os instrumentos via `time_sig_sequence`
- Compassos independentes por instrumento = partitura impossível de executar

### Percussão Indefinida: Staff Normal com NoteHead Overrides
- Alternativa ao `\drummode` nativo do LilyPond
- Vantagem: integração direta com o pipeline existente de NoteEvents
- Cada DrumVoice define posição de pauta (`_STAFF_POS_TO_LILY`) e override de cabeça (`NOTEHEAD_OVERRIDE`)

## Compatibilidade de Plataformas

| Ponto | macOS | Windows | Linux |
|-------|-------|---------|-------|
| Abrir arquivo | `subprocess.Popen(["open", path])` | `os.startfile(path)` | `subprocess.Popen(["xdg-open", path])` |
| Abrir pasta | `subprocess.Popen(["open", folder])` | `os.startfile(folder)` | `subprocess.Popen(["xdg-open", folder])` |
| Detecção | `platform.system() == "Darwin"` | `platform.system() == "Windows"` | `else` |
| LilyPond | `shutil.which("lilypond")` | `shutil.which("lilypond")` (requer PATH) | `shutil.which("lilypond")` |
| Tkinter | stdlib | stdlib | stdlib |
| matplotlib Agg | ✅ | ✅ | ✅ |
| Encoding | `encoding="utf-8"` em todos os `open()` | `encoding="utf-8"` em todos os `open()` | `encoding="utf-8"` em todos os `open()` |

## Estrutura do CompositionConfig

```python
@dataclass
class CompositionConfig:
    # Instrumentos
    instruments: list[str]
    n_notes: int = 64
    markov_order: int = 1

    # Stocástica
    rest_probability: float = 0.12
    tuplet_probability: float = 0.0
    tuplet_complexity: int = 1
    glissando_probability: float = 0.0

    # Dinâmicas
    dynamic_weights: list[float] = None
    use_hairpins: bool = True

    # Microtonalismo
    allow_microtones: bool = False
    microtone_probability: float = 0.25

    # Tempo e compasso
    tempo_bpm: int = 60
    time_signature: str = "4/4"
    random_time_changes: bool = False
    time_change_probability: float = 0.15

    # Notação
    notation_type: NotationType = NotationType.NORMAL
    proportional_notation: bool = False
    landscape: bool = False

    # Metadados
    title: str = "Composição Algorítmica"
    composer: str = ""
    output_dir: str = "output"
    open_pdf: bool = True
```

## Estrutura do CompositionResult

```python
@dataclass
class CompositionResult:
    success: bool
    pdf_path: Optional[str] = None
    ly_path: Optional[str] = None
    xml_path: Optional[str] = None
    xml_error: Optional[str] = None
    dashboard_path: Optional[str] = None
    analysis_files: dict = field(default_factory=dict)
    error_message: Optional[str] = None
    n_events_total: int = 0
    duration_seconds: float = 0.0
    instruments_used: list = field(default_factory=list)
    stats: dict = field(default_factory=dict)
```
