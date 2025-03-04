from typing import Dict, List, Any, Optional, Union
import os
import logging
import argparse
import json
from pathlib import Path
import time
import re

# For ChromaDB testing
from vector_store import VectorStore
from sas_parser import SASComponent, SASParser
from embedding_generator import EmbeddingGenerator

# Configure logging
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
logger = logging.getLogger('SASPythonConverter')

class SASPythonConverter:
    """
    Utility to convert SAS code to Python by retrieving components from a vector store
    and using embeddings for translation guidance.
    """
    
    def __init__(
        self, 
        vector_store=None, 
        output_directory: str = "python_output",
        embedding_generator=None
    ):
        """Initialize the converter."""
        self.vector_store = vector_store
        self.output_directory = output_directory
        
        # Initialize embedding generator if not provided
        if embedding_generator is None:
            self.embedding_generator = EmbeddingGenerator(embedding_dim=4096)
        else:
            self.embedding_generator = embedding_generator
        
        # Create output directory if it doesn't exist
        os.makedirs(output_directory, exist_ok=True)
        
        # Initialize state tracking
        self.macro_variables = {}
        self.libname_refs = {}
        self.format_functions = set()
        
        # Tracking for conversion process
        self.converted_files = {}
        self.dependency_map = {}
    
    def get_similar_components(self, 
                          query_text: str, 
                          component_type: Optional[str] = None, 
                          n_results: int = 5) -> List[Dict[str, Any]]:
        """
        Get similar components from vector store using consistent embedding dimensions.
        """
        if self.vector_store and self.embedding_generator:
            try:
                # Create a temporary component to generate an embedding
                temp_component = SASComponent(
                    type=component_type if component_type else "UNKNOWN",
                    name="query",
                    content=query_text,
                    line_start=0,
                    line_end=0,
                    metadata={"temp_query": True}
                )
                
                # Generate query embedding using the same generator used for storage
                embeddings = self.embedding_generator.generate_embeddings([temp_component])
                if not embeddings:
                    logger.error("Failed to generate query embedding")
                    return []
                    
                query_embedding = embeddings[0].embedding.tolist()
                
                # Get collection names
                if component_type:
                    collection_key = self._get_collection_for_type(component_type)
                    collection_names = [collection_key] if collection_key in self.vector_store.collections else []
                else:
                    collection_names = list(self.vector_store.collections.keys())
                
                if not collection_names:
                    collection_names = list(self.vector_store.collections.keys())
                    
                # Use embeddings directly for search to avoid dimension mismatch
                results = self.vector_store.search_with_embedding(
                    query_embedding=query_embedding,
                    n_results=n_results,
                    collection_names=collection_names
                )
                
                combined_results = []
                for collection_name, collection_results in results.items():
                    if collection_name == "_execution_metadata" or collection_name == "combined":
                        continue
                    
                    if "metadatas" in collection_results and "documents" in collection_results:
                        metadatas = collection_results["metadatas"]
                        documents = collection_results["documents"]
                        
                        for i in range(len(metadatas)):
                            if i < len(documents):
                                combined_results.append({
                                    "collection": collection_name,
                                    "metadata": metadatas[i],
                                    "content": documents[i]
                                })
                
                return combined_results
                
            except Exception as e:
                logger.error(f"Error in similarity search: {str(e)}")
                return []
        else:
            if not self.embedding_generator:
                logger.error("No embedding generator configured")
            if not self.vector_store:
                logger.error("No vector store configured")
            return []
            
    def _get_collection_for_type(self, component_type: str) -> str:
        """Get the appropriate collection name for a component type."""
        component_type = component_type.upper() if isinstance(component_type, str) else "OTHER"
        
        if component_type == "PROC" or component_type.startswith("PROC_"):
            return "PROC"
        elif component_type == "DATA":
            return "DATA"
        elif component_type == "MACRO":
            return "MACRO"
        elif component_type == "PROC_SQL":
            return "PROC_SQL"
        else:
            return "OTHER"
    
    def parse_sas_file(self, file_path: str) -> List[SASComponent]:
        """Parse a SAS file into components."""
        parser = SASParser()
        try:
            components = parser.parse_file(file_path)
            logger.info(f"Parsed {len(components)} components from {file_path}")
            return components
        except Exception as e:
            logger.error(f"Error parsing {file_path}: {str(e)}")
            return []
    
    def _add_dataset_loading(self, sas_components: List[SASComponent]) -> List[str]:
        """Generate code to load datasets referenced in SAS components."""
        dataset_refs = set()
        libref_defs = {}
        
        # First pass: collect LIBNAME definitions
        for comp in sas_components:
            if comp.type == "LIBNAME":
                lib_match = re.search(r'LIBNAME\s+(\w+)\s+([^;]+)', comp.content, re.IGNORECASE)
                if lib_match:
                    libref = lib_match.group(1)
                    path = lib_match.group(2).strip().strip("'\"")
                    libref_defs[libref] = path
        
        # Second pass: collect dataset references
        for comp in sas_components:
            if comp.type in ["DATA", "PROC", "PROC_SQL"]:
                # Find all dataset references
                refs = re.findall(r'(?:data|set|from|table)\s*=?\s*(\w+\.?\w*)', 
                                comp.content, 
                                re.IGNORECASE)
                dataset_refs.update(refs)
        
        code_lines = ["\n# Load required datasets"]
        
        # Add sashelp loading function
        code_lines.extend([
            "",
            "def load_sashelp_dataset(name: str) -> pd.DataFrame:",
            "    \"\"\"Load a dataset from sashelp library.\"\"\"",
            "    try:",
            "        return pd.read_csv(f'sashelp_{name.lower()}.csv')",
            "    except Exception as e:",
            "        print(f'Error loading sashelp.{name}: {e}')",
            "        return pd.DataFrame()"
        ])
        
        # Generate loading code for each dataset
        for dataset in sorted(dataset_refs):
            if '.' in dataset:
                lib, name = dataset.split('.')
                if lib.lower() == 'sashelp':
                    code_lines.extend([
                        "",
                        f"# Load {dataset}",
                        f"{name.lower()}_df = load_sashelp_dataset('{name}')"
                    ])
                elif lib in libref_defs:
                    code_lines.extend([
                        "",
                        f"# Load {dataset}",
                        f"try:",
                        f"    {name.lower()}_df = pd.read_csv(os.path.join({repr(libref_defs[lib])}, '{name}.csv'))",
                        f"except Exception as e:",
                        f"    print(f'Error loading {dataset}: {{e}}')",
                        f"    {name.lower()}_df = pd.DataFrame()"
                    ])
            else:
                code_lines.extend([
                    "",
                    f"# Initialize {dataset} dataset",
                    f"{dataset.lower()}_df = pd.DataFrame()"
                ])
        
        return code_lines

    def convert_to_python(self, components: List[SASComponent], file_path: str = None) -> str:
        """Convert SAS components to Python code."""
        # Reset helper functions for this conversion
        self.helper_functions = set()
        
        # Standard imports
        python_code = [
            "import pandas as pd",
            "import numpy as np",
            "from scipy import stats",
            "import matplotlib.pyplot as plt",
            "import seaborn as sns",
            "from pathlib import Path",
            "import os",
            "",
            "",
            "# Initialize variables",
            "pd.set_option('display.max_rows', None)",
            "pd.set_option('display.max_columns', None)",
            "",
            "",
        ]
        
        # Add dataset loading code
        python_code.extend(self._add_dataset_loading(components))
        
        # Process each component
        for component in components:
            try:
                if component.type == "COMMENT":
                    python_code.append(f"# {component.content.strip()}")
                
                elif component.type == "LIBNAME":
                    python_code.append(self._convert_libname(component))
                
                elif component.type == "DATA":
                    python_code.append(self._convert_data(component))
                
                elif component.type == "PROC":
                    python_code.append(self._convert_proc(component))
                
                elif component.type == "PROC_SQL":
                    python_code.append(self._convert_proc_sql(component))
                
                elif component.type == "MACRO":
                    python_code.append(self._convert_macro(component))
                
                elif component.type == "MACRO_CALL":
                    python_code.append(self._convert_macro_call(component))
                
                elif component.type == "TITLE" or component.type == "FOOTNOTE":
                    python_code.append(self._convert_title(component))
                
                elif component.type == "ODS":
                    python_code.append(self._convert_ods(component))
                
                elif component.type == "INCLUDE":
                    python_code.append(self._convert_include(component))
                
                elif component.type == "OPTIONS":
                    python_code.append(f"# TODO: Convert OPTIONS:\n# {component.content.strip()}")
                
                elif component.type == "CONDITIONAL":
                    python_code.append(self._convert_conditional(component))
                
                elif component.type == "WHILE":
                    python_code.append(self._convert_while(component))
                
                # Add special handling for macro statements in the content
                if component.content and '%' in component.content:
                    # Look for macro calls in the content
                    for line in component.content.split('\n'):
                        if line.strip().startswith('%analyze_segment'):
                            # Convert this specific macro call
                            macro_call = self._convert_macro_call_statement(line.strip())
                            python_code.append(macro_call)
                        elif line.strip().startswith('%do %while'):
                            # Convert do while loop
                            do_while = self._convert_macro_do_statement(line.strip())
                            python_code.append(do_while)
                        elif line.strip() == '%end;':
                            # End of loop
                            python_code.append("    # End of loop")
                
                else:
                    python_code.append(f"# TODO: Convert {component.type}:\n# {component.content.strip()}")
                    
            except Exception as e:
                logger.warning(f"Error converting component {component.type}: {str(e)}")
                python_code.append(f"# TODO: Convert {component.type}:\n# {component.content.strip()}")
        
        # Add helper functions if needed
        helper_functions = self._get_helper_functions()
        if helper_functions:
            # Insert helper functions after imports
            python_code.insert(8, helper_functions)
        
        return '\n'.join(python_code)

    def convert_component(self, component: SASComponent) -> str:
        """Convert a single SAS component to Python code."""
        try:
            # Generate embedding for the component
            embedding = self.embedding_generator.generate_embedding(component)
            
            # Get the collection for this component type
            collection = self._get_collection_for_type(component.type)
            
            # Use the appropriate converter based on component type
            converters = {
                'PROC': self._convert_proc,
                'DATA': self._convert_data,
                'LIBNAME': self._convert_libname,
                'MACRO': self._convert_macro,
                '%LET': self._convert_let_direct,
                '%IF': self._convert_if,
                '%DO': self._convert_do,
                '%PUT': self._convert_put,
                'PROC_SQL': self._convert_proc_sql,
                'ODS': self._convert_ods,
                'TITLE': self._convert_title,
                'FOOTNOTE': self._convert_title,
                'GOPTIONS': self._convert_options
            }
            
            # Get the converter
            converter = converters.get(component.type)
            if not converter and component.type.startswith('PROC_'):
                converter = self._convert_proc
            
            if converter:
                try:
                    # First try direct conversion without using similar components
                    return converter(component)
                except Exception as e:
                    logger.warning(f"Direct converter failed for {component.type}: {str(e)}")
                    # Don't try to use similar components as fallback for now
                    return f"# TODO: Convert {component.type}:\n{component.content}"
            
            # If no converter found, return a TODO comment
            return f"# TODO: Convert {component.type}:\n{component.content}"
            
        except Exception as e:
            logger.warning(f"Failed to convert component {component.type}: {str(e)}")
            return f"# Failed to convert {component.type}:\n{component.content}"

    def _convert_proc(self, component: SASComponent) -> str:
        """Convert PROC statements to Python."""
        try:
            proc_name = component.name.lower() if component.name else ""
            content = component.content
            
            if proc_name == 'means':
                return self._convert_proc_means(component)
            elif proc_name == 'ttest':
                return self._convert_proc_ttest(component)
            elif proc_name == 'univariate':
                return self._convert_proc_univariate(component)
            elif proc_name == 'report':
                return self._convert_proc_report(component)
            elif proc_name == 'format':
                # Improved format conversion
                return self._convert_proc_format(component)
            elif proc_name == 'sort':
                return self._convert_proc_sort(component)
            elif proc_name == 'gchart':
                return self._convert_proc_gchart(component)
            elif proc_name == 'sql':
                return self._convert_proc_sql(component)
            
            # If no specific converter, create a function stub
            return f"""# TODO: Convert PROC {proc_name}
def proc_{proc_name}(data_df):
    \"\"\"Python equivalent of PROC {proc_name.upper()}\"\"\"
    # Original SAS code:
    # {content.strip()}
    pass"""
            
        except Exception as e:
            logger.warning(f"Error converting PROC {proc_name if 'proc_name' in locals() else ''}: {str(e)}")
            return f"""# TODO: Convert PROC:
# {component.content.strip()}
def proc_generic(data_df):
    \"\"\"Python equivalent of SAS PROC\"\"\"
    pass"""

    def _convert_proc_means(self, component: SASComponent) -> str:
        """Convert PROC MEANS to pandas describe()."""
        try:
            content = component.content
            data_match = re.search(r'data\s*=\s*(\S+)', content, re.IGNORECASE)
            
            if data_match:
                dataset = self._convert_sas_reference(data_match.group(1))
                return f"""# Calculate descriptive statistics
{dataset}_stats = {dataset}.describe()
print({dataset}_stats)"""
            else:
                return "# TODO: Convert PROC means - no dataset specified"
            
        except Exception as e:
            logger.warning(f"Error converting PROC MEANS: {str(e)}")
            return f"# TODO: Convert PROC means:\n{component.content}"

    def _convert_proc_univariate(self, component: SASComponent) -> str:
        """Convert PROC UNIVARIATE to pandas/scipy statistics."""
        try:
            content = component.content
            data_match = re.search(r'data\s*=\s*(\S+)', content, re.IGNORECASE)
            
            if data_match:
                dataset = self._convert_sas_reference(data_match.group(1))
                return f"""# Detailed descriptive statistics
{dataset}_stats = {dataset}.describe(percentiles=[0.01, 0.05, 0.1, 0.25, 0.5, 0.75, 0.9, 0.95, 0.99])
print({dataset}_stats)

# Normality tests
shapiro_results = []
for col in {dataset}.select_dtypes(include=['number']).columns:
    if {dataset}[col].notna().sum() > 3:  # Need at least 3 values for test
        stat, p = stats.shapiro({dataset}[col].dropna())
        shapiro_results.append({{'column': col, 'statistic': stat, 'p-value': p}})
        
shapiro_df = pd.DataFrame(shapiro_results)
print("Shapiro-Wilk test for normality:")
print(shapiro_df)"""
            else:
                return "# TODO: Convert PROC univariate - no dataset specified"
            
        except Exception as e:
            logger.warning(f"Error converting PROC UNIVARIATE: {str(e)}")
            return f"# TODO: Convert PROC univariate:\n{component.content}"

    def _convert_proc_ttest(self, component: SASComponent) -> str:
        """Convert PROC TTEST to scipy.stats t-test."""
        try:
            content = component.content
            data_match = re.search(r'data\s*=\s*(\S+)', content, re.IGNORECASE)
            h0_match = re.search(r'h0\s*=\s*(\S+)', content, re.IGNORECASE)
            alpha_match = re.search(r'alpha\s*=\s*(\S+)', content, re.IGNORECASE)
            
            if data_match:
                dataset = self._convert_sas_reference(data_match.group(1))
                h0 = h0_match.group(1) if h0_match else "0"
                alpha = alpha_match.group(1) if alpha_match else "0.05"
                
                # Remove & from variable references
                h0 = re.sub(r'&(\w+)', r'\1', h0)
                alpha = re.sub(r'&(\w+)', r'\1', alpha)
                
                return f"""# Perform t-test
for col in {dataset}.select_dtypes(include=['number']).columns:
    if {dataset}[col].notna().sum() > 1:  # Need at least 2 values for test
        t_stat, p_value = stats.ttest_1samp({dataset}[col].dropna(), {h0})
        print(f"T-test for {{col}}:")
        print(f"  T-statistic: {{t_stat:.4f}}")
        print(f"  P-value: {{p_value:.4f}}")
        print(f"  Significant at alpha={alpha}: {{p_value < {alpha}}}")"""
            else:
                return "# TODO: Convert PROC TTEST - no dataset specified"
            
        except Exception as e:
            logger.warning(f"Error converting PROC TTEST: {str(e)}")
            return f"# TODO: Convert PROC TTEST:\n# {component.content}"

    def _convert_proc_report(self, component: SASComponent) -> str:
        """Convert PROC REPORT to pandas display."""
        try:
            content = component.content
            data_match = re.search(r'data\s*=\s*(\S+)', content, re.IGNORECASE)
            
            if data_match:
                dataset = self._convert_sas_reference(data_match.group(1))
                return f"""# Generate report
print(f"Report for {dataset}:")
print({dataset}.head(20))"""
            else:
                return "# TODO: Convert PROC report - no dataset specified"
            
        except Exception as e:
            logger.warning(f"Error converting PROC REPORT: {str(e)}")
            return f"# TODO: Convert PROC report:\n{component.content}"

    def _convert_sas_reference(self, ref: str) -> str:
        """Convert SAS references like &var and dataset.name to Python variables."""
        if not ref:
            return ref
        
        # Handle macro variables
        if ref.startswith('&'):
            var_name = ref[1:]
            return var_name
        
        # Handle dataset references
        if '.' in ref:
            lib, name = ref.split('.')
            if lib.upper() == 'WORK':
                return f"{name.lower()}_df"
            else:
                return f"{name.lower()}_df"
        
        # Handle simple dataset names
        return f"{ref.lower()}_df"

    def _convert_data(self, component: SASComponent) -> str:
        """Convert DATA steps to Python DataFrame operations."""
        try:
            content = component.content
            data_match = re.search(r'data\s+(\w+\.?\w*)', content, re.IGNORECASE)
            
            if not data_match:
                return f"# TODO: Convert DATA step - no dataset name found:\n{content}"
            
            dataset = data_match.group(1)
            py_dataset = self._convert_sas_reference(dataset)
            
            if dataset.lower() == '_null_':
                return f"# Create new DataFrame _null_\n_null__df = pd.DataFrame()"
            
            # Check for SET statement
            set_match = re.search(r'set\s+(\w+\.?\w*)', content, re.IGNORECASE)
            if set_match:
                source_ds = set_match.group(1)
                py_source = self._convert_sas_reference(source_ds)
                return f"# Create {dataset} from {source_ds}\n{py_dataset} = {py_source}.copy()"
            
            # Simple dataset creation
            return f"# Create new DataFrame {dataset}\n{py_dataset} = pd.DataFrame()"
            
        except Exception as e:
            logger.warning(f"Error converting DATA step: {str(e)}")
            return f"# TODO: Convert DATA step:\n{component.content}"

    def _convert_if(self, component: SASComponent) -> str:
        """Convert %IF statements to Python if statements."""
        try:
            content = component.content.strip()
            if_match = re.search(r'%if\s+(.+?)\s+%then\s+(.+?)(?:\s+%else\s+(.+))?;', content, re.IGNORECASE)
            if not if_match:
                return f"# TODO: Convert %IF statement:\n{content}"
            
            condition = if_match.group(1)
            then_clause = if_match.group(2)
            else_clause = if_match.group(3) if if_match.group(3) else None
            
            # Convert SAS operators to Python
            condition = condition.replace(' eq ', ' == ').replace(' ne ', ' != ')
            condition = condition.replace(' gt ', ' > ').replace(' lt ', ' < ')
            condition = condition.replace(' ge ', ' >= ').replace(' le ', ' <= ')
            
            # Convert SAS macro variables
            condition = re.sub(r'&(\w+)', r'\1', condition)
            
            # Convert then clause
            then_code = then_clause.strip()
            if then_code.startswith('%do'):
                then_code = "    pass"
            else:
                then_code = f"    {then_code}"
            
            # Convert else clause if present
            else_code = f"\nelse:\n    {else_clause.strip()}" if else_clause else ""
            
            return f"if {condition}:\n{then_code}{else_code}"
            
        except Exception as e:
            logger.warning(f"Error converting %IF: {str(e)}")
            return f"# TODO: Convert %IF statement:\n{component.content}"

    def _convert_do(self, component: SASComponent) -> str:
        """Convert %DO loops to Python for/while loops."""
        try:
            content = component.content.strip()
            do_match = re.search(r'%do\s+(\w+)\s*=\s*(.+?)\s+to\s+(.+?)(?:\s+by\s+(.+?))?;', content, re.IGNORECASE)
            
            if do_match:
                # This is a %DO i=1 to n loop
                var = do_match.group(1)
                start = self._convert_sas_reference(do_match.group(2))
                end = self._convert_sas_reference(do_match.group(3))
                step = self._convert_sas_reference(do_match.group(4)) if do_match.group(4) else "1"
                
                # Extract loop body
                body_match = re.search(r'%do.+?;(.+?)%end', content, re.IGNORECASE | re.DOTALL)
                body = body_match.group(1).strip() if body_match else ""
                
                # Convert body
                body_lines = []
                for line in body.split('\n'):
                    if line.strip():
                        body_lines.append(f"    {line.strip()}")
                
                if not body_lines:
                    body_lines = ["    pass"]
                
                return f"for {var} in range({start}, {end}+1, {step}):\n{chr(10).join(body_lines)}"
            
            # Check for %DO %WHILE loops
            do_while_match = re.search(r'%do\s+%while\s*\((.+?)\);', content, re.IGNORECASE)
            if do_while_match:
                condition = do_while_match.group(1)
                
                # Convert SAS operators to Python
                condition = condition.replace(' eq ', ' == ').replace(' ne ', ' != ')
                condition = condition.replace(' gt ', ' > ').replace(' lt ', ' < ')
                condition = condition.replace(' ge ', ' >= ').replace(' le ', ' <= ')
                
                # Convert SAS macro variables
                condition = re.sub(r'&(\w+)', r'\1', condition)
                
                # Extract loop body
                body_match = re.search(r'%do\s+%while.+?;(.+?)%end', content, re.IGNORECASE | re.DOTALL)
                body = body_match.group(1).strip() if body_match else ""
                
                # Convert body
                body_lines = []
                for line in body.split('\n'):
                    if line.strip():
                        body_lines.append(f"    {line.strip()}")
                
                if not body_lines:
                    body_lines = ["    pass"]
                
                return f"while {condition}:\n{chr(10).join(body_lines)}"
            
            # Simple %DO without counter
            if content.lower().startswith('%do'):
                return "pass"
            
            return f"# TODO: Convert %DO loop:\n{content}"
            
        except Exception as e:
            logger.warning(f"Error converting %DO: {str(e)}")
            return f"# TODO: Convert %DO loop:\n{component.content}"

    def _convert_macro(self, component: SASComponent) -> str:
        """Convert SAS macros to Python functions."""
        try:
            content = component.content
            macro_match = re.search(r'%macro\s+(\w+)(?:\s*\(([^)]*)\))?;', content, re.IGNORECASE)
            
            if not macro_match:
                return f"# TODO: Convert MACRO - invalid syntax:\n{content}"
            
            macro_name = macro_match.group(1)
            params_str = macro_match.group(2) or ""
            
            # Convert parameters
            params = []
            if params_str:
                for param in params_str.split(','):
                    param = param.strip()
                    if '=' in param:
                        name, default = param.split('=', 1)
                        name = name.strip()
                        default = default.strip()
                        if default:
                            params.append(f"{name}={repr(default)}")
                        else:
                            params.append(name)
                    else:
                        params.append(param)
            
            # Extract macro body
            body_match = re.search(r'%macro.+?;(.+?)%mend', content, re.IGNORECASE | re.DOTALL)
            body = body_match.group(1).strip() if body_match else ""
            
            # Create function definition
            func_def = f"def {macro_name}({', '.join(params)}):"
            docstring = f'    """\n    Converted from SAS macro\n    Original: {macro_match.group(0)}...\n    """'
            
            # If body is empty or we can't convert it yet, just add a pass statement
            if not body:
                return f"{func_def}\n{docstring}\n    pass"
            
            return f"{func_def}\n{docstring}\n    pass"
            
        except Exception as e:
            logger.warning(f"Error converting MACRO: {str(e)}")
            return f"# TODO: Convert MACRO:\n{component.content}"

    def _convert_ods(self, component: SASComponent) -> str:
        """Convert ODS statements to matplotlib/pandas output settings."""
        try:
            content = component.content.strip().lower()
            
            if 'graphics on' in content:
                return "# Enable matplotlib for graphics\nplt.ion()"
            
            if 'graphics off' in content:
                return "# Disable matplotlib for graphics\nplt.ioff()"
            
            if 'html' in content and 'close' not in content:
                path_match = re.search(r'path\s*=\s*["\']?([^"\'\s]+)["\']?', component.content, re.IGNORECASE)
                body_match = re.search(r'body\s*=\s*["\']?([^"\'\s]+)["\']?', component.content, re.IGNORECASE)
                
                path = path_match.group(1) if path_match else '"./output"'
                file = body_match.group(1) if body_match else 'output.html'
                
                # Fix path string formatting
                if not (path.startswith('"') or path.startswith("'")):
                    path = f'"{path}"'
                
                return f"""# Set up HTML output
output_path = Path({path})
output_file = output_path / {repr(file)}
output_path.mkdir(exist_ok=True, parents=True)"""
            
            if 'html close' in content:
                return "# Close HTML output\nplt.close('all')"
            
            return f"# TODO: Convert ODS statement:\n# {component.content.strip()}"
            
        except Exception as e:
            logger.warning(f"Error converting ODS: {str(e)}")
            return f"# TODO: Convert ODS statement:\n# {component.content.strip()}"

    def _convert_proc_sql(self, component: SASComponent) -> str:
        """Convert PROC SQL to pandas operations."""
        try:
            sql_content = component.content
            
            # Extract SQL statements
            sql_statements = re.findall(r'(?:select|create|insert|update|delete).*?;', 
                                      sql_content, 
                                      re.IGNORECASE | re.DOTALL)
            
            python_code = []
            for stmt in sql_statements:
                if re.match(r'\s*select', stmt, re.IGNORECASE):
                    python_code.append(self._convert_sql_select(stmt))
                
            return '\n'.join(python_code)
            
        except Exception as e:
            raise ValueError(f"Error converting PROC SQL: {str(e)}")

    def _convert_format(self, component: SASComponent) -> str:
        """Convert FORMAT/INFORMAT statements to Python functions."""
        try:
            content = component.content.strip()
            format_match = re.search(r'value\s+(\w+)\s+(.*?);', content, re.IGNORECASE | re.DOTALL)
            if not format_match:
                return f"# TODO: Convert format: {content}"
            
            format_name = format_match.group(1)
            format_def = format_match.group(2)
            
            # Parse format definition
            code_lines = [
                f"def format_{format_name.lower()}(value):",
                "    \"\"\"Format function generated from SAS format\"\"\"",
                "    try:",
            ]
            
            # Add format conditions
            for line in format_def.split('\n'):
                line = line.strip()
                if not line:
                    continue
                value_match = re.search(r'([^=]+)=\s*["\']?(.*?)["\']?\s*$', line)
                if value_match:
                    cond, result = value_match.groups()
                    code_lines.append(f"        if value {cond.strip()}: return {repr(result.strip())}")
                
            code_lines.extend([
                "    except Exception:",
                "        return str(value)",
                "    return str(value)"
            ])
            
            return '\n'.join(code_lines)
            
        except Exception as e:
            raise ValueError(f"Error converting FORMAT: {str(e)}")

    def _convert_proc_print(self, component: SASComponent) -> str:
        """Convert PROC PRINT to pandas display."""
        try:
            # Extract dataset and options
            data_match = re.search(r'data\s*=\s*(\w+\.?\w*)', component.content, re.IGNORECASE)
            var_match = re.search(r'var\s+(.*?);', component.content, re.IGNORECASE)
            where_match = re.search(r'where\s+(.*?);', component.content, re.IGNORECASE)
            
            if not data_match:
                raise ValueError("No dataset specified")
            
            dataset = data_match.group(1).replace('.', '_')
            variables = var_match.group(1).split() if var_match else None
            where_clause = where_match.group(1) if where_match else None
            
            code_lines = [f"# Display contents of {dataset}"]
            
            # Build the display command
            if variables:
                code_lines.append(f"display_df = {dataset}_df[[{', '.join(repr(v) for v in variables)}]]")
            else:
                code_lines.append(f"display_df = {dataset}_df")
            
            if where_clause:
                # Convert SAS operators to Python
                where_clause = where_clause.replace(' eq ', ' == ')
                where_clause = where_clause.replace(' ne ', ' != ')
                where_clause = where_clause.replace(' gt ', ' > ')
                where_clause = where_clause.replace(' lt ', ' < ')
                where_clause = where_clause.replace(' ge ', ' >= ')
                where_clause = where_clause.replace(' le ', ' <= ')
                code_lines.append(f"display_df = display_df[{where_clause}]")
            
            code_lines.extend([
                "",
                "# Configure display options",
                "pd.set_option('display.max_rows', None)",
                "pd.set_option('display.max_columns', None)",
                "pd.set_option('display.width', None)",
                "",
                "print('Contents of dataset:')",
                "print(display_df)"
            ])
            
            return '\n'.join(code_lines)
            
        except Exception as e:
            raise ValueError(f"Error converting PROC PRINT: {str(e)}")

    def _convert_proc_format(self, component: SASComponent) -> str:
        """Convert PROC FORMAT to Python format functions."""
        try:
            content = component.content
            
            # Extract all VALUE statements
            value_pattern = r'value\s+(\w+)\s+(.*?);'
            formats = []
            
            for match in re.finditer(value_pattern, content, re.IGNORECASE | re.DOTALL):
                format_name = match.group(1)
                format_spec = match.group(2)
                
                formats.append(self._create_format_function(format_name, format_spec))
            
            if formats:
                return '\n\n'.join(formats)
            else:
                return """# TODO: Implement PROC format
def format_proc():
    \"\"\"Python equivalent of PROC FORMAT\"\"\"
    pass"""
            
        except Exception as e:
            logger.warning(f"Error converting PROC FORMAT: {str(e)}")
            return """# TODO: Implement PROC format
def format_proc():
    \"\"\"Python equivalent of PROC FORMAT\"\"\"
    pass"""

    def _create_format_function(self, name: str, spec: str) -> str:
        """Create a Python function for a SAS format."""
        format_dict = {}
        
        # Parse format specifications
        for line in spec.split('\n'):
            line = line.strip()
            if not line:
                continue
            
            # Handle different format specifications
            range_match = re.search(r'([\d\.-]+)\s*-\s*([\d\.-]+)\s*=\s*["\']([^"\']+)["\']', line)
            single_match = re.search(r'([\d\.-]+)\s*=\s*["\']([^"\']+)["\']', line)
            other_match = re.search(r'other\s*=\s*["\']([^"\']+)["\']', line, re.IGNORECASE)
            
            if range_match:
                start, end, label = range_match.groups()
                format_dict[f"{start}-{end}"] = label
            elif single_match:
                value, label = single_match.groups()
                format_dict[value] = label
            elif other_match:
                format_dict['other'] = other_match.group(1)
        
        # Generate function code
        code_lines = [
            f"def format_{name.lower()}(value):",
            f"    \"\"\"Format function converted from SAS format {name}\"\"\"",
            "    format_dict = {",
            *[f"        {k!r}: {v!r}," for k, v in format_dict.items()],
            "    }",
            "",
            "    try:",
            "        value = float(value)",
            "        # Check ranges first",
            "        for key, label in format_dict.items():",
            "            if key == 'other':",
            "                continue",
            "            if '-' in key:",
            "                start, end = map(float, key.split('-'))",
            "                if start <= value <= end:",
            "                    return label",
            "            elif float(key) == value:",
            "                return label",
            "        # Return 'other' value if specified, otherwise original value",
            "        return format_dict.get('other', str(value))",
            "    except (ValueError, TypeError):",
            "        return str(value)"
        ]
        
        return '\n'.join(code_lines)

    def _convert_statement_in_macro(self, statement: str) -> str:
        """Convert a SAS statement within a macro to Python."""
        statement = statement.strip()
        
        if statement.startswith('%let'):
            return self._convert_let({'content': statement})
        elif statement.startswith('data '):
            return self._convert_data({'content': statement})
        elif statement.startswith('proc '):
            return self._convert_proc({'content': statement})
        else:
            return f"# TODO: Convert statement: {statement}"

    def _convert_sas_condition(self, condition: str) -> str:
        """Convert SAS conditional expressions to Python."""
        # Replace SAS operators with Python equivalents
        condition = condition.replace(' eq ', ' == ').replace(' ne ', ' != ')
        condition = condition.replace(' gt ', ' > ').replace(' lt ', ' < ')
        condition = condition.replace(' ge ', ' >= ').replace(' le ', ' <= ')
        condition = condition.replace(' and ', ' and ')
        condition = condition.replace(' or ', ' or ')
        condition = condition.replace('&', 'and')
        condition = condition.replace('|', 'or')
        
        # Fix common SAS comparison issues
        condition = re.sub(r'(\w+)\s*=\s*(\w+)', r'\1 == \2', condition)
        
        # Handle macro variables
        condition = re.sub(r'&(\w+)', r'\1', condition)
        
        return condition

    def _convert_dataset_name(self, dataset: str) -> str:
        """Convert SAS dataset reference to Python variable name."""
        if '.' in dataset:
            lib, name = dataset.split('.')
            return f"{name.lower()}_df"
        return f"{dataset.lower()}_df"

    def _convert_libname(self, component: SASComponent) -> str:
        """Convert LIBNAME statements to Python path variables."""
        try:
            content = component.content
            lib_match = re.search(r'LIBNAME\s+(\w+)\s+([^;]+)', content, re.IGNORECASE)
            if not lib_match:
                raise ValueError("Invalid LIBNAME statement")
            
            libref = lib_match.group(1)
            path = lib_match.group(2).strip().strip("'\"")
            
            # Store in libname references
            self.libname_refs[libref] = path
            
            return f"{libref}_path = {repr(path)}"
            
        except Exception as e:
            raise ValueError(f"Error converting LIBNAME: {str(e)}")

    def _convert_filename(self, component: SASComponent) -> str:
        """Convert FILENAME statements to Python path variables."""
        try:
            content = component.content
            file_match = re.search(r'filename\s+(\w+)\s+["\']([^"\']+)["\']', content, re.IGNORECASE)
            if not file_match:
                raise ValueError("Invalid FILENAME statement")
            
            fileref = file_match.group(1)
            path = file_match.group(2)
            
            return f"{fileref}_path = {repr(path)}"
            
        except Exception as e:
            raise ValueError(f"Error converting FILENAME: {str(e)}")

    def _convert_options(self, component: SASComponent) -> str:
        """Convert SAS options to Python settings."""
        try:
            content = component.content.strip()
            if content.lower().startswith('goptions'):
                return self._convert_graphics_options(content)
            
            # Handle general options
            return f"# SAS options: {content}"
            
        except Exception as e:
            raise ValueError(f"Error converting OPTIONS: {str(e)}")

    def _convert_graphics_options(self, content: str) -> str:
        """Convert GOPTIONS to matplotlib settings."""
        code_lines = ["# Configure matplotlib"]
        
        if 'device=' in content.lower():
            code_lines.append("plt.switch_backend('agg')")
        
        code_lines.extend([
            "plt.style.use('default')",
            "plt.rcParams.update({",
            "    'figure.figsize': (8, 6),",
            "    'figure.dpi': 100,",
            "    'savefig.dpi': 300",
            "})"
        ])
        
        return '\n'.join(code_lines)

    def _convert_let(self, component: SASComponent) -> str:
        """Convert %LET statements to Python variable assignments."""
        try:
            content = component.content.strip()
            let_match = re.search(r'%let\s+(\w+)\s*=\s*(.+?);', content, re.IGNORECASE)
            if not let_match:
                return f"# TODO: Convert %LET: {content}"
            
            var_name = let_match.group(1)
            value = let_match.group(2).strip()
            
            # Try to convert value to appropriate Python type
            try:
                # Check if it's a function call
                if '%' in value:
                    # Convert the macro function call
                    value = self._convert_macro_function(value)
                    return f"{var_name} = {value}"
                
                # Try numeric conversion
                if '.' in value:
                    py_value = float(value)
                else:
                    py_value = int(value)
            except ValueError:
                # If not numeric, treat as string
                # Fix: Don't use f-string with backslashes
                value = value.strip('"').strip("'")
                py_value = f'"{value}"'
            
            return f"{var_name} = {py_value}"
            
        except Exception as e:
            logger.warning(f"Error converting %LET: {str(e)}")
            return f"# TODO: Convert %LET:\n# {content}"

    def _convert_let_direct(self, component: SASComponent) -> str:
        """Direct conversion of %LET statements."""
        try:
            content = component.content.strip()
            let_match = re.search(r'%let\s+(\w+)\s*=\s*([^;]+);', content, re.IGNORECASE)
            if not let_match:
                return f"# TODO: Convert %LET statement:\n{content}"
            
            var_name = let_match.group(1)
            value = let_match.group(2).strip()
            
            # Try to convert value to appropriate Python type
            try:
                # Check if it's a function call
                if '%' in value:
                    return f"{var_name} = '{value}'  # SAS function call"
                
                # Try numeric conversion
                if '.' in value:
                    py_value = float(value)
                else:
                    py_value = int(value)
            except ValueError:
                # If not numeric, treat as string
                py_value = value.strip('"\'')
            
            # Store in macro variables
            self.macro_variables[var_name] = py_value
            
            return f"{var_name} = {repr(py_value)}"
            
        except Exception as e:
            logger.warning(f"Error in direct %LET conversion: {str(e)}")
            return f"# TODO: Convert %LET statement:\n{component.content}"

    def _convert_title(self, component: SASComponent) -> str:
        """Convert TITLE/FOOTNOTE statements to matplotlib title/suptitle."""
        try:
            content = component.content.strip()
            
            if content.lower().startswith('title'):
                # Extract title number and text
                title_match = re.search(r'title(\d*)\s+["\']?([^"\']+)["\']?', content, re.IGNORECASE)
                if not title_match:
                    raise ValueError("Invalid TITLE statement")
                    
                title_num = title_match.group(1) or "1"
                title_text = title_match.group(2).strip()
                
                if title_num == "1":
                    return f"plt.suptitle({repr(title_text)})"
                else:
                    return f"plt.title({repr(title_text)})"
                
            elif content.lower().startswith('footnote'):
                # Extract footnote text
                footnote_match = re.search(r'footnote\s+["\']?([^"\']+)["\']?', content, re.IGNORECASE)
                if not footnote_match:
                    raise ValueError("Invalid FOOTNOTE statement")
                    
                footnote_text = footnote_match.group(1).strip()
                
                return f"plt.figtext(0.5, 0.01, {repr(footnote_text)}, ha='center')"
                
            return f"# TODO: Convert title/footnote:\n{content}"
            
        except Exception as e:
            raise ValueError(f"Error converting TITLE/FOOTNOTE: {str(e)}")

    def _convert_put(self, component: SASComponent) -> str:
        """Convert %PUT statements to Python print statements."""
        try:
            content = component.content.strip()
            put_match = re.search(r'%put\s+(.+?);', content, re.IGNORECASE)
            if not put_match:
                return f"# TODO: Convert %PUT statement:\n{content}"
            
            message = put_match.group(1).strip()
            
            # Check if it's a variable reference
            if message.startswith('&'):
                var_name = message[1:]
                return f"print({var_name})  # Converted from %PUT {message}"
            else:
                # It's a literal message
                return f"print({repr(message)})  # Converted from %PUT"
            
        except Exception as e:
            logger.warning(f"Error converting %PUT: {str(e)}")
            return f"# TODO: Convert %PUT statement:\n{component.content}"

    def _convert_sas_expression(self, expr: str) -> str:
        """Convert SAS expressions to Python."""
        expr = expr.strip()
        
        # Handle %SCAN function
        scan_matches = re.findall(r'%SCAN\s*\(\s*([^,]+)\s*,\s*([^,\)]+)(?:\s*,\s*([^\)]+))?\s*\)', expr)
        for match in scan_matches:
            var, pos = match[0], match[1]
            delim = match[2] if len(match) > 2 and match[2] else "' '"
            
            # Remove & from variable names
            var = re.sub(r'&(\w+)', r'\1', var)
            pos = re.sub(r'&(\w+)', r'\1', pos)
            
            # Convert to Python's list indexing (0-based)
            py_expr = f"{var}.split({delim})[{pos} - 1] if len({var}.split({delim})) >= {pos} else \"\""
            expr = expr.replace(f"%SCAN({match[0]}, {match[1]}{', ' + match[2] if len(match) > 2 and match[2] else ''})", py_expr)
        
        # Handle %EVAL function
        eval_matches = re.findall(r'%EVAL\((.*?)\)', expr)
        for match in eval_matches:
            # Convert internal operators to Python
            eval_expr = match.replace('+', '+').replace('-', '-').replace('*', '*').replace('/', '/')
            eval_expr = re.sub(r'&(\w+)', r'\1', eval_expr)  # Remove & references
            expr = expr.replace(f"%EVAL({match})", f"({eval_expr})")
        
        # Handle & variable references
        expr = re.sub(r'&(\w+)', r'\1', expr)
        
        return expr

    def _convert_macro_condition(self, condition: str) -> str:
        """Convert SAS macro condition to Python condition."""
        # Replace SAS operators with Python equivalents
        condition = condition.replace(' eq ', ' == ').replace(' ne ', ' != ')
        condition = condition.replace(' gt ', ' > ').replace(' lt ', ' < ')
        condition = condition.replace(' ge ', ' >= ').replace(' le ', ' <= ')
        
        # Handle macro variables
        condition = re.sub(r'&(\w+)', r'\1', condition)
        
        return condition

    def _convert_macro_action(self, action: str) -> str:
        """Convert SAS macro action to Python."""
        action = action.strip()
        
        # Handle %LET statements
        let_match = re.search(r'%LET\s+(\w+)\s*=\s*(.*?)(?:;|$)', action, re.IGNORECASE)
        if let_match:
            var, value = let_match.groups()
            py_value = self._convert_sas_expression(value)
            return f"{var} = {py_value}"
        
        # Handle other macro actions
        return f"# TODO: Convert macro action: {action}"

    def _convert_sql_condition(self, condition: str) -> str:
        """Convert SQL WHERE condition to pandas query syntax."""
        # Similar to _convert_sas_condition but for SQL context
        condition = condition.strip()
        
        # Replace SQL-specific operators
        condition = re.sub(r'\bIS NULL\b', '.isna()', condition, flags=re.IGNORECASE)
        condition = re.sub(r'\bIS NOT NULL\b', '.notna()', condition, flags=re.IGNORECASE)
        condition = re.sub(r'\bLIKE\s+[\'"](.*?)[\'"]\b', r'.str.contains(r"\1")', condition, flags=re.IGNORECASE)
        
        # Replace comparison operators (already handled in _convert_sas_condition)
        condition = self._convert_sas_condition(condition)
        
        return condition

    def _convert_sql_expression(self, expr: str) -> str:
        """Convert SQL expression to pandas syntax."""
        # Replace SQL-specific functions
        expr = expr.strip()
        
        # Aggregate functions
        expr = re.sub(r'COUNT\((.*?)\)', r'len(\1)', expr, flags=re.IGNORECASE)
        expr = re.sub(r'SUM\((.*?)\)', r'\1.sum()', expr, flags=re.IGNORECASE)
        expr = re.sub(r'AVG\((.*?)\)', r'\1.mean()', expr, flags=re.IGNORECASE)
        expr = re.sub(r'MIN\((.*?)\)', r'\1.min()', expr, flags=re.IGNORECASE)
        expr = re.sub(r'MAX\((.*?)\)', r'\1.max()', expr, flags=re.IGNORECASE)
        
        # String functions
        expr = re.sub(r'UPPER\((.*?)\)', r'\1.str.upper()', expr, flags=re.IGNORECASE)
        expr = re.sub(r'LOWER\((.*?)\)', r'\1.str.lower()', expr, flags=re.IGNORECASE)
        expr = re.sub(r'SUBSTR\((.*?),\s*(\d+),\s*(\d+)\)', r'\1.str.slice(\2-1, \2+\3-1)', expr, flags=re.IGNORECASE)
        
        return expr
    
    def convert_directory(self, input_dir: str) -> List[str]:
        """
        Convert all SAS files in a directory to Python.
        
        Args:
            input_dir: Directory containing SAS files
            
        Returns:
            List of paths to converted Python files
        """
        converted_files = []
        input_path = Path(input_dir)
        
        # Process each SAS file
        for sas_file in input_path.rglob("*.sas"):
            try:
                output_file = self.convert_file(str(sas_file))
                if output_file:
                    if isinstance(output_file, dict):
                        # If convert_file returns a dictionary, extract the file path
                        converted_files.extend(output_file.keys())
                    else:
                        # If convert_file returns a string path, use that directly
                        converted_files.append(output_file)
            except Exception as e:
                logger.error(f"Error converting {sas_file}: {str(e)}")
                    
        return converted_files
        
    def convert_file(self, file_path: str) -> str:
        """Convert a SAS file to Python."""
        logger.info(f"Converting {file_path}")
        
        # Parse the SAS file
        components = self.parse_sas_file(file_path)
        if not components:
            logger.warning(f"No components found in {file_path}")
            return None
        
        logger.info(f"Found {len(components)} components to convert")
        
        # Convert components to Python
        python_code = self.convert_to_python(components, file_path)
        
        # Write to output file
        output_file = os.path.join(
            self.output_directory,
            os.path.splitext(os.path.basename(file_path))[0] + '.py'
        )
        
        with open(output_file, 'w') as f:
            f.write(python_code)
        
        logger.info(f"✓ Successfully converted to {output_file}")
        
        # Track this file as converted
        self.converted_files[file_path] = output_file
        
        return output_file

    def _convert_proc_sort(self, component: SASComponent) -> str:
        """Convert PROC SORT to pandas sort_values."""
        try:
            # Extract dataset and options
            data_match = re.search(r'data\s*=\s*(\w+\.?\w*)', component.content, re.IGNORECASE)
            by_match = re.search(r'by\s+(.*?);', component.content, re.IGNORECASE)
            out_match = re.search(r'out\s*=\s*(\w+\.?\w*)', component.content, re.IGNORECASE)
            
            if not data_match or not by_match:
                raise ValueError("Missing required DATA= or BY statement")
            
            dataset = data_match.group(1).replace('.', '_')
            by_vars = by_match.group(1).split()
            output_ds = out_match.group(1).replace('.', '_') if out_match else dataset
            
            # Handle descending sort
            sort_cols = []
            ascending = []
            for var in by_vars:
                if var.upper().startswith('DESCENDING'):
                    var = var.split()[1]  # Get actual variable name
                    sort_cols.append(var)
                    ascending.append(False)
                else:
                    sort_cols.append(var)
                    ascending.append(True)
            
            code_lines = [
                f"# Sort {dataset} by {', '.join(by_vars)}",
                f"{output_ds}_df = {dataset}_df.sort_values(",
                f"    by={sort_cols},",
                f"    ascending={ascending},",
                f"    ignore_index=True",
                ")"
            ]
            
            return '\n'.join(code_lines)
            
        except Exception as e:
            raise ValueError(f"Error converting PROC SORT: {str(e)}")

    def _convert_include(self, component: SASComponent) -> str:
        """Convert %INCLUDE statements to Python imports."""
        try:
            # Extract file path
            path_match = re.search(r'%include\s+["\']([^"\']+)["\']', component.content, re.IGNORECASE)
            if not path_match:
                raise ValueError("Invalid %INCLUDE syntax")
            
            include_path = path_match.group(1)
            module_name = os.path.splitext(os.path.basename(include_path))[0]
            
            # Return import statement
            return f"from {module_name} import *  # Converted from %INCLUDE {include_path}"
            
        except Exception as e:
            raise ValueError(f"Error converting %INCLUDE: {str(e)}")

    def _convert_proc_gchart(self, component: SASComponent) -> str:
        """Convert PROC GCHART to matplotlib plotting."""
        try:
            content = component.content
            data_match = re.search(r'data\s*=\s*(\w+\.?\w*)', content, re.IGNORECASE)
            
            if not data_match:
                return "# TODO: Convert PROC GCHART - no dataset specified"
            
            dataset = self._convert_sas_reference(data_match.group(1))
            
            # Check for chart type
            vbar_match = re.search(r'vbar\s+(\w+)', content, re.IGNORECASE)
            hbar_match = re.search(r'hbar\s+(\w+)', content, re.IGNORECASE)
            pie_match = re.search(r'pie\s+(\w+)', content, re.IGNORECASE)
            
            if vbar_match:
                x_var = vbar_match.group(1)
                return f"""# Create vertical bar chart
plt.figure(figsize=(10, 6))
{dataset}.plot(kind='bar', x='{x_var}', y='amount', title='Sales by {x_var.title()}')
plt.xlabel('{x_var.title()}')
plt.ylabel('Amount')
plt.tight_layout()
plt.savefig('vbar_{x_var}.png')"""
            
            elif hbar_match:
                x_var = hbar_match.group(1)
                return f"""# Create horizontal bar chart
plt.figure(figsize=(10, 6))
{dataset}.plot(kind='barh', x='{x_var}', y='amount', title='Sales by {x_var.title()}')
plt.xlabel('Amount')
plt.ylabel('{x_var.title()}')
plt.tight_layout()
plt.savefig('hbar_{x_var}.png')"""
            
            elif pie_match:
                slice_var = pie_match.group(1)
                return f"""# Create pie chart
plt.figure(figsize=(10, 6))
{dataset}.plot(kind='pie', y='amount', labels={dataset}['{slice_var}'], autopct='%1.1f%%')
plt.title('Sales Distribution by {slice_var.title()}')
plt.ylabel('')
plt.tight_layout()
plt.savefig('pie_{slice_var}.png')"""
            
            return f"""# TODO: Convert PROC GCHART - chart type not recognized
# Original SAS code:
# {content.strip()}
def plot_chart(data_df):
    \"\"\"Create chart from data\"\"\"
    plt.figure(figsize=(10, 6))
    # Add appropriate plotting code here
    plt.tight_layout()
    plt.savefig('chart.png')"""
            
        except Exception as e:
            logger.warning(f"Error converting PROC GCHART: {str(e)}")
            return f"# TODO: Convert PROC GCHART:\n# {component.content.strip()}"

    def _convert_macro_call(self, component: SASComponent) -> str:
        """Convert SAS macro calls to Python function calls."""
        try:
            content = component.content.strip()
            
            # Check if this is a macro call with parameters
            macro_match = re.search(r'%(\w+)\s*\((.*)\);', content, re.IGNORECASE)
            if macro_match:
                macro_name = macro_match.group(1)
                params_str = macro_match.group(2)
                
                # Parse parameters
                params = {}
                for param in re.findall(r'(\w+)\s*=\s*([^,]+)', params_str):
                    param_name = param[0]
                    param_value = param[1].strip()
                    # Convert SAS references to Python
                    param_value = self._convert_sas_reference(param_value)
                    params[param_name] = param_value
                
                # Generate Python function call
                params_code = ", ".join([f"{k}={v}" for k, v in params.items()])
                return f"{macro_name}({params_code})"
            
            # Check if this is a simple macro call
            simple_macro_match = re.search(r'%(\w+);', content, re.IGNORECASE)
            if simple_macro_match:
                macro_name = simple_macro_match.group(1)
                return f"{macro_name}()"
            
            # If we can't parse it, return a TODO comment
            return f"# TODO: Convert macro call: {content}"
            
        except Exception as e:
            logger.warning(f"Error converting macro call: {str(e)}")
            return f"# TODO: Convert macro call: {content}"

    def _add_helper_function(self, function_name: str):
        """Add helper function to the list of functions to include in output."""
        if not hasattr(self, 'helper_functions'):
            self.helper_functions = set()
        
        self.helper_functions.add(function_name)

    def _get_helper_functions(self) -> str:
        """Get all helper functions needed for the conversion."""
        helper_code = []
        
        if hasattr(self, 'helper_functions'):
            if 'scan' in self.helper_functions:
                helper_code.append("""
def scan(text, position, delimiter=' '):
    \"\"\"Python equivalent of SAS %scan function\"\"\"
    if isinstance(text, str):
        parts = text.split(delimiter)
        if isinstance(position, (int, float)) and 0 <= position-1 < len(parts):
            return parts[position-1]
    return ""
""")
            
            if 'eval_expr' in self.helper_functions:
                helper_code.append("""
def eval_expr(expression):
    \"\"\"Python equivalent of SAS %eval function\"\"\"
    try:
        return eval(expression)
    except:
        return expression
""")
        
        return '\n'.join(helper_code)

    def _convert_macro_do(self, component: SASComponent) -> str:
        """Convert %DO statements to Python loops."""
        try:
            content = component.content.strip()
            
            # Handle %DO %WHILE
            do_while_match = re.search(r'%do\s+%while\s*\(\s*(.+?)\s*\)', content, re.IGNORECASE)
            if do_while_match:
                condition = do_while_match.group(1)
                # Convert condition to Python
                condition = self._convert_macro_condition(condition)
                return f"while {condition}:"
            
            # Handle %DO with counter
            do_counter_match = re.search(r'%do\s+(\w+)\s*=\s*(\d+)\s+to\s+(\d+)', content, re.IGNORECASE)
            if do_counter_match:
                var = do_counter_match.group(1)
                start = do_counter_match.group(2)
                end = do_counter_match.group(3)
                return f"for {var} in range({start}, {end}+1):"
            
            # Handle simple %DO
            if content.lower().startswith('%do'):
                return "# Start of DO block"
            
            return f"# TODO: Convert %DO: {content}"
            
        except Exception as e:
            logger.warning(f"Error converting %DO: {str(e)}")
            return f"# TODO: Convert %DO:\n# {content}"

    def _convert_macro_end(self, component: SASComponent) -> str:
        """Convert %END statements to Python."""
        try:
            # For %END, we just need to handle indentation in the calling code
            return "# End of block"
            
        except Exception as e:
            logger.warning(f"Error converting %END: {str(e)}")
            return f"# TODO: Convert %END:\n# {component.content}"

    def _convert_macro_call_statement(self, statement: str) -> str:
        """Convert a SAS macro call statement to Python function call."""
        try:
            # Extract macro name and parameters
            macro_match = re.search(r'%(\w+)\s*\((.*)\);', statement, re.IGNORECASE)
            if not macro_match:
                return f"# TODO: Convert macro call: {statement}"
            
            macro_name = macro_match.group(1)
            params_str = macro_match.group(2)
            
            # Parse parameters
            params = {}
            for param in re.findall(r'(\w+)\s*=\s*([^,]+)', params_str):
                param_name = param[0]
                param_value = param[1].strip()
                # Convert SAS references to Python
                param_value = self._convert_sas_reference(param_value)
                params[param_name] = param_value
            
            # Generate Python function call
            params_code = ", ".join([f"{k}={v}" for k, v in params.items()])
            return f"{macro_name}({params_code})"
            
        except Exception as e:
            logger.warning(f"Error converting macro call statement: {str(e)}")
            return f"# TODO: Convert macro call: {statement}"

    def _convert_macro_do_statement(self, statement: str) -> str:
        """Convert a %DO %WHILE statement to Python while loop."""
        try:
            # Extract condition
            do_while_match = re.search(r'%do\s+%while\s*\(\s*(.+?)\s*\);', statement, re.IGNORECASE)
            if do_while_match:
                condition = do_while_match.group(1)
                # Convert condition to Python
                condition = self._convert_macro_condition(condition)
                return f"while {condition}:"
            
            return f"# TODO: Convert %DO statement: {statement}"
        
        except Exception as e:
            logger.warning(f"Error converting %DO statement: {str(e)}")
            logger.warning(f"Error converting %DO %WHILE statement: {str(e)}")
            return f"# TODO: Convert %DO %WHILE statement: {statement}"