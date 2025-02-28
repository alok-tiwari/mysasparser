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
    
    def convert_to_python(self, sas_components: List[SASComponent], original_file_path: str) -> Dict[str, str]:
        """
        Convert SAS components to Python code.
        
        Args:
            sas_components: List of SAS components to convert
            original_file_path: Path to the original SAS file
            
        Returns:
            Dictionary mapping output file paths to Python code
        """
        python_files = {}
        sas_filename = os.path.basename(original_file_path)
        python_filename = os.path.splitext(sas_filename)[0] + ".py"
        output_path = os.path.join(self.output_directory, python_filename)
        
        # Track dependencies between components
        self._map_dependencies(sas_components)
        
        # Sort components by dependency order
        ordered_components = self._order_components_by_dependency(sas_components)
        
        # Start with imports
        python_code = [
            "# Auto-generated Python code from SAS file: " + sas_filename,
            "# Generated on: " + time.strftime("%Y-%m-%d %H:%M:%S"),
            "",
            "import pandas as pd",
            "import numpy as np",
            "from scipy import stats",
            ""
        ]
        
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
                f"# {'-'*50}",
                f"# {component.type}: {component.name} (Lines {component.line_start}-{component.line_end})",
                f"# {'-'*50}",
                converted_code,
                ""  # Empty line for readability
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
        
    def _convert_proc(self, component: SASComponent, similar_content: List[str]) -> str:
        """Convert SAS PROC statement to equivalent Python code."""
        proc_name = component.name.upper() if component.name else ""
        
        # Handle different PROC types
        if proc_name == "SORT":
            return self._convert_proc_sort(component)
        elif proc_name in ["MEANS", "SUMMARY"]:
            return self._convert_proc_means(component)
        elif proc_name == "UNIVARIATE":
            return self._convert_proc_univariate(component)
        elif proc_name == "TTEST":
            return self._convert_proc_ttest(component)
        elif proc_name == "REG":
            return self._convert_proc_reg(component)
        elif proc_name == "GLM":
            return self._convert_proc_glm(component)
        elif proc_name == "FREQ":
            return self._convert_proc_freq(component)
        elif proc_name == "TABULATE":
            return self._convert_proc_tabulate(component)
        elif proc_name == "FORMAT":
            return self._convert_proc_format(component)
        elif proc_name == "PRINT":
            return self._convert_proc_print(component)
        elif proc_name == "REPORT":
            return self._convert_proc_report(component)
        else:
            # Generic PROC conversion with comment
            return f"# TODO: Convert PROC {proc_name}\n# Original code:\n# " + component.content.replace("\n", "\n# ")

    def _convert_proc_sort(self, component: SASComponent) -> str:
        """Convert PROC SORT to pandas sort_values()."""
        # Extract data parameter
        data_match = re.search(r'data\s*=\s*(\w+)', component.content, re.IGNORECASE)
        out_match = re.search(r'out\s*=\s*(\w+)', component.content, re.IGNORECASE)
        by_match = re.search(r'by\s+(.*?);', component.content, re.IGNORECASE)
        
        if data_match and by_match:
            data_name = self._convert_dataset_name(data_match.group(1))
            by_vars = [v.strip() for v in by_match.group(1).split()]
            
            # Check for sorting options
            descending = []
            for i, var in enumerate(by_vars):
                if var.upper() == "DESCENDING":
                    descending.append(by_vars[i+1])
                    
            # Remove DESCENDING keyword from variables
            by_vars = [v for v in by_vars if v.upper() != "DESCENDING"]
            
            # Build ascending parameter
            ascending_list = ["False" if v in descending else "True" for v in by_vars]
            
            # Format the by variables for Python
            by_vars_str = "[" + ", ".join([f"'{v}'" for v in by_vars]) + "]"
            ascending_str = "[" + ", ".join(ascending_list) + "]"
            
            # Determine output dataset
            if out_match:
                out_name = self._convert_dataset_name(out_match.group(1))
            else:
                out_name = data_name
                
            # Generate code
            code = [
                f"# Sort data by {', '.join(by_vars)}",
                f"{out_name} = {data_name}.sort_values(by={by_vars_str}, ascending={ascending_str}, ignore_index=True)"
            ]
            
            return "\n".join(code)
        else:
            return f"# TODO: Convert PROC SORT (missing required parameters)\n# " + component.content.replace("\n", "\n# ")

    def _convert_proc_means(self, component: SASComponent) -> str:
        """Convert PROC MEANS to pandas describe() and aggregation."""
        # Extract parameters
        data_match = re.search(r'data\s*=\s*(\w+)', component.content, re.IGNORECASE)
        var_match = re.search(r'var\s+(.*?);', component.content, re.IGNORECASE)
        output_match = re.search(r'output\s+out\s*=\s*(\w+)(.*?);', component.content, re.IGNORECASE | re.DOTALL)
        by_match = re.search(r'by\s+(.*?);', component.content, re.IGNORECASE)
        
        # Build code
        code_lines = []
        
        # Handle data parameter
        if data_match:
            data_name = self._convert_dataset_name(data_match.group(1))
        else:
            data_name = "df"  # Default name
            
        # Start with base dataframe
        df_name = f"{data_name}_subset" if var_match or by_match else data_name
        
        # Handle VAR statement
        if var_match:
            vars_str = var_match.group(1).strip()
            var_list = [v.strip() for v in vars_str.split()]
            var_list_str = "[" + ", ".join([f"'{v}'" for v in var_list]) + "]"
            code_lines.append(f"{df_name} = {data_name}[{var_list_str}]")
        
        # Handle BY statement (groupby in pandas)
        if by_match:
            by_vars = by_match.group(1).strip()
            by_list = [v.strip() for v in by_vars.split()]
            by_list_str = "[" + ", ".join([f"'{v}'" for v in by_list]) + "]"
            group_name = f"{df_name}_grouped"
            code_lines.append(f"{group_name} = {df_name}.groupby({by_list_str})")
            
            # Determine aggregation
            if output_match:
                output_name = self._convert_dataset_name(output_match.group(1))
                stats_str = output_match.group(2).strip() if output_match.group(2) else ""
                
                # Parse statistics
                stats_dict = {}
                if stats_str:
                    stats_matches = re.findall(r'(\w+)\s*=\s*(\w+)', stats_str)
                    for stat, name in stats_matches:
                        stats_dict[stat.lower()] = name
                
                # Map SAS stats to pandas
                agg_dict = {}
                stat_map = {
                    'mean': 'mean', 
                    'std': 'std', 
                    'min': 'min', 
                    'max': 'max', 
                    'n': 'count',
                    'sum': 'sum',
                    'var': 'var',
                    'median': 'median',
                    'q1': lambda x: x.quantile(0.25),
                    'q3': lambda x: x.quantile(0.75)
                }
                
                # If no specific stats, use defaults
                if not stats_dict:
                    code_lines.append(f"{output_name} = {group_name}.agg(['mean', 'std', 'min', 'max', 'count']).reset_index()")
                else:
                    # Build aggregation dictionary
                    for var in var_list:
                        var_aggs = []
                        for sas_stat, name in stats_dict.items():
                            if sas_stat in stat_map:
                                var_aggs.append(f"'{name}': '{stat_map[sas_stat]}'")
                        
                        if var_aggs:
                            agg_dict[var] = "{" + ", ".join(var_aggs) + "}"
                    
                    # Format agg_dict for code
                    agg_str = "{\n    " + ",\n    ".join([f"'{var}': {aggs}" for var, aggs in agg_dict.items()]) + "\n}"
                    code_lines.append(f"{output_name} = {group_name}.agg({agg_str}).reset_index()")
            else:
                # Simple descriptive statistics
                code_lines.append(f"{df_name}_stats = {group_name}.describe()")
                code_lines.append(f"print({df_name}_stats)")
        else:
            # No grouping, just basic stats
            if output_match:
                output_name = self._convert_dataset_name(output_match.group(1))
                code_lines.append(f"{output_name} = {df_name}.describe().reset_index()")
                code_lines.append(f"{output_name} = {output_name}.rename(columns={{'index': 'statistic'}})")
            else:
                code_lines.append(f"{df_name}_stats = {df_name}.describe()")
                code_lines.append(f"print({df_name}_stats)")
        
        return "\n".join(code_lines)

    def _convert_proc_univariate(self, component: SASComponent) -> str:
        """Convert PROC UNIVARIATE to scipy.stats and matplotlib."""
        # Extract parameters
        data_match = re.search(r'data\s*=\s*(\w+)', component.content, re.IGNORECASE)
        var_match = re.search(r'var\s+(.*?);', component.content, re.IGNORECASE)
        plot_flag = re.search(r'\bplot\b', component.content, re.IGNORECASE)
        normal_flag = re.search(r'\bnormal\b', component.content, re.IGNORECASE)
        
        code_lines = []
        
        # Add imports
        code_lines.append("from scipy import stats")
        code_lines.append("import matplotlib.pyplot as plt")
        code_lines.append("import seaborn as sns")
        
        # Handle data parameter
        if data_match:
            data_name = self._convert_dataset_name(data_match.group(1))
        else:
            data_name = "df"  # Default name
        
        # Handle variables
        if var_match:
            var_list = [v.strip() for v in var_match.group(1).split()]
        else:
            code_lines.append(f"# Analyze all numeric columns")
            code_lines.append(f"var_list = {data_name}.select_dtypes(include=['number']).columns.tolist()")
            var_list = ["var_list"]  # Use the variable we just created
            
        # Generate analysis for each variable
        for var in var_list:
            if var == "var_list":  # Special case for dynamic variables
                code_lines.append(f"for col in {var}:")
                code_lines.append(f"    print(f\"\\nDescriptive statistics for {{col}}:\")")
                code_lines.append(f"    data = {data_name}[col].dropna()")
                
                # Basic descriptive statistics
                code_lines.append(f"    desc = data.describe()")
                code_lines.append(f"    print(desc)")
                
                # Normality test
                if normal_flag:
                    code_lines.append(f"    # Shapiro-Wilk normality test")
                    code_lines.append(f"    shapiro_test = stats.shapiro(data)")
                    code_lines.append(f"    print(f\"Shapiro-Wilk normality test: W={{shapiro_test[0]:.4f}}, p-value={{shapiro_test[1]:.4f}}\")")
                
                # Plots
                if plot_flag:
                    code_lines.append(f"    # Create plots")
                    code_lines.append(f"    plt.figure(figsize=(15, 10))")
                    
                    code_lines.append(f"    # Histogram")
                    code_lines.append(f"    plt.subplot(2, 2, 1)")
                    code_lines.append(f"    sns.histplot(data, kde=True)")
                    code_lines.append(f"    plt.title(f\"Histogram of {{col}}\")")
                    
                    code_lines.append(f"    # Box plot")
                    code_lines.append(f"    plt.subplot(2, 2, 2)")
                    code_lines.append(f"    sns.boxplot(y=data)")
                    code_lines.append(f"    plt.title(f\"Box Plot of {{col}}\")")
                    
                    code_lines.append(f"    # Q-Q plot")
                    code_lines.append(f"    plt.subplot(2, 2, 3)")
                    code_lines.append(f"    stats.probplot(data, plot=plt)")
                    code_lines.append(f"    plt.title(f\"Q-Q Plot of {{col}}\")")
                    
                    code_lines.append(f"    plt.tight_layout()")
                    code_lines.append(f"    plt.show()")
            else:
                var_name = f"'{var}'" if isinstance(var, str) else var
                code_lines.append(f"print(\"\\nDescriptive statistics for {var}:\")")
                code_lines.append(f"data = {data_name}[{var_name}].dropna()")
                
                # Basic descriptive statistics
                code_lines.append(f"desc = data.describe()")
                code_lines.append(f"print(desc)")
                
                # Additional statistics
                code_lines.append(f"additional_stats = {{")
                code_lines.append(f"    'skewness': data.skew(),")
                code_lines.append(f"    'kurtosis': data.kurtosis()")
                code_lines.append(f"}}")
                code_lines.append(f"print(pd.Series(additional_stats))")
                
                # Normality test
                if normal_flag:
                    code_lines.append(f"# Shapiro-Wilk normality test")
                    code_lines.append(f"shapiro_test = stats.shapiro(data)")
                    code_lines.append(f"print(f\"Shapiro-Wilk normality test: W={{shapiro_test[0]:.4f}}, p-value={{shapiro_test[1]:.4f}}\")")
                
                # Plots
                if plot_flag:
                    code_lines.append(f"# Create plots")
                    code_lines.append(f"plt.figure(figsize=(15, 10))")
                    
                    code_lines.append(f"# Histogram")
                    code_lines.append(f"plt.subplot(2, 2, 1)")
                    code_lines.append(f"sns.histplot(data, kde=True)")
                    code_lines.append(f"plt.title(\"Histogram of {var}\")")
                    
                    code_lines.append(f"# Box plot")
                    code_lines.append(f"plt.subplot(2, 2, 2)")
                    code_lines.append(f"sns.boxplot(y=data)")
                    code_lines.append(f"plt.title(\"Box Plot of {var}\")")
                    
                    code_lines.append(f"# Q-Q plot")
                    code_lines.append(f"plt.subplot(2, 2, 3)")
                    code_lines.append(f"stats.probplot(data, plot=plt)")
                    code_lines.append(f"plt.title(\"Q-Q Plot of {var}\")")
                    
                    code_lines.append(f"plt.tight_layout()")
                    code_lines.append(f"plt.show()")
        
        return "\n".join(code_lines)
    
    def _convert_proc_ttest(self, component: SASComponent) -> str:
        """Convert PROC TTEST to scipy.stats.ttest functions."""
        # Extract parameters
        data_match = re.search(r'data\s*=\s*(\w+)', component.content, re.IGNORECASE)
        var_match = re.search(r'var\s+(.*?);', component.content, re.IGNORECASE)
        h0_match = re.search(r'h0\s*=\s*(\S+)', component.content, re.IGNORECASE)
        alpha_match = re.search(r'alpha\s*=\s*(\S+)', component.content, re.IGNORECASE)
        where_match = re.search(r'where\s+(.*?);', component.content, re.IGNORECASE)
        
        code_lines = []
        
        # Import 
        code_lines.append("from scipy import stats")
        
        # Handle data parameter
        if data_match:
            data_name = self._convert_dataset_name(data_match.group(1))
        else:
            data_name = "df"
        
        # Handle hypothesized value
        h0_value = h0_match.group(1) if h0_match else "0"
        
        # Handle alpha
        alpha_value = alpha_match.group(1) if alpha_match else "0.05"
        
        # Handle variables
        if var_match:
            var_list = [v.strip() for v in var_match.group(1).split()]
            
            # Handle WHERE clause if present
            if where_match:
                where_condition = where_match.group(1)
                py_condition = self._convert_sas_condition(where_condition)
                code_lines.append(f"# Filter data based on WHERE clause")
                code_lines.append(f"filtered_data = {data_name}[{py_condition}]")
                data_name = "filtered_data"
            
            # Generate test for each variable
            for var in var_list:
                code_lines.append(f"\n# One-sample t-test for {var}")
                code_lines.append(f"data = {data_name}['{var}'].dropna()")
                code_lines.append(f"t_stat, p_value = stats.ttest_1samp(data, {h0_value})")
                code_lines.append(f"print(f\"One-sample t-test for {var}:\")")
                code_lines.append(f"print(f\"  t-statistic: {{t_stat:.4f}}\")")
                code_lines.append(f"print(f\"  p-value: {{p_value:.4f}}\")")
                code_lines.append(f"print(f\"  Significant at alpha={alpha_value}: {{p_value < float({alpha_value})}}\")")
        else:
            code_lines.append(f"# No variables specified for t-test")
        
        return "\n".join(code_lines)

    def _convert_format(self, component: SASComponent) -> str:
        """Convert SAS FORMAT/INFORMAT statements to Python functions."""
        code_lines = []
        content = component.content
        
        if component.type == "FORMAT":
            code_lines.append("# Define formatter functions for data display")
            
            # Extract format specifications
            format_specs = re.findall(r'(\w+)(?:\.|\:)(\w+)', content)
            
            for var, format_type in format_specs:
                if format_type.upper() in ['DATE', 'DATETIME', 'TIME']:
                    code_lines.append(f"# Format {var} as {format_type}")
                    code_lines.append(f"def format_{var.lower()}(value):")
                    code_lines.append(f"    return pd.to_datetime(value).strftime('%Y-%m-%d')")
                elif format_type.isdigit() or (format_type[0].isdigit() and '.' in format_type):
                    # Numeric format like 8.2
                    code_lines.append(f"# Format {var} with {format_type} precision")
                    code_lines.append(f"def format_{var.lower()}(value):")
                    if '.' in format_type:
                        width, precision = format_type.split('.')
                        code_lines.append(f"    return f'{{value:{width}.{precision}f}}'")
                    else:
                        code_lines.append(f"    return f'{{value:{format_type}}}'")
                else:
                    code_lines.append(f"# Format {var} with custom format {format_type}")
                    code_lines.append(f"def format_{var.lower()}(value):")
                    code_lines.append(f"    return str(value)")
        
        elif component.type == "INFORMAT":
            code_lines.append("# Define parser functions for data import")
            
            # Extract informat specifications
            informat_specs = re.findall(r'(\w+)(?:\.|\:)(\w+)', content)
            
            for var, informat_type in informat_specs:
                if informat_type.upper() in ['DATE', 'DATETIME', 'TIME']:
                    code_lines.append(f"# Parse {var} as {informat_type}")
                    code_lines.append(f"def parse_{var.lower()}(value):")
                    code_lines.append(f"    return pd.to_datetime(value)")
                elif informat_type.upper() == 'BEST':
                    code_lines.append(f"# Parse {var} as numeric (best width)")
                    code_lines.append(f"def parse_{var.lower()}(value):")
                    code_lines.append(f"    try:")
                    code_lines.append(f"        return float(value)")
                    code_lines.append(f"    except (ValueError, TypeError):")
                    code_lines.append(f"        return pd.NA")
                else:
                    code_lines.append(f"# Parse {var} with custom informat {informat_type}")
                    code_lines.append(f"def parse_{var.lower()}(value):")
                    code_lines.append(f"    return value")
        
        # Handle generic format statements
        if not code_lines or len(code_lines) <= 2:
            format_match = re.search(r'format\s+(.*?);', content, re.IGNORECASE)
            if format_match:
                formats = format_match.group(1).strip()
                code_lines.append("# Apply formatting to variables")
                code_lines.append("def apply_formats(df):")
                code_lines.append("    \"\"\"Apply SAS-like formats to DataFrame columns\"\"\"")
                code_lines.append("    formatted_df = df.copy()")
                
                for format_spec in formats.split():
                    if ':' in format_spec:
                        var, fmt = format_spec.split(':', 1)
                        code_lines.append(f"    # Format {var} as {fmt}")
                        if fmt.startswith('$'):
                            code_lines.append(f"    formatted_df['{var}'] = formatted_df['{var}'].astype(str)")
                        elif fmt.lower().startswith(('date', 'time')):
                            code_lines.append(f"    formatted_df['{var}'] = pd.to_datetime(formatted_df['{var}'])")
                        elif any(c.isdigit() for c in fmt):
                            code_lines.append(f"    formatted_df['{var}'] = formatted_df['{var}'].apply(lambda x: f'{{x:.{fmt}f}}' if pd.notna(x) else '')")
                
                code_lines.append("    return formatted_df")
        
        return "\n".join(code_lines)

    def _convert_title_footnote(self, component: SASComponent) -> str:
        """Convert SAS TITLE/FOOTNOTE statements to matplotlib title/figtext."""
        content = component.content.strip()
        
        if component.type == "TITLE":
            # Extract title number and text
            title_match = re.search(r'TITLE(\d*)\s+(.*?);', content, re.IGNORECASE)
            if title_match:
                title_num = title_match.group(1) or "1"  # Default to 1 if not specified
                title_text = title_match.group(2).strip()
                
                # For use with matplotlib
                code_lines = []
                code_lines.append("# Set plot title")
                code_lines.append(f"plt.suptitle({title_text}, fontsize={14+2*(1-int(title_num))})")
                
                # For general title use
                code_lines.append(f"title_{title_num} = {title_text}")
                
                return "\n".join(code_lines)
        
        elif component.type == "FOOTNOTE":
            # Extract footnote number and text
            footnote_match = re.search(r'FOOTNOTE(\d*)\s+(.*?);', content, re.IGNORECASE)
            if footnote_match:
                footnote_num = footnote_match.group(1) or "1"  # Default to 1 if not specified
                footnote_text = footnote_match.group(2).strip()
                
                code_lines = []
                code_lines.append("# Add footnote to plot")
                code_lines.append(f"plt.figtext(0.5, 0.01, {footnote_text}, ha='center', fontsize=10)")
                
                return "\n".join(code_lines)
        
        # Default fallback
        return f"# TODO: Convert {component.type}\n# {content}"

    def _convert_ods(self, component: SASComponent) -> str:
        """Convert ODS statements to Python plotting configuration."""
        content = component.content.strip()
        
        code_lines = []
        
        # Handle ODS GRAPHICS ON/OFF
        if re.search(r'ODS\s+GRAPHICS\s+ON', content, re.IGNORECASE):
            code_lines.append("# Enable Matplotlib and seaborn for graphics")
            code_lines.append("import matplotlib.pyplot as plt")
            code_lines.append("import seaborn as sns")
            code_lines.append("plt.rcParams['figure.figsize'] = (10, 6)")
            code_lines.append("plt.rcParams['figure.dpi'] = 100")
            
        elif re.search(r'ODS\s+GRAPHICS\s+OFF', content, re.IGNORECASE):
            code_lines.append("# Close all open plots")
            code_lines.append("plt.close('all')")
        
        # Handle ODS HTML
        html_match = re.search(r'ODS\s+HTML\s+PATH\s*=\s*[\'"]?(.*?)[\'"]?(?:\s+|$)', content, re.IGNORECASE)
        if html_match:
            path = html_match.group(1)
            code_lines.append("# Setup output directory for HTML reports")
            code_lines.append(f"import os")
            code_lines.append(f"output_dir = {repr(path)}")
            code_lines.append(f"os.makedirs(output_dir, exist_ok=True)")
            
            # Handle body parameter
            body_match = re.search(r'BODY\s*=\s*[\'"]?(.*?)[\'"]?(?:\s+|$)', content, re.IGNORECASE)
            if body_match:
                body = body_match.group(1)
                code_lines.append(f"html_file = os.path.join(output_dir, {repr(body)})")
        
        # Handle ODS HTML CLOSE
        if re.search(r'ODS\s+HTML\s+CLOSE', content, re.IGNORECASE):
            code_lines.append("# Complete HTML output")
            code_lines.append("# If using a library like pandas HTML output:")
            code_lines.append("# with open(html_file, 'w') as f:")
            code_lines.append("#     f.write(html_content)")
        
        if not code_lines:
            code_lines.append(f"# TODO: Convert complex ODS statement\n# {content}")
        
        return "\n".join(code_lines)

    def _convert_proc_report(self, component: SASComponent) -> str:
        """Convert PROC REPORT to pandas DataFrame formatting and display."""
        # Extract parameters
        data_match = re.search(r'data\s*=\s*(\w+)', component.content, re.IGNORECASE)
        column_match = re.search(r'column\s+(.*?);', component.content, re.IGNORECASE)
        
        code_lines = []
        
        # Handle data parameter
        if data_match:
            data_name = self._convert_dataset_name(data_match.group(1))
        else:
            data_name = "df"  # Default name
        
        code_lines.append("# Generate report from data")
        code_lines.append(f"report_df = {data_name}.copy()")
        
        # Handle column definitions
        if column_match:
            columns = [c.strip() for c in column_match.group(1).split()]
            code_lines.append(f"# Select and order columns for report")
            code_lines.append(f"report_df = report_df[{columns}]")
            
            # Extract define statements for column formatting
            define_matches = re.findall(r'define\s+(\w+)\s*/\s*([^;]*);', component.content, re.IGNORECASE)
            format_dict = {}
            
            for col, options in define_matches:
                # Extract display label
                label_match = re.search(r'\'([^\']+)\'', options)
                if label_match:
                    label = label_match.group(1)
                    format_dict[col] = f"'{label}'"
            
            if format_dict:
                format_str = ", ".join([f"'{k}': {v}" for k, v in format_dict.items()])
                code_lines.append(f"# Rename columns with display labels")
                code_lines.append(f"report_df = report_df.rename(columns={{{format_str}}})")
        
        # Add display code
        code_lines.append("# Display formatted report")
        code_lines.append("from IPython.display import display, HTML")
        code_lines.append("html_report = report_df.to_html(index=False)")
        code_lines.append("display(HTML(html_report))")
        code_lines.append("")
        code_lines.append("# Save report to file if needed")
        code_lines.append("# report_df.to_html('report.html', index=False)")
        code_lines.append("# report_df.to_csv('report.csv', index=False)")
        
        return "\n".join(code_lines)
    
    def _convert_proc_format(self, component: SASComponent) -> str:
        """Convert PROC FORMAT to Python dictionaries or mapping functions."""
        code_lines = []
        content = component.content
        
        # Extract format specifications
        format_specs = re.findall(r'value\s+(\w+)(.*?);', content, re.DOTALL | re.IGNORECASE)
        
        for format_name, format_values in format_specs:
            code_lines.append(f"# Create mapping for {format_name} format")
            code_lines.append(f"{format_name}_mapping = {{")
            
            # Parse the format values
            if '$' in format_name:  # String format
                # Extract individual mappings like 'NA' = 'North America'
                mappings = re.findall(r"'([^']+)'\s*=\s*'([^']+)'", format_values)
                for src, dst in mappings:
                    code_lines.append(f"    '{src}': '{dst}',")
                
                # Check for 'other' specification
                other_match = re.search(r'other\s*=\s*\'([^\']+)\'', format_values, re.IGNORECASE)
                if other_match:
                    code_lines.append(f"    'other': '{other_match.group(1)}',")
            else:  # Numeric format
                # Extract range mappings like low-25 = 'Young'
                range_mappings = re.findall(r'([\w.-]+)-([\w.-]+)\s*=\s*\'([^\']+)\'', format_values)
                for low, high, label in range_mappings:
                    if low.lower() == 'low':
                        code_lines.append(f"    'range1': {{")
                        code_lines.append(f"        'high': {high},")
                        code_lines.append(f"        'label': '{label}'")
                        code_lines.append(f"    }},")
                    elif high.lower() == 'high':
                        code_lines.append(f"    'range3': {{")
                        code_lines.append(f"        'low': {low},")
                        code_lines.append(f"        'label': '{label}'")
                        code_lines.append(f"    }},")
                    else:
                        code_lines.append(f"    'range2': {{")
                        code_lines.append(f"        'low': {low},")
                        code_lines.append(f"        'high': {high},")
                        code_lines.append(f"        'label': '{label}'")
                        code_lines.append(f"    }},")
            
            code_lines.append("}")
            
            # Create a function to apply the format
            code_lines.append(f"def apply_{format_name}_format(value):")
            if '$' in format_name:  # String format
                code_lines.append(f"    if value in {format_name}_mapping:")
                code_lines.append(f"        return {format_name}_mapping[value]")
                code_lines.append(f"    elif 'other' in {format_name}_mapping:")
                code_lines.append(f"        return {format_name}_mapping['other']")
                code_lines.append(f"    return value")
            else:  # Numeric format
                code_lines.append(f"    try:")
                code_lines.append(f"        val = float(value)")
                code_lines.append(f"        # Check low-high range")
                code_lines.append(f"        if 'range1' in {format_name}_mapping and val <= {format_name}_mapping['range1']['high']:")
                code_lines.append(f"            return {format_name}_mapping['range1']['label']")
                code_lines.append(f"        # Check middle ranges")
                code_lines.append(f"        if 'range2' in {format_name}_mapping and {format_name}_mapping['range2']['low'] <= val <= {format_name}_mapping['range2']['high']:")
                code_lines.append(f"            return {format_name}_mapping['range2']['label']")
                code_lines.append(f"        # Check high range")
                code_lines.append(f"        if 'range3' in {format_name}_mapping and val >= {format_name}_mapping['range3']['low']:")
                code_lines.append(f"            return {format_name}_mapping['range3']['label']")
                code_lines.append(f"        return value")
                code_lines.append(f"    except (ValueError, TypeError):")
                code_lines.append(f"        return value")
        
        return "\n".join(code_lines)

    def _convert_data_step(self, component: SASComponent, similar_content: List[str]) -> str:
        """Convert SAS DATA step to Python pandas operations."""
        # Get dataset name
        dataset_name = component.name
        
        # Check for special cases
        if dataset_name == "_NULL_":
            return self._convert_null_data_step(component)
        
        # Extract key components
        set_match = re.search(r'\bSET\s+(.*?);', component.content, re.IGNORECASE)
        merge_match = re.search(r'\bMERGE\s+(.*?);', component.content, re.IGNORECASE)
        by_match = re.search(r'\bBY\s+(.*?);', component.content, re.IGNORECASE)
        
        # Start building code
        code_lines = []
        
        # Convert dataset names
        output_df = self._convert_dataset_name(dataset_name)
        
        # Handle SET statement
        if set_match:
            input_datasets = [ds.strip() for ds in set_match.group(1).split()]
            if len(input_datasets) == 1:
                input_df = self._convert_dataset_name(input_datasets[0])
                code_lines.append(f"# Create a copy of the input dataset")
                code_lines.append(f"{output_df} = {input_df}.copy()")
            else:
                # Multiple datasets - concatenate
                input_dfs = [self._convert_dataset_name(ds) for ds in input_datasets]
                code_lines.append(f"# Concatenate multiple datasets")
                code_lines.append(f"{output_df} = pd.concat([{', '.join(input_dfs)}], ignore_index=True)")
            
            # Extract variable assignments
            assignments = re.findall(r'(\w+)\s*=\s*(.*?);', component.content)
            for var, expr in assignments:
                # Convert SAS expression to Python
                py_expr = self._convert_sas_expression(expr)
                code_lines.append(f"{output_df}['{var}'] = {py_expr}")
            
            # Handle IF statements
            if_statements = re.findall(r'if\s+(.*?)\s+then\s+(.*?);', component.content, re.IGNORECASE | re.DOTALL)
            for condition, action in if_statements:
                py_condition = self._convert_sas_condition(condition)
                # Check if action is a variable assignment
                assignment_match = re.search(r'(\w+)\s*=\s*(.*)', action)
                if assignment_match:
                    var, expr = assignment_match.groups()
                    py_expr = self._convert_sas_expression(expr)
                    code_lines.append(f"# Apply conditional transformation")
                    code_lines.append(f"{output_df}.loc[{py_condition}, '{var}'] = {py_expr}")
                else:
                    # Other actions
                    code_lines.append(f"# TODO: Convert complex IF-THEN action: {action}")
            
            # Handle WHERE clauses
            where_match = re.search(r'where\s+(.*?);', component.content, re.IGNORECASE)
            if where_match:
                where_condition = where_match.group(1)
                py_condition = self._convert_sas_condition(where_condition)
                code_lines.append(f"# Filter data based on WHERE clause")
                code_lines.append(f"{output_df} = {output_df}[{py_condition}]")
            
            # Handle DROP and KEEP statements
            drop_match = re.search(r'drop\s+(.*?);', component.content, re.IGNORECASE)
            keep_match = re.search(r'keep\s+(.*?);', component.content, re.IGNORECASE)
            
            if drop_match:
                drop_vars = [v.strip() for v in drop_match.group(1).split()]
                drop_vars_str = "[" + ", ".join([f"'{v}'" for v in drop_vars]) + "]"
                code_lines.append(f"# Drop variables")
                code_lines.append(f"{output_df} = {output_df}.drop(columns={drop_vars_str})")
            
            if keep_match:
                keep_vars = [v.strip() for v in keep_match.group(1).split()]
                keep_vars_str = "[" + ", ".join([f"'{v}'" for v in keep_vars]) + "]"
                code_lines.append(f"# Keep only specified variables")
                code_lines.append(f"{output_df} = {output_df}[{keep_vars_str}]")
                
        # Handle MERGE statement
        elif merge_match:
            input_datasets = [ds.strip() for ds in merge_match.group(1).split()]
            input_dfs = [self._convert_dataset_name(ds) for ds in input_datasets]
            
            if len(input_dfs) >= 2 and by_match:
                by_vars = [v.strip() for v in by_match.group(1).split()]
                by_vars_str = "[" + ", ".join([f"'{v}'" for v in by_vars]) + "]"
                
                # Merge first two datasets
                code_lines.append(f"# Merge datasets on {', '.join(by_vars)}")
                code_lines.append(f"{output_df} = pd.merge({input_dfs[0]}, {input_dfs[1]}, on={by_vars_str}, how='outer')")
                
                # Handle more than two datasets
                for i in range(2, len(input_dfs)):
                    code_lines.append(f"{output_df} = pd.merge({output_df}, {input_dfs[i]}, on={by_vars_str}, how='outer')")
            else:
                code_lines.append(f"# TODO: Convert MERGE without BY statement")
                code_lines.append(f"# Original code: {merge_match.group(0)}")
        else:
            # Creating a new dataset
            code_lines.append(f"# Create a new DataFrame")
            code_lines.append(f"{output_df} = pd.DataFrame()")
            
            # Extract variable assignments
            assignments = re.findall(r'(\w+)\s*=\s*(.*?);', component.content)
            for var, expr in assignments:
                # Convert SAS expression to Python
                py_expr = self._convert_sas_expression(expr)
                code_lines.append(f"{output_df}['{var}'] = {py_expr}")
        
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

    def _convert_sql(self, component: SASComponent, similar_content: List[str]) -> str:
        """Convert PROC SQL to pandas or SQLAlchemy."""
        code_lines = []
        
        # Add imports
        code_lines.append("# SQL operations using pandas")
        
        # Extract SQL statements
        create_table_matches = re.findall(r'CREATE\s+TABLE\s+(\w+)\s+AS\s+(.*?);', 
                                         component.content, 
                                         re.IGNORECASE | re.DOTALL)
        
        select_into_matches = re.findall(r'SELECT\s+(.*?)\s+INTO\s+:(.*?)\s+FROM', 
                                        component.content, 
                                        re.IGNORECASE | re.DOTALL)
        
        # Handle CREATE TABLE AS statements
        for table_name, query in create_table_matches:
            output_df = self._convert_dataset_name(table_name)
            
            # Extract the SELECT statement components
            select_match = re.search(r'SELECT\s+(.*?)\s+FROM\s+(.*?)(?:\s+WHERE\s+(.*?))?(?:\s+GROUP\s+BY\s+(.*?))?(?:\s+ORDER\s+BY\s+(.*?))?(?:\s*$|;)', 
                                   query, 
                                   re.IGNORECASE | re.DOTALL)
            
            if select_match:
                columns = select_match.group(1).strip()
                from_tables = select_match.group(2).strip()
                where_clause = select_match.group(3) if select_match.group(3) else None
                group_by = select_match.group(4) if select_match.group(4) else None
                order_by = select_match.group(5) if select_match.group(5) else None
                
                # Handle FROM clause
                input_tables = [t.strip() for t in from_tables.split(',')]
                if len(input_tables) == 1:
                    # Simple SELECT from one table
                    input_df = self._convert_dataset_name(input_tables[0])
                    code_lines.append(f"# Start with source table")
                    code_lines.append(f"{output_df} = {input_df}.copy()")
                    
                    # Handle WHERE clause
                    if where_clause:
                        py_condition = self._convert_sql_condition(where_clause)
                        code_lines.append(f"# Apply WHERE filter")
                        code_lines.append(f"{output_df} = {output_df}[{py_condition}]")
                    
                    # Handle SELECT columns (projections)
                    if columns != '*':
                        column_list = [c.strip() for c in columns.split(',')]
                        # Check for column renaming (AS)
                        renamed_columns = {}
                        selected_columns = []
                        
                        for col in column_list:
                            as_match = re.search(r'(.*?)\s+AS\s+(\w+)', col, re.IGNORECASE)
                            if as_match:
                                expr, new_name = as_match.groups()
                                # Handle expressions or simply column selection
                                if re.search(r'[+\-*/()]', expr):
                                    # Mathematical expression
                                    py_expr = self._convert_sql_expression(expr)
                                    code_lines.append(f"{output_df}['{new_name}'] = {py_expr}")
                                else:
                                    # Simple column rename
                                    selected_columns.append(expr.strip())
                                    renamed_columns[expr.strip()] = new_name
                            else:
                                selected_columns.append(col)
                        
                        if selected_columns:
                            col_list_str = "[" + ", ".join([f"'{c}'" for c in selected_columns]) + "]"
                            code_lines.append(f"# Select specific columns")
                            code_lines.append(f"{output_df} = {output_df}[{col_list_str}]")
                        
                        if renamed_columns:
                            rename_dict_str = "{" + ", ".join([f"'{old}': '{new}'" for old, new in renamed_columns.items()]) + "}"
                            code_lines.append(f"# Rename columns")
                            code_lines.append(f"{output_df} = {output_df}.rename(columns={rename_dict_str})")
                    
                    # Handle GROUP BY
                    if group_by:
                        group_cols = [c.strip() for c in group_by.split(',')]
                        group_cols_str = "[" + ", ".join([f"'{c}'" for c in group_cols]) + "]"
                        code_lines.append(f"# Group by columns")
                        code_lines.append(f"{output_df} = {output_df}.groupby({group_cols_str}).agg({{")
                        
                        # Infer aggregation for non-groupby columns
                        non_group_cols = [c for c in selected_columns if c not in group_cols]
                        for col in non_group_cols:
                            code_lines.append(f"    '{col}': 'first',  # Update with appropriate aggregation")
                        
                        code_lines.append(f"}}).reset_index()")
                    
                    # Handle ORDER BY
                    if order_by:
                        order_cols = []
                        ascending = []
                        
                        for col in [c.strip() for c in order_by.split(',')]:
                            if col.upper().endswith(' DESC'):
                                order_cols.append(col[:-5].strip())
                                ascending.append(False)
                            else:
                                order_cols.append(col.replace(' ASC', '').strip())
                                ascending.append(True)
                        
                        order_cols_str = "[" + ", ".join([f"'{c}'" for c in order_cols]) + "]"
                        ascending_str = str(ascending)
                        
                        code_lines.append(f"# Sort results")
                        code_lines.append(f"{output_df} = {output_df}.sort_values(by={order_cols_str}, ascending={ascending_str})")
                
                else:
                    # Multiple tables - handle JOIN
                    code_lines.append(f"# TODO: Handle multiple table join")
                    code_lines.append(f"# Original query: {query}")
        
        # Handle SELECT INTO statements (macro variables)
        for columns, var_names in select_into_matches:
            var_list = [v.strip() for v in var_names.split(',')]
            col_list = [c.strip() for c in columns.split(',')]
            
            if len(var_list) == len(col_list):
                for i, (var, col) in enumerate(zip(var_list, col_list)):
                    code_lines.append(f"# Get value into variable")
                    code_lines.append(f"{var} = query_result.iloc[0]['{col}']")
            else:
                code_lines.append(f"# TODO: Handle mismatched SELECT INTO variable count")
        
        # Handle other SQL operations
        if not create_table_matches and not select_into_matches:
            code_lines.append(f"# TODO: Convert complex SQL operations")
            code_lines.append(f"# Original SQL: {component.content}")
        
        return "\n".join(code_lines)

    def _convert_macro(self, component: SASComponent, similar_content: List[str]) -> str:
        """Convert SAS macro to Python function."""
        # Extract macro name and parameters
        macro_name = component.name
        params_match = re.search(r'%MACRO\s+\w+\s*\((.*?)\)', component.content, re.IGNORECASE)
        
        # Start building code
        code_lines = []
        
        if params_match:
            # Parse parameters
            params_str = params_match.group(1).strip()
            param_list = []
            
            if params_str:
                # Handle parameters with default values
                for param in params_str.split(','):
                    param = param.strip()
                    if '=' in param:
                        name, default = param.split('=', 1)
                        if default.strip():
                            param_list.append(f"{name.strip()}={default.strip()}")
                        else:
                            param_list.append(f"{name.strip()}=None")
                    else:
                        param_list.append(param)
            
            # Create function definition
            code_lines.append(f"def {macro_name}({', '.join(param_list)}):")
        else:
            # No parameters
            code_lines.append(f"def {macro_name}():")
        
        # Extract macro body - this is a simplified approach
        body_lines = []
        content_lines = component.content.split('\n')
        in_body = False
        
        for line in content_lines:
            if '%MEND' in line.upper():
                break
            if in_body:
                # Convert SAS macro statements to Python
                if line.strip().startswith('%'):
                    # Handle macro flow control
                    if line.strip().upper().startswith('%IF'):
                        if_match = re.search(r'%IF\s+(.*?)\s+%THEN\s+(.*?)(?:%ELSE|;|$)', line, re.IGNORECASE)
                        if if_match:
                            condition = self._convert_macro_condition(if_match.group(1))
                            # Fix = to == for comparison
                            condition = re.sub(r'(\w+)\s*=\s*(\w+|\d+)', r'\1 == \2', condition)
                            action = if_match.group(2).strip()
                            body_lines.append(f"    if {condition}:")
                            body_lines.append(f"        {self._convert_macro_action(action)}")
                            
                            # Check for %ELSE
                            else_match = re.search(r'%ELSE\s+(.*?);', line, re.IGNORECASE)
                            if else_match:
                                action = else_match.group(1).strip()
                                body_lines.append(f"    else:")
                                body_lines.append(f"        {self._convert_macro_action(action)}")
                    
                    elif line.strip().upper().startswith('%DO'):
                        do_match = re.search(r'%DO\s+(\w+)\s*=\s*(\d+)\s+TO\s+(\d+)', line, re.IGNORECASE)
                        if do_match:
                            var, start, end = do_match.groups()
                            body_lines.append(f"    for {var} in range({start}, {int(end)+1}):")
                        else:
                            do_while_match = re.search(r'%DO\s+%WHILE\s*\(\s*(.*?)\s*\)', line, re.IGNORECASE)
                            if do_while_match:
                                condition = do_while_match.group(1).strip()
                                # Convert &variable references
                                condition = re.sub(r'&(\w+)', r'\1', condition)
                                # Convert ne to !=
                                condition = re.sub(r'\bne\b', '!=', condition, flags=re.IGNORECASE)
                                body_lines.append(f"    while {condition}:")
                            else:
                                body_lines.append(f"    # TODO: Convert complex %DO loop")
                                body_lines.append(f"    # {line.strip()}")
                    
                    elif line.strip().upper() == '%END;':
                        body_lines.append(f"        pass  # End of loop or conditional block")
                    
                    else:
                        body_lines.append(f"    # TODO: Convert macro statement")
                        body_lines.append(f"    # {line.strip()}")
                else:
                    # Add regular SAS code as Python-converted code
                    sas_line = line.strip()
                    if sas_line.startswith('PROC '):
                        body_lines.append(f"    # Call appropriate Python function for {sas_line}")
                        proc_match = re.search(r'PROC\s+(\w+)', sas_line, re.IGNORECASE)
                        if proc_match:
                            proc_name = proc_match.group(1).lower()
                            body_lines.append(f"    {proc_name}_analysis({', '.join(param_list)})")
                    elif sas_line.startswith('DATA '):
                        body_lines.append(f"    # Create DataFrame")
                        data_match = re.search(r'DATA\s+(\w+)', sas_line, re.IGNORECASE)
                        if data_match:
                            data_name = data_match.group(1).lower()
                            body_lines.append(f"    {data_name}_df = pd.DataFrame()")
                    else:
                        body_lines.append(f"    # {sas_line}")
            
            if re.search(r'%MACRO\s+\w+', line, re.IGNORECASE):
                in_body = True
        
        # Add body lines or placeholder
        if body_lines:
            code_lines.extend(body_lines)
        else:
            code_lines.append("    # TODO: Implement macro body")
            code_lines.append("    pass")
        
        return "\n".join(code_lines)

    def _convert_macro_variable(self, component: SASComponent) -> str:
        """Convert SAS %LET statement to Python variable assignment."""
        # Extract variable name and value
        let_match = re.search(r'%LET\s+(\w+)\s*=\s*(.*?);', component.content, re.IGNORECASE)
        
        if let_match:
            var_name = let_match.group(1)
            value = let_match.group(2).strip()
            
            # Handle different value types
            if value.startswith("'") and value.endswith("'"):
                # String value
                return f"{var_name} = {value}"
            elif re.match(r'^\d+$', value):
                # Integer value
                return f"{var_name} = {value}"
            elif re.match(r'^\d+\.\d+$', value):
                # Float value
                return f"{var_name} = {value}"
            elif value.startswith("%SYSFUNC"):
                # Handle SAS functions
                if "TODAY()" in value.upper():
                    return f"{var_name} = pd.Timestamp.today().normalize()"
                else:
                    return f"{var_name} = None  # TODO: Convert SAS function: {value}"
            elif value.startswith("%SCAN"):
                # Handle SCAN function
                scan_match = re.search(r'%SCAN\((.+?),\s*(.+?)\)', value)
                if scan_match:
                    list_var = scan_match.group(1).replace('&', '')
                    index_var = scan_match.group(2).replace('&', '')
                    return f"{var_name} = {list_var}.split()[{index_var}-1] if {index_var}-1 < len({list_var}.split()) else \"\""
            elif value.startswith("%EVAL"):
                # Handle EVAL function
                eval_match = re.search(r'%EVAL\((.*?)\)', value)
                if eval_match:
                    expr = self._convert_sas_expression(eval_match.group(1))
                    return f"{var_name} = {expr}"
            else:
                # Other values - might be expressions or variables
                py_expr = self._convert_sas_expression(value)
                return f"{var_name} = {py_expr}"
        else:
            return f"# TODO: Convert macro variable assignment\n# {component.content}"

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

    def _convert_dataset_name(self, sas_name: str) -> str:
        """Convert SAS dataset name to Python variable name."""
        if sas_name.startswith('&'):
            # Macro variable reference
            return f"{sas_name[1:]}_df"
        
        # Handle library.dataset notation
        if '.' in sas_name:
            lib, ds = sas_name.split('.', 1)
            return f"{ds.lower()}_df"
        else:
            return f"{sas_name.lower()}_df"

    def _convert_sas_expression(self, expr: str) -> str:
        """Convert SAS expression to Python."""
        # Replace SAS-specific functions and operators
        expr = expr.strip()
        
        # Handle SAS functions
        expr = re.sub(r'(\w+)\*\*(\w+)', r'\1**\2', expr)  # Exponentiation
        expr = re.sub(r'EXP\(', r'np.exp(', expr, flags=re.IGNORECASE)
        expr = re.sub(r'LOG\(', r'np.log(', expr, flags=re.IGNORECASE)
        expr = re.sub(r'SQRT\(', r'np.sqrt(', expr, flags=re.IGNORECASE)
        expr = re.sub(r'SUM\((.*?)\)', r'sum([\1])', expr, flags=re.IGNORECASE)
        expr = re.sub(r'MEAN\((.*?)\)', r'np.mean([\1])', expr, flags=re.IGNORECASE)
        expr = re.sub(r'INT\(', r'int(', expr, flags=re.IGNORECASE)
        
        # Handle SAS date functions
        expr = re.sub(r'TODAY\(\)', r'pd.Timestamp.today().normalize()', expr, flags=re.IGNORECASE)
        expr = re.sub(r'DATE\(\)', r'pd.Timestamp.today().normalize()', expr, flags=re.IGNORECASE)
        
        # Handle &macro.variable references
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
        """
        Convert a single SAS file to Python.
        
        Args:
            sas_file: Path to SAS file
            
        Returns:
            Path to converted Python file
        """
        try:
            # Parse the SAS file
            parser = SASParser()
            components = parser.parse_file(sas_file)
            
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
        except Exception as e:
            logger.error(f"Error converting {sas_file}: {str(e)}")
            return None
        
    def _convert_libname(self, component: SASComponent) -> str:
        """Convert SAS LIBNAME statements to Python data paths."""
        # Extract name and path
        libname_match = re.search(r'LIBNAME\s+(\w+)\s+([^;]+);', component.content, re.IGNORECASE)
        
        if not libname_match:
            return f"# TODO: Complex LIBNAME conversion\n# {component.content}"
        
        lib_name = libname_match.group(1)
        lib_path = libname_match.group(2).strip()
        
        code_lines = []
        code_lines.append(f"# Define {lib_name} library path")
        
        # Handle different types of paths
        if lib_path.startswith('"') or lib_path.startswith("'"):
            # Regular path
            code_lines.append(f"{lib_name.lower()}_path = {lib_path}")
            code_lines.append(f"# For use with pandas:")
            code_lines.append(f"# df = pd.read_csv(f'{{{lib_name.lower()}_path}}/dataset.csv')")
        elif "oracle" in lib_path.lower():
            # Oracle connection
            oracle_match = re.search(r'oracle\s+path\s*=\s*[\'"]([^\'"]+)[\'"]', lib_path, re.IGNORECASE)
            schema_match = re.search(r'schema\s*=\s*(\w+)', lib_path, re.IGNORECASE)
            conn_string = oracle_match.group(1) if oracle_match else "oracle_connection"
            schema = schema_match.group(1) if schema_match else "schema"
            
            code_lines.append(f"# Import database libraries")
            code_lines.append(f"import sqlalchemy as sa")
            code_lines.append(f"")
            code_lines.append(f"# Create Oracle connection string")
            code_lines.append(f"{lib_name.lower()}_conn = sa.create_engine('oracle://{conn_string}')")
            code_lines.append(f"{lib_name.lower()}_schema = '{schema}'")
            code_lines.append(f"# For use with pandas:")
            code_lines.append(f"# df = pd.read_sql('SELECT * FROM table', {lib_name.lower()}_conn)")
        else:
            # Generic path
            code_lines.append(f"{lib_name.lower()}_path = '{lib_path}'")
        
        # Extract options
        if 'access=' in lib_path.lower():
            code_lines.append(f"# Note: Read-only access specified")
        if 'compress=' in lib_path.lower():
            code_lines.append(f"# Note: Data compression specified")
        
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
        code_lines.append("# Configure Python environment options")
        
        # Extract individual options
        options_match = re.search(r'OPTIONS\s+(.*?);', content, re.IGNORECASE)
        if options_match:
            options_str = options_match.group(1)
            options = [opt.strip() for opt in options_str.split()]
            
            for option in options:
                if '=' in option:
                    opt_name, opt_value = option.split('=', 1)
                    
                    # Handle specific options
                    if opt_name.upper() in ['LINESIZE', 'LS']:
                        code_lines.append(f"# Set display width")
                        code_lines.append(f"pd.set_option('display.width', {opt_value})")
                    elif opt_name.upper() in ['PAGESIZE', 'PS']:
                        code_lines.append(f"# Set display max rows")
                        code_lines.append(f"pd.set_option('display.max_rows', {opt_value})")
                    elif opt_name.upper() == 'MISSING':
                        code_lines.append(f"# Set missing value representation")
                        code_lines.append(f"pd.set_option('display.missing_repr', {opt_value})")
                    elif opt_name.upper() == 'NOCENTER':
                        code_lines.append(f"# Disable center alignment")
                    elif opt_name.upper() == 'NODATE':
                        code_lines.append(f"# Disable date display")
                    else:
                        code_lines.append(f"# Option: {opt_name}={opt_value}")
                else:
                    # Handle flag options
                    if option.upper() == 'COMPRESS=YES':
                        code_lines.append(f"# Enable data compression")
                    elif option.upper() == 'NOTES':
                        code_lines.append(f"# Enable notes/logging")
                        code_lines.append(f"import logging")
                        code_lines.append(f"logging.basicConfig(level=logging.INFO)")
                    elif option.upper() == 'NONOTES':
                        code_lines.append(f"# Disable notes/logging")
                        code_lines.append(f"import logging")
                        code_lines.append(f"logging.basicConfig(level=logging.WARNING)")
                    else:
                        code_lines.append(f"# Option: {option}")
        
        if len(code_lines) == 1:
            code_lines.append(f"# {content}")
        
        return "\n".join(code_lines)

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