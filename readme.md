

# SAS to Python Converter Components

## SAS Components Parsed by SAS_parser.py

The SAS parser identifies and extracts the following component types from SAS code:

1. **PROC** - Procedure statements (e.g., `PROC MEANS`, `PROC PRINT`)
2. **DATA** - Data step definitions
3. **LIBNAME** - Library reference definitions
4. **MACRO** - Macro definitions (`%macro...%mend`)
5. **%LET** - Macro variable assignments
6. **%IF** - Conditional macro statements
7. **%DO** - Macro loop statements
8. **%PUT** - Macro output statements
9. **PROC_SQL** - SQL procedure statements
10. **ODS** - Output Delivery System statements
11. **TITLE** - Title definitions
12. **FOOTNOTE** - Footnote definitions
13. **AXIS** - Axis definitions for graphics
14. **LEGEND** - Legend definitions for graphics
15. **SYMBOL** - Symbol definitions for graphics
16. **PATTERN** - Pattern definitions for graphics
17. **GOPTIONS** - Graphics options
18. **OPTIONS** - SAS system options
19. **FILENAME** - File reference definitions
20. **FORMAT** - Format definitions
21. **INFORMAT** - Input format definitions

## Components Handled by SAS_python_converter.py

The SAS to Python converter implements conversion methods for the following component types:

1. **PROC** - Converted to pandas/scipy operations
   - `PROC MEANS` → pandas `describe()`
   - `PROC TTEST` → scipy.stats `ttest_1samp()`
   - `PROC UNIVARIATE` → pandas/scipy statistics
   - `PROC REPORT` → pandas DataFrame display
   - `PROC GCHART` → matplotlib/seaborn charts
   - `PROC FORMAT` → Python functions for formatting
   - `PROC SORT` → pandas `sort_values()`

2. **DATA** - Converted to pandas DataFrame operations
   - Dataset creation
   - Variable assignments
   - WHERE clause filtering

3. **LIBNAME** - Converted to file path variables

4. **MACRO** - Converted to Python functions
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

9. **PROC_SQL** - Converted to pandas operations
   - SELECT statements → DataFrame filtering/selection
   - WHERE clauses → query() method
   - JOIN operations → merge() method

10. **ODS** - Converted to matplotlib/pandas output settings
    - HTML output configuration
    - Graphics on/off settings

11. **TITLE/FOOTNOTE** - Converted to matplotlib title/suptitle/figtext

12. **GOPTIONS** - Converted to matplotlib configuration

13. **_convert_using_similar** - Fallback method using vector embeddings
    - Uses similar components as reference
    - Substitutes dataset names and variables

The converter also includes helper methods for:
- Dataset loading code generation
- Variable type conversion
- SAS expression translation
- Error handling and fallback mechanisms

This comprehensive approach ensures that most common SAS components can be converted to equivalent Python code, with fallback mechanisms for more complex or unusual patterns.
