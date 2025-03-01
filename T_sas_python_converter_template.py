from template_loader import TemplateLoader
from typing import Dict, Any, List, Optional
import re
import logging
from datetime import datetime

logger = logging.getLogger(__name__)

class SASConversionError(Exception):
    """Custom exception for SAS conversion errors."""
    def __init__(self, message: str, component: Dict[str, Any], details: Optional[Dict] = None):
        self.message = message
        self.component = component
        self.details = details or {}
        super().__init__(f"SAS Conversion Error: {message}")

class SASPythonConverterTemplate:
    def __init__(self, template_file: str = 'sas_templates.yaml'):
        """Initialize converter with templates."""
        self.template_loader = TemplateLoader(template_file)
        self.templates = self.template_loader.load_templates()
        self.error_handler = self._setup_error_handler()
    
    def _setup_error_handler(self):
        """Setup error handling system."""
        template = self.templates.get('error_handling_system')
        if template:
            exec(template.render(), globals())
            return globals().get('SASErrorHandler')()
        return None

    def convert_component(self, component: Dict[str, Any]) -> str:
        """Convert a SAS component using appropriate template."""
        try:
            # Validate component
            self._validate_component(component)
            
            component_type = component.get('type', '').upper()
            component_name = component.get('name', '').upper()
            
            logger.debug(f"Converting {component_type} - {component_name}")
            
            # Get converter method
            converter_method = getattr(self, f"_convert_{component_type.lower()}", None)
            if not converter_method:
                raise SASConversionError(f"Unsupported component type: {component_type}", component)
            
            # Convert component
            result = converter_method(component)
            
            # Log success
            if self.error_handler:
                self.error_handler.add_note(
                    component=f"{component_type} - {component_name}",
                    message="Successfully converted"
                )
            
            return result
            
        except SASConversionError as e:
            logger.error(f"Conversion error: {str(e)}")
            if self.error_handler:
                self.error_handler.add_error(
                    component=str(component.get('type', 'Unknown')),
                    message=str(e),
                    details=e.details
                )
            return f"# ERROR: {str(e)}\n# {component.get('content', '')}"
        
        except Exception as e:
            logger.error(f"Unexpected error: {str(e)}", exc_info=True)
            if self.error_handler:
                self.error_handler.add_error(
                    component=str(component.get('type', 'Unknown')),
                    message=f"Unexpected error: {str(e)}"
                )
            return f"# ERROR: Unexpected error - {str(e)}\n# {component.get('content', '')}"

    def _validate_component(self, component: Dict[str, Any]):
        """Validate component structure."""
        if not isinstance(component, dict):
            raise SASConversionError("Component must be a dictionary", component)
        
        required_fields = ['type', 'content']
        missing_fields = [f for f in required_fields if f not in component]
        if missing_fields:
            raise SASConversionError(
                f"Missing required fields: {', '.join(missing_fields)}", 
                component
            )

    def _convert_proc(self, component: Dict[str, Any]) -> str:
        """Convert PROC statements using templates."""
        proc_name = component.get('name', '').lower()
        template_name = f"proc_{proc_name}"
        
        try:
            # Extract parameters based on PROC type
            params = self._extract_proc_params(component)
            return self.templates.get(template_name).render(**params)
        except ValueError as e:
            return f"# Template not found: {template_name}\n# {component.get('content', '')}"
        except Exception as e:
            return f"# Error converting PROC {proc_name}: {str(e)}\n# {component.get('content', '')}"

    def _extract_proc_params(self, component: Dict[str, Any]) -> Dict[str, Any]:
        """Extract parameters for PROC templates."""
        content = component.get('content', '')
        proc_name = component.get('name', '').lower()
        
        # Common parameters
        params = {
            'dataset': self._extract_dataset(content),
            'variables': self._extract_variables(content)
        }
        
        # PROC-specific parameters
        if proc_name == 'means':
            params.update(self._extract_means_params(content))
        elif proc_name == 'freq':
            params.update(self._extract_freq_params(content))
        elif proc_name == 'sort':
            params.update(self._extract_sort_params(content))
        # Add more PROC-specific parameter extraction
        
        return params

    def _convert_data_step(self, component: Dict[str, Any]) -> str:
        """Convert DATA step using template."""
        if 'null' in component.get('content', '').lower():
            return self.templates.get('null_data_step').render(statements=self._extract_data_statements(component))
        
        return self.templates.get('data_step').render(**self._extract_data_params(component))

    def _convert_sql(self, component: Dict[str, Any]) -> str:
        """Convert SQL statements using templates."""
        content = component.get('content', '')
        if self._is_complex_sql(content):
            return self.templates.get('complex_sql').render(**self._extract_complex_sql_params(content))
        
        return self.templates.get('sql').render(**self._extract_sql_params(content))

    def _convert_macro(self, component: Dict[str, Any]) -> str:
        """Convert macro definitions using template."""
        return self.templates.get('macro').render(**self._extract_macro_params(component))

    def _convert_macro_variable(self, component: Dict[str, Any]) -> str:
        """Convert macro variable operations using template."""
        return self.templates.get('macro_variable').render(**self._extract_macro_var_params(component))

    def _convert_libname(self, component: Dict[str, Any]) -> str:
        """Convert LIBNAME statements using template."""
        return self.templates.get('libname').render(**self._extract_libname_params(component))

    def _convert_filename(self, component: Dict[str, Any]) -> str:
        """Convert FILENAME statements using template."""
        return self.templates.get('filename').render(**self._extract_filename_params(component))

    def _convert_ods(self, component: Dict[str, Any]) -> str:
        """Convert ODS statements using template."""
        content = component.get('content', '').lower()
        if 'graphics' in content:
            return self.templates.get('ods_graphics').render(**self._extract_ods_graphics_params(content))
        return self.templates.get('ods').render(**self._extract_ods_params(content))

    # Helper methods for parameter extraction
    def _extract_dataset(self, content: str) -> str:
        """Extract dataset name from SAS code."""
        match = re.search(r'data\s*=\s*(\w+)', content, re.IGNORECASE)
        return match.group(1) if match else "df"

    def _extract_variables(self, content: str) -> List[str]:
        """Extract variable names from SAS code."""
        match = re.search(r'var\s+(.*?);', content, re.IGNORECASE)
        return match.group(1).split() if match else []

    def _extract_means_params(self, content: str) -> Dict[str, Any]:
        """Extract parameters for PROC MEANS."""
        return {
            'maxdec': self._extract_maxdec(content),
            'by_vars': self._extract_by_vars(content),
            'nway': 'nway' in content.lower(),
            'noprint': 'noprint' in content.lower()
        }

    def _extract_freq_params(self, content: str) -> Dict[str, Any]:
        """Extract parameters for PROC FREQ."""
        tables_match = re.search(r'tables\s+(.*?);', content, re.IGNORECASE)
        return {
            'tables': tables_match.group(1).split() if tables_match else [],
            'chisq': 'chisq' in content.lower()
        }

    def _extract_sort_params(self, content: str) -> Dict[str, Any]:
        """Extract parameters for PROC SORT."""
        by_match = re.search(r'by\s+(.*?);', content, re.IGNORECASE)
        out_match = re.search(r'out\s*=\s*(\w+)', content, re.IGNORECASE)
        return {
            'by_vars': by_match.group(1).split() if by_match else [],
            'out_name': out_match.group(1) if out_match else None,
            'nodupkey': 'nodupkey' in content.lower(),
            'nodup': 'nodup' in content.lower()
        }

    def _extract_data_params(self, component: Dict[str, Any]) -> Dict[str, Any]:
        """Extract parameters for DATA step."""
        content = component.get('content', '')
        return {
            'input_dataset': self._extract_input_dataset(content),
            'output_dataset': self._extract_output_dataset(content),
            'where_clause': self._extract_where_clause(content),
            'drop_vars': self._extract_drop_vars(content),
            'keep_vars': self._extract_keep_vars(content),
            'rename_dict': self._extract_rename_dict(content)
        }

    def _extract_input_dataset(self, content: str) -> Optional[str]:
        """Extract input dataset name from DATA step."""
        match = re.search(r'set\s+(\w+)', content, re.IGNORECASE)
        return match.group(1) if match else None

    def _extract_output_dataset(self, content: str) -> str:
        """Extract output dataset name from DATA step."""
        match = re.search(r'data\s+(\w+)', content, re.IGNORECASE)
        return match.group(1) if match else "output"

    def _extract_where_clause(self, content: str) -> Optional[str]:
        """Extract WHERE clause from SAS code."""
        match = re.search(r'where\s+(.*?);', content, re.IGNORECASE)
        if match:
            return self._convert_sas_condition(match.group(1))
        return None

    def _extract_drop_vars(self, content: str) -> List[str]:
        """Extract DROP variables."""
        match = re.search(r'drop\s+(.*?);', content, re.IGNORECASE)
        return match.group(1).split() if match else []

    def _extract_keep_vars(self, content: str) -> List[str]:
        """Extract KEEP variables."""
        match = re.search(r'keep\s+(.*?);', content, re.IGNORECASE)
        return match.group(1).split() if match else []

    def _extract_rename_dict(self, content: str) -> Dict[str, str]:
        """Extract RENAME mappings."""
        rename_dict = {}
        match = re.search(r'rename\s*=\s*\((.*?)\)', content, re.IGNORECASE)
        if match:
            pairs = match.group(1).split()
            for pair in pairs:
                old, new = pair.split('=')
                rename_dict[old.strip()] = new.strip()
        return rename_dict

    def _extract_sql_params(self, content: str) -> Dict[str, Any]:
        """Extract parameters from SQL statement."""
        return {
            'statements': self._parse_sql_statements(content)
        }

    def _parse_sql_statements(self, content: str) -> List[Dict[str, Any]]:
        """Parse SQL statements into structured format."""
        statements = []
        # Split into individual SQL statements
        sql_stmts = re.split(r';(?=[^;]*$)', content)
        
        for stmt in sql_stmts:
            if re.search(r'^\s*select', stmt, re.IGNORECASE):
                statements.append(self._parse_select_statement(stmt))
            elif re.search(r'^\s*create\s+table', stmt, re.IGNORECASE):
                statements.append(self._parse_create_table(stmt))
        
        return statements

    def _convert_sas_condition(self, condition: str) -> str:
        """Convert SAS condition to Python condition."""
        # Replace SAS operators with Python operators
        condition = re.sub(r'\beq\b', '==', condition, flags=re.IGNORECASE)
        condition = re.sub(r'\bne\b', '!=', condition, flags=re.IGNORECASE)
        condition = re.sub(r'\bgt\b', '>', condition, flags=re.IGNORECASE)
        condition = re.sub(r'\blt\b', '<', condition, flags=re.IGNORECASE)
        condition = re.sub(r'\bge\b', '>=', condition, flags=re.IGNORECASE)
        condition = re.sub(r'\ble\b', '<=', condition, flags=re.IGNORECASE)
        condition = re.sub(r'\band\b', '&', condition, flags=re.IGNORECASE)
        condition = re.sub(r'\bor\b', '|', condition, flags=re.IGNORECASE)
        
        return condition

    def _extract_macro_body(self, content: str) -> str:
        """Extract macro body between %MACRO and %MEND."""
        start = content.find(';', content.find('%macro')) + 1
        end = content.find('%mend')
        if start > 0 and end > start:
            return content[start:end].strip()
        return ""

    def _convert_macro_params(self, params_str: str) -> str:
        """Convert SAS macro parameters to Python parameters."""
        if not params_str:
            return ""
        
        # Convert each parameter
        python_params = []
        for param in params_str.split(','):
            param = param.strip()
            if '=' in param:  # Default value
                name, value = param.split('=')
                python_params.append(f"{name.strip()}={value.strip()}")
            else:
                python_params.append(param)
        
        return ", ".join(python_params)

    def _extract_macro_params(self, component: Dict[str, Any]) -> Dict[str, Any]:
        """Extract parameters for macro definition."""
        content = component.get('content', '')
        macro_match = re.search(r'%macro\s+(\w+)(?:\((.*?)\))?;', content, re.IGNORECASE)
        return {
            'macro_name': macro_match.group(1) if macro_match else '',
            'python_params': self._convert_macro_params(macro_match.group(2) if macro_match and macro_match.group(2) else ''),
            'body': self._extract_macro_body(content)
        }

    # Add more helper methods for parameter extraction
    def _extract_maxdec(self, content: str) -> Optional[int]:
        match = re.search(r'maxdec\s*=\s*(\d+)', content, re.IGNORECASE)
        return int(match.group(1)) if match else None

    def _extract_by_vars(self, content: str) -> List[str]:
        match = re.search(r'by\s+(.*?);', content, re.IGNORECASE)
        return match.group(1).split() if match else []

    def _parse_select_statement(self, stmt: str) -> Dict[str, Any]:
        """Parse SELECT statement into components."""
        stmt = stmt.strip()
        result = {
            'type': 'select',
            'columns': self._extract_select_columns(stmt),
            'table_df': self._extract_from_table(stmt),
            'where_clause': self._extract_sql_where(stmt),
            'group_by_list': self._extract_group_by(stmt),
            'order_by': self._extract_order_by(stmt),
            'is_into': 'into' in stmt.lower()
        }
        
        if result['is_into']:
            result.update({
                'macro_var': self._extract_into_var(stmt),
                'separator': self._extract_separator(stmt)
            })
            
        return result

    def _parse_create_table(self, stmt: str) -> Dict[str, Any]:
        """Parse CREATE TABLE statement."""
        stmt = stmt.strip()
        match = re.search(r'create\s+table\s+(\w+)\s+as', stmt, re.IGNORECASE)
        return {
            'type': 'create_table',
            'output_table_df': match.group(1) if match else 'output',
            'from_table_df': self._extract_from_table(stmt),
            'where_clause': self._extract_sql_where(stmt)
        }

    def _extract_select_columns(self, stmt: str) -> List[str]:
        """Extract column list from SELECT statement."""
        match = re.search(r'select\s+(.*?)\s+from', stmt, re.IGNORECASE)
        if match:
            cols = match.group(1).strip()
            if cols == '*':
                return []  # Return empty list for SELECT *
            return [c.strip() for c in cols.split(',')]
        return []

    def _extract_from_table(self, stmt: str) -> str:
        """Extract table name from FROM clause."""
        match = re.search(r'from\s+(\w+)', stmt, re.IGNORECASE)
        return match.group(1) if match else 'df'

    def _extract_sql_where(self, stmt: str) -> Optional[str]:
        """Extract and convert WHERE clause from SQL."""
        match = re.search(r'where\s+(.*?)(?:group by|order by|$)', stmt, re.IGNORECASE)
        if match:
            return self._convert_sql_condition(match.group(1).strip())
        return None

    def _extract_group_by(self, stmt: str) -> List[str]:
        """Extract GROUP BY columns."""
        match = re.search(r'group\s+by\s+(.*?)(?:having|order by|$)', stmt, re.IGNORECASE)
        if match:
            return [col.strip() for col in match.group(1).split(',')]
        return []

    def _extract_order_by(self, stmt: str) -> Dict[str, Any]:
        """Extract ORDER BY clause."""
        match = re.search(r'order\s+by\s+(.*?)$', stmt, re.IGNORECASE)
        if not match:
            return {'cols': [], 'ascending': []}
            
        cols = []
        ascending = []
        
        for item in match.group(1).split(','):
            item = item.strip()
            if item.lower().endswith(' desc'):
                cols.append(item[:-5].strip())
                ascending.append(False)
            else:
                cols.append(item)
                ascending.append(True)
                
        return {'cols': cols, 'ascending': ascending}

    def _extract_into_var(self, stmt: str) -> Optional[str]:
        """Extract INTO variable from SELECT statement."""
        match = re.search(r'into\s+(\w+)', stmt, re.IGNORECASE)
        return match.group(1) if match else None

    def _extract_separator(self, stmt: str) -> Optional[str]:
        """Extract separator from SELECT statement."""
        match = re.search(r'separator\s*=\s*(\w+)', stmt, re.IGNORECASE)
        return match.group(1) if match else None

    def _convert_sql_condition(self, condition: str) -> str:
        """Convert SQL condition to Python condition."""
        # Replace SQL operators with Python operators
        condition = re.sub(r'\beq\b', '==', condition, flags=re.IGNORECASE)
        condition = re.sub(r'\bne\b', '!=', condition, flags=re.IGNORECASE)
        condition = re.sub(r'\bgt\b', '>', condition, flags=re.IGNORECASE)
        condition = re.sub(r'\blt\b', '<', condition, flags=re.IGNORECASE)
        condition = re.sub(r'\bge\b', '>=', condition, flags=re.IGNORECASE)
        condition = re.sub(r'\ble\b', '<=', condition, flags=re.IGNORECASE)
        condition = re.sub(r'\band\b', '&', condition, flags=re.IGNORECASE)
        condition = re.sub(r'\bor\b', '|', condition, flags=re.IGNORECASE)
        
        return condition

    def _extract_ods_graphics_params(self, content: str) -> Dict[str, Any]:
        """Extract ODS GRAPHICS parameters."""
        params = {
            'width': self._extract_numeric_param(content, 'width'),
            'height': self._extract_numeric_param(content, 'height'),
            'dpi': self._extract_numeric_param(content, 'dpi'),
            'style': self._extract_style_param(content)
        }
        return {k: v for k, v in params.items() if v is not None}

    def _extract_numeric_param(self, content: str, param: str) -> Optional[int]:
        """Extract numeric parameter value."""
        match = re.search(rf'{param}\s*=\s*(\d+)', content, re.IGNORECASE)
        return int(match.group(1)) if match else None

    def _extract_style_param(self, content: str) -> Optional[str]:
        """Extract style parameter."""
        match = re.search(r'style\s*=\s*(\w+)', content, re.IGNORECASE)
        return match.group(1) if match else None

    def validate_component(self, component: Dict[str, Any]) -> bool:
        """Validate component structure and required fields."""
        required_fields = ['type', 'content']
        return all(field in component for field in required_fields)

    def validate_template_params(self, template_name: str, params: Dict[str, Any]) -> bool:
        """Validate parameters for a template."""
        try:
            return self.template_loader.validate_template(template_name, params)
        except Exception as e:
            logger.error(f"Template validation error: {str(e)}")
            return False

    def _is_complex_sql(self, content: str) -> bool:
        """Determine if SQL is complex (multiple statements, subqueries, etc.)."""
        indicators = [
            r'union\s+all',
            r'union',
            r'intersect',
            r'except',
            r'with\s+\w+\s+as',
            r'select.*?select',  # Subquery
            r'case\s+when'
        ]
        return any(re.search(pattern, content, re.IGNORECASE) for pattern in indicators)

    def _clean_sas_name(self, name: str) -> str:
        """Clean SAS name for Python use."""
        name = re.sub(r'[^a-zA-Z0-9_]', '_', name)
        if name[0].isdigit():
            name = 'n' + name
        return name.lower()

    def _format_python_string(self, value: str) -> str:
        """Format string for Python code."""
        value = value.replace("'", "\\'")
        return f"'{value}'"

    def _indent_code(self, code: str, level: int = 1) -> str:
        """Indent code by specified number of levels."""
        indent = "    " * level
        return "\n".join(indent + line if line.strip() else line 
                        for line in code.splitlines())

    # Add more parameter extraction methods as needed... 

    # Additional conversion methods
    def _convert_proc_tabulate(self, component: Dict[str, Any]) -> str:
        """Convert PROC TABULATE statements."""
        try:
            params = self._extract_tabulate_params(component)
            return self.templates.get('proc_extensions').get('tabulate').render(**params)
        except Exception as e:
            raise SASConversionError("Error converting PROC TABULATE", component, {'error': str(e)})

    def _convert_proc_transpose(self, component: Dict[str, Any]) -> str:
        """Convert PROC TRANSPOSE statements."""
        try:
            params = self._extract_transpose_params(component)
            return self.templates.get('proc_extensions').get('transpose').render(**params)
        except Exception as e:
            raise SASConversionError("Error converting PROC TRANSPOSE", component, {'error': str(e)})

    def _convert_proc_compare(self, component: Dict[str, Any]) -> str:
        """Convert PROC COMPARE statements."""
        try:
            params = self._extract_compare_params(component)
            return self.templates.get('proc_extensions').get('compare').render(**params)
        except Exception as e:
            raise SASConversionError("Error converting PROC COMPARE", component, {'error': str(e)})

    # Enhanced parameter extraction methods
    def _extract_tabulate_params(self, component: Dict[str, Any]) -> Dict[str, Any]:
        """Extract parameters for PROC TABULATE."""
        content = component.get('content', '')
        params = {
            'df': self._extract_dataset(content),
            'page_vars': [],
            'row_vars': [],
            'col_vars': [],
            'statistics': []
        }
        
        # Extract CLASS variables
        class_match = re.search(r'class\s+(.*?);', content, re.IGNORECASE | re.DOTALL)
        if class_match:
            class_vars = class_match.group(1).split()
            params['row_vars'] = class_vars
        
        # Extract TABLE statement
        table_match = re.search(r'table\s+(.*?);', content, re.IGNORECASE | re.DOTALL)
        if table_match:
            table_spec = table_match.group(1)
            # Parse table specification
            params.update(self._parse_table_spec(table_spec))
        
        return params

    def _extract_transpose_params(self, component: Dict[str, Any]) -> Dict[str, Any]:
        """Extract parameters for PROC TRANSPOSE."""
        content = component.get('content', '')
        params = {
            'df': self._extract_dataset(content),
            'id_vars': [],
            'value_vars': [],
            'name_prefix': ''
        }
        
        # Extract ID variables
        id_match = re.search(r'id\s+(.*?);', content, re.IGNORECASE)
        if id_match:
            params['id_vars'] = id_match.group(1).split()
        
        # Extract VAR variables
        var_match = re.search(r'var\s+(.*?);', content, re.IGNORECASE)
        if var_match:
            params['value_vars'] = var_match.group(1).split()
        
        # Extract PREFIX
        prefix_match = re.search(r'prefix\s*=\s*(\w+)', content, re.IGNORECASE)
        if prefix_match:
            params['name_prefix'] = prefix_match.group(1)
        
        return params

    def _extract_compare_params(self, component: Dict[str, Any]) -> Dict[str, Any]:
        """Extract parameters for PROC COMPARE."""
        content = component.get('content', '')
        params = {
            'base_df': None,
            'comp_df': None,
            'by_vars': [],
            'compare_vars': []
        }
        
        # Extract BASE dataset
        base_match = re.search(r'base\s*=\s*(\w+)', content, re.IGNORECASE)
        if base_match:
            params['base_df'] = base_match.group(1)
        
        # Extract COMPARE dataset
        comp_match = re.search(r'compare\s*=\s*(\w+)', content, re.IGNORECASE)
        if comp_match:
            params['comp_df'] = comp_match.group(1)
        
        # Extract BY variables
        by_match = re.search(r'by\s+(.*?);', content, re.IGNORECASE)
        if by_match:
            params['by_vars'] = by_match.group(1).split()
        
        # Extract VAR variables
        var_match = re.search(r'var\s+(.*?);', content, re.IGNORECASE)
        if var_match:
            params['compare_vars'] = var_match.group(1).split()
        
        return params

    def _parse_table_spec(self, table_spec: str) -> Dict[str, Any]:
        """Parse PROC TABULATE table specification."""
        result = {
            'row_vars': [],
            'col_vars': [],
            'statistics': []
        }
        
        # Split into dimensions
        parts = table_spec.split('*')
        for part in parts:
            part = part.strip()
            if 'all' in part.lower():
                continue
            elif any(stat in part.lower() for stat in ['mean', 'sum', 'n', 'std']):
                result['statistics'].append(part)
            elif ',' in part:
                result['col_vars'].extend(part.split(','))
            else:
                result['row_vars'].append(part)
        
        return result 

    # Additional PROC conversions
    def _convert_proc_append(self, component: Dict[str, Any]) -> str:
        """Convert PROC APPEND statements."""
        try:
            params = self._extract_append_params(component)
            return self.templates.get('proc_dataset_operations').get('append').render(**params)
        except Exception as e:
            raise SASConversionError("Error converting PROC APPEND", component, {'error': str(e)})

    def _convert_proc_datasets(self, component: Dict[str, Any]) -> str:
        """Convert PROC DATASETS statements."""
        try:
            params = self._extract_datasets_params(component)
            return self.templates.get('proc_dataset_operations').get('modify').render(**params)
        except Exception as e:
            raise SASConversionError("Error converting PROC DATASETS", component, {'error': str(e)})

    def _convert_proc_summary(self, component: Dict[str, Any]) -> str:
        """Convert PROC SUMMARY statements."""
        try:
            params = self._extract_summary_params(component)
            template = self.templates.get('proc_means')  # PROC SUMMARY is similar to PROC MEANS
            return template.render(**params)
        except Exception as e:
            raise SASConversionError("Error converting PROC SUMMARY", component, {'error': str(e)})

    # Enhanced parameter extraction methods
    def _extract_append_params(self, component: Dict[str, Any]) -> Dict[str, Any]:
        """Extract parameters for PROC APPEND."""
        content = component.get('content', '')
        params = {
            'base_df': None,
            'data_df': None,
            'force': False
        }
        
        # Extract BASE dataset
        base_match = re.search(r'base\s*=\s*(\w+)', content, re.IGNORECASE)
        if base_match:
            params['base_df'] = base_match.group(1)
        
        # Extract DATA dataset
        data_match = re.search(r'data\s*=\s*(\w+)', content, re.IGNORECASE)
        if data_match:
            params['data_df'] = data_match.group(1)
        
        # Check for FORCE option
        if re.search(r'force', content, re.IGNORECASE):
            params['force'] = True
        
        return params

    def _extract_datasets_params(self, component: Dict[str, Any]) -> Dict[str, Any]:
        """Extract parameters for PROC DATASETS."""
        content = component.get('content', '')
        params = {
            'lib_path': None,
            'modifications': []
        }
        
        # Extract library
        lib_match = re.search(r'library\s*=\s*(\w+)', content, re.IGNORECASE)
        if lib_match:
            params['lib_path'] = lib_match.group(1)
        
        # Extract MODIFY statements
        modify_matches = re.finditer(r'modify\s+(\w+).*?;(.*?)(?=modify|$)', 
                                   content, re.IGNORECASE | re.DOTALL)
        
        for match in modify_matches:
            dataset = match.group(1)
            modify_content = match.group(2)
            
            # Extract modifications
            mods = []
            
            # Handle RENAME
            rename_match = re.search(r'rename\s+(.*?);', modify_content, re.IGNORECASE)
            if rename_match:
                rename_pairs = self._parse_rename_statement(rename_match.group(1))
                mods.append({
                    'type': 'rename',
                    'mapping': rename_pairs
                })
            
            # Handle LABEL
            label_match = re.search(r'label\s+(.*?);', modify_content, re.IGNORECASE)
            if label_match:
                labels = self._parse_label_statement(label_match.group(1))
                mods.append({
                    'type': 'label',
                    'labels': labels
                })
            
            # Handle FORMAT
            format_match = re.search(r'format\s+(.*?);', modify_content, re.IGNORECASE)
            if format_match:
                formats = self._parse_format_statement(format_match.group(1))
                mods.append({
                    'type': 'format',
                    'formats': formats
                })
            
            params['modifications'].extend(mods)
        
        return params

    def _extract_summary_params(self, component: Dict[str, Any]) -> Dict[str, Any]:
        """Extract parameters for PROC SUMMARY."""
        content = component.get('content', '')
        params = {
            'dataset': self._extract_dataset(content),
            'variables': [],
            'class_vars': [],
            'ways': None,
            'output': None
        }
        
        # Extract VAR statement
        var_match = re.search(r'var\s+(.*?);', content, re.IGNORECASE)
        if var_match:
            params['variables'] = var_match.group(1).split()
        
        # Extract CLASS statement
        class_match = re.search(r'class\s+(.*?);', content, re.IGNORECASE)
        if class_match:
            params['class_vars'] = class_match.group(1).split()
        
        # Extract WAYS statement
        ways_match = re.search(r'ways\s+(\d+)', content, re.IGNORECASE)
        if ways_match:
            params['ways'] = int(ways_match.group(1))
        
        # Extract OUTPUT statement
        output_match = re.search(r'output\s+out\s*=\s*(\w+)(.*?);', 
                               content, re.IGNORECASE | re.DOTALL)
        if output_match:
            params['output'] = {
                'dataset': output_match.group(1),
                'statistics': self._parse_output_statement(output_match.group(2))
            }
        
        return params

    # Helper methods for parameter parsing
    def _parse_rename_statement(self, rename_content: str) -> Dict[str, str]:
        """Parse RENAME statement into old_name=new_name pairs."""
        pairs = {}
        for pair in rename_content.split():
            if '=' in pair:
                old, new = pair.split('=')
                pairs[old.strip()] = new.strip()
        return pairs

    def _parse_label_statement(self, label_content: str) -> Dict[str, str]:
        """Parse LABEL statement into variable='label' pairs."""
        labels = {}
        # Split by quotes, preserving quoted strings
        parts = re.findall(r'(\w+)\s*=\s*[\'"]([^\'"]*)[\'"]', label_content)
        for var, label in parts:
            labels[var.strip()] = label.strip()
        return labels

    def _parse_format_statement(self, format_content: str) -> Dict[str, str]:
        """Parse FORMAT statement into variable=format pairs."""
        formats = {}
        for pair in format_content.split():
            if ' ' in pair:
                var, fmt = pair.split()
                formats[var.strip()] = fmt.strip()
        return formats

    def _parse_output_statement(self, output_content: str) -> List[Dict[str, str]]:
        """Parse OUTPUT statement statistics."""
        stats = []
        # Match patterns like: sum=total mean=average
        matches = re.finditer(r'(\w+)\s*=\s*(\w+)', output_content)
        for match in matches:
            stats.append({
                'function': match.group(1),
                'name': match.group(2)
            })
        return stats 