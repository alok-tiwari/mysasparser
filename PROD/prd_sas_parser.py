from typing import List, Dict, Any, Optional, Generator, Tuple, Set
import re
import os
import logging
from dataclasses import dataclass, field
from pathlib import Path

# Configure logging
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
logger = logging.getLogger('PRDSASParser')

def preprocess_sas_content(content):
    """
    Preprocess SAS content to handle comments properly.
    This function removes comments when INCLUDE_COMMENTS is False to prevent them
    from being incorrectly matched by other patterns.
    
    Args:
        content (str): The original SAS content
        
    Returns:
        str: Processed content with comments handled
    """
    # If we're including comments, return the original content
    if SASParser.INCLUDE_COMMENTS:
        return content
    
    # Otherwise, remove comment blocks before pattern matching
    # Remove block comments (/* */)
    content_no_block_comments = re.sub(r'/\*[^*]*\*+(?:[^/*][^*]*\*+)*/', '', content, flags=re.DOTALL)
    
    # Remove line comments (* ;)
    content_no_comments = re.sub(r'^\s*\*[^;]*;', '', content_no_block_comments, flags=re.MULTILINE)
    
    return content_no_comments

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
            'OPTIONS': (r'options\s+[^;]+;', 1)
        }
        
        # Comment and single-line patterns - only added when INCLUDE_COMMENTS is True
        self.comment_and_single_line_patterns = {
            'BLOCK_COMMENT': (r'/\*[^*]*\*+(?:[^/*][^*]*\*+)*/', 3),
            'LINE_COMMENT': (r'^\s*\*[^;]*;', 2),
            'SINGLE_LINE_MACRO': (r'%(?!macro\s+)(\w+)(?:\([^)]*\))?\s*;', 1)  # Matches single-line macro calls but not macro definitions
        }

        # Macro patterns - only added when INCLUDE_COMMENTS is True
        self.macro_call_patterns = {
            'MACRO_CALL': (r'%(\w+)(?:\([^)]*\))?;', 8),
            'MACRO_END': (r'%mend\s*(\w+)?\s*;', 8),
            'MACRO_DO': (r'%do\s+.*?%end;', 8),
            'MACRO_IF': (r'%if\s+.*?(?:%then|%do).*?(?:%end|;)', 8)
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

        # Combine patterns based on INCLUDE_COMMENTS setting
        self.patterns = {**self.base_patterns}
        if self.INCLUDE_COMMENTS:
            self.patterns.update(self.comment_and_single_line_patterns)
        
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
        
        # Preprocess content to handle comments properly when INCLUDE_COMMENTS is False
        processed_content = preprocess_sas_content(content)
        
        # Ensure resolved file path
        resolved_path = str(Path(file_path).resolve())
        file_metadata = {
            "file_path": resolved_path,
            "source_file": os.path.basename(resolved_path),
            "directory": os.path.dirname(resolved_path)
        }
        
        # Split content into lines to track indentation
        content_lines = content.splitlines()
        
        # First, handle special case for macros with proper nesting
        macro_components = self._extract_macro_hierarchy(content, content_lines, file_metadata)
        if macro_components:
            components.extend(macro_components)
        
        # Find all matches for all patterns except MACRO (already handled)
        matches = []
        
        # Only process patterns that are currently compiled (based on INCLUDE_COMMENTS)
        for comp_type, (pattern, priority) in self.compiled_patterns.items():
            if comp_type == 'MACRO':
                continue  # Skip macro pattern as we handled it separately
            
            # Use processed_content for pattern matching when not including comments
            content_to_search = processed_content if not self.INCLUDE_COMMENTS else content
            
            for match in pattern.finditer(content_to_search):
                start, end = match.span()
                
                # Map positions back to original content for proper line tracking
                # This is important when using preprocessed content
                if not self.INCLUDE_COMMENTS and content_to_search != content:
                    # This is a simplified approach - for a complete solution, 
                    # a more sophisticated mapping would be needed
                    original_match_text = match.group(0)
                    real_start = content.find(original_match_text)
                    if real_start >= 0:
                        real_end = real_start + len(original_match_text)
                        start, end = real_start, real_end
                
                # Skip matches that are entirely within comment blocks if INCLUDE_COMMENTS is False
                if not self.INCLUDE_COMMENTS and self._is_within_comment(content, start, end):
                    continue
                
                # Skip matches that overlap with macro components we already extracted
                if any(self._ranges_overlap(start, end, comp.line_start, comp.line_end, content)
                      for comp in macro_components):
                    continue
                
                matches.append((start, end, comp_type, priority, match))
        
        # Sort matches by position
        matches.sort(key=lambda x: x[0])
        
        # Process matches
        for start, end, comp_type, priority, match in matches:
            # Get component content
            component_content = match.group(0)
            line_start = content.count('\n', 0, start) + line_offset
            line_end = content.count('\n', 0, end) + line_offset
            
            # Skip if this appears to be a comment block and INCLUDE_COMMENTS is False
            if not self.INCLUDE_COMMENTS and self._seems_like_comment(component_content):
                continue
            
            # Extract component name
            name = ''
            if comp_type in ['PROC', 'DATA', 'LIBNAME']:
                try:
                    name = match.group(1).strip()
                except:
                    name = f"{comp_type.lower()}_{line_start}"
            else:
                name = f"{comp_type.lower()}_{line_start}"
            
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
        
        return components

    def _is_within_comment(self, content: str, start: int, end: int) -> bool:
        """
        Check if a code segment is entirely within a comment block.
        Uses the same robust patterns as the preprocessing function.
        
        Args:
            content: The full content string
            start: Start position of the segment
            end: End position of the segment
            
        Returns:
            bool: True if the segment is within a comment block
        """
        if self.INCLUDE_COMMENTS:
            return False  # No need to check when including comments
            
        # Find all /* */ style comment blocks
        block_comment_pattern = r'/\*[^*]*\*+(?:[^/*][^*]*\*+)*/'
        comment_blocks = []
        
        for match in re.finditer(block_comment_pattern, content, re.DOTALL):
            comment_blocks.append(match.span())
        
        # Find all * ; style line comments
        line_comment_pattern = r'^\s*\*[^;]*;'
        for match in re.finditer(line_comment_pattern, content, re.MULTILINE):
            comment_blocks.append(match.span())
        
        # Check if the given range is entirely within any comment block
        for comment_start, comment_end in comment_blocks:
            if start >= comment_start and end <= comment_end:
                return True
                
        # Check if the segment itself appears to be a comment
        segment = content[start:end]
        return self._seems_like_comment(segment)

    def ensure_complete_coverage(self, content: str, components: List[SASComponent]) -> List[SASComponent]:
        """
        Ensure all lines are captured in components with preserved indentation.
        Handles comments based on INCLUDE_COMMENTS setting.
        
        Args:
            content: The full content string
            components: List of existing components
            
        Returns:
            List of components with complete coverage
        """
        content_lines = content.splitlines()
        covered_lines = set()
        
        # Get file metadata from existing components to ensure consistency
        file_metadata = next((
            comp.metadata for comp in components 
            if "file_path" in comp.metadata
        ), {})
        
        # Mark all lines covered by existing components
        for comp in components:
            for line in range(comp.line_start, comp.line_end + 1):
                covered_lines.add(line)
        
        # Preprocess to identify comment lines when not including comments
        comment_lines = set()
        if not self.INCLUDE_COMMENTS:
            in_comment_block = False
            for i, line in enumerate(content_lines, 1):
                stripped = line.strip()
                
                # Check for block comments
                if '/*' in line and '*/' in line and not in_comment_block:
                    # Single line block comment
                    comment_lines.add(i)
                elif '/*' in line and not in_comment_block:
                    in_comment_block = True
                    comment_lines.add(i)
                elif '*/' in line and in_comment_block:
                    in_comment_block = False
                    comment_lines.add(i)
                elif in_comment_block:
                    comment_lines.add(i)
                # Check for line comments
                elif stripped.startswith('*') and ';' in stripped:
                    comment_lines.add(i)
                # Check for single line macro calls
                elif stripped.startswith('%') and stripped.endswith(';') and '%macro' not in stripped.lower() and '%mend' not in stripped.lower():
                    comment_lines.add(i)
        
        total_lines = len(content_lines)
        uncovered_ranges = []
        
        # Find gaps in coverage
        line = 1
        current_range_start = None
        
        while line <= total_lines:
            if line not in covered_lines:
                # Skip comment lines when not including comments
                if not self.INCLUDE_COMMENTS and line in comment_lines:
                    line += 1
                    continue
                
                # Start a new range or continue current
                if current_range_start is None:
                    current_range_start = line
            else:
                # End current range if exists
                if current_range_start is not None:
                    uncovered_ranges.append((current_range_start, line - 1))
                    current_range_start = None
            
            line += 1
        
        # Handle final range if exists
        if current_range_start is not None:
            uncovered_ranges.append((current_range_start, total_lines))
        
        # Create DEFAULT components for uncovered ranges
        for start, end in uncovered_ranges:
            # Extract content for this range with preserved indentation
            range_lines = content_lines[start-1:end]
            if range_lines:
                # Skip ranges that are just comments when not including comments
                if not self.INCLUDE_COMMENTS:
                    all_comments = True
                    range_content = '\n'.join(range_lines)
                    if not self._seems_like_comment(range_content):
                        all_comments = False
                    if all_comments:
                        continue
                
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
        components.sort(key=lambda x: (x.line_start, -(x.line_end - x.line_start), -x.line_end))
        
        # Ensure macros are processed according to their nesting structure
        components_by_line = {comp.line_start: comp for comp in components}
        macro_stack = []
        
        # First pass to correctly identify macro nesting
        for comp in sorted(components, key=lambda x: x.line_start):
            if comp.type == 'MACRO':
                # Get the macro name from the content
                macro_name_match = re.search(r'%macro\s+([a-zA-Z_]\w*)', comp.content, re.IGNORECASE)
                if macro_name_match:
                    macro_name = macro_name_match.group(1)
                    comp.name = macro_name
                    macro_stack.append((macro_name, comp))
            
            # Check for macro end markers
            macro_end_matches = re.finditer(r'%mend\s*(\w*)\s*;', comp.content, re.IGNORECASE)
            for macro_end in macro_end_matches:
                ended_macro = macro_end.group(1).strip() if macro_end.group(1) else None
                if macro_stack and (not ended_macro or ended_macro == macro_stack[-1][0]):
                    macro_stack.pop()
        
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

    def _ranges_overlap(self, start1, end1, line_start, line_end, content):
        """Check if character-based range overlaps with line-based range."""
        line_start_char = content.find('\n', 0, start1) + 1 if start1 > 0 else 0
        line_end_char = content.rfind('\n', 0, end1) + 1 if end1 > 0 else 0
        
        return (line_start <= content.count('\n', 0, start1) + 1 <= line_end or 
                line_start <= content.count('\n', 0, end1) + 1 <= line_end)

    def _extract_macro_hierarchy(self, content, content_lines, file_metadata):
        """Extract macros with proper nesting hierarchy using a stack-based approach."""
        components = []
        macro_stack = []
        
        # Preprocess content for macro detection when INCLUDE_COMMENTS is False
        if not self.INCLUDE_COMMENTS:
            # For macro detection in preprocessed content, we need to preserve line numbers
            # Replace comment blocks with empty lines to maintain line count
            processed_lines = []
            in_comment = False
            
            for line in content_lines:
                stripped = line.strip()
                
                # Handle block comments
                if '/*' in line and '*/' in line:
                    # Comment begins and ends on same line - replace with empty line
                    processed_lines.append('')
                    continue
                elif '/*' in line:
                    in_comment = True
                    processed_lines.append('')
                    continue
                elif '*/' in line:
                    in_comment = False
                    processed_lines.append('')
                    continue
                elif in_comment:
                    processed_lines.append('')
                    continue
                    
                # Handle line comments
                if stripped.startswith('*') and ';' in stripped:
                    processed_lines.append('')
                    continue
                    
                # Non-comment line
                processed_lines.append(line)
                
            # Use processed content lines for macro detection
            analysis_lines = processed_lines
        else:
            # If including comments, use original content
            analysis_lines = content_lines
        
        # First, find all macro start and end positions
        macro_starts = []  # (line_num, macro_name, is_start)
        in_comment = False
        
        for i, line in enumerate(analysis_lines):
            line_num = i + 1
            stripped = line.strip()
            
            if not stripped:
                continue  # Skip empty lines
            
            # Find macro definitions
            if re.search(r'^\s*%macro\s+(\w+)', stripped, re.IGNORECASE):
                macro_name = re.search(r'^\s*%macro\s+(\w+)', stripped, re.IGNORECASE).group(1)
                macro_starts.append((line_num, macro_name, True))
            
            # Find macro ends
            if re.search(r'^\s*%mend\s*(\w*)', stripped, re.IGNORECASE):
                mend_match = re.search(r'^\s*%mend\s*(\w*)', stripped, re.IGNORECASE)
                macro_name = mend_match.group(1).strip() if mend_match.group(1) else None
                macro_starts.append((line_num, macro_name, False))
        
        # Process the macro hierarchy using a stack
        open_macros = []
        macro_ranges = []  # (start_line, end_line, macro_name, parent_name)
        
        for line_num, macro_name, is_start in macro_starts:
            if is_start:
                parent_name = open_macros[-1][1] if open_macros else None
                open_macros.append((line_num, macro_name))
            else:
                if not open_macros:
                    continue  # Unmatched %mend
                
                start_line, start_name = open_macros.pop()
                # If macro_name is specified, ensure it matches
                if macro_name and macro_name != start_name:
                    # This is an unmatched %mend, ignore it
                    open_macros.append((start_line, start_name))
                    continue
                
                parent_name = open_macros[-1][1] if open_macros else None
                macro_ranges.append((start_line, line_num, start_name, parent_name))
        
        # Create components for each macro range
        for start_line, end_line, macro_name, parent_name in macro_ranges:
            # Extract content with preserved indentation
            macro_content = '\n'.join(content_lines[start_line-1:end_line])
            
            component = SASComponent(
                type='MACRO',
                name=macro_name,
                content=macro_content,
                line_start=start_line,
                line_end=end_line,
                metadata={
                    **file_metadata,
                    "parent_info": {
                        "parent_name": parent_name,
                        "parent_type": "MACRO" if parent_name else None
                    },
                    "nested_info": {
                        "has_nested": False,
                        "nested_count": 0, 
                        "nested_names": []
                    }
                }
            )
            components.append(component)
        
        # Process nested components by updating metadata
        for comp in components:
            nested_comps = []
            for other_comp in components:
                if (other_comp.metadata["parent_info"]["parent_name"] == comp.name and
                    other_comp != comp):
                    nested_comps.append(other_comp)
                
            if nested_comps:
                comp.nested_components = nested_comps
                comp.metadata["nested_info"].update({
                    "has_nested": True,
                    "nested_count": len(nested_comps),
                    "nested_names": [c.name for c in nested_comps]
                })
        
        # Only return top-level macros
        return [c for c in components if c.metadata["parent_info"]["parent_name"] is None]

    def _seems_like_comment(self, content: str) -> bool:
        """Check if the content appears to be primarily a comment block."""
        # Check if content starts with comment markers
        if content.lstrip().startswith('/*') or content.lstrip().startswith('*'):
            return True
            
        # Check if most of the content is within comment blocks
        comment_patterns = [
            r'/\*.*?\*/',  # Block comments
            r'^\s*\*[^;]*;'  # Line comments
        ]
        
        content_length = len(content)
        comment_length = 0
        
        for pattern in comment_patterns:
            for match in re.finditer(pattern, content, re.DOTALL | re.MULTILINE):
                comment_length += len(match.group(0))
        
        # If more than 50% is comments, consider it a comment block
        return comment_length > content_length * 0.5 