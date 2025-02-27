/* Complex statistical analysis example */

/* Set global macro variables */
%let alpha = 0.05;
%let min_obs = 1000;

/* Create formats for reporting */
proc format;
    value age_grp
        low-25 = 'Young'
        26-50 = 'Middle'
        51-high = 'Senior'
    ;
    value $region_fmt
        'NA' = 'North America'
        'EU' = 'Europe'
        'APAC' = 'Asia Pacific'
        other = 'Other Regions'
    ;
run;

/* Complex macro for analysis */
%macro analyze_segment(data=, segment=, var=);
    /* Create summary statistics */
    proc means data=&data noprint;
        where segment = "&segment";
        var &var;
        output out=work.stats_&segment
               mean=avg
               std=std_dev
               min=min_val
               max=max_val
               n=n_obs;
    run;

    /* Check if enough observations */
    data _null_;
        set work.stats_&segment;
        if n_obs < &min_obs then do;
            put "WARNING: Insufficient observations for &segment";
            call symputx('skip_analysis', 1);
        end;
        else call symputx('skip_analysis', 0);
    run;

    %if &skip_analysis = 0 %then %do;
        /* Detailed analysis */
        proc univariate data=&data normal plot;
            where segment = "&segment";
            var &var;
            histogram / normal kernel;
            probplot / normal(mu=est sigma=est);
            qqplot / normal(mu=est sigma=est);
        run;

        /* Statistical tests */
        proc ttest data=&data h0=0 alpha=&alpha;
            where segment = "&segment";
            var &var;
        run;
    %end;
%mend analyze_segment;

/* Main analysis */
proc sql noprint;
    /* Get list of segments */
    select distinct segment 
    into :segment_list separated by ' '
    from WORK.analysis_data;
quit;

/* Loop through segments */
%macro run_analysis;
    %let i = 1;
    %let segment = %scan(&segment_list, &i);
    %do %while(&segment ne );
        %analyze_segment(
            data=WORK.analysis_data,
            segment=&segment,
            var=response_time
        );
        %let i = %eval(&i + 1);
        %let segment = %scan(&segment_list, &i);
    %end;
%mend run_analysis;

/* Execute analysis */
%run_analysis;

/* Generate reports */
ods graphics on;
ods html path="./output" 
         body="analysis_report.html"
         style=statistical;

title1 "Statistical Analysis Report";
title2 "By Segment";

proc report data=WORK.analysis_data;
    column segment n_obs avg std_dev min_val max_val;
    define segment / group 'Segment';
    define n_obs / 'N' format=comma8.;
    define avg / 'Average' format=8.2;
    define std_dev / 'Std Dev' format=8.2;
    define min_val / 'Minimum' format=8.2;
    define max_val / 'Maximum' format=8.2;
run;

ods html close;
ods graphics off; 