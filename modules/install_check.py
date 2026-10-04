"""Chequeo de instalación: avisa si hay archivos sueltos o desactualizados.

Evita que la app ejecute código viejo sin avisar (p. ej. un
modules/les_enfants_terribles.py anterior).
"""

from __future__ import annotations

from pathlib import Path

# Archivos que SOLO deben vivir dentro de su carpeta; en la raíz son copias
# sueltas (y, si difieren de la buena, una trampa).
MISPLACED_ROOT_FILES = frozenset(
    {
        "les_enfants_terribles.py",
        "militaires_sans_frontieres.py",
        "liquid_engine.py",
        "naked_engine.py",
        "shalashaska_engine.py",
        "solidus_engine.py",
        "venom_engine.py",
        "mission_control.py",
        "_streamlit_stub.py",
        "e2e_fixture.py",
    }
)

PLANNING_MODULE = Path("modules") / "les_enfants_terribles.py"


def installation_problems(root: Path) -> list[str]:
    """Lista de problemas de instalación; vacía si todo está en orden."""
    root = Path(root)
    problems: list[str] = []

    planning_module = root / PLANNING_MODULE
    if not planning_module.exists():
        problems.append(
            f"Falta {PLANNING_MODULE.as_posix()}: el módulo de planeación no "
            "está en su carpeta."
        )
    else:
        try:
            text = planning_module.read_text(encoding="utf-8", errors="replace")
        except OSError:
            text = ""
        if "APP_BUILD =" not in text:
            problems.append(
                f"{PLANNING_MODULE.as_posix()} es una versión anterior "
                "(no tiene sello de versión). Reemplázalo por el actual."
            )

    stray = sorted(
        name for name in MISPLACED_ROOT_FILES if (root / name).is_file()
    )
    stray += sorted(
        path.name
        for path in root.glob("test_*.py")
        if path.is_file()
    )
    stray += sorted(
        path.name for path in root.glob("__init__*.py") if path.is_file()
    )
    if stray:
        problems.append(
            "Archivos sueltos en la raíz que deben vivir en su carpeta "
            "(modules/, engines/ o tests/) o borrarse: "
            + ", ".join(stray)
            + "."
        )

    if (root / "download").is_file() and not (root / ".gitignore").exists():
        problems.append(
            "No hay .gitignore y existe un archivo 'download': es el "
            ".gitignore guardado con otro nombre. Renómbralo a .gitignore "
            "para que .streamlit/secrets.toml no se suba al repositorio."
        )
    return problems
