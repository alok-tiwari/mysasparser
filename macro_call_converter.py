from typing import Dict, List, Any, Optional, Union
import re
import logging

from sas_parser import SASComponent

logger = logging.getLogger('SASPythonConverter')

def convert_macro_call(statement: str) -> str:
    """Convert a SAS macro call statement to Python function call."""
    try:
        # Extract macro name and parameters
        macro_match = re.search(r'%(\w+)\s*\((.*)\);?', statement)
        if not macro_match:
            return f"# TODO: Convert macro call: {statement}"
        
        macro_name = macro_match.group(1)
        params_str = macro_match.group(2)
        
        # Parse parameters
        params = {}
        for param in re.findall(r'(\w+)\s*=\s*([^,]+)', params_str):
            name = param[0].strip()
            value = param[1].strip()
            
            # Remove & from macro variables
            if value.startswith('&'):
                value = value[1:]
            
            params[name] = value
        
        # Generate function call
        param_list = [f"{k}={v}" for k, v in params.items()]
        return f"{macro_name}({', '.join(param_list)})"
        
    except Exception as e:
        logger.warning(f"Error converting macro call statement: {str(e)}")
        return f"# TODO: Convert macro call: {statement}"

def convert_analyze_segment_call(statement: str) -> str:
    """Convert the analyze_segment macro call specifically."""
    try:
        # Extract parameters
        data_match = re.search(r'data\s*=\s*([^,\)]+)', statement)
        segment_match = re.search(r'segment\s*=\s*([^,\)]+)', statement)
        var_match = re.search(r'var\s*=\s*([^,\)]+)', statement)
        
        if not (data_match and segment_match and var_match):
            return f"# TODO: Convert analyze_segment call: {statement}"
        
        data = data_match.group(1).strip()
        segment = segment_match.group(1).strip()
        var = var_match.group(1).strip()
        
        # Remove & from macro variables
        if segment.startswith('&'):
            segment = segment[1:]
        
        # Convert dataset reference
        if '.' in data:
            lib, dataset = data.split('.')
            data_ref = f"{dataset.lower()}_df"
        else:
            data_ref = f"{data.lower()}_df"
        
        return f"analyze_segment(data={data_ref}, segment={segment}, var='{var}')"
    
    except Exception as e:
        logger.warning(f"Error converting analyze_segment call: {str(e)}")
        return f"# TODO: Convert analyze_segment call: {statement}"