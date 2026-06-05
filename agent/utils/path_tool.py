import os

def get_project_root():
    current_file = os.path.abspath(__file__)
    project_root = os.path.dirname(os.path.dirname(current_file))
    
    return project_root

def get_absolute_path(relative_path):
    project_root = get_project_root()
    absolute_path = os.path.join(project_root, relative_path)
    
    return absolute_path
