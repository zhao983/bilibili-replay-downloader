"""Build a source-only archive, never including login or download data."""

from pathlib import Path
import zipfile

ROOT = Path(__file__).resolve().parents[1]
TOP_FILES = ("README.md", "LICENSE", "THIRD_PARTY_NOTICES.md", "pyproject.toml", ".gitignore", "setup.cmd", "start.cmd")
SOURCE_PATTERNS = {"src": "*.py", "tests": "*.py", "scripts": "*.py", ".github/workflows": "*.yml", "licenses": "*.txt"}


def source_files(root=ROOT):
    files = [root / name for name in TOP_FILES]
    for directory, pattern in SOURCE_PATTERNS.items():
        files.extend(path for path in (root / directory).rglob(pattern)
                     if "__pycache__" not in path.parts)
    return sorted(files)


def package(root=ROOT, output=None):
    output = Path(output) if output else root.parent / (root.name + ".zip")
    with zipfile.ZipFile(output, "w", compression=zipfile.ZIP_DEFLATED) as archive:
        for path in source_files(root):
            archive.write(path, Path(root.name) / path.relative_to(root))
    return output


if __name__ == "__main__":
    result = package()
    print(f"Source archive: {result}")
