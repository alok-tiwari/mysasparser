/* Complex SAS example */
%macro process_data(ds_in=, ds_out=);
    %if &ds_in = %then %do;
        %put ERROR: Input dataset required;
        %return;
    %end;

    proc sql;
        create table work.temp as
        select a.*, b.category
        from &ds_in as a
        left join classifications as b
        on a.id = b.id
        where a.date >= '01JAN2023'd
        having count(*) > 1;
    quit;

    proc report data=work.temp;
        column region sales profit;
        define region / group;
        compute before region;
            line ' ';
        endcomp;
    run;

    data &ds_out;
        set work.temp;
        array nums(*) _numeric_;
        do i = 1 to dim(nums);
            if nums(i) = . then nums(i) = 0;
        end;
    run;
%mend; 