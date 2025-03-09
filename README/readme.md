

# SAS to Python Converter Components

## Components Covered in Parsing (SAS_parser.py)

The SAS parser identifies and extracts the following component types from SAS code:

### Core Processing Components

1. **PROC** - Procedure statements (e.g., `PROC MEANS`, `PROC PRINT`)
   - Regular PROC statements
   - Special PROCs (SQL, IML, R, etc.)
2. **DATA** - Data step definitions
3. **MACRO** - Macro definitions (`%macro...%mend`)

### Resource Definitions

4. **LIBNAME** - Library reference definitions
5. **FILENAME** - File reference definitions

### Macro Programming

6. **%LET** - Macro variable assignments
7. **%IF** - Conditional macro statements
8. **%DO** - Macro loop statements
9. **%PUT** - Macro output statements
10. **%INCLUDE** - Include external SAS code

### Output and Formatting

11. **ODS** - Output Delivery System statements
12. **TITLE** - Title definitions
13. **FOOTNOTE** - Footnote definitions
14. **OPTIONS** - SAS system options

### Graphics Components

15. **AXIS** - Axis definitions for graphics
16. **LEGEND** - Legend definitions for graphics
17. **SYMBOL** - Symbol definitions for graphics
18. **PATTERN** - Pattern definitions for graphics
19. **GOPTIONS** - Graphics options

### Format and Informats

20. **FORMAT** - Format definitions
21. **INFORMAT** - Input format definitions

### Special Cases

22. **CARDS/DATALINES** - Inline data blocks

## Components Handled by SAS_python_converter.py

The SAS to Python converter implements conversion methods for the following component types:

### PROC Statements

1. **PROC** - Converted to pandas/scipy operations
   - `_convert_proc_means` → pandas `describe()`
   - `_convert_proc_ttest` → scipy.stats `ttest_1samp()`
   - `_convert_proc_univariate` → pandas/scipy statistics
   - `_convert_proc_report` → pandas DataFrame display
   - `_convert_proc_gchart` → matplotlib/seaborn charts
   - `_convert_proc_format` → Python functions for formatting
   - `_convert_proc_sort` → pandas `sort_values()`
   - `_convert_proc_reg` → scipy/statsmodels regression
   - `_convert_proc_freq` → pandas value_counts()
   - `_convert_proc_corr` → pandas corr() method
   - `_convert_proc_print` → pandas display
   - `_convert_proc_sgplot` → matplotlib/seaborn plots

### DATA Steps

2. **DATA** - Converted to pandas DataFrame operations
   - `_convert_data_step` → Dataset creation and manipulation
   - `_convert_null_data_step` → Operations without dataset creation
   - Variable assignments
   - WHERE clause filtering

### SQL Operations

3. **PROC_SQL** - Converted to pandas operations
   - `_convert_sql` → Basic SQL operations
   - `_convert_complex_sql` → Multi-table operations
   - `_convert_sql_condition` → WHERE clauses → query() method
   - `_convert_sql_expression` → SQL expressions to pandas
   - SELECT statements → DataFrame filtering/selection
   - JOIN operations → merge() method

### Macro Programming

4. **MACRO** - Converted to Python functions
   - `_convert_macro` → Function definitions
   - `_convert_macro_variable` → Variable handling
   - `_convert_macro_statement` → Statement conversion
   - `_convert_macro_condition` → Condition evaluation
   - `_convert_macro_action` → Action implementation
   - Parameter handling
   - Function body conversion

5. **%LET** - Converted to Python variable assignments
   - Type conversion (numeric/string)
   - Function call handling

6. **%IF** - Converted to Python if/else statements
   - Operator translation (eq → ==, ne → !=, etc.)
   - Condition evaluation

7. **%DO** - Converted to Python loops
   - Counter-based loops → for loops with range()
   - While loops → Python while loops

8. **%PUT** - Converted to Python print statements

### Resource Definitions

9. **LIBNAME** - Converted to file path variables
   - `_convert_libname` → Path variables

10. **FILENAME** - Converted to file path variables
    - `_convert_filename` → File references

### Formatting and Output

11. **ODS** - Converted to matplotlib/pandas output settings
    - `_convert_ods` → Output configuration
    - `_convert_ods_graphics` → Graphics settings
    - HTML output configuration
    - Graphics on/off settings

12. **TITLE/FOOTNOTE** - Converted to matplotlib title/suptitle/figtext
    - `_convert_title_footnote` → Plot annotations

13. **GOPTIONS** - Converted to matplotlib configuration

14. **FORMAT** - Converted to Python formatting functions
    - `_convert_format` → Custom formatters

### Helper Methods for Expressions

15. **Expression Handling**
    - `_convert_sas_expression` → SAS to Python expressions
    - `_convert_sas_condition` → Condition translation
    - `_convert_where_clause` → Filtering conditions

16. **_convert_using_similar** - Fallback method using vector embeddings
    - Uses similar components as reference
    - Substitutes dataset names and variables

The converter also includes helper methods for:
- Dataset loading code generation
- Variable type conversion
- SAS expression translation
- Error handling and fallback mechanisms

This comprehensive approach ensures that most common SAS components can be converted to equivalent Python code, with fallback mechanisms for more complex or unusual patterns.




# SAS to Python Converter

This tool converts SAS code to Python, focusing on data analysis workflows. It uses a combination of pattern matching and vector embeddings to translate SAS constructs to their Python equivalents.

## Features

- Converts SAS DATA steps to pandas operations
- Translates common SAS PROCs to Python equivalents:
  - PROC MEANS → pandas.DataFrame.describe()
  - PROC TTEST → scipy.stats.ttest_1samp()
  - PROC UNIVARIATE → scipy.stats and pandas descriptive statistics
  - PROC SGPLOT → matplotlib/seaborn visualizations
  - PROC GCHART → matplotlib bar/pie charts
  - PROC SQL → pandas operations
  - PROC SORT → pandas.DataFrame.sort_values()
  - PROC FORMAT → custom formatting functions
- Handles SAS macro variables and functions
- Converts SAS ODS statements to matplotlib/pandas output settings
- Processes SAS libraries and datasets
- Cleans variable names to ensure Python compatibility

## Installation

```bash
git clone https://github.com/yourusername/sas-python-converter.git
cd sas-python-converter
pip install -r requirements.txt
```

## Usage

### Command Line Interface

```bash
python test_parser.py --input ./path/to/sas/files --output ./output/directory --clean --debug
```

Options:
- `--input`: Directory containing SAS files or path to a single SAS file
- `--output`: Directory where converted Python files will be saved
- `--clean`: Remove existing output directory before conversion
- `--debug`: Enable debug logging

### As a Library

```python
from sas_parser import SASParser
from sas_python_converter import SASPythonConverter

# Initialize parser and converter
parser = SASParser()
converter = SASPythonConverter(output_directory="./python_output")

# Parse SAS file
components = parser.parse_file("path/to/sas_file.sas")

# Convert to Python
python_code = converter.convert_to_python(components)

# Save to file
with open("output.py", "w") as f:
    f.write(python_code)
```

## Recent Improvements

- Added support for PROC SGPLOT conversion to matplotlib/seaborn
- Improved handling of SAS macro functions like %scan and %eval
- Enhanced ODS GRAPHICS conversion to matplotlib settings
- Better handling of variable names with invalid characters
- Fixed syntax errors in generated Python code
- Improved conversion of DATA step operations
- Enhanced error handling and reporting
- Added support for SAS macro control structures (%do %while, etc.)

## Limitations

- Complex SAS macros may require manual adjustment after conversion
- Custom SAS formats may not convert perfectly
- Some specialized SAS procedures may not have direct Python equivalents
- SAS-specific statistical methods might need additional Python libraries

## Contributing

Contributions are welcome! Please feel free to submit a Pull Request.

## License

This project is licensed under the MIT License - see the LICENSE file for details.
