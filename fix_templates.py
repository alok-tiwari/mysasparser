import yaml
import re
from pathlib import Path

def fix_jinja_syntax(content):
    """Fix common Jinja2 template syntax issues."""
    
    # Fix empty dictionaries
    content = re.sub(r' = \n', r' = {}\n', content)
    content = re.sub(r' = $', r' = {}', content, flags=re.MULTILINE)
    
    # Fix standalone curly braces
    content = re.sub(r'\{\}(?!\})', '', content)
    
    # Fix incorrect Jinja2 if-else structures
    content = re.sub(
        r'{% if ([^%}]+) %}\s*([^{%]+)\s*\{\}\s*{% for',
        r'{% if \1 %}\n\2\n{% endif %}\n{% for',
        content
    )
    
    # Fix format strings
    replacements = [
        (r'\.format\(\)', ''),
        (r': \'\.format', ': {}\'\.format'),
        (r': "\.format', ': {}"\.format'),
        (r'print\("([^"]+)"\)\.format', r'print("\1 {}")\.format'),
        (r'print\(\'([^\']+)\'\)\.format', r'print(\'\1 {}\')\.format'),
        (r'\.format type', '.format()'),
    ]
    
    for old, new in replacements:
        content = re.sub(old, new, content)
    
    return content

def validate_yaml(content):
    """Validate YAML syntax."""
    try:
        yaml.safe_load(content)
        return True
    except yaml.YAMLError as e:
        print("YAML validation error: {}".format(e))
        return False

def fix_template_file(filename):
    """Fix Jinja2 template syntax in YAML file."""
    filepath = Path(filename)
    if not filepath.exists():
        print("Error: File {} not found".format(filename))
        return
    
    # Create backup
    backup_path = filepath.with_suffix(filepath.suffix + '.bak')
    
    try:
        # Read content
        with open(filepath, 'r') as f:
            content = f.read()
        
        # Create backup
        with open(backup_path, 'w') as f:
            f.write(content)
        
        # Fix syntax
        fixed_content = fix_jinja_syntax(content)
        
        # Validate YAML
        if not validate_yaml(fixed_content):
            print("Error: Fixed content is not valid YAML")
            return
        
        # Write fixed content
        with open(filepath, 'w') as f:
            f.write(fixed_content)
        
        print("Successfully fixed {}".format(filename))
        print("Backup saved as {}".format(backup_path))
        
    except Exception as e:
        print("Error processing {}: {}".format(filename, e))
        # Restore from backup if exists
        if backup_path.exists():
            backup_path.replace(filepath)
            print("Restored original file from backup")

if __name__ == "__main__":
    fix_template_file("T_sas_templates.yaml") 