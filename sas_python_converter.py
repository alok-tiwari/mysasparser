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
from sas_parser import SASComponent, SASParser, SQLStatement
from embedding_generator import EmbeddingGenerator

# Import the additional PROC converters
try:
    from proc_converters import convert_proc_corr, convert_proc_reg, convert_proc_sgplot
except ImportError:
    # Fallback implementations if proc_converters is not available
    def convert_proc_corr(*args, **kwargs): 
        return "# PROC CORR conversion not available"
    def convert_proc_reg(*args, **kwargs): 
        return "# PROC REG conversion not available"
    def convert_proc_sgplot(*args, **kwargs): 
        return "# PROC SGPLOT conversion not available"
from proc_sql_converter import convert_proc_sql_enhanced

# Configure logging
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
logger = logging.getLogger('SASPythonConverter')

class SASPythonConverter:
    """
    Utility to convert SAS code to Python by retrieving components from a vector store
    and using embeddings for translation guidance.
    """
    
    def __init__(self, output_directory: str = "python_output", vector_store: Optional[VectorStore] = None, 
                 embedding_generator: Optional[EmbeddingGenerator] = None, input_directory: str = None):
        """
        Initialize the SAS to Python converter.
        
        Args:
            output_directory: Directory to write converted Python files
            vector_store: Vector store for embeddings
            embedding_generator: Embedding generator
            input_directory: Input directory for SAS files (used for relative paths)
        """
        self.output_directory = output_directory
        self.vector_store = vector_store
        self.embedding_generator = embedding_generator
        self.input_directory = input_directory
        self.helper_functions = set()
        self.macro_variables = {}
        
        # Create output directory if it doesn't exist
        os.makedirs(output_directory, exist_ok=True)
        
        # Initialize state tracking
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

    def _identify_datasets(self, components: List[SASComponent]) -> List[str]:
        """Identify all datasets referenced in the SAS code."""
        datasets = set()
        
        for component in components:
            # Look for dataset references in various components
            if component.type in ["DATA", "PROC", "PROC_SQL"]:
                # Find all dataset references
                refs = re.findall(r'(?:data|set|from|table)\s*=?\s*(\w+\.?\w*)', 
                                component.content, 
                                re.IGNORECASE)
                datasets.update(refs)
            
            # Also check for references in macro calls
            if '%' in component.content:
                refs = re.findall(r'data\s*=\s*(\w+\.?\w*)', component.content, re.IGNORECASE)
                datasets.update(refs)
        
        return list(datasets)

    def convert_to_python(self, components: List[SASComponent], file_path: str = None) -> str:
        """Convert SAS components to Python code."""
        python_code = []
        
        # Add standard imports and initialization
        python_code.extend([
            "import pandas as pd",
            "import numpy as np",
            "from scipy import stats",
            "import matplotlib.pyplot as plt",
            "import seaborn as sns",
            "from pathlib import Path",
            "import os",
            "",
            "# Initialize variables",
            "pd.set_option('display.max_rows', None)",
            "pd.set_option('display.max_columns', None)",
            "",
            "# Load required datasets",
            "def load_sashelp_dataset(name: str) -> pd.DataFrame:",
            "    \"\"\"Load a dataset from sashelp library.\"\"\"",
            "    try:",
            "        return pd.read_csv(f'sashelp_{name.lower()}.csv')",
            "    except Exception as e:",
            "        print(f'Error loading sashelp.{name}: {e}')",
            "        return pd.DataFrame()",
            ""
        ])

        # Track dataset names and their dependencies
        datasets = {}
        current_dataset = None

        # Process each component
        for component in components:
            try:
                if component.type == "PROC_SQL":
                    # Extract table name and structure from SQL
                    create_match = re.search(r'create\s+table\s+(\w+)\s+as\s*select\s+(.*?)\s+from\s+(.*?)(?:order\s+by|quit|;)', 
                                           component.content, re.IGNORECASE | re.DOTALL)
                    
                    if create_match:
                        table_name = create_match.group(1).replace('&', '')
                        columns = create_match.group(2)
                        from_clause = create_match.group(3)
                        current_dataset = table_name
                        
                        # Parse joins
                        joins = re.findall(r'left\s+join\s+&?(\w+)\s+(\w+)\s+on\s+([^(]*?)\s*(?=(?:left join|order by|$))', 
                                         component.content, re.IGNORECASE | re.DOTALL)
                        
                        # Build SQL conversion
                        sql_code = [
                            f"# Create SQL-based DataFrame",
                            f"{table_name}_df = {self._get_base_table(from_clause)}_df.copy()"
                        ]
                        
                        # Add joins
                        for table, alias, condition in joins:
                            table = table.replace('&', '')
                            join_conditions = self._parse_join_conditions(condition)
                            sql_code.append(
                                f"{table_name}_df = pd.merge({table_name}_df, {table}_df, "
                                f"how='left', {join_conditions})"
                            )
                        
                        # Add ORDER BY if present
                        order_match = re.search(r'order\s+by\s+(.*?)(?:quit|;)', component.content, re.IGNORECASE)
                        if order_match:
                            order_cols = [col.strip() for col in order_match.group(1).split(',')]
                            sql_code.append(f"{table_name}_df = {table_name}_df.sort_values(by={order_cols})")
                        
                        python_code.extend(sql_code)
                        python_code.append("")
                
                elif '%PARAMETER_Join_Parameter' in component.content:
                    params = self._parse_macro_parameters(component.content)
                    if params:
                        table_name = params.get('table')
                        param_name = params.get('param')
                        if table_name and param_name:
                            python_code.extend([
                                f"# Join parameters for {param_name}",
                                f"{table_name}_df = pd.merge(",
                                f"    {table_name}_df,",
                                "    parameters_df,",
                                "    how='left',",
                                f"    on='{param_name}'",
                                ")",
                                ""
                            ])
                
                elif component.type == "DATA":
                    # Extract dataset information
                    data_info = self._parse_data_step(component.content)
                    if data_info:
                        output_name = data_info['output'].replace('&', '')
                        input_name = data_info['input']
                        conditions = data_info['conditions']
                        
                        python_code.extend([
                            f"# Create output dataset",
                            f"{output_name}_df = {input_name}_df.copy()",
                            "",
                            "# Apply conditional logic",
                            "def apply_condition(row):",
                            f"    {self._convert_conditions(conditions)}",
                            "",
                            f"{output_name}_df['IR_VAR_DELTA'] = {output_name}_df.apply(apply_condition, axis=1)",
                            ""
                        ])

            except Exception as e:
                logger.warning(f"Error converting component {component.type}: {str(e)}")
                continue

        return '\n'.join(python_code)

    def _get_base_table(self, from_clause: str) -> str:
        """Extract base table name from FROM clause."""
        match = re.search(r'from\s+&?(\w+)', from_clause, re.IGNORECASE)
        if match:
            return match.group(1).replace('&', '')
        return 'input'

    def _parse_join_conditions(self, condition: str) -> str:
        """Parse JOIN conditions into pandas merge parameters."""
        conditions = condition.split('and')
        left_cols = []
        right_cols = []
        
        for cond in conditions:
            if '=' in cond:
                left, right = cond.split('=')
                left_cols.append(left.strip())
                right_cols.append(right.strip())
        
        if len(left_cols) == 1:
            return f"on='{left_cols[0]}'"
        return f"left_on={left_cols}, right_on={right_cols}"

    def _parse_macro_parameters(self, content: str) -> Dict[str, str]:
        """Parse macro parameters into a dictionary."""
        param_match = re.search(r'%\w+\s*\(\s*(.*?)\s*\)', content, re.IGNORECASE)
        if not param_match:
            return {}
        
        params = {}
        param_list = param_match.group(1).split(',')
        
        for i, param in enumerate(param_list):
            param = param.strip()
            if '=' in param:
                key, value = param.split('=')
                params[key.strip()] = value.strip()
            elif i == 0:
                params['table'] = param
            elif i == 1:
                params['param'] = param
        
        return params

    def _parse_data_step(self, content: str) -> Dict[str, Any]:
        """Parse DATA step content into structured information."""
        data_info = {}
        
        # Extract dataset names
        output_match = re.search(r'data\s+&?(\w+)', content)
        set_match = re.search(r'set\s+(\w+)', content)
        
        if output_match and set_match:
            data_info['output'] = output_match.group(1)
            data_info['input'] = set_match.group(1)
            
            # Extract conditions
            if_match = re.search(r'if\s*\((.*?)\)\s*then\s*(.*?);(?:\s*else\s*(.*?);)?', 
                               content, re.IGNORECASE | re.DOTALL)
            if if_match:
                data_info['conditions'] = {
                    'if': if_match.group(1).strip(),
                    'then': if_match.group(2).strip(),
                    'else': if_match.group(3).strip() if if_match.group(3) else '0'
                }
        
        return data_info

    def _convert_conditions(self, conditions: Dict[str, str]) -> str:
        """Convert SAS conditions to Python code."""
        if_cond = conditions['if'].replace("'", '"')
        then_stmt = conditions['then']
        else_stmt = conditions['else']
        
        return f"if {if_cond}:\n        return {then_stmt}\n    else:\n        return {else_stmt}"

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
                'MACRO_CALL': self._convert_macro_call_enhanced,  # Use enhanced macro call converter
                '%LET': self._convert_let_direct,
                '%IF': self._convert_if,
                '%DO': self._convert_do,
                '%PUT': self._convert_put,
                'PROC_SQL': self._convert_proc_sql_enhanced,  # Use enhanced SQL converter
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
                return self._convert_proc_format(component)
            elif proc_name == 'sort':
                return self._convert_proc_sort(component)
            elif proc_name == 'gchart':
                return self._convert_proc_gchart(component)
            elif proc_name == 'sql':
                return self._convert_proc_sql_enhanced(component)  # Use enhanced SQL converter
            elif proc_name == 'sgplot':
                return self._convert_proc_sgplot(component)
            
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
            
            if not data_match:
                return "# TODO: Convert PROC TTEST - no dataset specified"
            
            dataset = self._convert_sas_reference(data_match.group(1))
            h0_value = h0_match.group(1) if h0_match else "0"
            alpha_value = alpha_match.group(1) if alpha_match else "0.05"
            
            # Remove any semicolons from alpha_value
            alpha_value = alpha_value.replace(';', '')
            
            # If alpha is a macro variable, convert it to a Python variable
            if alpha_value.startswith('&'):
                alpha_var = alpha_value[1:]  # Remove the & prefix
                # Add alpha variable to the beginning of the code
                alpha_def = f"alpha = 0.05  # Default value, replace with actual value\n"
                
                return f"""# Perform t-test
{alpha_def}for col in {dataset}.select_dtypes(include=['number']).columns:
    if {dataset}[col].notna().sum() > 1:  # Need at least 2 values for test
        t_stat, p_value = stats.ttest_1samp({dataset}[col].dropna(), {h0_value})
        print(f"T-test for {{col}}:")
        print(f"  T-statistic: {{t_stat:.4f}}")
        print(f"  P-value: {{p_value:.4f}}")
        print(f"  Significant at alpha={{alpha}}: {{p_value < alpha}}")"""
            else:
                return f"""# Perform t-test
for col in {dataset}.select_dtypes(include=['number']).columns:
    if {dataset}[col].notna().sum() > 1:  # Need at least 2 values for test
        t_stat, p_value = stats.ttest_1samp({dataset}[col].dropna(), {h0_value})
        print(f"T-test for {{col}}:")
        print(f"  T-statistic: {{t_stat:.4f}}")
        print(f"  P-value: {{p_value:.4f}}")
        print(f"  Significant at alpha={alpha_value}: {{p_value < {alpha_value}}}")"""
            
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
            lib = self._clean_variable_name(lib.lower())
            dataset = self._clean_variable_name(dataset.lower())
            return f"{dataset}_df"
        else:
            # Clean and return
            return self._clean_variable_name(ref.lower()) + "_df"

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
        """Convert ODS statements to Python equivalents."""
        try:
            content = component.content.lower()
            
            if 'ods graphics on' in content:
                return "# Enable matplotlib for graphics\nplt.style.use('ggplot')"
            
            elif 'ods graphics off' in content:
                return "# Disable matplotlib for graphics\nplt.close('all')"
            
            elif 'ods html' in content and 'close' in content:
                return "# Close HTML output\nplt.close('all')"
            
            elif 'ods html' in content:
                # Extract path and filename if available
                path_match = re.search(r'path\s*=\s*["\']([^"\']+)["\']', content)
                body_match = re.search(r'body\s*=\s*["\']([^"\']+)["\']', content)
                
                path = path_match.group(1) if path_match else "./output"
                filename = body_match.group(1) if body_match else "output.html"
                
                return f"""# Set up HTML output
output_path = Path("{path}")
output_path.mkdir(exist_ok=True, parents=True)
# HTML output will be saved to {path}/{filename}"""
            
            return f"# TODO: Convert ODS:\n# {component.content.strip()}"
            
        except Exception as e:
            logger.warning(f"Error converting ODS: {str(e)}")
            return f"# TODO: Convert ODS:\n# {component.content.strip()}"

    def _convert_ods_graphics(self, component: SASComponent) -> str:
        """Convert ODS GRAPHICS statements to matplotlib settings."""
        try:
            content = component.content.lower()
            
            if 'on' in content:
                return """# Enable matplotlib for graphics
plt.ion()"""
            elif 'off' in content:
                return """# Disable matplotlib for graphics
plt.ioff()"""
            
            # Extract height and width if present
            height_match = re.search(r'height\s*=\s*(\d+)', content)
            width_match = re.search(r'width\s*=\s*(\d+)', content)
            
            height = height_match.group(1) if height_match else "6"
            width = width_match.group(1) if width_match else "8"
            
            return f"""# Set matplotlib figure size
plt.rcParams['figure.figsize'] = ({width}, {height})"""
            
        except Exception as e:
            logger.warning(f"Error converting ODS GRAPHICS: {str(e)}")
            return f"# TODO: Convert ODS GRAPHICS:\n# {component.content.strip()}"

    def _convert_proc_sql_enhanced(self, component: SASComponent) -> str:
        """Enhanced converter for PROC SQL with complex joins."""
        try:
            content = component.content
            
            # Extract CREATE TABLE statement
            create_match = re.search(r'create\s+table\s+(\w+)\s+as\s*select\s+(.*?)\s+from\s+(.*?)(?:order\s+by|quit|;)', 
                                   content, re.IGNORECASE | re.DOTALL)
            
            if not create_match:
                return "# TODO: Convert PROC SQL - complex statement\n# " + content
                
            table_name = create_match.group(1)
            columns = create_match.group(2)
            from_clause = create_match.group(3)
            
            # Handle macro variables
            table_name = table_name.replace('&', '')
            from_clause = re.sub(r'&(\w+)', r'\1', from_clause)
            
            # Process joins
            python_code = [
                f"# Create SQL-based DataFrame",
                f"{table_name}_df = input_df.copy()"
            ]
            
            # Handle joins
            if 'left join' in content.lower():
                joins = re.findall(r'left\s+join\s+&?(\w+)\s+(\w+)\s+on\s+([^(]*?)\s*(?=(?:left join|order by|$))', 
                                 content, re.IGNORECASE | re.DOTALL)
                for table, alias, condition in joins:
                    join_condition = condition.replace('=', '==').strip()
                    python_code.append(
                        f"{table_name}_df = pd.merge({table_name}_df, {table}_df, "
                        f"how='left', left_on='{join_condition.split('==')[0].strip()}', "
                        f"right_on='{join_condition.split('==')[1].strip()}')"
                    )
            
            # Handle ORDER BY
            order_match = re.search(r'order\s+by\s+(.*?)(?:quit|;)', content, re.IGNORECASE)
            if order_match:
                order_cols = [col.strip() for col in order_match.group(1).split(',')]
                python_code.append(f"{table_name}_df = {table_name}_df.sort_values(by={order_cols})")
            
            return '\n'.join(python_code)
            
        except Exception as e:
            logger.warning(f"Error converting PROC SQL: {str(e)}")
            return f"# TODO: Convert PROC SQL:\n# {content}"

    def _convert_format(self, format_str: str) -> str:
        """Convert SAS format to Python format string."""
        # Handle common SAS formats
        if re.match(r'(\$?)\w+(\d+)\.(\d+)', format_str):
            # Extract width and decimal places
            match = re.match(r'(\$?)(\w+)(\d+)\.(\d+)', format_str)
            is_char = match.group(1) == '$'
            width = int(match.group(3))
            decimals = int(match.group(4))
            
            if is_char:
                return f"'{{:<{width}}}'  # {format_str}"
            else:
                return f"'{{:{width}.{decimals}f}}'  # {format_str}"
        
        # Handle date formats
        if format_str.lower() in ('date9.', 'mmddyy10.', 'yymmdd10.'):
            return f"'%Y-%m-%d'  # {format_str}"
        
        # Handle time formats
        if format_str.lower() in ('time8.', 'hhmm8.'):
            return f"'%H:%M:%S'  # {format_str}"
        
        # Default case
        return f"'{{}}' # Unknown format: {format_str}"

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
            range_match = re.search(r'([\w\.-]+)\s*-\s*([\w\.-]+)\s*=\s*["\']([^"\']+)["\']', line)
            single_match = re.search(r'([\w\.-]+)\s*=\s*["\']([^"\']+)["\']', line)
            other_match = re.search(r'other\s*=\s*["\']([^"\']+)["\']', line, re.IGNORECASE)
            string_match = re.search(r'["\']([^"\']+)["\']\s*=\s*["\']([^"\']+)["\']', line)
            
            if range_match:
                start, end, label = range_match.groups()
                format_dict[f"{start}-{end}"] = label
            elif single_match:
                value, label = single_match.groups()
                format_dict[value] = label
            elif other_match:
                format_dict['other'] = other_match.group(1)
            elif string_match:
                value, label = string_match.groups()
                format_dict[value] = label
        
        # Generate function code
        code_lines = [
            f"def format_{name.lower()}(value):",
            f"    \"\"\"Format function converted from SAS format {name}\"\"\"",
            "    format_dict = {",
            *[f"        {k!r}: {v!r}," for k, v in format_dict.items()],
            "    }",
            "",
            "    try:",
            "        # Handle string values first",
            "        if isinstance(value, str):",
            "            return format_dict.get(value, format_dict.get('other', value))",
            "            ",
            "        # Handle numeric values",
            "        # Check ranges first",
            "        for key, label in format_dict.items():",
            "            if key == 'other':",
            "                continue",
            "            if '-' in key:",
            "                start, end = key.split('-')",
            "                # Handle special values 'low' and 'high'",
            "                try:",
            "                    start_val = float('-inf') if start.lower() == 'low' else float(start)",
            "                    end_val = float('inf') if end.lower() == 'high' else float(end)",
            "                    if start_val <= value <= end_val:",
            "                        return label",
            "                except ValueError:",
            "                    # Skip non-numeric ranges when processing numeric values",
            "                    continue",
            "            else:",
            "                try:",
            "                    if float(key) == value:",
            "                        return label",
            "                except ValueError:",
            "                    # Skip non-numeric keys when processing numeric values",
            "                    continue",
            "        # Return 'other' value if specified, otherwise original value",
            "        return format_dict.get('other', str(value))",
            "    except (ValueError, TypeError):",
            "        # For any other errors, return the original value as string",
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
        """Convert SAS options to Python equivalents."""
        try:
            content = component.content.lower()
            
            options = []
            
            # Handle common options
            if 'nocenter' in content:
                options.append("# Set pandas display options to not center output")
                options.append("pd.set_option('display.width', None)")
            
            if 'linesize=' in content:
                linesize_match = re.search(r'linesize\s*=\s*(\d+)', content)
                if linesize_match:
                    linesize = linesize_match.group(1)
                    options.append(f"# Set display width to {linesize}")
                    options.append(f"pd.set_option('display.width', {linesize})")
            
            if 'pagesize=' in content:
                pagesize_match = re.search(r'pagesize\s*=\s*(\d+)', content)
                if pagesize_match:
                    pagesize = pagesize_match.group(1)
                    options.append(f"# Set display max rows to {pagesize}")
                    options.append(f"pd.set_option('display.max_rows', {pagesize})")
            
            if options:
                return '\n'.join(options)
            
            return f"# TODO: Convert OPTIONS:\n# {component.content.strip()}"
            
        except Exception as e:
            logger.warning(f"Error converting OPTIONS: {str(e)}")
            return f"# TODO: Convert OPTIONS:\n# {component.content.strip()}"

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
        """Convert TITLE statements to matplotlib title/suptitle."""
        try:
            content = component.content.strip()
            
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
            
        except Exception as e:
            raise ValueError(f"Error converting TITLE: {str(e)}")

    def _convert_footnote(self, component: SASComponent) -> str:
        """Convert FOOTNOTE statements to matplotlib figtext."""
        try:
            content = component.content.strip()
            
            # Extract footnote text
            footnote_match = re.search(r'footnote\s+["\']?([^"\']+)["\']?', content, re.IGNORECASE)
            if not footnote_match:
                raise ValueError("Invalid FOOTNOTE statement")
                
            footnote_text = footnote_match.group(1).strip()
            
            return f"plt.figtext(0.5, 0.01, {repr(footnote_text)}, ha='center', fontsize=8)"
            
        except Exception as e:
            raise ValueError(f"Error converting FOOTNOTE: {str(e)}")

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
        # Replace SAS operators with Python operators
        condition = condition.replace('&', '')  # Remove & from macro variables
        
        # Handle SAS comparison operators
        condition = re.sub(r'\bne\b', '!=', condition, flags=re.IGNORECASE)
        condition = re.sub(r'\beq\b', '==', condition, flags=re.IGNORECASE)
        condition = re.sub(r'\bgt\b', '>', condition, flags=re.IGNORECASE)
        condition = re.sub(r'\blt\b', '<', condition, flags=re.IGNORECASE)
        condition = re.sub(r'\bge\b', '>=', condition, flags=re.IGNORECASE)
        condition = re.sub(r'\ble\b', '<=', condition, flags=re.IGNORECASE)
        
        # Ensure the condition has a value after comparison operators
        if re.search(r'!=\s*$', condition):
            condition = condition.rstrip() + " None"
        
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
                        converted_files.append(output_file.get('path', ''))
                    else:
                        converted_files.append(output_file)
            except Exception as e:
                logger.error(f"Error converting {sas_file}: {str(e)}")
        
        return converted_files

    def convert_file(self, input_file: str) -> str:
        """
        Convert a SAS file to Python.
        
        Args:
            input_file: Path to SAS file
            
        Returns:
            Path to converted Python file
        """
        try:
            # Parse the SAS file
            logger.info(f"Parsing {input_file}...")
            parser = SASParser()
            components = parser.parse_file(input_file)
            
            if not components:
                logger.warning(f"No components found in {input_file}")
                return None
            
            logger.info(f"Found {len(components)} components in {input_file}")
            
            # Convert to Python
            logger.info(f"Converting {len(components)} components to Python...")
            python_code = self.convert_to_python(components, input_file)
            
            # Create output file path
            input_path = Path(input_file)
            output_filename = input_path.name.replace('.sas', '.py')
            output_path = Path(self.output_directory) / output_filename
            
            # Create directory if it doesn't exist
            output_path.parent.mkdir(parents=True, exist_ok=True)
            
            # Write Python code to file
            logger.info(f"Writing Python code to {output_path}...")
            with open(output_path, 'w') as f:
                f.write(python_code)
            
            logger.info(f"Converted {input_file} to {output_path}")
            return str(output_path)
            
        except Exception as e:
            logger.error(f"Error converting {input_file}: {str(e)}")
            raise

    def _get_helper_functions(self) -> str:
        """Get helper functions needed for the converted code."""
        helper_code = []
        
        # Add load_sashelp_dataset helper function
        if 'load_sashelp_dataset' in self.helper_functions:
            helper_code.extend([
                "def load_sashelp_dataset(name: str) -> pd.DataFrame:",
                "    \"\"\"Load a dataset from sashelp library.\"\"\"",
                "    try:",
                "        return pd.read_csv(f'sashelp_{name.lower()}.csv')",
                "    except Exception as e:",
                "        print(f'Error loading sashelp.{name}: {e}')",
                "        return pd.DataFrame()"
            ])
        
        # Add eval_expr helper function
        if 'eval_expr' in self.helper_functions:
            helper_code.extend([
                "",
                "def eval_expr(expr: str):",
                "    \"\"\"Evaluate a SAS expression.\"\"\"",
                "    try:",
                "        return eval(expr)",
                "    except Exception as e:",
                "        print(f'Error evaluating expression {expr}: {e}')",
                "        return None"
            ])
        
        # Add other helper functions as needed
        
        return '\n'.join(helper_code)

    def _convert_proc_gchart(self, component: SASComponent) -> str:
        """Convert PROC GCHART to matplotlib charts."""
        try:
            content = component.content
            data_match = re.search(r'data\s*=\s*(\S+)', content, re.IGNORECASE)
            
            if not data_match:
                return "# TODO: Convert PROC GCHART - no dataset specified"
            
            dataset = self._convert_sas_reference(data_match.group(1))
            
            # Check for chart types
            vbar_match = re.search(r'vbar\s+(\w+)', content, re.IGNORECASE)
            hbar_match = re.search(r'hbar\s+(\w+)', content, re.IGNORECASE)
            pie_match = re.search(r'pie\s+(\w+)', content, re.IGNORECASE)
            
            # Extract title if present
            title_match = re.search(r'title\s*=\s*[\'"]([^\'"]+)[\'"]', content, re.IGNORECASE)
            title = f"'{title_match.group(1)}'" if title_match else "''"
            
            if vbar_match:
                x_var = vbar_match.group(1)
                return f"""# Create vertical bar chart
plt.figure(figsize=(10, 6))
{dataset}.plot(kind='bar', x='{x_var}')
plt.title('Distribution by {x_var.title()}')
plt.xlabel('{x_var.title()}')
plt.ylabel('Amount')
plt.tight_layout()"""
            
            elif hbar_match:
                x_var = hbar_match.group(1)
                return f"""# Create horizontal bar chart
plt.figure(figsize=(10, 6))
{dataset}.plot(kind='barh', x='{x_var}')
plt.title('Distribution by {x_var.title()}')
plt.xlabel('Amount')
plt.ylabel('{x_var.title()}')
plt.tight_layout()"""
            
            elif pie_match:
                slice_var = pie_match.group(1)
                return f"""# Create pie chart
plt.figure(figsize=(10, 6))
{dataset}['{slice_var}'].value_counts().plot(kind='pie', autopct='%1.1f%%')
plt.title('Sales Distribution by {slice_var.title()}')
plt.ylabel('')
plt.tight_layout()"""
            
            return f"""# TODO: Convert PROC GCHART - plot type not recognized
# Original SAS code:
# {content.strip()}
plt.figure(figsize=(10, 6))
# Add appropriate plotting code here
plt.title({title})
plt.tight_layout()"""
            
        except Exception as e:
            logger.warning(f"Error converting PROC GCHART: {str(e)}")
            return f"# TODO: Convert PROC GCHART:\n# {component.content.strip()}"

    def _convert_macro_do_statement(self, statement: str) -> str:
        """Convert a %DO %WHILE statement to Python while loop."""
        try:
            # Extract condition
            do_while_match = re.search(r'%do\s+%while\s*\(\s*(.+?)\s*\);', statement, re.IGNORECASE)
            if do_while_match:
                condition = do_while_match.group(1)
                # Convert condition to Python
                condition = self._convert_macro_condition(condition)
                
                # Ensure the condition is valid
                if not condition or condition.strip() == '!=':
                    return "while True:  # Original condition could not be parsed"
                
                return f"while {condition}:"
            
            return f"# TODO: Convert %DO statement: {statement}"
        
        except Exception as e:
            logger.warning(f"Error converting %DO statement: {str(e)}")
            return f"# TODO: Convert %DO %WHILE statement: {statement}"

    def _clean_variable_name(self, var_name: str) -> str:
        """Clean variable names by removing invalid characters."""
        if not var_name:
            return "unknown_df"
            
        # Remove semicolons and other invalid characters
        cleaned = re.sub(r'[;:,\s\(\)\[\]{}]', '_', var_name)
        
        # Ensure we don't have double underscores
        cleaned = re.sub(r'_+', '_', cleaned)
        
        # Ensure the name is a valid Python identifier
        if cleaned and not cleaned[0].isalpha() and cleaned[0] != '_':
            cleaned = f"_{cleaned}"
        
        return cleaned

    def _convert_macro_call_statement(self, statement: str) -> str:
        """Convert a macro call statement to Python function call."""
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
                if param_value.startswith('&'):
                    # It's a macro variable reference
                    param_value = param_value[1:]  # Remove the & prefix
                elif param_value.upper() in ('YES', 'NO'):
                    # Convert SAS boolean to Python
                    param_value = 'True' if param_value.upper() == 'YES' else 'False'
                elif '.' in param_value and not (param_value.startswith("'") or param_value.startswith('"')):
                    # It's likely a dataset reference
                    param_value = self._convert_sas_reference(param_value)
                
                params[param_name] = param_value
            
            # Generate Python function call
            params_code = ", ".join([f"{k}={v}" for k, v in params.items()])
            return f"{macro_name}({params_code})"
            
        except Exception as e:
            logger.warning(f"Error converting macro call statement: {str(e)}")
            return f"# TODO: Convert macro call: {statement}"

    def _convert_parameter_join(self, component: SASComponent) -> str:
        """Convert PARAMETER_Join_Parameter macro."""
        try:
            content = component.content
            # Fix the regex to properly capture all parameters including name=value pairs
            param_match = re.search(r'%PARAMETER_Join_Parameter\s*\(\s*(.*?)\s*\)', content, re.IGNORECASE)
            
            if not param_match:
                return f"# TODO: Convert parameter join macro:\n# {content}"
                
            # Split parameters and clean them
            params_str = param_match.group(1)
            params = []
            current_param = []
            in_quotes = False
            
            # Parse parameters handling quotes and commas properly
            for char in params_str:
                if char == '"' or char == "'":
                    in_quotes = not in_quotes
                elif char == ',' and not in_quotes:
                    if current_param:
                        params.append(''.join(current_param).strip())
                        current_param = []
                    continue
                current_param.append(char)
            
            if current_param:
                params.append(''.join(current_param).strip())
            
            if len(params) < 2:
                return f"# TODO: Convert parameter join macro - invalid parameters:\n# {content}"
                
            table_name = params[0].strip()
            param_name = params[1].strip()
            
            # Handle name= parameter if present
            for param in params[1:]:
                if 'name=' in param:
                    param_name = param.split('=')[1].strip()
                    break
            
            return f"""
# Join parameters for {table_name}
{table_name}_df = pd.merge(
    {table_name}_df,
    parameters_df,
    how='left',
    on='{param_name}'
)"""
                
        except Exception as e:
            logger.warning(f"Error converting parameter join: {str(e)}")
            return f"# TODO: Convert parameter join:\n# {content}"

    def _convert_data_step_enhanced(self, component: SASComponent) -> str:
        """Enhanced converter for DATA steps with conditional logic."""
        try:
            content = component.content
            
            # Extract dataset names handling macro variables
            output_match = re.search(r'data\s+&(\w+)', content)
            set_match = re.search(r'set\s+(\w+)', content)
            
            if not output_match or not set_match:
                return f"# TODO: Convert DATA step - missing dataset information\n# {content}"
                
            output_name = output_match.group(1)
            input_name = set_match.group(1)
            
            # Extract conditional logic with better regex
            if_match = re.search(r'if\s*\(\s*(.*?)\s*\)\s*then\s*(.*?);(?:\s*else\s*(.*?);)?', 
                               content, re.IGNORECASE | re.DOTALL)
            
            if not if_match:
                return f"# TODO: Convert DATA step - complex logic:\n# {content}"
            
            condition = if_match.group(1).strip()
            then_stmt = if_match.group(2).strip()
            else_stmt = if_match.group(3).strip() if if_match.group(3) else "0"
            
            # Clean up the condition and statements
            condition = condition.replace("'", '"').replace("_ir", "_ir")  # Fix spacing issues
            then_stmt = then_stmt.replace("(", " (").replace(")", ") ")  # Add spaces around parentheses
            
            return f"""
# Create output dataset
{output_name}_df = {input_name}_df.copy()

# Apply conditional logic
def apply_condition(row):
    if {condition}:
        return {then_stmt}
    else:
        return {else_stmt}

{output_name}_df['IR_VAR_DELTA'] = {output_name}_df.apply(apply_condition, axis=1)"""
                
        except Exception as e:
            logger.warning(f"Error converting DATA step: {str(e)}")
            return f"# TODO: Convert DATA step:\n# {content}"

    def _parse_sql_select(self, select_clause: str) -> List[Dict[str, str]]:
        """Parse SQL SELECT clause into column definitions."""
        columns = []
        for col in select_clause.split(','):
            col = col.strip()
            if ' as ' in col.lower():
                orig, alias = col.lower().split(' as ')
                columns.append({
                    'original': orig.strip(),
                    'alias': alias.strip(),
                    'table_prefix': orig.split('.')[0] if '.' in orig else None
                })
            elif '.' in col:
                table, field = col.split('.')
                columns.append({
                    'original': field.strip(),
                    'alias': None,
                    'table_prefix': table.strip()
                })
            else:
                columns.append({
                    'original': col,
                    'alias': None,
                    'table_prefix': None
                })
        return columns

    def _parse_join_clause(self, join_clause: str) -> Dict[str, Any]:
        """Parse SQL JOIN clause into structured format."""
        join_info = {
            'type': 'left' if 'left join' in join_clause.lower() else 'inner',
            'table': None,
            'alias': None,
            'conditions': []
        }
        
        # Extract table and alias
        table_match = re.search(r'join\s+&?(\w+)\s+(\w+)', join_clause)
        if table_match:
            join_info['table'] = table_match.group(1).replace('&', '')
            join_info['alias'] = table_match.group(2)
        
        # Extract conditions
        cond_match = re.search(r'on\s+(.+?)(?=(?:left join|$))', join_clause, re.IGNORECASE | re.DOTALL)
        if cond_match:
            conditions = cond_match.group(1).strip()
            # Handle special conditions
            if conditions == '(1=1)':
                join_info['conditions'].append({'type': 'cross_join'})
            else:
                for cond in conditions.split('and'):
                    if '=' in cond:
                        left, right = [s.strip() for s in cond.split('=')]
                        join_info['conditions'].append({
                            'type': 'equals',
                            'left': left,
                            'right': right
                        })
        
        return join_info

    def _convert_data_step_assignment(self, assignment: str) -> Dict[str, Any]:
        """Convert DATA step assignment to Python expression."""
        target, expression = [s.strip() for s in assignment.split('=')]
        
        # Parse function calls
        def parse_function(expr: str) -> Dict[str, Any]:
            func_match = re.search(r'(\w+)\((.*)\)', expr)
            if func_match:
                return {
                    'function': func_match.group(1),
                    'arguments': [arg.strip() for arg in func_match.group(2).split(',')]
                }
            return {'value': expr}
        
        # Handle complex expressions
        if '(' in expression:
            operations = []
            for part in re.findall(r'([\w_]+\([^)]+\)|-|\+|\*|/|\w+)', expression):
                if any(op in part for op in ['+', '-', '*', '/']):
                    operations.append({'operator': part})
                else:
                    operations.append(parse_function(part))
        else:
            operations = [{'value': expression}]
        
        return {
            'target': target,
            'operations': operations
        }
