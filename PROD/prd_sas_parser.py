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
    
    # Class-level configuration
    INCLUDE_COMMENTS = False  # Set default here
    
    def __init__(self):
        """Initialize the SAS parser."""
        # Base patterns with priority order
        self.base_patterns = {
            'PROC_SQL': (r'proc\s+sql\s*;(?:(?!/\*|\*/).)*?(?:quit|run)\s*;', 10),
            'MACRO': (r'%macro\s+([a-zA-Z_]\w*)(?:\s*\([^)]*\))?\s*;.*?%mend\s*(?:\1)?\s*;', 9),
            'PROC': (r'proc\s+(\w+)(?:\s+[^;]*)?;.*?(?:run|quit)\s*;', 8),
            'DATA': (r'data\s+([^;]+?)(?:\s+[^;]*)?;.*?run\s*;', 7),
            'LIBNAME': (r'libname\s+([a-zA-Z_]\w*)\s+[^;]+;', 6),
            'INCLUDE': (r'%include\s+([^;]+);', 5),
            'LET': (r'%let\s+([a-zA-Z_]\w*)\s*=\s*[^;]+;', 4)
        }
        
        # Only add comment patterns if INCLUDE_COMMENTS is True
        if self.INCLUDE_COMMENTS:
            self.base_patterns.update({
                'BLOCK_COMMENT': (r'/\*[^*]*\*+(?:[^/*][^*]*\*+)*/', 3),
                'LINE_COMMENT': (r'^\s*\*[^;]*;', 2)
            })
            
        self.base_patterns['OPTIONS'] = (r'options\s+[^;]+;', 1)

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
            'MACRO_CALL': (r'%(\w+)(?:\([^)]*\))?;', 8),  # Capture macro name
            'MACRO_END': (r'%mend\s*(\w+)?\s*;', 8),      # Optional macro name
            'MACRO_DO': (r'%do\s+.*?%end;', 8),
            'MACRO_IF': (r'%if\s+.*?(?:%then|%do).*?(?:%end|;)', 8)
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
        """Enhanced parse content with macro validation."""
        components = []
        line_offset = 1
        macro_stack = []
        
        # Ensure resolved file path
        resolved_path = str(Path(file_path).resolve())
        file_metadata = {
            "file_path": resolved_path,
            "source_file": os.path.basename(resolved_path),
            "directory": os.path.dirname(resolved_path)
        }
        
        # Split content into lines to track indentation
        content_lines = content.splitlines()
        
        # Find all matches for all patterns
        matches = []
        comment_matches = []  # Separate list for comments
        
        for comp_type, (pattern, priority) in self.compiled_patterns.items():
            if comp_type in ['BLOCK_COMMENT', 'LINE_COMMENT']:
                if self.INCLUDE_COMMENTS:
                    # Store comments separately
                    for match in pattern.finditer(content):
                        comment_matches.append((match.start(), match.end(), match.group(0)))
                continue
            
            for match in pattern.finditer(content):
                start, end = match.span()
                matches.append((start, end, comp_type, priority, match))
        
        # Sort matches by position
        matches.sort(key=lambda x: x[0])
        
        # Process matches and associate comments
        for start, end, comp_type, priority, match in matches:
            # Find any comments that belong to this component
            associated_comments = []
            
            if self.INCLUDE_COMMENTS:
                for c_start, c_end, c_content in comment_matches[:]:  # Use slice to allow modification
                    if c_end <= start:
                        between_content = content[c_end:start].strip()
                        if not between_content:
                            associated_comments.append(c_content)
                            comment_matches.remove((c_start, c_end, c_content))

            # Get component content including comments
            if associated_comments:
                component_content = '\n'.join(associated_comments + [match.group(0)])
                line_start = content.count('\n', 0, content.find(associated_comments[0])) + line_offset
            else:
                component_content = match.group(0)
                line_start = content.count('\n', 0, start) + line_offset
            
            # Fix line_end calculation
            line_end = content.count('\n', 0, end) + line_offset
            
            # Extract component name
            name = ''
            if comp_type in ['PROC', 'DATA', 'MACRO', 'LIBNAME']:
                try:
                    name = match.group(1).strip()
                except:
                    name = f"{comp_type.lower()}_{line_start}"
            else:
                name = f"{comp_type.lower()}_{line_start}"
            
            # Handle macro components
            if comp_type == 'MACRO':
                macro_stack.append(name)
            elif comp_type == 'MEND':
                if macro_stack:
                    macro_stack.pop()
            
            # Create component
            component = SASComponent(
                type=comp_type,
                name=name,
                content=component_content,
                line_start=line_start,
                line_end=line_end,
                metadata={
                    **file_metadata,
                    "parent_info": {"parent_name": None, "parent_type": None},
                    "nested_info": {"has_nested": False, "nested_count": 0, "nested_names": []}
                }
            )
            
            components.append(component)
        
        # Validate macro structure
        if macro_stack:
            logger.warning(f"Unclosed macros found: {macro_stack}")

        # After creating components, update their metadata in _process_nested_components
        return components

    def ensure_complete_coverage(self, content: str, components: List[SASComponent]) -> List[SASComponent]:
        """Ensure all lines are captured in components with preserved indentation."""
        content_lines = content.splitlines()
        covered_lines = set()
        
        # Get file metadata from existing components to ensure consistency
        file_metadata = next((
            comp.metadata for comp in components 
            if "file_path" in comp.metadata
        ), {})
        
        for comp in components:
            for line in range(comp.line_start, comp.line_end + 1):
                covered_lines.add(line)
        
        total_lines = len(content_lines)
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
            # Extract content for this range with preserved indentation
            range_lines = content_lines[start-1:end]
            if range_lines:
                # Find minimum indentation in non-empty lines
                indents = [len(line) - len(line.lstrip()) 
                          for line in range_lines if line.strip()]
                min_indent = min(indents) if indents else 0
                
                # Preserve relative indentation
                default_content = '\n'.join(
                    line[min_indent:] if line.strip() else line 
                    for line in range_lines
                )
                
                if default_content.strip():  # Only create component if content isn't empty
                    component = SASComponent(
                        type='DEFAULT',
                        name=f'uncaptured_{start}_{end}',
                        content=default_content,
                        line_start=start,
                        line_end=end,
                        metadata={
                            **file_metadata,  # Include file metadata
                            "coverage_type": "auto_generated",
                            "original_indentation": min_indent,
                            "parent_info": {
                                "parent_name": None,
                                "parent_type": None
                            },
                            "nested_info": {
                                "has_nested": False,
                                "nested_count": 0,
                                "nested_names": []
                            }
                        }
                    )
                    components.append(component)
        
        # Sort by line number
        components.sort(key=lambda x: x.line_start)
        return components

    def _process_nested_components(self, components: List[SASComponent]) -> List[SASComponent]:
        """Process and link nested components with enhanced metadata."""
        # Sort by line number and length of content (longer components first for proper nesting)
        components.sort(key=lambda x: (x.line_start, -len(x.content), -x.line_end))
        
        # Track macro nesting depth
        macro_depth = {}
        
        # Find parent-child relationships and update metadata
        for i, comp in enumerate(components):
            for potential_parent in components[:i]:
                if (comp.line_start > potential_parent.line_start and 
                    comp.line_end <= potential_parent.line_end):
                    # Set parent-child relationship
                    comp.parent_component = potential_parent
                    potential_parent.nested_components.append(comp)
                    
                    # Track macro nesting
                    if comp.type == 'MACRO':
                        parent_depth = macro_depth.get(potential_parent.name, 0)
                        macro_depth[comp.name] = parent_depth + 1
                    
                    # Update metadata
                    comp.metadata["parent_info"] = {
                        "parent_name": potential_parent.name,
                        "parent_type": potential_parent.type,
                        "nesting_depth": macro_depth.get(comp.name, 0)
                    }
                    
                    # Update parent's nested info
                    potential_parent.metadata["nested_info"].update({
                        "has_nested": True,
                        "nested_count": len(potential_parent.nested_components),
                        "nested_names": [c.name for c in potential_parent.nested_components],
                        "nested_types": [c.type for c in potential_parent.nested_components]
                    })
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

    def _classify_comment(self, content: str) -> str:
        """Determine comment type and structure."""
        if '\n' in content:
            return 'MULTILINE_COMMENT'
        if content.startswith('/*') and content.endswith('*/'):
            return 'INLINE_COMMENT'
        return 'LINE_COMMENT'

    def _extract_comment_metadata(self, comment_content: str) -> Dict[str, Any]:
        """Extract comment-specific metadata."""
        return {
            "comment_type": self._classify_comment(comment_content),
            "is_multiline": '\n' in comment_content,
            "comment_lines": len(comment_content.splitlines()),
            "is_documentation": bool(re.search(r'@\w+|param|return|description', 
                                             comment_content, re.I))
        }

    def _process_comment(self, content: str, line_start: int, original_lines: List[str]) -> Tuple[str, Dict[str, Any]]:
        """Process and preserve comment structure."""
        lines = content.splitlines()
        comment_type = self._classify_comment(content)
        
        if comment_type == 'MULTILINE_COMMENT':
            # Get original lines with indentation
            comment_lines = original_lines[line_start-1:line_start-1+len(lines)]
            # Preserve original formatting completely
            preserved_content = '\n'.join(comment_lines)
        else:
            # For single-line comments, preserve original line
            preserved_content = original_lines[line_start-1]
            
        # Extract comment metadata
        comment_metadata = self._extract_comment_metadata(content)
        
        return preserved_content, comment_metadata

    def _create_base_metadata(self, file_metadata: Dict[str, Any]) -> Dict[str, Any]:
        """Create consistent base metadata structure."""
        return {
            **file_metadata.copy(),
            "parent_info": {
                "parent_name": None,
                "parent_type": None
            },
            "nested_info": {
                "has_nested": False,
                "nested_count": 0,
                "nested_names": []
            },
            "original_indentation": 0,
            "line_info": {
                "start": 0,
                "end": 0
            }
        } 