--
-- PostgreSQL database dump
--

-- Dumped from database version 10.7
-- Dumped by pg_dump version 17.2

-- Started on 2025-11-06 11:19:19

SET statement_timeout = 0;
SET lock_timeout = 0;
SET idle_in_transaction_session_timeout = 0;
SET transaction_timeout = 0;
SET client_encoding = 'UTF8';
SET standard_conforming_strings = on;
SELECT pg_catalog.set_config('search_path', '', false);
SET check_function_bodies = false;
SET xmloption = content;
SET client_min_messages = warning;
SET row_security = off;

--
-- TOC entry 7 (class 2615 OID 27267)
-- Name: public; Type: SCHEMA; Schema: -; Owner: Administrator
--

-- *not* creating schema, since initdb creates it


ALTER SCHEMA public OWNER TO "Administrator";

--
-- TOC entry 1 (class 3079 OID 27268)
-- Name: plpgsql; Type: EXTENSION; Schema: -; Owner: -
--

CREATE EXTENSION IF NOT EXISTS plpgsql WITH SCHEMA pg_catalog;


--
-- TOC entry 4715 (class 0 OID 0)
-- Dependencies: 1
-- Name: EXTENSION plpgsql; Type: COMMENT; Schema: -; Owner: 
--

COMMENT ON EXTENSION plpgsql IS 'PL/pgSQL procedural language';


SET default_tablespace = '';

--
-- TOC entry 196 (class 1259 OID 27273)
-- Name: acc_acccombination; Type: TABLE; Schema: public; Owner: postgres
--

CREATE TABLE public.acc_acccombination (
    id integer NOT NULL,
    create_time timestamp with time zone,
    create_user character varying(150),
    change_time timestamp with time zone,
    change_user character varying(150),
    status smallint NOT NULL,
    combination_no integer NOT NULL,
    combination_name character varying(100) NOT NULL,
    group1 integer,
    group2 integer,
    group3 integer,
    group4 integer,
    group5 integer,
    remark character varying(999),
    update_time timestamp with time zone,
    area_id integer NOT NULL
);


ALTER TABLE public.acc_acccombination OWNER TO postgres;

--
-- TOC entry 197 (class 1259 OID 27279)
-- Name: acc_acccombination_id_seq; Type: SEQUENCE; Schema: public; Owner: postgres
--

CREATE SEQUENCE public.acc_acccombination_id_seq
    AS integer
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;


ALTER SEQUENCE public.acc_acccombination_id_seq OWNER TO postgres;

--
-- TOC entry 4716 (class 0 OID 0)
-- Dependencies: 197
-- Name: acc_acccombination_id_seq; Type: SEQUENCE OWNED BY; Schema: public; Owner: postgres
--

ALTER SEQUENCE public.acc_acccombination_id_seq OWNED BY public.acc_acccombination.id;


--
-- TOC entry 198 (class 1259 OID 27281)
-- Name: acc_accgroups; Type: TABLE; Schema: public; Owner: postgres
--

CREATE TABLE public.acc_accgroups (
    id integer NOT NULL,
    create_time timestamp with time zone,
    create_user character varying(150),
    change_time timestamp with time zone,
    change_user character varying(150),
    status smallint NOT NULL,
    group_no integer NOT NULL,
    group_name character varying(100) NOT NULL,
    verify_mode integer NOT NULL,
    timezone1 integer,
    timezone2 integer,
    timezone3 integer,
    is_include_holiday smallint NOT NULL,
    update_time timestamp with time zone,
    area_id integer NOT NULL
);


ALTER TABLE public.acc_accgroups OWNER TO postgres;

--
-- TOC entry 199 (class 1259 OID 27284)
-- Name: acc_accgroups_id_seq; Type: SEQUENCE; Schema: public; Owner: postgres
--

CREATE SEQUENCE public.acc_accgroups_id_seq
    AS integer
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;


ALTER SEQUENCE public.acc_accgroups_id_seq OWNER TO postgres;

--
-- TOC entry 4717 (class 0 OID 0)
-- Dependencies: 199
-- Name: acc_accgroups_id_seq; Type: SEQUENCE OWNED BY; Schema: public; Owner: postgres
--

ALTER SEQUENCE public.acc_accgroups_id_seq OWNED BY public.acc_accgroups.id;


--
-- TOC entry 200 (class 1259 OID 27286)
-- Name: acc_accholiday; Type: TABLE; Schema: public; Owner: postgres
--

CREATE TABLE public.acc_accholiday (
    id integer NOT NULL,
    create_time timestamp with time zone,
    create_user character varying(150),
    change_time timestamp with time zone,
    change_user character varying(150),
    status smallint NOT NULL,
    update_time timestamp with time zone,
    area_id integer NOT NULL,
    holiday_id integer NOT NULL,
    timezone_id integer NOT NULL
);


ALTER TABLE public.acc_accholiday OWNER TO postgres;

--
-- TOC entry 201 (class 1259 OID 27289)
-- Name: acc_accholiday_id_seq; Type: SEQUENCE; Schema: public; Owner: postgres
--

CREATE SEQUENCE public.acc_accholiday_id_seq
    AS integer
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;


ALTER SEQUENCE public.acc_accholiday_id_seq OWNER TO postgres;

--
-- TOC entry 4718 (class 0 OID 0)
-- Dependencies: 201
-- Name: acc_accholiday_id_seq; Type: SEQUENCE OWNED BY; Schema: public; Owner: postgres
--

ALTER SEQUENCE public.acc_accholiday_id_seq OWNED BY public.acc_accholiday.id;


--
-- TOC entry 202 (class 1259 OID 27291)
-- Name: acc_accprivilege; Type: TABLE; Schema: public; Owner: postgres
--

CREATE TABLE public.acc_accprivilege (
    id integer NOT NULL,
    create_time timestamp with time zone,
    create_user character varying(150),
    change_time timestamp with time zone,
    change_user character varying(150),
    status smallint NOT NULL,
    is_group_timezone smallint NOT NULL,
    timezone1 integer,
    timezone2 integer,
    timezone3 integer,
    is_group_verifycode smallint NOT NULL,
    verify_mode integer,
    update_time timestamp with time zone,
    area_id integer NOT NULL,
    employee_id integer NOT NULL,
    group_id integer NOT NULL
);


ALTER TABLE public.acc_accprivilege OWNER TO postgres;

--
-- TOC entry 203 (class 1259 OID 27294)
-- Name: acc_accprivilege_id_seq; Type: SEQUENCE; Schema: public; Owner: postgres
--

CREATE SEQUENCE public.acc_accprivilege_id_seq
    AS integer
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;


ALTER SEQUENCE public.acc_accprivilege_id_seq OWNER TO postgres;

--
-- TOC entry 4719 (class 0 OID 0)
-- Dependencies: 203
-- Name: acc_accprivilege_id_seq; Type: SEQUENCE OWNED BY; Schema: public; Owner: postgres
--

ALTER SEQUENCE public.acc_accprivilege_id_seq OWNED BY public.acc_accprivilege.id;


--
-- TOC entry 204 (class 1259 OID 27296)
-- Name: acc_accterminal; Type: TABLE; Schema: public; Owner: postgres
--

CREATE TABLE public.acc_accterminal (
    id integer NOT NULL,
    create_time timestamp with time zone,
    create_user character varying(150),
    change_time timestamp with time zone,
    change_user character varying(150),
    status smallint NOT NULL,
    door_name character varying(50),
    door_lock_delay integer NOT NULL,
    door_sensor_delay integer NOT NULL,
    door_sensor_type smallint NOT NULL,
    door_alarm_delay integer NOT NULL,
    retry_times smallint NOT NULL,
    valid_holiday smallint NOT NULL,
    nc_time_period integer NOT NULL,
    no_time_period integer NOT NULL,
    speaker_alarm smallint NOT NULL,
    duress_fun_on smallint NOT NULL,
    alarm_1_1 smallint NOT NULL,
    alarm_1_n smallint NOT NULL,
    alarm_password smallint NOT NULL,
    duress_alarm_delay integer NOT NULL,
    anti_passback_mode smallint NOT NULL,
    anti_door_direction smallint NOT NULL,
    verify_mode_485 smallint NOT NULL,
    push_time timestamp with time zone,
    terminal_id integer NOT NULL
);


ALTER TABLE public.acc_accterminal OWNER TO postgres;

--
-- TOC entry 205 (class 1259 OID 27299)
-- Name: acc_accterminal_id_seq; Type: SEQUENCE; Schema: public; Owner: postgres
--

CREATE SEQUENCE public.acc_accterminal_id_seq
    AS integer
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;


ALTER SEQUENCE public.acc_accterminal_id_seq OWNER TO postgres;

--
-- TOC entry 4720 (class 0 OID 0)
-- Dependencies: 205
-- Name: acc_accterminal_id_seq; Type: SEQUENCE OWNED BY; Schema: public; Owner: postgres
--

ALTER SEQUENCE public.acc_accterminal_id_seq OWNED BY public.acc_accterminal.id;


--
-- TOC entry 206 (class 1259 OID 27301)
-- Name: acc_acctimezone; Type: TABLE; Schema: public; Owner: postgres
--

CREATE TABLE public.acc_acctimezone (
    id integer NOT NULL,
    create_time timestamp with time zone,
    create_user character varying(150),
    change_time timestamp with time zone,
    change_user character varying(150),
    status smallint NOT NULL,
    timezone_no integer NOT NULL,
    timezone_name character varying(100) NOT NULL,
    sun_start time without time zone NOT NULL,
    sun_end time without time zone NOT NULL,
    sun_on smallint,
    mon_start time without time zone NOT NULL,
    mon_end time without time zone NOT NULL,
    mon_on smallint,
    tue_start time without time zone NOT NULL,
    tue_end time without time zone NOT NULL,
    tue_on smallint,
    wed_start time without time zone NOT NULL,
    wed_end time without time zone NOT NULL,
    wed_on smallint,
    thu_start time without time zone NOT NULL,
    thu_end time without time zone NOT NULL,
    thu_on smallint,
    fri_start time without time zone NOT NULL,
    fri_end time without time zone NOT NULL,
    fri_on smallint,
    sat_start time without time zone NOT NULL,
    sat_end time without time zone NOT NULL,
    sat_on smallint,
    remark character varying(999),
    update_time timestamp with time zone,
    area_id integer NOT NULL
);


ALTER TABLE public.acc_acctimezone OWNER TO postgres;

--
-- TOC entry 207 (class 1259 OID 27307)
-- Name: acc_acctimezone_id_seq; Type: SEQUENCE; Schema: public; Owner: postgres
--

CREATE SEQUENCE public.acc_acctimezone_id_seq
    AS integer
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;


ALTER SEQUENCE public.acc_acctimezone_id_seq OWNER TO postgres;

--
-- TOC entry 4721 (class 0 OID 0)
-- Dependencies: 207
-- Name: acc_acctimezone_id_seq; Type: SEQUENCE OWNED BY; Schema: public; Owner: postgres
--

ALTER SEQUENCE public.acc_acctimezone_id_seq OWNED BY public.acc_acctimezone.id;


--
-- TOC entry 208 (class 1259 OID 27309)
-- Name: accounts_adminbiodata; Type: TABLE; Schema: public; Owner: postgres
--

CREATE TABLE public.accounts_adminbiodata (
    id integer NOT NULL,
    create_time timestamp with time zone,
    create_user character varying(150),
    change_time timestamp with time zone,
    change_user character varying(150),
    status smallint NOT NULL,
    bio_tmp text NOT NULL,
    bio_no integer,
    bio_index integer,
    bio_type integer NOT NULL,
    major_ver character varying(30) NOT NULL,
    minor_ver character varying(30),
    bio_format integer,
    valid boolean NOT NULL,
    duress boolean NOT NULL,
    admin_id integer NOT NULL
);


ALTER TABLE public.accounts_adminbiodata OWNER TO postgres;

--
-- TOC entry 209 (class 1259 OID 27315)
-- Name: accounts_adminbiodata_id_seq; Type: SEQUENCE; Schema: public; Owner: postgres
--

CREATE SEQUENCE public.accounts_adminbiodata_id_seq
    AS integer
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;


ALTER SEQUENCE public.accounts_adminbiodata_id_seq OWNER TO postgres;

--
-- TOC entry 4722 (class 0 OID 0)
-- Dependencies: 209
-- Name: accounts_adminbiodata_id_seq; Type: SEQUENCE OWNED BY; Schema: public; Owner: postgres
--

ALTER SEQUENCE public.accounts_adminbiodata_id_seq OWNED BY public.accounts_adminbiodata.id;


--
-- TOC entry 210 (class 1259 OID 27317)
-- Name: accounts_usersecuritypolicy; Type: TABLE; Schema: public; Owner: postgres
--

CREATE TABLE public.accounts_usersecuritypolicy (
    id integer NOT NULL,
    account smallint NOT NULL,
    username character varying(50) NOT NULL,
    password_date date,
    password_expired smallint,
    unlock_time timestamp with time zone NOT NULL,
    session_key character varying(100)
);


ALTER TABLE public.accounts_usersecuritypolicy OWNER TO postgres;

--
-- TOC entry 211 (class 1259 OID 27320)
-- Name: accounts_usersecuritypolicy_id_seq; Type: SEQUENCE; Schema: public; Owner: postgres
--

CREATE SEQUENCE public.accounts_usersecuritypolicy_id_seq
    AS integer
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;


ALTER SEQUENCE public.accounts_usersecuritypolicy_id_seq OWNER TO postgres;

--
-- TOC entry 4723 (class 0 OID 0)
-- Dependencies: 211
-- Name: accounts_usersecuritypolicy_id_seq; Type: SEQUENCE OWNED BY; Schema: public; Owner: postgres
--

ALTER SEQUENCE public.accounts_usersecuritypolicy_id_seq OWNED BY public.accounts_usersecuritypolicy.id;


--
-- TOC entry 212 (class 1259 OID 27322)
-- Name: att_attcalclog; Type: TABLE; Schema: public; Owner: postgres
--

CREATE TABLE public.att_attcalclog (
    id integer NOT NULL,
    dept_id integer,
    emp_id integer,
    start_date timestamp with time zone NOT NULL,
    end_date timestamp with time zone NOT NULL,
    update_time timestamp with time zone NOT NULL,
    log_type integer NOT NULL
);


ALTER TABLE public.att_attcalclog OWNER TO postgres;

--
-- TOC entry 213 (class 1259 OID 27325)
-- Name: att_attcalclog_id_seq; Type: SEQUENCE; Schema: public; Owner: postgres
--

CREATE SEQUENCE public.att_attcalclog_id_seq
    AS integer
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;


ALTER SEQUENCE public.att_attcalclog_id_seq OWNER TO postgres;

--
-- TOC entry 4724 (class 0 OID 0)
-- Dependencies: 213
-- Name: att_attcalclog_id_seq; Type: SEQUENCE OWNED BY; Schema: public; Owner: postgres
--

ALTER SEQUENCE public.att_attcalclog_id_seq OWNED BY public.att_attcalclog.id;


--
-- TOC entry 214 (class 1259 OID 27327)
-- Name: att_attreportsetting; Type: TABLE; Schema: public; Owner: postgres
--

CREATE TABLE public.att_attreportsetting (
    id integer NOT NULL,
    resign_emp smallint NOT NULL,
    short_date smallint NOT NULL,
    short_time smallint NOT NULL,
    func_key text,
    att_item text
);


ALTER TABLE public.att_attreportsetting OWNER TO postgres;

--
-- TOC entry 215 (class 1259 OID 27333)
-- Name: att_attreportsetting_id_seq; Type: SEQUENCE; Schema: public; Owner: postgres
--

CREATE SEQUENCE public.att_attreportsetting_id_seq
    AS integer
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;


ALTER SEQUENCE public.att_attreportsetting_id_seq OWNER TO postgres;

--
-- TOC entry 4725 (class 0 OID 0)
-- Dependencies: 215
-- Name: att_attreportsetting_id_seq; Type: SEQUENCE OWNED BY; Schema: public; Owner: postgres
--

ALTER SEQUENCE public.att_attreportsetting_id_seq OWNED BY public.att_attreportsetting.id;


--
-- TOC entry 216 (class 1259 OID 27335)
-- Name: att_attrule; Type: TABLE; Schema: public; Owner: postgres
--

CREATE TABLE public.att_attrule (
    param_name character varying(20) NOT NULL,
    param_value text NOT NULL
);


ALTER TABLE public.att_attrule OWNER TO postgres;

--
-- TOC entry 217 (class 1259 OID 27341)
-- Name: att_attschedule; Type: TABLE; Schema: public; Owner: postgres
--

CREATE TABLE public.att_attschedule (
    id integer NOT NULL,
    start_date date NOT NULL,
    end_date date NOT NULL,
    employee_id integer NOT NULL,
    shift_id integer NOT NULL
);


ALTER TABLE public.att_attschedule OWNER TO postgres;

--
-- TOC entry 218 (class 1259 OID 27344)
-- Name: att_attschedule_id_seq; Type: SEQUENCE; Schema: public; Owner: postgres
--

CREATE SEQUENCE public.att_attschedule_id_seq
    AS integer
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;


ALTER SEQUENCE public.att_attschedule_id_seq OWNER TO postgres;

--
-- TOC entry 4726 (class 0 OID 0)
-- Dependencies: 218
-- Name: att_attschedule_id_seq; Type: SEQUENCE OWNED BY; Schema: public; Owner: postgres
--

ALTER SEQUENCE public.att_attschedule_id_seq OWNED BY public.att_attschedule.id;


--
-- TOC entry 219 (class 1259 OID 27346)
-- Name: att_attshift; Type: TABLE; Schema: public; Owner: postgres
--

CREATE TABLE public.att_attshift (
    id integer NOT NULL,
    create_time timestamp with time zone,
    create_user character varying(150),
    change_time timestamp with time zone,
    change_user character varying(150),
    status smallint NOT NULL,
    alias character varying(50) NOT NULL,
    cycle_unit smallint NOT NULL,
    shift_cycle integer NOT NULL,
    work_weekend boolean NOT NULL,
    weekend_type smallint NOT NULL,
    work_day_off boolean NOT NULL,
    day_off_type smallint NOT NULL,
    auto_shift boolean NOT NULL,
    company_id integer
);


ALTER TABLE public.att_attshift OWNER TO postgres;

--
-- TOC entry 220 (class 1259 OID 27349)
-- Name: att_attshift_id_seq; Type: SEQUENCE; Schema: public; Owner: postgres
--

CREATE SEQUENCE public.att_attshift_id_seq
    AS integer
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;


ALTER SEQUENCE public.att_attshift_id_seq OWNER TO postgres;

--
-- TOC entry 4727 (class 0 OID 0)
-- Dependencies: 220
-- Name: att_attshift_id_seq; Type: SEQUENCE OWNED BY; Schema: public; Owner: postgres
--

ALTER SEQUENCE public.att_attshift_id_seq OWNED BY public.att_attshift.id;


--
-- TOC entry 221 (class 1259 OID 27351)
-- Name: att_breaktime; Type: TABLE; Schema: public; Owner: postgres
--

CREATE TABLE public.att_breaktime (
    id integer NOT NULL,
    create_time timestamp with time zone,
    create_user character varying(150),
    change_time timestamp with time zone,
    change_user character varying(150),
    status smallint NOT NULL,
    alias character varying(50) NOT NULL,
    period_start time without time zone NOT NULL,
    duration integer NOT NULL,
    end_margin integer NOT NULL,
    func_key smallint NOT NULL,
    available_interval_type smallint NOT NULL,
    available_interval integer NOT NULL,
    multiple_punch smallint NOT NULL,
    calc_type smallint NOT NULL,
    minimum_duration integer,
    early_in smallint NOT NULL,
    min_early_in integer NOT NULL,
    late_in smallint NOT NULL,
    min_late_in integer NOT NULL,
    company_id integer
);


ALTER TABLE public.att_breaktime OWNER TO postgres;

--
-- TOC entry 222 (class 1259 OID 27354)
-- Name: att_breaktime_id_seq; Type: SEQUENCE; Schema: public; Owner: postgres
--

CREATE SEQUENCE public.att_breaktime_id_seq
    AS integer
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;


ALTER SEQUENCE public.att_breaktime_id_seq OWNER TO postgres;

--
-- TOC entry 4728 (class 0 OID 0)
-- Dependencies: 222
-- Name: att_breaktime_id_seq; Type: SEQUENCE OWNED BY; Schema: public; Owner: postgres
--

ALTER SEQUENCE public.att_breaktime_id_seq OWNED BY public.att_breaktime.id;


--
-- TOC entry 223 (class 1259 OID 27356)
-- Name: att_changeschedule; Type: TABLE; Schema: public; Owner: postgres
--

CREATE TABLE public.att_changeschedule (
    abstractexception_ptr_id integer NOT NULL,
    att_date date NOT NULL,
    previous_timeinterval character varying(100),
    apply_time timestamp with time zone NOT NULL,
    apply_reason character varying(200),
    audit_reason text,
    audit_time timestamp with time zone NOT NULL,
    approver character varying(50),
    employee_id integer NOT NULL,
    timeinterval_id integer NOT NULL
);


ALTER TABLE public.att_changeschedule OWNER TO postgres;

--
-- TOC entry 224 (class 1259 OID 27362)
-- Name: att_departmentschedule; Type: TABLE; Schema: public; Owner: postgres
--

CREATE TABLE public.att_departmentschedule (
    id integer NOT NULL,
    create_time timestamp with time zone,
    create_user character varying(150),
    change_time timestamp with time zone,
    change_user character varying(150),
    status smallint NOT NULL,
    start_date date NOT NULL,
    end_date date NOT NULL,
    department_id integer NOT NULL,
    shift_id integer NOT NULL
);


ALTER TABLE public.att_departmentschedule OWNER TO postgres;

--
-- TOC entry 225 (class 1259 OID 27365)
-- Name: att_departmentschedule_id_seq; Type: SEQUENCE; Schema: public; Owner: postgres
--

CREATE SEQUENCE public.att_departmentschedule_id_seq
    AS integer
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;


ALTER SEQUENCE public.att_departmentschedule_id_seq OWNER TO postgres;

--
-- TOC entry 4729 (class 0 OID 0)
-- Dependencies: 225
-- Name: att_departmentschedule_id_seq; Type: SEQUENCE OWNED BY; Schema: public; Owner: postgres
--

ALTER SEQUENCE public.att_departmentschedule_id_seq OWNED BY public.att_departmentschedule.id;


--
-- TOC entry 226 (class 1259 OID 27367)
-- Name: att_deptattrule; Type: TABLE; Schema: public; Owner: postgres
--

CREATE TABLE public.att_deptattrule (
    id integer NOT NULL,
    create_time timestamp with time zone,
    create_user character varying(150),
    change_time timestamp with time zone,
    change_user character varying(150),
    status smallint NOT NULL,
    alias character varying(50) NOT NULL,
    rule text,
    company_id integer,
    department_id integer NOT NULL
);


ALTER TABLE public.att_deptattrule OWNER TO postgres;

--
-- TOC entry 227 (class 1259 OID 27373)
-- Name: att_deptattrule_id_seq; Type: SEQUENCE; Schema: public; Owner: postgres
--

CREATE SEQUENCE public.att_deptattrule_id_seq
    AS integer
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;


ALTER SEQUENCE public.att_deptattrule_id_seq OWNER TO postgres;

--
-- TOC entry 4730 (class 0 OID 0)
-- Dependencies: 227
-- Name: att_deptattrule_id_seq; Type: SEQUENCE OWNED BY; Schema: public; Owner: postgres
--

ALTER SEQUENCE public.att_deptattrule_id_seq OWNED BY public.att_deptattrule.id;


--
-- TOC entry 228 (class 1259 OID 27375)
-- Name: att_holiday; Type: TABLE; Schema: public; Owner: postgres
--

CREATE TABLE public.att_holiday (
    id integer NOT NULL,
    alias character varying(50) NOT NULL,
    start_date date NOT NULL,
    duration_day smallint NOT NULL,
    work_type smallint NOT NULL,
    overtime_lv1 smallint NOT NULL,
    overtime_lv2 smallint NOT NULL,
    overtime_lv3 smallint NOT NULL,
    department_id integer
);


ALTER TABLE public.att_holiday OWNER TO postgres;

--
-- TOC entry 229 (class 1259 OID 27378)
-- Name: att_holiday_id_seq; Type: SEQUENCE; Schema: public; Owner: postgres
--

CREATE SEQUENCE public.att_holiday_id_seq
    AS integer
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;


ALTER SEQUENCE public.att_holiday_id_seq OWNER TO postgres;

--
-- TOC entry 4731 (class 0 OID 0)
-- Dependencies: 229
-- Name: att_holiday_id_seq; Type: SEQUENCE OWNED BY; Schema: public; Owner: postgres
--

ALTER SEQUENCE public.att_holiday_id_seq OWNED BY public.att_holiday.id;


--
-- TOC entry 230 (class 1259 OID 27380)
-- Name: att_leave; Type: TABLE; Schema: public; Owner: postgres
--

CREATE TABLE public.att_leave (
    abstractexception_ptr_id integer NOT NULL,
    start_time timestamp with time zone NOT NULL,
    end_time timestamp with time zone NOT NULL,
    type smallint NOT NULL,
    apply_reason text,
    apply_time timestamp with time zone NOT NULL,
    audit_reason text,
    audit_time timestamp with time zone NOT NULL,
    approval_level smallint,
    audit_user_id integer,
    approver character varying(50),
    vacation_number smallint NOT NULL,
    attachment character varying(100),
    category_id integer NOT NULL,
    employee_id integer NOT NULL
);


ALTER TABLE public.att_leave OWNER TO postgres;

--
-- TOC entry 231 (class 1259 OID 27386)
-- Name: att_leavecategory; Type: TABLE; Schema: public; Owner: postgres
--

CREATE TABLE public.att_leavecategory (
    id integer NOT NULL,
    category_name character varying(50) NOT NULL,
    minimum_unit double precision NOT NULL,
    unit smallint NOT NULL,
    round_off smallint NOT NULL,
    report_symbol character varying(5) NOT NULL,
    leave_category_type smallint NOT NULL
);


ALTER TABLE public.att_leavecategory OWNER TO postgres;

--
-- TOC entry 232 (class 1259 OID 27389)
-- Name: att_leavecategory_id_seq; Type: SEQUENCE; Schema: public; Owner: postgres
--

CREATE SEQUENCE public.att_leavecategory_id_seq
    AS integer
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;


ALTER SEQUENCE public.att_leavecategory_id_seq OWNER TO postgres;

--
-- TOC entry 4732 (class 0 OID 0)
-- Dependencies: 232
-- Name: att_leavecategory_id_seq; Type: SEQUENCE OWNED BY; Schema: public; Owner: postgres
--

ALTER SEQUENCE public.att_leavecategory_id_seq OWNED BY public.att_leavecategory.id;


--
-- TOC entry 233 (class 1259 OID 27391)
-- Name: att_manuallog; Type: TABLE; Schema: public; Owner: postgres
--

CREATE TABLE public.att_manuallog (
    abstractexception_ptr_id integer NOT NULL,
    punch_time timestamp with time zone NOT NULL,
    punch_state integer NOT NULL,
    work_code character varying(20),
    temperature numeric(4,1),
    is_mask boolean NOT NULL,
    apply_reason text,
    apply_time timestamp with time zone NOT NULL,
    audit_reason text,
    audit_time timestamp with time zone NOT NULL,
    approval_level smallint,
    audit_user_id integer,
    approver character varying(50),
    attachment character varying(100),
    employee_id integer NOT NULL
);


ALTER TABLE public.att_manuallog OWNER TO postgres;

--
-- TOC entry 234 (class 1259 OID 27397)
-- Name: att_overtime; Type: TABLE; Schema: public; Owner: postgres
--

CREATE TABLE public.att_overtime (
    abstractexception_ptr_id integer NOT NULL,
    overtime_type smallint NOT NULL,
    start_time timestamp with time zone NOT NULL,
    end_time timestamp with time zone NOT NULL,
    apply_reason text,
    apply_time timestamp with time zone NOT NULL,
    audit_reason text,
    audit_time timestamp with time zone NOT NULL,
    approval_level smallint,
    audit_user_id integer,
    approver character varying(50),
    attachment character varying(100),
    employee_id integer NOT NULL
);


ALTER TABLE public.att_overtime OWNER TO postgres;

--
-- TOC entry 235 (class 1259 OID 27403)
-- Name: att_payloadbase; Type: TABLE; Schema: public; Owner: postgres
--

CREATE TABLE public.att_payloadbase (
    uuid character varying(36) NOT NULL,
    att_date date,
    weekday smallint,
    check_in timestamp with time zone,
    check_out timestamp with time zone,
    duration integer,
    duty_duration integer,
    work_day double precision NOT NULL,
    clock_in timestamp with time zone,
    clock_out timestamp with time zone,
    total_time integer,
    duty_worked integer,
    actual_worked integer,
    unscheduled integer,
    remaining integer,
    total_worked integer,
    late integer,
    early_leave integer,
    short integer,
    absent integer,
    leave integer,
    exception character varying(50),
    day_off smallint NOT NULL,
    break_time_id character varying(36),
    emp_id integer NOT NULL,
    overtime_id character varying(36),
    timetable_id integer,
    trans_in_id integer,
    trans_out_id integer
);


ALTER TABLE public.att_payloadbase OWNER TO postgres;

--
-- TOC entry 236 (class 1259 OID 27406)
-- Name: att_payloadbreak; Type: TABLE; Schema: public; Owner: postgres
--

CREATE TABLE public.att_payloadbreak (
    uuid character varying(36) NOT NULL,
    break_out timestamp with time zone,
    break_in timestamp with time zone,
    duration integer,
    taken integer,
    actual_duration integer,
    early_in integer,
    late_in integer,
    late integer,
    early_leave integer,
    absent integer,
    work_time integer,
    overtime integer,
    weekend_ot integer,
    holiday_ot integer
);


ALTER TABLE public.att_payloadbreak OWNER TO postgres;

--
-- TOC entry 237 (class 1259 OID 27409)
-- Name: att_payloadexception; Type: TABLE; Schema: public; Owner: postgres
--

CREATE TABLE public.att_payloadexception (
    uuid character varying(36) NOT NULL,
    start_time timestamp with time zone NOT NULL,
    end_time timestamp with time zone NOT NULL,
    duration integer,
    days double precision,
    data_type smallint NOT NULL,
    description character varying(50),
    item_id integer,
    skd_id character varying(36)
);


ALTER TABLE public.att_payloadexception OWNER TO postgres;

--
-- TOC entry 238 (class 1259 OID 27412)
-- Name: att_payloadmulpunchset; Type: TABLE; Schema: public; Owner: postgres
--

CREATE TABLE public.att_payloadmulpunchset (
    id integer NOT NULL,
    att_date date NOT NULL,
    weekday smallint,
    data_index smallint NOT NULL,
    clock_in timestamp with time zone,
    in_id integer,
    clock_out timestamp with time zone,
    out_id integer,
    total_time integer,
    worked_time integer,
    data_type smallint NOT NULL,
    emp_id integer NOT NULL,
    timetable_id integer
);


ALTER TABLE public.att_payloadmulpunchset OWNER TO postgres;

--
-- TOC entry 239 (class 1259 OID 27415)
-- Name: att_payloadmulpunchset_id_seq; Type: SEQUENCE; Schema: public; Owner: postgres
--

CREATE SEQUENCE public.att_payloadmulpunchset_id_seq
    AS integer
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;


ALTER SEQUENCE public.att_payloadmulpunchset_id_seq OWNER TO postgres;

--
-- TOC entry 4733 (class 0 OID 0)
-- Dependencies: 239
-- Name: att_payloadmulpunchset_id_seq; Type: SEQUENCE OWNED BY; Schema: public; Owner: postgres
--

ALTER SEQUENCE public.att_payloadmulpunchset_id_seq OWNED BY public.att_payloadmulpunchset.id;


--
-- TOC entry 240 (class 1259 OID 27417)
-- Name: att_payloadovertime; Type: TABLE; Schema: public; Owner: postgres
--

CREATE TABLE public.att_payloadovertime (
    uuid character varying(36) NOT NULL,
    normal_wt integer,
    normal_ot integer,
    weekend_ot integer,
    holiday_ot integer,
    dayoff_ot integer,
    ot_lv1 integer,
    ot_lv2 integer,
    ot_lv3 integer,
    total_ot integer
);


ALTER TABLE public.att_payloadovertime OWNER TO postgres;

--
-- TOC entry 241 (class 1259 OID 27420)
-- Name: att_payloadpunch; Type: TABLE; Schema: public; Owner: postgres
--

CREATE TABLE public.att_payloadpunch (
    uuid character varying(36) NOT NULL,
    att_date date,
    correct_state character varying(3),
    emp_id integer NOT NULL,
    orig_id integer,
    skd_id character varying(36)
);


ALTER TABLE public.att_payloadpunch OWNER TO postgres;

--
-- TOC entry 242 (class 1259 OID 27423)
-- Name: att_reportparam; Type: TABLE; Schema: public; Owner: postgres
--

CREATE TABLE public.att_reportparam (
    param_name character varying(20) NOT NULL,
    param_value text NOT NULL
);


ALTER TABLE public.att_reportparam OWNER TO postgres;

--
-- TOC entry 243 (class 1259 OID 27429)
-- Name: att_shiftdetail; Type: TABLE; Schema: public; Owner: postgres
--

CREATE TABLE public.att_shiftdetail (
    id integer NOT NULL,
    in_time time without time zone NOT NULL,
    out_time time without time zone NOT NULL,
    day_index integer NOT NULL,
    shift_id integer NOT NULL,
    time_interval_id integer NOT NULL
);


ALTER TABLE public.att_shiftdetail OWNER TO postgres;

--
-- TOC entry 244 (class 1259 OID 27432)
-- Name: att_shiftdetail_id_seq; Type: SEQUENCE; Schema: public; Owner: postgres
--

CREATE SEQUENCE public.att_shiftdetail_id_seq
    AS integer
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;


ALTER SEQUENCE public.att_shiftdetail_id_seq OWNER TO postgres;

--
-- TOC entry 4734 (class 0 OID 0)
-- Dependencies: 244
-- Name: att_shiftdetail_id_seq; Type: SEQUENCE OWNED BY; Schema: public; Owner: postgres
--

ALTER SEQUENCE public.att_shiftdetail_id_seq OWNED BY public.att_shiftdetail.id;


--
-- TOC entry 245 (class 1259 OID 27434)
-- Name: att_tempschedule; Type: TABLE; Schema: public; Owner: postgres
--

CREATE TABLE public.att_tempschedule (
    id integer NOT NULL,
    start_time timestamp with time zone NOT NULL,
    end_time timestamp with time zone NOT NULL,
    rule_flag smallint NOT NULL,
    work_type smallint NOT NULL,
    employee_id integer NOT NULL,
    time_interval_id integer
);


ALTER TABLE public.att_tempschedule OWNER TO postgres;

--
-- TOC entry 246 (class 1259 OID 27437)
-- Name: att_tempschedule_id_seq; Type: SEQUENCE; Schema: public; Owner: postgres
--

CREATE SEQUENCE public.att_tempschedule_id_seq
    AS integer
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;


ALTER SEQUENCE public.att_tempschedule_id_seq OWNER TO postgres;

--
-- TOC entry 4735 (class 0 OID 0)
-- Dependencies: 246
-- Name: att_tempschedule_id_seq; Type: SEQUENCE OWNED BY; Schema: public; Owner: postgres
--

ALTER SEQUENCE public.att_tempschedule_id_seq OWNED BY public.att_tempschedule.id;


--
-- TOC entry 247 (class 1259 OID 27439)
-- Name: att_timeinterval; Type: TABLE; Schema: public; Owner: postgres
--

CREATE TABLE public.att_timeinterval (
    id integer NOT NULL,
    create_time timestamp with time zone,
    create_user character varying(150),
    change_time timestamp with time zone,
    change_user character varying(150),
    status smallint NOT NULL,
    alias character varying(50) NOT NULL,
    use_mode smallint NOT NULL,
    in_time time without time zone NOT NULL,
    in_ahead_margin integer NOT NULL,
    in_above_margin integer NOT NULL,
    out_ahead_margin integer NOT NULL,
    out_above_margin integer NOT NULL,
    duration integer NOT NULL,
    in_required smallint NOT NULL,
    out_required smallint NOT NULL,
    allow_late integer NOT NULL,
    allow_leave_early integer NOT NULL,
    work_day double precision NOT NULL,
    early_in smallint NOT NULL,
    min_early_in integer NOT NULL,
    late_out smallint NOT NULL,
    min_late_out integer NOT NULL,
    overtime_lv smallint NOT NULL,
    overtime_lv1 smallint NOT NULL,
    overtime_lv2 smallint NOT NULL,
    overtime_lv3 smallint NOT NULL,
    multiple_punch smallint NOT NULL,
    available_interval_type smallint NOT NULL,
    available_interval integer NOT NULL,
    work_time_duration integer NOT NULL,
    func_key smallint NOT NULL,
    work_type smallint NOT NULL,
    day_change time without time zone NOT NULL,
    use_24_mode smallint NOT NULL,
    company_id integer
);


ALTER TABLE public.att_timeinterval OWNER TO postgres;

--
-- TOC entry 248 (class 1259 OID 27442)
-- Name: att_timeinterval_break_time; Type: TABLE; Schema: public; Owner: postgres
--

CREATE TABLE public.att_timeinterval_break_time (
    id integer NOT NULL,
    timeinterval_id integer NOT NULL,
    breaktime_id integer NOT NULL
);


ALTER TABLE public.att_timeinterval_break_time OWNER TO postgres;

--
-- TOC entry 249 (class 1259 OID 27445)
-- Name: att_timeinterval_break_time_id_seq; Type: SEQUENCE; Schema: public; Owner: postgres
--

CREATE SEQUENCE public.att_timeinterval_break_time_id_seq
    AS integer
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;


ALTER SEQUENCE public.att_timeinterval_break_time_id_seq OWNER TO postgres;

--
-- TOC entry 4736 (class 0 OID 0)
-- Dependencies: 249
-- Name: att_timeinterval_break_time_id_seq; Type: SEQUENCE OWNED BY; Schema: public; Owner: postgres
--

ALTER SEQUENCE public.att_timeinterval_break_time_id_seq OWNED BY public.att_timeinterval_break_time.id;


--
-- TOC entry 250 (class 1259 OID 27447)
-- Name: att_timeinterval_id_seq; Type: SEQUENCE; Schema: public; Owner: postgres
--

CREATE SEQUENCE public.att_timeinterval_id_seq
    AS integer
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;


ALTER SEQUENCE public.att_timeinterval_id_seq OWNER TO postgres;

--
-- TOC entry 4737 (class 0 OID 0)
-- Dependencies: 250
-- Name: att_timeinterval_id_seq; Type: SEQUENCE OWNED BY; Schema: public; Owner: postgres
--

ALTER SEQUENCE public.att_timeinterval_id_seq OWNED BY public.att_timeinterval.id;


--
-- TOC entry 251 (class 1259 OID 27449)
-- Name: att_training; Type: TABLE; Schema: public; Owner: postgres
--

CREATE TABLE public.att_training (
    abstractexception_ptr_id integer NOT NULL,
    start_time timestamp with time zone NOT NULL,
    end_time timestamp with time zone NOT NULL,
    apply_reason text,
    apply_time timestamp with time zone NOT NULL,
    audit_reason text,
    audit_time timestamp with time zone NOT NULL,
    approval_level smallint,
    audit_user_id integer,
    approver character varying(50),
    attachment character varying(100),
    category_id integer NOT NULL,
    employee_id integer NOT NULL
);


ALTER TABLE public.att_training OWNER TO postgres;

--
-- TOC entry 252 (class 1259 OID 27455)
-- Name: att_trainingcategory; Type: TABLE; Schema: public; Owner: postgres
--

CREATE TABLE public.att_trainingcategory (
    id integer NOT NULL,
    category_name character varying(50) NOT NULL,
    minimum_unit double precision NOT NULL,
    unit smallint NOT NULL,
    round_off smallint NOT NULL,
    report_symbol character varying(5) NOT NULL
);


ALTER TABLE public.att_trainingcategory OWNER TO postgres;

--
-- TOC entry 253 (class 1259 OID 27458)
-- Name: att_trainingcategory_id_seq; Type: SEQUENCE; Schema: public; Owner: postgres
--

CREATE SEQUENCE public.att_trainingcategory_id_seq
    AS integer
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;


ALTER SEQUENCE public.att_trainingcategory_id_seq OWNER TO postgres;

--
-- TOC entry 4738 (class 0 OID 0)
-- Dependencies: 253
-- Name: att_trainingcategory_id_seq; Type: SEQUENCE OWNED BY; Schema: public; Owner: postgres
--

ALTER SEQUENCE public.att_trainingcategory_id_seq OWNED BY public.att_trainingcategory.id;


--
-- TOC entry 254 (class 1259 OID 27460)
-- Name: att_vacationemployee; Type: TABLE; Schema: public; Owner: postgres
--

CREATE TABLE public.att_vacationemployee (
    id integer NOT NULL,
    days_left smallint NOT NULL,
    start_time timestamp with time zone NOT NULL,
    end_time timestamp with time zone NOT NULL,
    employee_id integer NOT NULL,
    leave_id integer NOT NULL,
    vacation_available_id integer NOT NULL
);


ALTER TABLE public.att_vacationemployee OWNER TO postgres;

--
-- TOC entry 255 (class 1259 OID 27463)
-- Name: att_vacationemployee_id_seq; Type: SEQUENCE; Schema: public; Owner: postgres
--

CREATE SEQUENCE public.att_vacationemployee_id_seq
    AS integer
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;


ALTER SEQUENCE public.att_vacationemployee_id_seq OWNER TO postgres;

--
-- TOC entry 4739 (class 0 OID 0)
-- Dependencies: 255
-- Name: att_vacationemployee_id_seq; Type: SEQUENCE OWNED BY; Schema: public; Owner: postgres
--

ALTER SEQUENCE public.att_vacationemployee_id_seq OWNED BY public.att_vacationemployee.id;


--
-- TOC entry 256 (class 1259 OID 27465)
-- Name: att_vacationtime; Type: TABLE; Schema: public; Owner: postgres
--

CREATE TABLE public.att_vacationtime (
    id integer NOT NULL,
    create_time timestamp with time zone,
    create_user character varying(150),
    change_time timestamp with time zone,
    change_user character varying(150),
    status smallint NOT NULL,
    category_code character varying(30) NOT NULL,
    category_name character varying(50) NOT NULL,
    company_id integer
);


ALTER TABLE public.att_vacationtime OWNER TO postgres;

--
-- TOC entry 257 (class 1259 OID 27468)
-- Name: att_vacationtime_id_seq; Type: SEQUENCE; Schema: public; Owner: postgres
--

CREATE SEQUENCE public.att_vacationtime_id_seq
    AS integer
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;


ALTER SEQUENCE public.att_vacationtime_id_seq OWNER TO postgres;

--
-- TOC entry 4740 (class 0 OID 0)
-- Dependencies: 257
-- Name: att_vacationtime_id_seq; Type: SEQUENCE OWNED BY; Schema: public; Owner: postgres
--

ALTER SEQUENCE public.att_vacationtime_id_seq OWNED BY public.att_vacationtime.id;


--
-- TOC entry 258 (class 1259 OID 27470)
-- Name: att_vacationtimeseniority; Type: TABLE; Schema: public; Owner: postgres
--

CREATE TABLE public.att_vacationtimeseniority (
    id integer NOT NULL,
    seniority smallint NOT NULL,
    days smallint,
    vacation_time_id integer NOT NULL
);


ALTER TABLE public.att_vacationtimeseniority OWNER TO postgres;

--
-- TOC entry 259 (class 1259 OID 27473)
-- Name: att_vacationtimeseniority_id_seq; Type: SEQUENCE; Schema: public; Owner: postgres
--

CREATE SEQUENCE public.att_vacationtimeseniority_id_seq
    AS integer
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;


ALTER SEQUENCE public.att_vacationtimeseniority_id_seq OWNER TO postgres;

--
-- TOC entry 4741 (class 0 OID 0)
-- Dependencies: 259
-- Name: att_vacationtimeseniority_id_seq; Type: SEQUENCE OWNED BY; Schema: public; Owner: postgres
--

ALTER SEQUENCE public.att_vacationtimeseniority_id_seq OWNED BY public.att_vacationtimeseniority.id;


--
-- TOC entry 260 (class 1259 OID 27475)
-- Name: attparam; Type: TABLE; Schema: public; Owner: postgres
--

CREATE TABLE public.attparam (
    id integer NOT NULL,
    paraname character varying(30) NOT NULL,
    paratype character varying(10),
    paravalue character varying(250)
);


ALTER TABLE public.attparam OWNER TO postgres;

--
-- TOC entry 261 (class 1259 OID 27478)
-- Name: attparam_id_seq; Type: SEQUENCE; Schema: public; Owner: postgres
--

CREATE SEQUENCE public.attparam_id_seq
    AS integer
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;


ALTER SEQUENCE public.attparam_id_seq OWNER TO postgres;

--
-- TOC entry 4742 (class 0 OID 0)
-- Dependencies: 261
-- Name: attparam_id_seq; Type: SEQUENCE OWNED BY; Schema: public; Owner: postgres
--

ALTER SEQUENCE public.attparam_id_seq OWNED BY public.attparam.id;


--
-- TOC entry 262 (class 1259 OID 27480)
-- Name: auth_group; Type: TABLE; Schema: public; Owner: postgres
--

CREATE TABLE public.auth_group (
    id integer NOT NULL,
    name character varying(80) NOT NULL
);


ALTER TABLE public.auth_group OWNER TO postgres;

--
-- TOC entry 263 (class 1259 OID 27483)
-- Name: auth_group_id_seq; Type: SEQUENCE; Schema: public; Owner: postgres
--

CREATE SEQUENCE public.auth_group_id_seq
    AS integer
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;


ALTER SEQUENCE public.auth_group_id_seq OWNER TO postgres;

--
-- TOC entry 4743 (class 0 OID 0)
-- Dependencies: 263
-- Name: auth_group_id_seq; Type: SEQUENCE OWNED BY; Schema: public; Owner: postgres
--

ALTER SEQUENCE public.auth_group_id_seq OWNED BY public.auth_group.id;


--
-- TOC entry 264 (class 1259 OID 27485)
-- Name: auth_group_permissions; Type: TABLE; Schema: public; Owner: postgres
--

CREATE TABLE public.auth_group_permissions (
    id integer NOT NULL,
    group_id integer NOT NULL,
    permission_id integer NOT NULL
);


ALTER TABLE public.auth_group_permissions OWNER TO postgres;

--
-- TOC entry 265 (class 1259 OID 27488)
-- Name: auth_group_permissions_id_seq; Type: SEQUENCE; Schema: public; Owner: postgres
--

CREATE SEQUENCE public.auth_group_permissions_id_seq
    AS integer
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;


ALTER SEQUENCE public.auth_group_permissions_id_seq OWNER TO postgres;

--
-- TOC entry 4744 (class 0 OID 0)
-- Dependencies: 265
-- Name: auth_group_permissions_id_seq; Type: SEQUENCE OWNED BY; Schema: public; Owner: postgres
--

ALTER SEQUENCE public.auth_group_permissions_id_seq OWNED BY public.auth_group_permissions.id;


--
-- TOC entry 266 (class 1259 OID 27490)
-- Name: auth_permission; Type: TABLE; Schema: public; Owner: postgres
--

CREATE TABLE public.auth_permission (
    id integer NOT NULL,
    name character varying(255) NOT NULL,
    content_type_id integer NOT NULL,
    codename character varying(100) NOT NULL
);


ALTER TABLE public.auth_permission OWNER TO postgres;

--
-- TOC entry 267 (class 1259 OID 27493)
-- Name: auth_permission_id_seq; Type: SEQUENCE; Schema: public; Owner: postgres
--

CREATE SEQUENCE public.auth_permission_id_seq
    AS integer
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;


ALTER SEQUENCE public.auth_permission_id_seq OWNER TO postgres;

--
-- TOC entry 4745 (class 0 OID 0)
-- Dependencies: 267
-- Name: auth_permission_id_seq; Type: SEQUENCE OWNED BY; Schema: public; Owner: postgres
--

ALTER SEQUENCE public.auth_permission_id_seq OWNED BY public.auth_permission.id;


--
-- TOC entry 268 (class 1259 OID 27495)
-- Name: auth_user; Type: TABLE; Schema: public; Owner: postgres
--

CREATE TABLE public.auth_user (
    id integer NOT NULL,
    username character varying(30) NOT NULL,
    password character varying(128) NOT NULL,
    update_time timestamp with time zone,
    first_name character varying(30) NOT NULL,
    last_name character varying(30) NOT NULL,
    emp_pin character varying(30),
    email character varying(254) NOT NULL,
    tele_phone character varying(30),
    auth_time_dept integer,
    login_id integer,
    login_type integer,
    login_count integer,
    is_staff boolean NOT NULL,
    is_active boolean NOT NULL,
    is_superuser boolean NOT NULL,
    is_public boolean NOT NULL,
    can_manage_all_dept boolean NOT NULL,
    del_flag integer,
    date_joined timestamp with time zone NOT NULL,
    last_login timestamp with time zone,
    auth_company_id integer,
    is_test boolean DEFAULT false NOT NULL
);


ALTER TABLE public.auth_user OWNER TO postgres;

--
-- TOC entry 269 (class 1259 OID 27501)
-- Name: auth_user_auth_area; Type: TABLE; Schema: public; Owner: postgres
--

CREATE TABLE public.auth_user_auth_area (
    id integer NOT NULL,
    myuser_id integer NOT NULL,
    area_id integer NOT NULL
);


ALTER TABLE public.auth_user_auth_area OWNER TO postgres;

--
-- TOC entry 270 (class 1259 OID 27504)
-- Name: auth_user_auth_area_id_seq; Type: SEQUENCE; Schema: public; Owner: postgres
--

CREATE SEQUENCE public.auth_user_auth_area_id_seq
    AS integer
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;


ALTER SEQUENCE public.auth_user_auth_area_id_seq OWNER TO postgres;

--
-- TOC entry 4746 (class 0 OID 0)
-- Dependencies: 270
-- Name: auth_user_auth_area_id_seq; Type: SEQUENCE OWNED BY; Schema: public; Owner: postgres
--

ALTER SEQUENCE public.auth_user_auth_area_id_seq OWNED BY public.auth_user_auth_area.id;


--
-- TOC entry 271 (class 1259 OID 27506)
-- Name: auth_user_auth_dept; Type: TABLE; Schema: public; Owner: postgres
--

CREATE TABLE public.auth_user_auth_dept (
    id integer NOT NULL,
    myuser_id integer NOT NULL,
    department_id integer NOT NULL
);


ALTER TABLE public.auth_user_auth_dept OWNER TO postgres;

--
-- TOC entry 272 (class 1259 OID 27509)
-- Name: auth_user_auth_dept_id_seq; Type: SEQUENCE; Schema: public; Owner: postgres
--

CREATE SEQUENCE public.auth_user_auth_dept_id_seq
    AS integer
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;


ALTER SEQUENCE public.auth_user_auth_dept_id_seq OWNER TO postgres;

--
-- TOC entry 4747 (class 0 OID 0)
-- Dependencies: 272
-- Name: auth_user_auth_dept_id_seq; Type: SEQUENCE OWNED BY; Schema: public; Owner: postgres
--

ALTER SEQUENCE public.auth_user_auth_dept_id_seq OWNED BY public.auth_user_auth_dept.id;


--
-- TOC entry 273 (class 1259 OID 27511)
-- Name: auth_user_groups; Type: TABLE; Schema: public; Owner: postgres
--

CREATE TABLE public.auth_user_groups (
    id integer NOT NULL,
    myuser_id integer NOT NULL,
    group_id integer NOT NULL
);


ALTER TABLE public.auth_user_groups OWNER TO postgres;

--
-- TOC entry 274 (class 1259 OID 27514)
-- Name: auth_user_groups_id_seq; Type: SEQUENCE; Schema: public; Owner: postgres
--

CREATE SEQUENCE public.auth_user_groups_id_seq
    AS integer
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;


ALTER SEQUENCE public.auth_user_groups_id_seq OWNER TO postgres;

--
-- TOC entry 4748 (class 0 OID 0)
-- Dependencies: 274
-- Name: auth_user_groups_id_seq; Type: SEQUENCE OWNED BY; Schema: public; Owner: postgres
--

ALTER SEQUENCE public.auth_user_groups_id_seq OWNED BY public.auth_user_groups.id;


--
-- TOC entry 275 (class 1259 OID 27516)
-- Name: auth_user_id_seq; Type: SEQUENCE; Schema: public; Owner: postgres
--

CREATE SEQUENCE public.auth_user_id_seq
    AS integer
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;


ALTER SEQUENCE public.auth_user_id_seq OWNER TO postgres;

--
-- TOC entry 4749 (class 0 OID 0)
-- Dependencies: 275
-- Name: auth_user_id_seq; Type: SEQUENCE OWNED BY; Schema: public; Owner: postgres
--

ALTER SEQUENCE public.auth_user_id_seq OWNED BY public.auth_user.id;


--
-- TOC entry 276 (class 1259 OID 27518)
-- Name: auth_user_profile; Type: TABLE; Schema: public; Owner: postgres
--

CREATE TABLE public.auth_user_profile (
    id integer NOT NULL,
    login_name character varying(30) NOT NULL,
    pin_tabs text NOT NULL,
    disabled_fields text NOT NULL,
    column_order text NOT NULL,
    preferences text NOT NULL,
    pwd_update_time timestamp with time zone,
    user_id integer NOT NULL
);


ALTER TABLE public.auth_user_profile OWNER TO postgres;

--
-- TOC entry 277 (class 1259 OID 27524)
-- Name: auth_user_profile_id_seq; Type: SEQUENCE; Schema: public; Owner: postgres
--

CREATE SEQUENCE public.auth_user_profile_id_seq
    AS integer
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;


ALTER SEQUENCE public.auth_user_profile_id_seq OWNER TO postgres;

--
-- TOC entry 4750 (class 0 OID 0)
-- Dependencies: 277
-- Name: auth_user_profile_id_seq; Type: SEQUENCE OWNED BY; Schema: public; Owner: postgres
--

ALTER SEQUENCE public.auth_user_profile_id_seq OWNED BY public.auth_user_profile.id;


--
-- TOC entry 278 (class 1259 OID 27526)
-- Name: auth_user_user_permissions; Type: TABLE; Schema: public; Owner: postgres
--

CREATE TABLE public.auth_user_user_permissions (
    id integer NOT NULL,
    myuser_id integer NOT NULL,
    permission_id integer NOT NULL
);


ALTER TABLE public.auth_user_user_permissions OWNER TO postgres;

--
-- TOC entry 279 (class 1259 OID 27529)
-- Name: auth_user_user_permissions_id_seq; Type: SEQUENCE; Schema: public; Owner: postgres
--

CREATE SEQUENCE public.auth_user_user_permissions_id_seq
    AS integer
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;


ALTER SEQUENCE public.auth_user_user_permissions_id_seq OWNER TO postgres;

--
-- TOC entry 4751 (class 0 OID 0)
-- Dependencies: 279
-- Name: auth_user_user_permissions_id_seq; Type: SEQUENCE OWNED BY; Schema: public; Owner: postgres
--

ALTER SEQUENCE public.auth_user_user_permissions_id_seq OWNED BY public.auth_user_user_permissions.id;


--
-- TOC entry 280 (class 1259 OID 27531)
-- Name: authtoken_token; Type: TABLE; Schema: public; Owner: postgres
--

CREATE TABLE public.authtoken_token (
    key character varying(40) NOT NULL,
    created timestamp with time zone NOT NULL,
    user_id integer NOT NULL
);


ALTER TABLE public.authtoken_token OWNER TO postgres;

--
-- TOC entry 281 (class 1259 OID 27534)
-- Name: base_adminlog; Type: TABLE; Schema: public; Owner: postgres
--

CREATE TABLE public.base_adminlog (
    id integer NOT NULL,
    action character varying(50) NOT NULL,
    targets text,
    targets_repr text,
    action_status smallint NOT NULL,
    description text,
    ip_address inet,
    can_routable boolean NOT NULL,
    op_time timestamp with time zone NOT NULL,
    content_type_id integer,
    user_id integer NOT NULL
);


ALTER TABLE public.base_adminlog OWNER TO postgres;

--
-- TOC entry 282 (class 1259 OID 27540)
-- Name: base_adminlog_id_seq; Type: SEQUENCE; Schema: public; Owner: postgres
--

CREATE SEQUENCE public.base_adminlog_id_seq
    AS integer
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;


ALTER SEQUENCE public.base_adminlog_id_seq OWNER TO postgres;

--
-- TOC entry 4752 (class 0 OID 0)
-- Dependencies: 282
-- Name: base_adminlog_id_seq; Type: SEQUENCE OWNED BY; Schema: public; Owner: postgres
--

ALTER SEQUENCE public.base_adminlog_id_seq OWNED BY public.base_adminlog.id;


--
-- TOC entry 283 (class 1259 OID 27542)
-- Name: base_attparamdepts; Type: TABLE; Schema: public; Owner: postgres
--

CREATE TABLE public.base_attparamdepts (
    id integer NOT NULL,
    rulename character varying(40) NOT NULL,
    deptid integer NOT NULL,
    operator character varying(20),
    optime timestamp with time zone
);


ALTER TABLE public.base_attparamdepts OWNER TO postgres;

--
-- TOC entry 284 (class 1259 OID 27545)
-- Name: base_attparamdepts_id_seq; Type: SEQUENCE; Schema: public; Owner: postgres
--

CREATE SEQUENCE public.base_attparamdepts_id_seq
    AS integer
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;


ALTER SEQUENCE public.base_attparamdepts_id_seq OWNER TO postgres;

--
-- TOC entry 4753 (class 0 OID 0)
-- Dependencies: 284
-- Name: base_attparamdepts_id_seq; Type: SEQUENCE OWNED BY; Schema: public; Owner: postgres
--

ALTER SEQUENCE public.base_attparamdepts_id_seq OWNED BY public.base_attparamdepts.id;


--
-- TOC entry 285 (class 1259 OID 27547)
-- Name: base_autoexporttask; Type: TABLE; Schema: public; Owner: postgres
--

CREATE TABLE public.base_autoexporttask (
    id integer NOT NULL,
    create_time timestamp with time zone,
    create_user character varying(150),
    change_time timestamp with time zone,
    change_user character varying(150),
    status smallint NOT NULL,
    task_code character varying(30) NOT NULL,
    task_name character varying(30) NOT NULL,
    params text
);


ALTER TABLE public.base_autoexporttask OWNER TO postgres;

--
-- TOC entry 286 (class 1259 OID 27553)
-- Name: base_autoexporttask_id_seq; Type: SEQUENCE; Schema: public; Owner: postgres
--

CREATE SEQUENCE public.base_autoexporttask_id_seq
    AS integer
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;


ALTER SEQUENCE public.base_autoexporttask_id_seq OWNER TO postgres;

--
-- TOC entry 4754 (class 0 OID 0)
-- Dependencies: 286
-- Name: base_autoexporttask_id_seq; Type: SEQUENCE OWNED BY; Schema: public; Owner: postgres
--

ALTER SEQUENCE public.base_autoexporttask_id_seq OWNED BY public.base_autoexporttask.id;


--
-- TOC entry 287 (class 1259 OID 27555)
-- Name: base_bookmark; Type: TABLE; Schema: public; Owner: postgres
--

CREATE TABLE public.base_bookmark (
    id integer NOT NULL,
    title character varying(128) NOT NULL,
    filters character varying(1000) NOT NULL,
    is_share boolean NOT NULL,
    time_saved timestamp with time zone NOT NULL,
    content_type_id integer NOT NULL,
    user_id integer
);


ALTER TABLE public.base_bookmark OWNER TO postgres;

--
-- TOC entry 288 (class 1259 OID 27561)
-- Name: base_bookmark_id_seq; Type: SEQUENCE; Schema: public; Owner: postgres
--

CREATE SEQUENCE public.base_bookmark_id_seq
    AS integer
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;


ALTER SEQUENCE public.base_bookmark_id_seq OWNER TO postgres;

--
-- TOC entry 4755 (class 0 OID 0)
-- Dependencies: 288
-- Name: base_bookmark_id_seq; Type: SEQUENCE OWNED BY; Schema: public; Owner: postgres
--

ALTER SEQUENCE public.base_bookmark_id_seq OWNED BY public.base_bookmark.id;


--
-- TOC entry 289 (class 1259 OID 27563)
-- Name: base_dbbackuplog; Type: TABLE; Schema: public; Owner: postgres
--

CREATE TABLE public.base_dbbackuplog (
    id integer NOT NULL,
    create_time timestamp with time zone,
    create_user character varying(150),
    change_time timestamp with time zone,
    change_user character varying(150),
    status smallint NOT NULL,
    db_type character varying(50) NOT NULL,
    db_name character varying(50) NOT NULL,
    operator character varying(50),
    backup_file character varying(100) NOT NULL,
    backup_time timestamp with time zone NOT NULL,
    backup_status smallint NOT NULL,
    remark text
);


ALTER TABLE public.base_dbbackuplog OWNER TO postgres;

--
-- TOC entry 290 (class 1259 OID 27569)
-- Name: base_dbbackuplog_id_seq; Type: SEQUENCE; Schema: public; Owner: postgres
--

CREATE SEQUENCE public.base_dbbackuplog_id_seq
    AS integer
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;


ALTER SEQUENCE public.base_dbbackuplog_id_seq OWNER TO postgres;

--
-- TOC entry 4756 (class 0 OID 0)
-- Dependencies: 290
-- Name: base_dbbackuplog_id_seq; Type: SEQUENCE OWNED BY; Schema: public; Owner: postgres
--

ALTER SEQUENCE public.base_dbbackuplog_id_seq OWNED BY public.base_dbbackuplog.id;


--
-- TOC entry 291 (class 1259 OID 27571)
-- Name: base_dbmigrate; Type: TABLE; Schema: public; Owner: postgres
--

CREATE TABLE public.base_dbmigrate (
    id integer NOT NULL,
    create_time timestamp with time zone,
    create_user character varying(150),
    change_time timestamp with time zone,
    change_user character varying(150),
    status smallint NOT NULL,
    name character varying(30) NOT NULL,
    value text NOT NULL
);


ALTER TABLE public.base_dbmigrate OWNER TO postgres;

--
-- TOC entry 292 (class 1259 OID 27577)
-- Name: base_dbmigrate_id_seq; Type: SEQUENCE; Schema: public; Owner: postgres
--

CREATE SEQUENCE public.base_dbmigrate_id_seq
    AS integer
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;


ALTER SEQUENCE public.base_dbmigrate_id_seq OWNER TO postgres;

--
-- TOC entry 4757 (class 0 OID 0)
-- Dependencies: 292
-- Name: base_dbmigrate_id_seq; Type: SEQUENCE OWNED BY; Schema: public; Owner: postgres
--

ALTER SEQUENCE public.base_dbmigrate_id_seq OWNED BY public.base_dbmigrate.id;


--
-- TOC entry 293 (class 1259 OID 27579)
-- Name: base_departmentalert; Type: TABLE; Schema: public; Owner: postgres
--

CREATE TABLE public.base_departmentalert (
    personalalert_ptr_id integer NOT NULL,
    departmentalert_code character varying(116) NOT NULL,
    email character varying(50),
    emplist_id integer
);


ALTER TABLE public.base_departmentalert OWNER TO postgres;

--
-- TOC entry 294 (class 1259 OID 27582)
-- Name: base_departmentalert_department; Type: TABLE; Schema: public; Owner: postgres
--

CREATE TABLE public.base_departmentalert_department (
    id integer NOT NULL,
    departmentalert_id integer NOT NULL,
    department_id integer NOT NULL
);


ALTER TABLE public.base_departmentalert_department OWNER TO postgres;

--
-- TOC entry 295 (class 1259 OID 27585)
-- Name: base_departmentalert_department_id_seq; Type: SEQUENCE; Schema: public; Owner: postgres
--

CREATE SEQUENCE public.base_departmentalert_department_id_seq
    AS integer
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;


ALTER SEQUENCE public.base_departmentalert_department_id_seq OWNER TO postgres;

--
-- TOC entry 4758 (class 0 OID 0)
-- Dependencies: 295
-- Name: base_departmentalert_department_id_seq; Type: SEQUENCE OWNED BY; Schema: public; Owner: postgres
--

ALTER SEQUENCE public.base_departmentalert_department_id_seq OWNED BY public.base_departmentalert_department.id;


--
-- TOC entry 483 (class 1259 OID 44172)
-- Name: base_messengersentlog; Type: TABLE; Schema: public; Owner: postgres
--

CREATE TABLE public.base_messengersentlog (
    id bigint NOT NULL,
    action smallint NOT NULL,
    targets text,
    targets_repr text,
    action_status smallint NOT NULL,
    description text,
    ip_address inet,
    can_routable boolean NOT NULL,
    op_time timestamp with time zone NOT NULL,
    content_type_id integer,
    user_id integer NOT NULL,
    bot_uid character varying(100),
    emp_id integer
);


ALTER TABLE public.base_messengersentlog OWNER TO postgres;

--
-- TOC entry 482 (class 1259 OID 44170)
-- Name: base_messengersentlog_id_seq; Type: SEQUENCE; Schema: public; Owner: postgres
--

CREATE SEQUENCE public.base_messengersentlog_id_seq
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;


ALTER SEQUENCE public.base_messengersentlog_id_seq OWNER TO postgres;

--
-- TOC entry 4759 (class 0 OID 0)
-- Dependencies: 482
-- Name: base_messengersentlog_id_seq; Type: SEQUENCE OWNED BY; Schema: public; Owner: postgres
--

ALTER SEQUENCE public.base_messengersentlog_id_seq OWNED BY public.base_messengersentlog.id;


--
-- TOC entry 296 (class 1259 OID 27587)
-- Name: base_personalalert; Type: TABLE; Schema: public; Owner: postgres
--

CREATE TABLE public.base_personalalert (
    id integer NOT NULL,
    create_time timestamp with time zone,
    create_user character varying(150),
    change_time timestamp with time zone,
    change_user character varying(150),
    status smallint NOT NULL,
    code character varying(100) NOT NULL,
    late_exceeds integer,
    early_leave_exceeds integer,
    absent_exceeds integer,
    is_enble_alert integer,
    sending_frequency integer,
    day integer,
    "time" character varying(8),
    include_today integer,
    email_alert integer,
    pop_alert integer,
    alert_type integer,
    last_activity timestamp with time zone,
    message_type integer
);


ALTER TABLE public.base_personalalert OWNER TO postgres;

--
-- TOC entry 481 (class 1259 OID 44150)
-- Name: base_personalalert_employee; Type: TABLE; Schema: public; Owner: postgres
--

CREATE TABLE public.base_personalalert_employee (
    id integer NOT NULL,
    personalalert_id integer NOT NULL,
    employee_id integer NOT NULL
);


ALTER TABLE public.base_personalalert_employee OWNER TO postgres;

--
-- TOC entry 480 (class 1259 OID 44148)
-- Name: base_personalalert_employee_id_seq; Type: SEQUENCE; Schema: public; Owner: postgres
--

CREATE SEQUENCE public.base_personalalert_employee_id_seq
    AS integer
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;


ALTER SEQUENCE public.base_personalalert_employee_id_seq OWNER TO postgres;

--
-- TOC entry 4760 (class 0 OID 0)
-- Dependencies: 480
-- Name: base_personalalert_employee_id_seq; Type: SEQUENCE OWNED BY; Schema: public; Owner: postgres
--

ALTER SEQUENCE public.base_personalalert_employee_id_seq OWNED BY public.base_personalalert_employee.id;


--
-- TOC entry 297 (class 1259 OID 27595)
-- Name: base_personalalert_id_seq; Type: SEQUENCE; Schema: public; Owner: postgres
--

CREATE SEQUENCE public.base_personalalert_id_seq
    AS integer
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;


ALTER SEQUENCE public.base_personalalert_id_seq OWNER TO postgres;

--
-- TOC entry 4761 (class 0 OID 0)
-- Dependencies: 297
-- Name: base_personalalert_id_seq; Type: SEQUENCE OWNED BY; Schema: public; Owner: postgres
--

ALTER SEQUENCE public.base_personalalert_id_seq OWNED BY public.base_personalalert.id;


--
-- TOC entry 298 (class 1259 OID 27597)
-- Name: base_reportoutputsetting; Type: TABLE; Schema: public; Owner: postgres
--

CREATE TABLE public.base_reportoutputsetting (
    id integer NOT NULL,
    agreement_message_id character varying(200) NOT NULL,
    report_name character varying(200) NOT NULL,
    agreement_message text
);


ALTER TABLE public.base_reportoutputsetting OWNER TO postgres;

--
-- TOC entry 299 (class 1259 OID 27603)
-- Name: base_reportoutputsetting_id_seq; Type: SEQUENCE; Schema: public; Owner: postgres
--

CREATE SEQUENCE public.base_reportoutputsetting_id_seq
    AS integer
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;


ALTER SEQUENCE public.base_reportoutputsetting_id_seq OWNER TO postgres;

--
-- TOC entry 4762 (class 0 OID 0)
-- Dependencies: 299
-- Name: base_reportoutputsetting_id_seq; Type: SEQUENCE OWNED BY; Schema: public; Owner: postgres
--

ALTER SEQUENCE public.base_reportoutputsetting_id_seq OWNED BY public.base_reportoutputsetting.id;


--
-- TOC entry 300 (class 1259 OID 27605)
-- Name: base_securitypolicy; Type: TABLE; Schema: public; Owner: postgres
--

CREATE TABLE public.base_securitypolicy (
    id integer NOT NULL,
    single_login boolean NOT NULL,
    security_code boolean NOT NULL,
    code_length integer NOT NULL,
    valid_duration integer NOT NULL,
    failed_locked boolean NOT NULL,
    lock_failed_count integer NOT NULL,
    lock_duration integer NOT NULL,
    enforce_pwd_change boolean NOT NULL,
    enforce_pwd_expiration boolean NOT NULL,
    validity_period integer NOT NULL,
    is_default boolean NOT NULL
);


ALTER TABLE public.base_securitypolicy OWNER TO postgres;

--
-- TOC entry 301 (class 1259 OID 27608)
-- Name: base_securitypolicy_id_seq; Type: SEQUENCE; Schema: public; Owner: postgres
--

CREATE SEQUENCE public.base_securitypolicy_id_seq
    AS integer
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;


ALTER SEQUENCE public.base_securitypolicy_id_seq OWNER TO postgres;

--
-- TOC entry 4763 (class 0 OID 0)
-- Dependencies: 301
-- Name: base_securitypolicy_id_seq; Type: SEQUENCE OWNED BY; Schema: public; Owner: postgres
--

ALTER SEQUENCE public.base_securitypolicy_id_seq OWNED BY public.base_securitypolicy.id;


--
-- TOC entry 302 (class 1259 OID 27610)
-- Name: base_sendemail; Type: TABLE; Schema: public; Owner: postgres
--

CREATE TABLE public.base_sendemail (
    id integer NOT NULL,
    purpose integer NOT NULL,
    email_to text NOT NULL,
    email_cc text,
    email_bcc text,
    email_subject character varying(40) NOT NULL,
    email_content text,
    send_time timestamp with time zone,
    send_status smallint
);


ALTER TABLE public.base_sendemail OWNER TO postgres;

--
-- TOC entry 303 (class 1259 OID 27616)
-- Name: base_sendemail_id_seq; Type: SEQUENCE; Schema: public; Owner: postgres
--

CREATE SEQUENCE public.base_sendemail_id_seq
    AS integer
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;


ALTER SEQUENCE public.base_sendemail_id_seq OWNER TO postgres;

--
-- TOC entry 4764 (class 0 OID 0)
-- Dependencies: 303
-- Name: base_sendemail_id_seq; Type: SEQUENCE OWNED BY; Schema: public; Owner: postgres
--

ALTER SEQUENCE public.base_sendemail_id_seq OWNED BY public.base_sendemail.id;


--
-- TOC entry 304 (class 1259 OID 27618)
-- Name: base_sftpsetting; Type: TABLE; Schema: public; Owner: postgres
--

CREATE TABLE public.base_sftpsetting (
    id integer NOT NULL,
    host inet NOT NULL,
    port integer NOT NULL,
    auth_method integer NOT NULL,
    user_name character varying(30) NOT NULL,
    user_password character varying(128),
    user_key text,
    key_password character varying(128)
);


ALTER TABLE public.base_sftpsetting OWNER TO postgres;

--
-- TOC entry 305 (class 1259 OID 27624)
-- Name: base_sftpsetting_id_seq; Type: SEQUENCE; Schema: public; Owner: postgres
--

CREATE SEQUENCE public.base_sftpsetting_id_seq
    AS integer
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;


ALTER SEQUENCE public.base_sftpsetting_id_seq OWNER TO postgres;

--
-- TOC entry 4765 (class 0 OID 0)
-- Dependencies: 305
-- Name: base_sftpsetting_id_seq; Type: SEQUENCE OWNED BY; Schema: public; Owner: postgres
--

ALTER SEQUENCE public.base_sftpsetting_id_seq OWNED BY public.base_sftpsetting.id;


--
-- TOC entry 306 (class 1259 OID 27626)
-- Name: base_sysparam; Type: TABLE; Schema: public; Owner: postgres
--

CREATE TABLE public.base_sysparam (
    id integer NOT NULL,
    para_name character varying(30) NOT NULL,
    para_type character varying(10),
    para_value character varying(250)
);


ALTER TABLE public.base_sysparam OWNER TO postgres;

--
-- TOC entry 307 (class 1259 OID 27629)
-- Name: base_sysparam_id_seq; Type: SEQUENCE; Schema: public; Owner: postgres
--

CREATE SEQUENCE public.base_sysparam_id_seq
    AS integer
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;


ALTER SEQUENCE public.base_sysparam_id_seq OWNER TO postgres;

--
-- TOC entry 4766 (class 0 OID 0)
-- Dependencies: 307
-- Name: base_sysparam_id_seq; Type: SEQUENCE OWNED BY; Schema: public; Owner: postgres
--

ALTER SEQUENCE public.base_sysparam_id_seq OWNED BY public.base_sysparam.id;


--
-- TOC entry 308 (class 1259 OID 27631)
-- Name: base_sysparamdept; Type: TABLE; Schema: public; Owner: postgres
--

CREATE TABLE public.base_sysparamdept (
    id integer NOT NULL,
    rule_name character varying(40) NOT NULL,
    dept_id integer NOT NULL,
    operator character varying(20),
    op_time timestamp with time zone
);


ALTER TABLE public.base_sysparamdept OWNER TO postgres;

--
-- TOC entry 309 (class 1259 OID 27634)
-- Name: base_sysparamdept_id_seq; Type: SEQUENCE; Schema: public; Owner: postgres
--

CREATE SEQUENCE public.base_sysparamdept_id_seq
    AS integer
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;


ALTER SEQUENCE public.base_sysparamdept_id_seq OWNER TO postgres;

--
-- TOC entry 4767 (class 0 OID 0)
-- Dependencies: 309
-- Name: base_sysparamdept_id_seq; Type: SEQUENCE OWNED BY; Schema: public; Owner: postgres
--

ALTER SEQUENCE public.base_sysparamdept_id_seq OWNED BY public.base_sysparamdept.id;


--
-- TOC entry 310 (class 1259 OID 27636)
-- Name: base_systemsetting; Type: TABLE; Schema: public; Owner: postgres
--

CREATE TABLE public.base_systemsetting (
    id integer NOT NULL,
    create_time timestamp with time zone,
    create_user character varying(150),
    change_time timestamp with time zone,
    change_user character varying(150),
    status smallint NOT NULL,
    name character varying(30) NOT NULL,
    value text NOT NULL
);


ALTER TABLE public.base_systemsetting OWNER TO postgres;

--
-- TOC entry 311 (class 1259 OID 27642)
-- Name: base_systemsetting_id_seq; Type: SEQUENCE; Schema: public; Owner: postgres
--

CREATE SEQUENCE public.base_systemsetting_id_seq
    AS integer
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;


ALTER SEQUENCE public.base_systemsetting_id_seq OWNER TO postgres;

--
-- TOC entry 4768 (class 0 OID 0)
-- Dependencies: 311
-- Name: base_systemsetting_id_seq; Type: SEQUENCE OWNED BY; Schema: public; Owner: postgres
--

ALTER SEQUENCE public.base_systemsetting_id_seq OWNED BY public.base_systemsetting.id;


--
-- TOC entry 312 (class 1259 OID 27644)
-- Name: base_taskresultlog; Type: TABLE; Schema: public; Owner: postgres
--

CREATE TABLE public.base_taskresultlog (
    id integer NOT NULL,
    task character varying(50) NOT NULL,
    status character varying(10) NOT NULL,
    result character varying(500) NOT NULL,
    "time" timestamp with time zone NOT NULL
);


ALTER TABLE public.base_taskresultlog OWNER TO postgres;

--
-- TOC entry 313 (class 1259 OID 27650)
-- Name: base_taskresultlog_id_seq; Type: SEQUENCE; Schema: public; Owner: postgres
--

CREATE SEQUENCE public.base_taskresultlog_id_seq
    AS integer
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;


ALTER SEQUENCE public.base_taskresultlog_id_seq OWNER TO postgres;

--
-- TOC entry 4769 (class 0 OID 0)
-- Dependencies: 313
-- Name: base_taskresultlog_id_seq; Type: SEQUENCE OWNED BY; Schema: public; Owner: postgres
--

ALTER SEQUENCE public.base_taskresultlog_id_seq OWNED BY public.base_taskresultlog.id;


--
-- TOC entry 314 (class 1259 OID 27652)
-- Name: celery_taskmeta; Type: TABLE; Schema: public; Owner: postgres
--

CREATE TABLE public.celery_taskmeta (
    id integer NOT NULL,
    task_id character varying(255) NOT NULL,
    status character varying(50) NOT NULL,
    result text,
    date_done timestamp with time zone NOT NULL,
    traceback text,
    hidden boolean NOT NULL,
    meta text
);


ALTER TABLE public.celery_taskmeta OWNER TO postgres;

--
-- TOC entry 315 (class 1259 OID 27658)
-- Name: celery_taskmeta_id_seq; Type: SEQUENCE; Schema: public; Owner: postgres
--

CREATE SEQUENCE public.celery_taskmeta_id_seq
    AS integer
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;


ALTER SEQUENCE public.celery_taskmeta_id_seq OWNER TO postgres;

--
-- TOC entry 4770 (class 0 OID 0)
-- Dependencies: 315
-- Name: celery_taskmeta_id_seq; Type: SEQUENCE OWNED BY; Schema: public; Owner: postgres
--

ALTER SEQUENCE public.celery_taskmeta_id_seq OWNED BY public.celery_taskmeta.id;


--
-- TOC entry 316 (class 1259 OID 27660)
-- Name: celery_tasksetmeta; Type: TABLE; Schema: public; Owner: postgres
--

CREATE TABLE public.celery_tasksetmeta (
    id integer NOT NULL,
    taskset_id character varying(255) NOT NULL,
    result text NOT NULL,
    date_done timestamp with time zone NOT NULL,
    hidden boolean NOT NULL
);


ALTER TABLE public.celery_tasksetmeta OWNER TO postgres;

--
-- TOC entry 317 (class 1259 OID 27666)
-- Name: celery_tasksetmeta_id_seq; Type: SEQUENCE; Schema: public; Owner: postgres
--

CREATE SEQUENCE public.celery_tasksetmeta_id_seq
    AS integer
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;


ALTER SEQUENCE public.celery_tasksetmeta_id_seq OWNER TO postgres;

--
-- TOC entry 4771 (class 0 OID 0)
-- Dependencies: 317
-- Name: celery_tasksetmeta_id_seq; Type: SEQUENCE OWNED BY; Schema: public; Owner: postgres
--

ALTER SEQUENCE public.celery_tasksetmeta_id_seq OWNED BY public.celery_tasksetmeta.id;


--
-- TOC entry 318 (class 1259 OID 27668)
-- Name: django_admin_log; Type: TABLE; Schema: public; Owner: postgres
--

CREATE TABLE public.django_admin_log (
    id integer NOT NULL,
    action_time timestamp with time zone NOT NULL,
    object_id text,
    object_repr character varying(200) NOT NULL,
    action_flag smallint NOT NULL,
    change_message text NOT NULL,
    content_type_id integer,
    user_id integer NOT NULL,
    CONSTRAINT django_admin_log_action_flag_check CHECK ((action_flag >= 0))
);


ALTER TABLE public.django_admin_log OWNER TO postgres;

--
-- TOC entry 319 (class 1259 OID 27675)
-- Name: django_admin_log_id_seq; Type: SEQUENCE; Schema: public; Owner: postgres
--

CREATE SEQUENCE public.django_admin_log_id_seq
    AS integer
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;


ALTER SEQUENCE public.django_admin_log_id_seq OWNER TO postgres;

--
-- TOC entry 4772 (class 0 OID 0)
-- Dependencies: 319
-- Name: django_admin_log_id_seq; Type: SEQUENCE OWNED BY; Schema: public; Owner: postgres
--

ALTER SEQUENCE public.django_admin_log_id_seq OWNED BY public.django_admin_log.id;


--
-- TOC entry 320 (class 1259 OID 27677)
-- Name: django_content_type; Type: TABLE; Schema: public; Owner: postgres
--

CREATE TABLE public.django_content_type (
    id integer NOT NULL,
    app_label character varying(100) NOT NULL,
    model character varying(100) NOT NULL
);


ALTER TABLE public.django_content_type OWNER TO postgres;

--
-- TOC entry 321 (class 1259 OID 27680)
-- Name: django_content_type_id_seq; Type: SEQUENCE; Schema: public; Owner: postgres
--

CREATE SEQUENCE public.django_content_type_id_seq
    AS integer
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;


ALTER SEQUENCE public.django_content_type_id_seq OWNER TO postgres;

--
-- TOC entry 4773 (class 0 OID 0)
-- Dependencies: 321
-- Name: django_content_type_id_seq; Type: SEQUENCE OWNED BY; Schema: public; Owner: postgres
--

ALTER SEQUENCE public.django_content_type_id_seq OWNED BY public.django_content_type.id;


--
-- TOC entry 322 (class 1259 OID 27682)
-- Name: django_migrations; Type: TABLE; Schema: public; Owner: postgres
--

CREATE TABLE public.django_migrations (
    id integer NOT NULL,
    app character varying(255) NOT NULL,
    name character varying(255) NOT NULL,
    applied timestamp with time zone NOT NULL
);


ALTER TABLE public.django_migrations OWNER TO postgres;

--
-- TOC entry 323 (class 1259 OID 27688)
-- Name: django_migrations_id_seq; Type: SEQUENCE; Schema: public; Owner: postgres
--

CREATE SEQUENCE public.django_migrations_id_seq
    AS integer
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;


ALTER SEQUENCE public.django_migrations_id_seq OWNER TO postgres;

--
-- TOC entry 4774 (class 0 OID 0)
-- Dependencies: 323
-- Name: django_migrations_id_seq; Type: SEQUENCE OWNED BY; Schema: public; Owner: postgres
--

ALTER SEQUENCE public.django_migrations_id_seq OWNED BY public.django_migrations.id;


--
-- TOC entry 324 (class 1259 OID 27690)
-- Name: django_session; Type: TABLE; Schema: public; Owner: postgres
--

CREATE TABLE public.django_session (
    session_key character varying(40) NOT NULL,
    session_data text NOT NULL,
    expire_date timestamp with time zone NOT NULL
);


ALTER TABLE public.django_session OWNER TO postgres;

--
-- TOC entry 325 (class 1259 OID 27696)
-- Name: djcelery_crontabschedule; Type: TABLE; Schema: public; Owner: postgres
--

CREATE TABLE public.djcelery_crontabschedule (
    id integer NOT NULL,
    minute character varying(64) NOT NULL,
    hour character varying(64) NOT NULL,
    day_of_week character varying(64) NOT NULL,
    day_of_month character varying(64) NOT NULL,
    month_of_year character varying(64) NOT NULL
);


ALTER TABLE public.djcelery_crontabschedule OWNER TO postgres;

--
-- TOC entry 326 (class 1259 OID 27699)
-- Name: djcelery_crontabschedule_id_seq; Type: SEQUENCE; Schema: public; Owner: postgres
--

CREATE SEQUENCE public.djcelery_crontabschedule_id_seq
    AS integer
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;


ALTER SEQUENCE public.djcelery_crontabschedule_id_seq OWNER TO postgres;

--
-- TOC entry 4775 (class 0 OID 0)
-- Dependencies: 326
-- Name: djcelery_crontabschedule_id_seq; Type: SEQUENCE OWNED BY; Schema: public; Owner: postgres
--

ALTER SEQUENCE public.djcelery_crontabschedule_id_seq OWNED BY public.djcelery_crontabschedule.id;


--
-- TOC entry 327 (class 1259 OID 27701)
-- Name: djcelery_intervalschedule; Type: TABLE; Schema: public; Owner: postgres
--

CREATE TABLE public.djcelery_intervalschedule (
    id integer NOT NULL,
    every integer NOT NULL,
    period character varying(24) NOT NULL
);


ALTER TABLE public.djcelery_intervalschedule OWNER TO postgres;

--
-- TOC entry 328 (class 1259 OID 27704)
-- Name: djcelery_intervalschedule_id_seq; Type: SEQUENCE; Schema: public; Owner: postgres
--

CREATE SEQUENCE public.djcelery_intervalschedule_id_seq
    AS integer
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;


ALTER SEQUENCE public.djcelery_intervalschedule_id_seq OWNER TO postgres;

--
-- TOC entry 4776 (class 0 OID 0)
-- Dependencies: 328
-- Name: djcelery_intervalschedule_id_seq; Type: SEQUENCE OWNED BY; Schema: public; Owner: postgres
--

ALTER SEQUENCE public.djcelery_intervalschedule_id_seq OWNED BY public.djcelery_intervalschedule.id;


--
-- TOC entry 329 (class 1259 OID 27706)
-- Name: djcelery_periodictask; Type: TABLE; Schema: public; Owner: postgres
--

CREATE TABLE public.djcelery_periodictask (
    id integer NOT NULL,
    name character varying(200) NOT NULL,
    task character varying(200) NOT NULL,
    args text NOT NULL,
    kwargs text NOT NULL,
    queue character varying(200),
    exchange character varying(200),
    routing_key character varying(200),
    expires timestamp with time zone,
    enabled boolean NOT NULL,
    last_run_at timestamp with time zone,
    total_run_count integer NOT NULL,
    date_changed timestamp with time zone NOT NULL,
    description text NOT NULL,
    crontab_id integer,
    interval_id integer,
    CONSTRAINT djcelery_periodictask_total_run_count_check CHECK ((total_run_count >= 0))
);


ALTER TABLE public.djcelery_periodictask OWNER TO postgres;

--
-- TOC entry 330 (class 1259 OID 27713)
-- Name: djcelery_periodictask_id_seq; Type: SEQUENCE; Schema: public; Owner: postgres
--

CREATE SEQUENCE public.djcelery_periodictask_id_seq
    AS integer
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;


ALTER SEQUENCE public.djcelery_periodictask_id_seq OWNER TO postgres;

--
-- TOC entry 4777 (class 0 OID 0)
-- Dependencies: 330
-- Name: djcelery_periodictask_id_seq; Type: SEQUENCE OWNED BY; Schema: public; Owner: postgres
--

ALTER SEQUENCE public.djcelery_periodictask_id_seq OWNED BY public.djcelery_periodictask.id;


--
-- TOC entry 331 (class 1259 OID 27715)
-- Name: djcelery_periodictasks; Type: TABLE; Schema: public; Owner: postgres
--

CREATE TABLE public.djcelery_periodictasks (
    ident smallint NOT NULL,
    last_update timestamp with time zone NOT NULL
);


ALTER TABLE public.djcelery_periodictasks OWNER TO postgres;

--
-- TOC entry 332 (class 1259 OID 27718)
-- Name: djcelery_taskstate; Type: TABLE; Schema: public; Owner: postgres
--

CREATE TABLE public.djcelery_taskstate (
    id integer NOT NULL,
    state character varying(64) NOT NULL,
    task_id character varying(36) NOT NULL,
    name character varying(200),
    tstamp timestamp with time zone NOT NULL,
    args text,
    kwargs text,
    eta timestamp with time zone,
    expires timestamp with time zone,
    result text,
    traceback text,
    runtime double precision,
    retries integer NOT NULL,
    hidden boolean NOT NULL,
    worker_id integer
);


ALTER TABLE public.djcelery_taskstate OWNER TO postgres;

--
-- TOC entry 333 (class 1259 OID 27724)
-- Name: djcelery_taskstate_id_seq; Type: SEQUENCE; Schema: public; Owner: postgres
--

CREATE SEQUENCE public.djcelery_taskstate_id_seq
    AS integer
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;


ALTER SEQUENCE public.djcelery_taskstate_id_seq OWNER TO postgres;

--
-- TOC entry 4778 (class 0 OID 0)
-- Dependencies: 333
-- Name: djcelery_taskstate_id_seq; Type: SEQUENCE OWNED BY; Schema: public; Owner: postgres
--

ALTER SEQUENCE public.djcelery_taskstate_id_seq OWNED BY public.djcelery_taskstate.id;


--
-- TOC entry 334 (class 1259 OID 27726)
-- Name: djcelery_workerstate; Type: TABLE; Schema: public; Owner: postgres
--

CREATE TABLE public.djcelery_workerstate (
    id integer NOT NULL,
    hostname character varying(255) NOT NULL,
    last_heartbeat timestamp with time zone
);


ALTER TABLE public.djcelery_workerstate OWNER TO postgres;

--
-- TOC entry 335 (class 1259 OID 27729)
-- Name: djcelery_workerstate_id_seq; Type: SEQUENCE; Schema: public; Owner: postgres
--

CREATE SEQUENCE public.djcelery_workerstate_id_seq
    AS integer
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;


ALTER SEQUENCE public.djcelery_workerstate_id_seq OWNER TO postgres;

--
-- TOC entry 4779 (class 0 OID 0)
-- Dependencies: 335
-- Name: djcelery_workerstate_id_seq; Type: SEQUENCE OWNED BY; Schema: public; Owner: postgres
--

ALTER SEQUENCE public.djcelery_workerstate_id_seq OWNED BY public.djcelery_workerstate.id;


--
-- TOC entry 336 (class 1259 OID 27731)
-- Name: ep_epsetup; Type: TABLE; Schema: public; Owner: postgres
--

CREATE TABLE public.ep_epsetup (
    id integer NOT NULL,
    create_time timestamp with time zone,
    create_user character varying(150),
    change_time timestamp with time zone,
    change_user character varying(150),
    status smallint NOT NULL,
    temp_alarm boolean NOT NULL,
    temp_warning numeric(4,1) NOT NULL,
    temp_unit smallint NOT NULL,
    mask_alarm boolean NOT NULL
);


ALTER TABLE public.ep_epsetup OWNER TO postgres;

--
-- TOC entry 337 (class 1259 OID 27734)
-- Name: ep_epsetup_id_seq; Type: SEQUENCE; Schema: public; Owner: postgres
--

CREATE SEQUENCE public.ep_epsetup_id_seq
    AS integer
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;


ALTER SEQUENCE public.ep_epsetup_id_seq OWNER TO postgres;

--
-- TOC entry 4780 (class 0 OID 0)
-- Dependencies: 337
-- Name: ep_epsetup_id_seq; Type: SEQUENCE OWNED BY; Schema: public; Owner: postgres
--

ALTER SEQUENCE public.ep_epsetup_id_seq OWNED BY public.ep_epsetup.id;


--
-- TOC entry 338 (class 1259 OID 27736)
-- Name: ep_eptransaction; Type: TABLE; Schema: public; Owner: postgres
--

CREATE TABLE public.ep_eptransaction (
    id integer NOT NULL,
    create_time timestamp with time zone,
    create_user character varying(150),
    change_time timestamp with time zone,
    change_user character varying(150),
    status smallint NOT NULL,
    area character varying(100) NOT NULL,
    check_datetime timestamp with time zone,
    check_date date NOT NULL,
    check_time time without time zone NOT NULL,
    temperature numeric(4,1) NOT NULL,
    is_mask boolean NOT NULL,
    upload_time timestamp with time zone NOT NULL,
    source smallint NOT NULL,
    emp_id integer,
    terminal_id integer
);


ALTER TABLE public.ep_eptransaction OWNER TO postgres;

--
-- TOC entry 339 (class 1259 OID 27739)
-- Name: ep_eptransaction_id_seq; Type: SEQUENCE; Schema: public; Owner: postgres
--

CREATE SEQUENCE public.ep_eptransaction_id_seq
    AS integer
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;


ALTER SEQUENCE public.ep_eptransaction_id_seq OWNER TO postgres;

--
-- TOC entry 4781 (class 0 OID 0)
-- Dependencies: 339
-- Name: ep_eptransaction_id_seq; Type: SEQUENCE OWNED BY; Schema: public; Owner: postgres
--

ALTER SEQUENCE public.ep_eptransaction_id_seq OWNED BY public.ep_eptransaction.id;


--
-- TOC entry 340 (class 1259 OID 27741)
-- Name: guardian_groupobjectpermission; Type: TABLE; Schema: public; Owner: postgres
--

CREATE TABLE public.guardian_groupobjectpermission (
    id integer NOT NULL,
    object_pk character varying(255) NOT NULL,
    content_type_id integer NOT NULL,
    group_id integer NOT NULL,
    permission_id integer NOT NULL
);


ALTER TABLE public.guardian_groupobjectpermission OWNER TO postgres;

--
-- TOC entry 341 (class 1259 OID 27744)
-- Name: guardian_groupobjectpermission_id_seq; Type: SEQUENCE; Schema: public; Owner: postgres
--

CREATE SEQUENCE public.guardian_groupobjectpermission_id_seq
    AS integer
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;


ALTER SEQUENCE public.guardian_groupobjectpermission_id_seq OWNER TO postgres;

--
-- TOC entry 4782 (class 0 OID 0)
-- Dependencies: 341
-- Name: guardian_groupobjectpermission_id_seq; Type: SEQUENCE OWNED BY; Schema: public; Owner: postgres
--

ALTER SEQUENCE public.guardian_groupobjectpermission_id_seq OWNED BY public.guardian_groupobjectpermission.id;


--
-- TOC entry 342 (class 1259 OID 27746)
-- Name: guardian_userobjectpermission; Type: TABLE; Schema: public; Owner: postgres
--

CREATE TABLE public.guardian_userobjectpermission (
    id integer NOT NULL,
    object_pk character varying(255) NOT NULL,
    content_type_id integer NOT NULL,
    permission_id integer NOT NULL,
    user_id integer NOT NULL
);


ALTER TABLE public.guardian_userobjectpermission OWNER TO postgres;

--
-- TOC entry 343 (class 1259 OID 27749)
-- Name: guardian_userobjectpermission_id_seq; Type: SEQUENCE; Schema: public; Owner: postgres
--

CREATE SEQUENCE public.guardian_userobjectpermission_id_seq
    AS integer
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;


ALTER SEQUENCE public.guardian_userobjectpermission_id_seq OWNER TO postgres;

--
-- TOC entry 4783 (class 0 OID 0)
-- Dependencies: 343
-- Name: guardian_userobjectpermission_id_seq; Type: SEQUENCE OWNED BY; Schema: public; Owner: postgres
--

ALTER SEQUENCE public.guardian_userobjectpermission_id_seq OWNED BY public.guardian_userobjectpermission.id;


--
-- TOC entry 344 (class 1259 OID 27751)
-- Name: iclock_biodata; Type: TABLE; Schema: public; Owner: postgres
--

CREATE TABLE public.iclock_biodata (
    id integer NOT NULL,
    create_time timestamp with time zone,
    create_user character varying(150),
    change_time timestamp with time zone,
    change_user character varying(150),
    status smallint NOT NULL,
    bio_tmp text NOT NULL,
    bio_no integer,
    bio_index integer,
    bio_type integer NOT NULL,
    major_ver character varying(30) NOT NULL,
    minor_ver character varying(30),
    bio_format integer,
    valid integer NOT NULL,
    duress integer NOT NULL,
    update_time timestamp with time zone,
    sn character varying(50),
    employee_id integer NOT NULL
);


ALTER TABLE public.iclock_biodata OWNER TO postgres;

--
-- TOC entry 345 (class 1259 OID 27757)
-- Name: iclock_biodata_id_seq; Type: SEQUENCE; Schema: public; Owner: postgres
--

CREATE SEQUENCE public.iclock_biodata_id_seq
    AS integer
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;


ALTER SEQUENCE public.iclock_biodata_id_seq OWNER TO postgres;

--
-- TOC entry 4784 (class 0 OID 0)
-- Dependencies: 345
-- Name: iclock_biodata_id_seq; Type: SEQUENCE OWNED BY; Schema: public; Owner: postgres
--

ALTER SEQUENCE public.iclock_biodata_id_seq OWNED BY public.iclock_biodata.id;


--
-- TOC entry 346 (class 1259 OID 27759)
-- Name: iclock_biophoto; Type: TABLE; Schema: public; Owner: postgres
--

CREATE TABLE public.iclock_biophoto (
    id integer NOT NULL,
    create_time timestamp with time zone,
    create_user character varying(150),
    change_time timestamp with time zone,
    change_user character varying(150),
    status smallint NOT NULL,
    first_name character varying(24),
    last_name character varying(24),
    email character varying(254),
    enroll_sn character varying(100),
    register_photo character varying(100) NOT NULL,
    register_time timestamp with time zone NOT NULL,
    approval_photo character varying(100),
    approval_state smallint NOT NULL,
    approval_time timestamp with time zone,
    remark character varying(100),
    employee_id integer NOT NULL
);


ALTER TABLE public.iclock_biophoto OWNER TO postgres;

--
-- TOC entry 347 (class 1259 OID 27765)
-- Name: iclock_biophoto_id_seq; Type: SEQUENCE; Schema: public; Owner: postgres
--

CREATE SEQUENCE public.iclock_biophoto_id_seq
    AS integer
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;


ALTER SEQUENCE public.iclock_biophoto_id_seq OWNER TO postgres;

--
-- TOC entry 4785 (class 0 OID 0)
-- Dependencies: 347
-- Name: iclock_biophoto_id_seq; Type: SEQUENCE OWNED BY; Schema: public; Owner: postgres
--

ALTER SEQUENCE public.iclock_biophoto_id_seq OWNED BY public.iclock_biophoto.id;


--
-- TOC entry 348 (class 1259 OID 27767)
-- Name: iclock_deviceconfig; Type: TABLE; Schema: public; Owner: postgres
--

CREATE TABLE public.iclock_deviceconfig (
    uuid character varying(36) NOT NULL,
    enable_registration boolean NOT NULL,
    enable_resigned_filter boolean NOT NULL,
    enable_auto_add boolean NOT NULL,
    enable_name_upload boolean NOT NULL,
    enable_card_upload boolean NOT NULL,
    transaction_retention integer NOT NULL,
    command_retention integer NOT NULL,
    dev_log_retention integer NOT NULL,
    upload_log_retention integer NOT NULL,
    edit_policy smallint NOT NULL,
    import_policy smallint NOT NULL,
    mobile_policy smallint NOT NULL,
    device_policy smallint NOT NULL
);


ALTER TABLE public.iclock_deviceconfig OWNER TO postgres;

--
-- TOC entry 349 (class 1259 OID 27770)
-- Name: iclock_errorcommandlog; Type: TABLE; Schema: public; Owner: postgres
--

CREATE TABLE public.iclock_errorcommandlog (
    id integer NOT NULL,
    create_time timestamp with time zone,
    create_user character varying(150),
    change_time timestamp with time zone,
    change_user character varying(150),
    status smallint NOT NULL,
    error_code character varying(16),
    error_msg character varying(50),
    data_origin text,
    cmd character varying(50),
    additional text,
    upload_time timestamp with time zone NOT NULL,
    terminal_id integer NOT NULL
);


ALTER TABLE public.iclock_errorcommandlog OWNER TO postgres;

--
-- TOC entry 350 (class 1259 OID 27776)
-- Name: iclock_errorcommandlog_id_seq; Type: SEQUENCE; Schema: public; Owner: postgres
--

CREATE SEQUENCE public.iclock_errorcommandlog_id_seq
    AS integer
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;


ALTER SEQUENCE public.iclock_errorcommandlog_id_seq OWNER TO postgres;

--
-- TOC entry 4786 (class 0 OID 0)
-- Dependencies: 350
-- Name: iclock_errorcommandlog_id_seq; Type: SEQUENCE OWNED BY; Schema: public; Owner: postgres
--

ALTER SEQUENCE public.iclock_errorcommandlog_id_seq OWNED BY public.iclock_errorcommandlog.id;


--
-- TOC entry 351 (class 1259 OID 27778)
-- Name: iclock_privatemessage; Type: TABLE; Schema: public; Owner: postgres
--

CREATE TABLE public.iclock_privatemessage (
    id integer NOT NULL,
    create_time timestamp with time zone,
    create_user character varying(150),
    change_time timestamp with time zone,
    change_user character varying(150),
    status smallint NOT NULL,
    uid character varying(36),
    start_time timestamp with time zone NOT NULL,
    duration integer NOT NULL,
    content text NOT NULL,
    last_send timestamp with time zone,
    employee_id integer NOT NULL
);


ALTER TABLE public.iclock_privatemessage OWNER TO postgres;

--
-- TOC entry 352 (class 1259 OID 27784)
-- Name: iclock_privatemessage_id_seq; Type: SEQUENCE; Schema: public; Owner: postgres
--

CREATE SEQUENCE public.iclock_privatemessage_id_seq
    AS integer
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;


ALTER SEQUENCE public.iclock_privatemessage_id_seq OWNER TO postgres;

--
-- TOC entry 4787 (class 0 OID 0)
-- Dependencies: 352
-- Name: iclock_privatemessage_id_seq; Type: SEQUENCE OWNED BY; Schema: public; Owner: postgres
--

ALTER SEQUENCE public.iclock_privatemessage_id_seq OWNED BY public.iclock_privatemessage.id;


--
-- TOC entry 353 (class 1259 OID 27786)
-- Name: iclock_publicmessage; Type: TABLE; Schema: public; Owner: postgres
--

CREATE TABLE public.iclock_publicmessage (
    id integer NOT NULL,
    create_time timestamp with time zone,
    create_user character varying(150),
    change_time timestamp with time zone,
    change_user character varying(150),
    status smallint NOT NULL,
    uid character varying(36),
    start_time timestamp with time zone NOT NULL,
    duration integer NOT NULL,
    content text NOT NULL,
    last_send timestamp with time zone,
    terminal_id integer NOT NULL
);


ALTER TABLE public.iclock_publicmessage OWNER TO postgres;

--
-- TOC entry 354 (class 1259 OID 27792)
-- Name: iclock_publicmessage_id_seq; Type: SEQUENCE; Schema: public; Owner: postgres
--

CREATE SEQUENCE public.iclock_publicmessage_id_seq
    AS integer
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;


ALTER SEQUENCE public.iclock_publicmessage_id_seq OWNER TO postgres;

--
-- TOC entry 4788 (class 0 OID 0)
-- Dependencies: 354
-- Name: iclock_publicmessage_id_seq; Type: SEQUENCE OWNED BY; Schema: public; Owner: postgres
--

ALTER SEQUENCE public.iclock_publicmessage_id_seq OWNED BY public.iclock_publicmessage.id;


--
-- TOC entry 355 (class 1259 OID 27794)
-- Name: iclock_terminal; Type: TABLE; Schema: public; Owner: postgres
--

CREATE TABLE public.iclock_terminal (
    id integer NOT NULL,
    create_time timestamp with time zone,
    create_user character varying(150),
    change_time timestamp with time zone,
    change_user character varying(150),
    status smallint NOT NULL,
    sn character varying(50) NOT NULL,
    alias character varying(50) NOT NULL,
    ip_address inet NOT NULL,
    real_ip inet,
    state integer NOT NULL,
    terminal_tz smallint NOT NULL,
    heartbeat integer NOT NULL,
    transfer_mode smallint NOT NULL,
    transfer_interval integer NOT NULL,
    transfer_time character varying(100) NOT NULL,
    product_type smallint,
    is_attendance smallint NOT NULL,
    is_registration smallint NOT NULL,
    purpose smallint,
    controller_type smallint,
    authentication smallint NOT NULL,
    style character varying(20),
    upload_flag character varying(10),
    fw_ver character varying(100),
    push_protocol character varying(30) NOT NULL,
    push_ver character varying(30),
    language integer,
    is_tft boolean NOT NULL,
    terminal_name character varying(30),
    platform character varying(30),
    oem_vendor character varying(50),
    log_stamp character varying(30),
    op_log_stamp character varying(30),
    capture_stamp character varying(30),
    user_count integer,
    user_capacity integer,
    photo_func_on boolean NOT NULL,
    transaction_count integer,
    transaction_capacity integer,
    fp_func_on boolean NOT NULL,
    fp_count integer,
    fp_capacity integer,
    fp_alg_ver character varying(10),
    face_func_on boolean NOT NULL,
    face_count integer,
    face_capacity integer,
    face_alg_ver character varying(10),
    fv_func_on boolean NOT NULL,
    fv_count integer,
    fv_capacity integer,
    fv_alg_ver character varying(10),
    palm_func_on boolean NOT NULL,
    palm_count integer,
    palm_capacity integer,
    palm_alg_ver character varying(10),
    lock_func smallint NOT NULL,
    last_activity timestamp with time zone,
    upload_time timestamp with time zone,
    push_time timestamp with time zone,
    is_access smallint NOT NULL,
    area_id integer,
    company_id integer
);


ALTER TABLE public.iclock_terminal OWNER TO postgres;

--
-- TOC entry 356 (class 1259 OID 27800)
-- Name: iclock_terminal_id_seq; Type: SEQUENCE; Schema: public; Owner: postgres
--

CREATE SEQUENCE public.iclock_terminal_id_seq
    AS integer
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;


ALTER SEQUENCE public.iclock_terminal_id_seq OWNER TO postgres;

--
-- TOC entry 4789 (class 0 OID 0)
-- Dependencies: 356
-- Name: iclock_terminal_id_seq; Type: SEQUENCE OWNED BY; Schema: public; Owner: postgres
--

ALTER SEQUENCE public.iclock_terminal_id_seq OWNED BY public.iclock_terminal.id;


--
-- TOC entry 357 (class 1259 OID 27802)
-- Name: iclock_terminalcommand; Type: TABLE; Schema: public; Owner: postgres
--

CREATE TABLE public.iclock_terminalcommand (
    id integer NOT NULL,
    content text NOT NULL,
    commit_time timestamp with time zone NOT NULL,
    transfer_time timestamp with time zone,
    return_time timestamp with time zone,
    return_value integer,
    terminal_id integer NOT NULL
);


ALTER TABLE public.iclock_terminalcommand OWNER TO postgres;

--
-- TOC entry 358 (class 1259 OID 27808)
-- Name: iclock_terminalcommand_id_seq; Type: SEQUENCE; Schema: public; Owner: postgres
--

CREATE SEQUENCE public.iclock_terminalcommand_id_seq
    AS integer
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;


ALTER SEQUENCE public.iclock_terminalcommand_id_seq OWNER TO postgres;

--
-- TOC entry 4790 (class 0 OID 0)
-- Dependencies: 358
-- Name: iclock_terminalcommand_id_seq; Type: SEQUENCE OWNED BY; Schema: public; Owner: postgres
--

ALTER SEQUENCE public.iclock_terminalcommand_id_seq OWNED BY public.iclock_terminalcommand.id;


--
-- TOC entry 359 (class 1259 OID 27810)
-- Name: iclock_terminalcommandlog; Type: TABLE; Schema: public; Owner: postgres
--

CREATE TABLE public.iclock_terminalcommandlog (
    id integer NOT NULL,
    content text NOT NULL,
    commit_time timestamp with time zone NOT NULL,
    transfer_time timestamp with time zone,
    return_time timestamp with time zone,
    return_value integer,
    package integer,
    terminal_id integer NOT NULL
);


ALTER TABLE public.iclock_terminalcommandlog OWNER TO postgres;

--
-- TOC entry 360 (class 1259 OID 27816)
-- Name: iclock_terminalcommandlog_id_seq; Type: SEQUENCE; Schema: public; Owner: postgres
--

CREATE SEQUENCE public.iclock_terminalcommandlog_id_seq
    AS integer
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;


ALTER SEQUENCE public.iclock_terminalcommandlog_id_seq OWNER TO postgres;

--
-- TOC entry 4791 (class 0 OID 0)
-- Dependencies: 360
-- Name: iclock_terminalcommandlog_id_seq; Type: SEQUENCE OWNED BY; Schema: public; Owner: postgres
--

ALTER SEQUENCE public.iclock_terminalcommandlog_id_seq OWNED BY public.iclock_terminalcommandlog.id;


--
-- TOC entry 361 (class 1259 OID 27818)
-- Name: iclock_terminalemployee; Type: TABLE; Schema: public; Owner: postgres
--

CREATE TABLE public.iclock_terminalemployee (
    id integer NOT NULL,
    terminal_sn character varying(50) NOT NULL,
    emp_code character varying(20) NOT NULL,
    privilege smallint NOT NULL
);


ALTER TABLE public.iclock_terminalemployee OWNER TO postgres;

--
-- TOC entry 362 (class 1259 OID 27821)
-- Name: iclock_terminalemployee_id_seq; Type: SEQUENCE; Schema: public; Owner: postgres
--

CREATE SEQUENCE public.iclock_terminalemployee_id_seq
    AS integer
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;


ALTER SEQUENCE public.iclock_terminalemployee_id_seq OWNER TO postgres;

--
-- TOC entry 4792 (class 0 OID 0)
-- Dependencies: 362
-- Name: iclock_terminalemployee_id_seq; Type: SEQUENCE OWNED BY; Schema: public; Owner: postgres
--

ALTER SEQUENCE public.iclock_terminalemployee_id_seq OWNED BY public.iclock_terminalemployee.id;


--
-- TOC entry 363 (class 1259 OID 27823)
-- Name: iclock_terminallog; Type: TABLE; Schema: public; Owner: postgres
--

CREATE TABLE public.iclock_terminallog (
    id integer NOT NULL,
    terminal_tz smallint,
    admin character varying(50),
    action_name smallint,
    action_time timestamp with time zone,
    object character varying(50),
    param1 integer,
    param2 integer,
    param3 integer,
    upload_time timestamp with time zone,
    terminal_id integer NOT NULL
);


ALTER TABLE public.iclock_terminallog OWNER TO postgres;

--
-- TOC entry 364 (class 1259 OID 27826)
-- Name: iclock_terminallog_id_seq; Type: SEQUENCE; Schema: public; Owner: postgres
--

CREATE SEQUENCE public.iclock_terminallog_id_seq
    AS integer
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;


ALTER SEQUENCE public.iclock_terminallog_id_seq OWNER TO postgres;

--
-- TOC entry 4793 (class 0 OID 0)
-- Dependencies: 364
-- Name: iclock_terminallog_id_seq; Type: SEQUENCE OWNED BY; Schema: public; Owner: postgres
--

ALTER SEQUENCE public.iclock_terminallog_id_seq OWNED BY public.iclock_terminallog.id;


--
-- TOC entry 365 (class 1259 OID 27828)
-- Name: iclock_terminalparameter; Type: TABLE; Schema: public; Owner: postgres
--

CREATE TABLE public.iclock_terminalparameter (
    id integer NOT NULL,
    param_type character varying(10),
    param_name character varying(30) NOT NULL,
    param_value character varying(100) NOT NULL,
    terminal_id integer NOT NULL
);


ALTER TABLE public.iclock_terminalparameter OWNER TO postgres;

--
-- TOC entry 366 (class 1259 OID 27831)
-- Name: iclock_terminalparameter_id_seq; Type: SEQUENCE; Schema: public; Owner: postgres
--

CREATE SEQUENCE public.iclock_terminalparameter_id_seq
    AS integer
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;


ALTER SEQUENCE public.iclock_terminalparameter_id_seq OWNER TO postgres;

--
-- TOC entry 4794 (class 0 OID 0)
-- Dependencies: 366
-- Name: iclock_terminalparameter_id_seq; Type: SEQUENCE OWNED BY; Schema: public; Owner: postgres
--

ALTER SEQUENCE public.iclock_terminalparameter_id_seq OWNED BY public.iclock_terminalparameter.id;


--
-- TOC entry 367 (class 1259 OID 27833)
-- Name: iclock_terminaluploadlog; Type: TABLE; Schema: public; Owner: postgres
--

CREATE TABLE public.iclock_terminaluploadlog (
    id integer NOT NULL,
    event character varying(80) NOT NULL,
    content character varying(80) NOT NULL,
    upload_count integer NOT NULL,
    error_count integer NOT NULL,
    upload_time timestamp with time zone NOT NULL,
    terminal_id integer NOT NULL
);


ALTER TABLE public.iclock_terminaluploadlog OWNER TO postgres;

--
-- TOC entry 368 (class 1259 OID 27836)
-- Name: iclock_terminaluploadlog_id_seq; Type: SEQUENCE; Schema: public; Owner: postgres
--

CREATE SEQUENCE public.iclock_terminaluploadlog_id_seq
    AS integer
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;


ALTER SEQUENCE public.iclock_terminaluploadlog_id_seq OWNER TO postgres;

--
-- TOC entry 4795 (class 0 OID 0)
-- Dependencies: 368
-- Name: iclock_terminaluploadlog_id_seq; Type: SEQUENCE OWNED BY; Schema: public; Owner: postgres
--

ALTER SEQUENCE public.iclock_terminaluploadlog_id_seq OWNED BY public.iclock_terminaluploadlog.id;


--
-- TOC entry 369 (class 1259 OID 27838)
-- Name: iclock_terminalworkcode; Type: TABLE; Schema: public; Owner: postgres
--

CREATE TABLE public.iclock_terminalworkcode (
    id integer NOT NULL,
    create_time timestamp with time zone,
    create_user character varying(150),
    change_time timestamp with time zone,
    change_user character varying(150),
    status smallint NOT NULL,
    code character varying(8) NOT NULL,
    alias character varying(24) NOT NULL,
    last_activity timestamp with time zone
);


ALTER TABLE public.iclock_terminalworkcode OWNER TO postgres;

--
-- TOC entry 370 (class 1259 OID 27841)
-- Name: iclock_terminalworkcode_id_seq; Type: SEQUENCE; Schema: public; Owner: postgres
--

CREATE SEQUENCE public.iclock_terminalworkcode_id_seq
    AS integer
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;


ALTER SEQUENCE public.iclock_terminalworkcode_id_seq OWNER TO postgres;

--
-- TOC entry 4796 (class 0 OID 0)
-- Dependencies: 370
-- Name: iclock_terminalworkcode_id_seq; Type: SEQUENCE OWNED BY; Schema: public; Owner: postgres
--

ALTER SEQUENCE public.iclock_terminalworkcode_id_seq OWNED BY public.iclock_terminalworkcode.id;


--
-- TOC entry 371 (class 1259 OID 27843)
-- Name: iclock_transaction; Type: TABLE; Schema: public; Owner: postgres
--

CREATE TABLE public.iclock_transaction (
    id integer NOT NULL,
    emp_code character varying(20) NOT NULL,
    punch_time timestamp with time zone NOT NULL,
    punch_state character varying(5) NOT NULL,
    verify_type integer NOT NULL,
    work_code character varying(20),
    terminal_sn character varying(50),
    terminal_alias character varying(50),
    area_alias character varying(100),
    longitude double precision,
    latitude double precision,
    gps_location text,
    mobile character varying(50),
    source smallint,
    purpose smallint,
    crc character varying(100),
    is_attendance smallint,
    reserved character varying(100),
    upload_time timestamp with time zone,
    sync_status smallint,
    sync_time timestamp with time zone,
    is_mask smallint,
    temperature numeric(4,1),
    emp_id integer,
    terminal_id integer
);


ALTER TABLE public.iclock_transaction OWNER TO postgres;

--
-- TOC entry 372 (class 1259 OID 27849)
-- Name: iclock_transaction_id_seq; Type: SEQUENCE; Schema: public; Owner: postgres
--

CREATE SEQUENCE public.iclock_transaction_id_seq
    AS integer
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;


ALTER SEQUENCE public.iclock_transaction_id_seq OWNER TO postgres;

--
-- TOC entry 4797 (class 0 OID 0)
-- Dependencies: 372
-- Name: iclock_transaction_id_seq; Type: SEQUENCE OWNED BY; Schema: public; Owner: postgres
--

ALTER SEQUENCE public.iclock_transaction_id_seq OWNED BY public.iclock_transaction.id;


--
-- TOC entry 373 (class 1259 OID 27851)
-- Name: iclock_transactionproofcmd; Type: TABLE; Schema: public; Owner: postgres
--

CREATE TABLE public.iclock_transactionproofcmd (
    id integer NOT NULL,
    action_time timestamp with time zone NOT NULL,
    start_time timestamp with time zone NOT NULL,
    end_time timestamp with time zone NOT NULL,
    terminal_count integer,
    server_count integer,
    flag smallint,
    reserved_init integer,
    reserved_float double precision,
    reserved_char character varying(30),
    terminal_id integer NOT NULL
);


ALTER TABLE public.iclock_transactionproofcmd OWNER TO postgres;

--
-- TOC entry 374 (class 1259 OID 27854)
-- Name: iclock_transactionproofcmd_id_seq; Type: SEQUENCE; Schema: public; Owner: postgres
--

CREATE SEQUENCE public.iclock_transactionproofcmd_id_seq
    AS integer
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;


ALTER SEQUENCE public.iclock_transactionproofcmd_id_seq OWNER TO postgres;

--
-- TOC entry 4798 (class 0 OID 0)
-- Dependencies: 374
-- Name: iclock_transactionproofcmd_id_seq; Type: SEQUENCE OWNED BY; Schema: public; Owner: postgres
--

ALTER SEQUENCE public.iclock_transactionproofcmd_id_seq OWNED BY public.iclock_transactionproofcmd.id;


--
-- TOC entry 375 (class 1259 OID 27856)
-- Name: mobile_announcement; Type: TABLE; Schema: public; Owner: postgres
--

CREATE TABLE public.mobile_announcement (
    id integer NOT NULL,
    subject character varying(100) NOT NULL,
    content text NOT NULL,
    category smallint NOT NULL,
    sender character varying(50),
    system_sender character varying(50),
    create_time timestamp with time zone,
    receiver_id integer
);


ALTER TABLE public.mobile_announcement OWNER TO postgres;

--
-- TOC entry 376 (class 1259 OID 27862)
-- Name: mobile_announcement_id_seq; Type: SEQUENCE; Schema: public; Owner: postgres
--

CREATE SEQUENCE public.mobile_announcement_id_seq
    AS integer
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;


ALTER SEQUENCE public.mobile_announcement_id_seq OWNER TO postgres;

--
-- TOC entry 4799 (class 0 OID 0)
-- Dependencies: 376
-- Name: mobile_announcement_id_seq; Type: SEQUENCE OWNED BY; Schema: public; Owner: postgres
--

ALTER SEQUENCE public.mobile_announcement_id_seq OWNED BY public.mobile_announcement.id;


--
-- TOC entry 377 (class 1259 OID 27864)
-- Name: mobile_appactionlog; Type: TABLE; Schema: public; Owner: postgres
--

CREATE TABLE public.mobile_appactionlog (
    id integer NOT NULL,
    "user" character varying(20) NOT NULL,
    client character varying(50),
    action character varying(50),
    params text,
    describe text,
    request_status smallint NOT NULL,
    action_time timestamp with time zone NOT NULL,
    remote_ip character varying(20)
);


ALTER TABLE public.mobile_appactionlog OWNER TO postgres;

--
-- TOC entry 378 (class 1259 OID 27870)
-- Name: mobile_appactionlog_id_seq; Type: SEQUENCE; Schema: public; Owner: postgres
--

CREATE SEQUENCE public.mobile_appactionlog_id_seq
    AS integer
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;


ALTER SEQUENCE public.mobile_appactionlog_id_seq OWNER TO postgres;

--
-- TOC entry 4800 (class 0 OID 0)
-- Dependencies: 378
-- Name: mobile_appactionlog_id_seq; Type: SEQUENCE OWNED BY; Schema: public; Owner: postgres
--

ALTER SEQUENCE public.mobile_appactionlog_id_seq OWNED BY public.mobile_appactionlog.id;


--
-- TOC entry 379 (class 1259 OID 27872)
-- Name: mobile_applist; Type: TABLE; Schema: public; Owner: postgres
--

CREATE TABLE public.mobile_applist (
    id integer NOT NULL,
    username character varying(50) NOT NULL,
    login_time timestamp with time zone NOT NULL,
    last_active timestamp with time zone NOT NULL,
    token character varying(100) NOT NULL,
    device_token text NOT NULL,
    client_id character varying(100) NOT NULL,
    client_category smallint NOT NULL,
    active smallint,
    enable smallint
);


ALTER TABLE public.mobile_applist OWNER TO postgres;

--
-- TOC entry 380 (class 1259 OID 27878)
-- Name: mobile_applist_id_seq; Type: SEQUENCE; Schema: public; Owner: postgres
--

CREATE SEQUENCE public.mobile_applist_id_seq
    AS integer
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;


ALTER SEQUENCE public.mobile_applist_id_seq OWNER TO postgres;

--
-- TOC entry 4801 (class 0 OID 0)
-- Dependencies: 380
-- Name: mobile_applist_id_seq; Type: SEQUENCE OWNED BY; Schema: public; Owner: postgres
--

ALTER SEQUENCE public.mobile_applist_id_seq OWNED BY public.mobile_applist.id;


--
-- TOC entry 381 (class 1259 OID 27880)
-- Name: mobile_appnotification; Type: TABLE; Schema: public; Owner: postgres
--

CREATE TABLE public.mobile_appnotification (
    id integer NOT NULL,
    sender character varying(50),
    system_sender character varying(50),
    category smallint NOT NULL,
    sub_category integer,
    content text,
    source integer,
    notification_time timestamp with time zone NOT NULL,
    read_status smallint NOT NULL,
    read_time timestamp with time zone,
    receiver_id integer NOT NULL
);


ALTER TABLE public.mobile_appnotification OWNER TO postgres;

--
-- TOC entry 382 (class 1259 OID 27886)
-- Name: mobile_appnotification_id_seq; Type: SEQUENCE; Schema: public; Owner: postgres
--

CREATE SEQUENCE public.mobile_appnotification_id_seq
    AS integer
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;


ALTER SEQUENCE public.mobile_appnotification_id_seq OWNER TO postgres;

--
-- TOC entry 4802 (class 0 OID 0)
-- Dependencies: 382
-- Name: mobile_appnotification_id_seq; Type: SEQUENCE OWNED BY; Schema: public; Owner: postgres
--

ALTER SEQUENCE public.mobile_appnotification_id_seq OWNED BY public.mobile_appnotification.id;


--
-- TOC entry 383 (class 1259 OID 27888)
-- Name: mobile_gpsfordepartment; Type: TABLE; Schema: public; Owner: postgres
--

CREATE TABLE public.mobile_gpsfordepartment (
    id integer NOT NULL,
    create_time timestamp with time zone,
    create_user character varying(150),
    change_time timestamp with time zone,
    change_user character varying(150),
    status smallint NOT NULL,
    location character varying(100) NOT NULL,
    longitude double precision NOT NULL,
    latitude double precision NOT NULL,
    distance integer NOT NULL,
    start_date date NOT NULL,
    end_date date NOT NULL,
    department_id integer NOT NULL
);


ALTER TABLE public.mobile_gpsfordepartment OWNER TO postgres;

--
-- TOC entry 384 (class 1259 OID 27891)
-- Name: mobile_gpsfordepartment_id_seq; Type: SEQUENCE; Schema: public; Owner: postgres
--

CREATE SEQUENCE public.mobile_gpsfordepartment_id_seq
    AS integer
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;


ALTER SEQUENCE public.mobile_gpsfordepartment_id_seq OWNER TO postgres;

--
-- TOC entry 4803 (class 0 OID 0)
-- Dependencies: 384
-- Name: mobile_gpsfordepartment_id_seq; Type: SEQUENCE OWNED BY; Schema: public; Owner: postgres
--

ALTER SEQUENCE public.mobile_gpsfordepartment_id_seq OWNED BY public.mobile_gpsfordepartment.id;


--
-- TOC entry 385 (class 1259 OID 27893)
-- Name: mobile_gpsforemployee; Type: TABLE; Schema: public; Owner: postgres
--

CREATE TABLE public.mobile_gpsforemployee (
    id integer NOT NULL,
    create_time timestamp with time zone,
    create_user character varying(150),
    change_time timestamp with time zone,
    change_user character varying(150),
    status smallint NOT NULL,
    location character varying(100) NOT NULL,
    longitude double precision NOT NULL,
    latitude double precision NOT NULL,
    distance integer NOT NULL,
    start_date date NOT NULL,
    end_date date NOT NULL,
    employee_id integer NOT NULL
);


ALTER TABLE public.mobile_gpsforemployee OWNER TO postgres;

--
-- TOC entry 386 (class 1259 OID 27896)
-- Name: mobile_gpsforemployee_id_seq; Type: SEQUENCE; Schema: public; Owner: postgres
--

CREATE SEQUENCE public.mobile_gpsforemployee_id_seq
    AS integer
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;


ALTER SEQUENCE public.mobile_gpsforemployee_id_seq OWNER TO postgres;

--
-- TOC entry 4804 (class 0 OID 0)
-- Dependencies: 386
-- Name: mobile_gpsforemployee_id_seq; Type: SEQUENCE OWNED BY; Schema: public; Owner: postgres
--

ALTER SEQUENCE public.mobile_gpsforemployee_id_seq OWNED BY public.mobile_gpsforemployee.id;


--
-- TOC entry 387 (class 1259 OID 27898)
-- Name: notifications_notification; Type: TABLE; Schema: public; Owner: postgres
--

CREATE TABLE public.notifications_notification (
    id integer NOT NULL,
    content character varying(999),
    is_sent boolean NOT NULL,
    event smallint,
    commit_time date NOT NULL,
    send_time date,
    exception_id character varying(255),
    content_type_id character varying(255)
);


ALTER TABLE public.notifications_notification OWNER TO postgres;

--
-- TOC entry 388 (class 1259 OID 27904)
-- Name: notifications_notification_id_seq; Type: SEQUENCE; Schema: public; Owner: postgres
--

CREATE SEQUENCE public.notifications_notification_id_seq
    AS integer
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;


ALTER SEQUENCE public.notifications_notification_id_seq OWNER TO postgres;

--
-- TOC entry 4805 (class 0 OID 0)
-- Dependencies: 388
-- Name: notifications_notification_id_seq; Type: SEQUENCE OWNED BY; Schema: public; Owner: postgres
--

ALTER SEQUENCE public.notifications_notification_id_seq OWNED BY public.notifications_notification.id;


--
-- TOC entry 389 (class 1259 OID 27906)
-- Name: payroll_deductionformula; Type: TABLE; Schema: public; Owner: postgres
--

CREATE TABLE public.payroll_deductionformula (
    id integer NOT NULL,
    name character varying(30) NOT NULL,
    formula character varying(100) NOT NULL,
    remark text
);


ALTER TABLE public.payroll_deductionformula OWNER TO postgres;

--
-- TOC entry 390 (class 1259 OID 27912)
-- Name: payroll_deductionformula_id_seq; Type: SEQUENCE; Schema: public; Owner: postgres
--

CREATE SEQUENCE public.payroll_deductionformula_id_seq
    AS integer
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;


ALTER SEQUENCE public.payroll_deductionformula_id_seq OWNER TO postgres;

--
-- TOC entry 4806 (class 0 OID 0)
-- Dependencies: 390
-- Name: payroll_deductionformula_id_seq; Type: SEQUENCE OWNED BY; Schema: public; Owner: postgres
--

ALTER SEQUENCE public.payroll_deductionformula_id_seq OWNED BY public.payroll_deductionformula.id;


--
-- TOC entry 391 (class 1259 OID 27914)
-- Name: payroll_emploan; Type: TABLE; Schema: public; Owner: postgres
--

CREATE TABLE public.payroll_emploan (
    id integer NOT NULL,
    create_time timestamp with time zone,
    create_user character varying(150),
    change_time timestamp with time zone,
    change_user character varying(150),
    status smallint NOT NULL,
    loan_amount integer NOT NULL,
    loan_time timestamp with time zone NOT NULL,
    refund_cycle smallint NOT NULL,
    per_cycle_refund double precision NOT NULL,
    loan_clean_time timestamp with time zone,
    remark character varying(300),
    employee_id integer
);


ALTER TABLE public.payroll_emploan OWNER TO postgres;

--
-- TOC entry 392 (class 1259 OID 27920)
-- Name: payroll_emploan_id_seq; Type: SEQUENCE; Schema: public; Owner: postgres
--

CREATE SEQUENCE public.payroll_emploan_id_seq
    AS integer
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;


ALTER SEQUENCE public.payroll_emploan_id_seq OWNER TO postgres;

--
-- TOC entry 4807 (class 0 OID 0)
-- Dependencies: 392
-- Name: payroll_emploan_id_seq; Type: SEQUENCE OWNED BY; Schema: public; Owner: postgres
--

ALTER SEQUENCE public.payroll_emploan_id_seq OWNED BY public.payroll_emploan.id;


--
-- TOC entry 393 (class 1259 OID 27922)
-- Name: payroll_emppayrollprofile; Type: TABLE; Schema: public; Owner: postgres
--

CREATE TABLE public.payroll_emppayrollprofile (
    id integer NOT NULL,
    payment_mode smallint,
    payment_type smallint,
    bank_name character varying(30),
    bank_account character varying(30),
    personnel_id character varying(30),
    agent_id character varying(30),
    agent_account character varying(30),
    employee_id integer NOT NULL
);


ALTER TABLE public.payroll_emppayrollprofile OWNER TO postgres;

--
-- TOC entry 394 (class 1259 OID 27925)
-- Name: payroll_emppayrollprofile_id_seq; Type: SEQUENCE; Schema: public; Owner: postgres
--

CREATE SEQUENCE public.payroll_emppayrollprofile_id_seq
    AS integer
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;


ALTER SEQUENCE public.payroll_emppayrollprofile_id_seq OWNER TO postgres;

--
-- TOC entry 4808 (class 0 OID 0)
-- Dependencies: 394
-- Name: payroll_emppayrollprofile_id_seq; Type: SEQUENCE OWNED BY; Schema: public; Owner: postgres
--

ALTER SEQUENCE public.payroll_emppayrollprofile_id_seq OWNED BY public.payroll_emppayrollprofile.id;


--
-- TOC entry 395 (class 1259 OID 27927)
-- Name: payroll_exceptionformula; Type: TABLE; Schema: public; Owner: postgres
--

CREATE TABLE public.payroll_exceptionformula (
    id integer NOT NULL,
    name character varying(30) NOT NULL,
    exception_type smallint NOT NULL,
    formula character varying(100) NOT NULL,
    remark text
);


ALTER TABLE public.payroll_exceptionformula OWNER TO postgres;

--
-- TOC entry 396 (class 1259 OID 27933)
-- Name: payroll_exceptionformula_id_seq; Type: SEQUENCE; Schema: public; Owner: postgres
--

CREATE SEQUENCE public.payroll_exceptionformula_id_seq
    AS integer
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;


ALTER SEQUENCE public.payroll_exceptionformula_id_seq OWNER TO postgres;

--
-- TOC entry 4809 (class 0 OID 0)
-- Dependencies: 396
-- Name: payroll_exceptionformula_id_seq; Type: SEQUENCE OWNED BY; Schema: public; Owner: postgres
--

ALTER SEQUENCE public.payroll_exceptionformula_id_seq OWNED BY public.payroll_exceptionformula.id;


--
-- TOC entry 397 (class 1259 OID 27935)
-- Name: payroll_extradeduction; Type: TABLE; Schema: public; Owner: postgres
--

CREATE TABLE public.payroll_extradeduction (
    id integer NOT NULL,
    create_time timestamp with time zone,
    create_user character varying(150),
    change_time timestamp with time zone,
    change_user character varying(150),
    status smallint NOT NULL,
    amount integer NOT NULL,
    issued_time timestamp with time zone NOT NULL,
    remark character varying(300),
    employee_id integer
);


ALTER TABLE public.payroll_extradeduction OWNER TO postgres;

--
-- TOC entry 398 (class 1259 OID 27941)
-- Name: payroll_extradeduction_id_seq; Type: SEQUENCE; Schema: public; Owner: postgres
--

CREATE SEQUENCE public.payroll_extradeduction_id_seq
    AS integer
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;


ALTER SEQUENCE public.payroll_extradeduction_id_seq OWNER TO postgres;

--
-- TOC entry 4810 (class 0 OID 0)
-- Dependencies: 398
-- Name: payroll_extradeduction_id_seq; Type: SEQUENCE OWNED BY; Schema: public; Owner: postgres
--

ALTER SEQUENCE public.payroll_extradeduction_id_seq OWNED BY public.payroll_extradeduction.id;


--
-- TOC entry 399 (class 1259 OID 27943)
-- Name: payroll_extraincrease; Type: TABLE; Schema: public; Owner: postgres
--

CREATE TABLE public.payroll_extraincrease (
    id integer NOT NULL,
    create_time timestamp with time zone,
    create_user character varying(150),
    change_time timestamp with time zone,
    change_user character varying(150),
    status smallint NOT NULL,
    amount integer NOT NULL,
    issued_time timestamp with time zone NOT NULL,
    remark character varying(300),
    employee_id integer
);


ALTER TABLE public.payroll_extraincrease OWNER TO postgres;

--
-- TOC entry 400 (class 1259 OID 27949)
-- Name: payroll_extraincrease_id_seq; Type: SEQUENCE; Schema: public; Owner: postgres
--

CREATE SEQUENCE public.payroll_extraincrease_id_seq
    AS integer
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;


ALTER SEQUENCE public.payroll_extraincrease_id_seq OWNER TO postgres;

--
-- TOC entry 4811 (class 0 OID 0)
-- Dependencies: 400
-- Name: payroll_extraincrease_id_seq; Type: SEQUENCE OWNED BY; Schema: public; Owner: postgres
--

ALTER SEQUENCE public.payroll_extraincrease_id_seq OWNED BY public.payroll_extraincrease.id;


--
-- TOC entry 401 (class 1259 OID 27951)
-- Name: payroll_increasementformula; Type: TABLE; Schema: public; Owner: postgres
--

CREATE TABLE public.payroll_increasementformula (
    id integer NOT NULL,
    name character varying(30) NOT NULL,
    formula character varying(100) NOT NULL,
    remark text
);


ALTER TABLE public.payroll_increasementformula OWNER TO postgres;

--
-- TOC entry 402 (class 1259 OID 27957)
-- Name: payroll_increasementformula_id_seq; Type: SEQUENCE; Schema: public; Owner: postgres
--

CREATE SEQUENCE public.payroll_increasementformula_id_seq
    AS integer
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;


ALTER SEQUENCE public.payroll_increasementformula_id_seq OWNER TO postgres;

--
-- TOC entry 4812 (class 0 OID 0)
-- Dependencies: 402
-- Name: payroll_increasementformula_id_seq; Type: SEQUENCE OWNED BY; Schema: public; Owner: postgres
--

ALTER SEQUENCE public.payroll_increasementformula_id_seq OWNED BY public.payroll_increasementformula.id;


--
-- TOC entry 403 (class 1259 OID 27959)
-- Name: payroll_leaveformula; Type: TABLE; Schema: public; Owner: postgres
--

CREATE TABLE public.payroll_leaveformula (
    id integer NOT NULL,
    name character varying(30) NOT NULL,
    formula character varying(100) NOT NULL,
    remark text,
    category_id integer NOT NULL
);


ALTER TABLE public.payroll_leaveformula OWNER TO postgres;

--
-- TOC entry 404 (class 1259 OID 27965)
-- Name: payroll_leaveformula_id_seq; Type: SEQUENCE; Schema: public; Owner: postgres
--

CREATE SEQUENCE public.payroll_leaveformula_id_seq
    AS integer
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;


ALTER SEQUENCE public.payroll_leaveformula_id_seq OWNER TO postgres;

--
-- TOC entry 4813 (class 0 OID 0)
-- Dependencies: 404
-- Name: payroll_leaveformula_id_seq; Type: SEQUENCE OWNED BY; Schema: public; Owner: postgres
--

ALTER SEQUENCE public.payroll_leaveformula_id_seq OWNED BY public.payroll_leaveformula.id;


--
-- TOC entry 405 (class 1259 OID 27967)
-- Name: payroll_monthlysalary; Type: TABLE; Schema: public; Owner: postgres
--

CREATE TABLE public.payroll_monthlysalary (
    id integer NOT NULL,
    calc_time date,
    basic_salary double precision,
    effective_date date,
    format_dict text,
    ot1 double precision,
    ot2 double precision,
    ot3 double precision,
    normal_ot double precision,
    weekend_ot double precision,
    holiday_ot double precision,
    late_time double precision,
    early_leave double precision,
    absent_time double precision,
    increase double precision,
    deduction double precision,
    leave text,
    ot1_formula text,
    ot2_formula text,
    ot3_formula text,
    normal_ot_formula text,
    weekend_ot_formula text,
    holiday_ot_formula text,
    late_time_formula text,
    early_leave_formula text,
    absent_time_formula text,
    increase_formula text,
    deduction_formula text,
    leave_formula text,
    ot1_formula_name text,
    ot2_formula_name text,
    ot3_formula_name text,
    normal_ot_formula_name text,
    weekend_ot_formula_name text,
    holiday_ot_formula_name text,
    late_time_formula_name text,
    early_leave_formula_name text,
    absent_time_formula_name text,
    increase_formula_name text,
    deduction_formula_name text,
    leave_formula_name text,
    extra_increase double precision,
    extra_deduction double precision,
    total_loan_amount double precision,
    refund_loan_amount double precision,
    unrefund_loan_amount double precision,
    loan_deduction double precision,
    loan_increase double precision,
    advance_increase double precision,
    advance_deduction double precision,
    reimbursement double precision,
    total_increase_formula text,
    total_increase_formula_name text,
    total_increase_expression text,
    total_increase double precision,
    total_deduction_formula text,
    total_deduction_formula_name text,
    total_deduction_expression text,
    total_deduction double precision,
    total_salary_expression text,
    total_salary double precision,
    employee_id integer NOT NULL
);


ALTER TABLE public.payroll_monthlysalary OWNER TO postgres;

--
-- TOC entry 406 (class 1259 OID 27973)
-- Name: payroll_monthlysalary_id_seq; Type: SEQUENCE; Schema: public; Owner: postgres
--

CREATE SEQUENCE public.payroll_monthlysalary_id_seq
    AS integer
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;


ALTER SEQUENCE public.payroll_monthlysalary_id_seq OWNER TO postgres;

--
-- TOC entry 4814 (class 0 OID 0)
-- Dependencies: 406
-- Name: payroll_monthlysalary_id_seq; Type: SEQUENCE OWNED BY; Schema: public; Owner: postgres
--

ALTER SEQUENCE public.payroll_monthlysalary_id_seq OWNED BY public.payroll_monthlysalary.id;


--
-- TOC entry 407 (class 1259 OID 27975)
-- Name: payroll_overtimeformula; Type: TABLE; Schema: public; Owner: postgres
--

CREATE TABLE public.payroll_overtimeformula (
    id integer NOT NULL,
    name character varying(30) NOT NULL,
    overtime_level smallint NOT NULL,
    formula character varying(100) NOT NULL,
    remark text
);


ALTER TABLE public.payroll_overtimeformula OWNER TO postgres;

--
-- TOC entry 408 (class 1259 OID 27981)
-- Name: payroll_overtimeformula_id_seq; Type: SEQUENCE; Schema: public; Owner: postgres
--

CREATE SEQUENCE public.payroll_overtimeformula_id_seq
    AS integer
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;


ALTER SEQUENCE public.payroll_overtimeformula_id_seq OWNER TO postgres;

--
-- TOC entry 4815 (class 0 OID 0)
-- Dependencies: 408
-- Name: payroll_overtimeformula_id_seq; Type: SEQUENCE OWNED BY; Schema: public; Owner: postgres
--

ALTER SEQUENCE public.payroll_overtimeformula_id_seq OWNED BY public.payroll_overtimeformula.id;


--
-- TOC entry 409 (class 1259 OID 27983)
-- Name: payroll_reimbursement; Type: TABLE; Schema: public; Owner: postgres
--

CREATE TABLE public.payroll_reimbursement (
    id integer NOT NULL,
    rmb_amount integer NOT NULL,
    rmb_time timestamp with time zone NOT NULL,
    rmb_file character varying(200),
    rmb_remark character varying(300),
    employee_id integer
);


ALTER TABLE public.payroll_reimbursement OWNER TO postgres;

--
-- TOC entry 410 (class 1259 OID 27989)
-- Name: payroll_reimbursement_id_seq; Type: SEQUENCE; Schema: public; Owner: postgres
--

CREATE SEQUENCE public.payroll_reimbursement_id_seq
    AS integer
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;


ALTER SEQUENCE public.payroll_reimbursement_id_seq OWNER TO postgres;

--
-- TOC entry 4816 (class 0 OID 0)
-- Dependencies: 410
-- Name: payroll_reimbursement_id_seq; Type: SEQUENCE OWNED BY; Schema: public; Owner: postgres
--

ALTER SEQUENCE public.payroll_reimbursement_id_seq OWNED BY public.payroll_reimbursement.id;


--
-- TOC entry 411 (class 1259 OID 27991)
-- Name: payroll_salaryadvance; Type: TABLE; Schema: public; Owner: postgres
--

CREATE TABLE public.payroll_salaryadvance (
    id integer NOT NULL,
    advance_amount integer NOT NULL,
    advance_time timestamp with time zone NOT NULL,
    advance_remark character varying(300),
    employee_id integer
);


ALTER TABLE public.payroll_salaryadvance OWNER TO postgres;

--
-- TOC entry 412 (class 1259 OID 27994)
-- Name: payroll_salaryadvance_id_seq; Type: SEQUENCE; Schema: public; Owner: postgres
--

CREATE SEQUENCE public.payroll_salaryadvance_id_seq
    AS integer
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;


ALTER SEQUENCE public.payroll_salaryadvance_id_seq OWNER TO postgres;

--
-- TOC entry 4817 (class 0 OID 0)
-- Dependencies: 412
-- Name: payroll_salaryadvance_id_seq; Type: SEQUENCE OWNED BY; Schema: public; Owner: postgres
--

ALTER SEQUENCE public.payroll_salaryadvance_id_seq OWNED BY public.payroll_salaryadvance.id;


--
-- TOC entry 413 (class 1259 OID 27996)
-- Name: payroll_salarystructure; Type: TABLE; Schema: public; Owner: postgres
--

CREATE TABLE public.payroll_salarystructure (
    id integer NOT NULL,
    create_time timestamp with time zone,
    create_user character varying(150),
    change_time timestamp with time zone,
    change_user character varying(150),
    status smallint NOT NULL,
    salary_amount integer NOT NULL,
    effective_date date NOT NULL,
    salary_remark character varying(300),
    employee_id integer
);


ALTER TABLE public.payroll_salarystructure OWNER TO postgres;

--
-- TOC entry 414 (class 1259 OID 28002)
-- Name: payroll_salarystructure_deductionformula; Type: TABLE; Schema: public; Owner: postgres
--

CREATE TABLE public.payroll_salarystructure_deductionformula (
    id integer NOT NULL,
    salarystructure_id integer NOT NULL,
    deductionformula_id integer NOT NULL
);


ALTER TABLE public.payroll_salarystructure_deductionformula OWNER TO postgres;

--
-- TOC entry 415 (class 1259 OID 28005)
-- Name: payroll_salarystructure_deductionformula_id_seq; Type: SEQUENCE; Schema: public; Owner: postgres
--

CREATE SEQUENCE public.payroll_salarystructure_deductionformula_id_seq
    AS integer
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;


ALTER SEQUENCE public.payroll_salarystructure_deductionformula_id_seq OWNER TO postgres;

--
-- TOC entry 4818 (class 0 OID 0)
-- Dependencies: 415
-- Name: payroll_salarystructure_deductionformula_id_seq; Type: SEQUENCE OWNED BY; Schema: public; Owner: postgres
--

ALTER SEQUENCE public.payroll_salarystructure_deductionformula_id_seq OWNED BY public.payroll_salarystructure_deductionformula.id;


--
-- TOC entry 416 (class 1259 OID 28007)
-- Name: payroll_salarystructure_exceptionformula; Type: TABLE; Schema: public; Owner: postgres
--

CREATE TABLE public.payroll_salarystructure_exceptionformula (
    id integer NOT NULL,
    salarystructure_id integer NOT NULL,
    exceptionformula_id integer NOT NULL
);


ALTER TABLE public.payroll_salarystructure_exceptionformula OWNER TO postgres;

--
-- TOC entry 417 (class 1259 OID 28010)
-- Name: payroll_salarystructure_exceptionformula_id_seq; Type: SEQUENCE; Schema: public; Owner: postgres
--

CREATE SEQUENCE public.payroll_salarystructure_exceptionformula_id_seq
    AS integer
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;


ALTER SEQUENCE public.payroll_salarystructure_exceptionformula_id_seq OWNER TO postgres;

--
-- TOC entry 4819 (class 0 OID 0)
-- Dependencies: 417
-- Name: payroll_salarystructure_exceptionformula_id_seq; Type: SEQUENCE OWNED BY; Schema: public; Owner: postgres
--

ALTER SEQUENCE public.payroll_salarystructure_exceptionformula_id_seq OWNED BY public.payroll_salarystructure_exceptionformula.id;


--
-- TOC entry 418 (class 1259 OID 28012)
-- Name: payroll_salarystructure_id_seq; Type: SEQUENCE; Schema: public; Owner: postgres
--

CREATE SEQUENCE public.payroll_salarystructure_id_seq
    AS integer
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;


ALTER SEQUENCE public.payroll_salarystructure_id_seq OWNER TO postgres;

--
-- TOC entry 4820 (class 0 OID 0)
-- Dependencies: 418
-- Name: payroll_salarystructure_id_seq; Type: SEQUENCE OWNED BY; Schema: public; Owner: postgres
--

ALTER SEQUENCE public.payroll_salarystructure_id_seq OWNED BY public.payroll_salarystructure.id;


--
-- TOC entry 419 (class 1259 OID 28014)
-- Name: payroll_salarystructure_increasementformula; Type: TABLE; Schema: public; Owner: postgres
--

CREATE TABLE public.payroll_salarystructure_increasementformula (
    id integer NOT NULL,
    salarystructure_id integer NOT NULL,
    increasementformula_id integer NOT NULL
);


ALTER TABLE public.payroll_salarystructure_increasementformula OWNER TO postgres;

--
-- TOC entry 420 (class 1259 OID 28017)
-- Name: payroll_salarystructure_increasementformula_id_seq; Type: SEQUENCE; Schema: public; Owner: postgres
--

CREATE SEQUENCE public.payroll_salarystructure_increasementformula_id_seq
    AS integer
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;


ALTER SEQUENCE public.payroll_salarystructure_increasementformula_id_seq OWNER TO postgres;

--
-- TOC entry 4821 (class 0 OID 0)
-- Dependencies: 420
-- Name: payroll_salarystructure_increasementformula_id_seq; Type: SEQUENCE OWNED BY; Schema: public; Owner: postgres
--

ALTER SEQUENCE public.payroll_salarystructure_increasementformula_id_seq OWNED BY public.payroll_salarystructure_increasementformula.id;


--
-- TOC entry 421 (class 1259 OID 28019)
-- Name: payroll_salarystructure_leaveformula; Type: TABLE; Schema: public; Owner: postgres
--

CREATE TABLE public.payroll_salarystructure_leaveformula (
    id integer NOT NULL,
    salarystructure_id integer NOT NULL,
    leaveformula_id integer NOT NULL
);


ALTER TABLE public.payroll_salarystructure_leaveformula OWNER TO postgres;

--
-- TOC entry 422 (class 1259 OID 28022)
-- Name: payroll_salarystructure_leaveformula_id_seq; Type: SEQUENCE; Schema: public; Owner: postgres
--

CREATE SEQUENCE public.payroll_salarystructure_leaveformula_id_seq
    AS integer
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;


ALTER SEQUENCE public.payroll_salarystructure_leaveformula_id_seq OWNER TO postgres;

--
-- TOC entry 4822 (class 0 OID 0)
-- Dependencies: 422
-- Name: payroll_salarystructure_leaveformula_id_seq; Type: SEQUENCE OWNED BY; Schema: public; Owner: postgres
--

ALTER SEQUENCE public.payroll_salarystructure_leaveformula_id_seq OWNED BY public.payroll_salarystructure_leaveformula.id;


--
-- TOC entry 423 (class 1259 OID 28024)
-- Name: payroll_salarystructure_overtimeformula; Type: TABLE; Schema: public; Owner: postgres
--

CREATE TABLE public.payroll_salarystructure_overtimeformula (
    id integer NOT NULL,
    salarystructure_id integer NOT NULL,
    overtimeformula_id integer NOT NULL
);


ALTER TABLE public.payroll_salarystructure_overtimeformula OWNER TO postgres;

--
-- TOC entry 424 (class 1259 OID 28027)
-- Name: payroll_salarystructure_overtimeformula_id_seq; Type: SEQUENCE; Schema: public; Owner: postgres
--

CREATE SEQUENCE public.payroll_salarystructure_overtimeformula_id_seq
    AS integer
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;


ALTER SEQUENCE public.payroll_salarystructure_overtimeformula_id_seq OWNER TO postgres;

--
-- TOC entry 4823 (class 0 OID 0)
-- Dependencies: 424
-- Name: payroll_salarystructure_overtimeformula_id_seq; Type: SEQUENCE OWNED BY; Schema: public; Owner: postgres
--

ALTER SEQUENCE public.payroll_salarystructure_overtimeformula_id_seq OWNED BY public.payroll_salarystructure_overtimeformula.id;


--
-- TOC entry 425 (class 1259 OID 28029)
-- Name: personnel_area; Type: TABLE; Schema: public; Owner: postgres
--

CREATE TABLE public.personnel_area (
    id integer NOT NULL,
    area_code character varying(30) NOT NULL,
    area_name character varying(100) NOT NULL,
    is_default boolean NOT NULL,
    company_id integer,
    parent_area_id integer
);


ALTER TABLE public.personnel_area OWNER TO postgres;

--
-- TOC entry 426 (class 1259 OID 28032)
-- Name: personnel_area_id_seq; Type: SEQUENCE; Schema: public; Owner: postgres
--

CREATE SEQUENCE public.personnel_area_id_seq
    AS integer
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;


ALTER SEQUENCE public.personnel_area_id_seq OWNER TO postgres;

--
-- TOC entry 4824 (class 0 OID 0)
-- Dependencies: 426
-- Name: personnel_area_id_seq; Type: SEQUENCE OWNED BY; Schema: public; Owner: postgres
--

ALTER SEQUENCE public.personnel_area_id_seq OWNED BY public.personnel_area.id;


--
-- TOC entry 427 (class 1259 OID 28034)
-- Name: personnel_assignareaemployee; Type: TABLE; Schema: public; Owner: postgres
--

CREATE TABLE public.personnel_assignareaemployee (
    id integer NOT NULL,
    assigned_time timestamp with time zone NOT NULL,
    area_id integer NOT NULL,
    employee_id integer NOT NULL
);


ALTER TABLE public.personnel_assignareaemployee OWNER TO postgres;

--
-- TOC entry 428 (class 1259 OID 28037)
-- Name: personnel_assignareaemployee_id_seq; Type: SEQUENCE; Schema: public; Owner: postgres
--

CREATE SEQUENCE public.personnel_assignareaemployee_id_seq
    AS integer
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;


ALTER SEQUENCE public.personnel_assignareaemployee_id_seq OWNER TO postgres;

--
-- TOC entry 4825 (class 0 OID 0)
-- Dependencies: 428
-- Name: personnel_assignareaemployee_id_seq; Type: SEQUENCE OWNED BY; Schema: public; Owner: postgres
--

ALTER SEQUENCE public.personnel_assignareaemployee_id_seq OWNED BY public.personnel_assignareaemployee.id;


--
-- TOC entry 429 (class 1259 OID 28039)
-- Name: personnel_certification; Type: TABLE; Schema: public; Owner: postgres
--

CREATE TABLE public.personnel_certification (
    id integer NOT NULL,
    create_time timestamp with time zone,
    create_user character varying(150),
    change_time timestamp with time zone,
    change_user character varying(150),
    status smallint NOT NULL,
    cert_code character varying(20) NOT NULL,
    cert_name character varying(50) NOT NULL,
    company_id integer
);


ALTER TABLE public.personnel_certification OWNER TO postgres;

--
-- TOC entry 430 (class 1259 OID 28042)
-- Name: personnel_certification_id_seq; Type: SEQUENCE; Schema: public; Owner: postgres
--

CREATE SEQUENCE public.personnel_certification_id_seq
    AS integer
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;


ALTER SEQUENCE public.personnel_certification_id_seq OWNER TO postgres;

--
-- TOC entry 4826 (class 0 OID 0)
-- Dependencies: 430
-- Name: personnel_certification_id_seq; Type: SEQUENCE OWNED BY; Schema: public; Owner: postgres
--

ALTER SEQUENCE public.personnel_certification_id_seq OWNED BY public.personnel_certification.id;


--
-- TOC entry 431 (class 1259 OID 28044)
-- Name: personnel_company; Type: TABLE; Schema: public; Owner: postgres
--

CREATE TABLE public.personnel_company (
    id integer NOT NULL,
    company_name character varying(100) NOT NULL,
    company_code character varying(11) NOT NULL,
    logo character varying(200),
    country character varying(10),
    city character varying(10),
    fax character varying(20),
    email character varying(50),
    state character varying(20),
    phone character varying(20),
    website character varying(50),
    postal_code character varying(20),
    address character varying(200),
    address2 character varying(200),
    show_in_report boolean NOT NULL,
    is_default boolean NOT NULL,
    log_position integer,
    name_position integer,
    employee_number_gt bigint NOT NULL,
    employee_number_lt bigint NOT NULL,
    area_number_gt bigint NOT NULL,
    area_number_lt bigint NOT NULL,
    position_number_gt bigint NOT NULL,
    position_number_lt bigint NOT NULL,
    department_number_gt bigint NOT NULL,
    department_number_lt bigint NOT NULL
);


ALTER TABLE public.personnel_company OWNER TO postgres;

--
-- TOC entry 432 (class 1259 OID 28050)
-- Name: personnel_company_id_seq; Type: SEQUENCE; Schema: public; Owner: postgres
--

CREATE SEQUENCE public.personnel_company_id_seq
    AS integer
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;


ALTER SEQUENCE public.personnel_company_id_seq OWNER TO postgres;

--
-- TOC entry 4827 (class 0 OID 0)
-- Dependencies: 432
-- Name: personnel_company_id_seq; Type: SEQUENCE OWNED BY; Schema: public; Owner: postgres
--

ALTER SEQUENCE public.personnel_company_id_seq OWNED BY public.personnel_company.id;


--
-- TOC entry 433 (class 1259 OID 28052)
-- Name: personnel_companyregister; Type: TABLE; Schema: public; Owner: postgres
--

CREATE TABLE public.personnel_companyregister (
    id integer NOT NULL,
    create_time timestamp with time zone,
    create_user character varying(150),
    change_time timestamp with time zone,
    change_user character varying(150),
    status smallint NOT NULL,
    company_code character varying(100) NOT NULL,
    company_name character varying(200) NOT NULL,
    company_address character varying(200) NOT NULL,
    country_name character varying(200) NOT NULL,
    contact_name character varying(50) NOT NULL,
    area_name character varying(100) NOT NULL,
    email character varying(50) NOT NULL,
    mobile character varying(30) NOT NULL,
    desired_license_version smallint,
    desired_optional_functions character varying(200),
    security_code character varying(20) NOT NULL,
    send_mail boolean NOT NULL
);


ALTER TABLE public.personnel_companyregister OWNER TO postgres;

--
-- TOC entry 434 (class 1259 OID 28058)
-- Name: personnel_companyregister_id_seq; Type: SEQUENCE; Schema: public; Owner: postgres
--

CREATE SEQUENCE public.personnel_companyregister_id_seq
    AS integer
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;


ALTER SEQUENCE public.personnel_companyregister_id_seq OWNER TO postgres;

--
-- TOC entry 4828 (class 0 OID 0)
-- Dependencies: 434
-- Name: personnel_companyregister_id_seq; Type: SEQUENCE OWNED BY; Schema: public; Owner: postgres
--

ALTER SEQUENCE public.personnel_companyregister_id_seq OWNED BY public.personnel_companyregister.id;


--
-- TOC entry 435 (class 1259 OID 28060)
-- Name: personnel_department; Type: TABLE; Schema: public; Owner: postgres
--

CREATE TABLE public.personnel_department (
    id integer NOT NULL,
    dept_code character varying(50) NOT NULL,
    dept_name character varying(100) NOT NULL,
    is_default boolean NOT NULL,
    company_id integer,
    parent_dept_id integer
);


ALTER TABLE public.personnel_department OWNER TO postgres;

--
-- TOC entry 436 (class 1259 OID 28063)
-- Name: personnel_department_id_seq; Type: SEQUENCE; Schema: public; Owner: postgres
--

CREATE SEQUENCE public.personnel_department_id_seq
    AS integer
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;


ALTER SEQUENCE public.personnel_department_id_seq OWNER TO postgres;

--
-- TOC entry 4829 (class 0 OID 0)
-- Dependencies: 436
-- Name: personnel_department_id_seq; Type: SEQUENCE OWNED BY; Schema: public; Owner: postgres
--

ALTER SEQUENCE public.personnel_department_id_seq OWNED BY public.personnel_department.id;


--
-- TOC entry 437 (class 1259 OID 28065)
-- Name: personnel_employee; Type: TABLE; Schema: public; Owner: postgres
--

CREATE TABLE public.personnel_employee (
    id integer NOT NULL,
    create_time timestamp with time zone,
    create_user character varying(150),
    change_time timestamp with time zone,
    change_user character varying(150),
    status smallint NOT NULL,
    emp_code bigint NOT NULL,
    first_name character varying(50),
    last_name character varying(25),
    nickname character varying(25),
    passport character varying(30),
    driver_license_automobile character varying(30),
    driver_license_motorcycle character varying(30),
    photo character varying(200),
    self_password character varying(128),
    device_password character varying(20),
    dev_privilege integer,
    card_no character varying(20),
    acc_group character varying(5),
    acc_timezone character varying(20),
    gender character varying(1),
    birthday date,
    address character varying(200),
    postcode character varying(10),
    office_tel character varying(20),
    contact_tel character varying(20),
    mobile character varying(30),
    national_num character varying(50),
    payroll_num character varying(50),
    internal_emp_num character varying(50),
    "national" character varying(50),
    religion character varying(20),
    title character varying(20),
    enroll_sn character varying(20),
    ssn character varying(20),
    update_time timestamp with time zone,
    hire_date date,
    verify_mode integer,
    city character varying(20),
    is_admin boolean NOT NULL,
    emp_type integer,
    enable_att boolean NOT NULL,
    enable_payroll boolean NOT NULL,
    enable_overtime boolean NOT NULL,
    enable_holiday boolean NOT NULL,
    deleted boolean NOT NULL,
    reserved integer,
    del_tag integer,
    app_status smallint,
    app_role smallint,
    email character varying(50),
    last_login timestamp with time zone,
    is_active boolean NOT NULL,
    vacation_rule smallint,
    company_id integer,
    department_id integer,
    position_id integer
);


ALTER TABLE public.personnel_employee OWNER TO postgres;

--
-- TOC entry 438 (class 1259 OID 28071)
-- Name: personnel_employee_area; Type: TABLE; Schema: public; Owner: postgres
--

CREATE TABLE public.personnel_employee_area (
    id integer NOT NULL,
    employee_id integer NOT NULL,
    area_id integer NOT NULL
);


ALTER TABLE public.personnel_employee_area OWNER TO postgres;

--
-- TOC entry 439 (class 1259 OID 28074)
-- Name: personnel_employee_area_id_seq; Type: SEQUENCE; Schema: public; Owner: postgres
--

CREATE SEQUENCE public.personnel_employee_area_id_seq
    AS integer
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;


ALTER SEQUENCE public.personnel_employee_area_id_seq OWNER TO postgres;

--
-- TOC entry 4830 (class 0 OID 0)
-- Dependencies: 439
-- Name: personnel_employee_area_id_seq; Type: SEQUENCE OWNED BY; Schema: public; Owner: postgres
--

ALTER SEQUENCE public.personnel_employee_area_id_seq OWNED BY public.personnel_employee_area.id;


--
-- TOC entry 440 (class 1259 OID 28076)
-- Name: personnel_employee_area_privilege; Type: TABLE; Schema: public; Owner: postgres
--

CREATE TABLE public.personnel_employee_area_privilege (
    id integer NOT NULL,
    employee_id integer NOT NULL,
    area_id integer NOT NULL
);


ALTER TABLE public.personnel_employee_area_privilege OWNER TO postgres;

--
-- TOC entry 441 (class 1259 OID 28079)
-- Name: personnel_employee_area_privilege_id_seq; Type: SEQUENCE; Schema: public; Owner: postgres
--

CREATE SEQUENCE public.personnel_employee_area_privilege_id_seq
    AS integer
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;


ALTER SEQUENCE public.personnel_employee_area_privilege_id_seq OWNER TO postgres;

--
-- TOC entry 4831 (class 0 OID 0)
-- Dependencies: 441
-- Name: personnel_employee_area_privilege_id_seq; Type: SEQUENCE OWNED BY; Schema: public; Owner: postgres
--

ALTER SEQUENCE public.personnel_employee_area_privilege_id_seq OWNED BY public.personnel_employee_area_privilege.id;


--
-- TOC entry 442 (class 1259 OID 28081)
-- Name: personnel_employee_flow_role; Type: TABLE; Schema: public; Owner: postgres
--

CREATE TABLE public.personnel_employee_flow_role (
    id integer NOT NULL,
    employee_id integer NOT NULL,
    workflowrole_id integer NOT NULL
);


ALTER TABLE public.personnel_employee_flow_role OWNER TO postgres;

--
-- TOC entry 443 (class 1259 OID 28084)
-- Name: personnel_employee_flow_role_id_seq; Type: SEQUENCE; Schema: public; Owner: postgres
--

CREATE SEQUENCE public.personnel_employee_flow_role_id_seq
    AS integer
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;


ALTER SEQUENCE public.personnel_employee_flow_role_id_seq OWNER TO postgres;

--
-- TOC entry 4832 (class 0 OID 0)
-- Dependencies: 443
-- Name: personnel_employee_flow_role_id_seq; Type: SEQUENCE OWNED BY; Schema: public; Owner: postgres
--

ALTER SEQUENCE public.personnel_employee_flow_role_id_seq OWNED BY public.personnel_employee_flow_role.id;


--
-- TOC entry 444 (class 1259 OID 28086)
-- Name: personnel_employee_id_seq; Type: SEQUENCE; Schema: public; Owner: postgres
--

CREATE SEQUENCE public.personnel_employee_id_seq
    AS integer
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;


ALTER SEQUENCE public.personnel_employee_id_seq OWNER TO postgres;

--
-- TOC entry 4833 (class 0 OID 0)
-- Dependencies: 444
-- Name: personnel_employee_id_seq; Type: SEQUENCE OWNED BY; Schema: public; Owner: postgres
--

ALTER SEQUENCE public.personnel_employee_id_seq OWNED BY public.personnel_employee.id;


--
-- TOC entry 445 (class 1259 OID 28088)
-- Name: personnel_employeecertification; Type: TABLE; Schema: public; Owner: postgres
--

CREATE TABLE public.personnel_employeecertification (
    id integer NOT NULL,
    expire_on date,
    email_alert boolean NOT NULL,
    before integer,
    file_name character varying(200),
    file character varying(200),
    certification_id integer NOT NULL,
    employee_id integer NOT NULL
);


ALTER TABLE public.personnel_employeecertification OWNER TO postgres;

--
-- TOC entry 446 (class 1259 OID 28091)
-- Name: personnel_employeecertification_id_seq; Type: SEQUENCE; Schema: public; Owner: postgres
--

CREATE SEQUENCE public.personnel_employeecertification_id_seq
    AS integer
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;


ALTER SEQUENCE public.personnel_employeecertification_id_seq OWNER TO postgres;

--
-- TOC entry 4834 (class 0 OID 0)
-- Dependencies: 446
-- Name: personnel_employeecertification_id_seq; Type: SEQUENCE OWNED BY; Schema: public; Owner: postgres
--

ALTER SEQUENCE public.personnel_employeecertification_id_seq OWNED BY public.personnel_employeecertification.id;


--
-- TOC entry 447 (class 1259 OID 28093)
-- Name: personnel_employeeprofile; Type: TABLE; Schema: public; Owner: postgres
--

CREATE TABLE public.personnel_employeeprofile (
    id integer NOT NULL,
    column_order text NOT NULL,
    disabled_fields text NOT NULL,
    preferences text NOT NULL,
    pwd_update_time timestamp with time zone,
    emp_id integer NOT NULL
);


ALTER TABLE public.personnel_employeeprofile OWNER TO postgres;

--
-- TOC entry 448 (class 1259 OID 28099)
-- Name: personnel_employeeprofile_id_seq; Type: SEQUENCE; Schema: public; Owner: postgres
--

CREATE SEQUENCE public.personnel_employeeprofile_id_seq
    AS integer
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;


ALTER SEQUENCE public.personnel_employeeprofile_id_seq OWNER TO postgres;

--
-- TOC entry 4835 (class 0 OID 0)
-- Dependencies: 448
-- Name: personnel_employeeprofile_id_seq; Type: SEQUENCE OWNED BY; Schema: public; Owner: postgres
--

ALTER SEQUENCE public.personnel_employeeprofile_id_seq OWNED BY public.personnel_employeeprofile.id;


--
-- TOC entry 449 (class 1259 OID 28101)
-- Name: personnel_position; Type: TABLE; Schema: public; Owner: postgres
--

CREATE TABLE public.personnel_position (
    id integer NOT NULL,
    position_code character varying(50) NOT NULL,
    position_name character varying(100) NOT NULL,
    is_default boolean NOT NULL,
    company_id integer,
    parent_position_id integer
);


ALTER TABLE public.personnel_position OWNER TO postgres;

--
-- TOC entry 450 (class 1259 OID 28104)
-- Name: personnel_position_id_seq; Type: SEQUENCE; Schema: public; Owner: postgres
--

CREATE SEQUENCE public.personnel_position_id_seq
    AS integer
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;


ALTER SEQUENCE public.personnel_position_id_seq OWNER TO postgres;

--
-- TOC entry 4836 (class 0 OID 0)
-- Dependencies: 450
-- Name: personnel_position_id_seq; Type: SEQUENCE OWNED BY; Schema: public; Owner: postgres
--

ALTER SEQUENCE public.personnel_position_id_seq OWNED BY public.personnel_position.id;


--
-- TOC entry 451 (class 1259 OID 28106)
-- Name: personnel_resign; Type: TABLE; Schema: public; Owner: postgres
--

CREATE TABLE public.personnel_resign (
    id integer NOT NULL,
    resign_date date NOT NULL,
    resign_type integer,
    disableatt boolean NOT NULL,
    reason character varying(200),
    company_id integer,
    employee_id integer NOT NULL
);


ALTER TABLE public.personnel_resign OWNER TO postgres;

--
-- TOC entry 452 (class 1259 OID 28109)
-- Name: personnel_resign_id_seq; Type: SEQUENCE; Schema: public; Owner: postgres
--

CREATE SEQUENCE public.personnel_resign_id_seq
    AS integer
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;


ALTER SEQUENCE public.personnel_resign_id_seq OWNER TO postgres;

--
-- TOC entry 4837 (class 0 OID 0)
-- Dependencies: 452
-- Name: personnel_resign_id_seq; Type: SEQUENCE OWNED BY; Schema: public; Owner: postgres
--

ALTER SEQUENCE public.personnel_resign_id_seq OWNED BY public.personnel_resign.id;


--
-- TOC entry 453 (class 1259 OID 28111)
-- Name: staff_stafftoken; Type: TABLE; Schema: public; Owner: postgres
--

CREATE TABLE public.staff_stafftoken (
    key character varying(40) NOT NULL,
    created timestamp with time zone NOT NULL,
    user_id integer NOT NULL
);


ALTER TABLE public.staff_stafftoken OWNER TO postgres;

--
-- TOC entry 454 (class 1259 OID 28114)
-- Name: sync_area; Type: TABLE; Schema: public; Owner: postgres
--

CREATE TABLE public.sync_area (
    id integer NOT NULL,
    post_time timestamp with time zone,
    flag smallint NOT NULL,
    update_time timestamp with time zone,
    sync_ret character varying(200),
    area_code character varying(30) NOT NULL,
    area_name character varying(100) NOT NULL
);


ALTER TABLE public.sync_area OWNER TO postgres;

--
-- TOC entry 455 (class 1259 OID 28117)
-- Name: sync_area_id_seq; Type: SEQUENCE; Schema: public; Owner: postgres
--

CREATE SEQUENCE public.sync_area_id_seq
    AS integer
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;


ALTER SEQUENCE public.sync_area_id_seq OWNER TO postgres;

--
-- TOC entry 4838 (class 0 OID 0)
-- Dependencies: 455
-- Name: sync_area_id_seq; Type: SEQUENCE OWNED BY; Schema: public; Owner: postgres
--

ALTER SEQUENCE public.sync_area_id_seq OWNED BY public.sync_area.id;


--
-- TOC entry 456 (class 1259 OID 28119)
-- Name: sync_department; Type: TABLE; Schema: public; Owner: postgres
--

CREATE TABLE public.sync_department (
    id integer NOT NULL,
    post_time timestamp with time zone,
    flag smallint NOT NULL,
    update_time timestamp with time zone,
    sync_ret character varying(200),
    dept_code character varying(50) NOT NULL,
    dept_name character varying(100) NOT NULL
);


ALTER TABLE public.sync_department OWNER TO postgres;

--
-- TOC entry 457 (class 1259 OID 28122)
-- Name: sync_department_id_seq; Type: SEQUENCE; Schema: public; Owner: postgres
--

CREATE SEQUENCE public.sync_department_id_seq
    AS integer
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;


ALTER SEQUENCE public.sync_department_id_seq OWNER TO postgres;

--
-- TOC entry 4839 (class 0 OID 0)
-- Dependencies: 457
-- Name: sync_department_id_seq; Type: SEQUENCE OWNED BY; Schema: public; Owner: postgres
--

ALTER SEQUENCE public.sync_department_id_seq OWNED BY public.sync_department.id;


--
-- TOC entry 458 (class 1259 OID 28124)
-- Name: sync_employee; Type: TABLE; Schema: public; Owner: postgres
--

CREATE TABLE public.sync_employee (
    id integer NOT NULL,
    post_time timestamp with time zone,
    flag smallint NOT NULL,
    update_time timestamp with time zone,
    sync_ret character varying(200),
    emp_code character varying(20) NOT NULL,
    first_name character varying(50),
    last_name character varying(25),
    dept_code character varying(50),
    dept_name character varying(100),
    job_code character varying(50),
    job_name character varying(100),
    area_code character varying(30),
    area_name character varying(100),
    card_no character varying(20),
    multi_area boolean NOT NULL,
    hire_date date,
    gender character varying(2),
    birthday date,
    email character varying(100),
    active_status boolean NOT NULL
);


ALTER TABLE public.sync_employee OWNER TO postgres;

--
-- TOC entry 459 (class 1259 OID 28130)
-- Name: sync_employee_id_seq; Type: SEQUENCE; Schema: public; Owner: postgres
--

CREATE SEQUENCE public.sync_employee_id_seq
    AS integer
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;


ALTER SEQUENCE public.sync_employee_id_seq OWNER TO postgres;

--
-- TOC entry 4840 (class 0 OID 0)
-- Dependencies: 459
-- Name: sync_employee_id_seq; Type: SEQUENCE OWNED BY; Schema: public; Owner: postgres
--

ALTER SEQUENCE public.sync_employee_id_seq OWNED BY public.sync_employee.id;


--
-- TOC entry 460 (class 1259 OID 28132)
-- Name: sync_job; Type: TABLE; Schema: public; Owner: postgres
--

CREATE TABLE public.sync_job (
    id integer NOT NULL,
    post_time timestamp with time zone,
    flag smallint NOT NULL,
    update_time timestamp with time zone,
    sync_ret character varying(200),
    job_code character varying(50) NOT NULL,
    job_name character varying(100) NOT NULL
);


ALTER TABLE public.sync_job OWNER TO postgres;

--
-- TOC entry 461 (class 1259 OID 28135)
-- Name: sync_job_id_seq; Type: SEQUENCE; Schema: public; Owner: postgres
--

CREATE SEQUENCE public.sync_job_id_seq
    AS integer
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;


ALTER SEQUENCE public.sync_job_id_seq OWNER TO postgres;

--
-- TOC entry 4841 (class 0 OID 0)
-- Dependencies: 461
-- Name: sync_job_id_seq; Type: SEQUENCE OWNED BY; Schema: public; Owner: postgres
--

ALTER SEQUENCE public.sync_job_id_seq OWNED BY public.sync_job.id;


--
-- TOC entry 462 (class 1259 OID 28137)
-- Name: workflow_abstractexception; Type: TABLE; Schema: public; Owner: postgres
--

CREATE TABLE public.workflow_abstractexception (
    id integer NOT NULL,
    audit_status smallint NOT NULL,
    revoke_reason text
);


ALTER TABLE public.workflow_abstractexception OWNER TO postgres;

--
-- TOC entry 463 (class 1259 OID 28143)
-- Name: workflow_abstractexception_id_seq; Type: SEQUENCE; Schema: public; Owner: postgres
--

CREATE SEQUENCE public.workflow_abstractexception_id_seq
    AS integer
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;


ALTER SEQUENCE public.workflow_abstractexception_id_seq OWNER TO postgres;

--
-- TOC entry 4842 (class 0 OID 0)
-- Dependencies: 463
-- Name: workflow_abstractexception_id_seq; Type: SEQUENCE OWNED BY; Schema: public; Owner: postgres
--

ALTER SEQUENCE public.workflow_abstractexception_id_seq OWNED BY public.workflow_abstractexception.id;


--
-- TOC entry 464 (class 1259 OID 28145)
-- Name: workflow_nodeinstance; Type: TABLE; Schema: public; Owner: postgres
--

CREATE TABLE public.workflow_nodeinstance (
    id integer NOT NULL,
    name character varying(200) NOT NULL,
    "order" smallint NOT NULL,
    state smallint NOT NULL,
    is_last_node boolean NOT NULL,
    is_next_node boolean NOT NULL,
    remark character varying(255),
    apply_time timestamp with time zone,
    approver_admin_id integer,
    approver_employee_id integer,
    departments_id integer,
    node_engine_id integer,
    workflow_instance_id integer
);


ALTER TABLE public.workflow_nodeinstance OWNER TO postgres;

--
-- TOC entry 465 (class 1259 OID 28148)
-- Name: workflow_nodeinstance_id_seq; Type: SEQUENCE; Schema: public; Owner: postgres
--

CREATE SEQUENCE public.workflow_nodeinstance_id_seq
    AS integer
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;


ALTER SEQUENCE public.workflow_nodeinstance_id_seq OWNER TO postgres;

--
-- TOC entry 4843 (class 0 OID 0)
-- Dependencies: 465
-- Name: workflow_nodeinstance_id_seq; Type: SEQUENCE OWNED BY; Schema: public; Owner: postgres
--

ALTER SEQUENCE public.workflow_nodeinstance_id_seq OWNED BY public.workflow_nodeinstance.id;


--
-- TOC entry 466 (class 1259 OID 28150)
-- Name: workflow_workflowengine; Type: TABLE; Schema: public; Owner: postgres
--

CREATE TABLE public.workflow_workflowengine (
    id integer NOT NULL,
    create_time timestamp with time zone,
    create_user character varying(150),
    change_time timestamp with time zone,
    change_user character varying(150),
    status smallint NOT NULL,
    workflow_code character varying(50) NOT NULL,
    workflow_name character varying(50) NOT NULL,
    start_date date NOT NULL,
    end_date date NOT NULL,
    description character varying(50) NOT NULL,
    workflow_type smallint NOT NULL,
    inform_type smallint NOT NULL,
    del_flag smallint,
    applicant_position_id integer,
    company_id integer,
    content_type_id integer,
    departments_id integer
);


ALTER TABLE public.workflow_workflowengine OWNER TO postgres;

--
-- TOC entry 467 (class 1259 OID 28153)
-- Name: workflow_workflowengine_employee; Type: TABLE; Schema: public; Owner: postgres
--

CREATE TABLE public.workflow_workflowengine_employee (
    id integer NOT NULL,
    workflowengine_id integer NOT NULL,
    employee_id integer NOT NULL
);


ALTER TABLE public.workflow_workflowengine_employee OWNER TO postgres;

--
-- TOC entry 468 (class 1259 OID 28156)
-- Name: workflow_workflowengine_employee_id_seq; Type: SEQUENCE; Schema: public; Owner: postgres
--

CREATE SEQUENCE public.workflow_workflowengine_employee_id_seq
    AS integer
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;


ALTER SEQUENCE public.workflow_workflowengine_employee_id_seq OWNER TO postgres;

--
-- TOC entry 4844 (class 0 OID 0)
-- Dependencies: 468
-- Name: workflow_workflowengine_employee_id_seq; Type: SEQUENCE OWNED BY; Schema: public; Owner: postgres
--

ALTER SEQUENCE public.workflow_workflowengine_employee_id_seq OWNED BY public.workflow_workflowengine_employee.id;


--
-- TOC entry 469 (class 1259 OID 28158)
-- Name: workflow_workflowengine_id_seq; Type: SEQUENCE; Schema: public; Owner: postgres
--

CREATE SEQUENCE public.workflow_workflowengine_id_seq
    AS integer
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;


ALTER SEQUENCE public.workflow_workflowengine_id_seq OWNER TO postgres;

--
-- TOC entry 4845 (class 0 OID 0)
-- Dependencies: 469
-- Name: workflow_workflowengine_id_seq; Type: SEQUENCE OWNED BY; Schema: public; Owner: postgres
--

ALTER SEQUENCE public.workflow_workflowengine_id_seq OWNED BY public.workflow_workflowengine.id;


--
-- TOC entry 470 (class 1259 OID 28160)
-- Name: workflow_workflowinstance; Type: TABLE; Schema: public; Owner: postgres
--

CREATE TABLE public.workflow_workflowinstance (
    id integer NOT NULL,
    workflow_code character varying(255) NOT NULL,
    workflow_name character varying(255) NOT NULL,
    start_date date NOT NULL,
    end_date date NOT NULL,
    issue_date date NOT NULL,
    description character varying(255) NOT NULL,
    content_type integer NOT NULL,
    inform_type smallint NOT NULL,
    del_flag boolean NOT NULL,
    employee_id integer NOT NULL,
    exception_id integer,
    workflow_engine_id integer
);


ALTER TABLE public.workflow_workflowinstance OWNER TO postgres;

--
-- TOC entry 471 (class 1259 OID 28166)
-- Name: workflow_workflowinstance_id_seq; Type: SEQUENCE; Schema: public; Owner: postgres
--

CREATE SEQUENCE public.workflow_workflowinstance_id_seq
    AS integer
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;


ALTER SEQUENCE public.workflow_workflowinstance_id_seq OWNER TO postgres;

--
-- TOC entry 4846 (class 0 OID 0)
-- Dependencies: 471
-- Name: workflow_workflowinstance_id_seq; Type: SEQUENCE OWNED BY; Schema: public; Owner: postgres
--

ALTER SEQUENCE public.workflow_workflowinstance_id_seq OWNED BY public.workflow_workflowinstance.id;


--
-- TOC entry 472 (class 1259 OID 28168)
-- Name: workflow_workflownode; Type: TABLE; Schema: public; Owner: postgres
--

CREATE TABLE public.workflow_workflownode (
    id integer NOT NULL,
    create_time timestamp with time zone,
    create_user character varying(150),
    change_time timestamp with time zone,
    change_user character varying(150),
    status smallint NOT NULL,
    node_code character varying(30) NOT NULL,
    node_name character varying(30) NOT NULL,
    order_id integer NOT NULL,
    approver_type smallint,
    notifier_type smallint,
    approver_by_overall boolean NOT NULL,
    notify_by_overall boolean NOT NULL,
    workflow_engine integer NOT NULL,
    workflow_engine_name character varying(50) NOT NULL,
    company_id integer
);


ALTER TABLE public.workflow_workflownode OWNER TO postgres;

--
-- TOC entry 473 (class 1259 OID 28171)
-- Name: workflow_workflownode_approver; Type: TABLE; Schema: public; Owner: postgres
--

CREATE TABLE public.workflow_workflownode_approver (
    id integer NOT NULL,
    workflownode_id integer NOT NULL,
    workflowrole_id integer NOT NULL
);


ALTER TABLE public.workflow_workflownode_approver OWNER TO postgres;

--
-- TOC entry 474 (class 1259 OID 28174)
-- Name: workflow_workflownode_approver_id_seq; Type: SEQUENCE; Schema: public; Owner: postgres
--

CREATE SEQUENCE public.workflow_workflownode_approver_id_seq
    AS integer
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;


ALTER SEQUENCE public.workflow_workflownode_approver_id_seq OWNER TO postgres;

--
-- TOC entry 4847 (class 0 OID 0)
-- Dependencies: 474
-- Name: workflow_workflownode_approver_id_seq; Type: SEQUENCE OWNED BY; Schema: public; Owner: postgres
--

ALTER SEQUENCE public.workflow_workflownode_approver_id_seq OWNED BY public.workflow_workflownode_approver.id;


--
-- TOC entry 475 (class 1259 OID 28176)
-- Name: workflow_workflownode_id_seq; Type: SEQUENCE; Schema: public; Owner: postgres
--

CREATE SEQUENCE public.workflow_workflownode_id_seq
    AS integer
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;


ALTER SEQUENCE public.workflow_workflownode_id_seq OWNER TO postgres;

--
-- TOC entry 4848 (class 0 OID 0)
-- Dependencies: 475
-- Name: workflow_workflownode_id_seq; Type: SEQUENCE OWNED BY; Schema: public; Owner: postgres
--

ALTER SEQUENCE public.workflow_workflownode_id_seq OWNED BY public.workflow_workflownode.id;


--
-- TOC entry 476 (class 1259 OID 28178)
-- Name: workflow_workflownode_notifier; Type: TABLE; Schema: public; Owner: postgres
--

CREATE TABLE public.workflow_workflownode_notifier (
    id integer NOT NULL,
    workflownode_id integer NOT NULL,
    workflowrole_id integer NOT NULL
);


ALTER TABLE public.workflow_workflownode_notifier OWNER TO postgres;

--
-- TOC entry 477 (class 1259 OID 28181)
-- Name: workflow_workflownode_notifier_id_seq; Type: SEQUENCE; Schema: public; Owner: postgres
--

CREATE SEQUENCE public.workflow_workflownode_notifier_id_seq
    AS integer
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;


ALTER SEQUENCE public.workflow_workflownode_notifier_id_seq OWNER TO postgres;

--
-- TOC entry 4849 (class 0 OID 0)
-- Dependencies: 477
-- Name: workflow_workflownode_notifier_id_seq; Type: SEQUENCE OWNED BY; Schema: public; Owner: postgres
--

ALTER SEQUENCE public.workflow_workflownode_notifier_id_seq OWNED BY public.workflow_workflownode_notifier.id;


--
-- TOC entry 478 (class 1259 OID 28183)
-- Name: workflow_workflowrole; Type: TABLE; Schema: public; Owner: postgres
--

CREATE TABLE public.workflow_workflowrole (
    id integer NOT NULL,
    create_time timestamp with time zone,
    create_user character varying(150),
    change_time timestamp with time zone,
    change_user character varying(150),
    status smallint NOT NULL,
    role_code character varying(30) NOT NULL,
    role_name character varying(50) NOT NULL,
    description character varying(200),
    company_id integer
);


ALTER TABLE public.workflow_workflowrole OWNER TO postgres;

--
-- TOC entry 479 (class 1259 OID 28189)
-- Name: workflow_workflowrole_id_seq; Type: SEQUENCE; Schema: public; Owner: postgres
--

CREATE SEQUENCE public.workflow_workflowrole_id_seq
    AS integer
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;


ALTER SEQUENCE public.workflow_workflowrole_id_seq OWNER TO postgres;

--
-- TOC entry 4850 (class 0 OID 0)
-- Dependencies: 479
-- Name: workflow_workflowrole_id_seq; Type: SEQUENCE OWNED BY; Schema: public; Owner: postgres
--

ALTER SEQUENCE public.workflow_workflowrole_id_seq OWNED BY public.workflow_workflowrole.id;


--
-- TOC entry 3611 (class 2604 OID 28191)
-- Name: acc_acccombination id; Type: DEFAULT; Schema: public; Owner: postgres
--

ALTER TABLE ONLY public.acc_acccombination ALTER COLUMN id SET DEFAULT nextval('public.acc_acccombination_id_seq'::regclass);


--
-- TOC entry 3612 (class 2604 OID 28192)
-- Name: acc_accgroups id; Type: DEFAULT; Schema: public; Owner: postgres
--

ALTER TABLE ONLY public.acc_accgroups ALTER COLUMN id SET DEFAULT nextval('public.acc_accgroups_id_seq'::regclass);


--
-- TOC entry 3613 (class 2604 OID 28193)
-- Name: acc_accholiday id; Type: DEFAULT; Schema: public; Owner: postgres
--

ALTER TABLE ONLY public.acc_accholiday ALTER COLUMN id SET DEFAULT nextval('public.acc_accholiday_id_seq'::regclass);


--
-- TOC entry 3614 (class 2604 OID 28194)
-- Name: acc_accprivilege id; Type: DEFAULT; Schema: public; Owner: postgres
--

ALTER TABLE ONLY public.acc_accprivilege ALTER COLUMN id SET DEFAULT nextval('public.acc_accprivilege_id_seq'::regclass);


--
-- TOC entry 3615 (class 2604 OID 28195)
-- Name: acc_accterminal id; Type: DEFAULT; Schema: public; Owner: postgres
--

ALTER TABLE ONLY public.acc_accterminal ALTER COLUMN id SET DEFAULT nextval('public.acc_accterminal_id_seq'::regclass);


--
-- TOC entry 3616 (class 2604 OID 28196)
-- Name: acc_acctimezone id; Type: DEFAULT; Schema: public; Owner: postgres
--

ALTER TABLE ONLY public.acc_acctimezone ALTER COLUMN id SET DEFAULT nextval('public.acc_acctimezone_id_seq'::regclass);


--
-- TOC entry 3617 (class 2604 OID 28197)
-- Name: accounts_adminbiodata id; Type: DEFAULT; Schema: public; Owner: postgres
--

ALTER TABLE ONLY public.accounts_adminbiodata ALTER COLUMN id SET DEFAULT nextval('public.accounts_adminbiodata_id_seq'::regclass);


--
-- TOC entry 3618 (class 2604 OID 28198)
-- Name: accounts_usersecuritypolicy id; Type: DEFAULT; Schema: public; Owner: postgres
--

ALTER TABLE ONLY public.accounts_usersecuritypolicy ALTER COLUMN id SET DEFAULT nextval('public.accounts_usersecuritypolicy_id_seq'::regclass);


--
-- TOC entry 3619 (class 2604 OID 28199)
-- Name: att_attcalclog id; Type: DEFAULT; Schema: public; Owner: postgres
--

ALTER TABLE ONLY public.att_attcalclog ALTER COLUMN id SET DEFAULT nextval('public.att_attcalclog_id_seq'::regclass);


--
-- TOC entry 3620 (class 2604 OID 28200)
-- Name: att_attreportsetting id; Type: DEFAULT; Schema: public; Owner: postgres
--

ALTER TABLE ONLY public.att_attreportsetting ALTER COLUMN id SET DEFAULT nextval('public.att_attreportsetting_id_seq'::regclass);


--
-- TOC entry 3621 (class 2604 OID 28201)
-- Name: att_attschedule id; Type: DEFAULT; Schema: public; Owner: postgres
--

ALTER TABLE ONLY public.att_attschedule ALTER COLUMN id SET DEFAULT nextval('public.att_attschedule_id_seq'::regclass);


--
-- TOC entry 3622 (class 2604 OID 28202)
-- Name: att_attshift id; Type: DEFAULT; Schema: public; Owner: postgres
--

ALTER TABLE ONLY public.att_attshift ALTER COLUMN id SET DEFAULT nextval('public.att_attshift_id_seq'::regclass);


--
-- TOC entry 3623 (class 2604 OID 28203)
-- Name: att_breaktime id; Type: DEFAULT; Schema: public; Owner: postgres
--

ALTER TABLE ONLY public.att_breaktime ALTER COLUMN id SET DEFAULT nextval('public.att_breaktime_id_seq'::regclass);


--
-- TOC entry 3624 (class 2604 OID 28204)
-- Name: att_departmentschedule id; Type: DEFAULT; Schema: public; Owner: postgres
--

ALTER TABLE ONLY public.att_departmentschedule ALTER COLUMN id SET DEFAULT nextval('public.att_departmentschedule_id_seq'::regclass);


--
-- TOC entry 3625 (class 2604 OID 28205)
-- Name: att_deptattrule id; Type: DEFAULT; Schema: public; Owner: postgres
--

ALTER TABLE ONLY public.att_deptattrule ALTER COLUMN id SET DEFAULT nextval('public.att_deptattrule_id_seq'::regclass);


--
-- TOC entry 3626 (class 2604 OID 28206)
-- Name: att_holiday id; Type: DEFAULT; Schema: public; Owner: postgres
--

ALTER TABLE ONLY public.att_holiday ALTER COLUMN id SET DEFAULT nextval('public.att_holiday_id_seq'::regclass);


--
-- TOC entry 3627 (class 2604 OID 28207)
-- Name: att_leavecategory id; Type: DEFAULT; Schema: public; Owner: postgres
--

ALTER TABLE ONLY public.att_leavecategory ALTER COLUMN id SET DEFAULT nextval('public.att_leavecategory_id_seq'::regclass);


--
-- TOC entry 3628 (class 2604 OID 28208)
-- Name: att_payloadmulpunchset id; Type: DEFAULT; Schema: public; Owner: postgres
--

ALTER TABLE ONLY public.att_payloadmulpunchset ALTER COLUMN id SET DEFAULT nextval('public.att_payloadmulpunchset_id_seq'::regclass);


--
-- TOC entry 3629 (class 2604 OID 28209)
-- Name: att_shiftdetail id; Type: DEFAULT; Schema: public; Owner: postgres
--

ALTER TABLE ONLY public.att_shiftdetail ALTER COLUMN id SET DEFAULT nextval('public.att_shiftdetail_id_seq'::regclass);


--
-- TOC entry 3630 (class 2604 OID 28210)
-- Name: att_tempschedule id; Type: DEFAULT; Schema: public; Owner: postgres
--

ALTER TABLE ONLY public.att_tempschedule ALTER COLUMN id SET DEFAULT nextval('public.att_tempschedule_id_seq'::regclass);


--
-- TOC entry 3631 (class 2604 OID 28211)
-- Name: att_timeinterval id; Type: DEFAULT; Schema: public; Owner: postgres
--

ALTER TABLE ONLY public.att_timeinterval ALTER COLUMN id SET DEFAULT nextval('public.att_timeinterval_id_seq'::regclass);


--
-- TOC entry 3632 (class 2604 OID 28212)
-- Name: att_timeinterval_break_time id; Type: DEFAULT; Schema: public; Owner: postgres
--

ALTER TABLE ONLY public.att_timeinterval_break_time ALTER COLUMN id SET DEFAULT nextval('public.att_timeinterval_break_time_id_seq'::regclass);


--
-- TOC entry 3633 (class 2604 OID 28213)
-- Name: att_trainingcategory id; Type: DEFAULT; Schema: public; Owner: postgres
--

ALTER TABLE ONLY public.att_trainingcategory ALTER COLUMN id SET DEFAULT nextval('public.att_trainingcategory_id_seq'::regclass);


--
-- TOC entry 3634 (class 2604 OID 28214)
-- Name: att_vacationemployee id; Type: DEFAULT; Schema: public; Owner: postgres
--

ALTER TABLE ONLY public.att_vacationemployee ALTER COLUMN id SET DEFAULT nextval('public.att_vacationemployee_id_seq'::regclass);


--
-- TOC entry 3635 (class 2604 OID 28215)
-- Name: att_vacationtime id; Type: DEFAULT; Schema: public; Owner: postgres
--

ALTER TABLE ONLY public.att_vacationtime ALTER COLUMN id SET DEFAULT nextval('public.att_vacationtime_id_seq'::regclass);


--
-- TOC entry 3636 (class 2604 OID 28216)
-- Name: att_vacationtimeseniority id; Type: DEFAULT; Schema: public; Owner: postgres
--

ALTER TABLE ONLY public.att_vacationtimeseniority ALTER COLUMN id SET DEFAULT nextval('public.att_vacationtimeseniority_id_seq'::regclass);


--
-- TOC entry 3637 (class 2604 OID 28217)
-- Name: attparam id; Type: DEFAULT; Schema: public; Owner: postgres
--

ALTER TABLE ONLY public.attparam ALTER COLUMN id SET DEFAULT nextval('public.attparam_id_seq'::regclass);


--
-- TOC entry 3638 (class 2604 OID 28218)
-- Name: auth_group id; Type: DEFAULT; Schema: public; Owner: postgres
--

ALTER TABLE ONLY public.auth_group ALTER COLUMN id SET DEFAULT nextval('public.auth_group_id_seq'::regclass);


--
-- TOC entry 3639 (class 2604 OID 28219)
-- Name: auth_group_permissions id; Type: DEFAULT; Schema: public; Owner: postgres
--

ALTER TABLE ONLY public.auth_group_permissions ALTER COLUMN id SET DEFAULT nextval('public.auth_group_permissions_id_seq'::regclass);


--
-- TOC entry 3640 (class 2604 OID 28220)
-- Name: auth_permission id; Type: DEFAULT; Schema: public; Owner: postgres
--

ALTER TABLE ONLY public.auth_permission ALTER COLUMN id SET DEFAULT nextval('public.auth_permission_id_seq'::regclass);


--
-- TOC entry 3641 (class 2604 OID 28221)
-- Name: auth_user id; Type: DEFAULT; Schema: public; Owner: postgres
--

ALTER TABLE ONLY public.auth_user ALTER COLUMN id SET DEFAULT nextval('public.auth_user_id_seq'::regclass);


--
-- TOC entry 3643 (class 2604 OID 28222)
-- Name: auth_user_auth_area id; Type: DEFAULT; Schema: public; Owner: postgres
--

ALTER TABLE ONLY public.auth_user_auth_area ALTER COLUMN id SET DEFAULT nextval('public.auth_user_auth_area_id_seq'::regclass);


--
-- TOC entry 3644 (class 2604 OID 28223)
-- Name: auth_user_auth_dept id; Type: DEFAULT; Schema: public; Owner: postgres
--

ALTER TABLE ONLY public.auth_user_auth_dept ALTER COLUMN id SET DEFAULT nextval('public.auth_user_auth_dept_id_seq'::regclass);


--
-- TOC entry 3645 (class 2604 OID 28224)
-- Name: auth_user_groups id; Type: DEFAULT; Schema: public; Owner: postgres
--

ALTER TABLE ONLY public.auth_user_groups ALTER COLUMN id SET DEFAULT nextval('public.auth_user_groups_id_seq'::regclass);


--
-- TOC entry 3646 (class 2604 OID 28225)
-- Name: auth_user_profile id; Type: DEFAULT; Schema: public; Owner: postgres
--

ALTER TABLE ONLY public.auth_user_profile ALTER COLUMN id SET DEFAULT nextval('public.auth_user_profile_id_seq'::regclass);


--
-- TOC entry 3647 (class 2604 OID 28226)
-- Name: auth_user_user_permissions id; Type: DEFAULT; Schema: public; Owner: postgres
--

ALTER TABLE ONLY public.auth_user_user_permissions ALTER COLUMN id SET DEFAULT nextval('public.auth_user_user_permissions_id_seq'::regclass);


--
-- TOC entry 3648 (class 2604 OID 28227)
-- Name: base_adminlog id; Type: DEFAULT; Schema: public; Owner: postgres
--

ALTER TABLE ONLY public.base_adminlog ALTER COLUMN id SET DEFAULT nextval('public.base_adminlog_id_seq'::regclass);


--
-- TOC entry 3649 (class 2604 OID 28228)
-- Name: base_attparamdepts id; Type: DEFAULT; Schema: public; Owner: postgres
--

ALTER TABLE ONLY public.base_attparamdepts ALTER COLUMN id SET DEFAULT nextval('public.base_attparamdepts_id_seq'::regclass);


--
-- TOC entry 3650 (class 2604 OID 28229)
-- Name: base_autoexporttask id; Type: DEFAULT; Schema: public; Owner: postgres
--

ALTER TABLE ONLY public.base_autoexporttask ALTER COLUMN id SET DEFAULT nextval('public.base_autoexporttask_id_seq'::regclass);


--
-- TOC entry 3651 (class 2604 OID 28230)
-- Name: base_bookmark id; Type: DEFAULT; Schema: public; Owner: postgres
--

ALTER TABLE ONLY public.base_bookmark ALTER COLUMN id SET DEFAULT nextval('public.base_bookmark_id_seq'::regclass);


--
-- TOC entry 3652 (class 2604 OID 28231)
-- Name: base_dbbackuplog id; Type: DEFAULT; Schema: public; Owner: postgres
--

ALTER TABLE ONLY public.base_dbbackuplog ALTER COLUMN id SET DEFAULT nextval('public.base_dbbackuplog_id_seq'::regclass);


--
-- TOC entry 3653 (class 2604 OID 28232)
-- Name: base_dbmigrate id; Type: DEFAULT; Schema: public; Owner: postgres
--

ALTER TABLE ONLY public.base_dbmigrate ALTER COLUMN id SET DEFAULT nextval('public.base_dbmigrate_id_seq'::regclass);


--
-- TOC entry 3654 (class 2604 OID 28233)
-- Name: base_departmentalert_department id; Type: DEFAULT; Schema: public; Owner: postgres
--

ALTER TABLE ONLY public.base_departmentalert_department ALTER COLUMN id SET DEFAULT nextval('public.base_departmentalert_department_id_seq'::regclass);


--
-- TOC entry 3746 (class 2604 OID 44175)
-- Name: base_messengersentlog id; Type: DEFAULT; Schema: public; Owner: postgres
--

ALTER TABLE ONLY public.base_messengersentlog ALTER COLUMN id SET DEFAULT nextval('public.base_messengersentlog_id_seq'::regclass);


--
-- TOC entry 3655 (class 2604 OID 28234)
-- Name: base_personalalert id; Type: DEFAULT; Schema: public; Owner: postgres
--

ALTER TABLE ONLY public.base_personalalert ALTER COLUMN id SET DEFAULT nextval('public.base_personalalert_id_seq'::regclass);


--
-- TOC entry 3745 (class 2604 OID 44153)
-- Name: base_personalalert_employee id; Type: DEFAULT; Schema: public; Owner: postgres
--

ALTER TABLE ONLY public.base_personalalert_employee ALTER COLUMN id SET DEFAULT nextval('public.base_personalalert_employee_id_seq'::regclass);


--
-- TOC entry 3656 (class 2604 OID 28236)
-- Name: base_reportoutputsetting id; Type: DEFAULT; Schema: public; Owner: postgres
--

ALTER TABLE ONLY public.base_reportoutputsetting ALTER COLUMN id SET DEFAULT nextval('public.base_reportoutputsetting_id_seq'::regclass);


--
-- TOC entry 3657 (class 2604 OID 28237)
-- Name: base_securitypolicy id; Type: DEFAULT; Schema: public; Owner: postgres
--

ALTER TABLE ONLY public.base_securitypolicy ALTER COLUMN id SET DEFAULT nextval('public.base_securitypolicy_id_seq'::regclass);


--
-- TOC entry 3658 (class 2604 OID 28238)
-- Name: base_sendemail id; Type: DEFAULT; Schema: public; Owner: postgres
--

ALTER TABLE ONLY public.base_sendemail ALTER COLUMN id SET DEFAULT nextval('public.base_sendemail_id_seq'::regclass);


--
-- TOC entry 3659 (class 2604 OID 28239)
-- Name: base_sftpsetting id; Type: DEFAULT; Schema: public; Owner: postgres
--

ALTER TABLE ONLY public.base_sftpsetting ALTER COLUMN id SET DEFAULT nextval('public.base_sftpsetting_id_seq'::regclass);


--
-- TOC entry 3660 (class 2604 OID 28240)
-- Name: base_sysparam id; Type: DEFAULT; Schema: public; Owner: postgres
--

ALTER TABLE ONLY public.base_sysparam ALTER COLUMN id SET DEFAULT nextval('public.base_sysparam_id_seq'::regclass);


--
-- TOC entry 3661 (class 2604 OID 28241)
-- Name: base_sysparamdept id; Type: DEFAULT; Schema: public; Owner: postgres
--

ALTER TABLE ONLY public.base_sysparamdept ALTER COLUMN id SET DEFAULT nextval('public.base_sysparamdept_id_seq'::regclass);


--
-- TOC entry 3662 (class 2604 OID 28242)
-- Name: base_systemsetting id; Type: DEFAULT; Schema: public; Owner: postgres
--

ALTER TABLE ONLY public.base_systemsetting ALTER COLUMN id SET DEFAULT nextval('public.base_systemsetting_id_seq'::regclass);


--
-- TOC entry 3663 (class 2604 OID 28243)
-- Name: base_taskresultlog id; Type: DEFAULT; Schema: public; Owner: postgres
--

ALTER TABLE ONLY public.base_taskresultlog ALTER COLUMN id SET DEFAULT nextval('public.base_taskresultlog_id_seq'::regclass);


--
-- TOC entry 3664 (class 2604 OID 28244)
-- Name: celery_taskmeta id; Type: DEFAULT; Schema: public; Owner: postgres
--

ALTER TABLE ONLY public.celery_taskmeta ALTER COLUMN id SET DEFAULT nextval('public.celery_taskmeta_id_seq'::regclass);


--
-- TOC entry 3665 (class 2604 OID 28245)
-- Name: celery_tasksetmeta id; Type: DEFAULT; Schema: public; Owner: postgres
--

ALTER TABLE ONLY public.celery_tasksetmeta ALTER COLUMN id SET DEFAULT nextval('public.celery_tasksetmeta_id_seq'::regclass);


--
-- TOC entry 3666 (class 2604 OID 28246)
-- Name: django_admin_log id; Type: DEFAULT; Schema: public; Owner: postgres
--

ALTER TABLE ONLY public.django_admin_log ALTER COLUMN id SET DEFAULT nextval('public.django_admin_log_id_seq'::regclass);


--
-- TOC entry 3667 (class 2604 OID 28247)
-- Name: django_content_type id; Type: DEFAULT; Schema: public; Owner: postgres
--

ALTER TABLE ONLY public.django_content_type ALTER COLUMN id SET DEFAULT nextval('public.django_content_type_id_seq'::regclass);


--
-- TOC entry 3668 (class 2604 OID 28248)
-- Name: django_migrations id; Type: DEFAULT; Schema: public; Owner: postgres
--

ALTER TABLE ONLY public.django_migrations ALTER COLUMN id SET DEFAULT nextval('public.django_migrations_id_seq'::regclass);


--
-- TOC entry 3669 (class 2604 OID 28249)
-- Name: djcelery_crontabschedule id; Type: DEFAULT; Schema: public; Owner: postgres
--

ALTER TABLE ONLY public.djcelery_crontabschedule ALTER COLUMN id SET DEFAULT nextval('public.djcelery_crontabschedule_id_seq'::regclass);


--
-- TOC entry 3670 (class 2604 OID 28250)
-- Name: djcelery_intervalschedule id; Type: DEFAULT; Schema: public; Owner: postgres
--

ALTER TABLE ONLY public.djcelery_intervalschedule ALTER COLUMN id SET DEFAULT nextval('public.djcelery_intervalschedule_id_seq'::regclass);


--
-- TOC entry 3671 (class 2604 OID 28251)
-- Name: djcelery_periodictask id; Type: DEFAULT; Schema: public; Owner: postgres
--

ALTER TABLE ONLY public.djcelery_periodictask ALTER COLUMN id SET DEFAULT nextval('public.djcelery_periodictask_id_seq'::regclass);


--
-- TOC entry 3672 (class 2604 OID 28252)
-- Name: djcelery_taskstate id; Type: DEFAULT; Schema: public; Owner: postgres
--

ALTER TABLE ONLY public.djcelery_taskstate ALTER COLUMN id SET DEFAULT nextval('public.djcelery_taskstate_id_seq'::regclass);


--
-- TOC entry 3673 (class 2604 OID 28253)
-- Name: djcelery_workerstate id; Type: DEFAULT; Schema: public; Owner: postgres
--

ALTER TABLE ONLY public.djcelery_workerstate ALTER COLUMN id SET DEFAULT nextval('public.djcelery_workerstate_id_seq'::regclass);


--
-- TOC entry 3674 (class 2604 OID 28254)
-- Name: ep_epsetup id; Type: DEFAULT; Schema: public; Owner: postgres
--

ALTER TABLE ONLY public.ep_epsetup ALTER COLUMN id SET DEFAULT nextval('public.ep_epsetup_id_seq'::regclass);


--
-- TOC entry 3675 (class 2604 OID 28255)
-- Name: ep_eptransaction id; Type: DEFAULT; Schema: public; Owner: postgres
--

ALTER TABLE ONLY public.ep_eptransaction ALTER COLUMN id SET DEFAULT nextval('public.ep_eptransaction_id_seq'::regclass);


--
-- TOC entry 3676 (class 2604 OID 28256)
-- Name: guardian_groupobjectpermission id; Type: DEFAULT; Schema: public; Owner: postgres
--

ALTER TABLE ONLY public.guardian_groupobjectpermission ALTER COLUMN id SET DEFAULT nextval('public.guardian_groupobjectpermission_id_seq'::regclass);


--
-- TOC entry 3677 (class 2604 OID 28257)
-- Name: guardian_userobjectpermission id; Type: DEFAULT; Schema: public; Owner: postgres
--

ALTER TABLE ONLY public.guardian_userobjectpermission ALTER COLUMN id SET DEFAULT nextval('public.guardian_userobjectpermission_id_seq'::regclass);


--
-- TOC entry 3678 (class 2604 OID 28258)
-- Name: iclock_biodata id; Type: DEFAULT; Schema: public; Owner: postgres
--

ALTER TABLE ONLY public.iclock_biodata ALTER COLUMN id SET DEFAULT nextval('public.iclock_biodata_id_seq'::regclass);


--
-- TOC entry 3679 (class 2604 OID 28259)
-- Name: iclock_biophoto id; Type: DEFAULT; Schema: public; Owner: postgres
--

ALTER TABLE ONLY public.iclock_biophoto ALTER COLUMN id SET DEFAULT nextval('public.iclock_biophoto_id_seq'::regclass);


--
-- TOC entry 3680 (class 2604 OID 28260)
-- Name: iclock_errorcommandlog id; Type: DEFAULT; Schema: public; Owner: postgres
--

ALTER TABLE ONLY public.iclock_errorcommandlog ALTER COLUMN id SET DEFAULT nextval('public.iclock_errorcommandlog_id_seq'::regclass);


--
-- TOC entry 3681 (class 2604 OID 28261)
-- Name: iclock_privatemessage id; Type: DEFAULT; Schema: public; Owner: postgres
--

ALTER TABLE ONLY public.iclock_privatemessage ALTER COLUMN id SET DEFAULT nextval('public.iclock_privatemessage_id_seq'::regclass);


--
-- TOC entry 3682 (class 2604 OID 28262)
-- Name: iclock_publicmessage id; Type: DEFAULT; Schema: public; Owner: postgres
--

ALTER TABLE ONLY public.iclock_publicmessage ALTER COLUMN id SET DEFAULT nextval('public.iclock_publicmessage_id_seq'::regclass);


--
-- TOC entry 3683 (class 2604 OID 28263)
-- Name: iclock_terminal id; Type: DEFAULT; Schema: public; Owner: postgres
--

ALTER TABLE ONLY public.iclock_terminal ALTER COLUMN id SET DEFAULT nextval('public.iclock_terminal_id_seq'::regclass);


--
-- TOC entry 3684 (class 2604 OID 28264)
-- Name: iclock_terminalcommand id; Type: DEFAULT; Schema: public; Owner: postgres
--

ALTER TABLE ONLY public.iclock_terminalcommand ALTER COLUMN id SET DEFAULT nextval('public.iclock_terminalcommand_id_seq'::regclass);


--
-- TOC entry 3685 (class 2604 OID 28265)
-- Name: iclock_terminalcommandlog id; Type: DEFAULT; Schema: public; Owner: postgres
--

ALTER TABLE ONLY public.iclock_terminalcommandlog ALTER COLUMN id SET DEFAULT nextval('public.iclock_terminalcommandlog_id_seq'::regclass);


--
-- TOC entry 3686 (class 2604 OID 28266)
-- Name: iclock_terminalemployee id; Type: DEFAULT; Schema: public; Owner: postgres
--

ALTER TABLE ONLY public.iclock_terminalemployee ALTER COLUMN id SET DEFAULT nextval('public.iclock_terminalemployee_id_seq'::regclass);


--
-- TOC entry 3687 (class 2604 OID 28267)
-- Name: iclock_terminallog id; Type: DEFAULT; Schema: public; Owner: postgres
--

ALTER TABLE ONLY public.iclock_terminallog ALTER COLUMN id SET DEFAULT nextval('public.iclock_terminallog_id_seq'::regclass);


--
-- TOC entry 3688 (class 2604 OID 28268)
-- Name: iclock_terminalparameter id; Type: DEFAULT; Schema: public; Owner: postgres
--

ALTER TABLE ONLY public.iclock_terminalparameter ALTER COLUMN id SET DEFAULT nextval('public.iclock_terminalparameter_id_seq'::regclass);


--
-- TOC entry 3689 (class 2604 OID 28269)
-- Name: iclock_terminaluploadlog id; Type: DEFAULT; Schema: public; Owner: postgres
--

ALTER TABLE ONLY public.iclock_terminaluploadlog ALTER COLUMN id SET DEFAULT nextval('public.iclock_terminaluploadlog_id_seq'::regclass);


--
-- TOC entry 3690 (class 2604 OID 28270)
-- Name: iclock_terminalworkcode id; Type: DEFAULT; Schema: public; Owner: postgres
--

ALTER TABLE ONLY public.iclock_terminalworkcode ALTER COLUMN id SET DEFAULT nextval('public.iclock_terminalworkcode_id_seq'::regclass);


--
-- TOC entry 3691 (class 2604 OID 28271)
-- Name: iclock_transaction id; Type: DEFAULT; Schema: public; Owner: postgres
--

ALTER TABLE ONLY public.iclock_transaction ALTER COLUMN id SET DEFAULT nextval('public.iclock_transaction_id_seq'::regclass);


--
-- TOC entry 3692 (class 2604 OID 28272)
-- Name: iclock_transactionproofcmd id; Type: DEFAULT; Schema: public; Owner: postgres
--

ALTER TABLE ONLY public.iclock_transactionproofcmd ALTER COLUMN id SET DEFAULT nextval('public.iclock_transactionproofcmd_id_seq'::regclass);


--
-- TOC entry 3693 (class 2604 OID 28273)
-- Name: mobile_announcement id; Type: DEFAULT; Schema: public; Owner: postgres
--

ALTER TABLE ONLY public.mobile_announcement ALTER COLUMN id SET DEFAULT nextval('public.mobile_announcement_id_seq'::regclass);


--
-- TOC entry 3694 (class 2604 OID 28274)
-- Name: mobile_appactionlog id; Type: DEFAULT; Schema: public; Owner: postgres
--

ALTER TABLE ONLY public.mobile_appactionlog ALTER COLUMN id SET DEFAULT nextval('public.mobile_appactionlog_id_seq'::regclass);


--
-- TOC entry 3695 (class 2604 OID 28275)
-- Name: mobile_applist id; Type: DEFAULT; Schema: public; Owner: postgres
--

ALTER TABLE ONLY public.mobile_applist ALTER COLUMN id SET DEFAULT nextval('public.mobile_applist_id_seq'::regclass);


--
-- TOC entry 3696 (class 2604 OID 28276)
-- Name: mobile_appnotification id; Type: DEFAULT; Schema: public; Owner: postgres
--

ALTER TABLE ONLY public.mobile_appnotification ALTER COLUMN id SET DEFAULT nextval('public.mobile_appnotification_id_seq'::regclass);


--
-- TOC entry 3697 (class 2604 OID 28277)
-- Name: mobile_gpsfordepartment id; Type: DEFAULT; Schema: public; Owner: postgres
--

ALTER TABLE ONLY public.mobile_gpsfordepartment ALTER COLUMN id SET DEFAULT nextval('public.mobile_gpsfordepartment_id_seq'::regclass);


--
-- TOC entry 3698 (class 2604 OID 28278)
-- Name: mobile_gpsforemployee id; Type: DEFAULT; Schema: public; Owner: postgres
--

ALTER TABLE ONLY public.mobile_gpsforemployee ALTER COLUMN id SET DEFAULT nextval('public.mobile_gpsforemployee_id_seq'::regclass);


--
-- TOC entry 3699 (class 2604 OID 28279)
-- Name: notifications_notification id; Type: DEFAULT; Schema: public; Owner: postgres
--

ALTER TABLE ONLY public.notifications_notification ALTER COLUMN id SET DEFAULT nextval('public.notifications_notification_id_seq'::regclass);


--
-- TOC entry 3700 (class 2604 OID 28280)
-- Name: payroll_deductionformula id; Type: DEFAULT; Schema: public; Owner: postgres
--

ALTER TABLE ONLY public.payroll_deductionformula ALTER COLUMN id SET DEFAULT nextval('public.payroll_deductionformula_id_seq'::regclass);


--
-- TOC entry 3701 (class 2604 OID 28281)
-- Name: payroll_emploan id; Type: DEFAULT; Schema: public; Owner: postgres
--

ALTER TABLE ONLY public.payroll_emploan ALTER COLUMN id SET DEFAULT nextval('public.payroll_emploan_id_seq'::regclass);


--
-- TOC entry 3702 (class 2604 OID 28282)
-- Name: payroll_emppayrollprofile id; Type: DEFAULT; Schema: public; Owner: postgres
--

ALTER TABLE ONLY public.payroll_emppayrollprofile ALTER COLUMN id SET DEFAULT nextval('public.payroll_emppayrollprofile_id_seq'::regclass);


--
-- TOC entry 3703 (class 2604 OID 28283)
-- Name: payroll_exceptionformula id; Type: DEFAULT; Schema: public; Owner: postgres
--

ALTER TABLE ONLY public.payroll_exceptionformula ALTER COLUMN id SET DEFAULT nextval('public.payroll_exceptionformula_id_seq'::regclass);


--
-- TOC entry 3704 (class 2604 OID 28284)
-- Name: payroll_extradeduction id; Type: DEFAULT; Schema: public; Owner: postgres
--

ALTER TABLE ONLY public.payroll_extradeduction ALTER COLUMN id SET DEFAULT nextval('public.payroll_extradeduction_id_seq'::regclass);


--
-- TOC entry 3705 (class 2604 OID 28285)
-- Name: payroll_extraincrease id; Type: DEFAULT; Schema: public; Owner: postgres
--

ALTER TABLE ONLY public.payroll_extraincrease ALTER COLUMN id SET DEFAULT nextval('public.payroll_extraincrease_id_seq'::regclass);


--
-- TOC entry 3706 (class 2604 OID 28286)
-- Name: payroll_increasementformula id; Type: DEFAULT; Schema: public; Owner: postgres
--

ALTER TABLE ONLY public.payroll_increasementformula ALTER COLUMN id SET DEFAULT nextval('public.payroll_increasementformula_id_seq'::regclass);


--
-- TOC entry 3707 (class 2604 OID 28287)
-- Name: payroll_leaveformula id; Type: DEFAULT; Schema: public; Owner: postgres
--

ALTER TABLE ONLY public.payroll_leaveformula ALTER COLUMN id SET DEFAULT nextval('public.payroll_leaveformula_id_seq'::regclass);


--
-- TOC entry 3708 (class 2604 OID 28288)
-- Name: payroll_monthlysalary id; Type: DEFAULT; Schema: public; Owner: postgres
--

ALTER TABLE ONLY public.payroll_monthlysalary ALTER COLUMN id SET DEFAULT nextval('public.payroll_monthlysalary_id_seq'::regclass);


--
-- TOC entry 3709 (class 2604 OID 28289)
-- Name: payroll_overtimeformula id; Type: DEFAULT; Schema: public; Owner: postgres
--

ALTER TABLE ONLY public.payroll_overtimeformula ALTER COLUMN id SET DEFAULT nextval('public.payroll_overtimeformula_id_seq'::regclass);


--
-- TOC entry 3710 (class 2604 OID 28290)
-- Name: payroll_reimbursement id; Type: DEFAULT; Schema: public; Owner: postgres
--

ALTER TABLE ONLY public.payroll_reimbursement ALTER COLUMN id SET DEFAULT nextval('public.payroll_reimbursement_id_seq'::regclass);


--
-- TOC entry 3711 (class 2604 OID 28291)
-- Name: payroll_salaryadvance id; Type: DEFAULT; Schema: public; Owner: postgres
--

ALTER TABLE ONLY public.payroll_salaryadvance ALTER COLUMN id SET DEFAULT nextval('public.payroll_salaryadvance_id_seq'::regclass);


--
-- TOC entry 3712 (class 2604 OID 28292)
-- Name: payroll_salarystructure id; Type: DEFAULT; Schema: public; Owner: postgres
--

ALTER TABLE ONLY public.payroll_salarystructure ALTER COLUMN id SET DEFAULT nextval('public.payroll_salarystructure_id_seq'::regclass);


--
-- TOC entry 3713 (class 2604 OID 28293)
-- Name: payroll_salarystructure_deductionformula id; Type: DEFAULT; Schema: public; Owner: postgres
--

ALTER TABLE ONLY public.payroll_salarystructure_deductionformula ALTER COLUMN id SET DEFAULT nextval('public.payroll_salarystructure_deductionformula_id_seq'::regclass);


--
-- TOC entry 3714 (class 2604 OID 28294)
-- Name: payroll_salarystructure_exceptionformula id; Type: DEFAULT; Schema: public; Owner: postgres
--

ALTER TABLE ONLY public.payroll_salarystructure_exceptionformula ALTER COLUMN id SET DEFAULT nextval('public.payroll_salarystructure_exceptionformula_id_seq'::regclass);


--
-- TOC entry 3715 (class 2604 OID 28295)
-- Name: payroll_salarystructure_increasementformula id; Type: DEFAULT; Schema: public; Owner: postgres
--

ALTER TABLE ONLY public.payroll_salarystructure_increasementformula ALTER COLUMN id SET DEFAULT nextval('public.payroll_salarystructure_increasementformula_id_seq'::regclass);


--
-- TOC entry 3716 (class 2604 OID 28296)
-- Name: payroll_salarystructure_leaveformula id; Type: DEFAULT; Schema: public; Owner: postgres
--

ALTER TABLE ONLY public.payroll_salarystructure_leaveformula ALTER COLUMN id SET DEFAULT nextval('public.payroll_salarystructure_leaveformula_id_seq'::regclass);


--
-- TOC entry 3717 (class 2604 OID 28297)
-- Name: payroll_salarystructure_overtimeformula id; Type: DEFAULT; Schema: public; Owner: postgres
--

ALTER TABLE ONLY public.payroll_salarystructure_overtimeformula ALTER COLUMN id SET DEFAULT nextval('public.payroll_salarystructure_overtimeformula_id_seq'::regclass);


--
-- TOC entry 3718 (class 2604 OID 28298)
-- Name: personnel_area id; Type: DEFAULT; Schema: public; Owner: postgres
--

ALTER TABLE ONLY public.personnel_area ALTER COLUMN id SET DEFAULT nextval('public.personnel_area_id_seq'::regclass);


--
-- TOC entry 3719 (class 2604 OID 28299)
-- Name: personnel_assignareaemployee id; Type: DEFAULT; Schema: public; Owner: postgres
--

ALTER TABLE ONLY public.personnel_assignareaemployee ALTER COLUMN id SET DEFAULT nextval('public.personnel_assignareaemployee_id_seq'::regclass);


--
-- TOC entry 3720 (class 2604 OID 28300)
-- Name: personnel_certification id; Type: DEFAULT; Schema: public; Owner: postgres
--

ALTER TABLE ONLY public.personnel_certification ALTER COLUMN id SET DEFAULT nextval('public.personnel_certification_id_seq'::regclass);


--
-- TOC entry 3721 (class 2604 OID 28301)
-- Name: personnel_company id; Type: DEFAULT; Schema: public; Owner: postgres
--

ALTER TABLE ONLY public.personnel_company ALTER COLUMN id SET DEFAULT nextval('public.personnel_company_id_seq'::regclass);


--
-- TOC entry 3722 (class 2604 OID 28302)
-- Name: personnel_companyregister id; Type: DEFAULT; Schema: public; Owner: postgres
--

ALTER TABLE ONLY public.personnel_companyregister ALTER COLUMN id SET DEFAULT nextval('public.personnel_companyregister_id_seq'::regclass);


--
-- TOC entry 3723 (class 2604 OID 28303)
-- Name: personnel_department id; Type: DEFAULT; Schema: public; Owner: postgres
--

ALTER TABLE ONLY public.personnel_department ALTER COLUMN id SET DEFAULT nextval('public.personnel_department_id_seq'::regclass);


--
-- TOC entry 3724 (class 2604 OID 28304)
-- Name: personnel_employee id; Type: DEFAULT; Schema: public; Owner: postgres
--

ALTER TABLE ONLY public.personnel_employee ALTER COLUMN id SET DEFAULT nextval('public.personnel_employee_id_seq'::regclass);


--
-- TOC entry 3725 (class 2604 OID 28305)
-- Name: personnel_employee_area id; Type: DEFAULT; Schema: public; Owner: postgres
--

ALTER TABLE ONLY public.personnel_employee_area ALTER COLUMN id SET DEFAULT nextval('public.personnel_employee_area_id_seq'::regclass);


--
-- TOC entry 3726 (class 2604 OID 28306)
-- Name: personnel_employee_area_privilege id; Type: DEFAULT; Schema: public; Owner: postgres
--

ALTER TABLE ONLY public.personnel_employee_area_privilege ALTER COLUMN id SET DEFAULT nextval('public.personnel_employee_area_privilege_id_seq'::regclass);


--
-- TOC entry 3727 (class 2604 OID 28307)
-- Name: personnel_employee_flow_role id; Type: DEFAULT; Schema: public; Owner: postgres
--

ALTER TABLE ONLY public.personnel_employee_flow_role ALTER COLUMN id SET DEFAULT nextval('public.personnel_employee_flow_role_id_seq'::regclass);


--
-- TOC entry 3728 (class 2604 OID 28308)
-- Name: personnel_employeecertification id; Type: DEFAULT; Schema: public; Owner: postgres
--

ALTER TABLE ONLY public.personnel_employeecertification ALTER COLUMN id SET DEFAULT nextval('public.personnel_employeecertification_id_seq'::regclass);


--
-- TOC entry 3729 (class 2604 OID 28309)
-- Name: personnel_employeeprofile id; Type: DEFAULT; Schema: public; Owner: postgres
--

ALTER TABLE ONLY public.personnel_employeeprofile ALTER COLUMN id SET DEFAULT nextval('public.personnel_employeeprofile_id_seq'::regclass);


--
-- TOC entry 3730 (class 2604 OID 28310)
-- Name: personnel_position id; Type: DEFAULT; Schema: public; Owner: postgres
--

ALTER TABLE ONLY public.personnel_position ALTER COLUMN id SET DEFAULT nextval('public.personnel_position_id_seq'::regclass);


--
-- TOC entry 3731 (class 2604 OID 28311)
-- Name: personnel_resign id; Type: DEFAULT; Schema: public; Owner: postgres
--

ALTER TABLE ONLY public.personnel_resign ALTER COLUMN id SET DEFAULT nextval('public.personnel_resign_id_seq'::regclass);


--
-- TOC entry 3732 (class 2604 OID 28312)
-- Name: sync_area id; Type: DEFAULT; Schema: public; Owner: postgres
--

ALTER TABLE ONLY public.sync_area ALTER COLUMN id SET DEFAULT nextval('public.sync_area_id_seq'::regclass);


--
-- TOC entry 3733 (class 2604 OID 28313)
-- Name: sync_department id; Type: DEFAULT; Schema: public; Owner: postgres
--

ALTER TABLE ONLY public.sync_department ALTER COLUMN id SET DEFAULT nextval('public.sync_department_id_seq'::regclass);


--
-- TOC entry 3734 (class 2604 OID 28314)
-- Name: sync_employee id; Type: DEFAULT; Schema: public; Owner: postgres
--

ALTER TABLE ONLY public.sync_employee ALTER COLUMN id SET DEFAULT nextval('public.sync_employee_id_seq'::regclass);


--
-- TOC entry 3735 (class 2604 OID 28315)
-- Name: sync_job id; Type: DEFAULT; Schema: public; Owner: postgres
--

ALTER TABLE ONLY public.sync_job ALTER COLUMN id SET DEFAULT nextval('public.sync_job_id_seq'::regclass);


--
-- TOC entry 3736 (class 2604 OID 28316)
-- Name: workflow_abstractexception id; Type: DEFAULT; Schema: public; Owner: postgres
--

ALTER TABLE ONLY public.workflow_abstractexception ALTER COLUMN id SET DEFAULT nextval('public.workflow_abstractexception_id_seq'::regclass);


--
-- TOC entry 3737 (class 2604 OID 28317)
-- Name: workflow_nodeinstance id; Type: DEFAULT; Schema: public; Owner: postgres
--

ALTER TABLE ONLY public.workflow_nodeinstance ALTER COLUMN id SET DEFAULT nextval('public.workflow_nodeinstance_id_seq'::regclass);


--
-- TOC entry 3738 (class 2604 OID 28318)
-- Name: workflow_workflowengine id; Type: DEFAULT; Schema: public; Owner: postgres
--

ALTER TABLE ONLY public.workflow_workflowengine ALTER COLUMN id SET DEFAULT nextval('public.workflow_workflowengine_id_seq'::regclass);


--
-- TOC entry 3739 (class 2604 OID 28319)
-- Name: workflow_workflowengine_employee id; Type: DEFAULT; Schema: public; Owner: postgres
--

ALTER TABLE ONLY public.workflow_workflowengine_employee ALTER COLUMN id SET DEFAULT nextval('public.workflow_workflowengine_employee_id_seq'::regclass);


--
-- TOC entry 3740 (class 2604 OID 28320)
-- Name: workflow_workflowinstance id; Type: DEFAULT; Schema: public; Owner: postgres
--

ALTER TABLE ONLY public.workflow_workflowinstance ALTER COLUMN id SET DEFAULT nextval('public.workflow_workflowinstance_id_seq'::regclass);


--
-- TOC entry 3741 (class 2604 OID 28321)
-- Name: workflow_workflownode id; Type: DEFAULT; Schema: public; Owner: postgres
--

ALTER TABLE ONLY public.workflow_workflownode ALTER COLUMN id SET DEFAULT nextval('public.workflow_workflownode_id_seq'::regclass);


--
-- TOC entry 3742 (class 2604 OID 28322)
-- Name: workflow_workflownode_approver id; Type: DEFAULT; Schema: public; Owner: postgres
--

ALTER TABLE ONLY public.workflow_workflownode_approver ALTER COLUMN id SET DEFAULT nextval('public.workflow_workflownode_approver_id_seq'::regclass);


--
-- TOC entry 3743 (class 2604 OID 28323)
-- Name: workflow_workflownode_notifier id; Type: DEFAULT; Schema: public; Owner: postgres
--

ALTER TABLE ONLY public.workflow_workflownode_notifier ALTER COLUMN id SET DEFAULT nextval('public.workflow_workflownode_notifier_id_seq'::regclass);


--
-- TOC entry 3744 (class 2604 OID 28324)
-- Name: workflow_workflowrole id; Type: DEFAULT; Schema: public; Owner: postgres
--

ALTER TABLE ONLY public.workflow_workflowrole ALTER COLUMN id SET DEFAULT nextval('public.workflow_workflowrole_id_seq'::regclass);


--
-- TOC entry 3751 (class 2606 OID 28328)
-- Name: acc_acccombination acc_acccombination_area_id_combination_no_619eb4f5_uniq; Type: CONSTRAINT; Schema: public; Owner: postgres
--

ALTER TABLE ONLY public.acc_acccombination
    ADD CONSTRAINT acc_acccombination_area_id_combination_no_619eb4f5_uniq UNIQUE (area_id, combination_no);


--
-- TOC entry 3753 (class 2606 OID 28330)
-- Name: acc_acccombination acc_acccombination_pkey; Type: CONSTRAINT; Schema: public; Owner: postgres
--

ALTER TABLE ONLY public.acc_acccombination
    ADD CONSTRAINT acc_acccombination_pkey PRIMARY KEY (id);


--
-- TOC entry 3756 (class 2606 OID 28332)
-- Name: acc_accgroups acc_accgroups_area_id_group_no_5130a89c_uniq; Type: CONSTRAINT; Schema: public; Owner: postgres
--

ALTER TABLE ONLY public.acc_accgroups
    ADD CONSTRAINT acc_accgroups_area_id_group_no_5130a89c_uniq UNIQUE (area_id, group_no);


--
-- TOC entry 3758 (class 2606 OID 28334)
-- Name: acc_accgroups acc_accgroups_pkey; Type: CONSTRAINT; Schema: public; Owner: postgres
--

ALTER TABLE ONLY public.acc_accgroups
    ADD CONSTRAINT acc_accgroups_pkey PRIMARY KEY (id);


--
-- TOC entry 3761 (class 2606 OID 28336)
-- Name: acc_accholiday acc_accholiday_area_id_holiday_id_6630c2eb_uniq; Type: CONSTRAINT; Schema: public; Owner: postgres
--

ALTER TABLE ONLY public.acc_accholiday
    ADD CONSTRAINT acc_accholiday_area_id_holiday_id_6630c2eb_uniq UNIQUE (area_id, holiday_id);


--
-- TOC entry 3764 (class 2606 OID 28338)
-- Name: acc_accholiday acc_accholiday_pkey; Type: CONSTRAINT; Schema: public; Owner: postgres
--

ALTER TABLE ONLY public.acc_accholiday
    ADD CONSTRAINT acc_accholiday_pkey PRIMARY KEY (id);


--
-- TOC entry 3768 (class 2606 OID 28340)
-- Name: acc_accprivilege acc_accprivilege_area_id_employee_id_group_id_f3b297d8_uniq; Type: CONSTRAINT; Schema: public; Owner: postgres
--

ALTER TABLE ONLY public.acc_accprivilege
    ADD CONSTRAINT acc_accprivilege_area_id_employee_id_group_id_f3b297d8_uniq UNIQUE (area_id, employee_id, group_id);


--
-- TOC entry 3772 (class 2606 OID 28342)
-- Name: acc_accprivilege acc_accprivilege_pkey; Type: CONSTRAINT; Schema: public; Owner: postgres
--

ALTER TABLE ONLY public.acc_accprivilege
    ADD CONSTRAINT acc_accprivilege_pkey PRIMARY KEY (id);


--
-- TOC entry 3774 (class 2606 OID 28344)
-- Name: acc_accterminal acc_accterminal_pkey; Type: CONSTRAINT; Schema: public; Owner: postgres
--

ALTER TABLE ONLY public.acc_accterminal
    ADD CONSTRAINT acc_accterminal_pkey PRIMARY KEY (id);


--
-- TOC entry 3778 (class 2606 OID 28346)
-- Name: acc_acctimezone acc_acctimezone_area_id_timezone_no_0cb8250f_uniq; Type: CONSTRAINT; Schema: public; Owner: postgres
--

ALTER TABLE ONLY public.acc_acctimezone
    ADD CONSTRAINT acc_acctimezone_area_id_timezone_no_0cb8250f_uniq UNIQUE (area_id, timezone_no);


--
-- TOC entry 3780 (class 2606 OID 28348)
-- Name: acc_acctimezone acc_acctimezone_pkey; Type: CONSTRAINT; Schema: public; Owner: postgres
--

ALTER TABLE ONLY public.acc_acctimezone
    ADD CONSTRAINT acc_acctimezone_pkey PRIMARY KEY (id);


--
-- TOC entry 3783 (class 2606 OID 28350)
-- Name: accounts_adminbiodata accounts_adminbiodata_pkey; Type: CONSTRAINT; Schema: public; Owner: postgres
--

ALTER TABLE ONLY public.accounts_adminbiodata
    ADD CONSTRAINT accounts_adminbiodata_pkey PRIMARY KEY (id);


--
-- TOC entry 3785 (class 2606 OID 28352)
-- Name: accounts_usersecuritypolicy accounts_usersecuritypolicy_pkey; Type: CONSTRAINT; Schema: public; Owner: postgres
--

ALTER TABLE ONLY public.accounts_usersecuritypolicy
    ADD CONSTRAINT accounts_usersecuritypolicy_pkey PRIMARY KEY (id);


--
-- TOC entry 3787 (class 2606 OID 28354)
-- Name: att_attcalclog att_attcalclog_pkey; Type: CONSTRAINT; Schema: public; Owner: postgres
--

ALTER TABLE ONLY public.att_attcalclog
    ADD CONSTRAINT att_attcalclog_pkey PRIMARY KEY (id);


--
-- TOC entry 3789 (class 2606 OID 28356)
-- Name: att_attreportsetting att_attreportsetting_pkey; Type: CONSTRAINT; Schema: public; Owner: postgres
--

ALTER TABLE ONLY public.att_attreportsetting
    ADD CONSTRAINT att_attreportsetting_pkey PRIMARY KEY (id);


--
-- TOC entry 3792 (class 2606 OID 28358)
-- Name: att_attrule att_attrule_pkey; Type: CONSTRAINT; Schema: public; Owner: postgres
--

ALTER TABLE ONLY public.att_attrule
    ADD CONSTRAINT att_attrule_pkey PRIMARY KEY (param_name);


--
-- TOC entry 3795 (class 2606 OID 28360)
-- Name: att_attschedule att_attschedule_pkey; Type: CONSTRAINT; Schema: public; Owner: postgres
--

ALTER TABLE ONLY public.att_attschedule
    ADD CONSTRAINT att_attschedule_pkey PRIMARY KEY (id);


--
-- TOC entry 3799 (class 2606 OID 28362)
-- Name: att_attshift att_attshift_pkey; Type: CONSTRAINT; Schema: public; Owner: postgres
--

ALTER TABLE ONLY public.att_attshift
    ADD CONSTRAINT att_attshift_pkey PRIMARY KEY (id);


--
-- TOC entry 3801 (class 2606 OID 28364)
-- Name: att_breaktime att_breaktime_alias_company_id_d9efd675_uniq; Type: CONSTRAINT; Schema: public; Owner: postgres
--

ALTER TABLE ONLY public.att_breaktime
    ADD CONSTRAINT att_breaktime_alias_company_id_d9efd675_uniq UNIQUE (alias, company_id);


--
-- TOC entry 3804 (class 2606 OID 28366)
-- Name: att_breaktime att_breaktime_pkey; Type: CONSTRAINT; Schema: public; Owner: postgres
--

ALTER TABLE ONLY public.att_breaktime
    ADD CONSTRAINT att_breaktime_pkey PRIMARY KEY (id);


--
-- TOC entry 3807 (class 2606 OID 28368)
-- Name: att_changeschedule att_changeschedule_pkey; Type: CONSTRAINT; Schema: public; Owner: postgres
--

ALTER TABLE ONLY public.att_changeschedule
    ADD CONSTRAINT att_changeschedule_pkey PRIMARY KEY (abstractexception_ptr_id);


--
-- TOC entry 3811 (class 2606 OID 28370)
-- Name: att_departmentschedule att_departmentschedule_pkey; Type: CONSTRAINT; Schema: public; Owner: postgres
--

ALTER TABLE ONLY public.att_departmentschedule
    ADD CONSTRAINT att_departmentschedule_pkey PRIMARY KEY (id);


--
-- TOC entry 3816 (class 2606 OID 28372)
-- Name: att_deptattrule att_deptattrule_pkey; Type: CONSTRAINT; Schema: public; Owner: postgres
--

ALTER TABLE ONLY public.att_deptattrule
    ADD CONSTRAINT att_deptattrule_pkey PRIMARY KEY (id);


--
-- TOC entry 3819 (class 2606 OID 28374)
-- Name: att_holiday att_holiday_pkey; Type: CONSTRAINT; Schema: public; Owner: postgres
--

ALTER TABLE ONLY public.att_holiday
    ADD CONSTRAINT att_holiday_pkey PRIMARY KEY (id);


--
-- TOC entry 3823 (class 2606 OID 28376)
-- Name: att_leave att_leave_pkey; Type: CONSTRAINT; Schema: public; Owner: postgres
--

ALTER TABLE ONLY public.att_leave
    ADD CONSTRAINT att_leave_pkey PRIMARY KEY (abstractexception_ptr_id);


--
-- TOC entry 3825 (class 2606 OID 28378)
-- Name: att_leavecategory att_leavecategory_pkey; Type: CONSTRAINT; Schema: public; Owner: postgres
--

ALTER TABLE ONLY public.att_leavecategory
    ADD CONSTRAINT att_leavecategory_pkey PRIMARY KEY (id);


--
-- TOC entry 3828 (class 2606 OID 28380)
-- Name: att_manuallog att_manuallog_pkey; Type: CONSTRAINT; Schema: public; Owner: postgres
--

ALTER TABLE ONLY public.att_manuallog
    ADD CONSTRAINT att_manuallog_pkey PRIMARY KEY (abstractexception_ptr_id);


--
-- TOC entry 3831 (class 2606 OID 28382)
-- Name: att_overtime att_overtime_pkey; Type: CONSTRAINT; Schema: public; Owner: postgres
--

ALTER TABLE ONLY public.att_overtime
    ADD CONSTRAINT att_overtime_pkey PRIMARY KEY (abstractexception_ptr_id);


--
-- TOC entry 3834 (class 2606 OID 28384)
-- Name: att_payloadbase att_payloadbase_break_time_id_key; Type: CONSTRAINT; Schema: public; Owner: postgres
--

ALTER TABLE ONLY public.att_payloadbase
    ADD CONSTRAINT att_payloadbase_break_time_id_key UNIQUE (break_time_id);


--
-- TOC entry 3838 (class 2606 OID 28386)
-- Name: att_payloadbase att_payloadbase_overtime_id_key; Type: CONSTRAINT; Schema: public; Owner: postgres
--

ALTER TABLE ONLY public.att_payloadbase
    ADD CONSTRAINT att_payloadbase_overtime_id_key UNIQUE (overtime_id);


--
-- TOC entry 3840 (class 2606 OID 28388)
-- Name: att_payloadbase att_payloadbase_pkey; Type: CONSTRAINT; Schema: public; Owner: postgres
--

ALTER TABLE ONLY public.att_payloadbase
    ADD CONSTRAINT att_payloadbase_pkey PRIMARY KEY (uuid);


--
-- TOC entry 3846 (class 2606 OID 28390)
-- Name: att_payloadbreak att_payloadbreak_pkey; Type: CONSTRAINT; Schema: public; Owner: postgres
--

ALTER TABLE ONLY public.att_payloadbreak
    ADD CONSTRAINT att_payloadbreak_pkey PRIMARY KEY (uuid);


--
-- TOC entry 3850 (class 2606 OID 28392)
-- Name: att_payloadexception att_payloadexception_pkey; Type: CONSTRAINT; Schema: public; Owner: postgres
--

ALTER TABLE ONLY public.att_payloadexception
    ADD CONSTRAINT att_payloadexception_pkey PRIMARY KEY (uuid);


--
-- TOC entry 3856 (class 2606 OID 28394)
-- Name: att_payloadmulpunchset att_payloadmulpunchset_pkey; Type: CONSTRAINT; Schema: public; Owner: postgres
--

ALTER TABLE ONLY public.att_payloadmulpunchset
    ADD CONSTRAINT att_payloadmulpunchset_pkey PRIMARY KEY (id);


--
-- TOC entry 3859 (class 2606 OID 28396)
-- Name: att_payloadovertime att_payloadovertime_pkey; Type: CONSTRAINT; Schema: public; Owner: postgres
--

ALTER TABLE ONLY public.att_payloadovertime
    ADD CONSTRAINT att_payloadovertime_pkey PRIMARY KEY (uuid);


--
-- TOC entry 3864 (class 2606 OID 28398)
-- Name: att_payloadpunch att_payloadpunch_pkey; Type: CONSTRAINT; Schema: public; Owner: postgres
--

ALTER TABLE ONLY public.att_payloadpunch
    ADD CONSTRAINT att_payloadpunch_pkey PRIMARY KEY (uuid);


--
-- TOC entry 3870 (class 2606 OID 28400)
-- Name: att_reportparam att_reportparam_pkey; Type: CONSTRAINT; Schema: public; Owner: postgres
--

ALTER TABLE ONLY public.att_reportparam
    ADD CONSTRAINT att_reportparam_pkey PRIMARY KEY (param_name);


--
-- TOC entry 3872 (class 2606 OID 28402)
-- Name: att_shiftdetail att_shiftdetail_pkey; Type: CONSTRAINT; Schema: public; Owner: postgres
--

ALTER TABLE ONLY public.att_shiftdetail
    ADD CONSTRAINT att_shiftdetail_pkey PRIMARY KEY (id);


--
-- TOC entry 3877 (class 2606 OID 28404)
-- Name: att_tempschedule att_tempschedule_pkey; Type: CONSTRAINT; Schema: public; Owner: postgres
--

ALTER TABLE ONLY public.att_tempschedule
    ADD CONSTRAINT att_tempschedule_pkey PRIMARY KEY (id);


--
-- TOC entry 3883 (class 2606 OID 28406)
-- Name: att_timeinterval_break_time att_timeinterval_break_t_timeinterval_id_breaktim_6e1bfb4e_uniq; Type: CONSTRAINT; Schema: public; Owner: postgres
--

ALTER TABLE ONLY public.att_timeinterval_break_time
    ADD CONSTRAINT att_timeinterval_break_t_timeinterval_id_breaktim_6e1bfb4e_uniq UNIQUE (timeinterval_id, breaktime_id);


--
-- TOC entry 3886 (class 2606 OID 28408)
-- Name: att_timeinterval_break_time att_timeinterval_break_time_pkey; Type: CONSTRAINT; Schema: public; Owner: postgres
--

ALTER TABLE ONLY public.att_timeinterval_break_time
    ADD CONSTRAINT att_timeinterval_break_time_pkey PRIMARY KEY (id);


--
-- TOC entry 3881 (class 2606 OID 28410)
-- Name: att_timeinterval att_timeinterval_pkey; Type: CONSTRAINT; Schema: public; Owner: postgres
--

ALTER TABLE ONLY public.att_timeinterval
    ADD CONSTRAINT att_timeinterval_pkey PRIMARY KEY (id);


--
-- TOC entry 3891 (class 2606 OID 28412)
-- Name: att_training att_training_pkey; Type: CONSTRAINT; Schema: public; Owner: postgres
--

ALTER TABLE ONLY public.att_training
    ADD CONSTRAINT att_training_pkey PRIMARY KEY (abstractexception_ptr_id);


--
-- TOC entry 3893 (class 2606 OID 28414)
-- Name: att_trainingcategory att_trainingcategory_pkey; Type: CONSTRAINT; Schema: public; Owner: postgres
--

ALTER TABLE ONLY public.att_trainingcategory
    ADD CONSTRAINT att_trainingcategory_pkey PRIMARY KEY (id);


--
-- TOC entry 3897 (class 2606 OID 28416)
-- Name: att_vacationemployee att_vacationemployee_pkey; Type: CONSTRAINT; Schema: public; Owner: postgres
--

ALTER TABLE ONLY public.att_vacationemployee
    ADD CONSTRAINT att_vacationemployee_pkey PRIMARY KEY (id);


--
-- TOC entry 3900 (class 2606 OID 28418)
-- Name: att_vacationtime att_vacationtime_category_code_company_id_6be3ea7c_uniq; Type: CONSTRAINT; Schema: public; Owner: postgres
--

ALTER TABLE ONLY public.att_vacationtime
    ADD CONSTRAINT att_vacationtime_category_code_company_id_6be3ea7c_uniq UNIQUE (category_code, company_id);


--
-- TOC entry 3903 (class 2606 OID 28420)
-- Name: att_vacationtime att_vacationtime_pkey; Type: CONSTRAINT; Schema: public; Owner: postgres
--

ALTER TABLE ONLY public.att_vacationtime
    ADD CONSTRAINT att_vacationtime_pkey PRIMARY KEY (id);


--
-- TOC entry 3905 (class 2606 OID 28422)
-- Name: att_vacationtimeseniority att_vacationtimeseniority_pkey; Type: CONSTRAINT; Schema: public; Owner: postgres
--

ALTER TABLE ONLY public.att_vacationtimeseniority
    ADD CONSTRAINT att_vacationtimeseniority_pkey PRIMARY KEY (id);


--
-- TOC entry 3908 (class 2606 OID 28424)
-- Name: attparam attparam_paraname_paratype_6f176d25_uniq; Type: CONSTRAINT; Schema: public; Owner: postgres
--

ALTER TABLE ONLY public.attparam
    ADD CONSTRAINT attparam_paraname_paratype_6f176d25_uniq UNIQUE (paraname, paratype);


--
-- TOC entry 3910 (class 2606 OID 28426)
-- Name: attparam attparam_pkey; Type: CONSTRAINT; Schema: public; Owner: postgres
--

ALTER TABLE ONLY public.attparam
    ADD CONSTRAINT attparam_pkey PRIMARY KEY (id);


--
-- TOC entry 3913 (class 2606 OID 28428)
-- Name: auth_group auth_group_name_key; Type: CONSTRAINT; Schema: public; Owner: postgres
--

ALTER TABLE ONLY public.auth_group
    ADD CONSTRAINT auth_group_name_key UNIQUE (name);


--
-- TOC entry 3918 (class 2606 OID 28430)
-- Name: auth_group_permissions auth_group_permissions_group_id_permission_id_0cd325b0_uniq; Type: CONSTRAINT; Schema: public; Owner: postgres
--

ALTER TABLE ONLY public.auth_group_permissions
    ADD CONSTRAINT auth_group_permissions_group_id_permission_id_0cd325b0_uniq UNIQUE (group_id, permission_id);


--
-- TOC entry 3921 (class 2606 OID 28432)
-- Name: auth_group_permissions auth_group_permissions_pkey; Type: CONSTRAINT; Schema: public; Owner: postgres
--

ALTER TABLE ONLY public.auth_group_permissions
    ADD CONSTRAINT auth_group_permissions_pkey PRIMARY KEY (id);


--
-- TOC entry 3915 (class 2606 OID 28434)
-- Name: auth_group auth_group_pkey; Type: CONSTRAINT; Schema: public; Owner: postgres
--

ALTER TABLE ONLY public.auth_group
    ADD CONSTRAINT auth_group_pkey PRIMARY KEY (id);


--
-- TOC entry 3924 (class 2606 OID 28436)
-- Name: auth_permission auth_permission_content_type_id_codename_01ab375a_uniq; Type: CONSTRAINT; Schema: public; Owner: postgres
--

ALTER TABLE ONLY public.auth_permission
    ADD CONSTRAINT auth_permission_content_type_id_codename_01ab375a_uniq UNIQUE (content_type_id, codename);


--
-- TOC entry 3926 (class 2606 OID 28438)
-- Name: auth_permission auth_permission_pkey; Type: CONSTRAINT; Schema: public; Owner: postgres
--

ALTER TABLE ONLY public.auth_permission
    ADD CONSTRAINT auth_permission_pkey PRIMARY KEY (id);


--
-- TOC entry 3936 (class 2606 OID 28440)
-- Name: auth_user_auth_area auth_user_auth_area_myuser_id_area_id_02a19d63_uniq; Type: CONSTRAINT; Schema: public; Owner: postgres
--

ALTER TABLE ONLY public.auth_user_auth_area
    ADD CONSTRAINT auth_user_auth_area_myuser_id_area_id_02a19d63_uniq UNIQUE (myuser_id, area_id);


--
-- TOC entry 3938 (class 2606 OID 28442)
-- Name: auth_user_auth_area auth_user_auth_area_pkey; Type: CONSTRAINT; Schema: public; Owner: postgres
--

ALTER TABLE ONLY public.auth_user_auth_area
    ADD CONSTRAINT auth_user_auth_area_pkey PRIMARY KEY (id);


--
-- TOC entry 3942 (class 2606 OID 28444)
-- Name: auth_user_auth_dept auth_user_auth_dept_myuser_id_department_id_61d83386_uniq; Type: CONSTRAINT; Schema: public; Owner: postgres
--

ALTER TABLE ONLY public.auth_user_auth_dept
    ADD CONSTRAINT auth_user_auth_dept_myuser_id_department_id_61d83386_uniq UNIQUE (myuser_id, department_id);


--
-- TOC entry 3944 (class 2606 OID 28446)
-- Name: auth_user_auth_dept auth_user_auth_dept_pkey; Type: CONSTRAINT; Schema: public; Owner: postgres
--

ALTER TABLE ONLY public.auth_user_auth_dept
    ADD CONSTRAINT auth_user_auth_dept_pkey PRIMARY KEY (id);


--
-- TOC entry 3948 (class 2606 OID 28448)
-- Name: auth_user_groups auth_user_groups_myuser_id_group_id_664bdfc3_uniq; Type: CONSTRAINT; Schema: public; Owner: postgres
--

ALTER TABLE ONLY public.auth_user_groups
    ADD CONSTRAINT auth_user_groups_myuser_id_group_id_664bdfc3_uniq UNIQUE (myuser_id, group_id);


--
-- TOC entry 3950 (class 2606 OID 28450)
-- Name: auth_user_groups auth_user_groups_pkey; Type: CONSTRAINT; Schema: public; Owner: postgres
--

ALTER TABLE ONLY public.auth_user_groups
    ADD CONSTRAINT auth_user_groups_pkey PRIMARY KEY (id);


--
-- TOC entry 3929 (class 2606 OID 28452)
-- Name: auth_user auth_user_pkey; Type: CONSTRAINT; Schema: public; Owner: postgres
--

ALTER TABLE ONLY public.auth_user
    ADD CONSTRAINT auth_user_pkey PRIMARY KEY (id);


--
-- TOC entry 3952 (class 2606 OID 28454)
-- Name: auth_user_profile auth_user_profile_pkey; Type: CONSTRAINT; Schema: public; Owner: postgres
--

ALTER TABLE ONLY public.auth_user_profile
    ADD CONSTRAINT auth_user_profile_pkey PRIMARY KEY (id);


--
-- TOC entry 3954 (class 2606 OID 28456)
-- Name: auth_user_profile auth_user_profile_user_id_key; Type: CONSTRAINT; Schema: public; Owner: postgres
--

ALTER TABLE ONLY public.auth_user_profile
    ADD CONSTRAINT auth_user_profile_user_id_key UNIQUE (user_id);


--
-- TOC entry 3956 (class 2606 OID 28458)
-- Name: auth_user_user_permissions auth_user_user_permissio_myuser_id_permission_id_a558717f_uniq; Type: CONSTRAINT; Schema: public; Owner: postgres
--

ALTER TABLE ONLY public.auth_user_user_permissions
    ADD CONSTRAINT auth_user_user_permissio_myuser_id_permission_id_a558717f_uniq UNIQUE (myuser_id, permission_id);


--
-- TOC entry 3960 (class 2606 OID 28460)
-- Name: auth_user_user_permissions auth_user_user_permissions_pkey; Type: CONSTRAINT; Schema: public; Owner: postgres
--

ALTER TABLE ONLY public.auth_user_user_permissions
    ADD CONSTRAINT auth_user_user_permissions_pkey PRIMARY KEY (id);


--
-- TOC entry 3932 (class 2606 OID 28462)
-- Name: auth_user auth_user_username_key; Type: CONSTRAINT; Schema: public; Owner: postgres
--

ALTER TABLE ONLY public.auth_user
    ADD CONSTRAINT auth_user_username_key UNIQUE (username);


--
-- TOC entry 3963 (class 2606 OID 28464)
-- Name: authtoken_token authtoken_token_pkey; Type: CONSTRAINT; Schema: public; Owner: postgres
--

ALTER TABLE ONLY public.authtoken_token
    ADD CONSTRAINT authtoken_token_pkey PRIMARY KEY (key);


--
-- TOC entry 3965 (class 2606 OID 28466)
-- Name: authtoken_token authtoken_token_user_id_key; Type: CONSTRAINT; Schema: public; Owner: postgres
--

ALTER TABLE ONLY public.authtoken_token
    ADD CONSTRAINT authtoken_token_user_id_key UNIQUE (user_id);


--
-- TOC entry 3968 (class 2606 OID 28468)
-- Name: base_adminlog base_adminlog_pkey; Type: CONSTRAINT; Schema: public; Owner: postgres
--

ALTER TABLE ONLY public.base_adminlog
    ADD CONSTRAINT base_adminlog_pkey PRIMARY KEY (id);


--
-- TOC entry 3971 (class 2606 OID 28470)
-- Name: base_attparamdepts base_attparamdepts_pkey; Type: CONSTRAINT; Schema: public; Owner: postgres
--

ALTER TABLE ONLY public.base_attparamdepts
    ADD CONSTRAINT base_attparamdepts_pkey PRIMARY KEY (id);


--
-- TOC entry 3974 (class 2606 OID 28472)
-- Name: base_attparamdepts base_attparamdepts_rulename_key; Type: CONSTRAINT; Schema: public; Owner: postgres
--

ALTER TABLE ONLY public.base_attparamdepts
    ADD CONSTRAINT base_attparamdepts_rulename_key UNIQUE (rulename);


--
-- TOC entry 3976 (class 2606 OID 28474)
-- Name: base_autoexporttask base_autoexporttask_pkey; Type: CONSTRAINT; Schema: public; Owner: postgres
--

ALTER TABLE ONLY public.base_autoexporttask
    ADD CONSTRAINT base_autoexporttask_pkey PRIMARY KEY (id);


--
-- TOC entry 3979 (class 2606 OID 28476)
-- Name: base_autoexporttask base_autoexporttask_task_code_key; Type: CONSTRAINT; Schema: public; Owner: postgres
--

ALTER TABLE ONLY public.base_autoexporttask
    ADD CONSTRAINT base_autoexporttask_task_code_key UNIQUE (task_code);


--
-- TOC entry 3982 (class 2606 OID 28478)
-- Name: base_bookmark base_bookmark_pkey; Type: CONSTRAINT; Schema: public; Owner: postgres
--

ALTER TABLE ONLY public.base_bookmark
    ADD CONSTRAINT base_bookmark_pkey PRIMARY KEY (id);


--
-- TOC entry 3985 (class 2606 OID 28480)
-- Name: base_dbbackuplog base_dbbackuplog_pkey; Type: CONSTRAINT; Schema: public; Owner: postgres
--

ALTER TABLE ONLY public.base_dbbackuplog
    ADD CONSTRAINT base_dbbackuplog_pkey PRIMARY KEY (id);


--
-- TOC entry 3987 (class 2606 OID 28482)
-- Name: base_dbmigrate base_dbmigrate_pkey; Type: CONSTRAINT; Schema: public; Owner: postgres
--

ALTER TABLE ONLY public.base_dbmigrate
    ADD CONSTRAINT base_dbmigrate_pkey PRIMARY KEY (id);


--
-- TOC entry 3993 (class 2606 OID 28484)
-- Name: base_departmentalert_department base_departmentalert_dep_departmentalert_id_depar_42613c80_uniq; Type: CONSTRAINT; Schema: public; Owner: postgres
--

ALTER TABLE ONLY public.base_departmentalert_department
    ADD CONSTRAINT base_departmentalert_dep_departmentalert_id_depar_42613c80_uniq UNIQUE (departmentalert_id, department_id);


--
-- TOC entry 3997 (class 2606 OID 28486)
-- Name: base_departmentalert_department base_departmentalert_department_pkey; Type: CONSTRAINT; Schema: public; Owner: postgres
--

ALTER TABLE ONLY public.base_departmentalert_department
    ADD CONSTRAINT base_departmentalert_department_pkey PRIMARY KEY (id);


--
-- TOC entry 3989 (class 2606 OID 28488)
-- Name: base_departmentalert base_departmentalert_emplist_id_key; Type: CONSTRAINT; Schema: public; Owner: postgres
--

ALTER TABLE ONLY public.base_departmentalert
    ADD CONSTRAINT base_departmentalert_emplist_id_key UNIQUE (emplist_id);


--
-- TOC entry 3991 (class 2606 OID 28490)
-- Name: base_departmentalert base_departmentalert_pkey; Type: CONSTRAINT; Schema: public; Owner: postgres
--

ALTER TABLE ONLY public.base_departmentalert
    ADD CONSTRAINT base_departmentalert_pkey PRIMARY KEY (personalalert_ptr_id);


--
-- TOC entry 4412 (class 2606 OID 44180)
-- Name: base_messengersentlog base_messengersentlog_pkey; Type: CONSTRAINT; Schema: public; Owner: postgres
--

ALTER TABLE ONLY public.base_messengersentlog
    ADD CONSTRAINT base_messengersentlog_pkey PRIMARY KEY (id);


--
-- TOC entry 4000 (class 2606 OID 44219)
-- Name: base_personalalert base_personalalert_code_key; Type: CONSTRAINT; Schema: public; Owner: postgres
--

ALTER TABLE ONLY public.base_personalalert
    ADD CONSTRAINT base_personalalert_code_key UNIQUE (code);


--
-- TOC entry 4404 (class 2606 OID 44167)
-- Name: base_personalalert_employee base_personalalert_emplo_personalalert_id_employe_4b3520eb_uniq; Type: CONSTRAINT; Schema: public; Owner: postgres
--

ALTER TABLE ONLY public.base_personalalert_employee
    ADD CONSTRAINT base_personalalert_emplo_personalalert_id_employe_4b3520eb_uniq UNIQUE (personalalert_id, employee_id);


--
-- TOC entry 4408 (class 2606 OID 44155)
-- Name: base_personalalert_employee base_personalalert_employee_pkey; Type: CONSTRAINT; Schema: public; Owner: postgres
--

ALTER TABLE ONLY public.base_personalalert_employee
    ADD CONSTRAINT base_personalalert_employee_pkey PRIMARY KEY (id);


--
-- TOC entry 4002 (class 2606 OID 28498)
-- Name: base_personalalert base_personalalert_pkey; Type: CONSTRAINT; Schema: public; Owner: postgres
--

ALTER TABLE ONLY public.base_personalalert
    ADD CONSTRAINT base_personalalert_pkey PRIMARY KEY (id);


--
-- TOC entry 4004 (class 2606 OID 28500)
-- Name: base_reportoutputsetting base_reportoutputsetting_agreement_message_id_rep_a17e86da_uniq; Type: CONSTRAINT; Schema: public; Owner: postgres
--

ALTER TABLE ONLY public.base_reportoutputsetting
    ADD CONSTRAINT base_reportoutputsetting_agreement_message_id_rep_a17e86da_uniq UNIQUE (agreement_message_id, report_name);


--
-- TOC entry 4006 (class 2606 OID 28502)
-- Name: base_reportoutputsetting base_reportoutputsetting_pkey; Type: CONSTRAINT; Schema: public; Owner: postgres
--

ALTER TABLE ONLY public.base_reportoutputsetting
    ADD CONSTRAINT base_reportoutputsetting_pkey PRIMARY KEY (id);


--
-- TOC entry 4008 (class 2606 OID 28504)
-- Name: base_securitypolicy base_securitypolicy_pkey; Type: CONSTRAINT; Schema: public; Owner: postgres
--

ALTER TABLE ONLY public.base_securitypolicy
    ADD CONSTRAINT base_securitypolicy_pkey PRIMARY KEY (id);


--
-- TOC entry 4010 (class 2606 OID 28506)
-- Name: base_sendemail base_sendemail_pkey; Type: CONSTRAINT; Schema: public; Owner: postgres
--

ALTER TABLE ONLY public.base_sendemail
    ADD CONSTRAINT base_sendemail_pkey PRIMARY KEY (id);


--
-- TOC entry 4012 (class 2606 OID 28508)
-- Name: base_sftpsetting base_sftpsetting_pkey; Type: CONSTRAINT; Schema: public; Owner: postgres
--

ALTER TABLE ONLY public.base_sftpsetting
    ADD CONSTRAINT base_sftpsetting_pkey PRIMARY KEY (id);


--
-- TOC entry 4014 (class 2606 OID 28510)
-- Name: base_sftpsetting base_sftpsetting_user_name_host_f95e6bd9_uniq; Type: CONSTRAINT; Schema: public; Owner: postgres
--

ALTER TABLE ONLY public.base_sftpsetting
    ADD CONSTRAINT base_sftpsetting_user_name_host_f95e6bd9_uniq UNIQUE (user_name, host);


--
-- TOC entry 4016 (class 2606 OID 28512)
-- Name: base_sysparam base_sysparam_para_name_para_type_3086789a_uniq; Type: CONSTRAINT; Schema: public; Owner: postgres
--

ALTER TABLE ONLY public.base_sysparam
    ADD CONSTRAINT base_sysparam_para_name_para_type_3086789a_uniq UNIQUE (para_name, para_type);


--
-- TOC entry 4018 (class 2606 OID 28514)
-- Name: base_sysparam base_sysparam_pkey; Type: CONSTRAINT; Schema: public; Owner: postgres
--

ALTER TABLE ONLY public.base_sysparam
    ADD CONSTRAINT base_sysparam_pkey PRIMARY KEY (id);


--
-- TOC entry 4020 (class 2606 OID 28516)
-- Name: base_sysparamdept base_sysparamdept_pkey; Type: CONSTRAINT; Schema: public; Owner: postgres
--

ALTER TABLE ONLY public.base_sysparamdept
    ADD CONSTRAINT base_sysparamdept_pkey PRIMARY KEY (id);


--
-- TOC entry 4023 (class 2606 OID 28518)
-- Name: base_sysparamdept base_sysparamdept_rule_name_key; Type: CONSTRAINT; Schema: public; Owner: postgres
--

ALTER TABLE ONLY public.base_sysparamdept
    ADD CONSTRAINT base_sysparamdept_rule_name_key UNIQUE (rule_name);


--
-- TOC entry 4025 (class 2606 OID 28520)
-- Name: base_systemsetting base_systemsetting_pkey; Type: CONSTRAINT; Schema: public; Owner: postgres
--

ALTER TABLE ONLY public.base_systemsetting
    ADD CONSTRAINT base_systemsetting_pkey PRIMARY KEY (id);


--
-- TOC entry 4027 (class 2606 OID 28522)
-- Name: base_taskresultlog base_taskresultlog_pkey; Type: CONSTRAINT; Schema: public; Owner: postgres
--

ALTER TABLE ONLY public.base_taskresultlog
    ADD CONSTRAINT base_taskresultlog_pkey PRIMARY KEY (id);


--
-- TOC entry 4030 (class 2606 OID 28524)
-- Name: celery_taskmeta celery_taskmeta_pkey; Type: CONSTRAINT; Schema: public; Owner: postgres
--

ALTER TABLE ONLY public.celery_taskmeta
    ADD CONSTRAINT celery_taskmeta_pkey PRIMARY KEY (id);


--
-- TOC entry 4033 (class 2606 OID 28526)
-- Name: celery_taskmeta celery_taskmeta_task_id_key; Type: CONSTRAINT; Schema: public; Owner: postgres
--

ALTER TABLE ONLY public.celery_taskmeta
    ADD CONSTRAINT celery_taskmeta_task_id_key UNIQUE (task_id);


--
-- TOC entry 4036 (class 2606 OID 28528)
-- Name: celery_tasksetmeta celery_tasksetmeta_pkey; Type: CONSTRAINT; Schema: public; Owner: postgres
--

ALTER TABLE ONLY public.celery_tasksetmeta
    ADD CONSTRAINT celery_tasksetmeta_pkey PRIMARY KEY (id);


--
-- TOC entry 4039 (class 2606 OID 28530)
-- Name: celery_tasksetmeta celery_tasksetmeta_taskset_id_key; Type: CONSTRAINT; Schema: public; Owner: postgres
--

ALTER TABLE ONLY public.celery_tasksetmeta
    ADD CONSTRAINT celery_tasksetmeta_taskset_id_key UNIQUE (taskset_id);


--
-- TOC entry 4042 (class 2606 OID 28532)
-- Name: django_admin_log django_admin_log_pkey; Type: CONSTRAINT; Schema: public; Owner: postgres
--

ALTER TABLE ONLY public.django_admin_log
    ADD CONSTRAINT django_admin_log_pkey PRIMARY KEY (id);


--
-- TOC entry 4045 (class 2606 OID 28534)
-- Name: django_content_type django_content_type_app_label_model_76bd3d3b_uniq; Type: CONSTRAINT; Schema: public; Owner: postgres
--

ALTER TABLE ONLY public.django_content_type
    ADD CONSTRAINT django_content_type_app_label_model_76bd3d3b_uniq UNIQUE (app_label, model);


--
-- TOC entry 4047 (class 2606 OID 28536)
-- Name: django_content_type django_content_type_pkey; Type: CONSTRAINT; Schema: public; Owner: postgres
--

ALTER TABLE ONLY public.django_content_type
    ADD CONSTRAINT django_content_type_pkey PRIMARY KEY (id);


--
-- TOC entry 4049 (class 2606 OID 28538)
-- Name: django_migrations django_migrations_pkey; Type: CONSTRAINT; Schema: public; Owner: postgres
--

ALTER TABLE ONLY public.django_migrations
    ADD CONSTRAINT django_migrations_pkey PRIMARY KEY (id);


--
-- TOC entry 4052 (class 2606 OID 28540)
-- Name: django_session django_session_pkey; Type: CONSTRAINT; Schema: public; Owner: postgres
--

ALTER TABLE ONLY public.django_session
    ADD CONSTRAINT django_session_pkey PRIMARY KEY (session_key);


--
-- TOC entry 4055 (class 2606 OID 28542)
-- Name: djcelery_crontabschedule djcelery_crontabschedule_pkey; Type: CONSTRAINT; Schema: public; Owner: postgres
--

ALTER TABLE ONLY public.djcelery_crontabschedule
    ADD CONSTRAINT djcelery_crontabschedule_pkey PRIMARY KEY (id);


--
-- TOC entry 4057 (class 2606 OID 28544)
-- Name: djcelery_intervalschedule djcelery_intervalschedule_pkey; Type: CONSTRAINT; Schema: public; Owner: postgres
--

ALTER TABLE ONLY public.djcelery_intervalschedule
    ADD CONSTRAINT djcelery_intervalschedule_pkey PRIMARY KEY (id);


--
-- TOC entry 4062 (class 2606 OID 28546)
-- Name: djcelery_periodictask djcelery_periodictask_name_key; Type: CONSTRAINT; Schema: public; Owner: postgres
--

ALTER TABLE ONLY public.djcelery_periodictask
    ADD CONSTRAINT djcelery_periodictask_name_key UNIQUE (name);


--
-- TOC entry 4064 (class 2606 OID 28548)
-- Name: djcelery_periodictask djcelery_periodictask_pkey; Type: CONSTRAINT; Schema: public; Owner: postgres
--

ALTER TABLE ONLY public.djcelery_periodictask
    ADD CONSTRAINT djcelery_periodictask_pkey PRIMARY KEY (id);


--
-- TOC entry 4066 (class 2606 OID 28550)
-- Name: djcelery_periodictasks djcelery_periodictasks_pkey; Type: CONSTRAINT; Schema: public; Owner: postgres
--

ALTER TABLE ONLY public.djcelery_periodictasks
    ADD CONSTRAINT djcelery_periodictasks_pkey PRIMARY KEY (ident);


--
-- TOC entry 4071 (class 2606 OID 28552)
-- Name: djcelery_taskstate djcelery_taskstate_pkey; Type: CONSTRAINT; Schema: public; Owner: postgres
--

ALTER TABLE ONLY public.djcelery_taskstate
    ADD CONSTRAINT djcelery_taskstate_pkey PRIMARY KEY (id);


--
-- TOC entry 4076 (class 2606 OID 28554)
-- Name: djcelery_taskstate djcelery_taskstate_task_id_key; Type: CONSTRAINT; Schema: public; Owner: postgres
--

ALTER TABLE ONLY public.djcelery_taskstate
    ADD CONSTRAINT djcelery_taskstate_task_id_key UNIQUE (task_id);


--
-- TOC entry 4081 (class 2606 OID 28556)
-- Name: djcelery_workerstate djcelery_workerstate_hostname_key; Type: CONSTRAINT; Schema: public; Owner: postgres
--

ALTER TABLE ONLY public.djcelery_workerstate
    ADD CONSTRAINT djcelery_workerstate_hostname_key UNIQUE (hostname);


--
-- TOC entry 4084 (class 2606 OID 28558)
-- Name: djcelery_workerstate djcelery_workerstate_pkey; Type: CONSTRAINT; Schema: public; Owner: postgres
--

ALTER TABLE ONLY public.djcelery_workerstate
    ADD CONSTRAINT djcelery_workerstate_pkey PRIMARY KEY (id);


--
-- TOC entry 4086 (class 2606 OID 28560)
-- Name: ep_epsetup ep_epsetup_pkey; Type: CONSTRAINT; Schema: public; Owner: postgres
--

ALTER TABLE ONLY public.ep_epsetup
    ADD CONSTRAINT ep_epsetup_pkey PRIMARY KEY (id);


--
-- TOC entry 4089 (class 2606 OID 28562)
-- Name: ep_eptransaction ep_eptransaction_emp_id_check_datetime_57cec995_uniq; Type: CONSTRAINT; Schema: public; Owner: postgres
--

ALTER TABLE ONLY public.ep_eptransaction
    ADD CONSTRAINT ep_eptransaction_emp_id_check_datetime_57cec995_uniq UNIQUE (emp_id, check_datetime);


--
-- TOC entry 4091 (class 2606 OID 28564)
-- Name: ep_eptransaction ep_eptransaction_pkey; Type: CONSTRAINT; Schema: public; Owner: postgres
--

ALTER TABLE ONLY public.ep_eptransaction
    ADD CONSTRAINT ep_eptransaction_pkey PRIMARY KEY (id);


--
-- TOC entry 4094 (class 2606 OID 28566)
-- Name: guardian_groupobjectpermission guardian_groupobjectperm_group_id_permission_id_o_3f189f7c_uniq; Type: CONSTRAINT; Schema: public; Owner: postgres
--

ALTER TABLE ONLY public.guardian_groupobjectpermission
    ADD CONSTRAINT guardian_groupobjectperm_group_id_permission_id_o_3f189f7c_uniq UNIQUE (group_id, permission_id, object_pk);


--
-- TOC entry 4099 (class 2606 OID 28568)
-- Name: guardian_groupobjectpermission guardian_groupobjectpermission_pkey; Type: CONSTRAINT; Schema: public; Owner: postgres
--

ALTER TABLE ONLY public.guardian_groupobjectpermission
    ADD CONSTRAINT guardian_groupobjectpermission_pkey PRIMARY KEY (id);


--
-- TOC entry 4101 (class 2606 OID 28570)
-- Name: guardian_userobjectpermission guardian_userobjectpermi_user_id_permission_id_ob_b0b3d2fc_uniq; Type: CONSTRAINT; Schema: public; Owner: postgres
--

ALTER TABLE ONLY public.guardian_userobjectpermission
    ADD CONSTRAINT guardian_userobjectpermi_user_id_permission_id_ob_b0b3d2fc_uniq UNIQUE (user_id, permission_id, object_pk);


--
-- TOC entry 4105 (class 2606 OID 28572)
-- Name: guardian_userobjectpermission guardian_userobjectpermission_pkey; Type: CONSTRAINT; Schema: public; Owner: postgres
--

ALTER TABLE ONLY public.guardian_userobjectpermission
    ADD CONSTRAINT guardian_userobjectpermission_pkey PRIMARY KEY (id);


--
-- TOC entry 4108 (class 2606 OID 28574)
-- Name: iclock_biodata iclock_biodata_employee_id_bio_no_bio_i_b71b2ca9_uniq; Type: CONSTRAINT; Schema: public; Owner: postgres
--

ALTER TABLE ONLY public.iclock_biodata
    ADD CONSTRAINT iclock_biodata_employee_id_bio_no_bio_i_b71b2ca9_uniq UNIQUE (employee_id, bio_no, bio_index, bio_type, bio_format, major_ver);


--
-- TOC entry 4111 (class 2606 OID 28576)
-- Name: iclock_biodata iclock_biodata_pkey; Type: CONSTRAINT; Schema: public; Owner: postgres
--

ALTER TABLE ONLY public.iclock_biodata
    ADD CONSTRAINT iclock_biodata_pkey PRIMARY KEY (id);


--
-- TOC entry 4114 (class 2606 OID 28578)
-- Name: iclock_biophoto iclock_biophoto_pkey; Type: CONSTRAINT; Schema: public; Owner: postgres
--

ALTER TABLE ONLY public.iclock_biophoto
    ADD CONSTRAINT iclock_biophoto_pkey PRIMARY KEY (id);


--
-- TOC entry 4116 (class 2606 OID 28580)
-- Name: iclock_deviceconfig iclock_deviceconfig_pkey; Type: CONSTRAINT; Schema: public; Owner: postgres
--

ALTER TABLE ONLY public.iclock_deviceconfig
    ADD CONSTRAINT iclock_deviceconfig_pkey PRIMARY KEY (uuid);


--
-- TOC entry 4119 (class 2606 OID 28582)
-- Name: iclock_errorcommandlog iclock_errorcommandlog_pkey; Type: CONSTRAINT; Schema: public; Owner: postgres
--

ALTER TABLE ONLY public.iclock_errorcommandlog
    ADD CONSTRAINT iclock_errorcommandlog_pkey PRIMARY KEY (id);


--
-- TOC entry 4123 (class 2606 OID 28584)
-- Name: iclock_privatemessage iclock_privatemessage_pkey; Type: CONSTRAINT; Schema: public; Owner: postgres
--

ALTER TABLE ONLY public.iclock_privatemessage
    ADD CONSTRAINT iclock_privatemessage_pkey PRIMARY KEY (id);


--
-- TOC entry 4125 (class 2606 OID 28586)
-- Name: iclock_publicmessage iclock_publicmessage_pkey; Type: CONSTRAINT; Schema: public; Owner: postgres
--

ALTER TABLE ONLY public.iclock_publicmessage
    ADD CONSTRAINT iclock_publicmessage_pkey PRIMARY KEY (id);


--
-- TOC entry 4130 (class 2606 OID 28588)
-- Name: iclock_terminal iclock_terminal_pkey; Type: CONSTRAINT; Schema: public; Owner: postgres
--

ALTER TABLE ONLY public.iclock_terminal
    ADD CONSTRAINT iclock_terminal_pkey PRIMARY KEY (id);


--
-- TOC entry 4133 (class 2606 OID 28590)
-- Name: iclock_terminal iclock_terminal_sn_key; Type: CONSTRAINT; Schema: public; Owner: postgres
--

ALTER TABLE ONLY public.iclock_terminal
    ADD CONSTRAINT iclock_terminal_sn_key UNIQUE (sn);


--
-- TOC entry 4135 (class 2606 OID 28592)
-- Name: iclock_terminalcommand iclock_terminalcommand_pkey; Type: CONSTRAINT; Schema: public; Owner: postgres
--

ALTER TABLE ONLY public.iclock_terminalcommand
    ADD CONSTRAINT iclock_terminalcommand_pkey PRIMARY KEY (id);


--
-- TOC entry 4138 (class 2606 OID 28594)
-- Name: iclock_terminalcommandlog iclock_terminalcommandlog_pkey; Type: CONSTRAINT; Schema: public; Owner: postgres
--

ALTER TABLE ONLY public.iclock_terminalcommandlog
    ADD CONSTRAINT iclock_terminalcommandlog_pkey PRIMARY KEY (id);


--
-- TOC entry 4141 (class 2606 OID 28596)
-- Name: iclock_terminalemployee iclock_terminalemployee_pkey; Type: CONSTRAINT; Schema: public; Owner: postgres
--

ALTER TABLE ONLY public.iclock_terminalemployee
    ADD CONSTRAINT iclock_terminalemployee_pkey PRIMARY KEY (id);


--
-- TOC entry 4143 (class 2606 OID 28598)
-- Name: iclock_terminallog iclock_terminallog_pkey; Type: CONSTRAINT; Schema: public; Owner: postgres
--

ALTER TABLE ONLY public.iclock_terminallog
    ADD CONSTRAINT iclock_terminallog_pkey PRIMARY KEY (id);


--
-- TOC entry 4146 (class 2606 OID 28600)
-- Name: iclock_terminalparameter iclock_terminalparameter_pkey; Type: CONSTRAINT; Schema: public; Owner: postgres
--

ALTER TABLE ONLY public.iclock_terminalparameter
    ADD CONSTRAINT iclock_terminalparameter_pkey PRIMARY KEY (id);


--
-- TOC entry 4149 (class 2606 OID 28602)
-- Name: iclock_terminalparameter iclock_terminalparameter_terminal_id_param_name_8abbb5c0_uniq; Type: CONSTRAINT; Schema: public; Owner: postgres
--

ALTER TABLE ONLY public.iclock_terminalparameter
    ADD CONSTRAINT iclock_terminalparameter_terminal_id_param_name_8abbb5c0_uniq UNIQUE (terminal_id, param_name);


--
-- TOC entry 4151 (class 2606 OID 28604)
-- Name: iclock_terminaluploadlog iclock_terminaluploadlog_pkey; Type: CONSTRAINT; Schema: public; Owner: postgres
--

ALTER TABLE ONLY public.iclock_terminaluploadlog
    ADD CONSTRAINT iclock_terminaluploadlog_pkey PRIMARY KEY (id);


--
-- TOC entry 4155 (class 2606 OID 28606)
-- Name: iclock_terminalworkcode iclock_terminalworkcode_code_key; Type: CONSTRAINT; Schema: public; Owner: postgres
--

ALTER TABLE ONLY public.iclock_terminalworkcode
    ADD CONSTRAINT iclock_terminalworkcode_code_key UNIQUE (code);


--
-- TOC entry 4157 (class 2606 OID 28608)
-- Name: iclock_terminalworkcode iclock_terminalworkcode_pkey; Type: CONSTRAINT; Schema: public; Owner: postgres
--

ALTER TABLE ONLY public.iclock_terminalworkcode
    ADD CONSTRAINT iclock_terminalworkcode_pkey PRIMARY KEY (id);


--
-- TOC entry 4159 (class 2606 OID 28610)
-- Name: iclock_transaction iclock_transaction_emp_code_punch_time_ca282852_uniq; Type: CONSTRAINT; Schema: public; Owner: postgres
--

ALTER TABLE ONLY public.iclock_transaction
    ADD CONSTRAINT iclock_transaction_emp_code_punch_time_ca282852_uniq UNIQUE (emp_code, punch_time);


--
-- TOC entry 4162 (class 2606 OID 28612)
-- Name: iclock_transaction iclock_transaction_pkey; Type: CONSTRAINT; Schema: public; Owner: postgres
--

ALTER TABLE ONLY public.iclock_transaction
    ADD CONSTRAINT iclock_transaction_pkey PRIMARY KEY (id);


--
-- TOC entry 4165 (class 2606 OID 28614)
-- Name: iclock_transactionproofcmd iclock_transactionproofcmd_pkey; Type: CONSTRAINT; Schema: public; Owner: postgres
--

ALTER TABLE ONLY public.iclock_transactionproofcmd
    ADD CONSTRAINT iclock_transactionproofcmd_pkey PRIMARY KEY (id);


--
-- TOC entry 4168 (class 2606 OID 28616)
-- Name: mobile_announcement mobile_announcement_pkey; Type: CONSTRAINT; Schema: public; Owner: postgres
--

ALTER TABLE ONLY public.mobile_announcement
    ADD CONSTRAINT mobile_announcement_pkey PRIMARY KEY (id);


--
-- TOC entry 4171 (class 2606 OID 28618)
-- Name: mobile_appactionlog mobile_appactionlog_pkey; Type: CONSTRAINT; Schema: public; Owner: postgres
--

ALTER TABLE ONLY public.mobile_appactionlog
    ADD CONSTRAINT mobile_appactionlog_pkey PRIMARY KEY (id);


--
-- TOC entry 4173 (class 2606 OID 28620)
-- Name: mobile_applist mobile_applist_pkey; Type: CONSTRAINT; Schema: public; Owner: postgres
--

ALTER TABLE ONLY public.mobile_applist
    ADD CONSTRAINT mobile_applist_pkey PRIMARY KEY (id);


--
-- TOC entry 4175 (class 2606 OID 28622)
-- Name: mobile_appnotification mobile_appnotification_pkey; Type: CONSTRAINT; Schema: public; Owner: postgres
--

ALTER TABLE ONLY public.mobile_appnotification
    ADD CONSTRAINT mobile_appnotification_pkey PRIMARY KEY (id);


--
-- TOC entry 4179 (class 2606 OID 28624)
-- Name: mobile_gpsfordepartment mobile_gpsfordepartment_pkey; Type: CONSTRAINT; Schema: public; Owner: postgres
--

ALTER TABLE ONLY public.mobile_gpsfordepartment
    ADD CONSTRAINT mobile_gpsfordepartment_pkey PRIMARY KEY (id);


--
-- TOC entry 4182 (class 2606 OID 28626)
-- Name: mobile_gpsforemployee mobile_gpsforemployee_pkey; Type: CONSTRAINT; Schema: public; Owner: postgres
--

ALTER TABLE ONLY public.mobile_gpsforemployee
    ADD CONSTRAINT mobile_gpsforemployee_pkey PRIMARY KEY (id);


--
-- TOC entry 4184 (class 2606 OID 28628)
-- Name: notifications_notification notifications_notification_pkey; Type: CONSTRAINT; Schema: public; Owner: postgres
--

ALTER TABLE ONLY public.notifications_notification
    ADD CONSTRAINT notifications_notification_pkey PRIMARY KEY (id);


--
-- TOC entry 4186 (class 2606 OID 28630)
-- Name: payroll_deductionformula payroll_deductionformula_pkey; Type: CONSTRAINT; Schema: public; Owner: postgres
--

ALTER TABLE ONLY public.payroll_deductionformula
    ADD CONSTRAINT payroll_deductionformula_pkey PRIMARY KEY (id);


--
-- TOC entry 4189 (class 2606 OID 28632)
-- Name: payroll_emploan payroll_emploan_pkey; Type: CONSTRAINT; Schema: public; Owner: postgres
--

ALTER TABLE ONLY public.payroll_emploan
    ADD CONSTRAINT payroll_emploan_pkey PRIMARY KEY (id);


--
-- TOC entry 4191 (class 2606 OID 28634)
-- Name: payroll_emppayrollprofile payroll_emppayrollprofile_employee_id_key; Type: CONSTRAINT; Schema: public; Owner: postgres
--

ALTER TABLE ONLY public.payroll_emppayrollprofile
    ADD CONSTRAINT payroll_emppayrollprofile_employee_id_key UNIQUE (employee_id);


--
-- TOC entry 4193 (class 2606 OID 28636)
-- Name: payroll_emppayrollprofile payroll_emppayrollprofile_pkey; Type: CONSTRAINT; Schema: public; Owner: postgres
--

ALTER TABLE ONLY public.payroll_emppayrollprofile
    ADD CONSTRAINT payroll_emppayrollprofile_pkey PRIMARY KEY (id);


--
-- TOC entry 4195 (class 2606 OID 28638)
-- Name: payroll_exceptionformula payroll_exceptionformula_pkey; Type: CONSTRAINT; Schema: public; Owner: postgres
--

ALTER TABLE ONLY public.payroll_exceptionformula
    ADD CONSTRAINT payroll_exceptionformula_pkey PRIMARY KEY (id);


--
-- TOC entry 4198 (class 2606 OID 28640)
-- Name: payroll_extradeduction payroll_extradeduction_pkey; Type: CONSTRAINT; Schema: public; Owner: postgres
--

ALTER TABLE ONLY public.payroll_extradeduction
    ADD CONSTRAINT payroll_extradeduction_pkey PRIMARY KEY (id);


--
-- TOC entry 4201 (class 2606 OID 28642)
-- Name: payroll_extraincrease payroll_extraincrease_pkey; Type: CONSTRAINT; Schema: public; Owner: postgres
--

ALTER TABLE ONLY public.payroll_extraincrease
    ADD CONSTRAINT payroll_extraincrease_pkey PRIMARY KEY (id);


--
-- TOC entry 4203 (class 2606 OID 28644)
-- Name: payroll_increasementformula payroll_increasementformula_pkey; Type: CONSTRAINT; Schema: public; Owner: postgres
--

ALTER TABLE ONLY public.payroll_increasementformula
    ADD CONSTRAINT payroll_increasementformula_pkey PRIMARY KEY (id);


--
-- TOC entry 4206 (class 2606 OID 28646)
-- Name: payroll_leaveformula payroll_leaveformula_pkey; Type: CONSTRAINT; Schema: public; Owner: postgres
--

ALTER TABLE ONLY public.payroll_leaveformula
    ADD CONSTRAINT payroll_leaveformula_pkey PRIMARY KEY (id);


--
-- TOC entry 4209 (class 2606 OID 28648)
-- Name: payroll_monthlysalary payroll_monthlysalary_pkey; Type: CONSTRAINT; Schema: public; Owner: postgres
--

ALTER TABLE ONLY public.payroll_monthlysalary
    ADD CONSTRAINT payroll_monthlysalary_pkey PRIMARY KEY (id);


--
-- TOC entry 4211 (class 2606 OID 28650)
-- Name: payroll_overtimeformula payroll_overtimeformula_pkey; Type: CONSTRAINT; Schema: public; Owner: postgres
--

ALTER TABLE ONLY public.payroll_overtimeformula
    ADD CONSTRAINT payroll_overtimeformula_pkey PRIMARY KEY (id);


--
-- TOC entry 4214 (class 2606 OID 28652)
-- Name: payroll_reimbursement payroll_reimbursement_pkey; Type: CONSTRAINT; Schema: public; Owner: postgres
--

ALTER TABLE ONLY public.payroll_reimbursement
    ADD CONSTRAINT payroll_reimbursement_pkey PRIMARY KEY (id);


--
-- TOC entry 4217 (class 2606 OID 28654)
-- Name: payroll_salaryadvance payroll_salaryadvance_pkey; Type: CONSTRAINT; Schema: public; Owner: postgres
--

ALTER TABLE ONLY public.payroll_salaryadvance
    ADD CONSTRAINT payroll_salaryadvance_pkey PRIMARY KEY (id);


--
-- TOC entry 4222 (class 2606 OID 28656)
-- Name: payroll_salarystructure_deductionformula payroll_salarystructure__salarystructure_id_deduc_794e8449_uniq; Type: CONSTRAINT; Schema: public; Owner: postgres
--

ALTER TABLE ONLY public.payroll_salarystructure_deductionformula
    ADD CONSTRAINT payroll_salarystructure__salarystructure_id_deduc_794e8449_uniq UNIQUE (salarystructure_id, deductionformula_id);


--
-- TOC entry 4228 (class 2606 OID 28658)
-- Name: payroll_salarystructure_exceptionformula payroll_salarystructure__salarystructure_id_excep_a5e869ff_uniq; Type: CONSTRAINT; Schema: public; Owner: postgres
--

ALTER TABLE ONLY public.payroll_salarystructure_exceptionformula
    ADD CONSTRAINT payroll_salarystructure__salarystructure_id_excep_a5e869ff_uniq UNIQUE (salarystructure_id, exceptionformula_id);


--
-- TOC entry 4234 (class 2606 OID 28660)
-- Name: payroll_salarystructure_increasementformula payroll_salarystructure__salarystructure_id_incre_749132b3_uniq; Type: CONSTRAINT; Schema: public; Owner: postgres
--

ALTER TABLE ONLY public.payroll_salarystructure_increasementformula
    ADD CONSTRAINT payroll_salarystructure__salarystructure_id_incre_749132b3_uniq UNIQUE (salarystructure_id, increasementformula_id);


--
-- TOC entry 4240 (class 2606 OID 28662)
-- Name: payroll_salarystructure_leaveformula payroll_salarystructure__salarystructure_id_leave_4efdce30_uniq; Type: CONSTRAINT; Schema: public; Owner: postgres
--

ALTER TABLE ONLY public.payroll_salarystructure_leaveformula
    ADD CONSTRAINT payroll_salarystructure__salarystructure_id_leave_4efdce30_uniq UNIQUE (salarystructure_id, leaveformula_id);


--
-- TOC entry 4246 (class 2606 OID 28664)
-- Name: payroll_salarystructure_overtimeformula payroll_salarystructure__salarystructure_id_overt_0d0a0e81_uniq; Type: CONSTRAINT; Schema: public; Owner: postgres
--

ALTER TABLE ONLY public.payroll_salarystructure_overtimeformula
    ADD CONSTRAINT payroll_salarystructure__salarystructure_id_overt_0d0a0e81_uniq UNIQUE (salarystructure_id, overtimeformula_id);


--
-- TOC entry 4226 (class 2606 OID 28666)
-- Name: payroll_salarystructure_deductionformula payroll_salarystructure_deductionformula_pkey; Type: CONSTRAINT; Schema: public; Owner: postgres
--

ALTER TABLE ONLY public.payroll_salarystructure_deductionformula
    ADD CONSTRAINT payroll_salarystructure_deductionformula_pkey PRIMARY KEY (id);


--
-- TOC entry 4232 (class 2606 OID 28668)
-- Name: payroll_salarystructure_exceptionformula payroll_salarystructure_exceptionformula_pkey; Type: CONSTRAINT; Schema: public; Owner: postgres
--

ALTER TABLE ONLY public.payroll_salarystructure_exceptionformula
    ADD CONSTRAINT payroll_salarystructure_exceptionformula_pkey PRIMARY KEY (id);


--
-- TOC entry 4238 (class 2606 OID 28670)
-- Name: payroll_salarystructure_increasementformula payroll_salarystructure_increasementformula_pkey; Type: CONSTRAINT; Schema: public; Owner: postgres
--

ALTER TABLE ONLY public.payroll_salarystructure_increasementformula
    ADD CONSTRAINT payroll_salarystructure_increasementformula_pkey PRIMARY KEY (id);


--
-- TOC entry 4244 (class 2606 OID 28672)
-- Name: payroll_salarystructure_leaveformula payroll_salarystructure_leaveformula_pkey; Type: CONSTRAINT; Schema: public; Owner: postgres
--

ALTER TABLE ONLY public.payroll_salarystructure_leaveformula
    ADD CONSTRAINT payroll_salarystructure_leaveformula_pkey PRIMARY KEY (id);


--
-- TOC entry 4250 (class 2606 OID 28674)
-- Name: payroll_salarystructure_overtimeformula payroll_salarystructure_overtimeformula_pkey; Type: CONSTRAINT; Schema: public; Owner: postgres
--

ALTER TABLE ONLY public.payroll_salarystructure_overtimeformula
    ADD CONSTRAINT payroll_salarystructure_overtimeformula_pkey PRIMARY KEY (id);


--
-- TOC entry 4220 (class 2606 OID 28676)
-- Name: payroll_salarystructure payroll_salarystructure_pkey; Type: CONSTRAINT; Schema: public; Owner: postgres
--

ALTER TABLE ONLY public.payroll_salarystructure
    ADD CONSTRAINT payroll_salarystructure_pkey PRIMARY KEY (id);


--
-- TOC entry 4253 (class 2606 OID 28678)
-- Name: personnel_area personnel_area_area_code_key; Type: CONSTRAINT; Schema: public; Owner: postgres
--

ALTER TABLE ONLY public.personnel_area
    ADD CONSTRAINT personnel_area_area_code_key UNIQUE (area_code);


--
-- TOC entry 4257 (class 2606 OID 28680)
-- Name: personnel_area personnel_area_pkey; Type: CONSTRAINT; Schema: public; Owner: postgres
--

ALTER TABLE ONLY public.personnel_area
    ADD CONSTRAINT personnel_area_pkey PRIMARY KEY (id);


--
-- TOC entry 4261 (class 2606 OID 28682)
-- Name: personnel_assignareaemployee personnel_assignareaemployee_pkey; Type: CONSTRAINT; Schema: public; Owner: postgres
--

ALTER TABLE ONLY public.personnel_assignareaemployee
    ADD CONSTRAINT personnel_assignareaemployee_pkey PRIMARY KEY (id);


--
-- TOC entry 4263 (class 2606 OID 28684)
-- Name: personnel_certification personnel_certification_cert_code_cert_name_comp_10ee81ab_uniq; Type: CONSTRAINT; Schema: public; Owner: postgres
--

ALTER TABLE ONLY public.personnel_certification
    ADD CONSTRAINT personnel_certification_cert_code_cert_name_comp_10ee81ab_uniq UNIQUE (cert_code, cert_name, company_id);


--
-- TOC entry 4266 (class 2606 OID 28686)
-- Name: personnel_certification personnel_certification_pkey; Type: CONSTRAINT; Schema: public; Owner: postgres
--

ALTER TABLE ONLY public.personnel_certification
    ADD CONSTRAINT personnel_certification_pkey PRIMARY KEY (id);


--
-- TOC entry 4269 (class 2606 OID 28688)
-- Name: personnel_company personnel_company_company_code_key; Type: CONSTRAINT; Schema: public; Owner: postgres
--

ALTER TABLE ONLY public.personnel_company
    ADD CONSTRAINT personnel_company_company_code_key UNIQUE (company_code);


--
-- TOC entry 4271 (class 2606 OID 28690)
-- Name: personnel_company personnel_company_pkey; Type: CONSTRAINT; Schema: public; Owner: postgres
--

ALTER TABLE ONLY public.personnel_company
    ADD CONSTRAINT personnel_company_pkey PRIMARY KEY (id);


--
-- TOC entry 4274 (class 2606 OID 28692)
-- Name: personnel_companyregister personnel_companyregister_company_code_key; Type: CONSTRAINT; Schema: public; Owner: postgres
--

ALTER TABLE ONLY public.personnel_companyregister
    ADD CONSTRAINT personnel_companyregister_company_code_key UNIQUE (company_code);


--
-- TOC entry 4276 (class 2606 OID 28694)
-- Name: personnel_companyregister personnel_companyregister_pkey; Type: CONSTRAINT; Schema: public; Owner: postgres
--

ALTER TABLE ONLY public.personnel_companyregister
    ADD CONSTRAINT personnel_companyregister_pkey PRIMARY KEY (id);


--
-- TOC entry 4280 (class 2606 OID 28696)
-- Name: personnel_department personnel_department_dept_code_key; Type: CONSTRAINT; Schema: public; Owner: postgres
--

ALTER TABLE ONLY public.personnel_department
    ADD CONSTRAINT personnel_department_dept_code_key UNIQUE (dept_code);


--
-- TOC entry 4283 (class 2606 OID 28698)
-- Name: personnel_department personnel_department_pkey; Type: CONSTRAINT; Schema: public; Owner: postgres
--

ALTER TABLE ONLY public.personnel_department
    ADD CONSTRAINT personnel_department_pkey PRIMARY KEY (id);


--
-- TOC entry 4298 (class 2606 OID 28700)
-- Name: personnel_employee_area_privilege personnel_employee_area__employee_id_area_id_99f40c1a_uniq; Type: CONSTRAINT; Schema: public; Owner: postgres
--

ALTER TABLE ONLY public.personnel_employee_area_privilege
    ADD CONSTRAINT personnel_employee_area__employee_id_area_id_99f40c1a_uniq UNIQUE (employee_id, area_id);


--
-- TOC entry 4294 (class 2606 OID 28702)
-- Name: personnel_employee_area personnel_employee_area_employee_id_area_id_00b3d777_uniq; Type: CONSTRAINT; Schema: public; Owner: postgres
--

ALTER TABLE ONLY public.personnel_employee_area
    ADD CONSTRAINT personnel_employee_area_employee_id_area_id_00b3d777_uniq UNIQUE (employee_id, area_id);


--
-- TOC entry 4296 (class 2606 OID 28704)
-- Name: personnel_employee_area personnel_employee_area_pkey; Type: CONSTRAINT; Schema: public; Owner: postgres
--

ALTER TABLE ONLY public.personnel_employee_area
    ADD CONSTRAINT personnel_employee_area_pkey PRIMARY KEY (id);


--
-- TOC entry 4302 (class 2606 OID 28706)
-- Name: personnel_employee_area_privilege personnel_employee_area_privilege_pkey; Type: CONSTRAINT; Schema: public; Owner: postgres
--

ALTER TABLE ONLY public.personnel_employee_area_privilege
    ADD CONSTRAINT personnel_employee_area_privilege_pkey PRIMARY KEY (id);


--
-- TOC entry 4287 (class 2606 OID 28708)
-- Name: personnel_employee personnel_employee_emp_code_key; Type: CONSTRAINT; Schema: public; Owner: postgres
--

ALTER TABLE ONLY public.personnel_employee
    ADD CONSTRAINT personnel_employee_emp_code_key UNIQUE (emp_code);


--
-- TOC entry 4304 (class 2606 OID 28710)
-- Name: personnel_employee_flow_role personnel_employee_flow__employee_id_workflowrole_46b0e5e0_uniq; Type: CONSTRAINT; Schema: public; Owner: postgres
--

ALTER TABLE ONLY public.personnel_employee_flow_role
    ADD CONSTRAINT personnel_employee_flow__employee_id_workflowrole_46b0e5e0_uniq UNIQUE (employee_id, workflowrole_id);


--
-- TOC entry 4307 (class 2606 OID 28712)
-- Name: personnel_employee_flow_role personnel_employee_flow_role_pkey; Type: CONSTRAINT; Schema: public; Owner: postgres
--

ALTER TABLE ONLY public.personnel_employee_flow_role
    ADD CONSTRAINT personnel_employee_flow_role_pkey PRIMARY KEY (id);


--
-- TOC entry 4289 (class 2606 OID 28714)
-- Name: personnel_employee personnel_employee_pkey; Type: CONSTRAINT; Schema: public; Owner: postgres
--

ALTER TABLE ONLY public.personnel_employee
    ADD CONSTRAINT personnel_employee_pkey PRIMARY KEY (id);


--
-- TOC entry 4310 (class 2606 OID 28716)
-- Name: personnel_employeecertification personnel_employeecertif_employee_id_certificatio_7bcf4c7d_uniq; Type: CONSTRAINT; Schema: public; Owner: postgres
--

ALTER TABLE ONLY public.personnel_employeecertification
    ADD CONSTRAINT personnel_employeecertif_employee_id_certificatio_7bcf4c7d_uniq UNIQUE (employee_id, certification_id);


--
-- TOC entry 4314 (class 2606 OID 28718)
-- Name: personnel_employeecertification personnel_employeecertification_pkey; Type: CONSTRAINT; Schema: public; Owner: postgres
--

ALTER TABLE ONLY public.personnel_employeecertification
    ADD CONSTRAINT personnel_employeecertification_pkey PRIMARY KEY (id);


--
-- TOC entry 4316 (class 2606 OID 28720)
-- Name: personnel_employeeprofile personnel_employeeprofile_emp_id_key; Type: CONSTRAINT; Schema: public; Owner: postgres
--

ALTER TABLE ONLY public.personnel_employeeprofile
    ADD CONSTRAINT personnel_employeeprofile_emp_id_key UNIQUE (emp_id);


--
-- TOC entry 4318 (class 2606 OID 28722)
-- Name: personnel_employeeprofile personnel_employeeprofile_pkey; Type: CONSTRAINT; Schema: public; Owner: postgres
--

ALTER TABLE ONLY public.personnel_employeeprofile
    ADD CONSTRAINT personnel_employeeprofile_pkey PRIMARY KEY (id);


--
-- TOC entry 4322 (class 2606 OID 28724)
-- Name: personnel_position personnel_position_pkey; Type: CONSTRAINT; Schema: public; Owner: postgres
--

ALTER TABLE ONLY public.personnel_position
    ADD CONSTRAINT personnel_position_pkey PRIMARY KEY (id);


--
-- TOC entry 4325 (class 2606 OID 28726)
-- Name: personnel_position personnel_position_position_code_key; Type: CONSTRAINT; Schema: public; Owner: postgres
--

ALTER TABLE ONLY public.personnel_position
    ADD CONSTRAINT personnel_position_position_code_key UNIQUE (position_code);


--
-- TOC entry 4328 (class 2606 OID 28728)
-- Name: personnel_resign personnel_resign_employee_id_key; Type: CONSTRAINT; Schema: public; Owner: postgres
--

ALTER TABLE ONLY public.personnel_resign
    ADD CONSTRAINT personnel_resign_employee_id_key UNIQUE (employee_id);


--
-- TOC entry 4330 (class 2606 OID 28730)
-- Name: personnel_resign personnel_resign_pkey; Type: CONSTRAINT; Schema: public; Owner: postgres
--

ALTER TABLE ONLY public.personnel_resign
    ADD CONSTRAINT personnel_resign_pkey PRIMARY KEY (id);


--
-- TOC entry 4333 (class 2606 OID 28732)
-- Name: staff_stafftoken staff_stafftoken_pkey; Type: CONSTRAINT; Schema: public; Owner: postgres
--

ALTER TABLE ONLY public.staff_stafftoken
    ADD CONSTRAINT staff_stafftoken_pkey PRIMARY KEY (key);


--
-- TOC entry 4335 (class 2606 OID 28734)
-- Name: staff_stafftoken staff_stafftoken_user_id_key; Type: CONSTRAINT; Schema: public; Owner: postgres
--

ALTER TABLE ONLY public.staff_stafftoken
    ADD CONSTRAINT staff_stafftoken_user_id_key UNIQUE (user_id);


--
-- TOC entry 4337 (class 2606 OID 44212)
-- Name: sync_area sync_area_area_code_area_name_200046d1_uniq; Type: CONSTRAINT; Schema: public; Owner: postgres
--

ALTER TABLE ONLY public.sync_area
    ADD CONSTRAINT sync_area_area_code_area_name_200046d1_uniq UNIQUE (area_code, area_name);


--
-- TOC entry 4339 (class 2606 OID 28738)
-- Name: sync_area sync_area_pkey; Type: CONSTRAINT; Schema: public; Owner: postgres
--

ALTER TABLE ONLY public.sync_area
    ADD CONSTRAINT sync_area_pkey PRIMARY KEY (id);


--
-- TOC entry 4341 (class 2606 OID 28740)
-- Name: sync_department sync_department_dept_code_dept_name_93923213_uniq; Type: CONSTRAINT; Schema: public; Owner: postgres
--

ALTER TABLE ONLY public.sync_department
    ADD CONSTRAINT sync_department_dept_code_dept_name_93923213_uniq UNIQUE (dept_code, dept_name);


--
-- TOC entry 4343 (class 2606 OID 28742)
-- Name: sync_department sync_department_pkey; Type: CONSTRAINT; Schema: public; Owner: postgres
--

ALTER TABLE ONLY public.sync_department
    ADD CONSTRAINT sync_department_pkey PRIMARY KEY (id);


--
-- TOC entry 4345 (class 2606 OID 28744)
-- Name: sync_employee sync_employee_emp_code_521bf06d_uniq; Type: CONSTRAINT; Schema: public; Owner: postgres
--

ALTER TABLE ONLY public.sync_employee
    ADD CONSTRAINT sync_employee_emp_code_521bf06d_uniq UNIQUE (emp_code);


--
-- TOC entry 4347 (class 2606 OID 28746)
-- Name: sync_employee sync_employee_pkey; Type: CONSTRAINT; Schema: public; Owner: postgres
--

ALTER TABLE ONLY public.sync_employee
    ADD CONSTRAINT sync_employee_pkey PRIMARY KEY (id);


--
-- TOC entry 4349 (class 2606 OID 28748)
-- Name: sync_job sync_job_job_code_job_name_4ec5619e_uniq; Type: CONSTRAINT; Schema: public; Owner: postgres
--

ALTER TABLE ONLY public.sync_job
    ADD CONSTRAINT sync_job_job_code_job_name_4ec5619e_uniq UNIQUE (job_code, job_name);


--
-- TOC entry 4351 (class 2606 OID 28750)
-- Name: sync_job sync_job_pkey; Type: CONSTRAINT; Schema: public; Owner: postgres
--

ALTER TABLE ONLY public.sync_job
    ADD CONSTRAINT sync_job_pkey PRIMARY KEY (id);


--
-- TOC entry 4353 (class 2606 OID 28752)
-- Name: workflow_abstractexception workflow_abstractexception_pkey; Type: CONSTRAINT; Schema: public; Owner: postgres
--

ALTER TABLE ONLY public.workflow_abstractexception
    ADD CONSTRAINT workflow_abstractexception_pkey PRIMARY KEY (id);


--
-- TOC entry 4359 (class 2606 OID 28754)
-- Name: workflow_nodeinstance workflow_nodeinstance_pkey; Type: CONSTRAINT; Schema: public; Owner: postgres
--

ALTER TABLE ONLY public.workflow_nodeinstance
    ADD CONSTRAINT workflow_nodeinstance_pkey PRIMARY KEY (id);


--
-- TOC entry 4370 (class 2606 OID 28756)
-- Name: workflow_workflowengine_employee workflow_workflowengine__workflowengine_id_employ_8128deb2_uniq; Type: CONSTRAINT; Schema: public; Owner: postgres
--

ALTER TABLE ONLY public.workflow_workflowengine_employee
    ADD CONSTRAINT workflow_workflowengine__workflowengine_id_employ_8128deb2_uniq UNIQUE (workflowengine_id, employee_id);


--
-- TOC entry 4373 (class 2606 OID 28758)
-- Name: workflow_workflowengine_employee workflow_workflowengine_employee_pkey; Type: CONSTRAINT; Schema: public; Owner: postgres
--

ALTER TABLE ONLY public.workflow_workflowengine_employee
    ADD CONSTRAINT workflow_workflowengine_employee_pkey PRIMARY KEY (id);


--
-- TOC entry 4366 (class 2606 OID 28760)
-- Name: workflow_workflowengine workflow_workflowengine_pkey; Type: CONSTRAINT; Schema: public; Owner: postgres
--

ALTER TABLE ONLY public.workflow_workflowengine
    ADD CONSTRAINT workflow_workflowengine_pkey PRIMARY KEY (id);


--
-- TOC entry 4368 (class 2606 OID 28762)
-- Name: workflow_workflowengine workflow_workflowengine_workflow_code_company_id_8f99f5dd_uniq; Type: CONSTRAINT; Schema: public; Owner: postgres
--

ALTER TABLE ONLY public.workflow_workflowengine
    ADD CONSTRAINT workflow_workflowengine_workflow_code_company_id_8f99f5dd_uniq UNIQUE (workflow_code, company_id);


--
-- TOC entry 4377 (class 2606 OID 28764)
-- Name: workflow_workflowinstance workflow_workflowinstance_exception_id_key; Type: CONSTRAINT; Schema: public; Owner: postgres
--

ALTER TABLE ONLY public.workflow_workflowinstance
    ADD CONSTRAINT workflow_workflowinstance_exception_id_key UNIQUE (exception_id);


--
-- TOC entry 4379 (class 2606 OID 28766)
-- Name: workflow_workflowinstance workflow_workflowinstance_pkey; Type: CONSTRAINT; Schema: public; Owner: postgres
--

ALTER TABLE ONLY public.workflow_workflowinstance
    ADD CONSTRAINT workflow_workflowinstance_pkey PRIMARY KEY (id);


--
-- TOC entry 4385 (class 2606 OID 28768)
-- Name: workflow_workflownode_approver workflow_workflownode_ap_workflownode_id_workflow_7543ba37_uniq; Type: CONSTRAINT; Schema: public; Owner: postgres
--

ALTER TABLE ONLY public.workflow_workflownode_approver
    ADD CONSTRAINT workflow_workflownode_ap_workflownode_id_workflow_7543ba37_uniq UNIQUE (workflownode_id, workflowrole_id);


--
-- TOC entry 4387 (class 2606 OID 28770)
-- Name: workflow_workflownode_approver workflow_workflownode_approver_pkey; Type: CONSTRAINT; Schema: public; Owner: postgres
--

ALTER TABLE ONLY public.workflow_workflownode_approver
    ADD CONSTRAINT workflow_workflownode_approver_pkey PRIMARY KEY (id);


--
-- TOC entry 4391 (class 2606 OID 28772)
-- Name: workflow_workflownode_notifier workflow_workflownode_no_workflownode_id_workflow_cac02b37_uniq; Type: CONSTRAINT; Schema: public; Owner: postgres
--

ALTER TABLE ONLY public.workflow_workflownode_notifier
    ADD CONSTRAINT workflow_workflownode_no_workflownode_id_workflow_cac02b37_uniq UNIQUE (workflownode_id, workflowrole_id);


--
-- TOC entry 4393 (class 2606 OID 28774)
-- Name: workflow_workflownode_notifier workflow_workflownode_notifier_pkey; Type: CONSTRAINT; Schema: public; Owner: postgres
--

ALTER TABLE ONLY public.workflow_workflownode_notifier
    ADD CONSTRAINT workflow_workflownode_notifier_pkey PRIMARY KEY (id);


--
-- TOC entry 4383 (class 2606 OID 28776)
-- Name: workflow_workflownode workflow_workflownode_pkey; Type: CONSTRAINT; Schema: public; Owner: postgres
--

ALTER TABLE ONLY public.workflow_workflownode
    ADD CONSTRAINT workflow_workflownode_pkey PRIMARY KEY (id);


--
-- TOC entry 4398 (class 2606 OID 28778)
-- Name: workflow_workflowrole workflow_workflowrole_pkey; Type: CONSTRAINT; Schema: public; Owner: postgres
--

ALTER TABLE ONLY public.workflow_workflowrole
    ADD CONSTRAINT workflow_workflowrole_pkey PRIMARY KEY (id);


--
-- TOC entry 4400 (class 2606 OID 28780)
-- Name: workflow_workflowrole workflow_workflowrole_role_code_company_id_b3f06ba6_uniq; Type: CONSTRAINT; Schema: public; Owner: postgres
--

ALTER TABLE ONLY public.workflow_workflowrole
    ADD CONSTRAINT workflow_workflowrole_role_code_company_id_b3f06ba6_uniq UNIQUE (role_code, company_id);


--
-- TOC entry 4402 (class 2606 OID 28782)
-- Name: workflow_workflowrole workflow_workflowrole_role_name_company_id_0270d4c3_uniq; Type: CONSTRAINT; Schema: public; Owner: postgres
--

ALTER TABLE ONLY public.workflow_workflowrole
    ADD CONSTRAINT workflow_workflowrole_role_name_company_id_0270d4c3_uniq UNIQUE (role_name, company_id);


--
-- TOC entry 3749 (class 1259 OID 28783)
-- Name: acc_acccombination_area_id_0d22c34e; Type: INDEX; Schema: public; Owner: postgres
--

CREATE INDEX acc_acccombination_area_id_0d22c34e ON public.acc_acccombination USING btree (area_id);


--
-- TOC entry 3754 (class 1259 OID 28784)
-- Name: acc_accgroups_area_id_b83745c3; Type: INDEX; Schema: public; Owner: postgres
--

CREATE INDEX acc_accgroups_area_id_b83745c3 ON public.acc_accgroups USING btree (area_id);


--
-- TOC entry 3759 (class 1259 OID 28785)
-- Name: acc_accholiday_area_id_d15c19da; Type: INDEX; Schema: public; Owner: postgres
--

CREATE INDEX acc_accholiday_area_id_d15c19da ON public.acc_accholiday USING btree (area_id);


--
-- TOC entry 3762 (class 1259 OID 28786)
-- Name: acc_accholiday_holiday_id_a9efe924; Type: INDEX; Schema: public; Owner: postgres
--

CREATE INDEX acc_accholiday_holiday_id_a9efe924 ON public.acc_accholiday USING btree (holiday_id);


--
-- TOC entry 3765 (class 1259 OID 28787)
-- Name: acc_accholiday_timezone_id_450d2d1e; Type: INDEX; Schema: public; Owner: postgres
--

CREATE INDEX acc_accholiday_timezone_id_450d2d1e ON public.acc_accholiday USING btree (timezone_id);


--
-- TOC entry 3766 (class 1259 OID 28788)
-- Name: acc_accprivilege_area_id_2123ff6f; Type: INDEX; Schema: public; Owner: postgres
--

CREATE INDEX acc_accprivilege_area_id_2123ff6f ON public.acc_accprivilege USING btree (area_id);


--
-- TOC entry 3769 (class 1259 OID 28789)
-- Name: acc_accprivilege_employee_id_5fc55f95; Type: INDEX; Schema: public; Owner: postgres
--

CREATE INDEX acc_accprivilege_employee_id_5fc55f95 ON public.acc_accprivilege USING btree (employee_id);


--
-- TOC entry 3770 (class 1259 OID 28790)
-- Name: acc_accprivilege_group_id_c5ed7003; Type: INDEX; Schema: public; Owner: postgres
--

CREATE INDEX acc_accprivilege_group_id_c5ed7003 ON public.acc_accprivilege USING btree (group_id);


--
-- TOC entry 3775 (class 1259 OID 28791)
-- Name: acc_accterminal_terminal_id_fc92cce2; Type: INDEX; Schema: public; Owner: postgres
--

CREATE INDEX acc_accterminal_terminal_id_fc92cce2 ON public.acc_accterminal USING btree (terminal_id);


--
-- TOC entry 3776 (class 1259 OID 28792)
-- Name: acc_acctimezone_area_id_e9ce7a7a; Type: INDEX; Schema: public; Owner: postgres
--

CREATE INDEX acc_acctimezone_area_id_e9ce7a7a ON public.acc_acctimezone USING btree (area_id);


--
-- TOC entry 3781 (class 1259 OID 28793)
-- Name: accounts_adminbiodata_admin_id_1e6d2d45; Type: INDEX; Schema: public; Owner: postgres
--

CREATE INDEX accounts_adminbiodata_admin_id_1e6d2d45 ON public.accounts_adminbiodata USING btree (admin_id);


--
-- TOC entry 3790 (class 1259 OID 28794)
-- Name: att_attrule_param_name_406bcfb6_like; Type: INDEX; Schema: public; Owner: postgres
--

CREATE INDEX att_attrule_param_name_406bcfb6_like ON public.att_attrule USING btree (param_name varchar_pattern_ops);


--
-- TOC entry 3793 (class 1259 OID 28795)
-- Name: att_attschedule_employee_id_caa61686; Type: INDEX; Schema: public; Owner: postgres
--

CREATE INDEX att_attschedule_employee_id_caa61686 ON public.att_attschedule USING btree (employee_id);


--
-- TOC entry 3796 (class 1259 OID 28796)
-- Name: att_attschedule_shift_id_13d2db9a; Type: INDEX; Schema: public; Owner: postgres
--

CREATE INDEX att_attschedule_shift_id_13d2db9a ON public.att_attschedule USING btree (shift_id);


--
-- TOC entry 3797 (class 1259 OID 28797)
-- Name: att_attshift_company_id_2c0a4f56; Type: INDEX; Schema: public; Owner: postgres
--

CREATE INDEX att_attshift_company_id_2c0a4f56 ON public.att_attshift USING btree (company_id);


--
-- TOC entry 3802 (class 1259 OID 28798)
-- Name: att_breaktime_company_id_fbb9a2b7; Type: INDEX; Schema: public; Owner: postgres
--

CREATE INDEX att_breaktime_company_id_fbb9a2b7 ON public.att_breaktime USING btree (company_id);


--
-- TOC entry 3805 (class 1259 OID 28799)
-- Name: att_changeschedule_employee_id_7871a2b6; Type: INDEX; Schema: public; Owner: postgres
--

CREATE INDEX att_changeschedule_employee_id_7871a2b6 ON public.att_changeschedule USING btree (employee_id);


--
-- TOC entry 3808 (class 1259 OID 28800)
-- Name: att_changeschedule_timeinterval_id_d41ac077; Type: INDEX; Schema: public; Owner: postgres
--

CREATE INDEX att_changeschedule_timeinterval_id_d41ac077 ON public.att_changeschedule USING btree (timeinterval_id);


--
-- TOC entry 3809 (class 1259 OID 28801)
-- Name: att_departmentschedule_department_id_c68fca3d; Type: INDEX; Schema: public; Owner: postgres
--

CREATE INDEX att_departmentschedule_department_id_c68fca3d ON public.att_departmentschedule USING btree (department_id);


--
-- TOC entry 3812 (class 1259 OID 28802)
-- Name: att_departmentschedule_shift_id_c37d5ade; Type: INDEX; Schema: public; Owner: postgres
--

CREATE INDEX att_departmentschedule_shift_id_c37d5ade ON public.att_departmentschedule USING btree (shift_id);


--
-- TOC entry 3813 (class 1259 OID 28803)
-- Name: att_deptattrule_company_id_420199ab; Type: INDEX; Schema: public; Owner: postgres
--

CREATE INDEX att_deptattrule_company_id_420199ab ON public.att_deptattrule USING btree (company_id);


--
-- TOC entry 3814 (class 1259 OID 28804)
-- Name: att_deptattrule_department_id_f333c8f0; Type: INDEX; Schema: public; Owner: postgres
--

CREATE INDEX att_deptattrule_department_id_f333c8f0 ON public.att_deptattrule USING btree (department_id);


--
-- TOC entry 3817 (class 1259 OID 28805)
-- Name: att_holiday_department_id_fbbbd185; Type: INDEX; Schema: public; Owner: postgres
--

CREATE INDEX att_holiday_department_id_fbbbd185 ON public.att_holiday USING btree (department_id);


--
-- TOC entry 3820 (class 1259 OID 28806)
-- Name: att_leave_category_id_bbba39ba; Type: INDEX; Schema: public; Owner: postgres
--

CREATE INDEX att_leave_category_id_bbba39ba ON public.att_leave USING btree (category_id);


--
-- TOC entry 3821 (class 1259 OID 28807)
-- Name: att_leave_employee_id_bb231627; Type: INDEX; Schema: public; Owner: postgres
--

CREATE INDEX att_leave_employee_id_bb231627 ON public.att_leave USING btree (employee_id);


--
-- TOC entry 3826 (class 1259 OID 28808)
-- Name: att_manuallog_employee_id_dc8cc2ad; Type: INDEX; Schema: public; Owner: postgres
--

CREATE INDEX att_manuallog_employee_id_dc8cc2ad ON public.att_manuallog USING btree (employee_id);


--
-- TOC entry 3829 (class 1259 OID 28809)
-- Name: att_overtime_employee_id_0c0d39dc; Type: INDEX; Schema: public; Owner: postgres
--

CREATE INDEX att_overtime_employee_id_0c0d39dc ON public.att_overtime USING btree (employee_id);


--
-- TOC entry 3832 (class 1259 OID 28810)
-- Name: att_payloadbase_break_time_id_022d6fac_like; Type: INDEX; Schema: public; Owner: postgres
--

CREATE INDEX att_payloadbase_break_time_id_022d6fac_like ON public.att_payloadbase USING btree (break_time_id varchar_pattern_ops);


--
-- TOC entry 3835 (class 1259 OID 28811)
-- Name: att_payloadbase_emp_id_2c0f6a7b; Type: INDEX; Schema: public; Owner: postgres
--

CREATE INDEX att_payloadbase_emp_id_2c0f6a7b ON public.att_payloadbase USING btree (emp_id);


--
-- TOC entry 3836 (class 1259 OID 28812)
-- Name: att_payloadbase_overtime_id_0e7be795_like; Type: INDEX; Schema: public; Owner: postgres
--

CREATE INDEX att_payloadbase_overtime_id_0e7be795_like ON public.att_payloadbase USING btree (overtime_id varchar_pattern_ops);


--
-- TOC entry 3841 (class 1259 OID 28813)
-- Name: att_payloadbase_timetable_id_a389e3d8; Type: INDEX; Schema: public; Owner: postgres
--

CREATE INDEX att_payloadbase_timetable_id_a389e3d8 ON public.att_payloadbase USING btree (timetable_id);


--
-- TOC entry 3842 (class 1259 OID 28814)
-- Name: att_payloadbase_trans_in_id_3b8fd648; Type: INDEX; Schema: public; Owner: postgres
--

CREATE INDEX att_payloadbase_trans_in_id_3b8fd648 ON public.att_payloadbase USING btree (trans_in_id);


--
-- TOC entry 3843 (class 1259 OID 28815)
-- Name: att_payloadbase_trans_out_id_ec63bbcc; Type: INDEX; Schema: public; Owner: postgres
--

CREATE INDEX att_payloadbase_trans_out_id_ec63bbcc ON public.att_payloadbase USING btree (trans_out_id);


--
-- TOC entry 3844 (class 1259 OID 28816)
-- Name: att_payloadbase_uuid_60250467_like; Type: INDEX; Schema: public; Owner: postgres
--

CREATE INDEX att_payloadbase_uuid_60250467_like ON public.att_payloadbase USING btree (uuid varchar_pattern_ops);


--
-- TOC entry 3847 (class 1259 OID 28817)
-- Name: att_payloadbreak_uuid_533ea5e2_like; Type: INDEX; Schema: public; Owner: postgres
--

CREATE INDEX att_payloadbreak_uuid_533ea5e2_like ON public.att_payloadbreak USING btree (uuid varchar_pattern_ops);


--
-- TOC entry 3848 (class 1259 OID 28818)
-- Name: att_payloadexception_item_id_a08bfe48; Type: INDEX; Schema: public; Owner: postgres
--

CREATE INDEX att_payloadexception_item_id_a08bfe48 ON public.att_payloadexception USING btree (item_id);


--
-- TOC entry 3851 (class 1259 OID 28819)
-- Name: att_payloadexception_skd_id_b2e9ecaa; Type: INDEX; Schema: public; Owner: postgres
--

CREATE INDEX att_payloadexception_skd_id_b2e9ecaa ON public.att_payloadexception USING btree (skd_id);


--
-- TOC entry 3852 (class 1259 OID 28820)
-- Name: att_payloadexception_skd_id_b2e9ecaa_like; Type: INDEX; Schema: public; Owner: postgres
--

CREATE INDEX att_payloadexception_skd_id_b2e9ecaa_like ON public.att_payloadexception USING btree (skd_id varchar_pattern_ops);


--
-- TOC entry 3853 (class 1259 OID 28821)
-- Name: att_payloadexception_uuid_517a81e8_like; Type: INDEX; Schema: public; Owner: postgres
--

CREATE INDEX att_payloadexception_uuid_517a81e8_like ON public.att_payloadexception USING btree (uuid varchar_pattern_ops);


--
-- TOC entry 3854 (class 1259 OID 28822)
-- Name: att_payloadmulpunchset_emp_id_f47610c8; Type: INDEX; Schema: public; Owner: postgres
--

CREATE INDEX att_payloadmulpunchset_emp_id_f47610c8 ON public.att_payloadmulpunchset USING btree (emp_id);


--
-- TOC entry 3857 (class 1259 OID 28823)
-- Name: att_payloadmulpunchset_timetable_id_9a439a09; Type: INDEX; Schema: public; Owner: postgres
--

CREATE INDEX att_payloadmulpunchset_timetable_id_9a439a09 ON public.att_payloadmulpunchset USING btree (timetable_id);


--
-- TOC entry 3860 (class 1259 OID 28824)
-- Name: att_payloadovertime_uuid_15d7782f_like; Type: INDEX; Schema: public; Owner: postgres
--

CREATE INDEX att_payloadovertime_uuid_15d7782f_like ON public.att_payloadovertime USING btree (uuid varchar_pattern_ops);


--
-- TOC entry 3861 (class 1259 OID 28825)
-- Name: att_payloadpunch_emp_id_053da2f0; Type: INDEX; Schema: public; Owner: postgres
--

CREATE INDEX att_payloadpunch_emp_id_053da2f0 ON public.att_payloadpunch USING btree (emp_id);


--
-- TOC entry 3862 (class 1259 OID 28826)
-- Name: att_payloadpunch_orig_id_16b26416; Type: INDEX; Schema: public; Owner: postgres
--

CREATE INDEX att_payloadpunch_orig_id_16b26416 ON public.att_payloadpunch USING btree (orig_id);


--
-- TOC entry 3865 (class 1259 OID 28827)
-- Name: att_payloadpunch_skd_id_17596d82; Type: INDEX; Schema: public; Owner: postgres
--

CREATE INDEX att_payloadpunch_skd_id_17596d82 ON public.att_payloadpunch USING btree (skd_id);


--
-- TOC entry 3866 (class 1259 OID 28828)
-- Name: att_payloadpunch_skd_id_17596d82_like; Type: INDEX; Schema: public; Owner: postgres
--

CREATE INDEX att_payloadpunch_skd_id_17596d82_like ON public.att_payloadpunch USING btree (skd_id varchar_pattern_ops);


--
-- TOC entry 3867 (class 1259 OID 28829)
-- Name: att_payloadpunch_uuid_91e722f4_like; Type: INDEX; Schema: public; Owner: postgres
--

CREATE INDEX att_payloadpunch_uuid_91e722f4_like ON public.att_payloadpunch USING btree (uuid varchar_pattern_ops);


--
-- TOC entry 3868 (class 1259 OID 28830)
-- Name: att_reportparam_param_name_23bdf026_like; Type: INDEX; Schema: public; Owner: postgres
--

CREATE INDEX att_reportparam_param_name_23bdf026_like ON public.att_reportparam USING btree (param_name varchar_pattern_ops);


--
-- TOC entry 3873 (class 1259 OID 28831)
-- Name: att_shiftdetail_shift_id_7d694501; Type: INDEX; Schema: public; Owner: postgres
--

CREATE INDEX att_shiftdetail_shift_id_7d694501 ON public.att_shiftdetail USING btree (shift_id);


--
-- TOC entry 3874 (class 1259 OID 28832)
-- Name: att_shiftdetail_time_interval_id_777dde8f; Type: INDEX; Schema: public; Owner: postgres
--

CREATE INDEX att_shiftdetail_time_interval_id_777dde8f ON public.att_shiftdetail USING btree (time_interval_id);


--
-- TOC entry 3875 (class 1259 OID 28833)
-- Name: att_tempschedule_employee_id_b89c7e54; Type: INDEX; Schema: public; Owner: postgres
--

CREATE INDEX att_tempschedule_employee_id_b89c7e54 ON public.att_tempschedule USING btree (employee_id);


--
-- TOC entry 3878 (class 1259 OID 28834)
-- Name: att_tempschedule_time_interval_id_08dd8eb3; Type: INDEX; Schema: public; Owner: postgres
--

CREATE INDEX att_tempschedule_time_interval_id_08dd8eb3 ON public.att_tempschedule USING btree (time_interval_id);


--
-- TOC entry 3884 (class 1259 OID 28835)
-- Name: att_timeinterval_break_time_breaktime_id_08462308; Type: INDEX; Schema: public; Owner: postgres
--

CREATE INDEX att_timeinterval_break_time_breaktime_id_08462308 ON public.att_timeinterval_break_time USING btree (breaktime_id);


--
-- TOC entry 3887 (class 1259 OID 28836)
-- Name: att_timeinterval_break_time_timeinterval_id_2287017e; Type: INDEX; Schema: public; Owner: postgres
--

CREATE INDEX att_timeinterval_break_time_timeinterval_id_2287017e ON public.att_timeinterval_break_time USING btree (timeinterval_id);


--
-- TOC entry 3879 (class 1259 OID 28837)
-- Name: att_timeinterval_company_id_9824d651; Type: INDEX; Schema: public; Owner: postgres
--

CREATE INDEX att_timeinterval_company_id_9824d651 ON public.att_timeinterval USING btree (company_id);


--
-- TOC entry 3888 (class 1259 OID 28838)
-- Name: att_training_category_id_fb38e891; Type: INDEX; Schema: public; Owner: postgres
--

CREATE INDEX att_training_category_id_fb38e891 ON public.att_training USING btree (category_id);


--
-- TOC entry 3889 (class 1259 OID 28839)
-- Name: att_training_employee_id_44af8319; Type: INDEX; Schema: public; Owner: postgres
--

CREATE INDEX att_training_employee_id_44af8319 ON public.att_training USING btree (employee_id);


--
-- TOC entry 3894 (class 1259 OID 28840)
-- Name: att_vacationemployee_employee_id_05793644; Type: INDEX; Schema: public; Owner: postgres
--

CREATE INDEX att_vacationemployee_employee_id_05793644 ON public.att_vacationemployee USING btree (employee_id);


--
-- TOC entry 3895 (class 1259 OID 28841)
-- Name: att_vacationemployee_leave_id_b127a4fe; Type: INDEX; Schema: public; Owner: postgres
--

CREATE INDEX att_vacationemployee_leave_id_b127a4fe ON public.att_vacationemployee USING btree (leave_id);


--
-- TOC entry 3898 (class 1259 OID 28842)
-- Name: att_vacationemployee_vacation_available_id_04bc7d89; Type: INDEX; Schema: public; Owner: postgres
--

CREATE INDEX att_vacationemployee_vacation_available_id_04bc7d89 ON public.att_vacationemployee USING btree (vacation_available_id);


--
-- TOC entry 3901 (class 1259 OID 28843)
-- Name: att_vacationtime_company_id_e885043c; Type: INDEX; Schema: public; Owner: postgres
--

CREATE INDEX att_vacationtime_company_id_e885043c ON public.att_vacationtime USING btree (company_id);


--
-- TOC entry 3906 (class 1259 OID 28844)
-- Name: att_vacationtimeseniority_vacation_time_id_803f6e65; Type: INDEX; Schema: public; Owner: postgres
--

CREATE INDEX att_vacationtimeseniority_vacation_time_id_803f6e65 ON public.att_vacationtimeseniority USING btree (vacation_time_id);


--
-- TOC entry 3911 (class 1259 OID 28845)
-- Name: auth_group_name_a6ea08ec_like; Type: INDEX; Schema: public; Owner: postgres
--

CREATE INDEX auth_group_name_a6ea08ec_like ON public.auth_group USING btree (name varchar_pattern_ops);


--
-- TOC entry 3916 (class 1259 OID 28846)
-- Name: auth_group_permissions_group_id_b120cbf9; Type: INDEX; Schema: public; Owner: postgres
--

CREATE INDEX auth_group_permissions_group_id_b120cbf9 ON public.auth_group_permissions USING btree (group_id);


--
-- TOC entry 3919 (class 1259 OID 28847)
-- Name: auth_group_permissions_permission_id_84c5c92e; Type: INDEX; Schema: public; Owner: postgres
--

CREATE INDEX auth_group_permissions_permission_id_84c5c92e ON public.auth_group_permissions USING btree (permission_id);


--
-- TOC entry 3922 (class 1259 OID 28848)
-- Name: auth_permission_content_type_id_2f476e4b; Type: INDEX; Schema: public; Owner: postgres
--

CREATE INDEX auth_permission_content_type_id_2f476e4b ON public.auth_permission USING btree (content_type_id);


--
-- TOC entry 3933 (class 1259 OID 28849)
-- Name: auth_user_auth_area_area_id_d1e54c70; Type: INDEX; Schema: public; Owner: postgres
--

CREATE INDEX auth_user_auth_area_area_id_d1e54c70 ON public.auth_user_auth_area USING btree (area_id);


--
-- TOC entry 3934 (class 1259 OID 28850)
-- Name: auth_user_auth_area_myuser_id_5fb9a803; Type: INDEX; Schema: public; Owner: postgres
--

CREATE INDEX auth_user_auth_area_myuser_id_5fb9a803 ON public.auth_user_auth_area USING btree (myuser_id);


--
-- TOC entry 3927 (class 1259 OID 28851)
-- Name: auth_user_auth_company_id_30b74281; Type: INDEX; Schema: public; Owner: postgres
--

CREATE INDEX auth_user_auth_company_id_30b74281 ON public.auth_user USING btree (auth_company_id);


--
-- TOC entry 3939 (class 1259 OID 28852)
-- Name: auth_user_auth_dept_department_id_5866c514; Type: INDEX; Schema: public; Owner: postgres
--

CREATE INDEX auth_user_auth_dept_department_id_5866c514 ON public.auth_user_auth_dept USING btree (department_id);


--
-- TOC entry 3940 (class 1259 OID 28853)
-- Name: auth_user_auth_dept_myuser_id_18a51b27; Type: INDEX; Schema: public; Owner: postgres
--

CREATE INDEX auth_user_auth_dept_myuser_id_18a51b27 ON public.auth_user_auth_dept USING btree (myuser_id);


--
-- TOC entry 3945 (class 1259 OID 28854)
-- Name: auth_user_groups_group_id_97559544; Type: INDEX; Schema: public; Owner: postgres
--

CREATE INDEX auth_user_groups_group_id_97559544 ON public.auth_user_groups USING btree (group_id);


--
-- TOC entry 3946 (class 1259 OID 28855)
-- Name: auth_user_groups_myuser_id_d03e8dcc; Type: INDEX; Schema: public; Owner: postgres
--

CREATE INDEX auth_user_groups_myuser_id_d03e8dcc ON public.auth_user_groups USING btree (myuser_id);


--
-- TOC entry 3957 (class 1259 OID 28856)
-- Name: auth_user_user_permissions_myuser_id_679b1527; Type: INDEX; Schema: public; Owner: postgres
--

CREATE INDEX auth_user_user_permissions_myuser_id_679b1527 ON public.auth_user_user_permissions USING btree (myuser_id);


--
-- TOC entry 3958 (class 1259 OID 28857)
-- Name: auth_user_user_permissions_permission_id_1fbb5f2c; Type: INDEX; Schema: public; Owner: postgres
--

CREATE INDEX auth_user_user_permissions_permission_id_1fbb5f2c ON public.auth_user_user_permissions USING btree (permission_id);


--
-- TOC entry 3930 (class 1259 OID 28858)
-- Name: auth_user_username_6821ab7c_like; Type: INDEX; Schema: public; Owner: postgres
--

CREATE INDEX auth_user_username_6821ab7c_like ON public.auth_user USING btree (username varchar_pattern_ops);


--
-- TOC entry 3961 (class 1259 OID 28859)
-- Name: authtoken_token_key_10f0b77e_like; Type: INDEX; Schema: public; Owner: postgres
--

CREATE INDEX authtoken_token_key_10f0b77e_like ON public.authtoken_token USING btree (key varchar_pattern_ops);


--
-- TOC entry 3966 (class 1259 OID 28860)
-- Name: base_adminlog_content_type_id_3e553c30; Type: INDEX; Schema: public; Owner: postgres
--

CREATE INDEX base_adminlog_content_type_id_3e553c30 ON public.base_adminlog USING btree (content_type_id);


--
-- TOC entry 3969 (class 1259 OID 28861)
-- Name: base_adminlog_user_id_ecf659f8; Type: INDEX; Schema: public; Owner: postgres
--

CREATE INDEX base_adminlog_user_id_ecf659f8 ON public.base_adminlog USING btree (user_id);


--
-- TOC entry 3972 (class 1259 OID 28862)
-- Name: base_attparamdepts_rulename_922e6bf3_like; Type: INDEX; Schema: public; Owner: postgres
--

CREATE INDEX base_attparamdepts_rulename_922e6bf3_like ON public.base_attparamdepts USING btree (rulename varchar_pattern_ops);


--
-- TOC entry 3977 (class 1259 OID 28863)
-- Name: base_autoexporttask_task_code_b7fa7d4e_like; Type: INDEX; Schema: public; Owner: postgres
--

CREATE INDEX base_autoexporttask_task_code_b7fa7d4e_like ON public.base_autoexporttask USING btree (task_code varchar_pattern_ops);


--
-- TOC entry 3980 (class 1259 OID 28864)
-- Name: base_bookmark_content_type_id_b6a0e799; Type: INDEX; Schema: public; Owner: postgres
--

CREATE INDEX base_bookmark_content_type_id_b6a0e799 ON public.base_bookmark USING btree (content_type_id);


--
-- TOC entry 3983 (class 1259 OID 28865)
-- Name: base_bookmark_user_id_5f2d5ca2; Type: INDEX; Schema: public; Owner: postgres
--

CREATE INDEX base_bookmark_user_id_5f2d5ca2 ON public.base_bookmark USING btree (user_id);


--
-- TOC entry 3994 (class 1259 OID 28866)
-- Name: base_departmentalert_department_department_id_33b76e92; Type: INDEX; Schema: public; Owner: postgres
--

CREATE INDEX base_departmentalert_department_department_id_33b76e92 ON public.base_departmentalert_department USING btree (department_id);


--
-- TOC entry 3995 (class 1259 OID 28867)
-- Name: base_departmentalert_department_departmentalert_id_79d27d1d; Type: INDEX; Schema: public; Owner: postgres
--

CREATE INDEX base_departmentalert_department_departmentalert_id_79d27d1d ON public.base_departmentalert_department USING btree (departmentalert_id);


--
-- TOC entry 4409 (class 1259 OID 44191)
-- Name: base_messengersentlog_content_type_id_e6e9b3d5; Type: INDEX; Schema: public; Owner: postgres
--

CREATE INDEX base_messengersentlog_content_type_id_e6e9b3d5 ON public.base_messengersentlog USING btree (content_type_id);


--
-- TOC entry 4410 (class 1259 OID 44203)
-- Name: base_messengersentlog_emp_id_44eba15e; Type: INDEX; Schema: public; Owner: postgres
--

CREATE INDEX base_messengersentlog_emp_id_44eba15e ON public.base_messengersentlog USING btree (emp_id);


--
-- TOC entry 4413 (class 1259 OID 44192)
-- Name: base_messengersentlog_user_id_64034c70; Type: INDEX; Schema: public; Owner: postgres
--

CREATE INDEX base_messengersentlog_user_id_64034c70 ON public.base_messengersentlog USING btree (user_id);


--
-- TOC entry 3998 (class 1259 OID 44220)
-- Name: base_personalalert_code_299aafe4_like; Type: INDEX; Schema: public; Owner: postgres
--

CREATE INDEX base_personalalert_code_299aafe4_like ON public.base_personalalert USING btree (code varchar_pattern_ops);


--
-- TOC entry 4405 (class 1259 OID 44169)
-- Name: base_personalalert_employee_employee_id_94832616; Type: INDEX; Schema: public; Owner: postgres
--

CREATE INDEX base_personalalert_employee_employee_id_94832616 ON public.base_personalalert_employee USING btree (employee_id);


--
-- TOC entry 4406 (class 1259 OID 44168)
-- Name: base_personalalert_employee_personalalert_id_27743165; Type: INDEX; Schema: public; Owner: postgres
--

CREATE INDEX base_personalalert_employee_personalalert_id_27743165 ON public.base_personalalert_employee USING btree (personalalert_id);


--
-- TOC entry 4021 (class 1259 OID 28871)
-- Name: base_sysparamdept_rule_name_bb46d5af_like; Type: INDEX; Schema: public; Owner: postgres
--

CREATE INDEX base_sysparamdept_rule_name_bb46d5af_like ON public.base_sysparamdept USING btree (rule_name varchar_pattern_ops);


--
-- TOC entry 4028 (class 1259 OID 28872)
-- Name: celery_taskmeta_hidden_23fd02dc; Type: INDEX; Schema: public; Owner: postgres
--

CREATE INDEX celery_taskmeta_hidden_23fd02dc ON public.celery_taskmeta USING btree (hidden);


--
-- TOC entry 4031 (class 1259 OID 28873)
-- Name: celery_taskmeta_task_id_9558b198_like; Type: INDEX; Schema: public; Owner: postgres
--

CREATE INDEX celery_taskmeta_task_id_9558b198_like ON public.celery_taskmeta USING btree (task_id varchar_pattern_ops);


--
-- TOC entry 4034 (class 1259 OID 28874)
-- Name: celery_tasksetmeta_hidden_593cfc24; Type: INDEX; Schema: public; Owner: postgres
--

CREATE INDEX celery_tasksetmeta_hidden_593cfc24 ON public.celery_tasksetmeta USING btree (hidden);


--
-- TOC entry 4037 (class 1259 OID 28875)
-- Name: celery_tasksetmeta_taskset_id_a5a1d4ae_like; Type: INDEX; Schema: public; Owner: postgres
--

CREATE INDEX celery_tasksetmeta_taskset_id_a5a1d4ae_like ON public.celery_tasksetmeta USING btree (taskset_id varchar_pattern_ops);


--
-- TOC entry 4040 (class 1259 OID 28876)
-- Name: django_admin_log_content_type_id_c4bce8eb; Type: INDEX; Schema: public; Owner: postgres
--

CREATE INDEX django_admin_log_content_type_id_c4bce8eb ON public.django_admin_log USING btree (content_type_id);


--
-- TOC entry 4043 (class 1259 OID 28877)
-- Name: django_admin_log_user_id_c564eba6; Type: INDEX; Schema: public; Owner: postgres
--

CREATE INDEX django_admin_log_user_id_c564eba6 ON public.django_admin_log USING btree (user_id);


--
-- TOC entry 4050 (class 1259 OID 28878)
-- Name: django_session_expire_date_a5c62663; Type: INDEX; Schema: public; Owner: postgres
--

CREATE INDEX django_session_expire_date_a5c62663 ON public.django_session USING btree (expire_date);


--
-- TOC entry 4053 (class 1259 OID 28879)
-- Name: django_session_session_key_c0390e0f_like; Type: INDEX; Schema: public; Owner: postgres
--

CREATE INDEX django_session_session_key_c0390e0f_like ON public.django_session USING btree (session_key varchar_pattern_ops);


--
-- TOC entry 4058 (class 1259 OID 28880)
-- Name: djcelery_periodictask_crontab_id_75609bab; Type: INDEX; Schema: public; Owner: postgres
--

CREATE INDEX djcelery_periodictask_crontab_id_75609bab ON public.djcelery_periodictask USING btree (crontab_id);


--
-- TOC entry 4059 (class 1259 OID 28881)
-- Name: djcelery_periodictask_interval_id_b426ab02; Type: INDEX; Schema: public; Owner: postgres
--

CREATE INDEX djcelery_periodictask_interval_id_b426ab02 ON public.djcelery_periodictask USING btree (interval_id);


--
-- TOC entry 4060 (class 1259 OID 28882)
-- Name: djcelery_periodictask_name_cb62cda9_like; Type: INDEX; Schema: public; Owner: postgres
--

CREATE INDEX djcelery_periodictask_name_cb62cda9_like ON public.djcelery_periodictask USING btree (name varchar_pattern_ops);


--
-- TOC entry 4067 (class 1259 OID 28883)
-- Name: djcelery_taskstate_hidden_c3905e57; Type: INDEX; Schema: public; Owner: postgres
--

CREATE INDEX djcelery_taskstate_hidden_c3905e57 ON public.djcelery_taskstate USING btree (hidden);


--
-- TOC entry 4068 (class 1259 OID 28884)
-- Name: djcelery_taskstate_name_8af9eded; Type: INDEX; Schema: public; Owner: postgres
--

CREATE INDEX djcelery_taskstate_name_8af9eded ON public.djcelery_taskstate USING btree (name);


--
-- TOC entry 4069 (class 1259 OID 28885)
-- Name: djcelery_taskstate_name_8af9eded_like; Type: INDEX; Schema: public; Owner: postgres
--

CREATE INDEX djcelery_taskstate_name_8af9eded_like ON public.djcelery_taskstate USING btree (name varchar_pattern_ops);


--
-- TOC entry 4072 (class 1259 OID 28886)
-- Name: djcelery_taskstate_state_53543be4; Type: INDEX; Schema: public; Owner: postgres
--

CREATE INDEX djcelery_taskstate_state_53543be4 ON public.djcelery_taskstate USING btree (state);


--
-- TOC entry 4073 (class 1259 OID 28887)
-- Name: djcelery_taskstate_state_53543be4_like; Type: INDEX; Schema: public; Owner: postgres
--

CREATE INDEX djcelery_taskstate_state_53543be4_like ON public.djcelery_taskstate USING btree (state varchar_pattern_ops);


--
-- TOC entry 4074 (class 1259 OID 28888)
-- Name: djcelery_taskstate_task_id_9d2efdb5_like; Type: INDEX; Schema: public; Owner: postgres
--

CREATE INDEX djcelery_taskstate_task_id_9d2efdb5_like ON public.djcelery_taskstate USING btree (task_id varchar_pattern_ops);


--
-- TOC entry 4077 (class 1259 OID 28889)
-- Name: djcelery_taskstate_tstamp_4c3f93a1; Type: INDEX; Schema: public; Owner: postgres
--

CREATE INDEX djcelery_taskstate_tstamp_4c3f93a1 ON public.djcelery_taskstate USING btree (tstamp);


--
-- TOC entry 4078 (class 1259 OID 28890)
-- Name: djcelery_taskstate_worker_id_f7f57a05; Type: INDEX; Schema: public; Owner: postgres
--

CREATE INDEX djcelery_taskstate_worker_id_f7f57a05 ON public.djcelery_taskstate USING btree (worker_id);


--
-- TOC entry 4079 (class 1259 OID 28891)
-- Name: djcelery_workerstate_hostname_b31c7fab_like; Type: INDEX; Schema: public; Owner: postgres
--

CREATE INDEX djcelery_workerstate_hostname_b31c7fab_like ON public.djcelery_workerstate USING btree (hostname varchar_pattern_ops);


--
-- TOC entry 4082 (class 1259 OID 28892)
-- Name: djcelery_workerstate_last_heartbeat_4539b544; Type: INDEX; Schema: public; Owner: postgres
--

CREATE INDEX djcelery_workerstate_last_heartbeat_4539b544 ON public.djcelery_workerstate USING btree (last_heartbeat);


--
-- TOC entry 4087 (class 1259 OID 28893)
-- Name: ep_eptransaction_emp_id_1006883f; Type: INDEX; Schema: public; Owner: postgres
--

CREATE INDEX ep_eptransaction_emp_id_1006883f ON public.ep_eptransaction USING btree (emp_id);


--
-- TOC entry 4092 (class 1259 OID 28894)
-- Name: ep_eptransaction_terminal_id_4490b209; Type: INDEX; Schema: public; Owner: postgres
--

CREATE INDEX ep_eptransaction_terminal_id_4490b209 ON public.ep_eptransaction USING btree (terminal_id);


--
-- TOC entry 4095 (class 1259 OID 28895)
-- Name: guardian_groupobjectpermission_content_type_id_7ade36b8; Type: INDEX; Schema: public; Owner: postgres
--

CREATE INDEX guardian_groupobjectpermission_content_type_id_7ade36b8 ON public.guardian_groupobjectpermission USING btree (content_type_id);


--
-- TOC entry 4096 (class 1259 OID 28896)
-- Name: guardian_groupobjectpermission_group_id_4bbbfb62; Type: INDEX; Schema: public; Owner: postgres
--

CREATE INDEX guardian_groupobjectpermission_group_id_4bbbfb62 ON public.guardian_groupobjectpermission USING btree (group_id);


--
-- TOC entry 4097 (class 1259 OID 28897)
-- Name: guardian_groupobjectpermission_permission_id_36572738; Type: INDEX; Schema: public; Owner: postgres
--

CREATE INDEX guardian_groupobjectpermission_permission_id_36572738 ON public.guardian_groupobjectpermission USING btree (permission_id);


--
-- TOC entry 4102 (class 1259 OID 28898)
-- Name: guardian_userobjectpermission_content_type_id_2e892405; Type: INDEX; Schema: public; Owner: postgres
--

CREATE INDEX guardian_userobjectpermission_content_type_id_2e892405 ON public.guardian_userobjectpermission USING btree (content_type_id);


--
-- TOC entry 4103 (class 1259 OID 28899)
-- Name: guardian_userobjectpermission_permission_id_71807bfc; Type: INDEX; Schema: public; Owner: postgres
--

CREATE INDEX guardian_userobjectpermission_permission_id_71807bfc ON public.guardian_userobjectpermission USING btree (permission_id);


--
-- TOC entry 4106 (class 1259 OID 28900)
-- Name: guardian_userobjectpermission_user_id_d5c1e964; Type: INDEX; Schema: public; Owner: postgres
--

CREATE INDEX guardian_userobjectpermission_user_id_d5c1e964 ON public.guardian_userobjectpermission USING btree (user_id);


--
-- TOC entry 4109 (class 1259 OID 28901)
-- Name: iclock_biodata_employee_id_ff748ea7; Type: INDEX; Schema: public; Owner: postgres
--

CREATE INDEX iclock_biodata_employee_id_ff748ea7 ON public.iclock_biodata USING btree (employee_id);


--
-- TOC entry 4112 (class 1259 OID 28902)
-- Name: iclock_biophoto_employee_id_3dba5819; Type: INDEX; Schema: public; Owner: postgres
--

CREATE INDEX iclock_biophoto_employee_id_3dba5819 ON public.iclock_biophoto USING btree (employee_id);


--
-- TOC entry 4117 (class 1259 OID 28903)
-- Name: iclock_deviceconfig_uuid_d52a3627_like; Type: INDEX; Schema: public; Owner: postgres
--

CREATE INDEX iclock_deviceconfig_uuid_d52a3627_like ON public.iclock_deviceconfig USING btree (uuid varchar_pattern_ops);


--
-- TOC entry 4120 (class 1259 OID 28904)
-- Name: iclock_errorcommandlog_terminal_id_3b2d7cbd; Type: INDEX; Schema: public; Owner: postgres
--

CREATE INDEX iclock_errorcommandlog_terminal_id_3b2d7cbd ON public.iclock_errorcommandlog USING btree (terminal_id);


--
-- TOC entry 4121 (class 1259 OID 28905)
-- Name: iclock_privatemessage_employee_id_e84a34c0; Type: INDEX; Schema: public; Owner: postgres
--

CREATE INDEX iclock_privatemessage_employee_id_e84a34c0 ON public.iclock_privatemessage USING btree (employee_id);


--
-- TOC entry 4126 (class 1259 OID 28906)
-- Name: iclock_publicmessage_terminal_id_c3b5e4cf; Type: INDEX; Schema: public; Owner: postgres
--

CREATE INDEX iclock_publicmessage_terminal_id_c3b5e4cf ON public.iclock_publicmessage USING btree (terminal_id);


--
-- TOC entry 4127 (class 1259 OID 28907)
-- Name: iclock_terminal_area_id_c019c6f0; Type: INDEX; Schema: public; Owner: postgres
--

CREATE INDEX iclock_terminal_area_id_c019c6f0 ON public.iclock_terminal USING btree (area_id);


--
-- TOC entry 4128 (class 1259 OID 28908)
-- Name: iclock_terminal_company_id_f2ecaaba; Type: INDEX; Schema: public; Owner: postgres
--

CREATE INDEX iclock_terminal_company_id_f2ecaaba ON public.iclock_terminal USING btree (company_id);


--
-- TOC entry 4131 (class 1259 OID 28909)
-- Name: iclock_terminal_sn_209168b1_like; Type: INDEX; Schema: public; Owner: postgres
--

CREATE INDEX iclock_terminal_sn_209168b1_like ON public.iclock_terminal USING btree (sn varchar_pattern_ops);


--
-- TOC entry 4136 (class 1259 OID 28910)
-- Name: iclock_terminalcommand_terminal_id_3dcf836f; Type: INDEX; Schema: public; Owner: postgres
--

CREATE INDEX iclock_terminalcommand_terminal_id_3dcf836f ON public.iclock_terminalcommand USING btree (terminal_id);


--
-- TOC entry 4139 (class 1259 OID 28911)
-- Name: iclock_terminalcommandlog_terminal_id_35ea8b2b; Type: INDEX; Schema: public; Owner: postgres
--

CREATE INDEX iclock_terminalcommandlog_terminal_id_35ea8b2b ON public.iclock_terminalcommandlog USING btree (terminal_id);


--
-- TOC entry 4144 (class 1259 OID 28912)
-- Name: iclock_terminallog_terminal_id_667b3ea7; Type: INDEX; Schema: public; Owner: postgres
--

CREATE INDEX iclock_terminallog_terminal_id_667b3ea7 ON public.iclock_terminallog USING btree (terminal_id);


--
-- TOC entry 4147 (class 1259 OID 28913)
-- Name: iclock_terminalparameter_terminal_id_443872e3; Type: INDEX; Schema: public; Owner: postgres
--

CREATE INDEX iclock_terminalparameter_terminal_id_443872e3 ON public.iclock_terminalparameter USING btree (terminal_id);


--
-- TOC entry 4152 (class 1259 OID 28914)
-- Name: iclock_terminaluploadlog_terminal_id_9c9a7664; Type: INDEX; Schema: public; Owner: postgres
--

CREATE INDEX iclock_terminaluploadlog_terminal_id_9c9a7664 ON public.iclock_terminaluploadlog USING btree (terminal_id);


--
-- TOC entry 4153 (class 1259 OID 28915)
-- Name: iclock_terminalworkcode_code_244e0245_like; Type: INDEX; Schema: public; Owner: postgres
--

CREATE INDEX iclock_terminalworkcode_code_244e0245_like ON public.iclock_terminalworkcode USING btree (code varchar_pattern_ops);


--
-- TOC entry 4160 (class 1259 OID 28916)
-- Name: iclock_transaction_emp_id_60fa3521; Type: INDEX; Schema: public; Owner: postgres
--

CREATE INDEX iclock_transaction_emp_id_60fa3521 ON public.iclock_transaction USING btree (emp_id);


--
-- TOC entry 4163 (class 1259 OID 28917)
-- Name: iclock_transaction_terminal_id_451c81c2; Type: INDEX; Schema: public; Owner: postgres
--

CREATE INDEX iclock_transaction_terminal_id_451c81c2 ON public.iclock_transaction USING btree (terminal_id);


--
-- TOC entry 4166 (class 1259 OID 28918)
-- Name: iclock_transactionproofcmd_terminal_id_08b81e1e; Type: INDEX; Schema: public; Owner: postgres
--

CREATE INDEX iclock_transactionproofcmd_terminal_id_08b81e1e ON public.iclock_transactionproofcmd USING btree (terminal_id);


--
-- TOC entry 4169 (class 1259 OID 28919)
-- Name: mobile_announcement_receiver_id_ddf2a860; Type: INDEX; Schema: public; Owner: postgres
--

CREATE INDEX mobile_announcement_receiver_id_ddf2a860 ON public.mobile_announcement USING btree (receiver_id);


--
-- TOC entry 4176 (class 1259 OID 28920)
-- Name: mobile_appnotification_receiver_id_90c4a355; Type: INDEX; Schema: public; Owner: postgres
--

CREATE INDEX mobile_appnotification_receiver_id_90c4a355 ON public.mobile_appnotification USING btree (receiver_id);


--
-- TOC entry 4177 (class 1259 OID 28921)
-- Name: mobile_gpsfordepartment_department_id_988ccf22; Type: INDEX; Schema: public; Owner: postgres
--

CREATE INDEX mobile_gpsfordepartment_department_id_988ccf22 ON public.mobile_gpsfordepartment USING btree (department_id);


--
-- TOC entry 4180 (class 1259 OID 28922)
-- Name: mobile_gpsforemployee_employee_id_982b7cef; Type: INDEX; Schema: public; Owner: postgres
--

CREATE INDEX mobile_gpsforemployee_employee_id_982b7cef ON public.mobile_gpsforemployee USING btree (employee_id);


--
-- TOC entry 4187 (class 1259 OID 28923)
-- Name: payroll_emploan_employee_id_97a251ef; Type: INDEX; Schema: public; Owner: postgres
--

CREATE INDEX payroll_emploan_employee_id_97a251ef ON public.payroll_emploan USING btree (employee_id);


--
-- TOC entry 4196 (class 1259 OID 28924)
-- Name: payroll_extradeduction_employee_id_53072441; Type: INDEX; Schema: public; Owner: postgres
--

CREATE INDEX payroll_extradeduction_employee_id_53072441 ON public.payroll_extradeduction USING btree (employee_id);


--
-- TOC entry 4199 (class 1259 OID 28925)
-- Name: payroll_extraincrease_employee_id_f902e6bb; Type: INDEX; Schema: public; Owner: postgres
--

CREATE INDEX payroll_extraincrease_employee_id_f902e6bb ON public.payroll_extraincrease USING btree (employee_id);


--
-- TOC entry 4204 (class 1259 OID 28926)
-- Name: payroll_leaveformula_category_id_945b2054; Type: INDEX; Schema: public; Owner: postgres
--

CREATE INDEX payroll_leaveformula_category_id_945b2054 ON public.payroll_leaveformula USING btree (category_id);


--
-- TOC entry 4207 (class 1259 OID 28927)
-- Name: payroll_monthlysalary_employee_id_97fdc6a9; Type: INDEX; Schema: public; Owner: postgres
--

CREATE INDEX payroll_monthlysalary_employee_id_97fdc6a9 ON public.payroll_monthlysalary USING btree (employee_id);


--
-- TOC entry 4212 (class 1259 OID 28928)
-- Name: payroll_reimbursement_employee_id_c4bbde36; Type: INDEX; Schema: public; Owner: postgres
--

CREATE INDEX payroll_reimbursement_employee_id_c4bbde36 ON public.payroll_reimbursement USING btree (employee_id);


--
-- TOC entry 4215 (class 1259 OID 28929)
-- Name: payroll_salaryadvance_employee_id_2abd43e5; Type: INDEX; Schema: public; Owner: postgres
--

CREATE INDEX payroll_salaryadvance_employee_id_2abd43e5 ON public.payroll_salaryadvance USING btree (employee_id);


--
-- TOC entry 4223 (class 1259 OID 28930)
-- Name: payroll_salarystructure_de_deductionformula_id_b174d5b6; Type: INDEX; Schema: public; Owner: postgres
--

CREATE INDEX payroll_salarystructure_de_deductionformula_id_b174d5b6 ON public.payroll_salarystructure_deductionformula USING btree (deductionformula_id);


--
-- TOC entry 4224 (class 1259 OID 28931)
-- Name: payroll_salarystructure_de_salarystructure_id_5ca7cdb5; Type: INDEX; Schema: public; Owner: postgres
--

CREATE INDEX payroll_salarystructure_de_salarystructure_id_5ca7cdb5 ON public.payroll_salarystructure_deductionformula USING btree (salarystructure_id);


--
-- TOC entry 4218 (class 1259 OID 28932)
-- Name: payroll_salarystructure_employee_id_98996e15; Type: INDEX; Schema: public; Owner: postgres
--

CREATE INDEX payroll_salarystructure_employee_id_98996e15 ON public.payroll_salarystructure USING btree (employee_id);


--
-- TOC entry 4229 (class 1259 OID 28933)
-- Name: payroll_salarystructure_ex_exceptionformula_id_8f6dadb3; Type: INDEX; Schema: public; Owner: postgres
--

CREATE INDEX payroll_salarystructure_ex_exceptionformula_id_8f6dadb3 ON public.payroll_salarystructure_exceptionformula USING btree (exceptionformula_id);


--
-- TOC entry 4230 (class 1259 OID 28934)
-- Name: payroll_salarystructure_ex_salarystructure_id_3c087208; Type: INDEX; Schema: public; Owner: postgres
--

CREATE INDEX payroll_salarystructure_ex_salarystructure_id_3c087208 ON public.payroll_salarystructure_exceptionformula USING btree (salarystructure_id);


--
-- TOC entry 4235 (class 1259 OID 28935)
-- Name: payroll_salarystructure_in_increasementformula_id_3cd77082; Type: INDEX; Schema: public; Owner: postgres
--

CREATE INDEX payroll_salarystructure_in_increasementformula_id_3cd77082 ON public.payroll_salarystructure_increasementformula USING btree (increasementformula_id);


--
-- TOC entry 4236 (class 1259 OID 28936)
-- Name: payroll_salarystructure_in_salarystructure_id_8752401c; Type: INDEX; Schema: public; Owner: postgres
--

CREATE INDEX payroll_salarystructure_in_salarystructure_id_8752401c ON public.payroll_salarystructure_increasementformula USING btree (salarystructure_id);


--
-- TOC entry 4241 (class 1259 OID 28937)
-- Name: payroll_salarystructure_le_salarystructure_id_cf98fdd7; Type: INDEX; Schema: public; Owner: postgres
--

CREATE INDEX payroll_salarystructure_le_salarystructure_id_cf98fdd7 ON public.payroll_salarystructure_leaveformula USING btree (salarystructure_id);


--
-- TOC entry 4242 (class 1259 OID 28938)
-- Name: payroll_salarystructure_leaveformula_leaveformula_id_049f9024; Type: INDEX; Schema: public; Owner: postgres
--

CREATE INDEX payroll_salarystructure_leaveformula_leaveformula_id_049f9024 ON public.payroll_salarystructure_leaveformula USING btree (leaveformula_id);


--
-- TOC entry 4247 (class 1259 OID 28939)
-- Name: payroll_salarystructure_ov_overtimeformula_id_40ad89ef; Type: INDEX; Schema: public; Owner: postgres
--

CREATE INDEX payroll_salarystructure_ov_overtimeformula_id_40ad89ef ON public.payroll_salarystructure_overtimeformula USING btree (overtimeformula_id);


--
-- TOC entry 4248 (class 1259 OID 28940)
-- Name: payroll_salarystructure_ov_salarystructure_id_64f75042; Type: INDEX; Schema: public; Owner: postgres
--

CREATE INDEX payroll_salarystructure_ov_salarystructure_id_64f75042 ON public.payroll_salarystructure_overtimeformula USING btree (salarystructure_id);


--
-- TOC entry 4251 (class 1259 OID 28941)
-- Name: personnel_area_area_code_16aa7c34_like; Type: INDEX; Schema: public; Owner: postgres
--

CREATE INDEX personnel_area_area_code_16aa7c34_like ON public.personnel_area USING btree (area_code varchar_pattern_ops);


--
-- TOC entry 4254 (class 1259 OID 28942)
-- Name: personnel_area_company_id_59750eb5; Type: INDEX; Schema: public; Owner: postgres
--

CREATE INDEX personnel_area_company_id_59750eb5 ON public.personnel_area USING btree (company_id);


--
-- TOC entry 4255 (class 1259 OID 28943)
-- Name: personnel_area_parent_area_id_39028fda; Type: INDEX; Schema: public; Owner: postgres
--

CREATE INDEX personnel_area_parent_area_id_39028fda ON public.personnel_area USING btree (parent_area_id);


--
-- TOC entry 4258 (class 1259 OID 28944)
-- Name: personnel_assignareaemployee_area_id_6f049d6a; Type: INDEX; Schema: public; Owner: postgres
--

CREATE INDEX personnel_assignareaemployee_area_id_6f049d6a ON public.personnel_assignareaemployee USING btree (area_id);


--
-- TOC entry 4259 (class 1259 OID 28945)
-- Name: personnel_assignareaemployee_employee_id_a3d4dd25; Type: INDEX; Schema: public; Owner: postgres
--

CREATE INDEX personnel_assignareaemployee_employee_id_a3d4dd25 ON public.personnel_assignareaemployee USING btree (employee_id);


--
-- TOC entry 4264 (class 1259 OID 28946)
-- Name: personnel_certification_company_id_c1b1bd00; Type: INDEX; Schema: public; Owner: postgres
--

CREATE INDEX personnel_certification_company_id_c1b1bd00 ON public.personnel_certification USING btree (company_id);


--
-- TOC entry 4267 (class 1259 OID 28947)
-- Name: personnel_company_company_code_537dca09_like; Type: INDEX; Schema: public; Owner: postgres
--

CREATE INDEX personnel_company_company_code_537dca09_like ON public.personnel_company USING btree (company_code varchar_pattern_ops);


--
-- TOC entry 4272 (class 1259 OID 28948)
-- Name: personnel_companyregister_company_code_3d5ba9dd_like; Type: INDEX; Schema: public; Owner: postgres
--

CREATE INDEX personnel_companyregister_company_code_3d5ba9dd_like ON public.personnel_companyregister USING btree (company_code varchar_pattern_ops);


--
-- TOC entry 4277 (class 1259 OID 28949)
-- Name: personnel_department_company_id_00867fd8; Type: INDEX; Schema: public; Owner: postgres
--

CREATE INDEX personnel_department_company_id_00867fd8 ON public.personnel_department USING btree (company_id);


--
-- TOC entry 4278 (class 1259 OID 28950)
-- Name: personnel_department_dept_code_215a9448_like; Type: INDEX; Schema: public; Owner: postgres
--

CREATE INDEX personnel_department_dept_code_215a9448_like ON public.personnel_department USING btree (dept_code varchar_pattern_ops);


--
-- TOC entry 4281 (class 1259 OID 28951)
-- Name: personnel_department_parent_dept_id_d0b44024; Type: INDEX; Schema: public; Owner: postgres
--

CREATE INDEX personnel_department_parent_dept_id_d0b44024 ON public.personnel_department USING btree (parent_dept_id);


--
-- TOC entry 4291 (class 1259 OID 28952)
-- Name: personnel_employee_area_area_id_64c21925; Type: INDEX; Schema: public; Owner: postgres
--

CREATE INDEX personnel_employee_area_area_id_64c21925 ON public.personnel_employee_area USING btree (area_id);


--
-- TOC entry 4292 (class 1259 OID 28953)
-- Name: personnel_employee_area_employee_id_8e5cec21; Type: INDEX; Schema: public; Owner: postgres
--

CREATE INDEX personnel_employee_area_employee_id_8e5cec21 ON public.personnel_employee_area USING btree (employee_id);


--
-- TOC entry 4299 (class 1259 OID 28954)
-- Name: personnel_employee_area_privilege_area_id_6e42535e; Type: INDEX; Schema: public; Owner: postgres
--

CREATE INDEX personnel_employee_area_privilege_area_id_6e42535e ON public.personnel_employee_area_privilege USING btree (area_id);


--
-- TOC entry 4300 (class 1259 OID 28955)
-- Name: personnel_employee_area_privilege_employee_id_1ee6fb47; Type: INDEX; Schema: public; Owner: postgres
--

CREATE INDEX personnel_employee_area_privilege_employee_id_1ee6fb47 ON public.personnel_employee_area_privilege USING btree (employee_id);


--
-- TOC entry 4284 (class 1259 OID 28956)
-- Name: personnel_employee_company_id_95b3fd72; Type: INDEX; Schema: public; Owner: postgres
--

CREATE INDEX personnel_employee_company_id_95b3fd72 ON public.personnel_employee USING btree (company_id);


--
-- TOC entry 4285 (class 1259 OID 28957)
-- Name: personnel_employee_department_id_068bbd08; Type: INDEX; Schema: public; Owner: postgres
--

CREATE INDEX personnel_employee_department_id_068bbd08 ON public.personnel_employee USING btree (department_id);


--
-- TOC entry 4305 (class 1259 OID 28958)
-- Name: personnel_employee_flow_role_employee_id_c27f8a56; Type: INDEX; Schema: public; Owner: postgres
--

CREATE INDEX personnel_employee_flow_role_employee_id_c27f8a56 ON public.personnel_employee_flow_role USING btree (employee_id);


--
-- TOC entry 4308 (class 1259 OID 28959)
-- Name: personnel_employee_flow_role_workflowrole_id_4704db32; Type: INDEX; Schema: public; Owner: postgres
--

CREATE INDEX personnel_employee_flow_role_workflowrole_id_4704db32 ON public.personnel_employee_flow_role USING btree (workflowrole_id);


--
-- TOC entry 4290 (class 1259 OID 28960)
-- Name: personnel_employee_position_id_c9321343; Type: INDEX; Schema: public; Owner: postgres
--

CREATE INDEX personnel_employee_position_id_c9321343 ON public.personnel_employee USING btree (position_id);


--
-- TOC entry 4311 (class 1259 OID 28961)
-- Name: personnel_employeecertification_certification_id_faabed40; Type: INDEX; Schema: public; Owner: postgres
--

CREATE INDEX personnel_employeecertification_certification_id_faabed40 ON public.personnel_employeecertification USING btree (certification_id);


--
-- TOC entry 4312 (class 1259 OID 28962)
-- Name: personnel_employeecertification_employee_id_b7bd3867; Type: INDEX; Schema: public; Owner: postgres
--

CREATE INDEX personnel_employeecertification_employee_id_b7bd3867 ON public.personnel_employeecertification USING btree (employee_id);


--
-- TOC entry 4319 (class 1259 OID 28963)
-- Name: personnel_position_company_id_f06c5d2a; Type: INDEX; Schema: public; Owner: postgres
--

CREATE INDEX personnel_position_company_id_f06c5d2a ON public.personnel_position USING btree (company_id);


--
-- TOC entry 4320 (class 1259 OID 28964)
-- Name: personnel_position_parent_position_id_a496a36b; Type: INDEX; Schema: public; Owner: postgres
--

CREATE INDEX personnel_position_parent_position_id_a496a36b ON public.personnel_position USING btree (parent_position_id);


--
-- TOC entry 4323 (class 1259 OID 28965)
-- Name: personnel_position_position_code_4ff57828_like; Type: INDEX; Schema: public; Owner: postgres
--

CREATE INDEX personnel_position_position_code_4ff57828_like ON public.personnel_position USING btree (position_code varchar_pattern_ops);


--
-- TOC entry 4326 (class 1259 OID 28966)
-- Name: personnel_resign_company_id_a02da327; Type: INDEX; Schema: public; Owner: postgres
--

CREATE INDEX personnel_resign_company_id_a02da327 ON public.personnel_resign USING btree (company_id);


--
-- TOC entry 4331 (class 1259 OID 28967)
-- Name: staff_stafftoken_key_af7789a4_like; Type: INDEX; Schema: public; Owner: postgres
--

CREATE INDEX staff_stafftoken_key_af7789a4_like ON public.staff_stafftoken USING btree (key varchar_pattern_ops);


--
-- TOC entry 4354 (class 1259 OID 28968)
-- Name: workflow_nodeinstance_approver_admin_id_dff58806; Type: INDEX; Schema: public; Owner: postgres
--

CREATE INDEX workflow_nodeinstance_approver_admin_id_dff58806 ON public.workflow_nodeinstance USING btree (approver_admin_id);


--
-- TOC entry 4355 (class 1259 OID 28969)
-- Name: workflow_nodeinstance_approver_employee_id_d36cd45d; Type: INDEX; Schema: public; Owner: postgres
--

CREATE INDEX workflow_nodeinstance_approver_employee_id_d36cd45d ON public.workflow_nodeinstance USING btree (approver_employee_id);


--
-- TOC entry 4356 (class 1259 OID 28970)
-- Name: workflow_nodeinstance_departments_id_b0dc2bdb; Type: INDEX; Schema: public; Owner: postgres
--

CREATE INDEX workflow_nodeinstance_departments_id_b0dc2bdb ON public.workflow_nodeinstance USING btree (departments_id);


--
-- TOC entry 4357 (class 1259 OID 28971)
-- Name: workflow_nodeinstance_node_engine_id_4533f12d; Type: INDEX; Schema: public; Owner: postgres
--

CREATE INDEX workflow_nodeinstance_node_engine_id_4533f12d ON public.workflow_nodeinstance USING btree (node_engine_id);


--
-- TOC entry 4360 (class 1259 OID 28972)
-- Name: workflow_nodeinstance_workflow_instance_id_afe84fe4; Type: INDEX; Schema: public; Owner: postgres
--

CREATE INDEX workflow_nodeinstance_workflow_instance_id_afe84fe4 ON public.workflow_nodeinstance USING btree (workflow_instance_id);


--
-- TOC entry 4361 (class 1259 OID 28973)
-- Name: workflow_workflowengine_applicant_position_id_8a65e03a; Type: INDEX; Schema: public; Owner: postgres
--

CREATE INDEX workflow_workflowengine_applicant_position_id_8a65e03a ON public.workflow_workflowengine USING btree (applicant_position_id);


--
-- TOC entry 4362 (class 1259 OID 28974)
-- Name: workflow_workflowengine_company_id_c42adcb0; Type: INDEX; Schema: public; Owner: postgres
--

CREATE INDEX workflow_workflowengine_company_id_c42adcb0 ON public.workflow_workflowengine USING btree (company_id);


--
-- TOC entry 4363 (class 1259 OID 28975)
-- Name: workflow_workflowengine_content_type_id_f7345c20; Type: INDEX; Schema: public; Owner: postgres
--

CREATE INDEX workflow_workflowengine_content_type_id_f7345c20 ON public.workflow_workflowengine USING btree (content_type_id);


--
-- TOC entry 4364 (class 1259 OID 28976)
-- Name: workflow_workflowengine_departments_id_0f06d4c7; Type: INDEX; Schema: public; Owner: postgres
--

CREATE INDEX workflow_workflowengine_departments_id_0f06d4c7 ON public.workflow_workflowengine USING btree (departments_id);


--
-- TOC entry 4371 (class 1259 OID 28977)
-- Name: workflow_workflowengine_employee_employee_id_803a409e; Type: INDEX; Schema: public; Owner: postgres
--

CREATE INDEX workflow_workflowengine_employee_employee_id_803a409e ON public.workflow_workflowengine_employee USING btree (employee_id);


--
-- TOC entry 4374 (class 1259 OID 28978)
-- Name: workflow_workflowengine_employee_workflowengine_id_6ebcc5f2; Type: INDEX; Schema: public; Owner: postgres
--

CREATE INDEX workflow_workflowengine_employee_workflowengine_id_6ebcc5f2 ON public.workflow_workflowengine_employee USING btree (workflowengine_id);


--
-- TOC entry 4375 (class 1259 OID 28979)
-- Name: workflow_workflowinstance_employee_id_c7cff08e; Type: INDEX; Schema: public; Owner: postgres
--

CREATE INDEX workflow_workflowinstance_employee_id_c7cff08e ON public.workflow_workflowinstance USING btree (employee_id);


--
-- TOC entry 4380 (class 1259 OID 28980)
-- Name: workflow_workflowinstance_workflow_engine_id_1e6ac40f; Type: INDEX; Schema: public; Owner: postgres
--

CREATE INDEX workflow_workflowinstance_workflow_engine_id_1e6ac40f ON public.workflow_workflowinstance USING btree (workflow_engine_id);


--
-- TOC entry 4388 (class 1259 OID 28981)
-- Name: workflow_workflownode_approver_workflownode_id_d814c941; Type: INDEX; Schema: public; Owner: postgres
--

CREATE INDEX workflow_workflownode_approver_workflownode_id_d814c941 ON public.workflow_workflownode_approver USING btree (workflownode_id);


--
-- TOC entry 4389 (class 1259 OID 28982)
-- Name: workflow_workflownode_approver_workflowrole_id_c8e00d42; Type: INDEX; Schema: public; Owner: postgres
--

CREATE INDEX workflow_workflownode_approver_workflowrole_id_c8e00d42 ON public.workflow_workflownode_approver USING btree (workflowrole_id);


--
-- TOC entry 4381 (class 1259 OID 28983)
-- Name: workflow_workflownode_company_id_44989997; Type: INDEX; Schema: public; Owner: postgres
--

CREATE INDEX workflow_workflownode_company_id_44989997 ON public.workflow_workflownode USING btree (company_id);


--
-- TOC entry 4394 (class 1259 OID 28984)
-- Name: workflow_workflownode_notifier_workflownode_id_57298016; Type: INDEX; Schema: public; Owner: postgres
--

CREATE INDEX workflow_workflownode_notifier_workflownode_id_57298016 ON public.workflow_workflownode_notifier USING btree (workflownode_id);


--
-- TOC entry 4395 (class 1259 OID 28985)
-- Name: workflow_workflownode_notifier_workflowrole_id_73de7fc2; Type: INDEX; Schema: public; Owner: postgres
--

CREATE INDEX workflow_workflownode_notifier_workflowrole_id_73de7fc2 ON public.workflow_workflownode_notifier USING btree (workflowrole_id);


--
-- TOC entry 4396 (class 1259 OID 28986)
-- Name: workflow_workflowrole_company_id_bbb75590; Type: INDEX; Schema: public; Owner: postgres
--

CREATE INDEX workflow_workflowrole_company_id_bbb75590 ON public.workflow_workflowrole USING btree (company_id);


--
-- TOC entry 4414 (class 2606 OID 28987)
-- Name: acc_acccombination acc_acccombination_area_id_0d22c34e_fk_personnel_area_id; Type: FK CONSTRAINT; Schema: public; Owner: postgres
--

ALTER TABLE ONLY public.acc_acccombination
    ADD CONSTRAINT acc_acccombination_area_id_0d22c34e_fk_personnel_area_id FOREIGN KEY (area_id) REFERENCES public.personnel_area(id) DEFERRABLE INITIALLY DEFERRED;


--
-- TOC entry 4415 (class 2606 OID 28992)
-- Name: acc_accgroups acc_accgroups_area_id_b83745c3_fk_personnel_area_id; Type: FK CONSTRAINT; Schema: public; Owner: postgres
--

ALTER TABLE ONLY public.acc_accgroups
    ADD CONSTRAINT acc_accgroups_area_id_b83745c3_fk_personnel_area_id FOREIGN KEY (area_id) REFERENCES public.personnel_area(id) DEFERRABLE INITIALLY DEFERRED;


--
-- TOC entry 4416 (class 2606 OID 28997)
-- Name: acc_accholiday acc_accholiday_area_id_d15c19da_fk_personnel_area_id; Type: FK CONSTRAINT; Schema: public; Owner: postgres
--

ALTER TABLE ONLY public.acc_accholiday
    ADD CONSTRAINT acc_accholiday_area_id_d15c19da_fk_personnel_area_id FOREIGN KEY (area_id) REFERENCES public.personnel_area(id) DEFERRABLE INITIALLY DEFERRED;


--
-- TOC entry 4417 (class 2606 OID 29002)
-- Name: acc_accholiday acc_accholiday_holiday_id_a9efe924_fk_att_holiday_id; Type: FK CONSTRAINT; Schema: public; Owner: postgres
--

ALTER TABLE ONLY public.acc_accholiday
    ADD CONSTRAINT acc_accholiday_holiday_id_a9efe924_fk_att_holiday_id FOREIGN KEY (holiday_id) REFERENCES public.att_holiday(id) DEFERRABLE INITIALLY DEFERRED;


--
-- TOC entry 4418 (class 2606 OID 29007)
-- Name: acc_accholiday acc_accholiday_timezone_id_450d2d1e_fk_acc_acctimezone_id; Type: FK CONSTRAINT; Schema: public; Owner: postgres
--

ALTER TABLE ONLY public.acc_accholiday
    ADD CONSTRAINT acc_accholiday_timezone_id_450d2d1e_fk_acc_acctimezone_id FOREIGN KEY (timezone_id) REFERENCES public.acc_acctimezone(id) DEFERRABLE INITIALLY DEFERRED;


--
-- TOC entry 4419 (class 2606 OID 29012)
-- Name: acc_accprivilege acc_accprivilege_area_id_2123ff6f_fk_personnel_area_id; Type: FK CONSTRAINT; Schema: public; Owner: postgres
--

ALTER TABLE ONLY public.acc_accprivilege
    ADD CONSTRAINT acc_accprivilege_area_id_2123ff6f_fk_personnel_area_id FOREIGN KEY (area_id) REFERENCES public.personnel_area(id) DEFERRABLE INITIALLY DEFERRED;


--
-- TOC entry 4420 (class 2606 OID 29017)
-- Name: acc_accprivilege acc_accprivilege_employee_id_5fc55f95_fk_personnel_employee_id; Type: FK CONSTRAINT; Schema: public; Owner: postgres
--

ALTER TABLE ONLY public.acc_accprivilege
    ADD CONSTRAINT acc_accprivilege_employee_id_5fc55f95_fk_personnel_employee_id FOREIGN KEY (employee_id) REFERENCES public.personnel_employee(id) DEFERRABLE INITIALLY DEFERRED;


--
-- TOC entry 4421 (class 2606 OID 29022)
-- Name: acc_accprivilege acc_accprivilege_group_id_c5ed7003_fk_acc_accgroups_id; Type: FK CONSTRAINT; Schema: public; Owner: postgres
--

ALTER TABLE ONLY public.acc_accprivilege
    ADD CONSTRAINT acc_accprivilege_group_id_c5ed7003_fk_acc_accgroups_id FOREIGN KEY (group_id) REFERENCES public.acc_accgroups(id) DEFERRABLE INITIALLY DEFERRED;


--
-- TOC entry 4422 (class 2606 OID 29027)
-- Name: acc_accterminal acc_accterminal_terminal_id_fc92cce2_fk_iclock_terminal_id; Type: FK CONSTRAINT; Schema: public; Owner: postgres
--

ALTER TABLE ONLY public.acc_accterminal
    ADD CONSTRAINT acc_accterminal_terminal_id_fc92cce2_fk_iclock_terminal_id FOREIGN KEY (terminal_id) REFERENCES public.iclock_terminal(id) DEFERRABLE INITIALLY DEFERRED;


--
-- TOC entry 4423 (class 2606 OID 29032)
-- Name: acc_acctimezone acc_acctimezone_area_id_e9ce7a7a_fk_personnel_area_id; Type: FK CONSTRAINT; Schema: public; Owner: postgres
--

ALTER TABLE ONLY public.acc_acctimezone
    ADD CONSTRAINT acc_acctimezone_area_id_e9ce7a7a_fk_personnel_area_id FOREIGN KEY (area_id) REFERENCES public.personnel_area(id) DEFERRABLE INITIALLY DEFERRED;


--
-- TOC entry 4424 (class 2606 OID 29037)
-- Name: accounts_adminbiodata accounts_adminbiodata_admin_id_1e6d2d45_fk_auth_user_id; Type: FK CONSTRAINT; Schema: public; Owner: postgres
--

ALTER TABLE ONLY public.accounts_adminbiodata
    ADD CONSTRAINT accounts_adminbiodata_admin_id_1e6d2d45_fk_auth_user_id FOREIGN KEY (admin_id) REFERENCES public.auth_user(id) DEFERRABLE INITIALLY DEFERRED;


--
-- TOC entry 4425 (class 2606 OID 29042)
-- Name: att_attschedule att_attschedule_employee_id_caa61686_fk_personnel_employee_id; Type: FK CONSTRAINT; Schema: public; Owner: postgres
--

ALTER TABLE ONLY public.att_attschedule
    ADD CONSTRAINT att_attschedule_employee_id_caa61686_fk_personnel_employee_id FOREIGN KEY (employee_id) REFERENCES public.personnel_employee(id) DEFERRABLE INITIALLY DEFERRED;


--
-- TOC entry 4426 (class 2606 OID 29047)
-- Name: att_attschedule att_attschedule_shift_id_13d2db9a_fk_att_attshift_id; Type: FK CONSTRAINT; Schema: public; Owner: postgres
--

ALTER TABLE ONLY public.att_attschedule
    ADD CONSTRAINT att_attschedule_shift_id_13d2db9a_fk_att_attshift_id FOREIGN KEY (shift_id) REFERENCES public.att_attshift(id) DEFERRABLE INITIALLY DEFERRED;


--
-- TOC entry 4427 (class 2606 OID 29052)
-- Name: att_attshift att_attshift_company_id_2c0a4f56_fk_personnel_company_id; Type: FK CONSTRAINT; Schema: public; Owner: postgres
--

ALTER TABLE ONLY public.att_attshift
    ADD CONSTRAINT att_attshift_company_id_2c0a4f56_fk_personnel_company_id FOREIGN KEY (company_id) REFERENCES public.personnel_company(id) DEFERRABLE INITIALLY DEFERRED;


--
-- TOC entry 4428 (class 2606 OID 29057)
-- Name: att_breaktime att_breaktime_company_id_fbb9a2b7_fk_personnel_company_id; Type: FK CONSTRAINT; Schema: public; Owner: postgres
--

ALTER TABLE ONLY public.att_breaktime
    ADD CONSTRAINT att_breaktime_company_id_fbb9a2b7_fk_personnel_company_id FOREIGN KEY (company_id) REFERENCES public.personnel_company(id) DEFERRABLE INITIALLY DEFERRED;


--
-- TOC entry 4429 (class 2606 OID 29062)
-- Name: att_changeschedule att_changeschedule_abstractexception_pt_6bf48cd8_fk_workflow_; Type: FK CONSTRAINT; Schema: public; Owner: postgres
--

ALTER TABLE ONLY public.att_changeschedule
    ADD CONSTRAINT att_changeschedule_abstractexception_pt_6bf48cd8_fk_workflow_ FOREIGN KEY (abstractexception_ptr_id) REFERENCES public.workflow_abstractexception(id) DEFERRABLE INITIALLY DEFERRED;


--
-- TOC entry 4430 (class 2606 OID 29067)
-- Name: att_changeschedule att_changeschedule_employee_id_7871a2b6_fk_personnel; Type: FK CONSTRAINT; Schema: public; Owner: postgres
--

ALTER TABLE ONLY public.att_changeschedule
    ADD CONSTRAINT att_changeschedule_employee_id_7871a2b6_fk_personnel FOREIGN KEY (employee_id) REFERENCES public.personnel_employee(id) DEFERRABLE INITIALLY DEFERRED;


--
-- TOC entry 4431 (class 2606 OID 29072)
-- Name: att_changeschedule att_changeschedule_timeinterval_id_d41ac077_fk_att_timei; Type: FK CONSTRAINT; Schema: public; Owner: postgres
--

ALTER TABLE ONLY public.att_changeschedule
    ADD CONSTRAINT att_changeschedule_timeinterval_id_d41ac077_fk_att_timei FOREIGN KEY (timeinterval_id) REFERENCES public.att_timeinterval(id) DEFERRABLE INITIALLY DEFERRED;


--
-- TOC entry 4432 (class 2606 OID 29077)
-- Name: att_departmentschedule att_departmentschedu_department_id_c68fca3d_fk_personnel; Type: FK CONSTRAINT; Schema: public; Owner: postgres
--

ALTER TABLE ONLY public.att_departmentschedule
    ADD CONSTRAINT att_departmentschedu_department_id_c68fca3d_fk_personnel FOREIGN KEY (department_id) REFERENCES public.personnel_department(id) DEFERRABLE INITIALLY DEFERRED;


--
-- TOC entry 4433 (class 2606 OID 29082)
-- Name: att_departmentschedule att_departmentschedule_shift_id_c37d5ade_fk_att_attshift_id; Type: FK CONSTRAINT; Schema: public; Owner: postgres
--

ALTER TABLE ONLY public.att_departmentschedule
    ADD CONSTRAINT att_departmentschedule_shift_id_c37d5ade_fk_att_attshift_id FOREIGN KEY (shift_id) REFERENCES public.att_attshift(id) DEFERRABLE INITIALLY DEFERRED;


--
-- TOC entry 4434 (class 2606 OID 29087)
-- Name: att_deptattrule att_deptattrule_company_id_420199ab_fk_personnel_company_id; Type: FK CONSTRAINT; Schema: public; Owner: postgres
--

ALTER TABLE ONLY public.att_deptattrule
    ADD CONSTRAINT att_deptattrule_company_id_420199ab_fk_personnel_company_id FOREIGN KEY (company_id) REFERENCES public.personnel_company(id) DEFERRABLE INITIALLY DEFERRED;


--
-- TOC entry 4435 (class 2606 OID 29092)
-- Name: att_deptattrule att_deptattrule_department_id_f333c8f0_fk_personnel; Type: FK CONSTRAINT; Schema: public; Owner: postgres
--

ALTER TABLE ONLY public.att_deptattrule
    ADD CONSTRAINT att_deptattrule_department_id_f333c8f0_fk_personnel FOREIGN KEY (department_id) REFERENCES public.personnel_department(id) DEFERRABLE INITIALLY DEFERRED;


--
-- TOC entry 4436 (class 2606 OID 29097)
-- Name: att_holiday att_holiday_department_id_fbbbd185_fk_personnel_department_id; Type: FK CONSTRAINT; Schema: public; Owner: postgres
--

ALTER TABLE ONLY public.att_holiday
    ADD CONSTRAINT att_holiday_department_id_fbbbd185_fk_personnel_department_id FOREIGN KEY (department_id) REFERENCES public.personnel_department(id) DEFERRABLE INITIALLY DEFERRED;


--
-- TOC entry 4437 (class 2606 OID 29102)
-- Name: att_leave att_leave_abstractexception_pt_7d182abd_fk_workflow_; Type: FK CONSTRAINT; Schema: public; Owner: postgres
--

ALTER TABLE ONLY public.att_leave
    ADD CONSTRAINT att_leave_abstractexception_pt_7d182abd_fk_workflow_ FOREIGN KEY (abstractexception_ptr_id) REFERENCES public.workflow_abstractexception(id) DEFERRABLE INITIALLY DEFERRED;


--
-- TOC entry 4438 (class 2606 OID 29107)
-- Name: att_leave att_leave_category_id_bbba39ba_fk_att_leavecategory_id; Type: FK CONSTRAINT; Schema: public; Owner: postgres
--

ALTER TABLE ONLY public.att_leave
    ADD CONSTRAINT att_leave_category_id_bbba39ba_fk_att_leavecategory_id FOREIGN KEY (category_id) REFERENCES public.att_leavecategory(id) DEFERRABLE INITIALLY DEFERRED;


--
-- TOC entry 4439 (class 2606 OID 29112)
-- Name: att_leave att_leave_employee_id_bb231627_fk_personnel_employee_id; Type: FK CONSTRAINT; Schema: public; Owner: postgres
--

ALTER TABLE ONLY public.att_leave
    ADD CONSTRAINT att_leave_employee_id_bb231627_fk_personnel_employee_id FOREIGN KEY (employee_id) REFERENCES public.personnel_employee(id) DEFERRABLE INITIALLY DEFERRED;


--
-- TOC entry 4440 (class 2606 OID 29117)
-- Name: att_manuallog att_manuallog_abstractexception_pt_f1e1b292_fk_workflow_; Type: FK CONSTRAINT; Schema: public; Owner: postgres
--

ALTER TABLE ONLY public.att_manuallog
    ADD CONSTRAINT att_manuallog_abstractexception_pt_f1e1b292_fk_workflow_ FOREIGN KEY (abstractexception_ptr_id) REFERENCES public.workflow_abstractexception(id) DEFERRABLE INITIALLY DEFERRED;


--
-- TOC entry 4441 (class 2606 OID 29122)
-- Name: att_manuallog att_manuallog_employee_id_dc8cc2ad_fk_personnel_employee_id; Type: FK CONSTRAINT; Schema: public; Owner: postgres
--

ALTER TABLE ONLY public.att_manuallog
    ADD CONSTRAINT att_manuallog_employee_id_dc8cc2ad_fk_personnel_employee_id FOREIGN KEY (employee_id) REFERENCES public.personnel_employee(id) DEFERRABLE INITIALLY DEFERRED;


--
-- TOC entry 4442 (class 2606 OID 29127)
-- Name: att_overtime att_overtime_abstractexception_pt_94834697_fk_workflow_; Type: FK CONSTRAINT; Schema: public; Owner: postgres
--

ALTER TABLE ONLY public.att_overtime
    ADD CONSTRAINT att_overtime_abstractexception_pt_94834697_fk_workflow_ FOREIGN KEY (abstractexception_ptr_id) REFERENCES public.workflow_abstractexception(id) DEFERRABLE INITIALLY DEFERRED;


--
-- TOC entry 4443 (class 2606 OID 29132)
-- Name: att_overtime att_overtime_employee_id_0c0d39dc_fk_personnel_employee_id; Type: FK CONSTRAINT; Schema: public; Owner: postgres
--

ALTER TABLE ONLY public.att_overtime
    ADD CONSTRAINT att_overtime_employee_id_0c0d39dc_fk_personnel_employee_id FOREIGN KEY (employee_id) REFERENCES public.personnel_employee(id) DEFERRABLE INITIALLY DEFERRED;


--
-- TOC entry 4444 (class 2606 OID 29137)
-- Name: att_payloadbase att_payloadbase_emp_id_2c0f6a7b_fk_personnel_employee_id; Type: FK CONSTRAINT; Schema: public; Owner: postgres
--

ALTER TABLE ONLY public.att_payloadbase
    ADD CONSTRAINT att_payloadbase_emp_id_2c0f6a7b_fk_personnel_employee_id FOREIGN KEY (emp_id) REFERENCES public.personnel_employee(id) DEFERRABLE INITIALLY DEFERRED;


--
-- TOC entry 4445 (class 2606 OID 29142)
-- Name: att_payloadbase att_payloadbase_timetable_id_a389e3d8_fk_att_timeinterval_id; Type: FK CONSTRAINT; Schema: public; Owner: postgres
--

ALTER TABLE ONLY public.att_payloadbase
    ADD CONSTRAINT att_payloadbase_timetable_id_a389e3d8_fk_att_timeinterval_id FOREIGN KEY (timetable_id) REFERENCES public.att_timeinterval(id) DEFERRABLE INITIALLY DEFERRED;


--
-- TOC entry 4446 (class 2606 OID 29147)
-- Name: att_payloadbase att_payloadbase_trans_in_id_3b8fd648_fk_iclock_transaction_id; Type: FK CONSTRAINT; Schema: public; Owner: postgres
--

ALTER TABLE ONLY public.att_payloadbase
    ADD CONSTRAINT att_payloadbase_trans_in_id_3b8fd648_fk_iclock_transaction_id FOREIGN KEY (trans_in_id) REFERENCES public.iclock_transaction(id) DEFERRABLE INITIALLY DEFERRED;


--
-- TOC entry 4447 (class 2606 OID 29152)
-- Name: att_payloadbase att_payloadbase_trans_out_id_ec63bbcc_fk_iclock_transaction_id; Type: FK CONSTRAINT; Schema: public; Owner: postgres
--

ALTER TABLE ONLY public.att_payloadbase
    ADD CONSTRAINT att_payloadbase_trans_out_id_ec63bbcc_fk_iclock_transaction_id FOREIGN KEY (trans_out_id) REFERENCES public.iclock_transaction(id) DEFERRABLE INITIALLY DEFERRED;


--
-- TOC entry 4448 (class 2606 OID 29157)
-- Name: att_payloadexception att_payloadexception_item_id_a08bfe48_fk_att_leave; Type: FK CONSTRAINT; Schema: public; Owner: postgres
--

ALTER TABLE ONLY public.att_payloadexception
    ADD CONSTRAINT att_payloadexception_item_id_a08bfe48_fk_att_leave FOREIGN KEY (item_id) REFERENCES public.att_leave(abstractexception_ptr_id) DEFERRABLE INITIALLY DEFERRED;


--
-- TOC entry 4449 (class 2606 OID 29162)
-- Name: att_payloadmulpunchset att_payloadmulpunchset_emp_id_f47610c8_fk_personnel_employee_id; Type: FK CONSTRAINT; Schema: public; Owner: postgres
--

ALTER TABLE ONLY public.att_payloadmulpunchset
    ADD CONSTRAINT att_payloadmulpunchset_emp_id_f47610c8_fk_personnel_employee_id FOREIGN KEY (emp_id) REFERENCES public.personnel_employee(id) DEFERRABLE INITIALLY DEFERRED;


--
-- TOC entry 4450 (class 2606 OID 29167)
-- Name: att_payloadpunch att_payloadpunch_emp_id_053da2f0_fk_personnel_employee_id; Type: FK CONSTRAINT; Schema: public; Owner: postgres
--

ALTER TABLE ONLY public.att_payloadpunch
    ADD CONSTRAINT att_payloadpunch_emp_id_053da2f0_fk_personnel_employee_id FOREIGN KEY (emp_id) REFERENCES public.personnel_employee(id) DEFERRABLE INITIALLY DEFERRED;


--
-- TOC entry 4451 (class 2606 OID 29172)
-- Name: att_payloadpunch att_payloadpunch_orig_id_16b26416_fk_iclock_transaction_id; Type: FK CONSTRAINT; Schema: public; Owner: postgres
--

ALTER TABLE ONLY public.att_payloadpunch
    ADD CONSTRAINT att_payloadpunch_orig_id_16b26416_fk_iclock_transaction_id FOREIGN KEY (orig_id) REFERENCES public.iclock_transaction(id) DEFERRABLE INITIALLY DEFERRED;


--
-- TOC entry 4452 (class 2606 OID 29177)
-- Name: att_shiftdetail att_shiftdetail_shift_id_7d694501_fk_att_attshift_id; Type: FK CONSTRAINT; Schema: public; Owner: postgres
--

ALTER TABLE ONLY public.att_shiftdetail
    ADD CONSTRAINT att_shiftdetail_shift_id_7d694501_fk_att_attshift_id FOREIGN KEY (shift_id) REFERENCES public.att_attshift(id) DEFERRABLE INITIALLY DEFERRED;


--
-- TOC entry 4453 (class 2606 OID 29182)
-- Name: att_shiftdetail att_shiftdetail_time_interval_id_777dde8f_fk_att_timei; Type: FK CONSTRAINT; Schema: public; Owner: postgres
--

ALTER TABLE ONLY public.att_shiftdetail
    ADD CONSTRAINT att_shiftdetail_time_interval_id_777dde8f_fk_att_timei FOREIGN KEY (time_interval_id) REFERENCES public.att_timeinterval(id) DEFERRABLE INITIALLY DEFERRED;


--
-- TOC entry 4454 (class 2606 OID 29187)
-- Name: att_tempschedule att_tempschedule_employee_id_b89c7e54_fk_personnel_employee_id; Type: FK CONSTRAINT; Schema: public; Owner: postgres
--

ALTER TABLE ONLY public.att_tempschedule
    ADD CONSTRAINT att_tempschedule_employee_id_b89c7e54_fk_personnel_employee_id FOREIGN KEY (employee_id) REFERENCES public.personnel_employee(id) DEFERRABLE INITIALLY DEFERRED;


--
-- TOC entry 4456 (class 2606 OID 29192)
-- Name: att_timeinterval_break_time att_timeinterval_bre_breaktime_id_08462308_fk_att_break; Type: FK CONSTRAINT; Schema: public; Owner: postgres
--

ALTER TABLE ONLY public.att_timeinterval_break_time
    ADD CONSTRAINT att_timeinterval_bre_breaktime_id_08462308_fk_att_break FOREIGN KEY (breaktime_id) REFERENCES public.att_breaktime(id) DEFERRABLE INITIALLY DEFERRED;


--
-- TOC entry 4457 (class 2606 OID 29197)
-- Name: att_timeinterval_break_time att_timeinterval_bre_timeinterval_id_2287017e_fk_att_timei; Type: FK CONSTRAINT; Schema: public; Owner: postgres
--

ALTER TABLE ONLY public.att_timeinterval_break_time
    ADD CONSTRAINT att_timeinterval_bre_timeinterval_id_2287017e_fk_att_timei FOREIGN KEY (timeinterval_id) REFERENCES public.att_timeinterval(id) DEFERRABLE INITIALLY DEFERRED;


--
-- TOC entry 4455 (class 2606 OID 29202)
-- Name: att_timeinterval att_timeinterval_company_id_9824d651_fk_personnel_company_id; Type: FK CONSTRAINT; Schema: public; Owner: postgres
--

ALTER TABLE ONLY public.att_timeinterval
    ADD CONSTRAINT att_timeinterval_company_id_9824d651_fk_personnel_company_id FOREIGN KEY (company_id) REFERENCES public.personnel_company(id) DEFERRABLE INITIALLY DEFERRED;


--
-- TOC entry 4458 (class 2606 OID 29207)
-- Name: att_training att_training_abstractexception_pt_60a3e8f3_fk_workflow_; Type: FK CONSTRAINT; Schema: public; Owner: postgres
--

ALTER TABLE ONLY public.att_training
    ADD CONSTRAINT att_training_abstractexception_pt_60a3e8f3_fk_workflow_ FOREIGN KEY (abstractexception_ptr_id) REFERENCES public.workflow_abstractexception(id) DEFERRABLE INITIALLY DEFERRED;


--
-- TOC entry 4459 (class 2606 OID 29212)
-- Name: att_training att_training_category_id_fb38e891_fk_att_trainingcategory_id; Type: FK CONSTRAINT; Schema: public; Owner: postgres
--

ALTER TABLE ONLY public.att_training
    ADD CONSTRAINT att_training_category_id_fb38e891_fk_att_trainingcategory_id FOREIGN KEY (category_id) REFERENCES public.att_trainingcategory(id) DEFERRABLE INITIALLY DEFERRED;


--
-- TOC entry 4460 (class 2606 OID 29217)
-- Name: att_training att_training_employee_id_44af8319_fk_personnel_employee_id; Type: FK CONSTRAINT; Schema: public; Owner: postgres
--

ALTER TABLE ONLY public.att_training
    ADD CONSTRAINT att_training_employee_id_44af8319_fk_personnel_employee_id FOREIGN KEY (employee_id) REFERENCES public.personnel_employee(id) DEFERRABLE INITIALLY DEFERRED;


--
-- TOC entry 4461 (class 2606 OID 29222)
-- Name: att_vacationemployee att_vacationemployee_employee_id_05793644_fk_personnel; Type: FK CONSTRAINT; Schema: public; Owner: postgres
--

ALTER TABLE ONLY public.att_vacationemployee
    ADD CONSTRAINT att_vacationemployee_employee_id_05793644_fk_personnel FOREIGN KEY (employee_id) REFERENCES public.personnel_employee(id) DEFERRABLE INITIALLY DEFERRED;


--
-- TOC entry 4462 (class 2606 OID 29227)
-- Name: att_vacationemployee att_vacationemployee_leave_id_b127a4fe_fk_att_leave; Type: FK CONSTRAINT; Schema: public; Owner: postgres
--

ALTER TABLE ONLY public.att_vacationemployee
    ADD CONSTRAINT att_vacationemployee_leave_id_b127a4fe_fk_att_leave FOREIGN KEY (leave_id) REFERENCES public.att_leave(abstractexception_ptr_id) DEFERRABLE INITIALLY DEFERRED;


--
-- TOC entry 4463 (class 2606 OID 29232)
-- Name: att_vacationemployee att_vacationemployee_vacation_available_i_04bc7d89_fk_att_vacat; Type: FK CONSTRAINT; Schema: public; Owner: postgres
--

ALTER TABLE ONLY public.att_vacationemployee
    ADD CONSTRAINT att_vacationemployee_vacation_available_i_04bc7d89_fk_att_vacat FOREIGN KEY (vacation_available_id) REFERENCES public.att_vacationtime(id) DEFERRABLE INITIALLY DEFERRED;


--
-- TOC entry 4464 (class 2606 OID 29237)
-- Name: att_vacationtime att_vacationtime_company_id_e885043c_fk_personnel_company_id; Type: FK CONSTRAINT; Schema: public; Owner: postgres
--

ALTER TABLE ONLY public.att_vacationtime
    ADD CONSTRAINT att_vacationtime_company_id_e885043c_fk_personnel_company_id FOREIGN KEY (company_id) REFERENCES public.personnel_company(id) DEFERRABLE INITIALLY DEFERRED;


--
-- TOC entry 4465 (class 2606 OID 29242)
-- Name: att_vacationtimeseniority att_vacationtimeseni_vacation_time_id_803f6e65_fk_att_vacat; Type: FK CONSTRAINT; Schema: public; Owner: postgres
--

ALTER TABLE ONLY public.att_vacationtimeseniority
    ADD CONSTRAINT att_vacationtimeseni_vacation_time_id_803f6e65_fk_att_vacat FOREIGN KEY (vacation_time_id) REFERENCES public.att_vacationtime(id) DEFERRABLE INITIALLY DEFERRED;


--
-- TOC entry 4466 (class 2606 OID 29247)
-- Name: auth_group_permissions auth_group_permissio_permission_id_84c5c92e_fk_auth_perm; Type: FK CONSTRAINT; Schema: public; Owner: postgres
--

ALTER TABLE ONLY public.auth_group_permissions
    ADD CONSTRAINT auth_group_permissio_permission_id_84c5c92e_fk_auth_perm FOREIGN KEY (permission_id) REFERENCES public.auth_permission(id) DEFERRABLE INITIALLY DEFERRED;


--
-- TOC entry 4467 (class 2606 OID 29252)
-- Name: auth_group_permissions auth_group_permissions_group_id_b120cbf9_fk_auth_group_id; Type: FK CONSTRAINT; Schema: public; Owner: postgres
--

ALTER TABLE ONLY public.auth_group_permissions
    ADD CONSTRAINT auth_group_permissions_group_id_b120cbf9_fk_auth_group_id FOREIGN KEY (group_id) REFERENCES public.auth_group(id) DEFERRABLE INITIALLY DEFERRED;


--
-- TOC entry 4468 (class 2606 OID 29257)
-- Name: auth_permission auth_permission_content_type_id_2f476e4b_fk_django_co; Type: FK CONSTRAINT; Schema: public; Owner: postgres
--

ALTER TABLE ONLY public.auth_permission
    ADD CONSTRAINT auth_permission_content_type_id_2f476e4b_fk_django_co FOREIGN KEY (content_type_id) REFERENCES public.django_content_type(id) DEFERRABLE INITIALLY DEFERRED;


--
-- TOC entry 4470 (class 2606 OID 29262)
-- Name: auth_user_auth_area auth_user_auth_area_area_id_d1e54c70_fk_personnel_area_id; Type: FK CONSTRAINT; Schema: public; Owner: postgres
--

ALTER TABLE ONLY public.auth_user_auth_area
    ADD CONSTRAINT auth_user_auth_area_area_id_d1e54c70_fk_personnel_area_id FOREIGN KEY (area_id) REFERENCES public.personnel_area(id) DEFERRABLE INITIALLY DEFERRED;


--
-- TOC entry 4471 (class 2606 OID 29267)
-- Name: auth_user_auth_area auth_user_auth_area_myuser_id_5fb9a803_fk_auth_user_id; Type: FK CONSTRAINT; Schema: public; Owner: postgres
--

ALTER TABLE ONLY public.auth_user_auth_area
    ADD CONSTRAINT auth_user_auth_area_myuser_id_5fb9a803_fk_auth_user_id FOREIGN KEY (myuser_id) REFERENCES public.auth_user(id) DEFERRABLE INITIALLY DEFERRED;


--
-- TOC entry 4469 (class 2606 OID 29272)
-- Name: auth_user auth_user_auth_company_id_30b74281_fk_personnel_company_id; Type: FK CONSTRAINT; Schema: public; Owner: postgres
--

ALTER TABLE ONLY public.auth_user
    ADD CONSTRAINT auth_user_auth_company_id_30b74281_fk_personnel_company_id FOREIGN KEY (auth_company_id) REFERENCES public.personnel_company(id) DEFERRABLE INITIALLY DEFERRED;


--
-- TOC entry 4472 (class 2606 OID 29277)
-- Name: auth_user_auth_dept auth_user_auth_dept_department_id_5866c514_fk_personnel; Type: FK CONSTRAINT; Schema: public; Owner: postgres
--

ALTER TABLE ONLY public.auth_user_auth_dept
    ADD CONSTRAINT auth_user_auth_dept_department_id_5866c514_fk_personnel FOREIGN KEY (department_id) REFERENCES public.personnel_department(id) DEFERRABLE INITIALLY DEFERRED;


--
-- TOC entry 4473 (class 2606 OID 29282)
-- Name: auth_user_auth_dept auth_user_auth_dept_myuser_id_18a51b27_fk_auth_user_id; Type: FK CONSTRAINT; Schema: public; Owner: postgres
--

ALTER TABLE ONLY public.auth_user_auth_dept
    ADD CONSTRAINT auth_user_auth_dept_myuser_id_18a51b27_fk_auth_user_id FOREIGN KEY (myuser_id) REFERENCES public.auth_user(id) DEFERRABLE INITIALLY DEFERRED;


--
-- TOC entry 4474 (class 2606 OID 29287)
-- Name: auth_user_groups auth_user_groups_group_id_97559544_fk_auth_group_id; Type: FK CONSTRAINT; Schema: public; Owner: postgres
--

ALTER TABLE ONLY public.auth_user_groups
    ADD CONSTRAINT auth_user_groups_group_id_97559544_fk_auth_group_id FOREIGN KEY (group_id) REFERENCES public.auth_group(id) DEFERRABLE INITIALLY DEFERRED;


--
-- TOC entry 4475 (class 2606 OID 29292)
-- Name: auth_user_groups auth_user_groups_myuser_id_d03e8dcc_fk_auth_user_id; Type: FK CONSTRAINT; Schema: public; Owner: postgres
--

ALTER TABLE ONLY public.auth_user_groups
    ADD CONSTRAINT auth_user_groups_myuser_id_d03e8dcc_fk_auth_user_id FOREIGN KEY (myuser_id) REFERENCES public.auth_user(id) DEFERRABLE INITIALLY DEFERRED;


--
-- TOC entry 4476 (class 2606 OID 29297)
-- Name: auth_user_profile auth_user_profile_user_id_f9aded29_fk_auth_user_id; Type: FK CONSTRAINT; Schema: public; Owner: postgres
--

ALTER TABLE ONLY public.auth_user_profile
    ADD CONSTRAINT auth_user_profile_user_id_f9aded29_fk_auth_user_id FOREIGN KEY (user_id) REFERENCES public.auth_user(id) DEFERRABLE INITIALLY DEFERRED;


--
-- TOC entry 4477 (class 2606 OID 29302)
-- Name: auth_user_user_permissions auth_user_user_permi_permission_id_1fbb5f2c_fk_auth_perm; Type: FK CONSTRAINT; Schema: public; Owner: postgres
--

ALTER TABLE ONLY public.auth_user_user_permissions
    ADD CONSTRAINT auth_user_user_permi_permission_id_1fbb5f2c_fk_auth_perm FOREIGN KEY (permission_id) REFERENCES public.auth_permission(id) DEFERRABLE INITIALLY DEFERRED;


--
-- TOC entry 4478 (class 2606 OID 29307)
-- Name: auth_user_user_permissions auth_user_user_permissions_myuser_id_679b1527_fk_auth_user_id; Type: FK CONSTRAINT; Schema: public; Owner: postgres
--

ALTER TABLE ONLY public.auth_user_user_permissions
    ADD CONSTRAINT auth_user_user_permissions_myuser_id_679b1527_fk_auth_user_id FOREIGN KEY (myuser_id) REFERENCES public.auth_user(id) DEFERRABLE INITIALLY DEFERRED;


--
-- TOC entry 4479 (class 2606 OID 29312)
-- Name: authtoken_token authtoken_token_user_id_35299eff_fk_auth_user_id; Type: FK CONSTRAINT; Schema: public; Owner: postgres
--

ALTER TABLE ONLY public.authtoken_token
    ADD CONSTRAINT authtoken_token_user_id_35299eff_fk_auth_user_id FOREIGN KEY (user_id) REFERENCES public.auth_user(id) DEFERRABLE INITIALLY DEFERRED;


--
-- TOC entry 4480 (class 2606 OID 29317)
-- Name: base_adminlog base_adminlog_content_type_id_3e553c30_fk_django_co; Type: FK CONSTRAINT; Schema: public; Owner: postgres
--

ALTER TABLE ONLY public.base_adminlog
    ADD CONSTRAINT base_adminlog_content_type_id_3e553c30_fk_django_co FOREIGN KEY (content_type_id) REFERENCES public.django_content_type(id) DEFERRABLE INITIALLY DEFERRED;


--
-- TOC entry 4481 (class 2606 OID 29322)
-- Name: base_adminlog base_adminlog_user_id_ecf659f8_fk_auth_user_id; Type: FK CONSTRAINT; Schema: public; Owner: postgres
--

ALTER TABLE ONLY public.base_adminlog
    ADD CONSTRAINT base_adminlog_user_id_ecf659f8_fk_auth_user_id FOREIGN KEY (user_id) REFERENCES public.auth_user(id) DEFERRABLE INITIALLY DEFERRED;


--
-- TOC entry 4482 (class 2606 OID 29327)
-- Name: base_bookmark base_bookmark_content_type_id_b6a0e799_fk_django_co; Type: FK CONSTRAINT; Schema: public; Owner: postgres
--

ALTER TABLE ONLY public.base_bookmark
    ADD CONSTRAINT base_bookmark_content_type_id_b6a0e799_fk_django_co FOREIGN KEY (content_type_id) REFERENCES public.django_content_type(id) DEFERRABLE INITIALLY DEFERRED;


--
-- TOC entry 4483 (class 2606 OID 29332)
-- Name: base_bookmark base_bookmark_user_id_5f2d5ca2_fk_auth_user_id; Type: FK CONSTRAINT; Schema: public; Owner: postgres
--

ALTER TABLE ONLY public.base_bookmark
    ADD CONSTRAINT base_bookmark_user_id_5f2d5ca2_fk_auth_user_id FOREIGN KEY (user_id) REFERENCES public.auth_user(id) DEFERRABLE INITIALLY DEFERRED;


--
-- TOC entry 4486 (class 2606 OID 29337)
-- Name: base_departmentalert_department base_departmentalert_department_id_33b76e92_fk_personnel; Type: FK CONSTRAINT; Schema: public; Owner: postgres
--

ALTER TABLE ONLY public.base_departmentalert_department
    ADD CONSTRAINT base_departmentalert_department_id_33b76e92_fk_personnel FOREIGN KEY (department_id) REFERENCES public.personnel_department(id) DEFERRABLE INITIALLY DEFERRED;


--
-- TOC entry 4487 (class 2606 OID 29342)
-- Name: base_departmentalert_department base_departmentalert_departmentalert_id_79d27d1d_fk_base_depa; Type: FK CONSTRAINT; Schema: public; Owner: postgres
--

ALTER TABLE ONLY public.base_departmentalert_department
    ADD CONSTRAINT base_departmentalert_departmentalert_id_79d27d1d_fk_base_depa FOREIGN KEY (departmentalert_id) REFERENCES public.base_departmentalert(personalalert_ptr_id) DEFERRABLE INITIALLY DEFERRED;


--
-- TOC entry 4484 (class 2606 OID 44213)
-- Name: base_departmentalert base_departmentalert_emplist_id_b3f5ef6d_fk_personnel; Type: FK CONSTRAINT; Schema: public; Owner: postgres
--

ALTER TABLE ONLY public.base_departmentalert
    ADD CONSTRAINT base_departmentalert_emplist_id_b3f5ef6d_fk_personnel FOREIGN KEY (emplist_id) REFERENCES public.personnel_employee(id) DEFERRABLE INITIALLY DEFERRED;


--
-- TOC entry 4485 (class 2606 OID 29352)
-- Name: base_departmentalert base_departmentalert_personalalert_ptr_id_d1912ed0_fk_base_pers; Type: FK CONSTRAINT; Schema: public; Owner: postgres
--

ALTER TABLE ONLY public.base_departmentalert
    ADD CONSTRAINT base_departmentalert_personalalert_ptr_id_d1912ed0_fk_base_pers FOREIGN KEY (personalalert_ptr_id) REFERENCES public.base_personalalert(id) DEFERRABLE INITIALLY DEFERRED;


--
-- TOC entry 4585 (class 2606 OID 44181)
-- Name: base_messengersentlog base_messengersentlo_content_type_id_e6e9b3d5_fk_django_co; Type: FK CONSTRAINT; Schema: public; Owner: postgres
--

ALTER TABLE ONLY public.base_messengersentlog
    ADD CONSTRAINT base_messengersentlo_content_type_id_e6e9b3d5_fk_django_co FOREIGN KEY (content_type_id) REFERENCES public.django_content_type(id) DEFERRABLE INITIALLY DEFERRED;


--
-- TOC entry 4586 (class 2606 OID 44204)
-- Name: base_messengersentlog base_messengersentlog_emp_id_44eba15e_fk_personnel_employee_id; Type: FK CONSTRAINT; Schema: public; Owner: postgres
--

ALTER TABLE ONLY public.base_messengersentlog
    ADD CONSTRAINT base_messengersentlog_emp_id_44eba15e_fk_personnel_employee_id FOREIGN KEY (emp_id) REFERENCES public.personnel_employee(id) DEFERRABLE INITIALLY DEFERRED;


--
-- TOC entry 4587 (class 2606 OID 44186)
-- Name: base_messengersentlog base_messengersentlog_user_id_64034c70_fk_auth_user_id; Type: FK CONSTRAINT; Schema: public; Owner: postgres
--

ALTER TABLE ONLY public.base_messengersentlog
    ADD CONSTRAINT base_messengersentlog_user_id_64034c70_fk_auth_user_id FOREIGN KEY (user_id) REFERENCES public.auth_user(id) DEFERRABLE INITIALLY DEFERRED;


--
-- TOC entry 4583 (class 2606 OID 44161)
-- Name: base_personalalert_employee base_personalalert_e_employee_id_94832616_fk_personnel; Type: FK CONSTRAINT; Schema: public; Owner: postgres
--

ALTER TABLE ONLY public.base_personalalert_employee
    ADD CONSTRAINT base_personalalert_e_employee_id_94832616_fk_personnel FOREIGN KEY (employee_id) REFERENCES public.personnel_employee(id) DEFERRABLE INITIALLY DEFERRED;


--
-- TOC entry 4584 (class 2606 OID 44156)
-- Name: base_personalalert_employee base_personalalert_e_personalalert_id_27743165_fk_base_pers; Type: FK CONSTRAINT; Schema: public; Owner: postgres
--

ALTER TABLE ONLY public.base_personalalert_employee
    ADD CONSTRAINT base_personalalert_e_personalalert_id_27743165_fk_base_pers FOREIGN KEY (personalalert_id) REFERENCES public.base_personalalert(id) DEFERRABLE INITIALLY DEFERRED;


--
-- TOC entry 4488 (class 2606 OID 29367)
-- Name: django_admin_log django_admin_log_content_type_id_c4bce8eb_fk_django_co; Type: FK CONSTRAINT; Schema: public; Owner: postgres
--

ALTER TABLE ONLY public.django_admin_log
    ADD CONSTRAINT django_admin_log_content_type_id_c4bce8eb_fk_django_co FOREIGN KEY (content_type_id) REFERENCES public.django_content_type(id) DEFERRABLE INITIALLY DEFERRED;


--
-- TOC entry 4489 (class 2606 OID 29372)
-- Name: django_admin_log django_admin_log_user_id_c564eba6_fk_auth_user_id; Type: FK CONSTRAINT; Schema: public; Owner: postgres
--

ALTER TABLE ONLY public.django_admin_log
    ADD CONSTRAINT django_admin_log_user_id_c564eba6_fk_auth_user_id FOREIGN KEY (user_id) REFERENCES public.auth_user(id) DEFERRABLE INITIALLY DEFERRED;


--
-- TOC entry 4490 (class 2606 OID 29377)
-- Name: djcelery_periodictask djcelery_periodictas_crontab_id_75609bab_fk_djcelery_; Type: FK CONSTRAINT; Schema: public; Owner: postgres
--

ALTER TABLE ONLY public.djcelery_periodictask
    ADD CONSTRAINT djcelery_periodictas_crontab_id_75609bab_fk_djcelery_ FOREIGN KEY (crontab_id) REFERENCES public.djcelery_crontabschedule(id) DEFERRABLE INITIALLY DEFERRED;


--
-- TOC entry 4491 (class 2606 OID 29382)
-- Name: djcelery_periodictask djcelery_periodictas_interval_id_b426ab02_fk_djcelery_; Type: FK CONSTRAINT; Schema: public; Owner: postgres
--

ALTER TABLE ONLY public.djcelery_periodictask
    ADD CONSTRAINT djcelery_periodictas_interval_id_b426ab02_fk_djcelery_ FOREIGN KEY (interval_id) REFERENCES public.djcelery_intervalschedule(id) DEFERRABLE INITIALLY DEFERRED;


--
-- TOC entry 4492 (class 2606 OID 29387)
-- Name: djcelery_taskstate djcelery_taskstate_worker_id_f7f57a05_fk_djcelery_; Type: FK CONSTRAINT; Schema: public; Owner: postgres
--

ALTER TABLE ONLY public.djcelery_taskstate
    ADD CONSTRAINT djcelery_taskstate_worker_id_f7f57a05_fk_djcelery_ FOREIGN KEY (worker_id) REFERENCES public.djcelery_workerstate(id) DEFERRABLE INITIALLY DEFERRED;


--
-- TOC entry 4493 (class 2606 OID 29392)
-- Name: ep_eptransaction ep_eptransaction_emp_id_1006883f_fk_personnel_employee_id; Type: FK CONSTRAINT; Schema: public; Owner: postgres
--

ALTER TABLE ONLY public.ep_eptransaction
    ADD CONSTRAINT ep_eptransaction_emp_id_1006883f_fk_personnel_employee_id FOREIGN KEY (emp_id) REFERENCES public.personnel_employee(id) DEFERRABLE INITIALLY DEFERRED;


--
-- TOC entry 4494 (class 2606 OID 29397)
-- Name: ep_eptransaction ep_eptransaction_terminal_id_4490b209_fk_iclock_terminal_id; Type: FK CONSTRAINT; Schema: public; Owner: postgres
--

ALTER TABLE ONLY public.ep_eptransaction
    ADD CONSTRAINT ep_eptransaction_terminal_id_4490b209_fk_iclock_terminal_id FOREIGN KEY (terminal_id) REFERENCES public.iclock_terminal(id) DEFERRABLE INITIALLY DEFERRED;


--
-- TOC entry 4495 (class 2606 OID 29402)
-- Name: guardian_groupobjectpermission guardian_groupobject_content_type_id_7ade36b8_fk_django_co; Type: FK CONSTRAINT; Schema: public; Owner: postgres
--

ALTER TABLE ONLY public.guardian_groupobjectpermission
    ADD CONSTRAINT guardian_groupobject_content_type_id_7ade36b8_fk_django_co FOREIGN KEY (content_type_id) REFERENCES public.django_content_type(id) DEFERRABLE INITIALLY DEFERRED;


--
-- TOC entry 4496 (class 2606 OID 29407)
-- Name: guardian_groupobjectpermission guardian_groupobject_group_id_4bbbfb62_fk_auth_grou; Type: FK CONSTRAINT; Schema: public; Owner: postgres
--

ALTER TABLE ONLY public.guardian_groupobjectpermission
    ADD CONSTRAINT guardian_groupobject_group_id_4bbbfb62_fk_auth_grou FOREIGN KEY (group_id) REFERENCES public.auth_group(id) DEFERRABLE INITIALLY DEFERRED;


--
-- TOC entry 4497 (class 2606 OID 29412)
-- Name: guardian_groupobjectpermission guardian_groupobject_permission_id_36572738_fk_auth_perm; Type: FK CONSTRAINT; Schema: public; Owner: postgres
--

ALTER TABLE ONLY public.guardian_groupobjectpermission
    ADD CONSTRAINT guardian_groupobject_permission_id_36572738_fk_auth_perm FOREIGN KEY (permission_id) REFERENCES public.auth_permission(id) DEFERRABLE INITIALLY DEFERRED;


--
-- TOC entry 4498 (class 2606 OID 29417)
-- Name: guardian_userobjectpermission guardian_userobjectp_content_type_id_2e892405_fk_django_co; Type: FK CONSTRAINT; Schema: public; Owner: postgres
--

ALTER TABLE ONLY public.guardian_userobjectpermission
    ADD CONSTRAINT guardian_userobjectp_content_type_id_2e892405_fk_django_co FOREIGN KEY (content_type_id) REFERENCES public.django_content_type(id) DEFERRABLE INITIALLY DEFERRED;


--
-- TOC entry 4499 (class 2606 OID 29422)
-- Name: guardian_userobjectpermission guardian_userobjectp_permission_id_71807bfc_fk_auth_perm; Type: FK CONSTRAINT; Schema: public; Owner: postgres
--

ALTER TABLE ONLY public.guardian_userobjectpermission
    ADD CONSTRAINT guardian_userobjectp_permission_id_71807bfc_fk_auth_perm FOREIGN KEY (permission_id) REFERENCES public.auth_permission(id) DEFERRABLE INITIALLY DEFERRED;


--
-- TOC entry 4500 (class 2606 OID 29427)
-- Name: guardian_userobjectpermission guardian_userobjectpermission_user_id_d5c1e964_fk_auth_user_id; Type: FK CONSTRAINT; Schema: public; Owner: postgres
--

ALTER TABLE ONLY public.guardian_userobjectpermission
    ADD CONSTRAINT guardian_userobjectpermission_user_id_d5c1e964_fk_auth_user_id FOREIGN KEY (user_id) REFERENCES public.auth_user(id) DEFERRABLE INITIALLY DEFERRED;


--
-- TOC entry 4501 (class 2606 OID 29432)
-- Name: iclock_biodata iclock_biodata_employee_id_ff748ea7_fk_personnel_employee_id; Type: FK CONSTRAINT; Schema: public; Owner: postgres
--

ALTER TABLE ONLY public.iclock_biodata
    ADD CONSTRAINT iclock_biodata_employee_id_ff748ea7_fk_personnel_employee_id FOREIGN KEY (employee_id) REFERENCES public.personnel_employee(id) DEFERRABLE INITIALLY DEFERRED;


--
-- TOC entry 4502 (class 2606 OID 29437)
-- Name: iclock_biophoto iclock_biophoto_employee_id_3dba5819_fk_personnel_employee_id; Type: FK CONSTRAINT; Schema: public; Owner: postgres
--

ALTER TABLE ONLY public.iclock_biophoto
    ADD CONSTRAINT iclock_biophoto_employee_id_3dba5819_fk_personnel_employee_id FOREIGN KEY (employee_id) REFERENCES public.personnel_employee(id) DEFERRABLE INITIALLY DEFERRED;


--
-- TOC entry 4503 (class 2606 OID 29442)
-- Name: iclock_errorcommandlog iclock_errorcommandl_terminal_id_3b2d7cbd_fk_iclock_te; Type: FK CONSTRAINT; Schema: public; Owner: postgres
--

ALTER TABLE ONLY public.iclock_errorcommandlog
    ADD CONSTRAINT iclock_errorcommandl_terminal_id_3b2d7cbd_fk_iclock_te FOREIGN KEY (terminal_id) REFERENCES public.iclock_terminal(id) DEFERRABLE INITIALLY DEFERRED;


--
-- TOC entry 4504 (class 2606 OID 29447)
-- Name: iclock_privatemessage iclock_privatemessag_employee_id_e84a34c0_fk_personnel; Type: FK CONSTRAINT; Schema: public; Owner: postgres
--

ALTER TABLE ONLY public.iclock_privatemessage
    ADD CONSTRAINT iclock_privatemessag_employee_id_e84a34c0_fk_personnel FOREIGN KEY (employee_id) REFERENCES public.personnel_employee(id) DEFERRABLE INITIALLY DEFERRED;


--
-- TOC entry 4505 (class 2606 OID 29452)
-- Name: iclock_publicmessage iclock_publicmessage_terminal_id_c3b5e4cf_fk_iclock_terminal_id; Type: FK CONSTRAINT; Schema: public; Owner: postgres
--

ALTER TABLE ONLY public.iclock_publicmessage
    ADD CONSTRAINT iclock_publicmessage_terminal_id_c3b5e4cf_fk_iclock_terminal_id FOREIGN KEY (terminal_id) REFERENCES public.iclock_terminal(id) DEFERRABLE INITIALLY DEFERRED;


--
-- TOC entry 4506 (class 2606 OID 29457)
-- Name: iclock_terminal iclock_terminal_area_id_c019c6f0_fk_personnel_area_id; Type: FK CONSTRAINT; Schema: public; Owner: postgres
--

ALTER TABLE ONLY public.iclock_terminal
    ADD CONSTRAINT iclock_terminal_area_id_c019c6f0_fk_personnel_area_id FOREIGN KEY (area_id) REFERENCES public.personnel_area(id) DEFERRABLE INITIALLY DEFERRED;


--
-- TOC entry 4507 (class 2606 OID 29462)
-- Name: iclock_terminal iclock_terminal_company_id_f2ecaaba_fk_personnel_company_id; Type: FK CONSTRAINT; Schema: public; Owner: postgres
--

ALTER TABLE ONLY public.iclock_terminal
    ADD CONSTRAINT iclock_terminal_company_id_f2ecaaba_fk_personnel_company_id FOREIGN KEY (company_id) REFERENCES public.personnel_company(id) DEFERRABLE INITIALLY DEFERRED;


--
-- TOC entry 4509 (class 2606 OID 29467)
-- Name: iclock_terminalcommandlog iclock_terminalcomma_terminal_id_35ea8b2b_fk_iclock_te; Type: FK CONSTRAINT; Schema: public; Owner: postgres
--

ALTER TABLE ONLY public.iclock_terminalcommandlog
    ADD CONSTRAINT iclock_terminalcomma_terminal_id_35ea8b2b_fk_iclock_te FOREIGN KEY (terminal_id) REFERENCES public.iclock_terminal(id) DEFERRABLE INITIALLY DEFERRED;


--
-- TOC entry 4508 (class 2606 OID 29472)
-- Name: iclock_terminalcommand iclock_terminalcomma_terminal_id_3dcf836f_fk_iclock_te; Type: FK CONSTRAINT; Schema: public; Owner: postgres
--

ALTER TABLE ONLY public.iclock_terminalcommand
    ADD CONSTRAINT iclock_terminalcomma_terminal_id_3dcf836f_fk_iclock_te FOREIGN KEY (terminal_id) REFERENCES public.iclock_terminal(id) DEFERRABLE INITIALLY DEFERRED;


--
-- TOC entry 4510 (class 2606 OID 29477)
-- Name: iclock_terminallog iclock_terminallog_terminal_id_667b3ea7_fk_iclock_terminal_id; Type: FK CONSTRAINT; Schema: public; Owner: postgres
--

ALTER TABLE ONLY public.iclock_terminallog
    ADD CONSTRAINT iclock_terminallog_terminal_id_667b3ea7_fk_iclock_terminal_id FOREIGN KEY (terminal_id) REFERENCES public.iclock_terminal(id) DEFERRABLE INITIALLY DEFERRED;


--
-- TOC entry 4511 (class 2606 OID 29482)
-- Name: iclock_terminalparameter iclock_terminalparam_terminal_id_443872e3_fk_iclock_te; Type: FK CONSTRAINT; Schema: public; Owner: postgres
--

ALTER TABLE ONLY public.iclock_terminalparameter
    ADD CONSTRAINT iclock_terminalparam_terminal_id_443872e3_fk_iclock_te FOREIGN KEY (terminal_id) REFERENCES public.iclock_terminal(id) DEFERRABLE INITIALLY DEFERRED;


--
-- TOC entry 4512 (class 2606 OID 29487)
-- Name: iclock_terminaluploadlog iclock_terminaluploa_terminal_id_9c9a7664_fk_iclock_te; Type: FK CONSTRAINT; Schema: public; Owner: postgres
--

ALTER TABLE ONLY public.iclock_terminaluploadlog
    ADD CONSTRAINT iclock_terminaluploa_terminal_id_9c9a7664_fk_iclock_te FOREIGN KEY (terminal_id) REFERENCES public.iclock_terminal(id) DEFERRABLE INITIALLY DEFERRED;


--
-- TOC entry 4513 (class 2606 OID 29492)
-- Name: iclock_transaction iclock_transaction_emp_id_60fa3521_fk_personnel_employee_id; Type: FK CONSTRAINT; Schema: public; Owner: postgres
--

ALTER TABLE ONLY public.iclock_transaction
    ADD CONSTRAINT iclock_transaction_emp_id_60fa3521_fk_personnel_employee_id FOREIGN KEY (emp_id) REFERENCES public.personnel_employee(id) DEFERRABLE INITIALLY DEFERRED;


--
-- TOC entry 4514 (class 2606 OID 29497)
-- Name: iclock_transaction iclock_transaction_terminal_id_451c81c2_fk_iclock_terminal_id; Type: FK CONSTRAINT; Schema: public; Owner: postgres
--

ALTER TABLE ONLY public.iclock_transaction
    ADD CONSTRAINT iclock_transaction_terminal_id_451c81c2_fk_iclock_terminal_id FOREIGN KEY (terminal_id) REFERENCES public.iclock_terminal(id) DEFERRABLE INITIALLY DEFERRED;


--
-- TOC entry 4515 (class 2606 OID 29502)
-- Name: iclock_transactionproofcmd iclock_transactionpr_terminal_id_08b81e1e_fk_iclock_te; Type: FK CONSTRAINT; Schema: public; Owner: postgres
--

ALTER TABLE ONLY public.iclock_transactionproofcmd
    ADD CONSTRAINT iclock_transactionpr_terminal_id_08b81e1e_fk_iclock_te FOREIGN KEY (terminal_id) REFERENCES public.iclock_terminal(id) DEFERRABLE INITIALLY DEFERRED;


--
-- TOC entry 4516 (class 2606 OID 29507)
-- Name: mobile_announcement mobile_announcement_receiver_id_ddf2a860_fk_personnel; Type: FK CONSTRAINT; Schema: public; Owner: postgres
--

ALTER TABLE ONLY public.mobile_announcement
    ADD CONSTRAINT mobile_announcement_receiver_id_ddf2a860_fk_personnel FOREIGN KEY (receiver_id) REFERENCES public.personnel_employee(id) DEFERRABLE INITIALLY DEFERRED;


--
-- TOC entry 4517 (class 2606 OID 29512)
-- Name: mobile_appnotification mobile_appnotificati_receiver_id_90c4a355_fk_personnel; Type: FK CONSTRAINT; Schema: public; Owner: postgres
--

ALTER TABLE ONLY public.mobile_appnotification
    ADD CONSTRAINT mobile_appnotificati_receiver_id_90c4a355_fk_personnel FOREIGN KEY (receiver_id) REFERENCES public.personnel_employee(id) DEFERRABLE INITIALLY DEFERRED;


--
-- TOC entry 4518 (class 2606 OID 29517)
-- Name: mobile_gpsfordepartment mobile_gpsfordepartm_department_id_988ccf22_fk_personnel; Type: FK CONSTRAINT; Schema: public; Owner: postgres
--

ALTER TABLE ONLY public.mobile_gpsfordepartment
    ADD CONSTRAINT mobile_gpsfordepartm_department_id_988ccf22_fk_personnel FOREIGN KEY (department_id) REFERENCES public.personnel_department(id) DEFERRABLE INITIALLY DEFERRED;


--
-- TOC entry 4519 (class 2606 OID 29522)
-- Name: mobile_gpsforemployee mobile_gpsforemploye_employee_id_982b7cef_fk_personnel; Type: FK CONSTRAINT; Schema: public; Owner: postgres
--

ALTER TABLE ONLY public.mobile_gpsforemployee
    ADD CONSTRAINT mobile_gpsforemploye_employee_id_982b7cef_fk_personnel FOREIGN KEY (employee_id) REFERENCES public.personnel_employee(id) DEFERRABLE INITIALLY DEFERRED;


--
-- TOC entry 4520 (class 2606 OID 29527)
-- Name: payroll_emploan payroll_emploan_employee_id_97a251ef_fk_personnel_employee_id; Type: FK CONSTRAINT; Schema: public; Owner: postgres
--

ALTER TABLE ONLY public.payroll_emploan
    ADD CONSTRAINT payroll_emploan_employee_id_97a251ef_fk_personnel_employee_id FOREIGN KEY (employee_id) REFERENCES public.personnel_employee(id) DEFERRABLE INITIALLY DEFERRED;


--
-- TOC entry 4521 (class 2606 OID 29532)
-- Name: payroll_emppayrollprofile payroll_emppayrollpr_employee_id_6c97078c_fk_personnel; Type: FK CONSTRAINT; Schema: public; Owner: postgres
--

ALTER TABLE ONLY public.payroll_emppayrollprofile
    ADD CONSTRAINT payroll_emppayrollpr_employee_id_6c97078c_fk_personnel FOREIGN KEY (employee_id) REFERENCES public.personnel_employee(id) DEFERRABLE INITIALLY DEFERRED;


--
-- TOC entry 4522 (class 2606 OID 29537)
-- Name: payroll_extradeduction payroll_extradeducti_employee_id_53072441_fk_personnel; Type: FK CONSTRAINT; Schema: public; Owner: postgres
--

ALTER TABLE ONLY public.payroll_extradeduction
    ADD CONSTRAINT payroll_extradeducti_employee_id_53072441_fk_personnel FOREIGN KEY (employee_id) REFERENCES public.personnel_employee(id) DEFERRABLE INITIALLY DEFERRED;


--
-- TOC entry 4523 (class 2606 OID 29542)
-- Name: payroll_extraincrease payroll_extraincreas_employee_id_f902e6bb_fk_personnel; Type: FK CONSTRAINT; Schema: public; Owner: postgres
--

ALTER TABLE ONLY public.payroll_extraincrease
    ADD CONSTRAINT payroll_extraincreas_employee_id_f902e6bb_fk_personnel FOREIGN KEY (employee_id) REFERENCES public.personnel_employee(id) DEFERRABLE INITIALLY DEFERRED;


--
-- TOC entry 4524 (class 2606 OID 29547)
-- Name: payroll_leaveformula payroll_leaveformula_category_id_945b2054_fk_att_leave; Type: FK CONSTRAINT; Schema: public; Owner: postgres
--

ALTER TABLE ONLY public.payroll_leaveformula
    ADD CONSTRAINT payroll_leaveformula_category_id_945b2054_fk_att_leave FOREIGN KEY (category_id) REFERENCES public.att_leavecategory(id) DEFERRABLE INITIALLY DEFERRED;


--
-- TOC entry 4525 (class 2606 OID 29552)
-- Name: payroll_monthlysalary payroll_monthlysalar_employee_id_97fdc6a9_fk_personnel; Type: FK CONSTRAINT; Schema: public; Owner: postgres
--

ALTER TABLE ONLY public.payroll_monthlysalary
    ADD CONSTRAINT payroll_monthlysalar_employee_id_97fdc6a9_fk_personnel FOREIGN KEY (employee_id) REFERENCES public.personnel_employee(id) DEFERRABLE INITIALLY DEFERRED;


--
-- TOC entry 4526 (class 2606 OID 29557)
-- Name: payroll_reimbursement payroll_reimbursemen_employee_id_c4bbde36_fk_personnel; Type: FK CONSTRAINT; Schema: public; Owner: postgres
--

ALTER TABLE ONLY public.payroll_reimbursement
    ADD CONSTRAINT payroll_reimbursemen_employee_id_c4bbde36_fk_personnel FOREIGN KEY (employee_id) REFERENCES public.personnel_employee(id) DEFERRABLE INITIALLY DEFERRED;


--
-- TOC entry 4527 (class 2606 OID 29562)
-- Name: payroll_salaryadvance payroll_salaryadvanc_employee_id_2abd43e5_fk_personnel; Type: FK CONSTRAINT; Schema: public; Owner: postgres
--

ALTER TABLE ONLY public.payroll_salaryadvance
    ADD CONSTRAINT payroll_salaryadvanc_employee_id_2abd43e5_fk_personnel FOREIGN KEY (employee_id) REFERENCES public.personnel_employee(id) DEFERRABLE INITIALLY DEFERRED;


--
-- TOC entry 4529 (class 2606 OID 29567)
-- Name: payroll_salarystructure_deductionformula payroll_salarystruct_deductionformula_id_b174d5b6_fk_payroll_d; Type: FK CONSTRAINT; Schema: public; Owner: postgres
--

ALTER TABLE ONLY public.payroll_salarystructure_deductionformula
    ADD CONSTRAINT payroll_salarystruct_deductionformula_id_b174d5b6_fk_payroll_d FOREIGN KEY (deductionformula_id) REFERENCES public.payroll_deductionformula(id) DEFERRABLE INITIALLY DEFERRED;


--
-- TOC entry 4528 (class 2606 OID 29572)
-- Name: payroll_salarystructure payroll_salarystruct_employee_id_98996e15_fk_personnel; Type: FK CONSTRAINT; Schema: public; Owner: postgres
--

ALTER TABLE ONLY public.payroll_salarystructure
    ADD CONSTRAINT payroll_salarystruct_employee_id_98996e15_fk_personnel FOREIGN KEY (employee_id) REFERENCES public.personnel_employee(id) DEFERRABLE INITIALLY DEFERRED;


--
-- TOC entry 4531 (class 2606 OID 29577)
-- Name: payroll_salarystructure_exceptionformula payroll_salarystruct_exceptionformula_id_8f6dadb3_fk_payroll_e; Type: FK CONSTRAINT; Schema: public; Owner: postgres
--

ALTER TABLE ONLY public.payroll_salarystructure_exceptionformula
    ADD CONSTRAINT payroll_salarystruct_exceptionformula_id_8f6dadb3_fk_payroll_e FOREIGN KEY (exceptionformula_id) REFERENCES public.payroll_exceptionformula(id) DEFERRABLE INITIALLY DEFERRED;


--
-- TOC entry 4533 (class 2606 OID 29582)
-- Name: payroll_salarystructure_increasementformula payroll_salarystruct_increasementformula__3cd77082_fk_payroll_i; Type: FK CONSTRAINT; Schema: public; Owner: postgres
--

ALTER TABLE ONLY public.payroll_salarystructure_increasementformula
    ADD CONSTRAINT payroll_salarystruct_increasementformula__3cd77082_fk_payroll_i FOREIGN KEY (increasementformula_id) REFERENCES public.payroll_increasementformula(id) DEFERRABLE INITIALLY DEFERRED;


--
-- TOC entry 4535 (class 2606 OID 29587)
-- Name: payroll_salarystructure_leaveformula payroll_salarystruct_leaveformula_id_049f9024_fk_payroll_l; Type: FK CONSTRAINT; Schema: public; Owner: postgres
--

ALTER TABLE ONLY public.payroll_salarystructure_leaveformula
    ADD CONSTRAINT payroll_salarystruct_leaveformula_id_049f9024_fk_payroll_l FOREIGN KEY (leaveformula_id) REFERENCES public.payroll_leaveformula(id) DEFERRABLE INITIALLY DEFERRED;


--
-- TOC entry 4537 (class 2606 OID 29592)
-- Name: payroll_salarystructure_overtimeformula payroll_salarystruct_overtimeformula_id_40ad89ef_fk_payroll_o; Type: FK CONSTRAINT; Schema: public; Owner: postgres
--

ALTER TABLE ONLY public.payroll_salarystructure_overtimeformula
    ADD CONSTRAINT payroll_salarystruct_overtimeformula_id_40ad89ef_fk_payroll_o FOREIGN KEY (overtimeformula_id) REFERENCES public.payroll_overtimeformula(id) DEFERRABLE INITIALLY DEFERRED;


--
-- TOC entry 4532 (class 2606 OID 29597)
-- Name: payroll_salarystructure_exceptionformula payroll_salarystruct_salarystructure_id_3c087208_fk_payroll_s; Type: FK CONSTRAINT; Schema: public; Owner: postgres
--

ALTER TABLE ONLY public.payroll_salarystructure_exceptionformula
    ADD CONSTRAINT payroll_salarystruct_salarystructure_id_3c087208_fk_payroll_s FOREIGN KEY (salarystructure_id) REFERENCES public.payroll_salarystructure(id) DEFERRABLE INITIALLY DEFERRED;


--
-- TOC entry 4530 (class 2606 OID 29602)
-- Name: payroll_salarystructure_deductionformula payroll_salarystruct_salarystructure_id_5ca7cdb5_fk_payroll_s; Type: FK CONSTRAINT; Schema: public; Owner: postgres
--

ALTER TABLE ONLY public.payroll_salarystructure_deductionformula
    ADD CONSTRAINT payroll_salarystruct_salarystructure_id_5ca7cdb5_fk_payroll_s FOREIGN KEY (salarystructure_id) REFERENCES public.payroll_salarystructure(id) DEFERRABLE INITIALLY DEFERRED;


--
-- TOC entry 4538 (class 2606 OID 29607)
-- Name: payroll_salarystructure_overtimeformula payroll_salarystruct_salarystructure_id_64f75042_fk_payroll_s; Type: FK CONSTRAINT; Schema: public; Owner: postgres
--

ALTER TABLE ONLY public.payroll_salarystructure_overtimeformula
    ADD CONSTRAINT payroll_salarystruct_salarystructure_id_64f75042_fk_payroll_s FOREIGN KEY (salarystructure_id) REFERENCES public.payroll_salarystructure(id) DEFERRABLE INITIALLY DEFERRED;


--
-- TOC entry 4534 (class 2606 OID 29612)
-- Name: payroll_salarystructure_increasementformula payroll_salarystruct_salarystructure_id_8752401c_fk_payroll_s; Type: FK CONSTRAINT; Schema: public; Owner: postgres
--

ALTER TABLE ONLY public.payroll_salarystructure_increasementformula
    ADD CONSTRAINT payroll_salarystruct_salarystructure_id_8752401c_fk_payroll_s FOREIGN KEY (salarystructure_id) REFERENCES public.payroll_salarystructure(id) DEFERRABLE INITIALLY DEFERRED;


--
-- TOC entry 4536 (class 2606 OID 29617)
-- Name: payroll_salarystructure_leaveformula payroll_salarystruct_salarystructure_id_cf98fdd7_fk_payroll_s; Type: FK CONSTRAINT; Schema: public; Owner: postgres
--

ALTER TABLE ONLY public.payroll_salarystructure_leaveformula
    ADD CONSTRAINT payroll_salarystruct_salarystructure_id_cf98fdd7_fk_payroll_s FOREIGN KEY (salarystructure_id) REFERENCES public.payroll_salarystructure(id) DEFERRABLE INITIALLY DEFERRED;


--
-- TOC entry 4539 (class 2606 OID 29622)
-- Name: personnel_area personnel_area_company_id_59750eb5_fk_personnel_company_id; Type: FK CONSTRAINT; Schema: public; Owner: postgres
--

ALTER TABLE ONLY public.personnel_area
    ADD CONSTRAINT personnel_area_company_id_59750eb5_fk_personnel_company_id FOREIGN KEY (company_id) REFERENCES public.personnel_company(id) DEFERRABLE INITIALLY DEFERRED;


--
-- TOC entry 4540 (class 2606 OID 29627)
-- Name: personnel_area personnel_area_parent_area_id_39028fda_fk_personnel_area_id; Type: FK CONSTRAINT; Schema: public; Owner: postgres
--

ALTER TABLE ONLY public.personnel_area
    ADD CONSTRAINT personnel_area_parent_area_id_39028fda_fk_personnel_area_id FOREIGN KEY (parent_area_id) REFERENCES public.personnel_area(id) DEFERRABLE INITIALLY DEFERRED;


--
-- TOC entry 4541 (class 2606 OID 29632)
-- Name: personnel_assignareaemployee personnel_assignarea_area_id_6f049d6a_fk_personnel; Type: FK CONSTRAINT; Schema: public; Owner: postgres
--

ALTER TABLE ONLY public.personnel_assignareaemployee
    ADD CONSTRAINT personnel_assignarea_area_id_6f049d6a_fk_personnel FOREIGN KEY (area_id) REFERENCES public.personnel_area(id) DEFERRABLE INITIALLY DEFERRED;


--
-- TOC entry 4542 (class 2606 OID 29637)
-- Name: personnel_assignareaemployee personnel_assignarea_employee_id_a3d4dd25_fk_personnel; Type: FK CONSTRAINT; Schema: public; Owner: postgres
--

ALTER TABLE ONLY public.personnel_assignareaemployee
    ADD CONSTRAINT personnel_assignarea_employee_id_a3d4dd25_fk_personnel FOREIGN KEY (employee_id) REFERENCES public.personnel_employee(id) DEFERRABLE INITIALLY DEFERRED;


--
-- TOC entry 4543 (class 2606 OID 29642)
-- Name: personnel_certification personnel_certificat_company_id_c1b1bd00_fk_personnel; Type: FK CONSTRAINT; Schema: public; Owner: postgres
--

ALTER TABLE ONLY public.personnel_certification
    ADD CONSTRAINT personnel_certificat_company_id_c1b1bd00_fk_personnel FOREIGN KEY (company_id) REFERENCES public.personnel_company(id) DEFERRABLE INITIALLY DEFERRED;


--
-- TOC entry 4544 (class 2606 OID 29647)
-- Name: personnel_department personnel_department_company_id_00867fd8_fk_personnel; Type: FK CONSTRAINT; Schema: public; Owner: postgres
--

ALTER TABLE ONLY public.personnel_department
    ADD CONSTRAINT personnel_department_company_id_00867fd8_fk_personnel FOREIGN KEY (company_id) REFERENCES public.personnel_company(id) DEFERRABLE INITIALLY DEFERRED;


--
-- TOC entry 4545 (class 2606 OID 29652)
-- Name: personnel_department personnel_department_parent_dept_id_d0b44024_fk_personnel; Type: FK CONSTRAINT; Schema: public; Owner: postgres
--

ALTER TABLE ONLY public.personnel_department
    ADD CONSTRAINT personnel_department_parent_dept_id_d0b44024_fk_personnel FOREIGN KEY (parent_dept_id) REFERENCES public.personnel_department(id) DEFERRABLE INITIALLY DEFERRED;


--
-- TOC entry 4551 (class 2606 OID 29657)
-- Name: personnel_employee_area_privilege personnel_employee_a_area_id_6e42535e_fk_personnel; Type: FK CONSTRAINT; Schema: public; Owner: postgres
--

ALTER TABLE ONLY public.personnel_employee_area_privilege
    ADD CONSTRAINT personnel_employee_a_area_id_6e42535e_fk_personnel FOREIGN KEY (area_id) REFERENCES public.personnel_area(id) DEFERRABLE INITIALLY DEFERRED;


--
-- TOC entry 4552 (class 2606 OID 29662)
-- Name: personnel_employee_area_privilege personnel_employee_a_employee_id_1ee6fb47_fk_personnel; Type: FK CONSTRAINT; Schema: public; Owner: postgres
--

ALTER TABLE ONLY public.personnel_employee_area_privilege
    ADD CONSTRAINT personnel_employee_a_employee_id_1ee6fb47_fk_personnel FOREIGN KEY (employee_id) REFERENCES public.personnel_employee(id) DEFERRABLE INITIALLY DEFERRED;


--
-- TOC entry 4549 (class 2606 OID 29667)
-- Name: personnel_employee_area personnel_employee_a_employee_id_8e5cec21_fk_personnel; Type: FK CONSTRAINT; Schema: public; Owner: postgres
--

ALTER TABLE ONLY public.personnel_employee_area
    ADD CONSTRAINT personnel_employee_a_employee_id_8e5cec21_fk_personnel FOREIGN KEY (employee_id) REFERENCES public.personnel_employee(id) DEFERRABLE INITIALLY DEFERRED;


--
-- TOC entry 4550 (class 2606 OID 29672)
-- Name: personnel_employee_area personnel_employee_area_area_id_64c21925_fk_personnel_area_id; Type: FK CONSTRAINT; Schema: public; Owner: postgres
--

ALTER TABLE ONLY public.personnel_employee_area
    ADD CONSTRAINT personnel_employee_area_area_id_64c21925_fk_personnel_area_id FOREIGN KEY (area_id) REFERENCES public.personnel_area(id) DEFERRABLE INITIALLY DEFERRED;


--
-- TOC entry 4546 (class 2606 OID 29677)
-- Name: personnel_employee personnel_employee_company_id_95b3fd72_fk_personnel_company_id; Type: FK CONSTRAINT; Schema: public; Owner: postgres
--

ALTER TABLE ONLY public.personnel_employee
    ADD CONSTRAINT personnel_employee_company_id_95b3fd72_fk_personnel_company_id FOREIGN KEY (company_id) REFERENCES public.personnel_company(id) DEFERRABLE INITIALLY DEFERRED;


--
-- TOC entry 4547 (class 2606 OID 29682)
-- Name: personnel_employee personnel_employee_department_id_068bbd08_fk_personnel; Type: FK CONSTRAINT; Schema: public; Owner: postgres
--

ALTER TABLE ONLY public.personnel_employee
    ADD CONSTRAINT personnel_employee_department_id_068bbd08_fk_personnel FOREIGN KEY (department_id) REFERENCES public.personnel_department(id) DEFERRABLE INITIALLY DEFERRED;


--
-- TOC entry 4553 (class 2606 OID 29687)
-- Name: personnel_employee_flow_role personnel_employee_f_employee_id_c27f8a56_fk_personnel; Type: FK CONSTRAINT; Schema: public; Owner: postgres
--

ALTER TABLE ONLY public.personnel_employee_flow_role
    ADD CONSTRAINT personnel_employee_f_employee_id_c27f8a56_fk_personnel FOREIGN KEY (employee_id) REFERENCES public.personnel_employee(id) DEFERRABLE INITIALLY DEFERRED;


--
-- TOC entry 4554 (class 2606 OID 29692)
-- Name: personnel_employee_flow_role personnel_employee_f_workflowrole_id_4704db32_fk_workflow_; Type: FK CONSTRAINT; Schema: public; Owner: postgres
--

ALTER TABLE ONLY public.personnel_employee_flow_role
    ADD CONSTRAINT personnel_employee_f_workflowrole_id_4704db32_fk_workflow_ FOREIGN KEY (workflowrole_id) REFERENCES public.workflow_workflowrole(id) DEFERRABLE INITIALLY DEFERRED;


--
-- TOC entry 4548 (class 2606 OID 29697)
-- Name: personnel_employee personnel_employee_position_id_c9321343_fk_personnel; Type: FK CONSTRAINT; Schema: public; Owner: postgres
--

ALTER TABLE ONLY public.personnel_employee
    ADD CONSTRAINT personnel_employee_position_id_c9321343_fk_personnel FOREIGN KEY (position_id) REFERENCES public.personnel_position(id) DEFERRABLE INITIALLY DEFERRED;


--
-- TOC entry 4555 (class 2606 OID 29702)
-- Name: personnel_employeecertification personnel_employeece_certification_id_faabed40_fk_personnel; Type: FK CONSTRAINT; Schema: public; Owner: postgres
--

ALTER TABLE ONLY public.personnel_employeecertification
    ADD CONSTRAINT personnel_employeece_certification_id_faabed40_fk_personnel FOREIGN KEY (certification_id) REFERENCES public.personnel_certification(id) DEFERRABLE INITIALLY DEFERRED;


--
-- TOC entry 4556 (class 2606 OID 29707)
-- Name: personnel_employeecertification personnel_employeece_employee_id_b7bd3867_fk_personnel; Type: FK CONSTRAINT; Schema: public; Owner: postgres
--

ALTER TABLE ONLY public.personnel_employeecertification
    ADD CONSTRAINT personnel_employeece_employee_id_b7bd3867_fk_personnel FOREIGN KEY (employee_id) REFERENCES public.personnel_employee(id) DEFERRABLE INITIALLY DEFERRED;


--
-- TOC entry 4557 (class 2606 OID 29712)
-- Name: personnel_employeeprofile personnel_employeepr_emp_id_3a69c313_fk_personnel; Type: FK CONSTRAINT; Schema: public; Owner: postgres
--

ALTER TABLE ONLY public.personnel_employeeprofile
    ADD CONSTRAINT personnel_employeepr_emp_id_3a69c313_fk_personnel FOREIGN KEY (emp_id) REFERENCES public.personnel_employee(id) DEFERRABLE INITIALLY DEFERRED;


--
-- TOC entry 4558 (class 2606 OID 29717)
-- Name: personnel_position personnel_position_company_id_f06c5d2a_fk_personnel_company_id; Type: FK CONSTRAINT; Schema: public; Owner: postgres
--

ALTER TABLE ONLY public.personnel_position
    ADD CONSTRAINT personnel_position_company_id_f06c5d2a_fk_personnel_company_id FOREIGN KEY (company_id) REFERENCES public.personnel_company(id) DEFERRABLE INITIALLY DEFERRED;


--
-- TOC entry 4559 (class 2606 OID 29722)
-- Name: personnel_position personnel_position_parent_position_id_a496a36b_fk_personnel; Type: FK CONSTRAINT; Schema: public; Owner: postgres
--

ALTER TABLE ONLY public.personnel_position
    ADD CONSTRAINT personnel_position_parent_position_id_a496a36b_fk_personnel FOREIGN KEY (parent_position_id) REFERENCES public.personnel_position(id) DEFERRABLE INITIALLY DEFERRED;


--
-- TOC entry 4560 (class 2606 OID 29727)
-- Name: personnel_resign personnel_resign_company_id_a02da327_fk_personnel_company_id; Type: FK CONSTRAINT; Schema: public; Owner: postgres
--

ALTER TABLE ONLY public.personnel_resign
    ADD CONSTRAINT personnel_resign_company_id_a02da327_fk_personnel_company_id FOREIGN KEY (company_id) REFERENCES public.personnel_company(id) DEFERRABLE INITIALLY DEFERRED;


--
-- TOC entry 4561 (class 2606 OID 29732)
-- Name: personnel_resign personnel_resign_employee_id_dd9b7e08_fk_personnel_employee_id; Type: FK CONSTRAINT; Schema: public; Owner: postgres
--

ALTER TABLE ONLY public.personnel_resign
    ADD CONSTRAINT personnel_resign_employee_id_dd9b7e08_fk_personnel_employee_id FOREIGN KEY (employee_id) REFERENCES public.personnel_employee(id) DEFERRABLE INITIALLY DEFERRED;


--
-- TOC entry 4562 (class 2606 OID 29737)
-- Name: staff_stafftoken staff_stafftoken_user_id_39c937fa_fk_personnel_employee_id; Type: FK CONSTRAINT; Schema: public; Owner: postgres
--

ALTER TABLE ONLY public.staff_stafftoken
    ADD CONSTRAINT staff_stafftoken_user_id_39c937fa_fk_personnel_employee_id FOREIGN KEY (user_id) REFERENCES public.personnel_employee(id) DEFERRABLE INITIALLY DEFERRED;


--
-- TOC entry 4563 (class 2606 OID 29742)
-- Name: workflow_nodeinstance workflow_nodeinstanc_approver_admin_id_dff58806_fk_auth_user; Type: FK CONSTRAINT; Schema: public; Owner: postgres
--

ALTER TABLE ONLY public.workflow_nodeinstance
    ADD CONSTRAINT workflow_nodeinstanc_approver_admin_id_dff58806_fk_auth_user FOREIGN KEY (approver_admin_id) REFERENCES public.auth_user(id) DEFERRABLE INITIALLY DEFERRED;


--
-- TOC entry 4564 (class 2606 OID 29747)
-- Name: workflow_nodeinstance workflow_nodeinstanc_approver_employee_id_d36cd45d_fk_personnel; Type: FK CONSTRAINT; Schema: public; Owner: postgres
--

ALTER TABLE ONLY public.workflow_nodeinstance
    ADD CONSTRAINT workflow_nodeinstanc_approver_employee_id_d36cd45d_fk_personnel FOREIGN KEY (approver_employee_id) REFERENCES public.personnel_employee(id) DEFERRABLE INITIALLY DEFERRED;


--
-- TOC entry 4565 (class 2606 OID 29752)
-- Name: workflow_nodeinstance workflow_nodeinstanc_departments_id_b0dc2bdb_fk_personnel; Type: FK CONSTRAINT; Schema: public; Owner: postgres
--

ALTER TABLE ONLY public.workflow_nodeinstance
    ADD CONSTRAINT workflow_nodeinstanc_departments_id_b0dc2bdb_fk_personnel FOREIGN KEY (departments_id) REFERENCES public.personnel_department(id) DEFERRABLE INITIALLY DEFERRED;


--
-- TOC entry 4566 (class 2606 OID 29757)
-- Name: workflow_nodeinstance workflow_nodeinstanc_node_engine_id_4533f12d_fk_workflow_; Type: FK CONSTRAINT; Schema: public; Owner: postgres
--

ALTER TABLE ONLY public.workflow_nodeinstance
    ADD CONSTRAINT workflow_nodeinstanc_node_engine_id_4533f12d_fk_workflow_ FOREIGN KEY (node_engine_id) REFERENCES public.workflow_workflownode(id) DEFERRABLE INITIALLY DEFERRED;


--
-- TOC entry 4567 (class 2606 OID 29762)
-- Name: workflow_nodeinstance workflow_nodeinstanc_workflow_instance_id_afe84fe4_fk_workflow_; Type: FK CONSTRAINT; Schema: public; Owner: postgres
--

ALTER TABLE ONLY public.workflow_nodeinstance
    ADD CONSTRAINT workflow_nodeinstanc_workflow_instance_id_afe84fe4_fk_workflow_ FOREIGN KEY (workflow_instance_id) REFERENCES public.workflow_workflowinstance(id) DEFERRABLE INITIALLY DEFERRED;


--
-- TOC entry 4568 (class 2606 OID 29767)
-- Name: workflow_workflowengine workflow_workfloweng_applicant_position_i_8a65e03a_fk_personnel; Type: FK CONSTRAINT; Schema: public; Owner: postgres
--

ALTER TABLE ONLY public.workflow_workflowengine
    ADD CONSTRAINT workflow_workfloweng_applicant_position_i_8a65e03a_fk_personnel FOREIGN KEY (applicant_position_id) REFERENCES public.personnel_position(id) DEFERRABLE INITIALLY DEFERRED;


--
-- TOC entry 4569 (class 2606 OID 29772)
-- Name: workflow_workflowengine workflow_workfloweng_company_id_c42adcb0_fk_personnel; Type: FK CONSTRAINT; Schema: public; Owner: postgres
--

ALTER TABLE ONLY public.workflow_workflowengine
    ADD CONSTRAINT workflow_workfloweng_company_id_c42adcb0_fk_personnel FOREIGN KEY (company_id) REFERENCES public.personnel_company(id) DEFERRABLE INITIALLY DEFERRED;


--
-- TOC entry 4570 (class 2606 OID 29777)
-- Name: workflow_workflowengine workflow_workfloweng_content_type_id_f7345c20_fk_django_co; Type: FK CONSTRAINT; Schema: public; Owner: postgres
--

ALTER TABLE ONLY public.workflow_workflowengine
    ADD CONSTRAINT workflow_workfloweng_content_type_id_f7345c20_fk_django_co FOREIGN KEY (content_type_id) REFERENCES public.django_content_type(id) DEFERRABLE INITIALLY DEFERRED;


--
-- TOC entry 4571 (class 2606 OID 29782)
-- Name: workflow_workflowengine workflow_workfloweng_departments_id_0f06d4c7_fk_personnel; Type: FK CONSTRAINT; Schema: public; Owner: postgres
--

ALTER TABLE ONLY public.workflow_workflowengine
    ADD CONSTRAINT workflow_workfloweng_departments_id_0f06d4c7_fk_personnel FOREIGN KEY (departments_id) REFERENCES public.personnel_department(id) DEFERRABLE INITIALLY DEFERRED;


--
-- TOC entry 4572 (class 2606 OID 29787)
-- Name: workflow_workflowengine_employee workflow_workfloweng_employee_id_803a409e_fk_personnel; Type: FK CONSTRAINT; Schema: public; Owner: postgres
--

ALTER TABLE ONLY public.workflow_workflowengine_employee
    ADD CONSTRAINT workflow_workfloweng_employee_id_803a409e_fk_personnel FOREIGN KEY (employee_id) REFERENCES public.personnel_employee(id) DEFERRABLE INITIALLY DEFERRED;


--
-- TOC entry 4573 (class 2606 OID 29792)
-- Name: workflow_workflowengine_employee workflow_workfloweng_workflowengine_id_6ebcc5f2_fk_workflow_; Type: FK CONSTRAINT; Schema: public; Owner: postgres
--

ALTER TABLE ONLY public.workflow_workflowengine_employee
    ADD CONSTRAINT workflow_workfloweng_workflowengine_id_6ebcc5f2_fk_workflow_ FOREIGN KEY (workflowengine_id) REFERENCES public.workflow_workflowengine(id) DEFERRABLE INITIALLY DEFERRED;


--
-- TOC entry 4574 (class 2606 OID 29797)
-- Name: workflow_workflowinstance workflow_workflowins_employee_id_c7cff08e_fk_personnel; Type: FK CONSTRAINT; Schema: public; Owner: postgres
--

ALTER TABLE ONLY public.workflow_workflowinstance
    ADD CONSTRAINT workflow_workflowins_employee_id_c7cff08e_fk_personnel FOREIGN KEY (employee_id) REFERENCES public.personnel_employee(id) DEFERRABLE INITIALLY DEFERRED;


--
-- TOC entry 4575 (class 2606 OID 29802)
-- Name: workflow_workflowinstance workflow_workflowins_exception_id_6c82a5d8_fk_workflow_; Type: FK CONSTRAINT; Schema: public; Owner: postgres
--

ALTER TABLE ONLY public.workflow_workflowinstance
    ADD CONSTRAINT workflow_workflowins_exception_id_6c82a5d8_fk_workflow_ FOREIGN KEY (exception_id) REFERENCES public.workflow_abstractexception(id) DEFERRABLE INITIALLY DEFERRED;


--
-- TOC entry 4576 (class 2606 OID 29807)
-- Name: workflow_workflowinstance workflow_workflowins_workflow_engine_id_1e6ac40f_fk_workflow_; Type: FK CONSTRAINT; Schema: public; Owner: postgres
--

ALTER TABLE ONLY public.workflow_workflowinstance
    ADD CONSTRAINT workflow_workflowins_workflow_engine_id_1e6ac40f_fk_workflow_ FOREIGN KEY (workflow_engine_id) REFERENCES public.workflow_workflowengine(id) DEFERRABLE INITIALLY DEFERRED;


--
-- TOC entry 4577 (class 2606 OID 29812)
-- Name: workflow_workflownode workflow_workflownod_company_id_44989997_fk_personnel; Type: FK CONSTRAINT; Schema: public; Owner: postgres
--

ALTER TABLE ONLY public.workflow_workflownode
    ADD CONSTRAINT workflow_workflownod_company_id_44989997_fk_personnel FOREIGN KEY (company_id) REFERENCES public.personnel_company(id) DEFERRABLE INITIALLY DEFERRED;


--
-- TOC entry 4580 (class 2606 OID 29817)
-- Name: workflow_workflownode_notifier workflow_workflownod_workflownode_id_57298016_fk_workflow_; Type: FK CONSTRAINT; Schema: public; Owner: postgres
--

ALTER TABLE ONLY public.workflow_workflownode_notifier
    ADD CONSTRAINT workflow_workflownod_workflownode_id_57298016_fk_workflow_ FOREIGN KEY (workflownode_id) REFERENCES public.workflow_workflownode(id) DEFERRABLE INITIALLY DEFERRED;


--
-- TOC entry 4578 (class 2606 OID 29822)
-- Name: workflow_workflownode_approver workflow_workflownod_workflownode_id_d814c941_fk_workflow_; Type: FK CONSTRAINT; Schema: public; Owner: postgres
--

ALTER TABLE ONLY public.workflow_workflownode_approver
    ADD CONSTRAINT workflow_workflownod_workflownode_id_d814c941_fk_workflow_ FOREIGN KEY (workflownode_id) REFERENCES public.workflow_workflownode(id) DEFERRABLE INITIALLY DEFERRED;


--
-- TOC entry 4581 (class 2606 OID 29827)
-- Name: workflow_workflownode_notifier workflow_workflownod_workflowrole_id_73de7fc2_fk_workflow_; Type: FK CONSTRAINT; Schema: public; Owner: postgres
--

ALTER TABLE ONLY public.workflow_workflownode_notifier
    ADD CONSTRAINT workflow_workflownod_workflowrole_id_73de7fc2_fk_workflow_ FOREIGN KEY (workflowrole_id) REFERENCES public.workflow_workflowrole(id) DEFERRABLE INITIALLY DEFERRED;


--
-- TOC entry 4579 (class 2606 OID 29832)
-- Name: workflow_workflownode_approver workflow_workflownod_workflowrole_id_c8e00d42_fk_workflow_; Type: FK CONSTRAINT; Schema: public; Owner: postgres
--

ALTER TABLE ONLY public.workflow_workflownode_approver
    ADD CONSTRAINT workflow_workflownod_workflowrole_id_c8e00d42_fk_workflow_ FOREIGN KEY (workflowrole_id) REFERENCES public.workflow_workflowrole(id) DEFERRABLE INITIALLY DEFERRED;


--
-- TOC entry 4582 (class 2606 OID 29837)
-- Name: workflow_workflowrole workflow_workflowrol_company_id_bbb75590_fk_personnel; Type: FK CONSTRAINT; Schema: public; Owner: postgres
--

ALTER TABLE ONLY public.workflow_workflowrole
    ADD CONSTRAINT workflow_workflowrol_company_id_bbb75590_fk_personnel FOREIGN KEY (company_id) REFERENCES public.personnel_company(id) DEFERRABLE INITIALLY DEFERRED;


--
-- TOC entry 4714 (class 0 OID 0)
-- Dependencies: 7
-- Name: SCHEMA public; Type: ACL; Schema: -; Owner: Administrator
--

REVOKE USAGE ON SCHEMA public FROM PUBLIC;
GRANT ALL ON SCHEMA public TO PUBLIC;


-- Completed on 2025-11-06 11:19:19

--
-- PostgreSQL database dump complete
--

