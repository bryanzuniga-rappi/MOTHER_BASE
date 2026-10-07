"""Empaqueta únicamente fuentes y configuración pública del release revisado."""
from pathlib import Path
import hashlib
import zipfile

root = Path(__file__).resolve().parent
version = 'MOTHER_BASE-v14-naked-otacon-v2'
target = root.parent / f'{version}.zip'
root_files = [
    'app.py', 'auth.py', 'modelo_abasto.py', 'mother_base_theme.py',
    'README.md', 'VALIDATION.txt', 'requirements.txt', 'requirements-dev.txt',
    'requirements-dev.lock', 'runtime.txt', '.python-version', '.gitignore',
    '.streamlit/config.toml', '.streamlit/secrets.toml.example',
    'package_release.py',
]
files = [root / name for name in root_files]
for folder in ('engines', 'modules', 'tests'):
    files.extend(sorted((root / folder).rglob('*.py')))
assert all(file.is_file() for file in files)
assert all(file.name != 'secrets.toml' for file in files)
with zipfile.ZipFile(target, 'w', zipfile.ZIP_DEFLATED) as archive:
    for file in files:
        archive.write(file, Path(version) / file.relative_to(root))
with zipfile.ZipFile(target) as archive:
    assert archive.testzip() is None
    assert len(archive.namelist()) == len(files)
    assert not any('__pycache__' in name or '/.venv' in name or name.endswith('/secrets.toml')
                   for name in archive.namelist())
digest = hashlib.sha256(target.read_bytes()).hexdigest()
target.with_suffix('.zip.sha256').write_text(f'{digest}  {target.name}\n', encoding='ascii')
print(f'{target}\n{len(files)} archivos; {target.stat().st_size} bytes\nSHA256 {digest}')
