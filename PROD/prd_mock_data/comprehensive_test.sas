/* Top level comment */
options mprint;

/* Standalone PROC */
proc print data=sashelp.class;
    var name age height;
    where age > 12;
run;

/* Macro with nested components */
%macro process_data(ds_in=, ds_out=);
    /* Nested comment */
    proc sql;
        create table work.temp as
        select a.*, 
               b.category
        from &ds_in as a
        left join classifications as b
            on a.id = b.id
        where a.date >= '01JAN2023'd;
    quit;

    data &ds_out;
        set work.temp;
        array nums(*) _numeric_;
        do i = 1 to dim(nums);
            if nums(i) = . then nums(i) = 0;
        end;
    run;
%mend;

/* Standalone data step */
data work.final;
    set sashelp.class;
    bmi = weight / (height * height);
run;

/* Nested macros */
%macro outer;
    %macro inner1;
        proc means data=sashelp.class;
            var age height weight;
        run;
    %mend;

    %macro inner2;
        proc freq data=sashelp.class;
            tables sex age;
        run;
    %mend;

    %inner1;
    %inner2;
%mend;

/* Standalone libname */
libname mylib '/path/to/lib';

/* Multiple comments */
/* Comment 1 */
* Comment 2;
/* Multiline
   Comment 3
   with indentation */ 