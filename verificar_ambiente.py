"""
verificar_ambiente.py
=====================
Verifica se o ambiente está corretamente configurado para o
Markov-Abjad Composer.

Uso / Usage:
    python verificar_ambiente.py
"""

import sys
import shutil
import importlib
import platform

OK    = "✅"
WARN  = "⚠️ "
ERROR = "❌"

def check(label, ok, detail=""):
    status = OK if ok else ERROR
    msg = f"  {status}  {label}"
    if detail:
        msg += f"  ({detail})"
    print(msg)
    return ok

def main():
    print("=" * 55)
    print("  Markov-Abjad Composer — Verificação de Ambiente")
    print("=" * 55)
    print()

    all_ok = True

    # Python
    version = sys.version_info
    py_ok = version >= (3, 11)
    all_ok &= check(
        f"Python {version.major}.{version.minor}.{version.micro}",
        py_ok,
        "requer 3.11+" if not py_ok else ""
    )

    # LilyPond
    lily = shutil.which("lilypond")
    lily_ok = lily is not None
    all_ok &= check(
        "LilyPond",
        lily_ok,
        lily if lily_ok else "não encontrado no PATH"
    )

    # Dependências Python
    print()
    print("  Dependências Python:")
    deps = {
        "mido":       "leitura de MIDI",
        "matplotlib": "dashboard de análise",
        "numpy":      "cálculos numéricos",
        "tkinter":    "interface gráfica",
    }
    for pkg, desc in deps.items():
        try:
            m = importlib.import_module(pkg)
            ver = getattr(m, "__version__", "?")
            check(f"{pkg} {ver}", True, desc)
        except ImportError:
            check(f"{pkg}", False, f"não instalado — pip install {pkg}")
            all_ok = False

    # Módulos do projeto
    print()
    print("  Módulos do projeto:")
    modules = [
        "note_event", "percussion", "markov_engine",
        "abjad_engine", "integration", "midi_trainer",
    ]
    for mod in modules:
        try:
            importlib.import_module(mod)
            check(f"{mod}.py", True)
        except ImportError as e:
            check(f"{mod}.py", False, str(e))
            all_ok = False

    # Plataforma
    print()
    sys_name = platform.system()
    check(f"Plataforma: {sys_name} {platform.release()}", True)

    print()
    print("=" * 55)
    if all_ok:
        print("  ✅  Ambiente pronto. Execute: python gui.py")
    else:
        print("  ❌  Corrija os problemas acima antes de executar.")
    print("=" * 55)

if __name__ == "__main__":
    main()
