from typing import List, Dict, Any, Optional, Generator, Tuple, Set
import re
import os
import logging
from dataclasses import dataclass, field
from pathlib import Path

# Configure logging
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
logger = logging.getLogger('PRDSASParser')

@dataclass
class SASComponent:
    """Represents a parsed SAS component."""
    type: str
    name: str
    content: str
    line_start: int
    line_end: int
    parent_component: Optional['SASComponent'] = None
    nested_components: List['SASComponent'] = field(default_factory=list)
    metadata: Dict[str, Any] = field(default_factory=dict)

class SASParser:
    """Parser for SAS code components with complete line tracking."""
    
    def __init__(self):
        """Initialize the SAS parser."""
        # Base patterns with priority order
        self.base_patterns = {
            'PROC_SQL': (r'proc\s+sql\s*;.*?(?:quit|run);', 10),
            'MACRO': (r'%macro\s+([^;(]+).*?%mend\s*(?:\1)?\s*;', 9),
            'PROC': (r'proc\s+(\w+).*?(?:run|quit);', 8),
            'DATA': (r'data\s+([^;]+);.*?run;', 7),
            'LIBNAME': (r'libname\s+([^;]+);', 6),
            'INCLUDE': (r'%include\s+([^;]+);', 5),
            'LET': (r'%let\s+([^;]+);', 4),
            'COMMENT': (r'/\*.*?\*/|^\s*\*[^;]*;', 3),
            'OPTIONS': (r'options\s+[^;]+;', 2)
        }

        # Advanced PROC patterns
        self.proc_patterns = {
            'PROC_REPORT': (r'proc\s+report\s+.*?(?=run;).*?run;', 10),
            'PROC_TABULATE': (r'proc\s+tabulate\s+.*?(?=run;).*?run;', 10),
            'PROC_SUMMARY': (r'proc\s+summary\s+.*?(?=run;).*?run;', 10),
            'PROC_MEANS': (r'proc\s+means\s+.*?(?=run;).*?run;', 10),
            'PROC_FREQ': (r'proc\s+freq\s+.*?(?=run;).*?run;', 10),
            'PROC_DATASETS': (r'proc\s+datasets\s+.*?(?:run|quit);', 10),
            'PROC_TEMPLATE': (r'proc\s+template\s+.*?(?:run|quit);', 10)
        }

        # Advanced macro patterns
        self.macro_patterns = {
            'MACRO_DEF': (r'%macro\s+([^;(]+)(?:\([^)]*\))?\s*;.*?%mend\s*(?:\1)?\s*;', 9),
            'MACRO_CALL': (r'%\w+(?:\([^)]*\))?;', 8),
            'MACRO_DO': (r'%do\s+.*?%end;', 8),
            'MACRO_IF': (r'%if\s+.*?(?:%then|%do).*?(?:%end|;)', 8),
            'MACRO_FUNCTION': (r'%function\s+.*?%mend;', 9)
        }

        # Data step patterns
        self.data_patterns = {
            'MERGE': (r'merge\s+[^;]+;', 7),
            'SET_BY': (r'set\s+.*?\s+by\s+.*?;', 7),
            'UPDATE': (r'update\s+.*?;', 7),
            'MODIFY': (r'modify\s+.*?;', 7),
            'BY_GROUP': (r'by\s+.*?;', 6),
            'WHERE': (r'where\s+.*?;', 6),
            'ARRAY': (r'array\s+.*?;', 6)
        }

        # Combine all patterns
        self.patterns = {
            **self.base_patterns,
            **self.proc_patterns,
            **self.macro_patterns,
            **self.data_patterns
        }
        
        # Compile patterns
        self.compiled_patterns = {
            name: (re.compile(pattern, re.IGNORECASE | re.DOTALL | re.MULTILINE), priority)
            for name, (pattern, priority) in self.patterns.items()
        }

    def parse_file(self, file_path: str, validate: bool = True) -> List[SASComponent]:
        """
        Parse a SAS file into components with complete coverage.
        
        Args:
            file_path: Path to SAS file
            validate: Whether to validate and ensure complete coverage
            
        Returns:
            List of SASComponent objects
        """
        try:
            with open(file_path, 'r', encoding='utf-8') as f:
                content = f.read()
                
            # Initial parsing
            components = self._parse_content(content, file_path)
            
            # Ensure complete coverage if validation is enabled
            if validate:
                components = self.ensure_complete_coverage(content, components)
                self._validate_coverage(content, components)
            
            # Process nested components
            components = self._process_nested_components(components)
            
            logger.info(f"Found {len(components)} components in {file_path}")
            return components
            
        except Exception as e:
            logger.error(f"Error parsing file {file_path}: {str(e)}")
            return []

    def _parse_content(self, content: str, file_path: str) -> List[SASComponent]:
        """Enhanced parse content with advanced component detection."""
        components = []
        line_offset = 1
        
        # Track file-level metadata
        file_metadata = {
            "file_path": str(Path(file_path).resolve()),
            "source_file": os.path.basename(file_path),
            "directory": os.path.dirname(file_path)
        }
        
        # Find all matches for all patterns
        matches = []
        for comp_type, (pattern, priority) in self.compiled_patterns.items():
            for match in pattern.finditer(content):
                start, end = match.span()
                matches.append((start, end, comp_type, priority, match))
        
        # Sort by start position and priority
        matches.sort(key=lambda x: (x[0], -x[3]))
        
        # Process matches while handling overlaps
        used_ranges = set()
        for start, end, comp_type, _, match in matches:
            # Check if this range overlaps with already processed components
            if any(start < r[1] and end > r[0] for r in used_ranges):
                continue
                
            line_start = content.count('\n', 0, start) + line_offset
            line_end = content.count('\n', 0, end) + line_offset
            
            # Extract component name
            name = ''
            if comp_type in ['PROC', 'DATA', 'MACRO']:
                try:
                    name = match.group(1).strip()
                except:
                    name = 'unnamed'
            
            component = SASComponent(
                type=comp_type,
                name=name,
                content=match.group(0),
                line_start=line_start,
                line_end=line_end,
                metadata=file_metadata.copy()
            )
            components.append(component)
            used_ranges.add((start, end))
        
        # After creating the component, analyze it
        for component in components:
            self._analyze_component(component)
        
        return components

    def ensure_complete_coverage(self, content: str, components: List[SASComponent]) -> List[SASComponent]:
        """
        Ensure all lines are captured in components.
        Add DEFAULT components for uncaptured code.
        """
        covered_lines = set()
        for comp in components:
            for line in range(comp.line_start, comp.line_end + 1):
                covered_lines.add(line)
        
        total_lines = content.count('\n') + 1
        uncovered_ranges = []
        
        # Find gaps in coverage
        for line in range(1, total_lines + 1):
            if line not in covered_lines:
                if not uncovered_ranges or uncovered_ranges[-1][1] != line - 1:
                    uncovered_ranges.append([line, line])
                else:
                    uncovered_ranges[-1][1] = line
        
        # Create DEFAULT components for uncovered ranges
        for start, end in uncovered_ranges:
            # Extract content for this range
            lines = content.split('\n')
            default_content = '\n'.join(lines[start-1:end])
            
            if default_content.strip():  # Only create component if content isn't empty
                component = SASComponent(
                    type='DEFAULT',
                    name=f'uncaptured_{start}_{end}',
                    content=default_content,
                    line_start=start,
                    line_end=end,
                    metadata={"coverage_type": "auto_generated"}
                )
                components.append(component)
        
        # Sort by line number
        components.sort(key=lambda x: x.line_start)
        return components

    def _process_nested_components(self, components: List[SASComponent]) -> List[SASComponent]:
        """Process and link nested components."""
        # Sort by line number
        components.sort(key=lambda x: (x.line_start, -x.line_end))
        
        # Find parent-child relationships
        for i, comp in enumerate(components):
            for potential_parent in components[:i]:
                if (comp.line_start > potential_parent.line_start and 
                    comp.line_end <= potential_parent.line_end):
                    comp.parent_component = potential_parent
                    potential_parent.nested_components.append(comp)
                    break
        
        # Return only top-level components
        return [c for c in components if c.parent_component is None]

    def _validate_coverage(self, content: str, components: List[SASComponent]) -> bool:
        """
        Validate that all lines are covered exactly once.
        
        Args:
            content: Original file content
            components: List of components
            
        Returns:
            bool: True if coverage is complete and valid
        """
        total_lines = content.count('\n') + 1
        coverage = [0] * total_lines
        
        for comp in components:
            for line in range(comp.line_start - 1, comp.line_end):
                coverage[line] += 1
        
        # Check for gaps or overlaps
        for line_num, count in enumerate(coverage, 1):
            if count == 0:
                logger.error(f"Line {line_num} is not covered by any component")
                return False
            elif count > 1:
                logger.error(f"Line {line_num} is covered by {count} components")
                return False
        
        return True

    def parse_directory(self, directory: str) -> Generator[List[SASComponent], None, None]:
        """Parse all SAS files in a directory."""
        try:
            directory_path = Path(directory)
            if not directory_path.exists():
                logger.error(f"Directory not found: {directory}")
                return
                
            for file_path in directory_path.glob('**/*.sas'):
                logger.info(f"Parsing {file_path}")
                components = self.parse_file(str(file_path))
                if components:
                    yield components
                    
        except Exception as e:
            logger.error(f"Error parsing directory {directory}: {str(e)}")
            return

    def extract_sql_statements(self, sql_component: SASComponent) -> List[Dict[str, Any]]:
        """
        Extract SQL statements from a PROC SQL component.
        
        Args:
            sql_component: PROC SQL component
            
        Returns:
            List of dictionaries containing SQL statement information
        """
        if sql_component.type != 'PROC_SQL':
            return []
            
        statements = []
        content = sql_component.content
        
        # Remove PROC SQL and QUIT
        content = re.sub(r'proc\s+sql\s*;', '', content, flags=re.IGNORECASE)
        content = re.sub(r'quit\s*;', '', content, flags=re.IGNORECASE)
        
        # Split into individual statements
        for stmt in content.split(';'):
            stmt = stmt.strip()
            if not stmt:
                continue
                
            # Determine statement type and extract key information
            stmt_info = {
                'content': stmt,
                'type': self._get_sql_statement_type(stmt)
            }
            statements.append(stmt_info)
            
        return statements

    def _get_sql_statement_type(self, statement: str) -> str:
        """Determine the type of SQL statement."""
        statement = statement.strip().lower()
        if statement.startswith('create'):
            return 'create'
        elif statement.startswith('select'):
            return 'select'
        elif statement.startswith('insert'):
            return 'insert'
        elif statement.startswith('update'):
            return 'update'
        elif statement.startswith('delete'):
            return 'delete'
        else:
            return 'other'

    def _analyze_component(self, component: SASComponent) -> Dict[str, Any]:
        """Analyze component for complexity and structure."""
        analysis = {
            'complexity': 0,
            'nested_macros': [],
            'data_dependencies': set(),
            'macro_variables': set()
        }

        try:
            if component.type.startswith('PROC_'):
                analysis['complexity'] = self._analyze_proc_complexity(component)
            elif component.type.startswith('MACRO'):
                analysis['complexity'] = self._analyze_macro_complexity(component)
                analysis['macro_variables'] = self._extract_macro_variables(component)
            elif component.type == 'DATA':
                analysis['complexity'] = self._analyze_data_complexity(component)

            component.metadata['analysis'] = analysis
            
        except Exception as e:
            logger.warning(f"Error analyzing component {component.type}: {str(e)}")

        return analysis

    def _analyze_proc_complexity(self, component: SASComponent) -> int:
        """Analyze PROC step complexity."""
        complexity = 1
        content = component.content.lower()
        
        # Check for complex features
        if 'by ' in content: complexity += 1
        if 'where ' in content: complexity += 1
        if 'having ' in content: complexity += 2
        if 'class ' in content: complexity += 1
        if 'merge ' in content: complexity += 2
        
        return complexity

    def _analyze_macro_complexity(self, component: SASComponent) -> int:
        """Analyze macro complexity."""
        complexity = 1
        content = component.content.lower()
        
        # Check for complex features
        if '%do ' in content: complexity += 1
        if '%if ' in content: complexity += 1
        if '%let ' in content: complexity += 1
        if 'call symput' in content: complexity += 2
        
        return complexity

    def _extract_macro_variables(self, component: SASComponent) -> Set[str]:
        """Extract macro variables used in component."""
        variables = set()
        content = component.content
        
        # Find macro variable references
        for match in re.finditer(r'&(\w+)\.?', content):
            variables.add(match.group(1))
            
        return variables

    def _analyze_data_complexity(self, component: SASComponent) -> int:
        """Analyze data step complexity."""
        complexity = 1
        content = component.content.lower()
        
        # Check for complex features
        if 'merge ' in content: complexity += 2
        if 'set ' in content: complexity += 1
        if 'update ' in content: complexity += 1
        if 'modify ' in content: complexity += 1
        if 'by ' in content: complexity += 1
        if 'where ' in content: complexity += 1
        if 'array ' in content: complexity += 1
        
        return complexity 