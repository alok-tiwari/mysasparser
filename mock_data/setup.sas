/* Library and file setup */
libname RAWDATA "/path/to/raw" access=readonly;
libname WORK "/path/to/work" compress=yes;

/* Global options */
options nocenter mprint symbolgen mlogic;
options compress=yes reuse=yes;

/* External file references */
filename DATAIN "/path/to/input.csv";
filename REPORT "/path/to/report.txt";

/* Include external code */
%include "/path/to/macros.sas"; 