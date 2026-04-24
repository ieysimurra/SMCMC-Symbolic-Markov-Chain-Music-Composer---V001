# Markov-Abjad Composer — Documentação Completa

**Prof. Ivan Eiji Simurra · NICS / UNICAMP · 2026**

---

## Sumário

1. [Contexto e Motivação](#1-contexto-e-motivação)
2. [Cadeias de Markov na Composição Musical](#2-cadeias-de-markov-na-composição-musical)
3. [Arquitetura do Sistema](#3-arquitetura-do-sistema)
4. [Instrumentação e Tessituras](#4-instrumentação-e-tessituras)
5. [Sistema de Notação](#5-sistema-de-notação)
6. [Instalação e Configuração](#6-instalação-e-configuração)
7. [Manual de Uso da Interface](#7-manual-de-uso-da-interface)
8. [Arquivos de Saída](#8-arquivos-de-saída)
9. [Referências](#9-referências)
10. [Glossário](#10-glossário)

---

## 1. Contexto e Motivação

A composição algorítmica ocupa um espaço central no pensamento musical do século XX e XXI, situando-se na confluência entre teoria musical, matemática, ciências cognitivas e tecnologia. Ao delegar aspectos do processo criativo a sistemas formais, o compositor não abdica de seu papel, mas o reposiciona: de articulador direto de alturas e durações para arquiteto de sistemas que geram material musical segundo regras explicitamente definidas.

O **Markov-Abjad Composer** insere-se nessa tradição com um foco específico: explorar processos estocásticos — em particular as Cadeias de Markov — como motor de geração de material musical, combinando-os com um sistema de notação contemporâneo de alta precisão baseado em LilyPond e Abjad. O resultado é um ambiente onde a imprevisibilidade controlada da cadeia de Markov dialoga com as exigências notacionais da música de câmara e orquestral contemporânea.

Do ponto de vista estético, o sistema foi concebido em diálogo com compositores como Morton Feldman (indeterminismo e densidade temporal), Brian Ferneyhough (complexidade rítmica e quiálteras aninhadas), György Ligeti (micropolifonia e textura), Salvatore Sciarrino (técnicas estendidas e dinâmicas extremas) e Helmut Lachenmann (musique concrète instrumentale). Esses referenciais não são imitados, mas evocados como horizonte estético que orienta as escolhas de parâmetros implementados.

---

## 2. Cadeias de Markov na Composição Musical

### 2.1 Fundamentos Matemáticos

Uma Cadeia de Markov é um processo estocástico discreto que satisfaz a **propriedade markoviana**: a probabilidade de transição para um estado futuro depende exclusivamente do estado presente, e não da história anterior de estados. Formalmente:

```
P(Sₙ₊₁ = s | S₁, S₂, ..., Sₙ) = P(Sₙ₊₁ = s | Sₙ)
```

A cadeia é descrita por uma **matriz de transição T**, onde cada elemento Tᵢⱼ representa a probabilidade de transitar do estado i para o estado j. Para cadeias de **ordem N**, o contexto relevante é formado pelos N estados precedentes, ampliando o espaço de contextos possíveis para |S|ᴺ combinações.

### 2.2 Cinco Matrizes Independentes

O sistema utiliza cinco matrizes de Markov independentes, cada uma governando um parâmetro musical distinto:

| Parâmetro | Espaço de estados | Descrição |
|-----------|------------------|-----------|
| **Pitch** | 12 classes cromáticas + microtons + pausa R | Transições entre alturas |
| **Duration** | Semibreve, mínima, semínima, colcheia, semicolcheia, fusa (+ pontuadas) | Transições entre valores rítmicos |
| **Dynamic** | ppp, pp, p, mp, mf, f, ff, fff, niente | Transições entre níveis dinâmicos |
| **Technique** | ord., s.p., s.t., col legno, flutter, multifônico, harm., tremolo, pizz. | Transições entre técnicas |
| **Microtone** | natural, +¼, −¼, +¾, −¾ | Transições entre modificadores microtonais |

A **independência das matrizes** é uma escolha arquitetural deliberada: ritmo e harmonia evoluem com suas próprias lógicas internas, sem correlação forçada. Ao mesmo tempo, o treinamento por corpus MIDI captura as correlações emergentes do repertório aprendido.

### 2.3 Modos de Treinamento

**Modo Uniforme (padrão)**

As matrizes são construídas com pesos deterministicamente normalizados usando `itertools.product` para preencher todos os contextos N-gramas possíveis. Isso garante precisão estatística: configurar 30% de pausas produz efetivamente ~30% de pausas. A variância estocástica da cadeia produz sequências diferentes a cada geração.

**Modo MIDI (corpus)**

Arquivos MIDI são carregados e analisados. As transições observadas alimentam as matrizes de contagem, que são normalizadas em probabilidades. Múltiplos arquivos podem ser combinados (merge). Um mecanismo de **backoff progressivo** garante tratamento de contextos não observados:

1. Tentativa com contexto exato de ordem N
2. Backoff para sufixo de ordem N−1
3. Continuação até ordem 1
4. Fallback final com `_default_weights` (preserva parâmetros do usuário)

### 2.4 Geração: n_notes conta apenas notas sonoras

O parâmetro `n_notes` define o número de **notas sonoras** (não incluindo pausas). O loop de geração itera até atingir exatamente `n_notes` notas sonoras, independente de quantas pausas a cadeia inserir. Um `safety_limit` baseado na `rest_probability` evita loops infinitos em configurações extremas.

---

## 3. Arquitetura do Sistema

### 3.1 Módulos

| Módulo | Responsabilidade |
|--------|-----------------|
| `gui.py` | Interface Tkinter, parâmetros, threading, log, botões de saída |
| `integration.py` | CompositionConfig, CompositionResult, pipelines, estatísticas, dashboard, CSV/JSON/TXT |
| `markov_engine.py` | MarkovMatrix, MarkovEngine, treinamento, geração, InstrumentFamily, tessituras |
| `abjad_engine.py` | Geração LilyPond manual, quantização, quiálteras, hairpins, glissando, compilação |
| `note_event.py` | NoteEvent dataclass, enums, apply_glissando, _pitch_to_midi |
| `percussion.py` | DrumVoice, 29 instrumentos, PITCHED_PERCUSSION, NoteHead overrides |
| `midi_trainer.py` | MidiTrainer, análise de MIDI, merge de corpus |

### 3.2 NoteEvent — Estrutura Central

```python
@dataclass(frozen=True)
class NoteEvent:
    pitch_name    : Optional[str]    # pitch LilyPond (ex: "fis''", "bes,")
    duration      : Fraction          # duração exata (1/4 = semínima)
    dynamic       : Dynamic           # enum: PPP...FFF, NIENTE
    technique     : Technique         # enum: ORDINARIO, SUL_PONTICELLO...
    microtone     : Microtone         # enum: NONE, QS, QF, TQS, TQF
    notation_type : NotationType      # NORMAL ou PROPORTIONAL
    velocity      : int               # MIDI velocity (0–127)
    is_rest       : bool = False
    tuplet_ratio  : Optional[tuple] = None   # (num, den) ex: (3,2)
    tie_start     : bool = False
    tie_stop      : bool = False
    gliss_to_next : bool = False
```

### 3.3 Fluxo de Dados

```
GUI → CompositionConfig
    → MarkovEngine.train_uniform() | train_from_sequences()
    → MarkovEngine.generate_score() → dict[str, list[NoteEvent]]
    → apply_glissando()
    → _calcular_estatisticas()
    → generate_lilypond_code() → str
    → compile_to_pdf() → PDF + MusicXML
    → gerar_dashboard_analise() → PNG
    → exportar_dados_analise() → CSV/JSON/TXT
    → CompositionResult → GUI
```

---

## 4. Instrumentação e Tessituras

Todas as tessituras em **concert pitch** (soa real), baseadas em Adler (3ª ed.), Gould e Blatter.

### Madeiras
| Instrumento | Tessitura |
|-------------|-----------|
| Flauta (Flute) | B3–D7 |
| Oboé (Oboe) | Bb3–G6 |
| Clarinete (Clarinet) | D3–Bb6 |
| Fagote (Bassoon) | Bb1–Eb5 |

### Metais
| Instrumento | Tessitura |
|-------------|-----------|
| Trompa (Horn) | B1–F5 |
| Trompete (Trumpet) | F#3–Bb5 |
| Trombone | E2–F5 |
| Tuba | D1–F4 |

### Cordas
| Instrumento | Tessitura |
|-------------|-----------|
| Violino (Violin) | G3–E7 |
| Viola | C3–E6 |
| Violoncelo (Violoncello) | C2–C6 |
| Contrabaixo (Double Bass) | E1–C5 |
| Harpa (Harp) | C1–G7 |

### Percussão de Altura Definida
| Instrumento | Tessitura | Clave |
|-------------|-----------|-------|
| Vibrafone (Vibraphone) | F3–F6 | Sol |
| Marimba | C2–C7 | Sol |
| Tímpano (Timpani) | E2–F4 | Fá |
| Xilofone (Xylophone) | C4–C7 | Sol |
| Glockenspiel | G5–C8 (escrita) | Sol |
| Crotales | C4–C6 (escrita) | Sol |

### Percussão de Altura Indefinida

Posições e cabeças de nota segundo Weinberg (PAS, 1998) e Gould (Behind Bars, pp. 600–650):

| Instrumento | Posição na pauta | Cabeça de nota |
|-------------|-----------------|----------------|
| Crash Cymbal | Linha aux. superior | △ triangle |
| China/Splash | Linha aux. superior | ◇ diamond |
| Prato Suspenso | Espaço acima 1ª | △ triangle |
| Pratos a 2 | Espaço acima 1ª | × cross |
| Ride Cymbal | 1ª linha | × cross |
| Bell of Ride | 1ª linha | ⊗ xcircle |
| Hi-Hat Fechado | 1ª linha | × cross |
| Hi-Hat Aberto | 1ª linha | ⊗ xcircle |
| Hi-Hat com Pé | Linha aux. inferior | × cross |
| Tam-Tam | 3ª linha central | △ triangle |
| Caixa Clara | 4ª linha | ● default |
| Bumbo | Linha aux. inferior | ● default |
| Tantã | Espaço 4ª–5ª | ● default |
| Tom Agudo | 2ª linha | ● default |
| Tom Médio | Espaço 2ª–3ª | ● default |
| Tom Grave | Espaço 3ª–4ª | ● default |
| Tom de Chão | Espaço 4ª–5ª | ● default |
| Gongo | Espaço abaixo 5ª | ● default |
| Triângulo | Linha aux. superior | △ triangle |
| Woodblock | Espaço 1ª–2ª | □ do |
| Cowbell | Espaço 1ª–2ª | ▲ la |
| Crotales (indef.) | Linha aux. superior | ◇ diamond |
| Claves | Espaço 1ª–2ª | □ do |

---

## 5. Sistema de Notação

### 5.1 Pipeline LilyPond Manual

O código LilyPond é gerado 100% manualmente (sem `music21.lily.translate`), garantindo:
- Controle total sobre cada elemento notacional
- Compatibilidade com deploy remoto
- Velocidade de geração muito superior

Etapas do pipeline por instrumento:
1. Resolução de clave por família
2. Quantização em compassos com `Fraction` arithmetic
3. Agrupamento de eventos em blocos normais e quiálteras
4. Emissão de notas com pitch, duração, dinâmica, técnica e indicações especiais
5. Fechamento de spanners antes das barras
6. Compilação com timeout dinâmico adaptativo

### 5.2 Notação Proporcional Gráfica

Ativada pelo checkbox "Notação Proporcional", produz partituras no espírito de Feldman/Cardew:

- `Timing_translator` e `Default_bar_line_engraver` removidos → sem barras de compasso
- `TimeSignature`, `KeySignature`, `BarNumber` transparentes
- `proportionalNotationDuration` ativo → espaçamento proporcional às durações
- Pausas emitidas como spacer (`s`) → invisíveis, preservam espaçamento temporal
- Hastes, colchetes e dinâmicas mais finas → visual mais leve e abstrato

### 5.3 Glissando — Fórmula de Ponderação

```
P_final = min(1.0, P_base × (1 + w × tanh(Δsemitons / 12)))
```

onde `P_base` é o slider de Densidade e `w = 0.5` é o peso do intervalo. Restrições: não parte de pausa, não chega a pausa, não coexiste com ligadura de valor.

### 5.4 Timeout Adaptativo

O tempo máximo de compilação LilyPond é calculado automaticamente:
- Base por tamanho do código (.ly): 150s–1800s
- Multiplicadores: +40% para notação proporcional, +20% para quiálteras densas (>200), +10% para hairpins densos
- Máximo absoluto: 1800s (30 minutos)

---

## 6. Instalação e Configuração

### 6.1 macOS

```bash
# Instalar LilyPond
brew install lilypond

# Criar e ativar ambiente virtual
python3 -m venv venv
source venv/bin/activate

# Instalar dependências
pip install -r requirements.txt

# Executar
python gui.py
```

### 6.2 Windows

```powershell
# 1. Instalar Python de python.org (marcar "Add Python to PATH")
# 2. Instalar LilyPond de lilypond.org
# 3. Adicionar ao PATH: C:\Program Files (x86)\LilyPond\usr\bin

# Verificar instalação do LilyPond
Get-ChildItem "C:\Program Files*" -Recurse -Filter "lilypond.exe"

# Criar e ativar ambiente virtual
python -m venv venv
venv\Scripts\activate

# Instalar dependências
pip install -r requirements.txt

# Executar
python gui.py
```

### 6.3 Linux

```bash
# Instalar LilyPond
sudo apt install lilypond   # Debian/Ubuntu
# sudo dnf install lilypond  # Fedora

# Criar e ativar ambiente virtual
python3 -m venv venv
source venv/bin/activate

# Instalar dependências
pip install -r requirements.txt

# Executar
python gui.py
```

---

## 7. Manual de Uso da Interface

### 7.1 Painel de Instrumentos (esquerda)

- Instrumentos agrupados por família
- Clique para selecionar (destacado em âmbar) / clique novamente para desselecionar
- Múltiplas instâncias do mesmo instrumento são suportadas
- Botões: Selecionar Todos / Limpar

### 7.2 Aba MIDI

| Controle | Função |
|----------|--------|
| Adicionar Arquivo/Pasta | Carrega arquivos .mid para treinamento |
| Selecionar trilha | Escolhe qual trilha analisar em arquivos multi-trilha |
| Analisar Corpus | Processa e treina as matrizes |
| Limpar Corpus | Retorna ao modo uniforme |

### 7.3 Aba Musical

| Parâmetro | Descrição |
|-----------|-----------|
| Ordem da Cadeia | 1–4. Ordens maiores = mais memória, mais coerência local |
| Notas / instrumento | Notas sonoras por instrumento (pausas não contam) |
| Pausas (%) | Proporção de pausas no total de eventos |
| Dinâmicas (pesos) | Peso relativo de cada nível dinâmico (ppp a fff) |
| Hairpins | Crescendo/decrescendo automático entre transições dinâmicas |
| Quiálteras | Densidade (%) e Complexidade (1–4) |
| Glissando | Densidade (%) de glissandos entre notas consecutivas |
| BPM | Andamento em batidas por minuto |
| Fórmula de compasso | 4/4, 3/4, 2/4, 6/8, 5/4, 7/8 |
| Mudanças de compasso | Mudanças aleatórias sincronizadas entre instrumentos |

### 7.4 Aba Microtonalismo

| Parâmetro | Descrição |
|-----------|-----------|
| Habilitar | Ativa a matriz de microtons |
| Densidade (%) | Proporção de notas com modificação microtonal |
| Por família | Controle independente por grupo instrumental |

### 7.5 Aba Notação

| Parâmetro | Descrição |
|-----------|-----------|
| Título / Compositor | Metadados da partitura |
| Notação Proporcional | Modo gráfico sem barras de compasso |
| Paisagem | Orientação horizontal da página |
| Pasta de saída | Diretório de destino dos arquivos |

### 7.6 Botões de Resultado

| Botão | Ação |
|-------|------|
| Abrir PDF | Partitura no visualizador padrão |
| Abrir .ly | Código LilyPond fonte |
| Abrir MusicXML | Compatível com Sibelius, Finale, MuseScore |
| 📊 Dashboard | Dashboard de análise visual (PNG) |
| 📁 Análise | Pasta com todos os arquivos exportados |
| Exportar Matrizes CSV | Matrizes de Markov em CSV |

---

## 8. Arquivos de Saída

### Partitura
| Arquivo | Conteúdo |
|---------|----------|
| `{base}.ly` | Código LilyPond fonte |
| `{base}.pdf` | Partitura em PDF |
| `{base}.xml` | MusicXML |

### Análise
| Arquivo | Conteúdo |
|---------|----------|
| `{base}_relatorio.txt` | Relatório completo com tabelas ASCII |
| `{base}_analise.json` | Dados estruturados completos |
| `{base}_eventos.csv` | Um evento por linha com todos os parâmetros |
| `{base}_resumo.csv` | Resumo por instrumento |
| `{base}_dist_dinamicas.csv` | Distribuição de dinâmicas |
| `{base}_dist_duracoes.csv` | Distribuição de valores rítmicos |
| `{base}_dist_pitch.csv` | Distribuição de classes de pitch |
| `{base}_dist_tecnicas.csv` | Distribuição de técnicas estendidas |
| `{base}_dist_microtons.csv` | Distribuição de microtons |
| `{base}_dashboard.png` | Dashboard visual (7 painéis, 150 DPI) |

---

## 9. Referências

### Composição Algorítmica
- Xenakis, I. (1992). *Formalized Music*. Pendragon Press.
- Nierhaus, G. (2009). *Algorithmic Composition*. Springer.
- Roads, C. (1996). *The Computer Music Tutorial*. MIT Press.

### Cadeias de Markov
- Norris, J. R. (1997). *Markov Chains*. Cambridge University Press.
- Pinkerton, R. C. (1956). Information Theory and Melody. *Scientific American*, 194(2), 77–86.

### Notação Contemporânea
- Gould, E. (2011). *Behind Bars*. Faber Music.
- Stone, K. (1980). *Music Notation in the 20th Century*. W. W. Norton.
- Adler, S. (2002). *The Study of Orchestration* (3rd ed.). W. W. Norton.
- Weinberg, N. (1998). *Guide to Standardized Drumset Notation*. PAS Publications.

### Ferramentas
- LilyPond Music Engraver (2.24+). [lilypond.org](https://lilypond.org)
- Abjad API (3.x). [abjad-api.readthedocs.io](https://abjad-api.readthedocs.io)
- mido. [mido.readthedocs.io](https://mido.readthedocs.io)

---

## 10. Glossário

| Termo | Definição |
|-------|-----------|
| Cadeia de Markov | Processo estocástico onde a transição ao próximo estado depende apenas do estado atual |
| Matriz de transição | Tabela de probabilidades de transição entre estados |
| Backoff | Estratégia de fallback: quando o contexto de ordem N não foi observado, tenta ordens menores |
| NoteEvent | Dataclass imutável representando um único evento musical com todos os seus parâmetros |
| LilyPond | Sistema de engraving musical que compila arquivos de texto em partituras de alta qualidade |
| Abjad | Biblioteca Python para controle formalizado de partituras LilyPond |
| Notação proporcional | Sistema sem barras de compasso onde o espaço é proporcional à duração |
| Quiáltera | Subdivisão rítmica irregular: tercina (3:2), quintina (5:4), septina (7:4) |
| Microton | Altura entre os semitons cromáticos. O sistema suporta quartos de tom (±¼, ±¾) |
| Hairpin | Símbolo de crescendo (< ) ou decrescendo (>) |
| Glissando | Deslizamento contínuo de altura entre duas notas |
| DrumVoice | Estrutura que define posição de pauta e cabeça de nota para percussão indefinida |
| Concert pitch | Altura real soada, independente da transposição notacional |
| n_notes | Número de notas **sonoras** por instrumento (pausas não são contadas) |
