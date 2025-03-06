from sas_parser import SASParser
from embedding_generator import EmbeddingGenerator
from vector_store import VectorStore
from sas_python_converter import SASPythonConverter  # Import the converter
import numpy as np
import shutil
import os
import argparse
import tempfile
from pathlib import Path
import unittest
from T_sas_python_converter_template import SASPythonConverterTemplate
import glob
import logging
import sys
import yaml
import pandas as pd

def test_parser():
    """Test the SAS parser functionality."""
    parser = SASParser()
    components = parser.parse_file("mock_data/sample.sas")
    
    print("\n=== Parser Test Results ===")
    print(f"Total components found: {len(components)}")
    for comp in components:
        print(f"\nComponent Type: {comp.type}")
        print(f"Name: {comp.name}")
        print(f"Lines: {comp.line_start}-{comp.line_end}")
        print(f"Content preview: {comp.content[:100]}...")

def test_embeddings():
    # Test Embedding Generation
    parser = SASParser()
    embedding_gen = EmbeddingGenerator(embedding_dim=4096)
    
    components = parser.parse_file("mock_data/sample.sas")
    embeddings = embedding_gen.generate_embeddings(components)
    
    print("\n=== Embedding Test Results ===")
    print(f"Total embeddings generated: {len(embeddings)}")
    for i, emb in enumerate(embeddings[:2]):  # Show first 2 embeddings
        print(f"\nEmbedding {i+1}:")
        print(f"Shape: {emb.embedding.shape}")
        print(f"Type: {emb.component.type}")
        print(f"Metadata: {emb.metadata}")
        print(f"Non-zero elements: {np.count_nonzero(emb.embedding)}")

def test_vector_store():
    # Test Vector Store
    parser = SASParser()
    embedding_gen = EmbeddingGenerator()
    vector_store = VectorStore(persist_directory="chroma_db")
    
    components = parser.parse_file("mock_data/sample.sas")
    embeddings = embedding_gen.generate_embeddings(components)
    vector_store.store_embeddings(embeddings)
    
    # Test retrieval
    print("\n=== Vector Store Test Results ===")
    for collection_name, collection in vector_store.collections.items():
        count = collection.count()
        print(f"\nCollection '{collection_name}' has {count} entries")
        
        if count > 0:
            # Get a sample entry
            result = collection.get(limit=1)
            print(f"Sample metadata: {result['metadatas'][0]}")

def cleanup_chromadb():
    """Clean up ChromaDB with error handling."""
    try:
        print("\nCleaning up ChromaDB...")
        # Remove the ChromaDB directory if it exists
        if os.path.exists("chroma_db"):
            shutil.rmtree("chroma_db")
        print("ChromaDB cleaned up")
    except Exception as e:
        print(f"Warning: ChromaDB cleanup error: {str(e)}")
        # Continue execution even if cleanup fails

def test_single_component():
    """Test parsing of a single component to debug issues."""
    print("\n=== Testing Single Component Parsing ===")
    test_content = """
/* Test PROC SQL */
proc sql;
    create table test as
    select * from data;
quit;

/* Test DATA step */
data test;
    set input;
    x = 1;
run;

/* Test Macro */
%macro test(param);
    proc print data=&param;
    run;
%mend test;
"""
    with tempfile.NamedTemporaryFile(mode='w', suffix='.sas', delete=False) as f:
        f.write(test_content)
        test_file = f.name
    
    parser = SASParser()
    components = parser.parse_file(test_file)
    
    print(f"Found {len(components)} components")
    for comp in components:
        print(f"\nComponent Type: {comp.type}")
        print(f"Name: {comp.name}")
        print(f"Lines: {comp.line_start}-{comp.line_end}")
        print(f"Content:\n{comp.content}")
        print(f"Metadata: {comp.metadata}")

def test_directory_parsing():
    """Test parsing all SAS files in mock_data directory."""
    print("\n=== Testing Directory Parsing ===")
    parser = SASParser()
    
    total_components = 0
    component_types = {}
    file_components = {}
    
    # Process each file
    for components in parser.parse_directory("mock_data"):
        if components:  # If any components were found
            file_path = components[0].metadata["source_file"]
            file_components[file_path] = components
            total_components += len(components)
            for comp in components:
                component_types[comp.type] = component_types.get(comp.type, 0) + 1
    
    # Print summary
    print(f"\nTotal files processed: {len(list(Path('mock_data').glob('*.sas')))}")
    print(f"Total components found: {total_components}")
    
    # Print file-by-file breakdown
    print("\nComponents by file:")
    for file_name, components in file_components.items():
        print(f"\n{file_name}:")
        file_type_counts = {}
        for comp in components:
            file_type_counts[comp.type] = file_type_counts.get(comp.type, 0) + 1
        for comp_type, count in file_type_counts.items():
            print(f"  {comp_type}: {count}")
    
    # Print overall type summary
    print("\nTotal components by type:")
    for comp_type, count in sorted(component_types.items()):
        print(f"{comp_type}: {count}")

def test_end_to_end_conversion(input_dir, output_dir):
    """
    Test the full end-to-end process: parsing, embedding, storing, and converting
    """
    print(f"\n=== Testing End-to-End Conversion ===")
    print(f"Input directory: {input_dir}")
    print(f"Output directory: {output_dir}")
    
    # Initialize components with explicit embedding dimension
    parser = SASParser()
    embedding_gen = EmbeddingGenerator(embedding_dim=4096)
    vector_store = VectorStore(persist_directory="chroma_db")
    
    # Initialize converter early to use its collection mapping
    converter = SASPythonConverter(
        vector_store=vector_store,
        output_directory=output_dir,
        embedding_generator=embedding_gen
    )
    
    # Process all files in directory
    total_files = 0
    total_components = 0
    all_embeddings = []
    
    print("\nStep 1: Parsing and Generating Embeddings...")
    for sas_file in glob.glob(os.path.join(input_dir, "*.sas")):
        print(f"\nProcessing {sas_file}...")
        components = parser.parse_file(sas_file)
        if components:
            total_files += 1
            total_components += len(components)
            
            # Generate embeddings for these components
            print(f"Generating embeddings for {len(components)} components...")
            embeddings = embedding_gen.generate_embeddings(components)
            all_embeddings.extend(embeddings)
            print(f"Generated {len(embeddings)} embeddings")
            
            # Store embeddings using vector_store's method
            print("Storing embeddings in vector store...")
            vector_store.store_embeddings(embeddings)
    
    print(f"\nParsed {total_files} files with {total_components} components")
    print(f"Generated and stored {len(all_embeddings)} embeddings")
    
    print("\nStep 3: Converting SAS to Python using embeddings...")
    converted_files = []
    
    for sas_file in glob.glob(os.path.join(input_dir, "*.sas")):
        print(f"\nConverting {sas_file}...")
        try:
            # Use threading with timeout instead of signal
            import threading
            import queue
            
            result_queue = queue.Queue()
            
            def conversion_worker():
                try:
                    output_file = converter.convert_file(sas_file)
                    result_queue.put(("success", output_file))
                except Exception as e:
                    result_queue.put(("error", str(e)))
            
            # Start conversion in a separate thread
            conversion_thread = threading.Thread(target=conversion_worker)
            conversion_thread.daemon = True
            conversion_thread.start()
            
            # Wait for the thread to complete with timeout
            conversion_thread.join(timeout=30)
            
            if conversion_thread.is_alive():
                # Conversion is still running after timeout
                print(f"✗ Conversion of {sas_file} timed out after 30 seconds")
                
                # Create a simple Python file with a timeout message
                output_path = os.path.join(output_dir, os.path.basename(sas_file).replace('.sas', '.py'))
                with open(output_path, 'w') as f:
                    f.write(f"# Conversion timed out for {sas_file}\n")
                    f.write("# This is a placeholder file\n\n")
                    f.write("import pandas as pd\n")
                    f.write("import numpy as np\n")
                    f.write("print('This file was not fully converted due to a timeout')\n")
                converted_files.append(output_path)
                print(f"Created placeholder file {output_path}")
            else:
                # Thread completed within timeout
                if not result_queue.empty():
                    status, result = result_queue.get()
                    if status == "success":
                        if result:
                            converted_files.append(result)
                            print(f"✓ Successfully converted to {result}")
                        else:
                            print(f"✗ Failed to convert {sas_file}")
                    else:
                        print(f"✗ Error during conversion: {result}")
                else:
                    print(f"✗ Conversion thread completed but no result was returned")
                
        except Exception as e:
            print(f"✗ Error setting up conversion: {str(e)}")
    
    print(f"\nConverted {len(converted_files)} files to Python")
    
    return {
        "files_processed": total_files,
        "components_found": total_components,
        "embeddings_generated": len(all_embeddings),
        "python_files_created": len(converted_files)
    }

def test_template_converter():
    """Test the template-based converter with enhanced error handling."""
    print("\n=== Testing Template-Based Converter ===")
    
    try:
        # Test with minimal templates first
        minimal_templates = {
            'proc_means': {
                'template': """
                # Calculate descriptive statistics for ${dataset}
                stats_df = ${dataset}_df.describe()
                print('\nDescriptive Statistics:')
                print(stats_df)
                """
            },
            'proc_freq': {
                'template': """
                # Frequency analysis
                freq_table = pd.crosstab(
                    ${dataset}_df['${var}'],
                    margins=True
                )
                print('\nFrequency Table:')
                print(freq_table)
                """
            },
            'data_step': {
                'template': """
                # Create new dataset ${output_dataset}
                ${output_dataset}_df = pd.DataFrame()
                """
            },
            'proc_sql': {
                'template': """
                # SQL operation
                result = pd.read_sql("${query}", connection)
                """
            }
        }
        
        # Create a temporary YAML file with minimal templates
        with open('minimal_templates.yaml', 'w') as f:
            yaml.dump(minimal_templates, f)
        
        converter = SASPythonConverterTemplate(template_file='minimal_templates.yaml')
        
        # Test cases with proper component structure
        test_cases = [
            {
                'type': 'PROC',
                'name': 'means',
                'content': "PROC MEANS data=mydata;",
                'metadata': {'source_file': 'test.sas', 'line_number': 1}
            }
        ]
        
        print("\nProcessing test cases:")
        for case in test_cases:
            try:
                print(f"\nConverting {case['type']} {case.get('name', '')}")
                result = converter.convert_component(case)
                if result:
                    print("✓ Conversion successful")
                    print("Result preview:")
                    print(result)
                else:
                    print("✗ No output generated")
            except Exception as e:
                print(f"✗ Error converting component: {str(e)}")
                
    except Exception as e:
        print(f"✗ Failed to initialize converter: {str(e)}")
        return False
    finally:
        # Cleanup
        if os.path.exists('minimal_templates.yaml'):
            os.remove('minimal_templates.yaml')
    
    return True

def clean_output_directory(output_dir: str):
    """Clean up the output directory."""
    import shutil
    try:
        if os.path.exists(output_dir):
            # Remove the entire directory and its contents
            shutil.rmtree(output_dir)
        # Create the output directory
        os.makedirs(output_dir)
        print(f"\nCleaned output directory: {output_dir}")
    except Exception as e:
        print(f"Error cleaning output directory: {str(e)}")

def test_converter():
    """Test the SAS to Python converter."""
    print("\n=== Testing SAS to Python Converter ===")
    
    try:
        # Initialize converter
        converter = SASPythonConverter(output_directory="./mock_output")
        
        # Convert test files
        if os.path.exists("./mock_data"):
            sas_files = glob.glob(os.path.join("./mock_data", "*.sas"))
            
            if not sas_files:
                print("No SAS files found in ./mock_data")
                return
            
            success_count = 0
            error_count = 0
            
            for sas_file in sas_files:
                try:
                    print(f"\nConverting {sas_file}")
                    parser = SASParser()
                    components = parser.parse_file(sas_file)
                    python_files = converter.convert_to_python(components, sas_file)
                    success_count += 1
                    print(f"✓ Successfully converted to Python")
                except Exception as e:
                    error_count += 1
                    print(f"✗ Error converting file: {str(e)}")
            
            print(f"\nConversion complete:")
            print(f"Successfully converted: {success_count}")
            print(f"Failed conversions: {error_count}")
            
    except Exception as e:
        print(f"✗ Error initializing converter: {str(e)}")
        return False
    
    return True

def main():
    parser = argparse.ArgumentParser(description='Test SAS Parser and Converter')
    parser.add_argument('--input', default='./mock_data', help='Input directory with SAS files')
    parser.add_argument('--output', default='./mock_output', help='Output directory for Python files')
    parser.add_argument('--clean', action='store_true', help='Clean output directory before running')
    parser.add_argument('--debug', action='store_true', help='Enable debug logging')
    args = parser.parse_args()

    # Setup logging
    logging.basicConfig(
        level=logging.DEBUG if args.debug else logging.INFO,
        format='%(asctime)s - %(levelname)s - %(message)s'
    )

    try:
        if args.clean:
            clean_output_directory(args.output)

        # Run end-to-end test
        results = test_end_to_end_conversion(args.input, args.output)
        
        print("\nTest Summary:")
        print(f"Files processed: {results['files_processed']}")
        print(f"Components found: {results['components_found']}")
        print(f"Embeddings generated: {results['embeddings_generated']}")
        print(f"Python files created: {results['python_files_created']}")

    except Exception as e:
        logging.error(f"Critical error: {str(e)}", exc_info=True)
        sys.exit(1)

class TestSASPythonConverter(unittest.TestCase):
    def setUp(self):
        self.converter = SASPythonConverterTemplate()

    def test_proc_means(self):
        sas_code = """
        PROC MEANS data=mydata;
            var age income;
        run;
        """
        params = {
            'dataset': 'mydata',
            'variables': ['age', 'income']
        }
        python_code = self.converter.convert_proc('means', params)
        self.assertIn('mydata_df', python_code)
        self.assertIn("['age', 'income']", python_code)

    def test_data_step(self):
        sas_code = """
        DATA newdata;
            set mydata;
            where age > 18;
        run;
        """
        params = {
            'output_dataset': 'newdata',
            'input_dataset': 'mydata',
            'where_clause': 'age > 18'
        }
        python_code = self.converter.convert_data_step(params)
        self.assertIn('newdata_df', python_code)
        self.assertIn('mydata_df', python_code)
        self.assertIn('age > 18', python_code)

    def test_sql(self):
        sas_code = """
        PROC SQL;
            SELECT name, age
            FROM mydata
            WHERE age > 18;
        quit;
        """
        statements = [{
            'type': 'select',
            'table_df': 'mydata_df',
            'where_clause': 'age > 18'
        }]
        python_code = self.converter.convert_sql(statements)
        self.assertIn('mydata_df', python_code)
        self.assertIn('age > 18', python_code)

    def test_macro(self):
        sas_code = """
        %let var = value;
        """
        params = {
            'var_name': 'var',
            'value': 'value',
            'is_numeric': False
        }
        python_code = self.converter.convert_macro('let', params)
        self.assertIn('var = ', python_code)
        self.assertIn("'value'", python_code)

    def test_format(self):
        sas_code = """
        PROC FORMAT;
            value agefmt
                0-17 = 'Child'
                18-64 = 'Adult'
                65-high = 'Senior';
        run;
        """
        params = {
            'format_name': 'agefmt',
            'ranges': [
                {'start': 0, 'end': 17, 'label': 'Child'},
                {'start': 18, 'end': 64, 'label': 'Adult'},
                {'start': 65, 'end': float('inf'), 'label': 'Senior'}
            ]
        }
        python_code = self.converter.convert_format(params)
        self.assertIn('agefmt', python_code)
        self.assertIn('Child', python_code)
        self.assertIn('Adult', python_code)
        self.assertIn('Senior', python_code)

if __name__ == "__main__":
    main()