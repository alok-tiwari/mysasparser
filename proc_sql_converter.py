from typing import Dict, List, Any, Optional, Union
import re
import logging

from sas_parser import SASComponent

logger = logging.getLogger('SASPythonConverter')

def convert_proc_sql_enhanced(component: SASComponent) -> str:
    """Enhanced conversion of PROC SQL to pandas operations."""
    try:
        content = component.content
        
        # Check for noprint option
        noprint = 'noprint' in content.lower()
        
        # Extract CREATE TABLE statements
        create_table_matches = re.findall(r'create\s+table\s+(\S+)\s+as\s+select\s+(.*?)\s+from\s+(\S+)(?:\s+where\s+(.*?))?(?:\s+group\s+by\s+(.*?))?(?:\s+order\s+by\s+(.*?))?;', 
                                         content, re.IGNORECASE | re.DOTALL)
        
        # Extract SELECT INTO statements (for macro variables)
        select_into_matches = re.findall(r'select\s+(.*?)\s+into\s+:(\w+)(?:\s+separated\s+by\s+["\']([^"\']*)["\'])?\s+from\s+(\S+)(?:\s+where\s+(.*?))?;', 
                                         content, re.IGNORECASE | re.DOTALL)
        
        if create_table_matches:
            sql_code = []
            for match in create_table_matches:
                output_table = convert_sas_reference(match[0])
                columns = match[1].strip()
                input_table = convert_sas_reference(match[2])
                where_clause = match[3].strip() if len(match) > 3 and match[3] else None
                group_by = match[4].strip() if len(match) > 4 and match[4] else None
                order_by = match[5].strip() if len(match) > 5 and match[5] else None
                
                # Start with the input table
                code = [f"{output_table} = {input_table}.copy()"]
                
                # Handle column selection
                if columns != '*':
                    cols = [c.strip() for c in columns.split(',')]
                    code.append(f"{output_table} = {output_table}[[{', '.join(repr(c) for c in cols)}]]")
                
                # Handle WHERE clause
                if where_clause:
                    py_condition = convert_sas_condition(where_clause)
                    code.append(f"{output_table} = {output_table}[{py_condition}]")
                
                # Handle GROUP BY
                if group_by:
                    group_cols = [c.strip() for c in group_by.split(',')]
                    code.append(f"{output_table} = {output_table}.groupby([{', '.join(repr(c) for c in group_cols)}]).agg({{'*': 'count'}})")
                
                # Handle ORDER BY
                if order_by:
                    order_cols = []
                    ascending = []
                    for col in order_by.split(','):
                        col = col.strip()
                        if col.lower().endswith(' desc'):
                            order_cols.append(col[:-5].strip())
                            ascending.append(False)
                        else:
                            order_cols.append(col)
                            ascending.append(True)
                    
                    code.append(f"{output_table} = {output_table}.sort_values(by=[{', '.join(repr(c) for c in order_cols)}], ascending={ascending})")
                
                sql_code.extend(code)
            
            return '\n'.join(sql_code)
        
        elif select_into_matches:
            sql_code = []
            for match in select_into_matches:
                columns = match[0].strip()
                macro_var = match[1].strip()
                separator = match[2] if len(match) > 2 and match[2] else " "
                input_table = convert_sas_reference(match[3])
                where_clause = match[4].strip() if len(match) > 4 and match[4] else None
                
                # Handle distinct if present
                distinct = False
                if 'distinct' in columns.lower():
                    distinct = True
                    columns = re.sub(r'distinct\s+', '', columns, flags=re.IGNORECASE)
                
                # Get the column name
                col_name = columns.strip()
                
                # Create code to extract values into a list
                code = [f"# Extract values for macro variable {macro_var}"]
                
                # Filter if where clause exists
                if where_clause:
                    py_condition = convert_sas_condition(where_clause)
                    code.append(f"filtered_df = {input_table}[{py_condition}]")
                    df_ref = "filtered_df"
                else:
                    df_ref = input_table
                
                # Apply distinct if needed
                if distinct:
                    code.append(f"{macro_var} = ' '.join({df_ref}['{col_name}'].unique().astype(str))")
                else:
                    code.append(f"{macro_var} = '{separator}'.join({df_ref}['{col_name}'].astype(str))")
                
                sql_code.extend(code)
            
            return '\n'.join(sql_code)
        
        # If no CREATE TABLE or SELECT INTO statements found, return a TODO comment
        return f"# TODO: Convert PROC SQL:\n# {content.strip()}"
        
    except Exception as e:
        logger.warning(f"Error converting PROC SQL: {str(e)}")
        return f"# TODO: Convert PROC SQL:\n# {component.content.strip()}"

def convert_sas_reference(ref: str) -> str:
    """Convert SAS dataset/variable references to Python variable names."""
    if not ref:
        return ref
    
    # Clean up the reference
    ref = ref.strip()
    
    # Remove & from macro variables
    if ref.startswith('&'):
        ref = ref[1:]
    
    # Handle dataset references (libname.dataset)
    if '.' in ref:
        lib, dataset = ref.split('.', 1)
        # Clean both parts
        lib = clean_variable_name(lib.lower())
        dataset = clean_variable_name(dataset.lower())
        return f"{dataset}_df"
    else:
        # Clean and return
        return clean_variable_name(ref.lower()) + "_df"

def clean_variable_name(name: str) -> str:
    """Clean a SAS name to make it a valid Python variable name."""
    # Replace invalid characters with underscore
    name = re.sub(r'[^a-zA-Z0-9_]', '_', name)
    
    # Ensure it doesn't start with a number
    if name and name[0].isdigit():
        name = '_' + name
    
    return name

def convert_sas_condition(condition: str) -> str:
    """Convert SAS WHERE conditions to pandas query syntax."""
    # Replace SAS operators with Python operators
    condition = condition.replace(' eq ', ' == ')
    condition = condition.replace(' ne ', ' != ')
    condition = condition.replace(' gt ', ' > ')
    condition = condition.replace(' lt ', ' < ')
    condition = condition.replace(' ge ', ' >= ')
    condition = condition.replace(' le ', ' <= ')
    condition = condition.replace(' and ', ' & ')
    condition = condition.replace(' or ', ' | ')
    condition = condition.replace('=', '==')
    
    # Handle special SAS functions
    condition = re.sub(r'missing\(([^)]+)\)', r'\1.isna()', condition, flags=re.IGNORECASE)
    condition = re.sub(r'not\s+missing\(([^)]+)\)', r'\1.notna()', condition, flags=re.IGNORECASE)
    
    return condition