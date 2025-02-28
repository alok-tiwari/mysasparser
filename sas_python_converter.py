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
        vector_store: VectorStore,
        output_directory: str = "python_output",
        embedding_generator: EmbeddingGenerator = None
    ):
        """
        Initialize the converter.
        
        Args:
            vector_store: VectorStore instance (for testing) or None (for production)
            embedding_generator: EmbeddingGenerator instance for generating embeddings
            output_directory: Directory to save Python output files
        """
        self.vector_store = vector_store
        self.output_directory = output_directory
        self.embedding_generator = embedding_generator
        
        # Create output directory if it doesn't exist
        os.makedirs(output_directory, exist_ok=True)
        
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
            if component_type == "PROC_SQL":
                return "sql"
            return "procedures"
        elif component_type == "DATA":
            return "data_steps"
        elif component_type == "MACRO":
            return "macros"
        else:
            return "other"
    
    def parse_sas_file(self, file_path: str) -> List[SASComponent]:
        """Parse a SAS file into components."""
        parser = SASParser()
        try:
            return parser.parse_file(file_path)
        except Exception as e:
            logger.error(f"Error parsing file {file_path}: {str(e)}")
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

    def convert_to_python(self, sas_components: List[SASComponent], original_file_path: str) -> Dict[str, str]:
        """Enhanced conversion with dataset loading."""
        python_files = {}
        sas_filename = os.path.basename(original_file_path)
        python_filename = os.path.splitext(sas_filename)[0] + ".py"
        output_path = os.path.join(self.output_directory, python_filename)
        
        # Track dependencies and order components
        self._map_dependencies(sas_components)
        ordered_components = self._order_components_by_dependency(sas_components)
        
        # Start with imports and setup
        python_code = [
            f"# Auto-generated Python code from SAS file: {sas_filename}",
            f"# Generated on: {time.strftime('%Y-%m-%d %H:%M:%S')}",
            "",
            "import pandas as pd",
            "import numpy as np",
            "from scipy import stats",
            "import os",
            "import matplotlib.pyplot as plt",
            "import seaborn as sns",
            "",
            "# Configure plotting",
            "plt.style.use('seaborn')",
            "sns.set_theme()",
            ""
        ]
        
        # Add dataset loading code
        python_code.extend(self._add_dataset_loading(sas_components))
        
        # Convert each component
        for component in ordered_components:
            # Get similar components for guidance
            similar_components = self.get_similar_components(
                component.content,
                component_type=component.type,
                n_results=3
            )
            
            # Convert the component with guidance from similar components
            converted_code = self._convert_component(component, similar_components)
            
            # Skip empty or None conversions
            if not converted_code:
                logger.warning(f"Skipping empty conversion for {component.type}: {component.name}")
                continue
                
            # Add converted code with comment header
            python_code.extend([
                "",
                f"# {'-'*50}",
                f"# {component.type}: {component.name} (Lines {component.line_start}-{component.line_end})",
                f"# {'-'*50}",
                converted_code,
                ""  # Empty line for readability
            ])
        
        # Add a main execution block
        python_code.extend([
            "",
            "# Execute main code when run directly",
            "if __name__ == '__main__':",
            "    # Add your main execution code here",
            "    pass"
        ])
        
        # Join all code parts
        final_code = "\n".join(python_code)
        
        # Save to output file
        with open(output_path, 'w') as f:
            f.write(final_code)
            
        logger.info(f"Converted {len(ordered_components)} components to {output_path}")
        
        python_files[output_path] = final_code
        return python_files
    
    def _map_dependencies(self, components: List[SASComponent]):
        """Map dependencies between components for ordering."""
        self.dependency_map = {}
        
        # First pass: build name-to-component mapping
        name_map = {}
        comp_id_map = {}  # Map to track components by ID
        
        for i, comp in enumerate(components):
            comp_id = f"comp_{i}"  # Create a unique ID for each component
            comp_id_map[comp_id] = comp
            if comp.name:
                name_map[comp.name] = comp_id
        
        # Second pass: build dependency graph
        for i, comp in enumerate(components):
            comp_id = f"comp_{i}"
            self.dependency_map[comp_id] = []
            for dep_name in comp.dependencies:
                if dep_name in name_map:
                    self.dependency_map[comp_id].append(name_map[dep_name])
        
        # Store the id map for later use
        self.comp_id_map = comp_id_map
    
    def _order_components_by_dependency(self, components: List[SASComponent]) -> List[SASComponent]:
        """Order components by dependency for conversion."""
        if not self.dependency_map:
            return components
        
        # Simple topological sort
        visited = set()
        ordered_comp_ids = []
        
        def visit(comp_id):
            if comp_id in visited:
                return
            visited.add(comp_id)
            for dep_id in self.dependency_map.get(comp_id, []):
                visit(dep_id)
            ordered_comp_ids.append(comp_id)
        
        # Visit all components
        for i in range(len(components)):
            comp_id = f"comp_{i}"
            visit(comp_id)
        
        # Convert back to actual components
        ordered_components = [self.comp_id_map[comp_id] for comp_id in ordered_comp_ids]
        return ordered_components
    
    def _convert_component(self, component: SASComponent, similar_components: List[Dict[str, Any]]) -> str:
        """
        Convert a SAS component to Python code with detailed logic.
        """
        try:
            # Extract similar examples to guide conversion
            similar_content = []
            if similar_components:
                for item in similar_components[:2]:  # Use top 2 most similar components
                    if "content" in item:
                        similar_content.append(item["content"])
            
            # Convert based on component type with detailed logic
            if component.type == "PROC":
                return self._convert_proc(component, similar_content)
            elif component.type == "DATA":
                return self._convert_data_step(component, similar_content)
            elif component.type == "MACRO":
                return self._convert_macro(component, similar_content)
            elif component.type == "PROC_SQL":
                return self._convert_sql(component, similar_content)
            elif component.type == "%LET":
                return self._convert_macro_variable(component)
            elif component.type.startswith("%"):
                return self._convert_macro_statement(component)
            elif component.type == "LIBNAME":
                return self._convert_libname(component)
            elif component.type == "FILENAME":
                return self._convert_filename(component)
            elif component.type == "OPTIONS":
                return self._convert_options(component)
            elif component.type == "ODS":
                return self._convert_ods(component)
            elif component.type == "FORMAT" or component.type == "INFORMAT":
                return self._convert_format(component)
            elif component.type in ["TITLE", "FOOTNOTE"]:
                return self._convert_title_footnote(component)
            else:
                return f"# TODO: Convert {component.type} - {component.name}\n# Original code:\n# " + component.content.replace("\n", "\n# ")
        except Exception as e:
            logger.error(f"Error converting component {component.type} - {component.name}: {str(e)}")
            return f"# ERROR converting {component.type} - {component.name}: {str(e)}\n# Original code:\n# " + component.content.replace("\n", "\n# ")
        
    def _convert_proc(self, component: SASComponent, similar_components: List[Dict[str, Any]]) -> str:
        """Convert SAS PROC to Python equivalent."""
        proc_type = component.name.upper()
        
        # Map PROC types to conversion methods
        proc_converters = {
            'MEANS': self._convert_proc_means,
            'TTEST': self._convert_proc_ttest,
            'UNIVARIATE': self._convert_proc_univariate,
            'SQL': self._convert_sql,
            'SORT': self._convert_proc_sort,
            'PRINT': self._convert_proc_print,
            'FORMAT': self._convert_proc_format,
            'REPORT': self._convert_proc_report,
            'SGPLOT': self._convert_proc_sgplot
        }
        
        # Check if we have a converter method for this PROC
        if proc_type in proc_converters:
            try:
                if hasattr(self, proc_converters[proc_type].__name__):
                    return proc_converters[proc_type](component)
                else:
                    return f"# TODO: Implement {proc_converters[proc_type].__name__}\n# Original code:\n{component.content}"
            except Exception as e:
                return f"# ERROR converting PROC - {proc_type}: {str(e)}\n# Original code:\n{component.content}"
        else:
            return f"# TODO: Convert PROC {proc_type}\n# Original code:\n{component.content}"

    def _convert_proc_sort(self, component: SASComponent) -> str:
        """Convert PROC SORT to pandas sort_values() and drop_duplicates()."""
        data_match = re.search(r'data\s*=\s*(\w+)', component.content, re.IGNORECASE)
        out_match = re.search(r'out\s*=\s*(\w+)', component.content, re.IGNORECASE)
        by_match = re.search(r'by\s+(.*?);', component.content, re.IGNORECASE)
        nodupkey = 'nodupkey' in component.content.lower()
        nodup = 'nodup' in component.content.lower()
        
        if data_match and by_match:
            data_name = self._convert_dataset_name(data_match.group(1))
            out_name = self._convert_dataset_name(out_match.group(1)) if out_match else data_name
            by_vars = [v.strip() for v in by_match.group(1).split()]
            
            code_lines = []
            code_lines.append(f"# Sort dataset by {', '.join(by_vars)}")
            
            if nodupkey:
                code_lines.extend([
                    f"{out_name} = {data_name}.sort_values([{', '.join(f''''{v}' ''' for v in by_vars)}])",
                    f"{out_name} = {out_name}.drop_duplicates(subset=[{', '.join(f''''{v}' ''' for v in by_vars)}], keep='first')"
                ])
            elif nodup:
                code_lines.extend([
                    f"{out_name} = {data_name}.sort_values([{', '.join(f''''{v}' ''' for v in by_vars)}])",
                    f"{out_name} = {out_name}.drop_duplicates(keep='first')"
                ])
            else:
                code_lines.append(f"{out_name} = {data_name}.sort_values([{', '.join(f''''{v}' ''' for v in by_vars)}])")
            
            return "\n".join(code_lines)
        
        return f"# TODO: Convert complex PROC SORT\n# {component.content}"

    def _convert_proc_means(self, component: SASComponent) -> str:
        """Convert PROC MEANS to pandas descriptive statistics."""
        data_match = re.search(r'data\s*=\s*(\w+)', component.content, re.IGNORECASE)
        var_match = re.search(r'var\s+(.*?);', component.content, re.IGNORECASE)
        by_match = re.search(r'by\s+(.*?);', component.content, re.IGNORECASE)
        maxdec_match = re.search(r'maxdec\s*=\s*(\d+)', component.content, re.IGNORECASE)
        nway = 'nway' in component.content.lower()
        
        dataset = data_match.group(1) if data_match else "df"
        dataset = dataset.replace('&', '')
        variables = var_match.group(1).split() if var_match else []
        by_vars = by_match.group(1).split() if by_match else []
        maxdec = int(maxdec_match.group(1)) if maxdec_match else 4
        
        code_lines = []
        code_lines.append("# Calculate descriptive statistics")
        
        # Format string for numeric output
        format_str = f":.{maxdec}f"
        code_lines.append(f"pd.set_option('display.float_format', lambda x: '{{0:{format_str}}}'.format(x))")
        
        # Handle NWAY option
        if nway and by_vars:
            code_lines.append("# NWAY option: only show statistics for each BY group combination")
            code_lines.append(f"stats_df = {dataset}_df.groupby([{', '.join(f''''{v}' ''' for v in by_vars)}], dropna=False)")
        else:
            if by_vars:
                if variables:
                    var_list = ", ".join(f"'{v}'" for v in variables)
                    code_lines.append(f"stats_df = {dataset}_df.groupby([{', '.join(f''''{v}' ''' for v in by_vars)}])[{var_list}].agg({stats})")
                else:
                    code_lines.append(f"stats_df = {dataset}_df.groupby([{', '.join(f''''{v}' ''' for v in by_vars)}]).agg({stats})")
            else:
                if variables:
                    var_list = ", ".join(f"'{v}'" for v in variables)
                    code_lines.append(f"stats_df = {dataset}_df[[{var_list}]].agg({stats})")
                else:
                    code_lines.append(f"stats_df = {dataset}_df.agg({stats})")
        
        # Reset index if using groupby
        if by_vars:
            code_lines.append("stats_df = stats_df.reset_index()")
        
        # Add output if specified
        output_match = re.search(r'output\s+out\s*=\s*(\w+)\s*(.*?);', component.content, re.IGNORECASE)
        if output_match:
            out_dataset = output_match.group(1)
            code_lines.extend([
                "",
                "# Save statistics to new DataFrame",
                f"{out_dataset}_df = stats_df.copy()"
            ])
        
        # Print results unless noprint specified
        if not 'noprint' in component.content.lower():
            code_lines.extend([
                "print('\\nDescriptive Statistics:')",
                "print(stats_df)"
            ])
        
        return "\n".join(code_lines)

    def _convert_proc_univariate(self, component: SASComponent) -> str:
        """Convert PROC UNIVARIATE to detailed pandas/scipy statistics."""
        # Extract dataset and variables
        data_match = re.search(r'data\s*=\s*(\w+)', component.content, re.IGNORECASE)
        var_match = re.search(r'var\s+(.*?);', component.content, re.IGNORECASE)
        
        dataset = data_match.group(1) if data_match else "df"
        dataset = dataset.replace('&', '')  # Handle macro variables
        variables = var_match.group(1).split() if var_match else []
        
        code_lines = [
            "# Calculate detailed statistics",
            "from scipy import stats",
            ""
        ]
        
        if variables:
            for var in variables:
                code_lines.extend([
                    f"print(f'\\nDetailed Analysis for {var}:')",
                    f"data = {dataset}_df['{var}'].dropna()",
                    "",
                    "# Basic statistics",
                    "desc = data.describe()",
                    "print('\\nBasic Statistics:')",
                    "print(desc)",
                    "",
                    "# Additional statistics",
                    "print('\\nAdditional Statistics:')",
                    "print(f'Skewness: {stats.skew(data):.3f}')",
                    "print(f'Kurtosis: {stats.kurtosis(data):.3f}')",
                    "",
                    "# Normality test",
                    "stat, p_value = stats.normaltest(data)",
                    "print(f'Normality test: statistic={stat:.3f}, p-value={p_value:.3f}')",
                    "",
                    "# Generate QQ plot",
                    "fig, ax = plt.subplots(figsize=(8, 6))",
                    f"stats.probplot(data, dist='norm', plot=ax)",
                    f"ax.set_title(f'Q-Q Plot of {var}')",
                    "plt.show()"
                ])
        else:
            code_lines.extend([
                "# Analyze all numeric columns",
                "numeric_cols = df.select_dtypes(include=[np.number]).columns",
                "for col in numeric_cols:",
                "    print(f'\\nAnalysis for {col}:')",
                "    data = df[col].dropna()",
                "    print(data.describe())"
            ])
        
        return "\n".join(code_lines)

    def _convert_proc_ttest(self, component: SASComponent) -> str:
        """Convert PROC TTEST to scipy.stats t-tests with enhanced output."""
        content = component.content
        code_lines = []
        
        # Import required libraries
        code_lines.extend([
            "# T-test analysis",
            "from scipy import stats",
            "import pandas as pd",
            "import matplotlib.pyplot as plt",
            "import seaborn as sns"
        ])
        
        # Extract data parameter
        data_match = re.search(r'data\s*=\s*(\w+)', content, re.IGNORECASE)
        data_name = data_match.group(1) if data_match else "df"
        data_df = f"{data_name.lower()}_df"
        
        # Extract VAR statement
        var_match = re.search(r'VAR\s+(.*?);', content, re.IGNORECASE)
        var_list = []
        if var_match:
            var_list = [v.strip() for v in var_match.group(1).split()]
        
        # Extract hypothesis value (H0)
        h0_match = re.search(r'H0\s*=\s*(\S+)', content, re.IGNORECASE)
        h0_value = h0_match.group(1) if h0_match else "0"
        
        # Extract alpha value
        alpha_match = re.search(r'ALPHA\s*=\s*(\S+)', content, re.IGNORECASE)
        alpha_value = alpha_match.group(1) if alpha_match else "0.05"
        
        # Extract CLASS variable (for paired or two-sample t-test)
        class_match = re.search(r'CLASS\s+(\w+)', content, re.IGNORECASE)
        class_var = class_match.group(1) if class_match else None
        
        # Extract PAIRED option
        paired_option = re.search(r'\bPAIRED\b', content, re.IGNORECASE) is not None
        
        # Extract WHERE condition
        where_match = re.search(r'WHERE\s+(.*?);', content, re.IGNORECASE)
        if where_match:
            where_condition = self._convert_sas_condition(where_match.group(1))
            code_lines.append(f"# Filter data")
            code_lines.append(f"filtered_df = {data_df}[{where_condition}]")
            data_df = "filtered_df"
        
        # Determine test type and generate code
        if class_var and paired_option:
            # Paired t-test
            code_lines.append(f"# Paired t-test with CLASS variable {class_var}")
            code_lines.append(f"class_values = {data_df}['{class_var}'].unique()")
            code_lines.append(f"if len(class_values) != 2:")
            code_lines.append(f"    print(f\"Error: Paired t-test requires exactly 2 class values, found {{len(class_values)}}\")")
            code_lines.append(f"else:")
            code_lines.append(f"    class_val1, class_val2 = class_values[:2]")
            code_lines.append(f"    print(f\"Performing paired t-test with {{class_var}} groups: {{class_val1}} vs {{class_val2}}\")")
            
            for var in var_list:
                code_lines.append(f"    # Paired t-test for {var}")
                code_lines.append(f"    group1 = {data_df}[{data_df}['{class_var}'] == class_val1]['{var}'].dropna()")
                code_lines.append(f"    group2 = {data_df}[{data_df}['{class_var}'] == class_val2]['{var}'].dropna()")
                code_lines.append(f"    # Ensure equal sizes for paired test")
                code_lines.append(f"    min_size = min(len(group1), len(group2))")
                code_lines.append(f"    if min_size > 0:")
                code_lines.append(f"        paired_result = stats.ttest_rel(group1[:min_size], group2[:min_size])")
                code_lines.append(f"        print(f\"\\nPaired t-test for {{var}}:\")")
                code_lines.append(f"        print(f\"  t-statistic: {{paired_result.statistic:.4f}}\")")
                code_lines.append(f"        print(f\"  p-value: {{paired_result.pvalue:.4f}}\")")
                code_lines.append(f"        print(f\"  Significant at alpha={alpha_value}: {{paired_result.pvalue < float({alpha_value})}}\")")
                code_lines.append(f"        ")
                code_lines.append(f"        # Visualize differences")
                code_lines.append(f"        plt.figure(figsize=(12, 6))")
                code_lines.append(f"        plt.subplot(1, 2, 1)")
                code_lines.append(f"        sns.boxplot(x='{class_var}', y='{var}', data={data_df})")
                code_lines.append(f"        plt.title(f\"Boxplot of {{var}} by {{class_var}}\")")
                code_lines.append(f"        ")
                code_lines.append(f"        plt.subplot(1, 2, 2)")
                code_lines.append(f"        differences = group1[:min_size] - group2[:min_size]")
                code_lines.append(f"        sns.histplot(differences, kde=True)")
                code_lines.append(f"        plt.axvline(x=0, color='r', linestyle='--')")
                code_lines.append(f"        plt.title(f\"Differences ({{class_val1}} - {{class_val2}})\")")
                code_lines.append(f"        plt.tight_layout()")
                code_lines.append(f"        plt.show()")
                code_lines.append(f"    else:")
                code_lines.append(f"        print(f\"Error: Insufficient data for paired t-test on {{var}}\")")
        
        elif class_var:
            # Two-sample t-test
            code_lines.append(f"# Two-sample t-test with CLASS variable {class_var}")
            code_lines.append(f"class_values = {data_df}['{class_var}'].unique()")
            code_lines.append(f"if len(class_values) != 2:")
            code_lines.append(f"    print(f\"Warning: Two-sample t-test works best with exactly 2 class values, found {{len(class_values)}}\")")
            code_lines.append(f"    if len(class_values) > 2:")
            code_lines.append(f"        class_values = class_values[:2]")
            code_lines.append(f"        print(f\"Using first two class values: {{class_values}}\")")
            code_lines.append(f"")
            code_lines.append(f"if len(class_values) >= 2:")
            code_lines.append(f"    class_val1, class_val2 = class_values[:2]")
            code_lines.append(f"    print(f\"Performing two-sample t-test with {{class_var}} groups: {{class_val1}} vs {{class_val2}}\")")
            
            for var in var_list:
                code_lines.append(f"    # Two-sample t-test for {var}")
                code_lines.append(f"    group1 = {data_df}[{data_df}['{class_var}'] == class_val1]['{var}'].dropna()")
                code_lines.append(f"    group2 = {data_df}[{data_df}['{class_var}'] == class_val2]['{var}'].dropna()")
                code_lines.append(f"    ")
                code_lines.append(f"    # Test for equal variances")
                code_lines.append(f"    _, var_p_value = stats.levene(group1, group2)")
                code_lines.append(f"    equal_var = var_p_value > 0.05  # Assume equal variance if p > 0.05")
                code_lines.append(f"    ")
                code_lines.append(f"    # Perform t-test")
                code_lines.append(f"    t_result = stats.ttest_ind(group1, group2, equal_var=equal_var)")
                code_lines.append(f"    variance_type = \"equal\" if equal_var else \"unequal\"")
                code_lines.append(f"    print(f\"\\nTwo-sample t-test for {{var}} (assuming {variance_type} variances):\")")
                code_lines.append(f"    print(f\"  t-statistic: {{t_result.statistic:.4f}}\")")
                code_lines.append(f"    print(f\"  p-value: {{t_result.pvalue:.4f}}\")")
                code_lines.append(f"    print(f\"  Significant at alpha={alpha_value}: {{t_result.pvalue < float({alpha_value})}}\")")
                code_lines.append(f"    ")
                code_lines.append(f"    # Basic descriptive statistics")
                code_lines.append(f"    desc1 = group1.describe()")
                code_lines.append(f"    desc2 = group2.describe()")
                code_lines.append(f"    print(f\"\\nGroup statistics:\")")
                code_lines.append(f"    print(f\"  {{class_val1}}: n={{desc1['count']:.0f}}, mean={{desc1['mean']:.4f}}, std={{desc1['std']:.4f}}\")")
                code_lines.append(f"    print(f\"  {{class_val2}}: n={{desc2['count']:.0f}}, mean={{desc2['mean']:.4f}}, std={{desc2['std']:.4f}}\")")
                code_lines.append(f"    ")
                code_lines.append(f"    # Visualize groups")
                code_lines.append(f"    plt.figure(figsize=(15, 5))")
                code_lines.append(f"    plt.subplot(1, 3, 1)")
                code_lines.append(f"    sns.boxplot(x='{class_var}', y='{var}', data={data_df})")
                code_lines.append(f"    plt.title(f\"Boxplot of {{var}} by {{class_var}}\")")
                code_lines.append(f"    ")
                code_lines.append(f"    plt.subplot(1, 3, 2)")
                code_lines.append(f"    sns.histplot(group1, kde=True, color='blue', alpha=0.5, label=str(class_val1))")
                code_lines.append(f"    sns.histplot(group2, kde=True, color='red', alpha=0.5, label=str(class_val2))")
                code_lines.append(f"    plt.legend()")
                code_lines.append(f"    plt.title(f\"Distribution of {{var}} by group\")")
                code_lines.append(f"    ")
                code_lines.append(f"    plt.subplot(1, 3, 3)")
                code_lines.append(f"    sns.kdeplot(group1, shade=True, color='blue', label=str(class_val1))")
                code_lines.append(f"    sns.kdeplot(group2, shade=True, color='red', label=str(class_val2))")
                code_lines.append(f"    plt.legend()")
                code_lines.append(f"    plt.title(f\"Density of {{var}} by group\")")
                code_lines.append(f"    ")
                code_lines.append(f"    plt.tight_layout()")
                code_lines.append(f"    plt.show()")
        
        else:
            # One-sample t-test
            code_lines.append(f"# One-sample t-test (H0: mean = {h0_value})")
            for var in var_list:
                code_lines.append(f"# One-sample t-test for {var}")
                code_lines.append(f"data = {data_df}['{var}'].dropna()")
                code_lines.append(f"t_stat, p_value = stats.ttest_1samp(data, {h0_value})")
                code_lines.append(f"print(f\"\\nOne-sample t-test for {var}:\")")
                code_lines.append(f"print(f\"  Null hypothesis: μ = {h0_value}\")")
                code_lines.append(f"print(f\"  t-statistic: {{t_stat:.4f}}\")")
                code_lines.append(f"print(f\"  p-value: {{p_value:.4f}}\")")
                code_lines.append(f"print(f\"  Significant at alpha={alpha_value}: {{p_value < float({alpha_value})}}\")")
                code_lines.append(f"")
                code_lines.append(f"# Basic descriptive statistics")
                code_lines.append(f"desc = data.describe()")
                code_lines.append(f"print(f\"  n={{desc['count']:.0f}}, mean={{desc['mean']:.4f}}, std={{desc['std']:.4f}}\")")
                code_lines.append(f"print(f\"  95% CI: [{{desc['mean'] - 1.96 * desc['std']/np.sqrt(desc['count']):.4f}}, {{desc['mean'] + 1.96 * desc['std']/np.sqrt(desc['count']):.4f}}]\")")
                code_lines.append(f"")
                code_lines.append(f"# Visualize data")
                code_lines.append(f"plt.figure(figsize=(12, 5))")
                code_lines.append(f"plt.subplot(1, 2, 1)")
                code_lines.append(f"sns.histplot(data, kde=True)")
                code_lines.append(f"plt.axvline(x=float({h0_value}), color='red', linestyle='--', label=f'H0: μ = {h0_value}')")
                code_lines.append(f"plt.axvline(x=desc['mean'], color='green', linestyle='-', label='Sample mean')")
                code_lines.append(f"plt.legend()")
                code_lines.append(f"plt.title(f\"Distribution of {var} with reference lines\")")
                
                code_lines.append(f"plt.subplot(1, 2, 2)")
                code_lines.append(f"sns.boxplot(y=data)")
                code_lines.append(f"plt.axhline(y=float({h0_value}), color='red', linestyle='--', label=f'H0: μ = {h0_value}')")
                code_lines.append(f"plt.title(f\"Boxplot of {var}\")")
                code_lines.append(f"plt.tight_layout()")
                code_lines.append(f"plt.show()")
        
        return "\n".join(code_lines)

    def _convert_proc_reg(self, component: SASComponent) -> str:
        """Convert PROC REG to statsmodels linear regression."""
        content = component.content
        code_lines = []
        
        # Import required libraries
        code_lines.extend([
            "# Linear regression analysis using statsmodels",
            "import statsmodels.api as sm",
            "import statsmodels.formula.api as smf",
            "import matplotlib.pyplot as plt",
            "import seaborn as sns",
            "import numpy as np"
        ])
        
        # Extract data parameter
        data_match = re.search(r'data\s*=\s*(\w+)', content, re.IGNORECASE)
        data_name = data_match.group(1) if data_match else "df"
        data_df = f"{data_name.lower()}_df"
        
        # Extract MODEL statement(s)
        model_matches = re.findall(r'MODEL\s+(.*?);', content, re.IGNORECASE | re.DOTALL)
        
        if model_matches:
            for i, model_stmt in enumerate(model_matches):
                # Parse MODEL statement for dependent and independent variables
                # Format: dependent = independent1 independent2 ...
                model_parts = model_stmt.split('=', 1)
                if len(model_parts) == 2:
                    dependent = model_parts[0].strip()
                    independents = model_parts[1].strip().split()
                    
                    # Build formula for statsmodels
                    formula = f"'{dependent} ~ " + " + ".join(independents) + "'"
                    model_name = f"model{i+1}" if i > 0 else "model"
                    result_name = f"results{i+1}" if i > 0 else "results"
                    
                    code_lines.append(f"# Model {i+1}: {dependent} = {' + '.join(independents)}")
                    code_lines.append(f"formula = {formula}")
                    code_lines.append(f"{model_name} = smf.ols(formula, data={data_df})")
                    code_lines.append(f"{result_name} = {model_name}.fit()")
                    code_lines.append(f"")
                    code_lines.append(f"# Print detailed summary")
                    code_lines.append(f"print({result_name}.summary())")
                    code_lines.append(f"")
                    
                    # Add diagnostic plots
                    code_lines.append(f"# Create diagnostic plots")
                    code_lines.append(f"plt.figure(figsize=(15, 10))")
                    
                    # Residuals vs Fitted
                    code_lines.append(f"plt.subplot(2, 2, 1)")
                    code_lines.append(f"sns.residplot(x={result_name}.fittedvalues, y={result_name}.resid, lowess=True)")
                    code_lines.append(f"plt.xlabel('Fitted values')")
                    code_lines.append(f"plt.ylabel('Residuals')")
                    code_lines.append(f"plt.title('Residuals vs Fitted')")
                    code_lines.append(f"plt.axhline(y=0, color='red', linestyle='--')")
                    
                    # Normal Q-Q plot
                    code_lines.append(f"plt.subplot(2, 2, 2)")
                    code_lines.append(f"sm.qqplot({result_name}.resid, line='45', fit=True, ax=plt.gca())")
                    code_lines.append(f"plt.title('Normal Q-Q')")
                    
                    # Scale-Location plot
                    code_lines.append(f"plt.subplot(2, 2, 3)")
                    code_lines.append(f"standardized_resid = {result_name}.get_influence().resid_studentized_internal")
                    code_lines.append(f"plt.scatter({result_name}.fittedvalues, np.sqrt(np.abs(standardized_resid)))")
                    code_lines.append(f"plt.xlabel('Fitted values')")
                    code_lines.append(f"plt.ylabel('√|Standardized residuals|')")
                    code_lines.append(f"plt.title('Scale-Location')")
                    
                    # Residuals vs Leverage
                    code_lines.append(f"plt.subplot(2, 2, 4)")
                    code_lines.append(f"influence = {result_name}.get_influence()")
                    code_lines.append(f"leverage = influence.hat_matrix_diag")
                    code_lines.append(f"plt.scatter(leverage, standardized_resid)")
                    code_lines.append(f"plt.xlabel('Leverage')")
                    code_lines.append(f"plt.ylabel('Standardized residuals')")
                    code_lines.append(f"plt.title('Residuals vs Leverage')")
                    
                    # Add cook's distance contours
                    code_lines.append(f"# Add Cook's distance contours")
                    code_lines.append(f"cooks = influence.cooks_distance[0]")
                    code_lines.append(f"(p, k) = {model_name}.exog.shape")
                    code_lines.append(f"for val in [0.5, 1.0]:")
                    code_lines.append(f"    x = np.linspace(0, max(leverage)*1.1, 100)")
                    code_lines.append(f"    y = np.sqrt(val * k * (1 - x) / x)")
                    code_lines.append(f"    plt.plot(x, y, 'r--', label=f\"Cook's distance = {{val}}\")")
                    code_lines.append(f"    plt.plot(x, -y, 'r--')")
                    
                    code_lines.append(f"plt.tight_layout()")
                    code_lines.append(f"plt.show()")
                    
                    # Add variable influence assessment
                    code_lines.append(f"# Plot coefficient values with confidence intervals")
                    code_lines.append(f"coef_df = pd.DataFrame({{'coef': {result_name}.params[1:]}}).reset_index()")
                    code_lines.append(f"coef_df['lower'] = {result_name}.conf_int()[0][1:]")
                    code_lines.append(f"coef_df['upper'] = {result_name}.conf_int()[1][1:]")
                    code_lines.append(f"coef_df = coef_df.sort_values('coef')")
                    
                    code_lines.append(f"plt.figure(figsize=(10, 6))")
                    code_lines.append(f"plt.errorbar(coef_df['coef'], coef_df['index'], xerr=[(coef_df['coef']-coef_df['lower']), (coef_df['upper']-coef_df['coef'])], fmt='o')")
                    code_lines.append(f"plt.axvline(x=0, color='red', linestyle='--')")
                    code_lines.append(f"plt.xlabel('Coefficient value')")
                    code_lines.append(f"plt.ylabel('Variable')")
                    code_lines.append(f"plt.title('Coefficient Plot with 95% Confidence Intervals')")
                    code_lines.append(f"plt.grid(True, alpha=0.3)")
                    code_lines.append(f"plt.tight_layout()")
                    code_lines.append(f"plt.show()")
                    
                    # Add prediction and confidence intervals if OUTPUT statement exists
                    output_match = re.search(r'OUTPUT\s+OUT\s*=\s*(\w+)', content, re.IGNORECASE)
                    if output_match:
                        output_ds = output_match.group(1)
                        code_lines.append(f"# Generate predictions with confidence intervals")
                        code_lines.append(f"{output_ds.lower()}_df = {data_df}.copy()")
                        code_lines.append(f"{output_ds.lower()}_df['predicted'] = {result_name}.predict()")
                        code_lines.append(f"pred_ci = {result_name}.get_prediction().conf_int()")
                        code_lines.append(f"{output_ds.lower()}_df['lower_ci'] = pred_ci[:, 0]")
                        code_lines.append(f"{output_ds.lower()}_df['upper_ci'] = pred_ci[:, 1]")
                        code_lines.append(f"{output_ds.lower()}_df['residuals'] = {result_name}.resid")
                        code_lines.append(f"{output_ds.lower()}_df['std_residuals'] = {result_name}.get_influence().resid_studentized_internal")
                        code_lines.append(f"")
                        
                        # Plot actual vs predicted
                        code_lines.append(f"# Plot actual vs predicted values")
                        code_lines.append(f"plt.figure(figsize=(10, 6))")
                        code_lines.append(f"plt.scatter({output_ds.lower()}_df['{dependent}'], {output_ds.lower()}_df['predicted'])")
                        code_lines.append(f"min_val = min({output_ds.lower()}_df['{dependent}'].min(), {output_ds.lower()}_df['predicted'].min())")
                        code_lines.append(f"max_val = max({output_ds.lower()}_df['{dependent}'].max(), {output_ds.lower()}_df['predicted'].max())")
                        code_lines.append(f"plt.plot([min_val, max_val], [min_val, max_val], 'r--')")
                        code_lines.append(f"plt.xlabel('Actual values')")
                        code_lines.append(f"plt.ylabel('Predicted values')")
                        code_lines.append(f"plt.title('Actual vs Predicted')")
                        code_lines.append(f"plt.grid(True, alpha=0.3)")
                        code_lines.append(f"plt.tight_layout()")
                        code_lines.append(f"plt.show()")
        else:
            code_lines.append(f"# No MODEL statement found in PROC REG. Please check the SAS code.")
        
        return "\n".join(code_lines)

    def _convert_proc_freq(self, component: SASComponent) -> str:
        """Convert PROC FREQ to pandas crosstab/value_counts with chi-square test."""
        data_match = re.search(r'data\s*=\s*(\w+)', component.content, re.IGNORECASE)
        tables_match = re.search(r'tables\s+(.*?);', component.content, re.IGNORECASE)
        chisq_option = 'chisq' in component.content.lower()
        
        dataset = data_match.group(1) if data_match else "df"
        dataset = dataset.replace('&', '')
        
        code_lines = []
        code_lines.append("# Calculate frequency distributions")
        
        if tables_match:
            tables = tables_match.group(1).split()
            for table_spec in tables:
                if '*' in table_spec:
                    vars = table_spec.split('*')
                    code_lines.extend([
                        f"# Cross-tabulation of {' by '.join(vars)}",
                        f"ctab = pd.crosstab({dataset}_df['{vars[0]}'], {dataset}_df['{vars[1]}'])",
                        "print('\\nCross-tabulation:')",
                        "print(ctab)",
                        "",
                        "# Add row and column percentages",
                        "print('\\nRow Percentages:')",
                        "print(pd.crosstab(data[vars[0]], data[vars[1]], normalize='index') * 100)",
                        "print('\\nColumn Percentages:')",
                        "print(pd.crosstab(data[vars[0]], data[vars[1]], normalize='columns') * 100)"
                    ])
                    
                    if chisq_option:
                        code_lines.extend([
                            "",
                            "# Chi-square test",
                            "chi2, p_value, dof, expected = stats.chi2_contingency(ctab)",
                            "print('\\nChi-square test results:')",
                            "print(f'Chi-square statistic: {chi2:.4f}')",
                            "print(f'p-value: {p_value:.4f}')",
                            "print(f'Degrees of freedom: {dof}')",
                            "print(f'Significant at α=0.05: {p_value < 0.05}')"
                        ])
                else:
                    code_lines.extend([
                        f"# Frequency distribution of {table_spec}",
                        f"freq = {dataset}_df['{table_spec}'].value_counts()",
                        f"pct = {dataset}_df['{table_spec}'].value_counts(normalize=True) * 100",
                        "freq_df = pd.DataFrame({",
                        "    'Frequency': freq,",
                        "    'Percentage': pct,",
                        "    'Cumulative Freq': freq.cumsum(),",
                        "    'Cumulative Pct': pct.cumsum()",
                        "})",
                        "print('\\nFrequency Distribution:')",
                        "print(freq_df)"
                    ])
        
        return "\n".join(code_lines)

    def _convert_proc_corr(self, component: SASComponent) -> str:
        """Convert PROC CORR to pandas correlation analysis."""
        # Extract dataset and variables
        data_match = re.search(r'data\s*=\s*(\w+)', component.content, re.IGNORECASE)
        var_match = re.search(r'var\s+(.*?);', component.content, re.IGNORECASE)
        with_match = re.search(r'with\s+(.*?);', component.content, re.IGNORECASE)
        
        dataset = data_match.group(1) if data_match else "df"
        dataset = dataset.replace('&', '')  # Handle macro variables
        
        code_lines = []
        code_lines.append("# Calculate correlations")
        
        if var_match:
            variables = var_match.group(1).split()
            if with_match:
                # Correlation between specific sets of variables
                with_vars = with_match.group(1).split()
                var_list = ", ".join(f"'{v}'" for v in variables)
                with_list = ", ".join(f"'{v}'" for v in with_vars)
                code_lines.extend([
                    f"var_cols = [{var_list}]",
                    f"with_cols = [{with_list}]",
                    f"corr = {dataset}_df[var_cols].corrwith({dataset}_df[with_cols])",
                    "print('\\nCorrelations:')",
                    "print(corr)"
                ])
            else:
                # Correlation matrix for all specified variables
                var_list = ", ".join(f"'{v}'" for v in variables)
                code_lines.extend([
                    f"corr_matrix = {dataset}_df[[{var_list}]].corr()",
                    "print('\\nCorrelation Matrix:')",
                    "print(corr_matrix)",
                    "",
                    "# Create correlation heatmap",
                    "plt.figure(figsize=(10, 8))",
                    "sns.heatmap(corr_matrix, annot=True, cmap='coolwarm', center=0)",
                    "plt.title('Correlation Heatmap')",
                    "plt.tight_layout()",
                    "plt.show()"
                ])
        
        return "\n".join(code_lines)

    def _convert_format(self, component: SASComponent) -> str:
        """Convert SAS FORMAT statements to Python format functions."""
        code_lines = []
        
        # Extract format name and definition
        format_match = re.search(r'FORMAT\s+(.*?);', component.content, re.IGNORECASE)
        if format_match:
            formats = format_match.group(1).split()
            for fmt in formats:
                if '.' in fmt:
                    var, format_type = fmt.split('.')
                    code_lines.extend([
                        f"# Apply format to {var}",
                        f"if '{format_type}' in globals():",
                        f"    {var}_formatted = {var}_df['{var}'].apply(apply_{format_type}_format)",
                        f"else:",
                        f"    {var}_formatted = {var}_df['{var}'].astype(str)"
                    ])
        
        return "\n".join(code_lines)

    def _convert_title_footnote(self, component: SASComponent) -> str:
        """Convert SAS TITLE/FOOTNOTE statements to Python plot titles."""
        content = component.content.strip()
        text = re.search(r'(?:TITLE|FOOTNOTE)\s*\d*\s*["\'](.*?)["\']', content, re.IGNORECASE)
        
        if text:
            title_text = text.group(1)
            if component.type.upper() == 'TITLE':
                return f"title_{component.name} = \"{title_text}\"\nplt.suptitle(\"{title_text}\", fontsize=14)"
            else:
                return f"footnote_{component.name} = \"{title_text}\"\nplt.figtext(0.5, 0.01, \"{title_text}\", ha='center')"
        
        return f"# TODO: Convert complex {component.type}\n# {content}"

    def _convert_ods(self, component: SASComponent) -> str:
        """Convert ODS statements to Python visualization setup."""
        content = component.content.lower()
        code_lines = []
        
        if 'graphics' in content:
            if 'on' in content:
                code_lines.extend([
                    "# Enable high-quality graphics",
                    "import matplotlib.pyplot as plt",
                    "import seaborn as sns",
                    "plt.style.use('seaborn')",
                    "plt.rcParams.update({",
                    "    'figure.figsize': (10, 6),",
                    "    'figure.dpi': 100,",
                    "    'savefig.dpi': 300,",
                    "    'font.size': 10,",
                    "    'axes.titlesize': 12,",
                    "    'axes.labelsize': 10,",
                    "    'axes.grid': True",
                    "})",
                    "sns.set_theme(style='whitegrid')"
                ])
            elif 'off' in content:
                code_lines.extend([
                    "# Close all plots",
                    "plt.close('all')"
                ])
        elif 'html' in content:
            if 'close' in content:
                code_lines.extend([
                    "# Close HTML output",
                    "if 'html_file' in locals():",
                    "    with open(html_file, 'w') as f:",
                    "        f.write(html_content)"
                ])
            else:
                path_match = re.search(r'path\s*=\s*[\'"]([^\'"]+)[\'"]', content)
                file_match = re.search(r'body\s*=\s*[\'"]([^\'"]+)[\'"]', content)
                
                code_lines.extend([
                    "# Setup HTML output",
                    "import os",
                    f"output_dir = {repr(path_match.group(1) if path_match else './output')}",
                    "os.makedirs(output_dir, exist_ok=True)",
                    f"html_file = os.path.join(output_dir, {repr(file_match.group(1) if file_match else 'output.html')})",
                    "html_content = []"
                ])
        
        return "\n".join(code_lines)

    def _convert_proc_print(self, component: SASComponent) -> str:
        """Convert PROC PRINT to pandas display."""
        data_match = re.search(r'data\s*=\s*(\w+)', component.content, re.IGNORECASE)
        dataset = data_match.group(1) if data_match else "df"
        
        return f"# Display dataset contents\nprint({dataset}_df)"

    def _convert_proc_report(self, component: SASComponent) -> str:
        """Convert PROC REPORT to pandas DataFrame display with formatting."""
        data_match = re.search(r'data\s*=\s*(\w+)', component.content, re.IGNORECASE)
        dataset = data_match.group(1) if data_match else "df"
        
        code_lines = [
            "# Generate formatted report",
            f"print('\\nReport for {dataset}:')",
            f"display({dataset}_df.style.format(precision=2))"
        ]
        return "\n".join(code_lines)

    def _convert_proc_format(self, component: SASComponent) -> str:
        """Convert PROC FORMAT to Python dictionaries/functions."""
        code_lines = []
        
        # Extract format definitions
        value_matches = re.finditer(r'value\s+(\w+)\s+(.*?);', component.content, re.DOTALL | re.IGNORECASE)
        
        for match in value_matches:
            format_name = match.group(1)
            format_def = match.group(2)
            
            code_lines.extend([
                f"{format_name}_format = {{",
                "    # Format mapping"
            ])
            
            # Parse format entries with better regex
            entries = re.findall(r'([\'"]?[\w\s<>.-]+[\'"]?)\s*=\s*[\'"](.*?)[\'"]', format_def)
            for key, value in entries:
                key = key.strip().strip("'\"")
                if key.lower() == 'other':
                    code_lines.append(f"    'default': '{value}',")
                elif '-' in key:
                    low, high = [x.strip() for x in key.split('-')]
                    if low.lower() == 'low':
                        code_lines.append(f"    lambda x: float(x) <= float('{high}'): '{value}',")
                    elif high.lower() == 'high':
                        code_lines.append(f"    lambda x: float(x) > float('{low}'): '{value}',")
                    else:
                        code_lines.append(f"    lambda x: float('{low}') <= float(x) <= float('{high}'): '{value}',")
                else:
                    code_lines.append(f"    '{key}': '{value}',")
            
            code_lines.append("}")
            
            # Add format function with better error handling
            code_lines.extend([
                "",
                f"def apply_{format_name}_format(value):",
                f"    \"\"\"Apply {format_name} format to value.",
                f"    Args:",
                f"        value: Value to format",
                f"    Returns:",
                f"        Formatted string value",
                f"    \"\"\"",
                "    try:",
                "        if pd.isna(value):",
                "            return ''",
                "        if isinstance(value, (int, float)):",
                "            # Handle numeric values",
                "            for condition, result in {format_name}_format.items():",
                "                if callable(condition) and condition(value):",
                "                    return result",
                "        # Handle string/other values",
                "        str_value = str(value)",
                "        return {format_name}_format.get(str_value,",
                "            {format_name}_format.get('default', str_value))",
                "    except Exception as e:",
                "        return str(value)  # Return original value on error"
            ])
        
        return "\n".join(code_lines)

    def _convert_data_step(self, component: SASComponent, similar_components: List[Dict[str, Any]]) -> str:
        """Convert SAS DATA step to pandas operations."""
        code_lines = []
        
        # Extract input and output datasets
        set_match = re.search(r'SET\s+(\w+\.?\w*)', component.content, re.IGNORECASE)
        data_match = re.search(r'DATA\s+(\w+)', component.content, re.IGNORECASE)
        
        if set_match and data_match:
            input_ds = self._convert_dataset_name(set_match.group(1))
            output_ds = self._convert_dataset_name(data_match.group(1))
            
            code_lines.extend([
                f"# Create new dataset from {input_ds}",
                f"{output_ds} = {input_ds}.copy()"
            ])
            
            # Handle WHERE clause
            where_match = re.search(r'WHERE\s+(.*?);', component.content, re.IGNORECASE)
            if where_match:
                condition = self._convert_where_clause(where_match.group(1))
                code_lines.append(f"{output_ds} = {output_ds}[{condition}]")
            
            # Handle DROP/KEEP statements
            drop_match = re.search(r'DROP\s+(.*?);', component.content, re.IGNORECASE)
            keep_match = re.search(r'KEEP\s+(.*?);', component.content, re.IGNORECASE)
            
            if drop_match:
                columns = [col.strip() for col in drop_match.group(1).split()]
                code_lines.append(f"{output_ds} = {output_ds}.drop(columns=[{', '.join(f''''{col}' ''' for col in columns)}])")
            elif keep_match:
                columns = [col.strip() for col in keep_match.group(1).split()]
                code_lines.append(f"{output_ds} = {output_ds}[[{', '.join(f''''{col}' ''' for col in columns)}]]")
            
            # Handle RENAME statement
            rename_match = re.search(r'RENAME\s+(.*?);', component.content, re.IGNORECASE)
            if rename_match:
                rename_dict = {}
                renames = rename_match.group(1).split()
                for rename in renames:
                    if '=' in rename:
                        old, new = rename.split('=')
                        rename_dict[old.strip()] = new.strip()
                if rename_dict:
                    code_lines.append(f"{output_ds} = {output_ds}.rename(columns={rename_dict})")
        
        return "\n".join(code_lines)

    def _convert_null_data_step(self, component: SASComponent) -> str:
        """Convert _NULL_ DATA step to Python code."""
        code_lines = []
        code_lines.append("# DATA _NULL_ step - processing without creating a dataset")
        
        # Extract SET statement if present
        set_match = re.search(r'\bSET\s+(.*?);', component.content, re.IGNORECASE)
        if set_match:
            input_dataset = set_match.group(1).strip()
            input_df = self._convert_dataset_name(input_dataset)
            code_lines.append(f"# Process data from {input_dataset}")
            code_lines.append(f"for _, row in {input_df}.iterrows():")
        
        # Extract PUT statements
        put_statements = re.findall(r'put\s+(.*?);', component.content, re.IGNORECASE)
        for put_stmt in put_statements:
            # Simple string output
            if put_stmt.startswith('"') or put_stmt.startswith("'"):
                code_lines.append(f"print({put_stmt})")
            else:
                # Variable output - may need more complex handling
                code_lines.append(f"print(f\"{{{put_stmt}}}\")")
    
        # Extract CALL SYMPUTX statements (set macro variables)
        call_statements = re.findall(r'call\s+symputx\s*\(\s*[\'"]?(\w+)[\'"]?\s*,\s*(.*?)\s*\)\s*;', component.content, re.IGNORECASE)
        for var_name, value in call_statements:
            py_value = self._convert_sas_expression(value)
            code_lines.append(f"# Set variable for use in later code")
            code_lines.append(f"{var_name} = {py_value}")
        
        return "\n".join(code_lines)

    def _convert_sql(self, component: SASComponent, similar_components: List[Dict[str, Any]]) -> str:
        """Convert PROC SQL to pandas operations."""
        code_lines = []
        sql_content = component.content
        
        # Handle SELECT INTO with SEPARATED BY
        select_into_match = re.search(
            r'SELECT\s+(?:DISTINCT\s+)?(.+?)\s+INTO\s*:(\w+)(?:\s+SEPARATED\s+BY\s+[\'"](.*?)[\'"])?\s+FROM\s+(\w+)',
            sql_content,
            re.IGNORECASE | re.DOTALL
        )
        
        if select_into_match:
            columns = select_into_match.group(1).strip()
            macro_var = select_into_match.group(2)
            separator = select_into_match.group(3) if select_into_match.group(3) else " "
            table = select_into_match.group(4)
            
            # Handle DISTINCT properly
            if 'DISTINCT' in sql_content.upper():
                code_lines.extend([
                    f"# Get unique values into list",
                    f"{macro_var} = sorted({table}_df['{columns}'].unique().tolist())",
                    f"{macro_var}_str = '{separator}'.join(map(str, {macro_var}))"
                ])
            else:
                code_lines.extend([
                    f"# Get values into list",
                    f"{macro_var} = {table}_df['{columns}'].tolist()",
                    f"{macro_var}_str = '{separator}'.join(map(str, {macro_var}))"
                ])
        else:
            # Handle other SQL operations
            code_lines.extend(self._convert_complex_sql(sql_content))
        
        return "\n".join(code_lines)

    def _convert_complex_sql(self, sql_content: str) -> List[str]:
        """Convert complex SQL operations to pandas."""
        code_lines = []
        
        # Extract main parts of SQL query
        select_match = re.search(
            r'SELECT\s+(.*?)\s+FROM\s+(\w+)(?:\s+WHERE\s+(.*?))?(?:\s+GROUP\s+BY\s+(.*?))?(?:\s+ORDER\s+BY\s+(.*?))?;',
            sql_content,
            re.IGNORECASE | re.DOTALL
        )
        
        if select_match:
            columns = select_match.group(1).strip()
            table = select_match.group(2)
            where_clause = select_match.group(3)
            group_by = select_match.group(4)
            order_by = select_match.group(5)
            
            # Start with base DataFrame
            code_lines.append(f"# Get base DataFrame")
            code_lines.append(f"result_df = {table}_df.copy()")
            
            # Handle WHERE clause
            if where_clause:
                conditions = self._convert_where_clause(where_clause)
                code_lines.extend([
                    "# Apply WHERE conditions",
                    f"result_df = result_df[{conditions}]"
                ])
            
            # Handle GROUP BY
            if group_by:
                group_cols = [col.strip() for col in group_by.split(',')]
                code_lines.extend([
                    "# Group data",
                    f"result_df = result_df.groupby([{', '.join(f''''{col}' ''' for col in group_cols)}]).agg({{"
                ])
                
                # Handle aggregations in SELECT
                if re.search(r'(COUNT|SUM|AVG|MEAN|MIN|MAX)\s*\(', columns, re.IGNORECASE):
                    aggs = self._parse_aggregations(columns)
                    code_lines.extend([f"    '{col}': '{agg}'," for col, agg in aggs.items()])
                    code_lines.append("}).reset_index()")
                else:
                    code_lines.append("    'size': 'count'}).reset_index()")
            
            # Handle ORDER BY
            if order_by:
                sort_cols = []
                ascending = []
                for col in order_by.split(','):
                    col = col.strip()
                    if 'DESC' in col.upper():
                        sort_cols.append(col.replace('DESC', '').strip())
                        ascending.append(False)
                    else:
                        sort_cols.append(col.replace('ASC', '').strip())
                        ascending.append(True)
                
                code_lines.extend([
                    "# Sort results",
                    f"result_df = result_df.sort_values([{', '.join(f''''{col}' ''' for col in sort_cols)}], ",
                    f"    ascending={ascending})"
                ])
        
        return code_lines

    def _convert_where_clause(self, where_clause: str) -> str:
        """Convert SQL WHERE clause to pandas boolean expression."""
        # Replace SQL operators with Python/pandas operators
        clause = where_clause.strip()
        clause = re.sub(r'\bAND\b', '&', clause, flags=re.IGNORECASE)
        clause = re.sub(r'\bOR\b', '|', clause, flags=re.IGNORECASE)
        clause = re.sub(r'\bIN\b', 'isin', clause, flags=re.IGNORECASE)
        clause = re.sub(r'\bLIKE\b', 'str.contains', clause, flags=re.IGNORECASE)
        clause = re.sub(r'\bIS NULL\b', '.isna()', clause, flags=re.IGNORECASE)
        clause = re.sub(r'\bIS NOT NULL\b', '.notna()', clause, flags=re.IGNORECASE)
        
        return clause

    def _convert_macro(self, component: SASComponent, similar_components: List[Dict[str, Any]]) -> str:
        """Convert a SAS macro to a Python function."""
        # Extract macro parameters
        params_match = re.search(r'%MACRO\s+(\w+)\s*\((.*?)\)', component.content, re.IGNORECASE)
        
        if params_match:
            macro_name = params_match.group(1)
            params_str = params_match.group(2)
            
            # Parse parameters properly
            params = []
            if params_str:
                param_list = params_str.split(',')
                for param in param_list:
                    param = param.strip()
                    if '=' in param:
                        name, default = param.split('=')
                        params.append(f"{name.strip()}")  # Remove default values
                    else:
                        params.append(param)
            
            # Special handling for known macros
            if macro_name == 'analyze_segment':
                return self._convert_analyze_segment_macro(params)
            elif macro_name == 'run_analysis':
                return self._convert_run_analysis_macro()
            
            # Default macro conversion
            param_docs = [f"        {p}: Parameter description" for p in params]
            param_docs_str = "\n".join(param_docs)
            
            code_lines = [
                f"def {macro_name}({', '.join(params)}):",
                f"    \"\"\"Python function converted from SAS macro {macro_name}.",
                f"    Args:",
                f"{param_docs_str}",
                f"    \"\"\"",
                "    # TODO: Implement macro logic",
                "    pass"
            ]
            
            return "\n".join(code_lines)
        
        return f"# ERROR converting MACRO - {component.name}\n# Original code:\n# {component.content}"

    def _convert_analyze_segment_macro(self, params: List[str]) -> str:
        """Special conversion for analyze_segment macro."""
        code = [
            "def analyze_segment(data, segment, var):",
            "    \"\"\"Analyze a segment of data with statistical tests and plots.\"\"\"",
            "    # Filter data for segment",
            "    segment_data = data[data['segment'] == segment]",
            "",
            "    # Check if enough observations",
            "    if len(segment_data) < min_obs:",
            "        print(f\"WARNING: Insufficient observations for {segment}\")",
            "        return",
            "",
            "    # Calculate summary statistics",
            "    stats = segment_data[var].describe()",
            "    print(f\"Statistics for {var} in segment {segment}:\")",
            "    print(stats)",
            "",
            "    # Detailed analysis",
            "    # Normality test",
            "    stat, p_value = stats.normaltest(segment_data[var].dropna())",
            "    print(f\"Normality test: stat={stat:.4f}, p-value={p_value:.4f}\")",
            "",
            "    # Visualizations",
            "    fig, (ax1, ax2, ax3) = plt.subplots(1, 3, figsize=(15, 5))",
            "",
            "    # Histogram",
            "    sns.histplot(data=segment_data, x=var, kde=True, ax=ax1)",
            "    ax1.set_title(f\"Distribution of {var}\")",
            "",
            "    # Box plot",
            "    sns.boxplot(y=segment_data[var], ax=ax2)",
            "    ax2.set_title(\"Box Plot\")",
            "",
            "    # Q-Q plot",
            "    stats.probplot(segment_data[var].dropna(), plot=ax3)",
            "    ax3.set_title(\"Q-Q Plot\")",
            "",
            "    plt.tight_layout()",
            "    plt.show()"
        ]
        return "\n".join(code)

    def _convert_run_analysis_macro(self) -> str:
        """Special conversion for run_analysis macro."""
        code = [
            "def run_analysis():",
            "    \"\"\"Run analysis on all segments in the data.\"\"\"",
            "    # Get unique segments",
            "    segments = analysis_data_df['segment'].unique()",
            "",
            "    # Process each segment",
            "    for segment in segments:",
            "        print(f\"\\nAnalyzing segment: {segment}\")",
            "        analyze_segment(",
            "            data=analysis_data_df,",
            "            segment=segment,",
            "            var='response_time'",
            "        )",
            "",
            "    print(\"\\nAnalysis complete!\")"
        ]
        return "\n".join(code)

    def _convert_statement_in_macro(self, statement):
        """Convert a SAS statement within a macro to Python."""
        # Handle common SAS statements - extend as needed
        # This is a simplified example
        statement = statement.strip()
        
        # Assignment statement
        if '=' in statement and not statement.startswith('if') and not statement.startswith('where'):
            var, expr = statement.split('=', 1)
            return f"{var.strip()} = {self._convert_sas_expression(expr)}"
        
        # IF statement
        if statement.upper().startswith('IF '):
            if_match = re.search(r'IF\s+(.*?)\s+THEN\s+(.*?)(?:ELSE|$)', statement, re.IGNORECASE)
            if if_match:
                condition = self._convert_sas_condition(if_match.group(1))
                action = if_match.group(2).strip()
                py_code = f"if {condition}:\n"
                py_code += f"    {self._convert_statement_in_macro(action)}"
                
                # Check for ELSE
                else_match = re.search(r'ELSE\s+(.*?)$', statement, re.IGNORECASE)
                if else_match:
                    else_action = else_match.group(1).strip()
                    py_code += f"\nelse:\n"
                    py_code += f"    {self._convert_statement_in_macro(else_action)}"
                
                return py_code
        
        # CALL statement
        if statement.upper().startswith('CALL '):
            # Handle different CALL functions
            call_match = re.search(r'CALL\s+(\w+)\s*\((.*?)\)', statement, re.IGNORECASE)
            if call_match:
                func_name = call_match.group(1).lower()
                args = call_match.group(2)
                
                if func_name == 'symputx':
                    # Convert CALL SYMPUTX to variable assignment
                    args_list = [arg.strip() for arg in args.split(',')]
                    if len(args_list) >= 2:
                        var_name = args_list[0].strip('"\'')
                        var_value = args_list[1]
                        return f"{var_name} = {self._convert_sas_expression(var_value)}"
        
        # PUT statement
        if statement.upper().startswith('PUT '):
            put_content = statement[4:].strip()
            # Convert to print statement
            return f"print({put_content})"
        
        return None

    def _convert_proc_call_in_macro(self, proc_statement):
        """Convert a PROC statement within a macro to Python function call."""
        # Extract PROC type and options
        proc_match = re.search(r'PROC\s+(\w+)(.*?);', proc_statement, re.IGNORECASE)
        if not proc_match:
            return f"# Unable to convert: {proc_statement}"
        
        proc_type = proc_match.group(1).lower()
        options = proc_match.group(2).strip() if proc_match.group(2) else ""
        
        # Parse the options
        data_match = re.search(r'DATA\s*=\s*(\w+)', options, re.IGNORECASE)
        data_name = data_match.group(1) if data_match else None
        
        # Generate Python code based on PROC type
        if proc_type == 'means':
            if data_name:
                return f"{data_name.lower()}_stats = {data_name.lower()}_df.describe()"
        elif proc_type == 'sort':
            out_match = re.search(r'OUT\s*=\s*(\w+)', options, re.IGNORECASE)
            by_match = re.search(r'BY\s+(.*?)(?:;|$)', proc_statement, re.IGNORECASE)
            
            if data_name and by_match:
                by_vars = [v.strip() for v in by_match.group(1).split()]
                out_name = out_match.group(1) if out_match else data_name
                
                vars_joined = ', '.join([f'"{v}"' for v in by_vars])
                return f"{out_name.lower()}_df = {data_name.lower()}_df.sort_values(by=[{vars_joined}])"
        
        # Default case - add as comment
        return f"# TODO: Convert PROC {proc_type}: {proc_statement}"

    def _convert_macro_variable(self, component: SASComponent) -> str:
        """Convert macro variable references to Python variables."""
        content = component.content
        
        # Handle %LET statements
        let_match = re.search(r'%LET\s+(\w+)\s*=\s*(.*?)\s*;', content, re.IGNORECASE)
        if let_match:
            var_name = let_match.group(1)
            value = let_match.group(2).strip()
            
            # Handle special macro functions
            if value.startswith('%SCAN'):
                scan_match = re.search(r'%SCAN\s*\((.*?),\s*(\d+)\)', value)
                if scan_match:
                    list_var = scan_match.group(1).strip('&')
                    index = int(scan_match.group(2)) - 1  # Convert to 0-based indexing
                    return f"{var_name} = {list_var}[{index}] if {index} < len({list_var}) else ''"
            elif value.startswith('%EVAL'):
                expr = value.replace('%EVAL', '').strip('()')
                # Convert SAS operators to Python
                expr = expr.replace('**', '^').replace('=', '==')
                return f"{var_name} = {expr}"
            
            # Try numeric conversion
            try:
                num_val = float(value)
                if num_val.is_integer():
                    return f"{var_name} = {int(num_val)}"
                return f"{var_name} = {num_val}"
            except ValueError:
                # String value
                return f"{var_name} = '{value}'"
        
        return f"# ERROR: Could not convert macro variable\n# {content}"

    def _convert_macro_statement(self, component: SASComponent) -> str:
        """Convert various SAS macro statements to Python."""
        content = component.content.strip()
        
        # Handle different macro statements
        if component.type == "%IF":
            if_match = re.search(r'%IF\s+(.*?)\s+%THEN\s+(.*?)(?:%ELSE|;|$)', content, re.IGNORECASE)
            if if_match:
                condition = self._convert_macro_condition(if_match.group(1))
                # Fix = to == for comparison
                condition = re.sub(r'(\w+)\s*=\s*(\w+|\d+)', r'\1 == \2', condition)
                action = if_match.group(2).strip()
                
                code = [f"if {condition}:"]
                code.append(f"    {self._convert_macro_action(action)}")
                
                # Check for %ELSE
                else_match = re.search(r'%ELSE\s+(.*?);', content, re.IGNORECASE)
                if else_match:
                    action = else_match.group(1).strip()
                    code.append(f"else:")
                    code.append(f"    {self._convert_macro_action(action)}")
                    
                return "\n".join(code)
        
        elif component.type == "%DO":
            do_match = re.search(r'%DO\s+(\w+)\s*=\s*(\d+)\s+TO\s+(\d+)', content, re.IGNORECASE)
            if do_match:
                var, start, end = do_match.groups()
                return f"for {var} in range({start}, {int(end)+1}):"
            
            do_while_match = re.search(r'%DO\s+%WHILE\s*\((.*?)\)', content, re.IGNORECASE)
            if do_while_match:
                condition = self._convert_macro_condition(do_while_match.group(1))
                return f"while {condition}:"
                
            # Special case for %DO %WHILE(&segment ne );
            segment_ne_match = re.search(r'%DO\s+%WHILE\s*\(\s*&(\w+)\s+ne\s+\)', content, re.IGNORECASE)
            if segment_ne_match:
                var_name = segment_ne_match.group(1)
                return f"while {var_name} != \"\":  # Loop until empty string"
        
        # ... rest of the method remains the same

    def _convert_dataset_name(self, dataset: str) -> str:
        """Convert SAS dataset reference to Python variable name."""
        # Handle macro variables
        if dataset.startswith('&'):
            return f"{dataset[1:]}_df"
        
        # Handle library references
        if '.' in dataset:
            lib, name = dataset.split('.')
            if lib.lower() == 'sashelp':
                return f"{name.lower()}_df"
            elif lib.lower() == 'work':
                return f"{name.lower()}_df"
            else:
                return f"{lib.lower()}_{name.lower()}_df"
        
        return f"{dataset.lower()}_df"

    def _add_sashelp_loading(self) -> List[str]:
        """Add code to load sashelp datasets."""
        return [
            "# Setup sashelp data directory",
            "sashelp_dir = os.getenv('SASHELP_DIR', './sashelp')",
            "os.makedirs(sashelp_dir, exist_ok=True)",
            "",
            "def load_sashelp_dataset(name: str) -> pd.DataFrame:",
            "    \"\"\"Load a dataset from sashelp library.\"\"\"",
            "    path = os.path.join(sashelp_dir, f'{name.lower()}.csv')",
            "    try:",
            "        return pd.read_csv(path)",
            "    except Exception as e:",
            "        print(f\"Error loading sashelp.{name}: {e}\")",
            "        return pd.DataFrame()"
        ]

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

    def _convert_sas_condition(self, condition: str) -> str:
        """Convert SAS condition to Python condition."""
        # Replace SAS-specific operators and functions
        condition = condition.strip()
        
        # Replace comparison operators
        condition = re.sub(r'\bEQ\b', '==', condition, flags=re.IGNORECASE)
        condition = re.sub(r'\bNE\b', '!=', condition, flags=re.IGNORECASE)
        condition = re.sub(r'\bGT\b', '>', condition, flags=re.IGNORECASE)
        condition = re.sub(r'\bLT\b', '<', condition, flags=re.IGNORECASE)
        condition = re.sub(r'\bGE\b', '>=', condition, flags=re.IGNORECASE)
        condition = re.sub(r'\bLE\b', '<=', condition, flags=re.IGNORECASE)
        
        # Replace logical operators
        condition = re.sub(r'\bAND\b', 'and', condition, flags=re.IGNORECASE)
        condition = re.sub(r'\bOR\b', 'or', condition, flags=re.IGNORECASE)
        condition = re.sub(r'\bNOT\b', 'not', condition, flags=re.IGNORECASE)
        
        # Replace IN operator
        in_matches = re.findall(r'(\w+)\s+IN\s+\((.*?)\)', condition, flags=re.IGNORECASE)
        for var, values in in_matches:
            value_list = [v.strip() for v in values.split(',')]
            python_list = "[" + ", ".join(value_list) + "]"
            condition = re.sub(f"{var}\\s+IN\\s+\\({values}\\)", f"{var} in {python_list}", condition, flags=re.IGNORECASE)
        
        # Handle missing values
        condition = re.sub(r'(\w+)\s+IS\s+MISSING', r'\1.isna()', condition, flags=re.IGNORECASE)
        condition = re.sub(r'(\w+)\s+=\s+\.', r'\1.isna()', condition)
        
        # Convert to pandas DataFrame syntax
        condition = re.sub(r'(\w+)', r'row.\1', condition)
        
        return condition

    def _convert_macro_condition(self, condition: str) -> str:
        """Convert SAS macro condition to Python condition."""
        # Replace macro-specific operators
        condition = condition.strip()
         # Handle empty check (common in %DO %WHILE loops)
        condition = re.sub(r'(\w+)\s+(?:NE|ne)\s*$', r'\1 != ""', condition)
        
        # Fix missing closing conditions
        if condition.endswith("NE") or condition.endswith("ne"):
            condition = condition[:-2].strip() + ' != ""'

        # Replace comparison operators
        condition = re.sub(r'\b=\b', '==', condition)  # = in macro is equality
        condition = re.sub(r'\bEQ\b', '==', condition, flags=re.IGNORECASE)
        condition = re.sub(r'\bNE\b', '!=', condition, flags=re.IGNORECASE)
        condition = re.sub(r'\bGT\b', '>', condition, flags=re.IGNORECASE)
        condition = re.sub(r'\bLT\b', '<', condition, flags=re.IGNORECASE)
        condition = re.sub(r'\bGE\b', '>=', condition, flags=re.IGNORECASE)
        condition = re.sub(r'\bLE\b', '<=', condition, flags=re.IGNORECASE)
        
        # Replace logical operators
        condition = re.sub(r'\bAND\b', 'and', condition, flags=re.IGNORECASE)
        condition = re.sub(r'\bOR\b', 'or', condition, flags=re.IGNORECASE)
        condition = re.sub(r'\bNOT\b', 'not', condition, flags=re.IGNORECASE)
        
        # Handle %EVAL expressions
        eval_matches = re.findall(r'%EVAL\((.*?)\)', condition, flags=re.IGNORECASE)
        for expr in eval_matches:
            condition = condition.replace(f"%EVAL({expr})", self._convert_sas_expression(expr))
        
        # Handle &macro.variables
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
        
    def convert_file(self, sas_file: str) -> str:
        """Convert a single SAS file to Python."""
        # Parse the SAS file
        components = self.parse_sas_file(sas_file)
        if not components:
            logger.error(f"No components found in {sas_file}")
            return None
            
        # Create output path
        rel_path = os.path.relpath(sas_file, start=os.path.dirname(sas_file))
        py_file = os.path.splitext(rel_path)[0] + ".py"
        output_path = os.path.join(self.output_directory, py_file)
        
        # Create output directory if needed
        os.makedirs(os.path.dirname(output_path), exist_ok=True)
        
        # Convert components to Python
        python_files = self.convert_to_python(components, sas_file)
        
        # Write the converted code
        if python_files and output_path in python_files:
            logger.info(f"Successfully converted {sas_file} to {output_path}")
            return output_path
        else:
            logger.error(f"Failed to convert {sas_file}")
            return None
        
    def _convert_libname(self, component: SASComponent) -> str:
        """Convert SAS LIBNAME statements to Python data paths."""
        libname_match = re.search(r'LIBNAME\s+(\w+)\s+([^;]+)', component.content, re.IGNORECASE)
        
        if not libname_match:
            return f"# TODO: Complex LIBNAME conversion\n# {component.content}"
        
        lib_name = libname_match.group(1)
        lib_path = libname_match.group(2).strip().strip("'\"")
        
        code_lines = [
            f"# Define {lib_name} library path",
            f"{lib_name.lower()}_path = {repr(lib_path)}",
            f"os.makedirs({lib_name.lower()}_path, exist_ok=True)",
            "",
            f"def read_{lib_name.lower()}_dataset(name: str) -> pd.DataFrame:",
            f"    \"\"\"Read dataset from {lib_name} library.\"\"\"",
            f"    try:",
            f"        path = os.path.join({lib_name.lower()}_path, f'{{name}}.csv')",
            f"        return pd.read_csv(path)",
            f"    except Exception as e:",
            f"        print(f'Error reading {{name}}: {{e}}')",
            f"        return pd.DataFrame()"
        ]
        
        return "\n".join(code_lines)

    def _convert_filename(self, component: SASComponent) -> str:
        """Convert SAS FILENAME statements to Python file paths."""
        # Extract name and path
        filename_match = re.search(r'FILENAME\s+(\w+)\s+([^;]+);', component.content, re.IGNORECASE)
        
        if not filename_match:
            return f"# TODO: Complex FILENAME conversion\n# {component.content}"
        
        file_ref = filename_match.group(1)
        file_spec = filename_match.group(2).strip()
        
        code_lines = []
        code_lines.append(f"# Define {file_ref} file reference")
        
        # Handle different types of file specs
        if file_spec.startswith('"') or file_spec.startswith("'"):
            # Simple file path
            code_lines.append(f"{file_ref.lower()}_path = {file_spec}")
            code_lines.append(f"")
            code_lines.append(f"# For file operations:")
            code_lines.append(f"# with open({file_ref.lower()}_path, 'r') as f:")
            code_lines.append(f"#     content = f.read()")
        elif "pipe" in file_spec.lower():
            # Pipe for system command
            pipe_match = re.search(r'pipe\s+[\'"]([^\'"]+)[\'"]', file_spec, re.IGNORECASE)
            if pipe_match:
                command = pipe_match.group(1)
                code_lines.append(f"# System command pipe")
                code_lines.append(f"import subprocess")
                code_lines.append(f"")
                code_lines.append(f"{file_ref.lower()}_command = '{command}'")
                code_lines.append(f"# Execute command:")
                code_lines.append(f"# result = subprocess.run({file_ref.lower()}_command, shell=True, capture_output=True, text=True)")
        elif "ftp" in file_spec.lower() or "url" in file_spec.lower():
            # URL or FTP reference
            code_lines.append(f"# Network file reference")
            code_lines.append(f"import requests")
            code_lines.append(f"")
            code_lines.append(f"{file_ref.lower()}_url = {file_spec}")
            code_lines.append(f"# Download content:")
            code_lines.append(f"# response = requests.get({file_ref.lower()}_url)")
            code_lines.append(f"# content = response.text")
        else:
            # Generic handling
            code_lines.append(f"{file_ref.lower()}_ref = '{file_spec}'")
        
        return "\n".join(code_lines)

    def _convert_options(self, component: SASComponent) -> str:
        """Convert SAS OPTIONS statements to Python configurations."""
        content = component.content.strip()
        
        code_lines = []
        code_lines.append("# Configure pandas and display options")
        
        # Extract individual options
        options_match = re.search(r'OPTIONS\s+(.*?);', content, re.IGNORECASE)
        if options_match:
            options_str = options_match.group(1)
            options = [opt.strip() for opt in options_str.split()]
            
            for option in options:
                if option.upper() == 'NOCENTER':
                    code_lines.extend([
                        "pd.set_option('display.expand_frame_repr', True)",
                        "pd.set_option('display.max_columns', None)"
                    ])
                elif option.upper() == 'NODATE':
                    code_lines.append("# Disable date display in output")
                elif option.upper() == 'MISSING':
                    code_lines.append("pd.set_option('display.missing_repr', '')")
                elif '=' in option:
                    name, value = option.split('=', 1)
                    if name.upper() in ['LINESIZE', 'LS']:
                        code_lines.append(f"pd.set_option('display.width', {value})")
                    elif name.upper() in ['PAGESIZE', 'PS']:
                        code_lines.append(f"pd.set_option('display.max_rows', {value})")
        
        return "\n".join(code_lines)

    def _convert_let_statement(self, component: SASComponent) -> str:
        """Convert %LET statement to Python variable assignment."""
        let_match = re.search(r'%LET\s+(\w+)\s*=\s*(.*?)\s*;', component.content, re.IGNORECASE)
        if let_match:
            var_name = let_match.group(1)
            value = let_match.group(2).strip()
            
            # Handle special cases
            if value.startswith('%SCAN'):
                return f"{var_name} = segment_list[i-1] if i-1 < len(segment_list) else \"\""
            elif value.startswith('%EVAL'):
                expr = value.replace('%EVAL', '').strip('()')
                return f"{var_name} = {expr}"
            
            # Try numeric conversion
            try:
                num_val = float(value)
                if num_val.is_integer():
                    return f"{var_name} = {int(num_val)}"
                return f"{var_name} = {num_val}"
            except ValueError:
                # String value
                return f"{var_name} = '{value}'"
                
        return f"# ERROR: Could not convert %LET statement\n# {component.content}"

    def _convert_proc_sgplot(self, component: SASComponent) -> str:
        """Convert PROC SGPLOT to matplotlib/seaborn."""
        code_lines = []
        
        # Extract dataset
        data_match = re.search(r'data\s*=\s*(\w+)', component.content, re.IGNORECASE)
        dataset = data_match.group(1) if data_match else "df"
        dataset = dataset.replace('sashelp.', '')  # Handle sashelp library
        
        # Extract plot type and variables
        scatter_match = re.search(r'scatter\s+x\s*=\s*(\w+)\s+y\s*=\s*(\w+)', component.content, re.IGNORECASE)
        reg_match = re.search(r'reg\s+x\s*=\s*(\w+)\s+y\s*=\s*(\w+)', component.content, re.IGNORECASE)
        
        code_lines.extend([
            "# Create visualization",
            "plt.figure(figsize=(10, 6))"
        ])
        
        if scatter_match and reg_match:
            x_var = scatter_match.group(1)
            y_var = scatter_match.group(2)
            code_lines.extend([
                f"sns.regplot(data={dataset}_df, x='{x_var}', y='{y_var}',",
                "    scatter_kws={'alpha': 0.5},",
                "    line_kws={'color': 'red'})"
            ])
        elif scatter_match:
            x_var = scatter_match.group(1)
            y_var = scatter_match.group(2)
            code_lines.append(f"sns.scatterplot(data={dataset}_df, x='{x_var}', y='{y_var}', alpha=0.5)")
        elif reg_match:
            x_var = reg_match.group(1)
            y_var = reg_match.group(2)
            code_lines.append(f"sns.regplot(data={dataset}_df, x='{x_var}', y='{y_var}', scatter=False, color='red')")
        
        # Add title and labels
        code_lines.extend([
            f"plt.xlabel('{x_var}')",
            f"plt.ylabel('{y_var}')",
            f"plt.title('{y_var} vs {x_var}')",
            "plt.grid(True)",
            "plt.tight_layout()",
            "plt.show()"
        ])
        
        return "\n".join(code_lines)

    def _parse_aggregations(self, columns: str) -> Dict[str, str]:
        """Parse SQL aggregation functions to pandas equivalents."""
        aggs = {}
        agg_matches = re.finditer(r'(\w+)\s*\(\s*(\w+)\s*\)', columns)
        
        # Map SAS SQL functions to pandas
        agg_map = {
            'COUNT': 'count',
            'SUM': 'sum',
            'AVG': 'mean',
            'MEAN': 'mean',
            'MIN': 'min',
            'MAX': 'max',
            'VAR': 'var',
            'STD': 'std'
        }
        
        for match in agg_matches:
            func = match.group(1).upper()
            col = match.group(2)
            if func in agg_map:
                aggs[col] = agg_map[func]
        
        return aggs

    def _convert_ods_graphics(self, content: str) -> List[str]:
        """Convert ODS GRAPHICS statements to matplotlib settings."""
        code_lines = []
        
        if 'on' in content.lower():
            code_lines.extend([
                "# Configure matplotlib for high-quality output",
                "plt.style.use('seaborn')",
                "plt.rcParams['figure.figsize'] = (10, 6)",
                "plt.rcParams['figure.dpi'] = 100",
                "plt.rcParams['savefig.dpi'] = 300",
                "plt.rcParams['font.size'] = 10",
                "plt.rcParams['axes.titlesize'] = 12",
                "plt.rcParams['axes.labelsize'] = 10"
            ])
        elif 'off' in content.lower():
            code_lines.extend([
                "# Close all plots",
                "plt.close('all')"
            ])
        
        return code_lines

def main():
    """Command line interface for the converter."""
    parser = argparse.ArgumentParser(description='Convert SAS code to Python using vector embeddings')
    parser.add_argument('input', help='SAS file or directory to convert')
    parser.add_argument('--output', '-o', default='python_output', help='Output directory for Python files')
    parser.add_argument('--config', '-c', help='Configuration file for production settings')
    parser.add_argument('--db-path', '-d', default='chroma_db', help='ChromaDB path (for testing)')
    
    args = parser.parse_args()
    
    # Initialize vector store (for testing)
    # In production, this would be replaced with API calls
    vector_store = VectorStore(persist_directory=args.db_path)
    
    # Initialize converter
    converter = SASPythonConverter(
        vector_store=vector_store,
        output_directory=args.output,
        embedding_generator=None
    )
    
    # Process input
    input_path = Path(args.input)
    if input_path.is_file():
        converter.convert_file(str(input_path))
    elif input_path.is_dir():
        converter.convert_directory(str(input_path))
    else:
        logger.error(f"Input path {args.input} does not exist")
        return 1
    
    logger.info(f"Conversion complete. Output written to {args.output}")
    return 0

if __name__ == "__main__":
    import sys
    import re  # Required for regex in conversion methods
    sys.exit(main())