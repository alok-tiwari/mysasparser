/* Graphics and reporting components */
goptions reset=all device=png;

/* Title and footnote */
title1 "Sales Analysis Report";
title2 "Year 2023";
footnote1 "Confidential";

/* Graph customization */
axis1 label=("Sales") order=(0 to 1000000 by 100000);
axis2 label=("Month");
legend1 label=("Region");
symbol1 value=dot color=blue;
pattern1 value=solid color=red;

/* ODS output */
ods graphics on;
ods html path="./output" body="report.html";

proc gchart data=sales;
    vbar month / sumvar=amount
                 type=sum
                 axis=axis1
                 legend=legend1;
run;

ods html close;
ods graphics off; 