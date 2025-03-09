/* Sample SAS file for testing */
proc sql;
    create table test as
    select *
    from input_data;
quit;

data output;
    set test;
    if age > 18;
run;

%macro test_macro;
    proc print data=output;
    run;
%mend; 