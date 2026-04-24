# Changelog

Todas as mudanças notáveis deste projeto estão documentadas aqui.  
All notable changes to this project are documented here.

O formato é baseado em [Keep a Changelog](https://keepachangelog.com/pt-BR/1.0.0/).

---

## [1.0.0] — 2026-04

### Adicionado / Added
- Sistema completo de composição algorítmica com Cadeias de Markov
- Cinco matrizes de Markov independentes: pitch, duration, dynamic, technique, microtone
- Interface gráfica Tkinter com tema editorial escuro
- Geração manual de código LilyPond (sem dependência de music21.lily.translate)
- Suporte a 42 instrumentos em 8 famílias
- Módulo de percussão completo (`percussion.py`): 29 instrumentos de altura indefinida + 6 de altura definida
- Notação proporcional gráfica (modo Feldman/Cardew)
- Microtonalismo: quartos de tom (±¼, ±¾)
- Quiálteras: tercinas, quintinas, septinas, quiálteras 6:4 e aninhadas (estilo Ferneyhough)
- Glissando com ponderação por intervalo via função tanh
- Hairpins automáticos (crescendo/decrescendo)
- Treinamento por corpus MIDI com merge de múltiplos arquivos
- Backoff progressivo para contextos não observados no corpus
- Dashboard de análise com 7 painéis visuais (PNG, 150 DPI)
- Exportação completa de dados analíticos: CSV (8 arquivos), JSON, TXT
- Timeout adaptativo de compilação LilyPond
- Compatibilidade multiplataforma: macOS, Windows, Linux
- Documentação bilíngue (PT/EN)

### Corrigido / Fixed
- `rest_probability` não respeitada para order > 1 (MarkovMatrix.weighted usava k pequeno)
- Compassos dessincronizados entre instrumentos (sequência agora centralizada)
- Identificadores LilyPond inválidos com dígitos (convertidos para números romanos minúsculos)
- PDF abrindo versão em cache em vez da recém-gerada (GUI abre após confirmação)
- `n_notes` contava pausas junto com notas sonoras (corrigido: pausas não contam)
- Tessitura de Trompa, Trompete e Trombone corrigidas contra Adler/Gould
- `pathlib.Path` indefinido em `_on_open_analise_folder` (usando `Path` importado no topo)
- SyntaxWarning `\d` em docstring do abjad_engine

### Técnico / Technical
- `MarkovMatrix.weighted()` usa `itertools.product` para preencher todos os contextos N-gramas
- `MarkovMatrix.sample()` implementa backoff progressivo com `_default_weights`
- Loop de geração: `while notes_generated < n_notes` com `safety_limit` baseado em `rest_probability`
- Todas as comparações de duração usam `Fraction` arithmetic (sem float)
- `abjad_engine.py`: percussão indefinida usa Staff normal com NoteHead overrides
