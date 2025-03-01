/* Test various SAS components */
PROC MEANS data=sashelp.class;
    var age height weight;
run;

DATA filtered;
    set sashelp.class;
    where age > 12;
    bmi = weight / (height * height) * 703;
run;

PROC SQL;
    SELECT name, age, calculated bmi
    FROM filtered
    WHERE bmi > 20
    ORDER BY bmi desc;
quit; 