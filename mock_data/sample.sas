/* Complex SAS program demonstrating various features */

/* Library definitions with multiple options */
libname RAW "/path/to/raw" access=readonly;
libname STAGE "/path/to/stage" compress=yes;
libname DW oracle path="@production" schema=DW_SCHEMA;

/* Global macro variables */
%let reporting_date = %sysfunc(today());
%let lookback_period = 12;

/* Complex macro with nested logic and error handling */
%macro process_data(input_ds, output_ds, date_var=, filter_condition=);
    %local error_count;
    %let error_count = 0;
    
    /* Input parameter validation */
    %if %sysfunc(exist(&input_ds)) = 0 %then %do;
        %put ERROR: Input dataset &input_ds does not exist;
        %let error_count = %eval(&error_count + 1);
    %end;
    
    %if &error_count = 0 %then %do;
        /* Data processing with multiple steps */
        proc sql noprint;
            create table work.temp_stats as
            select count(*) as record_count,
                   count(distinct &date_var) as date_count,
                   min(&date_var) as min_date format=date9.,
                   max(&date_var) as max_date format=date9.
            from &input_ds
            where &filter_condition;
        quit;
        
        data &output_ds;
            merge &input_ds(in=a)
                  work.temp_stats(in=b);
            by &date_var;
            if a;
            
            /* Complex calculations */
            array metrics{*} metric1-metric10;
            array flags{*} flag1-flag10;
            
            do i = 1 to dim(metrics);
                metrics{i} = sum(of var1-var5) / calculated record_count;
                flags{i} = (metrics{i} > mean(of var1-var5));
            end;
            
            /* Custom formatting */
            format metrics: 8.2 flags: $1.;
            informat _numeric_ best32.;
        run;
        
        /* Error checking */
        %if &syserr > 4 %then %do;
            %put ERROR: Data step failed with error code &syserr;
            %let error_count = %eval(&error_count + 1);
        %end;
    %end;
    
    /* Return macro status */
    &error_count
%mend process_data;

/* Complex DATA step with hash tables and arrays */
data STAGE.daily_summary;
    if _n_ = 1 then do;
        /* Initialize hash object */
        declare hash customer_info(dataset: 'DW.customer_master');
        customer_info.defineKey('customer_id');
        customer_info.defineData('customer_type', 'region', 'segment');
        customer_info.defineDone();
        call missing(customer_type, region, segment);
    end;
    
    /* Array for moving averages */
    array daily_values{90} _temporary_;
    retain window_idx 1;
    
    set RAW.transactions;
    by customer_id date;
    
    /* Lookup customer info */
    rc = customer_info.find();
    
    /* Calculate moving averages */
    daily_values{window_idx} = transaction_amount;
    if window_idx = 90 then window_idx = 1;
    else window_idx + 1;
    
    moving_avg = mean(of daily_values{*});
    
    /* Output filtered records */
    if moving_avg > 1000 and region = 'NORTH';
run;

/* Complex PROC SQL with multiple joins and window functions */
proc sql;
    create table STAGE.sales_analysis as
    select 
        a.customer_id,
        a.transaction_date,
        b.product_category,
        c.region,
        sum(a.amount) as total_sales,
        calculated total_sales / 
            sum(calculated total_sales) over (partition by c.region) as region_share,
        avg(a.amount) over (
            partition by a.customer_id 
            order by a.transaction_date 
            rows between 90 preceding and current row
        ) as moving_avg_90d
    from DW.transactions a
    left join DW.products b
        on a.product_id = b.product_id
    left join DW.geography c
        on a.location_id = c.location_id
    where a.transaction_date between 
        intnx('month', &reporting_date, -&lookback_period, 'B') and 
        &reporting_date
    group by 
        a.customer_id,
        a.transaction_date,
        b.product_category,
        c.region
    having calculated total_sales > 0
    order by 
        c.region,
        calculated total_sales desc;
quit;

/* Statistical analysis with multiple procedures */
proc means data=STAGE.sales_analysis noprint;
    class region product_category;
    var total_sales moving_avg_90d;
    output out=STAGE.summary_stats
           mean= std= min= max= / autoname;
run;

proc univariate data=STAGE.sales_analysis;
    class region;
    var total_sales;
    histogram / normal kernel;
    probplot / normal(mu=est sigma=est);
run;

/* Format creation with nested ranges */
proc format;
    value sales_range
        low-<1000="Low"
        1000-<5000="Medium"
        5000-<10000="High"
        10000-high="Premium"
    ;
    
    value $ region_group
        "NORTH","SOUTH"="Vertical-1"
        "EAST","WEST"="Vertical-2"
        other="Unknown"
    ;
run;

/* Call macro with complex parameters */
%let rc = %process_data(
    input_ds=STAGE.sales_analysis,
    output_ds=STAGE.final_output,
    date_var=transaction_date,
    filter_condition=%str(
        region in ('NORTH', 'SOUTH') and 
        total_sales > 0 and 
        moving_avg_90d is not missing
    )
);