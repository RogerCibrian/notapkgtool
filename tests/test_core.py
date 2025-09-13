from pathlib import Path

from notapkgtool.core import load_yaml


def test_load_yaml():
    yaml_path = Path(__file__).parent / "fixtures" / "test.yaml"
    data = load_yaml(str(yaml_path))

    assert isinstance(data, dict)
    assert data["name"] == "test"
    assert data["version"] == 1.0
    assert data["description"] == "A test fixture for testing purposes."
