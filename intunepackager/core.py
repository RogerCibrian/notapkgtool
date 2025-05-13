import yaml

def load_yaml(file_path):
    """
    Load a YAML file and return its content.
    
    :param file_path: Path to the YAML file.
    :return: Content of the YAML file.
    """
    with open(file_path, 'r', encoding='utf-8') as file:
        return yaml.safe_load(file)
    # Load the YAML file
    data = yaml.safe_load(file)
    
    # Check if the file is empty
    if not data:
        raise ValueError("The YAML file is empty.")