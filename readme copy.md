Components Covered in Parsing (SASParser)
The parser handles a wide range of SAS components:

Core Processing Components:

PROC statements (regular and special procs like SQL, IML, R, etc.)
DATA steps
MACRO definitions


Resource Definitions:

LIBNAME statements
FILENAME statements


Output and Formatting:

OPTIONS statements
ODS statements
TITLE and FOOTNOTE statements


Graphics Components:

GOPTIONS, SYMBOL, AXIS, PATTERN, LEGEND statements


Format and Informats:

FORMAT statements
INFORMAT statements


Macro Programming:

%LET statements
%DO loops
%IF conditional statements
%PUT statements
%INCLUDE statements


Special Cases:

CARDS/DATALINES blocks



Components Covered in Conversion (SASPythonConverter)
The converter has methods for transforming:

PROC Statements:

_convert_proc_means
_convert_proc_univariate
_convert_proc_ttest
_convert_proc_sort
_convert_proc_reg
_convert_proc_freq
_convert_proc_corr
_convert_proc_print
_convert_proc_report
_convert_proc_format
_convert_proc_sgplot


DATA Steps:

_convert_data_step
_convert_null_data_step


SQL Operations:

_convert_sql
_convert_complex_sql
_convert_sql_condition
_convert_sql_expression


Macro Programming:

_convert_macro
_convert_macro_variable
_convert_macro_statement
_convert_macro_condition
_convert_macro_action


Resource Definitions:

_convert_libname
_convert_filename


Formatting and Output:

_convert_format
_convert_title_footnote
_convert_ods
_convert_ods_graphics


Helper Methods for Expressions:

_convert_sas_expression
_convert_sas_condition
_convert_where_clause