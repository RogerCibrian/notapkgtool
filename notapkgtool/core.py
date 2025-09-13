from pathlib import Path
from typing import Any, Union

import yaml


def load_yaml(file_path: str | Path) -> Any:
    """
    Load and parse a YAML file for CLI usage.

    :param file_path: Path to the YAML file (as string or Path).
    :return: Parsed content of the YAML file.
    :raises SystemExit: If the file doesn't exist, is empty, or contains invalid YAML.
    """
    path = Path(file_path)

    if not path.exists():
        print(f"Error: File not found: {path}")
        raise SystemExit(1)

    try:
        with path.open("r", encoding="utf-8") as file:
            data = yaml.safe_load(file)
    except yaml.YAMLError as e:
        print(f"Error parsing YAML file '{path}': {e}")
        raise SystemExit(1)

    if not data:
        print(f"Error: YAML file '{path}' is empty or invalid.")
        raise SystemExit(1)

    return data
