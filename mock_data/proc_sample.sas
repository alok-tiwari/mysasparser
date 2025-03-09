proc sql nowarnrecurs;
    create table CT_DELTA_TEMP as 
        select 
            ct.*,
            ms.quarter, 
            ms.SHARUN_3M_IND,
            mso.SHARUN_3M_IND as SHARUN_3M_IND_0,
            pp_id,
            wi_re_id,
            wm_pos_id,
            quarter
        from &input. ct
            left join &macro. ms on (1=1)
            left join &macro. mso on mso.quarter = 0
        order by pp_id, wi_re_id, wm_pos_id, quarter;
quit;

%PARAMETER_Join_Parameter(
    CT_DELTA_TEMP, 
    USA_LIBOR_floor, 
    name = USA_LIBOR_floor
);

data &output.;
    set CT_DELTA_TEMP;
    if (flag_fixed_ir = 'N') then
        IR_VAR_DELTA = (max(SHARUN_3M_IND, USA_LIBOR_floor) - max(SHARUN_3M_IND_0, USA_LIBOR_floor));
    else 
        IR_VAR_DELTA = 0;
run;

%mend;