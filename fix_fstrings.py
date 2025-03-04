import re
import sys
from pathlib import Path

def fix_fstrings(content):
    # Patterns to find f-strings
    patterns = [
        # Pattern 1: f"..." with simple variable
        (r'f"([^"]*)\{([^}:]+)\}([^"]*)"', r'"\1{}\3".format(\2)'),
        
        # Pattern 2: f"..." with format specifier
        (r'f"([^"]*)\{([^}]+):([^}]+)\}([^"]*)"', r'"\1{:\3}\4".format(\2)'),
        
        # Pattern 3: f'...' with simple variable
        (r"f'([^']*)\{([^}:]+)\}([^']*)'", r"'\1{}\3'.format(\2)"),
        
        # Pattern 4: f'...' with format specifier
        (r"f'([^']*)\{([^}]+):([^}]+)\}([^']*)'", r"'\1{:\3}\4'.format(\2)"),
        
        # Pattern 5: List comprehension with f-strings
        (r'\[f["\']([^"\']*)\{([^}]+)\}([^"\']*)["\'] for', r'["\1{}\3".format(\2) for'),
        
        # Pattern 6: Multiple variables in one f-string
        (r'f"([^"]*)\{([^}:]+)\}([^"]*)\{([^}:]+)\}([^"]*)"', r'"\1{}\3{}\5".format(\2, \4)')
    ]
    
    modified = content
    for pattern, replacement in patterns:
        modified = re.sub(pattern, replacement, modified)
    
    return modified

def process_file(filename):
    try:
        filepath = Path(filename)
        if not filepath.exists():
            print("Error: File {} does not exist".format(filename))
            return
            
        # Create backup
        backup_path = filepath.with_suffix(filepath.suffix + '.bak')
        with open(filepath, 'r') as f:
            content = f.read()
        with open(backup_path, 'w') as f:
            f.write(content)
        
        # Fix f-strings
        modified = fix_fstrings(content)
        
        # Write back only if changes were made
        if modified != content:
            with open(filepath, 'w') as f:
                f.write(modified)
            print("Successfully processed {}".format(filename))
            print("Backup saved as {}".format(backup_path))
        else:
            print("No f-strings found in {}".format(filename))
            backup_path.unlink()  # Remove backup if no changes
        
    except Exception as e:
        print("Error processing {}: {}".format(filename, str(e)))

if __name__ == "__main__":
    if len(sys.argv) > 1:
        for filename in sys.argv[1:]:
            process_file(filename)
    else:
        process_file("T_sas_templates.yaml") 