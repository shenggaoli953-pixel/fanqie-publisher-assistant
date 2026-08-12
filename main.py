from pathlib import Path
import sys

from publisher.ui import run_app


def application_data_dir(script_path: Path, executable_path: Path | None = None) -> Path:
    if executable_path is not None:
        return executable_path.parents[2] / "data"
    return script_path.parent / "data"


if __name__ == "__main__":
    executable_path = Path(sys.executable).resolve() if getattr(sys, "frozen", False) else None
    run_app(application_data_dir(Path(__file__).resolve(), executable_path))
