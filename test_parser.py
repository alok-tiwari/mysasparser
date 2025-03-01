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

def test_parser():
    # Test SAS Parser
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
    print("\nCleaning up ChromaDB...")
    # Remove the ChromaDB directory if it exists
    if os.path.exists("chroma_db"):
        shutil.rmtree("chroma_db")
    print("ChromaDB cleaned up")

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
    embedding_gen = EmbeddingGenerator(embedding_dim=4096)  # Explicit dimension
    vector_store = VectorStore(persist_directory="chroma_db")
    converter = SASPythonConverter(
        vector_store=vector_store,
        output_directory=output_dir,
        embedding_generator=embedding_gen  # Pass the instance
    )
    
    # Process all files in directory
    total_files = 0
    total_components = 0
    all_embeddings = []
    
    print("\nStep 1: Parsing SAS files...")
    for components in parser.parse_directory(input_dir):
        if components:
            total_files += 1
            total_components += len(components)
            
            # Generate embeddings for these components
            print(f"Generating embeddings for {len(components)} components...")
            embeddings = embedding_gen.generate_embeddings(components)
            all_embeddings.extend(embeddings)
    
    print(f"\nParsed {total_files} files with {total_components} components")
    
    print("\nStep 2: Storing embeddings in vector database...")
    vector_store.store_embeddings(all_embeddings)
    print(f"Stored {len(all_embeddings)} embeddings")
    
    print("\nStep 3: Converting SAS to Python...")
    # Convert the directory
    converted_files = converter.convert_directory(input_dir)
    print(f"Converted {len(converted_files)} files to Python")
    
    print("\nConversion complete!")
    print(f"Output Python files are in: {output_dir}")
    
    # Return summary
    return {
        "files_processed": total_files,
        "components_found": total_components,
        "embeddings_generated": len(all_embeddings),
        "python_files_created": len(converted_files)
    }

def test_template_converter():
    """Test the template-based converter."""
    print("\n=== Testing Template-Based Converter ===")
    converter = SASPythonConverterTemplate()
    
    # Test cases with expected outputs
    test_cases = [
        {
            'type': 'PROC',
            'name': 'means',
            'content': """
            PROC MEANS data=mydata maxdec=2;
                var age income;
                by gender;
            run;
            """,
            'expected': ['mydata_df', 'age', 'income', 'gender', 'describe']
        },
        {
            'type': 'DATA',
            'content': """
            DATA filtered;
                set mydata;
                where age > 18;
                bmi = weight / (height * height) * 703;
            run;
            """,
            'expected': ['filtered_df', 'mydata_df', 'age > 18', 'bmi']
        },
        {
            'type': 'PROC',
            'name': 'sql',
            'content': """
            PROC SQL;
                SELECT name, age, calculated bmi
                FROM filtered
                WHERE bmi > 20
                ORDER BY bmi desc;
            quit;
            """,
            'expected': ['filtered_df', 'bmi > 20', 'sort_values']
        }
    ]
    
    print("\nTesting component conversions:")
    for case in test_cases:
        print(f"\nConverting {case['type']} {case.get('name', '')}")
        try:
            result = converter.convert_component(case)
            print("Result:")
            print(result)
            # Verify expected elements are in result
            for expected in case['expected']:
                assert expected in result, f"Expected '{expected}' not found in result"
            print("✓ All expected elements found")
        except Exception as e:
            print(f"Error: {str(e)}")

def clean_output_directory(output_dir: str):
    """Clean up the output directory."""
    import shutil
    try:
        if os.path.exists(output_dir):
            shutil.rmtree(output_dir)
        os.makedirs(output_dir)
        print(f"\nCleaned output directory: {output_dir}")
    except Exception as e:
        print(f"Error cleaning output directory: {str(e)}")

def main():
    """Main test function."""
    parser = argparse.ArgumentParser(description='Test SAS Parser')
    parser.add_argument('--input', default='./mock_data', help='Input directory with SAS files')
    parser.add_argument('--output', default='./mock_output', help='Output directory for Python files')
    parser.add_argument('--clean', action='store_true', help='Clean output directory before running')
    args = parser.parse_args()

    if args.clean:
        # Clean up output directory first
        clean_output_directory(args.output)
        print("\nCleaning up ChromaDB...")
        cleanup_chromadb()
        print("ChromaDB cleaned up")

    print("\nTesting Parser...")
    test_parser()

    print("\nTesting Template Converter...")
    test_template_converter()

    # Convert all SAS files in mock_data
    if os.path.exists(args.input):
        converter = SASPythonConverterTemplate()
        sas_files = glob.glob(os.path.join(args.input, "*.sas"))
        
        if not os.path.exists(args.output):
            os.makedirs(args.output)
            
        converted_count = 0
        for sas_file in sas_files:
            try:
                output_file = os.path.join(
                    args.output, 
                    os.path.splitext(os.path.basename(sas_file))[0] + '.py'
                )
                converter.convert_file(sas_file, output_file)
                converted_count += 1
                print(f"Successfully converted {sas_file} to {output_file}")
            except Exception as e:
                print(f"Error converting {sas_file}: {str(e)}")
                
        print(f"\nConverted {converted_count} files to Python")
        print(f"\nConversion complete!")
        print(f"Output Python files are in: {args.output}")

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