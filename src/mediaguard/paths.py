from pathlib import Path


def project_root() -> Path:
    return Path(__file__).resolve().parents[2]


def runtime_dir(root: Path | None = None) -> Path:
    return (root or project_root()) / "runtime"


def database_path(root: Path | None = None) -> Path:
    return runtime_dir(root) / "mediaguard.sqlite3"
