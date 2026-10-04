"""Pruebas del chequeo de instalación (archivos desordenados / viejos)."""

from pathlib import Path

from modules.install_check import installation_problems


def _write(path: Path, text: str = "x") -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")


def _clean_tree(root: Path) -> None:
    _write(root / "modules" / "les_enfants_terribles.py", 'APP_BUILD = "v"\n')
    _write(root / ".gitignore", ".streamlit/secrets.toml\n")


def test_clean_installation_has_no_problems(tmp_path):
    _clean_tree(tmp_path)
    assert installation_problems(tmp_path) == []


def test_detects_planning_module_without_build_stamp(tmp_path):
    _write(tmp_path / "modules" / "les_enfants_terribles.py", "# versión vieja\n")
    problems = installation_problems(tmp_path)
    assert any("versión anterior" in p for p in problems)


def test_detects_missing_planning_module(tmp_path):
    problems = installation_problems(tmp_path)
    assert any("Falta modules/les_enfants_terribles.py" in p for p in problems)


def test_detects_the_exact_misplaced_file_situation(tmp_path):
    """El caso real: la versión nueva quedó en la raíz y la de modules/ es
    vieja."""
    _write(tmp_path / "modules" / "les_enfants_terribles.py", "# vieja\n")
    _write(tmp_path / "les_enfants_terribles.py", 'APP_BUILD = "nueva"\n')
    problems = " ".join(installation_problems(tmp_path))
    assert "les_enfants_terribles.py" in problems
    assert "versión anterior" in problems
    assert "sueltos en la raíz" in problems


def test_detects_loose_tests_and_init_copies(tmp_path):
    _clean_tree(tmp_path)
    _write(tmp_path / "test_kazuhira.py")
    _write(tmp_path / "__init__ (1).py")
    problems = " ".join(installation_problems(tmp_path))
    assert "test_kazuhira.py" in problems and "__init__ (1).py" in problems


def test_detects_gitignore_saved_as_download(tmp_path):
    _write(tmp_path / "modules" / "les_enfants_terribles.py", 'APP_BUILD = "v"\n')
    _write(tmp_path / "download", "# .gitignore\n")
    problems = " ".join(installation_problems(tmp_path))
    assert "gitignore" in problems and "secrets" in problems


def test_download_file_is_fine_if_gitignore_exists(tmp_path):
    _clean_tree(tmp_path)
    _write(tmp_path / "download", "otra cosa\n")
    assert installation_problems(tmp_path) == []


def test_the_real_project_tree_is_clean():
    root = Path(__file__).resolve().parent.parent
    assert installation_problems(root) == [], installation_problems(root)
