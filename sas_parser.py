from typing import List, Dict, Any, Generator, Optional, Tuple, Set
from dataclasses import dataclass, field
import re
import os
from pathlib import Path
import logging
from collections import defaultdict

# Set up logging
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
logger = logging.getLogger('SASParser')

@dataclass
class SASComponent:
    type: str  # PROC, DATA, MACRO, etc.
    name: str
    content: str
    line_start: int
    line_end: int
    dependencies: List[str] = field(default_factory=list)
    metadata: Dict[str, Any] = field(default_factory=dict)
    parent: Optional['SASComponent'] = None
    children: List['SASComponent'] = field(default_factory=list)
    macro_variables: Dict[str, str] = field(default_factory=dict)

@dataclass
class SQLStatement:
    statement_type: str  # SELECT, INSERT, UPDATE, etc.
    content: str
    tables: List[str] = field(default_factory=list)
    line_start: int = 0
    line_end: int = 0

class SASParser:
    # Comprehensive SAS component types with improved regex patterns
    COMPONENT_TYPES = {
        # Core processing components
        'PROC': r'^PROC\s+(\w+)',
        'DATA': r'^DATA\s+([^;(\s]+)',
        'MACRO': r'^%MACRO\s+([^(;\s]+)',
        
        # Resource definitions
        'LIBNAME': r'^LIBNAME\s+([^;(\s]+)',
        'FILENAME': r'^FILENAME\s+([^;(\s]+)',
        
        # Output and formatting
        'OPTIONS': r'^OPTIONS\s+',
        'ODS': r'^ODS\s+',
        'TITLE': r'^TITLE\d*\s+',
        'FOOTNOTE': r'^FOOTNOTE\d*\s+',
        
        # Graphics components
        'GOPTIONS': r'^GOPTIONS\s+',
        'SYMBOL': r'^SYMBOL\d*\s+',
        'AXIS': r'^AXIS\d*\s+',
        'PATTERN': r'^PATTERN\d*\s+',
        'LEGEND': r'^LEGEND\d*\s+',
        
        # Format and informats
        'FORMAT': r'^FORMAT\s+',
        'INFORMAT': r'^INFORMAT\s+',
        
        # Macro programming
        '%LET': r'^%LET\s+([^=\s]+)',
        '%DO': r'^%DO\s+',
        '%IF': r'^%IF\s+',
        '%PUT': r'^%PUT\s+',
        '%INCLUDE': r'^%INCLUDE\s+',
        
        # Special cases
        'CARDS': r'^CARDS;|^DATALINES;',
        'DATALINES': r'^DATALINES;|^CARDS;',
        
        # RUN and QUIT statements are handled separately
    }
    
    # Special procedure names that need custom handling
    SPECIAL_PROCS = {
        'SQL': r'^PROC\s+SQL',
        'IML': r'^PROC\s+IML',
        'FCMP': r'^PROC\s+FCMP',
        'TEMPLATE': r'^PROC\s+TEMPLATE',
        'GROOVY': r'^PROC\s+GROOVY',
        'LUA': r'^PROC\s+LUA',
        'PYTHON': r'^PROC\s+PYTHON',
        'R': r'^PROC\s+R',
    }
    
    # SQL statement types to track
    SQL_STATEMENT_TYPES = [
        'SELECT', 'INSERT', 'UPDATE', 'DELETE', 
        'CREATE', 'DROP', 'ALTER', 'GRANT', 'REVOKE'
    ]

    def __init__(self):
        self.components: List[SASComponent] = []
        self.global_macro_variables: Dict[str, str] = {}
        self.nesting_stack: List[SASComponent] = []
        self.error_count = 0
        self.warning_count = 0

    def parse_directory(self, directory_path: str) -> Generator[List[SASComponent], None, None]:
        """Parse all SAS files in a directory and its subdirectories."""
        directory = Path(directory_path)
        
        # Walk through directory
        for file_path in directory.rglob("*.sas"):
            try:
                logger.info(f"Parsing file: {file_path}")
                components = self.parse_file(str(file_path))
                yield components
            except Exception as e:
                self.error_count += 1
                logger.error(f"Error parsing file {file_path}: {str(e)}")
                continue
        
        logger.info(f"Parsing complete. Processed files with {self.error_count} errors and {self.warning_count} warnings")
    
    def parse_directory_parallel(self, directory_path: str, max_workers: int = None) -> List[List[SASComponent]]:
        """
        Parse all SAS files in a directory and its subdirectories in parallel.
        
        Args:
            directory_path: Path to the directory containing SAS files
            max_workers: Maximum number of worker processes (defaults to CPU count)
            
        Returns:
            List of component lists, one list per file
        """
        import concurrent.futures
        from pathlib import Path
        import os
        
        if max_workers is None:
            import multiprocessing
            max_workers = multiprocessing.cpu_count()
        
        directory = Path(directory_path)
        sas_files = list(directory.rglob("*.sas"))
        
        all_components = []
        
        print(f"Found {len(sas_files)} SAS files to process with {max_workers} workers")
        
        # Define the helper function properly inside the method
        def parse_file_wrapper(file_path):
            try:
                return self.parse_file(str(file_path))
            except Exception as e:
                print(f"Error parsing file {file_path}: {str(e)}")
                return []
        
        # Process files in parallel
        with concurrent.futures.ProcessPoolExecutor(max_workers=max_workers) as executor:
            # Create a dictionary mapping futures to their corresponding files
            future_to_file = {}
            for file in sas_files:
                future = executor.submit(parse_file_wrapper, file)
                future_to_file[future] = file
            
            # Process results as they complete
            for i, future in enumerate(concurrent.futures.as_completed(future_to_file)):
                file = future_to_file[future]
                try:
                    components = future.result()
                    all_components.append(components)
                    print(f"Processed file {i+1}/{len(sas_files)}: {file.name} - Found {len(components)} components")
                except Exception as e:
                    print(f"Error processing {file}: {str(e)}")
        
        return all_components

    def parse_file(self, file_path: str) -> List[SASComponent]:
        """Parse a SAS file and extract components with enhanced logic."""
        try:
            with open(file_path, 'r', encoding='utf-8', errors='ignore') as file:
                content = file.readlines()
        except UnicodeDecodeError:
            # Fallback encoding for problematic files
            with open(file_path, 'r', encoding='latin-1', errors='ignore') as file:
                content = file.readlines()
                
        self.components = []
        self.nesting_stack = []
        current_component = None
        in_comment_block = False
        in_cards_block = False
        current_content = []
        
        # Get absolute file path for metadata
        abs_file_path = os.path.abspath(file_path)
        
        line_index = 0
        while line_index < len(content):
            line = content[line_index].strip()
            line_index += 1
            line_number = line_index  # 1-based line number
            
            # Handle comment blocks
            if '/*' in line and not in_comment_block and not self._is_in_quotes(line, line.find('/*')):
                comment_start = line.find('/*')
                # Check if comment ends on the same line
                if '*/' in line[comment_start:]:
                    # Comment begins and ends on the same line
                    comment_end = line.find('*/', comment_start)
                    line = line[:comment_start] + ' ' + line[comment_end+2:]
                else:
                    in_comment_block = True
                    line = line[:comment_start].strip()
                    
            if in_comment_block and '*/' in line:
                in_comment_block = False
                comment_end = line.find('*/')
                line = line[comment_end+2:].strip()
                if not line:
                    continue
                
            if in_comment_block:
                continue
                
            # Skip empty lines and single-line comments
            if not line or line.startswith('*') or line.startswith('//'):
                continue
            
            # Handle special case for CARDS/DATALINES blocks
            if in_cards_block:
                current_content.append(line)
                if line.strip() == ';' or line.strip() == ';;;;':
                    in_cards_block = False
                continue
                
            if re.match(r'^(CARDS|DATALINES);', line.upper()):
                in_cards_block = True
                current_content.append(line)
                continue
                
            # Add line to current content
            current_content.append(line)
            
            # Process %LET statements to track macro variables
            if re.match(r'^%LET\s+', line.upper()):
                self._process_macro_variable(line)
            
            # Check for component types
            component_matched = False
            
            # First, check for special procedure types that need custom handling
            for special_type, pattern in self.SPECIAL_PROCS.items():
                if re.match(pattern, line.upper()):
                    if current_component:
                        self._finalize_current_component(current_component, current_content[:-1], line_number-1)
                        current_content = [line]
                        
                    current_component = SASComponent(
                        type=f"PROC_{special_type}",
                        name=special_type,
                        content="",
                        line_start=line_number,
                        line_end=None,
                        dependencies=self._extract_dependencies(line),
                        metadata={
                            "file_path": abs_file_path,
                            "source_file": os.path.basename(file_path),
                            "directory": os.path.dirname(abs_file_path),
                            "special_handling": True
                        }
                    )
                    
                    # Special processing for different proc types
                    if special_type == 'SQL':
                        # For SQL procs, we'll collect SQL statements later
                        current_component.metadata["sql_statements"] = []
                    
                    component_matched = True
                    break
            
            # Then check for standard component types if no special type was matched
            if not component_matched:
                for comp_type, pattern in self.COMPONENT_TYPES.items():
                    if re.match(pattern, line.upper()):
                        if current_component:
                            self._finalize_current_component(current_component, current_content[:-1], line_number-1)
                            current_content = [line]
                        
                        name = self._extract_name(line, pattern) if comp_type in ['PROC', 'DATA', 'MACRO', 'LIBNAME', 'FILENAME', '%LET'] else ''
                        
                        current_component = SASComponent(
                            type=comp_type,
                            name=name,
                            content="",
                            line_start=line_number,
                            line_end=None,
                            dependencies=self._extract_dependencies(line),
                            metadata={
                                "file_path": abs_file_path,
                                "source_file": os.path.basename(file_path),
                                "directory": os.path.dirname(abs_file_path)
                            }
                        )
                        
                        component_matched = True
                        break
            
            # Check for macro nesting (for %DO, %IF, etc.)
            if re.match(r'^%(\w+)', line.upper()) and not component_matched:
                if current_component:
                    # This could be a nested macro statement inside an existing component
                    macro_command = re.match(r'^%(\w+)', line.upper()).group(1)
                    if macro_command in ['DO', 'IF', 'ELSE', 'END']:
                        # Track macro nesting but don't create a new component
                        pass
            
            # Check for end of components
            if self._is_component_end(line):
                if current_component:
                    self._finalize_current_component(current_component, current_content, line_number)
                    current_component = None
                current_content = []
                
            # Special processing for PROC SQL blocks
            elif current_component and current_component.type == "PROC_SQL":
                for sql_type in self.SQL_STATEMENT_TYPES:
                    if re.match(rf'^\s*{sql_type}\b', line.upper()):
                        # Process SQL statement
                        sql_content, end_line = self._extract_sql_statement(content, line_index-1)
                        if sql_content:
                            stmt = SQLStatement(
                                statement_type=sql_type,
                                content=sql_content,
                                line_start=line_number,
                                line_end=end_line,
                                tables=self._extract_sql_tables(sql_content, sql_type)
                            )
                            current_component.metadata["sql_statements"].append(stmt)
                        # Skip ahead to the end of the SQL statement
                        if end_line > line_index:
                            line_index = end_line
                        break
        
        # Add last component if exists
        if current_component:
            self._finalize_current_component(current_component, current_content, len(content))
        
        # Post-process all components to enhance metadata and extract relationships
        self._post_process_components()
        
        return self.components

    def _post_process_components(self):
        """Perform post-processing on components to extract additional info."""
        # Build a dictionary of components by name for easy lookup
        component_dict = {}
        for comp in self.components:
            if comp.name:
                component_dict[comp.name] = comp
                
        # Process dependencies and relationships
        for comp in self.components:
            # Enhance metadata based on component type
            if comp.type == "PROC":
                self._enhance_proc_metadata(comp)
            elif comp.type == "DATA":
                self._enhance_data_metadata(comp)
            elif comp.type == "MACRO":
                self._enhance_macro_metadata(comp)
            elif comp.type == "PROC_SQL":
                self._enhance_sql_metadata(comp)
                
            # Process references to other components
            for dep in comp.dependencies:
                if dep in component_dict:
                    # Create a bidirectional relationship
                    if "references" not in comp.metadata:
                        comp.metadata["references"] = []
                    comp.metadata["references"].append(component_dict[dep].name)
                    
                    if "referenced_by" not in component_dict[dep].metadata:
                        component_dict[dep].metadata["referenced_by"] = []
                    component_dict[dep].metadata["referenced_by"].append(comp.name)
    
    def _finalize_current_component(self, component: SASComponent, content_lines: List[str], end_line: int):
        """Finalize a component by setting its content and line_end."""
        component.line_end = end_line
        component.content = '\n'.join(content_lines)
        
        # Extract additional dependencies
        additional_deps = self._extract_dependencies(component.content)
        for dep in additional_deps:
            if dep not in component.dependencies:
                component.dependencies.append(dep)
        
        # Extract macro variables defined in this component
        component.macro_variables = self._extract_macro_variables(component.content)
        
        # Add component to the list
        self.components.append(component)
        
    def _extract_name(self, line: str, pattern: str) -> str:
        """Extract component name using regex pattern."""
        match = re.search(pattern, line, re.IGNORECASE)
        return match.group(1) if match else ""

    def _extract_dependencies(self, content: str) -> List[str]:
        """Extract dependencies from component content with enhanced patterns."""
        dependencies = set()
        
        # Dataset references (enhanced to catch more patterns)
        dataset_patterns = [
            r'(?:DATA|SET|MERGE|UPDATE|MODIFY)=?\s*([a-zA-Z_][a-zA-Z0-9_]*\.?[a-zA-Z0-9_]*)',
            r'(?:IN|OUT)=\s*([a-zA-Z_][a-zA-Z0-9_]*\.?[a-zA-Z0-9_]*)',
            r'(?:FROM|INTO|TABLE)\s+([a-zA-Z_][a-zA-Z0-9_]*\.?[a-zA-Z0-9_]*)'
        ]
        
        for pattern in dataset_patterns:
            matches = re.findall(pattern, content.upper())
            dependencies.update(matches)
        
        # Macro calls (enhanced pattern to capture more variants)
        macro_calls = re.findall(r'%([a-zA-Z_][a-zA-Z0-9_]*)\s*[\(;]', content)
        dependencies.update(macro_calls)
        
        # Library references
        libname_refs = re.findall(r'LIBNAME\s+([a-zA-Z_][a-zA-Z0-9_]*)', content.upper())
        dependencies.update(libname_refs)
        
        # File references
        filename_refs = re.findall(r'FILENAME\s+([a-zA-Z_][a-zA-Z0-9_]*)', content.upper())
        dependencies.update(filename_refs)
        
        # Include file references
        include_refs = re.findall(r'%INCLUDE\s+[\'"]([^\'"]+)[\'"]', content)
        dependencies.update(include_refs)
        
        # FORMAT references
        format_refs = re.findall(r'FORMAT\s+([a-zA-Z_][a-zA-Z0-9_]*\.?[a-zA-Z0-9_]*)', content.upper())
        dependencies.update(format_refs)
        
        return list(dependencies)

    def _is_component_end(self, line: str) -> bool:
        """Check if line indicates end of component with enhanced patterns."""
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

    def _is_in_quotes(self, line: str, pos: int) -> bool:
        """Check if position is inside quotes in a line."""
        # Count single and double quotes before position
        single_quotes = line[:pos].count("'") - line[:pos].count("''")
        double_quotes = line[:pos].count('"') - line[:pos].count('""')
        
        # If odd number of quotes, we're inside quotes
        return single_quotes % 2 == 1 or double_quotes % 2 == 1

    def _process_macro_variable(self, line: str):
        """Process a %LET statement to track macro variables."""
        match = re.match(r'^%LET\s+(\w+)\s*=\s*(.*?)\s*;', line)
        if match:
            var_name = match.group(1)
            var_value = match.group(2)
            self.global_macro_variables[var_name] = var_value

    def _extract_macro_variables(self, content: str) -> Dict[str, str]:
        """Extract all macro variable definitions from content."""
        variables = {}
        matches = re.findall(r'%LET\s+(\w+)\s*=\s*(.*?)\s*;', content)
        for name, value in matches:
            variables[name] = value
        return variables

    def _extract_sql_statement(self, content: List[str], start_line: int) -> Tuple[str, int]:
        """Extract a complete SQL statement beginning at start_line."""
        sql_lines = []
        semicolon_found = False
        line_index = start_line
        
        while line_index < len(content) and not semicolon_found:
            line = content[line_index].strip()
            
            # Skip comments
            if line.startswith('*') or line.startswith('/*') or line.startswith('--'):
                line_index += 1
                continue
                
            sql_lines.append(line)
            
            if line.endswith(';'):
                semicolon_found = True
                
            line_index += 1
            
        return '\n'.join(sql_lines), line_index

    def _extract_sql_tables(self, sql_content: str, statement_type: str) -> List[str]:
        """Extract table names from SQL statement."""
        tables = []
        
        if statement_type == 'SELECT':
            # Look for FROM clause and JOIN clauses
            from_match = re.search(r'FROM\s+([a-zA-Z_][a-zA-Z0-9_]*\.?[a-zA-Z0-9_]*)', sql_content, re.IGNORECASE)
            if from_match:
                tables.append(from_match.group(1))
                
            join_matches = re.findall(r'JOIN\s+([a-zA-Z_][a-zA-Z0-9_]*\.?[a-zA-Z0-9_]*)', sql_content, re.IGNORECASE)
            tables.extend(join_matches)
            
        elif statement_type in ['INSERT', 'UPDATE', 'DELETE']:
            # For INSERT, look for INTO clause
            if statement_type == 'INSERT':
                into_match = re.search(r'INTO\s+([a-zA-Z_][a-zA-Z0-9_]*\.?[a-zA-Z0-9_]*)', sql_content, re.IGNORECASE)
                if into_match:
                    tables.append(into_match.group(1))
                    
            # For UPDATE, look for table name after UPDATE
            elif statement_type == 'UPDATE':
                update_match = re.search(r'UPDATE\s+([a-zA-Z_][a-zA-Z0-9_]*\.?[a-zA-Z0-9_]*)', sql_content, re.IGNORECASE)
                if update_match:
                    tables.append(update_match.group(1))
                    
            # For DELETE, look for FROM clause
            elif statement_type == 'DELETE':
                from_match = re.search(r'FROM\s+([a-zA-Z_][a-zA-Z0-9_]*\.?[a-zA-Z0-9_]*)', sql_content, re.IGNORECASE)
                if from_match:
                    tables.append(from_match.group(1))
                    
        elif statement_type in ['CREATE', 'DROP', 'ALTER']:
            # Look for table name after TABLE keyword
            table_match = re.search(r'TABLE\s+([a-zA-Z_][a-zA-Z0-9_]*\.?[a-zA-Z0-9_]*)', sql_content, re.IGNORECASE)
            if table_match:
                tables.append(table_match.group(1))
                
        return tables

    def _enhance_proc_metadata(self, component: SASComponent):
        """Extract and enhance metadata specific to PROC components."""
        content = component.content.upper()
        metadata = component.metadata
        
        # Extract PROC options
        options_dict = {}
        options_pattern = r'(?:^|\s)(\w+)\s*=\s*([^;\s]+)'
        options_matches = re.findall(options_pattern, content)
        for opt_name, opt_value in options_matches:
            options_dict[opt_name] = opt_value
            
        metadata["proc_options"] = options_dict
        
        # Detect if this proc uses ODS output
        if "ODS" in content:
            metadata["uses_ods"] = True
            
        # Extract PROC-specific info based on type
        proc_name = component.name.upper()
        if proc_name == "MEANS" or proc_name == "SUMMARY":
            # Extract variables being analyzed
            vars_match = re.search(r'VAR\s+(.*?);', content)
            if vars_match:
                metadata["analysis_variables"] = [v.strip() for v in vars_match.group(1).split()]
                
        elif proc_name == "REG" or proc_name == "GLM":
            # Extract model statement
            model_match = re.search(r'MODEL\s+(.*?);', content)
            if model_match:
                metadata["model"] = model_match.group(1).strip()
                
        elif proc_name == "REPORT":
            # Extract columns
            column_match = re.search(r'COLUMN\s+(.*?);', content)
            if column_match:
                metadata["columns"] = column_match.group(1).strip()

    def _enhance_data_metadata(self, component: SASComponent):
        """Extract and enhance metadata specific to DATA steps."""
        content = component.content.upper()
        metadata = component.metadata
        
        # Check for SET, MERGE, UPDATE statements
        if re.search(r'\bSET\b', content):
            metadata["operation"] = "SET"
            set_match = re.search(r'SET\s+(.*?);', content)
            if set_match:
                metadata["input_datasets"] = [ds.strip() for ds in set_match.group(1).split()]
                
        elif re.search(r'\bMERGE\b', content):
            metadata["operation"] = "MERGE"
            merge_match = re.search(r'MERGE\s+(.*?);', content)
            if merge_match:
                metadata["input_datasets"] = [ds.strip() for ds in merge_match.group(1).split()]
                
        elif re.search(r'\bUPDATE\b', content):
            metadata["operation"] = "UPDATE"
            
        # Check for BY statement
        by_match = re.search(r'\bBY\s+(.*?);', content)
        if by_match:
            metadata["by_variables"] = [var.strip() for var in by_match.group(1).split()]
            
        # Extract variables created/modified
        var_assignments = re.findall(r'(\w+)\s*=', content)
        if var_assignments:
            metadata["modified_variables"] = list(set(var_assignments))
            
        # Check for DROP/KEEP statements
        drop_match = re.search(r'\bDROP\s+(.*?);', content)
        if drop_match:
            metadata["dropped_variables"] = [var.strip() for var in drop_match.group(1).split()]
            
        keep_match = re.search(r'\bKEEP\s+(.*?);', content)
        if keep_match:
            metadata["kept_variables"] = [var.strip() for var in keep_match.group(1).split()]
            
        # Check for OUTPUT statement
        if re.search(r'\bOUTPUT\b', content):
            metadata["has_output"] = True
            
        # Check for IF/THEN/ELSE logic
        if re.search(r'\bIF\b', content):
            metadata["has_conditional_logic"] = True
            
        # Check for DO loops
        if re.search(r'\bDO\b', content):
            metadata["has_loops"] = True

    def _enhance_macro_metadata(self, component: SASComponent):
        """Extract and enhance metadata specific to MACRO components."""
        content = component.content
        metadata = component.metadata
        
        # Extract macro parameters
        params_match = re.search(r'%MACRO\s+\w+\s*\((.*?)\)', content, re.IGNORECASE)
        if params_match:
            params_str = params_match.group(1)
            if params_str:
                params = [p.strip() for p in params_str.split(',')]
                metadata["parameters"] = params
                
        # Check for nested macros
        nested_macros = re.findall(r'%MACRO\s+(\w+)', content[1:], re.IGNORECASE)  # Skip first line
        if nested_macros:
            metadata["nested_macros"] = nested_macros
            
        # Check for macro calls within macro
        macro_calls = re.findall(r'%(\w+)\s*\(', content, re.IGNORECASE)
        if macro_calls:
            # Filter out internal SAS macro functions
            sas_functions = {'EVAL', 'SYSFUNC', 'SYSEVALF', 'QUOTE', 'STR', 'QSCAN', 'SUBSTR'}
            external_calls = [call for call in macro_calls if call not in sas_functions]
            if external_calls:
                metadata["macro_calls"] = list(set(external_calls))
                
        # Check for macro variables used
        macro_vars = re.findall(r'&(\w+)', content)
        if macro_vars:
            metadata["used_macro_variables"] = list(set(macro_vars))

    def _enhance_sql_metadata(self, component: SASComponent):
        """Extract and enhance metadata specific to SQL components."""
        metadata = component.metadata
        
        if "sql_statements" in metadata:
            # Count statement types
            statement_counts = defaultdict(int)
            for stmt in metadata["sql_statements"]:
                statement_counts[stmt.statement_type] += 1
                
            metadata["statement_counts"] = dict(statement_counts)
            
            # Extract all tables referenced
            all_tables = set()
            for stmt in metadata["sql_statements"]:
                all_tables.update(stmt.tables)
                
            metadata["referenced_tables"] = list(all_tables)
            
            # Convert statement objects to dictionaries for serialization
            serializable_statements = []
            for stmt in metadata["sql_statements"]:
                serializable_statements.append({
                    "type": stmt.statement_type,
                    "tables": stmt.tables,
                    "line_start": stmt.line_start,
                    "line_end": stmt.line_end
                })
            metadata["sql_statements"] = serializable_statements

    def _recover_from_parsing_error(self, file_path: str, line_number: int, error_message: str) -> Optional[SASComponent]:
        """Attempt to recover from parsing errors by creating a partial component."""
        self.warning_count += 1
        logger.warning(f"Parsing error at {file_path}:{line_number} - {error_message}")
        
        # Create a partial component for the error location
        partial_component = SASComponent(
            type="PARSE_ERROR",
            name=f"error_line_{line_number}",
            content=f"// Parsing error occurred here: {error_message}",
            line_start=line_number,
            line_end=line_number,
            metadata={
                "file_path": file_path,
                "source_file": os.path.basename(file_path),
                "directory": os.path.dirname(file_path),
                "error_message": error_message,
                "is_recovery": True
            }
        )
        
        return partial_component

    def extract_variables(self, component: SASComponent) -> List[str]:
        """Extract variable declarations from a component."""
        variables = set()
        
        # Variables in DATA steps are often assigned with =
        if component.type == "DATA":
            var_assignments = re.findall(r'(\w+)\s*=', component.content)
            variables.update(var_assignments)
            
            # Also look for variables in DROP/KEEP statements
            drop_match = re.search(r'\bDROP\s+(.*?);', component.content, re.IGNORECASE)
            if drop_match:
                drop_vars = [v.strip() for v in drop_match.group(1).split()]
                variables.update(drop_vars)
                
            keep_match = re.search(r'\bKEEP\s+(.*?);', component.content, re.IGNORECASE)
            if keep_match:
                keep_vars = [v.strip() for v in keep_match.group(1).split()]
                variables.update(keep_vars)
        
        # Variables in PROCs are often in VAR statements
        elif component.type == "PROC":
            var_match = re.search(r'\bVAR\s+(.*?);', component.content, re.IGNORECASE)
            if var_match:
                proc_vars = [v.strip() for v in var_match.group(1).split()]
                variables.update(proc_vars)
        
        # Variables in SQL are in column lists and WHERE clauses
        elif component.type == "PROC_SQL":
            # Extract column names from SELECT statements
            select_matches = re.findall(r'SELECT\s+(.*?)\s+FROM', component.content, re.IGNORECASE | re.DOTALL)
            for match in select_matches:
                # Split by commas, but be cautious of functions
                if '*' not in match:  # Skip SELECT * cases
                    columns = []
                    bracket_level = 0
                    current_column = ""
                    
                    for char in match:
                        if char == '(':
                            bracket_level += 1
                        elif char == ')':
                            bracket_level -= 1
                        
                        if char == ',' and bracket_level == 0:
                            columns.append(current_column.strip())
                            current_column = ""
                        else:
                            current_column += char
                    
                    if current_column:
                        columns.append(current_column.strip())
                    
                    # Extract actual variable names, handling AS clauses
                    for col in columns:
                        as_match = re.search(r'\bAS\b\s+(\w+)', col, re.IGNORECASE)
                        if as_match:
                            variables.add(as_match.group(1))
                        else:
                            col_parts = col.split('.')
                            if len(col_parts) > 1:
                                variables.add(col_parts[-1])
                            else:
                                variables.add(col)
        
        # Remove SAS keywords and common function names from variables
        sas_keywords = {'IF', 'THEN', 'ELSE', 'DO', 'END', 'BY', 'PROC', 'RUN', 'DATA', 'SET', 'MERGE'}
        sas_functions = {'SUM', 'MEAN', 'MIN', 'MAX', 'COUNT', 'AVG', 'SUBSTR', 'TRIM', 'INPUT', 'PUT'}
        
        variables = {v for v in variables if v.upper() not in sas_keywords and v.upper() not in sas_functions}
        
        return list(variables)

    def extract_procedures(self, components: List[SASComponent]) -> List[SASComponent]:
        """Filter SAS components to extract only PROC statements and their content."""
        return [comp for comp in components if comp.type == "PROC" or comp.type.startswith("PROC_")]
    
    def extract_data_steps(self, components: List[SASComponent]) -> List[SASComponent]:
        """Filter SAS components to extract only DATA steps and their transformations."""
        return [comp for comp in components if comp.type == "DATA"]
    
    def extract_macros(self, components: List[SASComponent]) -> List[SASComponent]:
        """Filter SAS components to extract only macro definitions and their content."""
        return [comp for comp in components if comp.type == "MACRO"]
    
    def extract_statistical_ops(self, components: List[SASComponent]) -> List[SASComponent]:
        """Extract statistical operations and their parameters from PROC components."""
        # List of PROC types that are commonly used for statistical analysis
        stat_procs = {'MEANS', 'GLM', 'REG', 'LOGISTIC', 'MIXED', 'ANOVA', 'TTEST', 'CORR', 'FREQ', 'UNIVARIATE'}
        
        statistical_components = []
        for comp in components:
            if comp.type == "PROC" and comp.name.upper() in stat_procs:
                statistical_components.append(comp)
                
        return statistical_components
    
    def extract_data_transformations(self, components: List[SASComponent]) -> List[Dict[str, Any]]:
        """Extract data transformation patterns from DATA steps."""
        transformations = []
        
        for comp in components:
            if comp.type == "DATA":
                # Initialize transformation metadata
                transform_info = {
                    "component_name": comp.name,
                    "transformation_type": "Unknown",
                    "input_datasets": [],
                    "output_dataset": comp.name,
                    "operations": []
                }
                
                content = comp.content
                
                # Determine transformation type
                if re.search(r'\bSET\b', content, re.IGNORECASE):
                    transform_info["transformation_type"] = "Filter/Transform"
                    # Extract input datasets
                    set_match = re.search(r'\bSET\s+(.*?);', content, re.IGNORECASE)
                    if set_match:
                        transform_info["input_datasets"] = [ds.strip() for ds in set_match.group(1).split()]
                        
                elif re.search(r'\bMERGE\b', content, re.IGNORECASE):
                    transform_info["transformation_type"] = "Merge"
                    # Extract input datasets
                    merge_match = re.search(r'\bMERGE\s+(.*?);', content, re.IGNORECASE)
                    if merge_match:
                        transform_info["input_datasets"] = [ds.strip() for ds in merge_match.group(1).split()]
                        
                elif re.search(r'\bUPDATE\b', content, re.IGNORECASE):
                    transform_info["transformation_type"] = "Update"
                    
                # Extract operations
                operations = []
                
                # Check for IF statements (filtering operations)
                if_matches = re.findall(r'\bIF\s+(.*?)\s+THEN\s+(.*?);', content, re.IGNORECASE | re.DOTALL)
                for condition, action in if_matches:
                    operations.append({
                        "type": "Conditional",
                        "condition": condition.strip(),
                        "action": action.strip()
                    })
                
                # Check for assignments (transformation operations)
                assignment_matches = re.findall(r'(\w+)\s*=\s*(.*?);', content)
                for var, expression in assignment_matches:
                    operations.append({
                        "type": "Assignment",
                        "variable": var.strip(),
                        "expression": expression.strip()
                    })
                
                transform_info["operations"] = operations
                transformations.append(transform_info)
                
        return transformations
    
    def extract_workflow(self, components: List[SASComponent]) -> Dict[str, Any]:
        """Attempt to reconstruct the data processing workflow from components."""
        workflow = {
            "data_sources": [],
            "transformations": [],
            "analysis": [],
            "output": [],
            "flow": []
        }
        
        # Identify data sources (LIBNAME statements, external data references)
        data_sources = []
        for comp in components:
            if comp.type == "LIBNAME":
                data_sources.append({
                    "type": "Library",
                    "name": comp.name,
                    "content": comp.content
                })
            elif comp.type == "FILENAME":
                data_sources.append({
                    "type": "External File",
                    "name": comp.name,
                    "content": comp.content
                })
                
        workflow["data_sources"] = data_sources
        
        # Map transformation steps
        transformations = self.extract_data_transformations(components)
        workflow["transformations"] = transformations
        
        # Map analysis steps
        analysis_steps = []
        for comp in self.extract_statistical_ops(components):
            analysis_steps.append({
                "type": f"PROC {comp.name}",
                "name": comp.name,
                "line_range": (comp.line_start, comp.line_end),
                "content_summary": comp.content[:100] + "..." if len(comp.content) > 100 else comp.content
            })
            
        workflow["analysis"] = analysis_steps
        
        # Map output steps (ODS, PROC REPORT, etc.)
        output_steps = []
        for comp in components:
            if "ODS" in comp.content.upper() or comp.type == "ODS":
                output_steps.append({
                    "type": "Output Definition",
                    "line_range": (comp.line_start, comp.line_end),
                    "content_summary": comp.content[:100] + "..." if len(comp.content) > 100 else comp.content
                })
            elif comp.type == "PROC" and comp.name.upper() in {"REPORT", "PRINT", "TABULATE", "SGPLOT", "GPLOT", "GCHART"}:
                output_steps.append({
                    "type": f"Reporting - PROC {comp.name}",
                    "line_range": (comp.line_start, comp.line_end),
                    "content_summary": comp.content[:100] + "..." if len(comp.content) > 100 else comp.content
                })
                
        workflow["output"] = output_steps
        
        # Simple flow reconstruction - this could be enhanced with dependency analysis
        workflow_steps = []
        for comp in components:
            if comp.type in ["LIBNAME", "FILENAME"]:
                workflow_steps.append({
                    "type": "Data Source Definition",
                    "name": comp.name,
                    "step_number": len(workflow_steps) + 1
                })
            elif comp.type == "DATA":
                workflow_steps.append({
                    "type": "Data Transformation",
                    "name": comp.name,
                    "step_number": len(workflow_steps) + 1,
                    "input_datasets": comp.metadata.get("input_datasets", []) if "input_datasets" in comp.metadata else []
                })
            elif comp.type == "PROC" or comp.type.startswith("PROC_"):
                workflow_steps.append({
                    "type": "Analysis/Reporting",
                    "name": f"PROC {comp.name}",
                    "step_number": len(workflow_steps) + 1
                })
                
        workflow["flow"] = workflow_steps
        
        return workflow
    
    def extract_global_dependencies(self, components: List[SASComponent]) -> Dict[str, List[str]]:
        """Extract global dependencies between components."""
        dependencies = {}
        
        # Build a dictionary of components by name
        component_dict = {}
        for comp in components:
            if comp.name:
                component_dict[comp.name] = comp
                
        # Analyze dependencies
        for comp in components:
            if comp.name:
                dependencies[comp.name] = []
                
                # Check direct dependencies
                for dep_name in comp.dependencies:
                    if dep_name in component_dict and dep_name != comp.name:
                        dependencies[comp.name].append(dep_name)
                        
                # Check content for references to other components
                for other_name in component_dict:
                    if other_name != comp.name and other_name in comp.content:
                        if other_name not in dependencies[comp.name]:
                            dependencies[comp.name].append(other_name)
        
        return dependencies
    
    def extract_document_structure(self, components: List[SASComponent]) -> Dict[str, Any]:
        """Extract the overall structure of the SAS document."""
        structure = {
            "total_components": len(components),
            "component_types": {},
            "sections": []
        }
        
        # Count component types
        for comp in components:
            if comp.type not in structure["component_types"]:
                structure["component_types"][comp.type] = 0
            structure["component_types"][comp.type] += 1
            
        # Identify logical sections in the document
        current_section = {
            "type": "Unknown",
            "start_line": 1,
            "components": []
        }
        
        for comp in sorted(components, key=lambda x: x.line_start):
            # Check if we need to start a new section
            if (not current_section["components"] or 
                (comp.line_start - current_section["components"][-1].line_end) > 5):
                
                # Add the previous section if it has components
                if current_section["components"]:
                    current_section["end_line"] = current_section["components"][-1].line_end
                    structure["sections"].append(current_section)
                
                # Start a new section
                current_section = {
                    "type": self._determine_section_type(comp),
                    "start_line": comp.line_start,
                    "components": [comp]
                }
            else:
                current_section["components"].append(comp)
                
        # Add the last section
        if current_section["components"]:
            current_section["end_line"] = current_section["components"][-1].line_end
            structure["sections"].append(current_section)
            
        return structure
    
    def _determine_section_type(self, component: SASComponent) -> str:
        """Determine the type of a document section based on its first component."""
        if component.type == "LIBNAME" or component.type == "FILENAME":
            return "Resource Definition"
        elif component.type == "OPTIONS" or component.type == "ODS":
            return "Configuration"
        elif component.type == "MACRO":
            return "Macro Definition"
        elif component.type == "DATA":
            return "Data Processing"
        elif component.type == "PROC" or component.type.startswith("PROC_"):
            proc_name = component.name.upper()
            if proc_name in {"MEANS", "GLM", "REG", "LOGISTIC", "MIXED", "ANOVA", "TTEST", "CORR", "FREQ", "UNIVARIATE"}:
                return "Statistical Analysis"
            elif proc_name in {"REPORT", "PRINT", "TABULATE", "SGPLOT", "GPLOT", "GCHART"}:
                return "Reporting/Visualization"
            else:
                return "Procedure"
        else:
            return "Miscellaneous"