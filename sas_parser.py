from typing import List, Dict, Any, Generator
from dataclasses import dataclass
import re
import os
from pathlib import Path

@dataclass
class SASComponent:
    type: str  # PROC, DATA, MACRO
    name: str
    content: str
    line_start: int
    line_end: int
    dependencies: List[str] = None
    metadata: Dict[str, Any] = None

class SASParser:
    # Additional SAS component types
    COMPONENT_TYPES = {
        'PROC': r'^PROC\s+(\w+)',
        'DATA': r'^DATA\s+([^;(\s]+)',
        'MACRO': r'^%MACRO\s+([^(;\s]+)',
        'LIBNAME': r'^LIBNAME\s+([^;(\s]+)',
        'OPTIONS': r'^OPTIONS\s+',
        'FILENAME': r'^FILENAME\s+([^;(\s]+)',
        '%INCLUDE': r'^%INCLUDE\s+',
        'ODS': r'^ODS\s+',
        'GOPTIONS': r'^GOPTIONS\s+',
        'TITLE': r'^TITLE\d*\s+',
        'FOOTNOTE': r'^FOOTNOTE\d*\s+',
        'SYMBOL': r'^SYMBOL\d*\s+',
        'AXIS': r'^AXIS\d*\s+',
        'PATTERN': r'^PATTERN\d*\s+',
        'LEGEND': r'^LEGEND\d*\s+'
    }

    def __init__(self):
        self.components: List[SASComponent] = []
        
    def parse_directory(self, directory_path: str) -> Generator[List[SASComponent], None, None]:
        """Parse all SAS files in a directory and its subdirectories."""
        directory = Path(directory_path)
        
        # Walk through directory
        for file_path in directory.rglob("*.sas"):
            try:
                components = self.parse_file(str(file_path))
                yield components
            except Exception as e:
                print(f"Error parsing file {file_path}: {str(e)}")
                continue

    def parse_file(self, file_path: str) -> List[SASComponent]:
        """Parse a SAS file and extract components."""
        with open(file_path, 'r', encoding='utf-8', errors='ignore') as file:
            content = file.readlines()
            
        self.components = []
        current_component = None
        in_comment_block = False
        current_content = []
        
        # Get absolute file path for metadata
        abs_file_path = os.path.abspath(file_path)
        
        for i, line in enumerate(content, 1):
            line = line.strip()
            
            # Handle comment blocks
            if '/*' in line and not line[:line.find('/*')].strip():
                in_comment_block = True
            if '*/' in line:
                in_comment_block = False
                continue
            if in_comment_block:
                continue
            if not line or line.startswith('*'):  # Skip empty lines and single-line comments
                continue
                
            # Add line to current content
            current_content.append(line)
            
            # Check for all component types
            for comp_type, pattern in self.COMPONENT_TYPES.items():
                if re.match(pattern, line.upper()):
                    if current_component:
                        current_component.line_end = i - 1
                        current_component.content = '\n'.join(current_content[:-1])
                        self.components.append(current_component)
                        current_content = [line]
                    
                    name = self._extract_name(line, pattern) if comp_type in ['PROC', 'DATA', 'MACRO', 'LIBNAME', 'FILENAME'] else ''
                    current_component = SASComponent(
                        type=comp_type,
                        name=name,
                        content="",  # Will be set when component ends
                        line_start=i,
                        line_end=None,
                        dependencies=self._extract_dependencies(line),
                        metadata={
                            "file_path": abs_file_path,
                            "source_file": os.path.basename(file_path),
                            "directory": os.path.dirname(abs_file_path)
                        }
                    )
                    break
            
            # Check for end of components
            elif self._is_component_end(line):
                if current_component:
                    current_component.line_end = i
                    current_component.content = '\n'.join(current_content)
                    current_component.dependencies.extend(self._extract_dependencies(current_component.content))
                    self.components.append(current_component)
                    current_component = None
                current_content = []
        
        # Add last component if exists
        if current_component:
            current_component.line_end = len(content)
            current_component.content = '\n'.join(current_content)
            current_component.dependencies.extend(self._extract_dependencies(current_component.content))
            self.components.append(current_component)
        
        return self.components

    def _extract_name(self, line: str, pattern: str) -> str:
        """Extract component name using regex pattern."""
        match = re.search(pattern, line, re.IGNORECASE)
        return match.group(1) if match else ""

    def _extract_dependencies(self, content: str) -> List[str]:
        """Extract dependencies from component content."""
        dependencies = set()
        
        # Dataset references
        dataset_refs = re.findall(r'(?:DATA|SET|MERGE|UPDATE|MODIFY)=?\s*([a-zA-Z_][a-zA-Z0-9_]*\.?[a-zA-Z0-9_]*)', content.upper())
        dependencies.update(dataset_refs)
        
        # Macro calls
        macro_calls = re.findall(r'%([a-zA-Z_][a-zA-Z0-9_]*)\s*[\(;]', content)
        dependencies.update(macro_calls)
        
        # Library references
        libname_refs = re.findall(r'LIBNAME\s+([a-zA-Z_][a-zA-Z0-9_]*)', content.upper())
        dependencies.update(libname_refs)
        
        # File references
        filename_refs = re.findall(r'FILENAME\s+([a-zA-Z_][a-zA-Z0-9_]*)', content.upper())
        dependencies.update(filename_refs)
        
        return list(dependencies)

    def _is_component_end(self, line: str) -> bool:
        """Check if line indicates end of component."""
        end_patterns = [
            r'^RUN;',
            r'^QUIT;',
            r'^%MEND',
            r'^ENDCOMP;',
            r'^END;',
            r'^PROC\s+',  # New PROC starts
            r'^DATA\s+',   # New DATA step starts
            r'^%MACRO\s+'  # New MACRO starts
        ]
        return any(re.match(pattern, line.upper()) for pattern in end_patterns)

    def extract_dependencies(self, component: SASComponent) -> List[str]:
        """Extract dependencies from a component's content."""
        dependencies = []
        content = component.content.upper()
        
        # Look for dataset references
        dataset_refs = re.findall(r'DATA=(\w+\.?\w+)', content)
        dependencies.extend(dataset_refs)
        
        # Look for macro calls
        macro_calls = re.findall(r'%(\w+)[\s(]', content)
        dependencies.extend(macro_calls)
        
        return list(set(dependencies))
    
    def extract_procedures(self, tree) -> List[SASComponent]:
        """Extract PROC statements and their content."""
        pass
    
    def extract_data_steps(self, tree) -> List[SASComponent]:
        """Extract DATA steps and their transformations."""
        pass
    
    def extract_macros(self, tree) -> List[SASComponent]:
        """Extract macro definitions and their content."""
        pass
    
    def extract_variables(self, tree) -> List[str]:
        """Extract variable declarations."""
        pass
    
    def extract_statistical_ops(self, tree) -> List[SASComponent]:
        """Extract statistical operations and their parameters."""
        pass