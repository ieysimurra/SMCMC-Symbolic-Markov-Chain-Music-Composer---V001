# Markov-Abjad Composer

**Sistema de Composição Algorítmica com Cadeias de Markov**  
*Algorithmic Composition System with Markov Chains*

---

<div align="center">

![Python](https://img.shields.io/badge/Python-3.11%2B-blue)
![LilyPond](https://img.shields.io/badge/LilyPond-2.24%2B-green)
![Platform](https://img.shields.io/badge/Platform-macOS%20%7C%20Windows%20%7C%20Linux-lightgrey)
![License](https://img.shields.io/badge/License-MIT-yellow)

**Prof. Ivan Eiji Simurra · NICS / UNICAMP · 2026**

</div>

---

## 🇧🇷 Português

### Visão Geral

O **Markov-Abjad Composer** é um sistema de composição algorítmica que utiliza Cadeias de Markov para gerar material musical e o LilyPond/Abjad para produzir partituras de notação contemporânea de alta qualidade. O sistema foi desenvolvido no contexto de pesquisa em música computacional no NICS (Núcleo Interdisciplinar de Comunicação Sonora) da UNICAMP.

O sistema opera com **cinco matrizes de Markov independentes** — para altura, duração, dinâmica, técnica e microtonalismo — permitindo que cada parâmetro musical evolua com sua própria lógica estocástica. As matrizes podem ser treinadas de forma uniforme (parâmetros configurados pelo usuário) ou a partir de corpus MIDI real.

**Referências estéticas:** Morton Feldman, Brian Ferneyhough, György Ligeti, Helmut Lachenmann, Salvatore Sciarrino, Iannis Xenakis.

### Características Principais

- **42 instrumentos** em 8 famílias: madeiras, metais, cordas, teclados e percussão (altura definida e indefinida)
- **Notação contemporânea completa:** quiálteras aninhadas, microtonalismo (quartos de tom), técnicas estendidas, dinâmicas niente, glissando contínuo
- **Notação proporcional gráfica** (modo Feldman/Cardew): sem barras de compasso, espaçamento temporal contínuo
- **Treinamento por corpus MIDI:** aprende padrões de arquivos MIDI reais
- **Dashboard de análise:** 7 painéis visuais + exportação em CSV, JSON e TXT
- **Compatível com macOS, Windows e Linux**

### Instalação Rápida

```bash
# 1. Instalar LilyPond (requerido para geração de PDF)
# macOS:   brew install lilypond
# Windows: https://lilypond.org/download.html
# Linux:   sudo apt install lilypond

# 2. Criar ambiente virtual e instalar dependências
python -m venv venv
source venv/bin/activate      # macOS/Linux
# venv\Scripts\activate       # Windows

pip install -r requirements.txt

# 3. Executar
python gui.py
```

### Uso Básico

1. **Selecionar instrumentos** no painel esquerdo (clique para selecionar/desselecionar)
2. **Configurar parâmetros** nas abas: Cadeia de Markov, Dinâmicas, Quiálteras, Glissando, Compasso
3. **Clicar em Gerar** — a composição é processada em thread separada
4. **Abrir PDF** para visualizar a partitura gerada
5. **Abrir 📊 Dashboard** para análise estatística; **📁 Análise** para acesso a todos os arquivos exportados

---

## 🇺🇸 English

### Overview

**Markov-Abjad Composer** is an algorithmic composition system that uses Markov Chains to generate musical material and LilyPond/Abjad to produce high-quality contemporary music scores. The system was developed in the context of computational music research at NICS (Interdisciplinary Sound Communication Nucleus), UNICAMP.

The system operates with **five independent Markov matrices** — for pitch, duration, dynamics, technique, and microtonalism — allowing each musical parameter to evolve with its own stochastic logic. Matrices can be trained uniformly (user-configured parameters) or from real MIDI corpus.

**Aesthetic references:** Morton Feldman, Brian Ferneyhough, György Ligeti, Helmut Lachenmann, Salvatore Sciarrino, Iannis Xenakis.

### Key Features

- **42 instruments** in 8 families: woodwinds, brass, strings, keyboards, and percussion (pitched and unpitched)
- **Complete contemporary notation:** nested tuplets, microtonalism (quarter tones), extended techniques, niente dynamics, continuous glissando
- **Graphical proportional notation** (Feldman/Cardew mode): no bar lines, continuous temporal spacing
- **MIDI corpus training:** learns patterns from real MIDI files
- **Analysis dashboard:** 7 visual panels + CSV, JSON, and TXT export
- **Compatible with macOS, Windows, and Linux**

### Quick Install

```bash
# 1. Install LilyPond (required for PDF generation)
# macOS:   brew install lilypond
# Windows: https://lilypond.org/download.html
# Linux:   sudo apt install lilypond

# 2. Create virtual environment and install dependencies
python -m venv venv
source venv/bin/activate      # macOS/Linux
# venv\Scripts\activate       # Windows

pip install -r requirements.txt

# 3. Run
python gui.py
```

### Basic Usage

1. **Select instruments** in the left panel (click to select/deselect)
2. **Configure parameters** in tabs: Markov Chain, Dynamics, Tuplets, Glissando, Time Signature
3. **Click Generate** — composition is processed in a separate thread
4. **Open PDF** to view the generated score
5. **Open 📊 Dashboard** for statistical analysis; **📁 Analysis** for all exported files

---

## Arquitetura / Architecture

```
markov-abjad-composer/
├── gui.py              ← Entry point / interface gráfica
├── integration.py      ← Orquestrador / pipeline controller
├── markov_engine.py    ← Motor Markov / Markov engine
├── abjad_engine.py     ← Geração LilyPond / LilyPond generation
├── note_event.py       ← Estrutura de dados / data structures
├── percussion.py       ← Módulo de percussão / percussion module
├── midi_trainer.py     ← Treinamento MIDI / MIDI training
├── requirements.txt
└── docs/
    ├── README_PT.md    ← Documentação completa em português
    ├── README_EN.md    ← Full documentation in English
    ├── ARCHITECTURE.md ← Arquitetura técnica detalhada
    ├── NOTATION.md     ← Guia de notação / Notation guide
    └── CHANGELOG.md    ← Histórico de versões / Version history
```

## Fluxo de dados / Data Flow

```
GUI (parâmetros)
      ↓
CompositionConfig
      ↓
MarkovEngine.train_uniform() | train_from_sequences()
      ↓
MarkovEngine.generate_score() → list[NoteEvent] por instrumento
      ↓
apply_glissando() → pós-processamento
      ↓
generate_lilypond_code() → código .ly
      ↓
compile_to_pdf() → PDF + MusicXML
      ↓
gerar_dashboard_analise() → PNG
      ↓
exportar_dados_analise() → CSV / JSON / TXT
```

## Requisitos / Requirements

| Software | Versão | Função |
|----------|--------|--------|
| Python   | 3.11+  | Runtime |
| LilyPond | 2.24+  | Compilação de partituras |
| mido     | 1.3+   | Leitura de MIDI |
| matplotlib | 3.7+ | Dashboard visual |
| numpy    | 1.24+  | Cálculos numéricos |

## Licença / License

MIT License — veja [LICENSE](LICENSE)

## Citação / Citation

```bibtex
@software{simurra2026markov,
  author    = {Simurra, Ivan Eiji},
  title     = {Markov-Abjad Composer: Algorithmic Composition with Markov Chains},
  year      = {2026},
  institution = {NICS, UNICAMP},
  url       = {https://github.com/ieysimurra/markov-abjad-composer}
}
```

## Contato / Contact

**Prof. Ivan Eiji Simurra**  
NICS — Núcleo Interdisciplinar de Comunicação Sonora  
UNICAMP — Universidade Estadual de Campinas  
