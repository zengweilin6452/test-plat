--
-- PostgreSQL database dump
--

\restrict kVBbsDfRvhbfddaoNAwIE4O4EUr2wECL2OerjUWFPZ1nkjn32ozCDWssgG47Ty0

-- Dumped from database version 17.6
-- Dumped by pg_dump version 17.6

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

SET default_tablespace = '';

SET default_table_access_method = heap;

--
-- Name: alembic_version; Type: TABLE; Schema: public; Owner: testdock
--

CREATE TABLE public.alembic_version (
    version_num character varying(32) NOT NULL
);


ALTER TABLE public.alembic_version OWNER TO testdock;

--
-- Name: app_builds; Type: TABLE; Schema: public; Owner: testdock
--

CREATE TABLE public.app_builds (
    id uuid NOT NULL,
    project_id uuid NOT NULL,
    application_id uuid NOT NULL,
    version text NOT NULL,
    build_key text NOT NULL,
    source_commit text,
    storage_key text,
    sha256 text,
    metadata jsonb DEFAULT '{}'::jsonb NOT NULL,
    created_at timestamp with time zone DEFAULT now() NOT NULL,
    CONSTRAINT ck_app_builds_metadata_object CHECK ((jsonb_typeof(metadata) = 'object'::text)),
    CONSTRAINT ck_app_builds_sha256_hex64 CHECK ((sha256 ~ '^[0-9a-f]{64}$'::text))
);


ALTER TABLE public.app_builds OWNER TO testdock;

--
-- Name: TABLE app_builds; Type: COMMENT; Schema: public; Owner: testdock
--

COMMENT ON TABLE public.app_builds IS '固定待测构建；移动包与 Web 部署均采用同一版本记录。';


--
-- Name: COLUMN app_builds.id; Type: COMMENT; Schema: public; Owner: testdock
--

COMMENT ON COLUMN public.app_builds.id IS '服务端生成 UUID';


--
-- Name: COLUMN app_builds.project_id; Type: COMMENT; Schema: public; Owner: testdock
--

COMMENT ON COLUMN public.app_builds.project_id IS '项目归属';


--
-- Name: COLUMN app_builds.application_id; Type: COMMENT; Schema: public; Owner: testdock
--

COMMENT ON COLUMN public.app_builds.application_id IS '所属应用';


--
-- Name: COLUMN app_builds.version; Type: COMMENT; Schema: public; Owner: testdock
--

COMMENT ON COLUMN public.app_builds.version IS '业务版本';


--
-- Name: COLUMN app_builds.build_key; Type: COMMENT; Schema: public; Owner: testdock
--

COMMENT ON COLUMN public.app_builds.build_key IS 'CI 构建号或部署版本，不使用可变 latest';


--
-- Name: COLUMN app_builds.source_commit; Type: COMMENT; Schema: public; Owner: testdock
--

COMMENT ON COLUMN public.app_builds.source_commit IS '来源提交号';


--
-- Name: COLUMN app_builds.storage_key; Type: COMMENT; Schema: public; Owner: testdock
--

COMMENT ON COLUMN public.app_builds.storage_key IS '包文件存储键；Web 部署可为空';


--
-- Name: COLUMN app_builds.sha256; Type: COMMENT; Schema: public; Owner: testdock
--

COMMENT ON COLUMN public.app_builds.sha256 IS '包校验摘要';


--
-- Name: COLUMN app_builds.metadata; Type: COMMENT; Schema: public; Owner: testdock
--

COMMENT ON COLUMN public.app_builds.metadata IS '包属性或部署元数据';


--
-- Name: COLUMN app_builds.created_at; Type: COMMENT; Schema: public; Owner: testdock
--

COMMENT ON COLUMN public.app_builds.created_at IS '创建时间，统一 UTC';


--
-- Name: applications; Type: TABLE; Schema: public; Owner: testdock
--

CREATE TABLE public.applications (
    id uuid NOT NULL,
    project_id uuid NOT NULL,
    platform text NOT NULL,
    name text NOT NULL,
    identifier text NOT NULL,
    archived_at timestamp with time zone,
    created_at timestamp with time zone DEFAULT now() NOT NULL,
    origin text,
    CONSTRAINT ck_applications_origin_allowed CHECK ((origin = ANY (ARRAY['manual'::text, 'demo_seed'::text]))),
    CONSTRAINT ck_applications_platform_allowed CHECK ((platform = ANY (ARRAY['android'::text, 'ios'::text, 'web'::text])))
);


ALTER TABLE public.applications OWNER TO testdock;

--
-- Name: TABLE applications; Type: COMMENT; Schema: public; Owner: testdock
--

COMMENT ON TABLE public.applications IS '目标端属于应用，不为每种端复制一套任务和报告表。';


--
-- Name: COLUMN applications.id; Type: COMMENT; Schema: public; Owner: testdock
--

COMMENT ON COLUMN public.applications.id IS '服务端生成 UUID';


--
-- Name: COLUMN applications.project_id; Type: COMMENT; Schema: public; Owner: testdock
--

COMMENT ON COLUMN public.applications.project_id IS '项目归属';


--
-- Name: COLUMN applications.platform; Type: COMMENT; Schema: public; Owner: testdock
--

COMMENT ON COLUMN public.applications.platform IS '目标端，新增端通过迁移扩展';


--
-- Name: COLUMN applications.name; Type: COMMENT; Schema: public; Owner: testdock
--

COMMENT ON COLUMN public.applications.name IS '应用名称';


--
-- Name: COLUMN applications.identifier; Type: COMMENT; Schema: public; Owner: testdock
--

COMMENT ON COLUMN public.applications.identifier IS '包名、Bundle ID 或站点逻辑标识';


--
-- Name: COLUMN applications.archived_at; Type: COMMENT; Schema: public; Owner: testdock
--

COMMENT ON COLUMN public.applications.archived_at IS '归档时间';


--
-- Name: COLUMN applications.created_at; Type: COMMENT; Schema: public; Owner: testdock
--

COMMENT ON COLUMN public.applications.created_at IS '创建时间，统一 UTC';


--
-- Name: COLUMN applications.origin; Type: COMMENT; Schema: public; Owner: testdock
--

COMMENT ON COLUMN public.applications.origin IS '来源标记：manual=页面/接口建立，demo_seed=显式演示导入；存量行 NULL=未标记';


--
-- Name: artifacts; Type: TABLE; Schema: public; Owner: testdock
--

CREATE TABLE public.artifacts (
    id uuid NOT NULL,
    project_id uuid NOT NULL,
    run_id uuid NOT NULL,
    component_id uuid,
    logical_key text NOT NULL,
    kind text NOT NULL,
    storage_key text NOT NULL,
    mime_type text NOT NULL,
    byte_size bigint NOT NULL,
    sha256 text NOT NULL,
    schema_version text,
    availability text DEFAULT 'available'::text NOT NULL,
    expires_at timestamp with time zone,
    created_at timestamp with time zone DEFAULT now() NOT NULL,
    CONSTRAINT ck_artifacts_availability_allowed CHECK ((availability = ANY (ARRAY['available'::text, 'missing'::text, 'expired'::text]))),
    CONSTRAINT ck_artifacts_byte_size_non_negative CHECK ((byte_size >= 0)),
    CONSTRAINT ck_artifacts_kind_allowed CHECK ((kind = ANY (ARRAY['screenshot'::text, 'ui_tree'::text, 'video'::text, 'log'::text, 'trace'::text, 'metric_series'::text, 'report_json'::text, 'report_html'::text, 'har'::text, 'other'::text]))),
    CONSTRAINT ck_artifacts_sha256_hex64 CHECK ((sha256 ~ '^[0-9a-f]{64}$'::text))
);


ALTER TABLE public.artifacts OWNER TO testdock;

--
-- Name: TABLE artifacts; Type: COMMENT; Schema: public; Owner: testdock
--

COMMENT ON TABLE public.artifacts IS '保存文件元数据和私有存储键，截图、日志、录像、曲线均通过此表归档。 文件先写临时键并校验成功，再提交元数据；无法做到数据库与文件原子提交，需幂等补偿。';


--
-- Name: COLUMN artifacts.id; Type: COMMENT; Schema: public; Owner: testdock
--

COMMENT ON COLUMN public.artifacts.id IS '服务端生成 UUID';


--
-- Name: COLUMN artifacts.project_id; Type: COMMENT; Schema: public; Owner: testdock
--

COMMENT ON COLUMN public.artifacts.project_id IS '项目归属';


--
-- Name: COLUMN artifacts.run_id; Type: COMMENT; Schema: public; Owner: testdock
--

COMMENT ON COLUMN public.artifacts.run_id IS '运行归属';


--
-- Name: COLUMN artifacts.component_id; Type: COMMENT; Schema: public; Owner: testdock
--

COMMENT ON COLUMN public.artifacts.component_id IS '可选子组件归属；总体报告为空';


--
-- Name: COLUMN artifacts.logical_key; Type: COMMENT; Schema: public; Owner: testdock
--

COMMENT ON COLUMN public.artifacts.logical_key IS '运行内唯一逻辑键，含用例或步骤路径';


--
-- Name: COLUMN artifacts.kind; Type: COMMENT; Schema: public; Owner: testdock
--

COMMENT ON COLUMN public.artifacts.kind IS '证据类型';


--
-- Name: COLUMN artifacts.storage_key; Type: COMMENT; Schema: public; Owner: testdock
--

COMMENT ON COLUMN public.artifacts.storage_key IS '受控文件或对象存储键，不存临时签名 URL';


--
-- Name: COLUMN artifacts.mime_type; Type: COMMENT; Schema: public; Owner: testdock
--

COMMENT ON COLUMN public.artifacts.mime_type IS '内容类型';


--
-- Name: COLUMN artifacts.byte_size; Type: COMMENT; Schema: public; Owner: testdock
--

COMMENT ON COLUMN public.artifacts.byte_size IS '文件字节数';


--
-- Name: COLUMN artifacts.sha256; Type: COMMENT; Schema: public; Owner: testdock
--

COMMENT ON COLUMN public.artifacts.sha256 IS '完整性摘要';


--
-- Name: COLUMN artifacts.schema_version; Type: COMMENT; Schema: public; Owner: testdock
--

COMMENT ON COLUMN public.artifacts.schema_version IS '原始报告或曲线 schema';


--
-- Name: COLUMN artifacts.availability; Type: COMMENT; Schema: public; Owner: testdock
--

COMMENT ON COLUMN public.artifacts.availability IS '文件可用状态';


--
-- Name: COLUMN artifacts.expires_at; Type: COMMENT; Schema: public; Owner: testdock
--

COMMENT ON COLUMN public.artifacts.expires_at IS '保留策略到期时间';


--
-- Name: COLUMN artifacts.created_at; Type: COMMENT; Schema: public; Owner: testdock
--

COMMENT ON COLUMN public.artifacts.created_at IS '创建时间，统一 UTC';


--
-- Name: audit_events; Type: TABLE; Schema: public; Owner: testdock
--

CREATE TABLE public.audit_events (
    id uuid NOT NULL,
    project_id uuid NOT NULL,
    actor_ref text NOT NULL,
    action text NOT NULL,
    entity_type text NOT NULL,
    entity_id uuid NOT NULL,
    request_id text NOT NULL,
    changes jsonb DEFAULT '{}'::jsonb NOT NULL,
    created_at timestamp with time zone DEFAULT now() NOT NULL,
    CONSTRAINT ck_audit_events_changes_object CHECK ((jsonb_typeof(changes) = 'object'::text))
);


ALTER TABLE public.audit_events OWNER TO testdock;

--
-- Name: TABLE audit_events; Type: COMMENT; Schema: public; Owner: testdock
--

COMMENT ON TABLE public.audit_events IS '记录谁修改配置、发起运行或调整规则，不承载完整业务数据。 只追加；审计主体与实体是否合法由授权后的业务事务写入。';


--
-- Name: COLUMN audit_events.id; Type: COMMENT; Schema: public; Owner: testdock
--

COMMENT ON COLUMN public.audit_events.id IS '服务端生成 UUID';


--
-- Name: COLUMN audit_events.project_id; Type: COMMENT; Schema: public; Owner: testdock
--

COMMENT ON COLUMN public.audit_events.project_id IS '项目归属';


--
-- Name: COLUMN audit_events.actor_ref; Type: COMMENT; Schema: public; Owner: testdock
--

COMMENT ON COLUMN public.audit_events.actor_ref IS '稳定用户或服务账号引用';


--
-- Name: COLUMN audit_events.action; Type: COMMENT; Schema: public; Owner: testdock
--

COMMENT ON COLUMN public.audit_events.action IS '业务动作';


--
-- Name: COLUMN audit_events.entity_type; Type: COMMENT; Schema: public; Owner: testdock
--

COMMENT ON COLUMN public.audit_events.entity_type IS '目标实体类型';


--
-- Name: COLUMN audit_events.entity_id; Type: COMMENT; Schema: public; Owner: testdock
--

COMMENT ON COLUMN public.audit_events.entity_id IS '目标 ID，历史追溯引用而非跨表通用外键';


--
-- Name: COLUMN audit_events.request_id; Type: COMMENT; Schema: public; Owner: testdock
--

COMMENT ON COLUMN public.audit_events.request_id IS '请求关联标识';


--
-- Name: COLUMN audit_events.changes; Type: COMMENT; Schema: public; Owner: testdock
--

COMMENT ON COLUMN public.audit_events.changes IS '脱敏差异摘要，禁止存凭据';


--
-- Name: COLUMN audit_events.created_at; Type: COMMENT; Schema: public; Owner: testdock
--

COMMENT ON COLUMN public.audit_events.created_at IS '创建时间，统一 UTC';


--
-- Name: baselines; Type: TABLE; Schema: public; Owner: testdock
--

CREATE TABLE public.baselines (
    id uuid NOT NULL,
    project_id uuid NOT NULL,
    application_id uuid NOT NULL,
    environment_id uuid NOT NULL,
    suite_version_id uuid NOT NULL,
    profile_id uuid NOT NULL,
    source_component_id uuid NOT NULL,
    name text NOT NULL,
    version integer NOT NULL,
    metrics_snapshot jsonb NOT NULL,
    created_at timestamp with time zone DEFAULT now() NOT NULL,
    CONSTRAINT ck_baselines_metrics_snapshot_object CHECK ((jsonb_typeof(metrics_snapshot) = 'object'::text)),
    CONSTRAINT ck_baselines_version_positive CHECK ((version > 0))
);


ALTER TABLE public.baselines OWNER TO testdock;

--
-- Name: TABLE baselines; Type: COMMENT; Schema: public; Owner: testdock
--

COMMENT ON TABLE public.baselines IS '不可变的对照版本；源运行和全部可比性信息一并保留。 来源组件的应用、场景、环境、profile 和完整性须由创建基线事务验证；不靠跨表 CHECK。';


--
-- Name: COLUMN baselines.id; Type: COMMENT; Schema: public; Owner: testdock
--

COMMENT ON COLUMN public.baselines.id IS '服务端生成 UUID';


--
-- Name: COLUMN baselines.project_id; Type: COMMENT; Schema: public; Owner: testdock
--

COMMENT ON COLUMN public.baselines.project_id IS '项目归属';


--
-- Name: COLUMN baselines.application_id; Type: COMMENT; Schema: public; Owner: testdock
--

COMMENT ON COLUMN public.baselines.application_id IS '应用';


--
-- Name: COLUMN baselines.environment_id; Type: COMMENT; Schema: public; Owner: testdock
--

COMMENT ON COLUMN public.baselines.environment_id IS '环境';


--
-- Name: COLUMN baselines.suite_version_id; Type: COMMENT; Schema: public; Owner: testdock
--

COMMENT ON COLUMN public.baselines.suite_version_id IS '场景版本';


--
-- Name: COLUMN baselines.profile_id; Type: COMMENT; Schema: public; Owner: testdock
--

COMMENT ON COLUMN public.baselines.profile_id IS '可比资源档案';


--
-- Name: COLUMN baselines.source_component_id; Type: COMMENT; Schema: public; Owner: testdock
--

COMMENT ON COLUMN public.baselines.source_component_id IS '来源性能组件';


--
-- Name: COLUMN baselines.name; Type: COMMENT; Schema: public; Owner: testdock
--

COMMENT ON COLUMN public.baselines.name IS '基线逻辑名';


--
-- Name: COLUMN baselines.version; Type: COMMENT; Schema: public; Owner: testdock
--

COMMENT ON COLUMN public.baselines.version IS '基线修订号';


--
-- Name: COLUMN baselines.metrics_snapshot; Type: COMMENT; Schema: public; Owner: testdock
--

COMMENT ON COLUMN public.baselines.metrics_snapshot IS '指标口径、统计量、值及 schemaVersion';


--
-- Name: COLUMN baselines.created_at; Type: COMMENT; Schema: public; Owner: testdock
--

COMMENT ON COLUMN public.baselines.created_at IS '创建时间，统一 UTC';


--
-- Name: case_results; Type: TABLE; Schema: public; Owner: testdock
--

CREATE TABLE public.case_results (
    id uuid NOT NULL,
    project_id uuid NOT NULL,
    component_id uuid NOT NULL,
    case_key text NOT NULL,
    attempt integer DEFAULT 1 NOT NULL,
    outcome text NOT NULL,
    duration_ms bigint,
    error_summary text,
    steps jsonb DEFAULT '[]'::jsonb NOT NULL,
    created_at timestamp with time zone DEFAULT now() NOT NULL,
    CONSTRAINT ck_case_results_attempt_positive CHECK ((attempt > 0)),
    CONSTRAINT ck_case_results_duration_ms_non_negative CHECK ((duration_ms >= 0)),
    CONSTRAINT ck_case_results_outcome_allowed CHECK ((outcome = ANY (ARRAY['passed'::text, 'failed'::text, 'skipped'::text, 'errored'::text]))),
    CONSTRAINT ck_case_results_steps_array CHECK ((jsonb_typeof(steps) = 'array'::text))
);


ALTER TABLE public.case_results OWNER TO testdock;

--
-- Name: TABLE case_results; Type: COMMENT; Schema: public; Owner: testdock
--

COMMENT ON TABLE public.case_results IS '每个用例的执行尝试独立保存，可区分用例重试与整次重跑。 后端只接受 UI 组件的用例记录，校验 case_key 属于固定 suite_version。';


--
-- Name: COLUMN case_results.id; Type: COMMENT; Schema: public; Owner: testdock
--

COMMENT ON COLUMN public.case_results.id IS '服务端生成 UUID';


--
-- Name: COLUMN case_results.project_id; Type: COMMENT; Schema: public; Owner: testdock
--

COMMENT ON COLUMN public.case_results.project_id IS '项目归属';


--
-- Name: COLUMN case_results.component_id; Type: COMMENT; Schema: public; Owner: testdock
--

COMMENT ON COLUMN public.case_results.component_id IS 'UI 组件结果';


--
-- Name: COLUMN case_results.case_key; Type: COMMENT; Schema: public; Owner: testdock
--

COMMENT ON COLUMN public.case_results.case_key IS '套件版本中的稳定用例 key';


--
-- Name: COLUMN case_results.attempt; Type: COMMENT; Schema: public; Owner: testdock
--

COMMENT ON COLUMN public.case_results.attempt IS '同一次运行内用例尝试次数';


--
-- Name: COLUMN case_results.outcome; Type: COMMENT; Schema: public; Owner: testdock
--

COMMENT ON COLUMN public.case_results.outcome IS '用例结果';


--
-- Name: COLUMN case_results.duration_ms; Type: COMMENT; Schema: public; Owner: testdock
--

COMMENT ON COLUMN public.case_results.duration_ms IS '用例耗时';


--
-- Name: COLUMN case_results.error_summary; Type: COMMENT; Schema: public; Owner: testdock
--

COMMENT ON COLUMN public.case_results.error_summary IS '脱敏错误摘要';


--
-- Name: COLUMN case_results.steps; Type: COMMENT; Schema: public; Owner: testdock
--

COMMENT ON COLUMN public.case_results.steps IS '小体积步骤摘要；完整日志存证据文件';


--
-- Name: COLUMN case_results.created_at; Type: COMMENT; Schema: public; Owner: testdock
--

COMMENT ON COLUMN public.case_results.created_at IS '创建时间，统一 UTC';


--
-- Name: debug_sessions; Type: TABLE; Schema: public; Owner: testdock
--

CREATE TABLE public.debug_sessions (
    id uuid NOT NULL,
    project_id uuid NOT NULL,
    resource_id uuid NOT NULL,
    actor_ref text NOT NULL,
    state text NOT NULL,
    expires_at timestamp with time zone NOT NULL,
    closed_at timestamp with time zone,
    created_at timestamp with time zone DEFAULT now() NOT NULL,
    CONSTRAINT ck_debug_sessions_closed_at_not_before_created CHECK (((closed_at IS NULL) OR (closed_at >= created_at))),
    CONSTRAINT ck_debug_sessions_expires_at_after_created CHECK ((expires_at > created_at)),
    CONSTRAINT ck_debug_sessions_state_allowed CHECK ((state = ANY (ARRAY['opening'::text, 'active'::text, 'closing'::text, 'closed'::text, 'lost'::text]))),
    CONSTRAINT ck_debug_sessions_state_closed_pair CHECK (((state = ANY (ARRAY['closed'::text, 'lost'::text])) = (closed_at IS NOT NULL)))
);


ALTER TABLE public.debug_sessions OWNER TO testdock;

--
-- Name: TABLE debug_sessions; Type: COMMENT; Schema: public; Owner: testdock
--

COMMENT ON TABLE public.debug_sessions IS '人工设备控制使用短期调试会话，与自动运行竞争同一资源租约。 只读预览不占独占租约；会发送输入、冻结采集等操作按宿主冲突规则受控。断线不能立即释放资源。';


--
-- Name: COLUMN debug_sessions.id; Type: COMMENT; Schema: public; Owner: testdock
--

COMMENT ON COLUMN public.debug_sessions.id IS '调试会话 UUID';


--
-- Name: COLUMN debug_sessions.project_id; Type: COMMENT; Schema: public; Owner: testdock
--

COMMENT ON COLUMN public.debug_sessions.project_id IS '项目归属';


--
-- Name: COLUMN debug_sessions.resource_id; Type: COMMENT; Schema: public; Owner: testdock
--

COMMENT ON COLUMN public.debug_sessions.resource_id IS '调试实例';


--
-- Name: COLUMN debug_sessions.actor_ref; Type: COMMENT; Schema: public; Owner: testdock
--

COMMENT ON COLUMN public.debug_sessions.actor_ref IS '操作人身份引用';


--
-- Name: COLUMN debug_sessions.state; Type: COMMENT; Schema: public; Owner: testdock
--

COMMENT ON COLUMN public.debug_sessions.state IS '调试生命周期';


--
-- Name: COLUMN debug_sessions.expires_at; Type: COMMENT; Schema: public; Owner: testdock
--

COMMENT ON COLUMN public.debug_sessions.expires_at IS '会话过期时间';


--
-- Name: COLUMN debug_sessions.closed_at; Type: COMMENT; Schema: public; Owner: testdock
--

COMMENT ON COLUMN public.debug_sessions.closed_at IS '关闭或确认失联时间';


--
-- Name: COLUMN debug_sessions.created_at; Type: COMMENT; Schema: public; Owner: testdock
--

COMMENT ON COLUMN public.debug_sessions.created_at IS '创建时间，统一 UTC';


--
-- Name: device_checks; Type: TABLE; Schema: public; Owner: testdock
--

CREATE TABLE public.device_checks (
    id uuid NOT NULL,
    project_id uuid NOT NULL,
    resource_id uuid NOT NULL,
    kind text NOT NULL,
    test_type text NOT NULL,
    holder_id text NOT NULL,
    state text NOT NULL,
    requested_at timestamp with time zone DEFAULT now() NOT NULL,
    started_at timestamp with time zone,
    finished_at timestamp with time zone,
    expires_at timestamp with time zone NOT NULL,
    result jsonb,
    error_code text,
    created_at timestamp with time zone DEFAULT now() NOT NULL,
    CONSTRAINT ck_device_checks_expires_at_after_created CHECK ((expires_at > created_at)),
    CONSTRAINT ck_device_checks_finished_at_not_before_created CHECK (((finished_at IS NULL) OR (finished_at >= created_at))),
    CONSTRAINT ck_device_checks_kind_allowed CHECK ((kind = ANY (ARRAY['readiness'::text, 'identity'::text]))),
    CONSTRAINT ck_device_checks_state_allowed CHECK ((state = ANY (ARRAY['opening'::text, 'running'::text, 'finished'::text, 'failed'::text, 'lost'::text]))),
    CONSTRAINT ck_device_checks_test_type_allowed CHECK ((test_type = ANY (ARRAY['ui'::text, 'performance'::text, 'joint'::text])))
);


ALTER TABLE public.device_checks OWNER TO testdock;

--
-- Name: TABLE device_checks; Type: COMMENT; Schema: public; Owner: testdock
--

COMMENT ON TABLE public.device_checks IS '设备短检查（readiness / identity）；与运行、调试共用 resource_leases 互斥';


--
-- Name: COLUMN device_checks.id; Type: COMMENT; Schema: public; Owner: testdock
--

COMMENT ON COLUMN public.device_checks.id IS '检查 id';


--
-- Name: COLUMN device_checks.project_id; Type: COMMENT; Schema: public; Owner: testdock
--

COMMENT ON COLUMN public.device_checks.project_id IS '所属项目';


--
-- Name: COLUMN device_checks.resource_id; Type: COMMENT; Schema: public; Owner: testdock
--

COMMENT ON COLUMN public.device_checks.resource_id IS '被检查的执行资源';


--
-- Name: COLUMN device_checks.kind; Type: COMMENT; Schema: public; Owner: testdock
--

COMMENT ON COLUMN public.device_checks.kind IS '检查类型：readiness / identity';


--
-- Name: COLUMN device_checks.test_type; Type: COMMENT; Schema: public; Owner: testdock
--

COMMENT ON COLUMN public.device_checks.test_type IS '检查目标测试类型';


--
-- Name: COLUMN device_checks.holder_id; Type: COMMENT; Schema: public; Owner: testdock
--

COMMENT ON COLUMN public.device_checks.holder_id IS '检查持有者标识';


--
-- Name: COLUMN device_checks.state; Type: COMMENT; Schema: public; Owner: testdock
--

COMMENT ON COLUMN public.device_checks.state IS '检查状态：opening / running / finished / failed / lost';


--
-- Name: COLUMN device_checks.requested_at; Type: COMMENT; Schema: public; Owner: testdock
--

COMMENT ON COLUMN public.device_checks.requested_at IS '请求时间';


--
-- Name: COLUMN device_checks.started_at; Type: COMMENT; Schema: public; Owner: testdock
--

COMMENT ON COLUMN public.device_checks.started_at IS '开始时间';


--
-- Name: COLUMN device_checks.finished_at; Type: COMMENT; Schema: public; Owner: testdock
--

COMMENT ON COLUMN public.device_checks.finished_at IS '结束时间';


--
-- Name: COLUMN device_checks.expires_at; Type: COMMENT; Schema: public; Owner: testdock
--

COMMENT ON COLUMN public.device_checks.expires_at IS '租约到期时间；过期即视为丢失';


--
-- Name: COLUMN device_checks.result; Type: COMMENT; Schema: public; Owner: testdock
--

COMMENT ON COLUMN public.device_checks.result IS '检查结果（readiness / identity 判定）';


--
-- Name: COLUMN device_checks.error_code; Type: COMMENT; Schema: public; Owner: testdock
--

COMMENT ON COLUMN public.device_checks.error_code IS '失败错误码';


--
-- Name: COLUMN device_checks.created_at; Type: COMMENT; Schema: public; Owner: testdock
--

COMMENT ON COLUMN public.device_checks.created_at IS '创建时间';


--
-- Name: environments; Type: TABLE; Schema: public; Owner: testdock
--

CREATE TABLE public.environments (
    id uuid NOT NULL,
    project_id uuid NOT NULL,
    name text NOT NULL,
    config jsonb DEFAULT '{}'::jsonb NOT NULL,
    secret_ref text,
    archived_at timestamp with time zone,
    created_at timestamp with time zone DEFAULT now() NOT NULL,
    CONSTRAINT ck_environments_config_object CHECK ((jsonb_typeof(config) = 'object'::text))
);


ALTER TABLE public.environments OWNER TO testdock;

--
-- Name: TABLE environments; Type: COMMENT; Schema: public; Owner: testdock
--

COMMENT ON TABLE public.environments IS '保存各环境的非敏感配置，实际站点地址可随环境区分。';


--
-- Name: COLUMN environments.id; Type: COMMENT; Schema: public; Owner: testdock
--

COMMENT ON COLUMN public.environments.id IS '服务端生成 UUID';


--
-- Name: COLUMN environments.project_id; Type: COMMENT; Schema: public; Owner: testdock
--

COMMENT ON COLUMN public.environments.project_id IS '项目归属';


--
-- Name: COLUMN environments.name; Type: COMMENT; Schema: public; Owner: testdock
--

COMMENT ON COLUMN public.environments.name IS 'staging、qa 等环境名';


--
-- Name: COLUMN environments.config; Type: COMMENT; Schema: public; Owner: testdock
--

COMMENT ON COLUMN public.environments.config IS '地址映射、变量及 schemaVersion；禁止明文凭据';


--
-- Name: COLUMN environments.secret_ref; Type: COMMENT; Schema: public; Owner: testdock
--

COMMENT ON COLUMN public.environments.secret_ref IS '密钥管理系统引用，不能是密钥值';


--
-- Name: COLUMN environments.archived_at; Type: COMMENT; Schema: public; Owner: testdock
--

COMMENT ON COLUMN public.environments.archived_at IS '归档时间';


--
-- Name: COLUMN environments.created_at; Type: COMMENT; Schema: public; Owner: testdock
--

COMMENT ON COLUMN public.environments.created_at IS '创建时间，统一 UTC';


--
-- Name: execution_nodes; Type: TABLE; Schema: public; Owner: testdock
--

CREATE TABLE public.execution_nodes (
    id uuid NOT NULL,
    project_id uuid NOT NULL,
    name text NOT NULL,
    agent_version text NOT NULL,
    capabilities jsonb DEFAULT '{}'::jsonb NOT NULL,
    status text NOT NULL,
    heartbeat_at timestamp with time zone,
    created_at timestamp with time zone DEFAULT now() NOT NULL,
    CONSTRAINT ck_execution_nodes_capabilities_object CHECK ((jsonb_typeof(capabilities) = 'object'::text)),
    CONSTRAINT ck_execution_nodes_status_allowed CHECK ((status = ANY (ARRAY['online'::text, 'offline'::text, 'draining'::text])))
);


ALTER TABLE public.execution_nodes OWNER TO testdock;

--
-- Name: TABLE execution_nodes; Type: COMMENT; Schema: public; Owner: testdock
--

COMMENT ON TABLE public.execution_nodes IS '宿主 Agent 与可用适配器，初期按项目独占。 宿主凭据不入 capabilities；首期不设计跨项目共享节点池。';


--
-- Name: COLUMN execution_nodes.id; Type: COMMENT; Schema: public; Owner: testdock
--

COMMENT ON COLUMN public.execution_nodes.id IS '服务端生成 UUID';


--
-- Name: COLUMN execution_nodes.project_id; Type: COMMENT; Schema: public; Owner: testdock
--

COMMENT ON COLUMN public.execution_nodes.project_id IS '项目归属';


--
-- Name: COLUMN execution_nodes.name; Type: COMMENT; Schema: public; Owner: testdock
--

COMMENT ON COLUMN public.execution_nodes.name IS '节点名称';


--
-- Name: COLUMN execution_nodes.agent_version; Type: COMMENT; Schema: public; Owner: testdock
--

COMMENT ON COLUMN public.execution_nodes.agent_version IS 'Agent 版本';


--
-- Name: COLUMN execution_nodes.capabilities; Type: COMMENT; Schema: public; Owner: testdock
--

COMMENT ON COLUMN public.execution_nodes.capabilities IS '已注册适配器及其版本';


--
-- Name: COLUMN execution_nodes.status; Type: COMMENT; Schema: public; Owner: testdock
--

COMMENT ON COLUMN public.execution_nodes.status IS '节点状态';


--
-- Name: COLUMN execution_nodes.heartbeat_at; Type: COMMENT; Schema: public; Owner: testdock
--

COMMENT ON COLUMN public.execution_nodes.heartbeat_at IS '最近心跳时间';


--
-- Name: COLUMN execution_nodes.created_at; Type: COMMENT; Schema: public; Owner: testdock
--

COMMENT ON COLUMN public.execution_nodes.created_at IS '创建时间，统一 UTC';


--
-- Name: execution_resources; Type: TABLE; Schema: public; Owner: testdock
--

CREATE TABLE public.execution_resources (
    id uuid NOT NULL,
    project_id uuid NOT NULL,
    node_id uuid NOT NULL,
    profile_id uuid NOT NULL,
    platform text NOT NULL,
    resource_key text NOT NULL,
    kind text NOT NULL,
    status text NOT NULL,
    fence_counter bigint DEFAULT 0 NOT NULL,
    created_at timestamp with time zone DEFAULT now() NOT NULL,
    last_seen_at timestamp with time zone,
    CONSTRAINT ck_execution_resources_fence_counter_non_negative CHECK ((fence_counter >= 0)),
    CONSTRAINT ck_execution_resources_kind_allowed CHECK ((kind = ANY (ARRAY['device'::text, 'simulator'::text, 'browser_slot'::text]))),
    CONSTRAINT ck_execution_resources_platform_allowed CHECK ((platform = ANY (ARRAY['android'::text, 'ios'::text, 'web'::text]))),
    CONSTRAINT ck_execution_resources_platform_kind_pair CHECK ((((platform = 'web'::text) AND (kind = 'browser_slot'::text)) OR ((platform <> 'web'::text) AND (kind = ANY (ARRAY['device'::text, 'simulator'::text]))))),
    CONSTRAINT ck_execution_resources_status_allowed CHECK ((status = ANY (ARRAY['ready'::text, 'offline'::text, 'unauthorized'::text, 'draining'::text])))
);


ALTER TABLE public.execution_resources OWNER TO testdock;

--
-- Name: TABLE execution_resources; Type: COMMENT; Schema: public; Owner: testdock
--

COMMENT ON TABLE public.execution_resources IS '真机、模拟器或浏览器槽位。每个实例只承载一个活动运行。 Web 并发通过多个独立槽位表示；资源重新建档须在无活动租约时处理。';


--
-- Name: COLUMN execution_resources.id; Type: COMMENT; Schema: public; Owner: testdock
--

COMMENT ON COLUMN public.execution_resources.id IS '服务端生成 UUID';


--
-- Name: COLUMN execution_resources.project_id; Type: COMMENT; Schema: public; Owner: testdock
--

COMMENT ON COLUMN public.execution_resources.project_id IS '项目归属';


--
-- Name: COLUMN execution_resources.node_id; Type: COMMENT; Schema: public; Owner: testdock
--

COMMENT ON COLUMN public.execution_resources.node_id IS '执行节点';


--
-- Name: COLUMN execution_resources.profile_id; Type: COMMENT; Schema: public; Owner: testdock
--

COMMENT ON COLUMN public.execution_resources.profile_id IS '当前不可变档案';


--
-- Name: COLUMN execution_resources.platform; Type: COMMENT; Schema: public; Owner: testdock
--

COMMENT ON COLUMN public.execution_resources.platform IS '目标端';


--
-- Name: COLUMN execution_resources.resource_key; Type: COMMENT; Schema: public; Owner: testdock
--

COMMENT ON COLUMN public.execution_resources.resource_key IS '宿主内设备标识或浏览器槽位';


--
-- Name: COLUMN execution_resources.kind; Type: COMMENT; Schema: public; Owner: testdock
--

COMMENT ON COLUMN public.execution_resources.kind IS '资源类型';


--
-- Name: COLUMN execution_resources.status; Type: COMMENT; Schema: public; Owner: testdock
--

COMMENT ON COLUMN public.execution_resources.status IS '连接状态；占用从租约推导';


--
-- Name: COLUMN execution_resources.fence_counter; Type: COMMENT; Schema: public; Owner: testdock
--

COMMENT ON COLUMN public.execution_resources.fence_counter IS '每次分配递增的隔离令牌';


--
-- Name: COLUMN execution_resources.created_at; Type: COMMENT; Schema: public; Owner: testdock
--

COMMENT ON COLUMN public.execution_resources.created_at IS '创建时间，统一 UTC';


--
-- Name: COLUMN execution_resources.last_seen_at; Type: COMMENT; Schema: public; Owner: testdock
--

COMMENT ON COLUMN public.execution_resources.last_seen_at IS '最近一次被节点同步确认在线的时间；NULL = 从未同步过';


--
-- Name: gate_evaluations; Type: TABLE; Schema: public; Owner: testdock
--

CREATE TABLE public.gate_evaluations (
    id uuid NOT NULL,
    project_id uuid NOT NULL,
    component_id uuid NOT NULL,
    policy_id uuid NOT NULL,
    baseline_id uuid,
    mode text NOT NULL,
    request_key text NOT NULL,
    verdict text NOT NULL,
    reason_code text,
    checks jsonb DEFAULT '[]'::jsonb NOT NULL,
    created_at timestamp with time zone DEFAULT now() NOT NULL,
    CONSTRAINT ck_gate_evaluations_checks_array CHECK ((jsonb_typeof(checks) = 'array'::text)),
    CONSTRAINT ck_gate_evaluations_mode_allowed CHECK ((mode = ANY (ARRAY['original'::text, 'reanalysis'::text]))),
    CONSTRAINT ck_gate_evaluations_verdict_allowed CHECK ((verdict = ANY (ARRAY['passed'::text, 'failed'::text, 'not_tested'::text]))),
    CONSTRAINT ck_gate_evaluations_verdict_not_tested_reason CHECK (((verdict <> 'not_tested'::text) OR (reason_code IS NOT NULL)))
);


ALTER TABLE public.gate_evaluations OWNER TO testdock;

--
-- Name: TABLE gate_evaluations; Type: COMMENT; Schema: public; Owner: testdock
--

COMMENT ON TABLE public.gate_evaluations IS '原始判定与后续试算分开保存；改规则不会覆盖历史结论。 同项目外键不保证规则与基线适用当前应用；服务必须检查完整可比性。';


--
-- Name: COLUMN gate_evaluations.id; Type: COMMENT; Schema: public; Owner: testdock
--

COMMENT ON COLUMN public.gate_evaluations.id IS '服务端生成 UUID';


--
-- Name: COLUMN gate_evaluations.project_id; Type: COMMENT; Schema: public; Owner: testdock
--

COMMENT ON COLUMN public.gate_evaluations.project_id IS '项目归属';


--
-- Name: COLUMN gate_evaluations.component_id; Type: COMMENT; Schema: public; Owner: testdock
--

COMMENT ON COLUMN public.gate_evaluations.component_id IS '性能组件';


--
-- Name: COLUMN gate_evaluations.policy_id; Type: COMMENT; Schema: public; Owner: testdock
--

COMMENT ON COLUMN public.gate_evaluations.policy_id IS '固定规则版本';


--
-- Name: COLUMN gate_evaluations.baseline_id; Type: COMMENT; Schema: public; Owner: testdock
--

COMMENT ON COLUMN public.gate_evaluations.baseline_id IS '可为空，缺失时形成 not_tested 及原因';


--
-- Name: COLUMN gate_evaluations.mode; Type: COMMENT; Schema: public; Owner: testdock
--

COMMENT ON COLUMN public.gate_evaluations.mode IS '原始判定或后续试算';


--
-- Name: COLUMN gate_evaluations.request_key; Type: COMMENT; Schema: public; Owner: testdock
--

COMMENT ON COLUMN public.gate_evaluations.request_key IS '判定请求幂等键';


--
-- Name: COLUMN gate_evaluations.verdict; Type: COMMENT; Schema: public; Owner: testdock
--

COMMENT ON COLUMN public.gate_evaluations.verdict IS '三态结论';


--
-- Name: COLUMN gate_evaluations.reason_code; Type: COMMENT; Schema: public; Owner: testdock
--

COMMENT ON COLUMN public.gate_evaluations.reason_code IS '未判定原因码';


--
-- Name: COLUMN gate_evaluations.checks; Type: COMMENT; Schema: public; Owner: testdock
--

COMMENT ON COLUMN public.gate_evaluations.checks IS '每项实际值、阈值、单位、样本数及结果';


--
-- Name: COLUMN gate_evaluations.created_at; Type: COMMENT; Schema: public; Owner: testdock
--

COMMENT ON COLUMN public.gate_evaluations.created_at IS '创建时间，统一 UTC';


--
-- Name: gate_policies; Type: TABLE; Schema: public; Owner: testdock
--

CREATE TABLE public.gate_policies (
    id uuid NOT NULL,
    project_id uuid NOT NULL,
    application_id uuid NOT NULL,
    name text NOT NULL,
    version integer NOT NULL,
    rules jsonb NOT NULL,
    created_at timestamp with time zone DEFAULT now() NOT NULL,
    CONSTRAINT ck_gate_policies_rules_object CHECK ((jsonb_typeof(rules) = 'object'::text)),
    CONSTRAINT ck_gate_policies_version_positive CHECK ((version > 0))
);


ALTER TABLE public.gate_policies OWNER TO testdock;

--
-- Name: TABLE gate_policies; Type: COMMENT; Schema: public; Owner: testdock
--

COMMENT ON TABLE public.gate_policies IS '平台持有门槛，适配器负责正确的测量与统计。';


--
-- Name: COLUMN gate_policies.id; Type: COMMENT; Schema: public; Owner: testdock
--

COMMENT ON COLUMN public.gate_policies.id IS '服务端生成 UUID';


--
-- Name: COLUMN gate_policies.project_id; Type: COMMENT; Schema: public; Owner: testdock
--

COMMENT ON COLUMN public.gate_policies.project_id IS '项目归属';


--
-- Name: COLUMN gate_policies.application_id; Type: COMMENT; Schema: public; Owner: testdock
--

COMMENT ON COLUMN public.gate_policies.application_id IS '规则适用应用';


--
-- Name: COLUMN gate_policies.name; Type: COMMENT; Schema: public; Owner: testdock
--

COMMENT ON COLUMN public.gate_policies.name IS '逻辑规则名';


--
-- Name: COLUMN gate_policies.version; Type: COMMENT; Schema: public; Owner: testdock
--

COMMENT ON COLUMN public.gate_policies.version IS '不可变规则版本';


--
-- Name: COLUMN gate_policies.rules; Type: COMMENT; Schema: public; Owner: testdock
--

COMMENT ON COLUMN public.gate_policies.rules IS '带 schemaVersion 的指标、单位、窗口、比较符、阈值、warn/fail 和样本下限';


--
-- Name: COLUMN gate_policies.created_at; Type: COMMENT; Schema: public; Owner: testdock
--

COMMENT ON COLUMN public.gate_policies.created_at IS '创建时间，统一 UTC';


--
-- Name: metric_summaries; Type: TABLE; Schema: public; Owner: testdock
--

CREATE TABLE public.metric_summaries (
    id uuid NOT NULL,
    project_id uuid NOT NULL,
    component_id uuid NOT NULL,
    metric_key text NOT NULL,
    metric_version text NOT NULL,
    unit text NOT NULL,
    scope text NOT NULL,
    window_key text NOT NULL,
    statistic text NOT NULL,
    sample_count integer NOT NULL,
    value double precision,
    missing_reason text,
    created_at timestamp with time zone DEFAULT now() NOT NULL,
    missing_reason_text text,
    CONSTRAINT ck_metric_summaries_sample_count_non_negative CHECK ((sample_count >= 0)),
    CONSTRAINT ck_metric_summaries_statistic_allowed CHECK ((statistic = ANY (ARRAY['median'::text, 'p95'::text, 'p90'::text, 'mean'::text, 'min'::text, 'max'::text]))),
    CONSTRAINT ck_metric_summaries_value_finite CHECK (((value IS NULL) OR ((sample_count > 0) AND (value > '-Infinity'::double precision) AND (value < 'Infinity'::double precision)))),
    CONSTRAINT ck_metric_summaries_value_missing_reason_pair CHECK ((((value IS NULL) AND (missing_reason IS NOT NULL)) OR ((value IS NOT NULL) AND (missing_reason IS NULL))))
);


ALTER TABLE public.metric_summaries OWNER TO testdock;

--
-- Name: TABLE metric_summaries; Type: COMMENT; Schema: public; Owner: testdock
--

COMMENT ON TABLE public.metric_summaries IS '按指标、统计窗口和统计量保存查询所需的小体积摘要。 采样率、单位换算、窗口边界属于适配器契约；原始 series 单独归档，不逐点写业务库。';


--
-- Name: COLUMN metric_summaries.id; Type: COMMENT; Schema: public; Owner: testdock
--

COMMENT ON COLUMN public.metric_summaries.id IS '服务端生成 UUID';


--
-- Name: COLUMN metric_summaries.project_id; Type: COMMENT; Schema: public; Owner: testdock
--

COMMENT ON COLUMN public.metric_summaries.project_id IS '项目归属';


--
-- Name: COLUMN metric_summaries.component_id; Type: COMMENT; Schema: public; Owner: testdock
--

COMMENT ON COLUMN public.metric_summaries.component_id IS '性能组件';


--
-- Name: COLUMN metric_summaries.metric_key; Type: COMMENT; Schema: public; Owner: testdock
--

COMMENT ON COLUMN public.metric_summaries.metric_key IS '有命名空间的指标键，例如 android.memory.pss';


--
-- Name: COLUMN metric_summaries.metric_version; Type: COMMENT; Schema: public; Owner: testdock
--

COMMENT ON COLUMN public.metric_summaries.metric_version IS '指标口径版本';


--
-- Name: COLUMN metric_summaries.unit; Type: COMMENT; Schema: public; Owner: testdock
--

COMMENT ON COLUMN public.metric_summaries.unit IS '显式单位，例如 MiB、ms、percent';


--
-- Name: COLUMN metric_summaries.scope; Type: COMMENT; Schema: public; Owner: testdock
--

COMMENT ON COLUMN public.metric_summaries.scope IS 'app、device、page 等测量范围';


--
-- Name: COLUMN metric_summaries.window_key; Type: COMMENT; Schema: public; Owner: testdock
--

COMMENT ON COLUMN public.metric_summaries.window_key IS '全程或步骤窗口';


--
-- Name: COLUMN metric_summaries.statistic; Type: COMMENT; Schema: public; Owner: testdock
--

COMMENT ON COLUMN public.metric_summaries.statistic IS '统计量，现有 Android 判定使用 median';


--
-- Name: COLUMN metric_summaries.sample_count; Type: COMMENT; Schema: public; Owner: testdock
--

COMMENT ON COLUMN public.metric_summaries.sample_count IS '有效样本数';


--
-- Name: COLUMN metric_summaries.value; Type: COMMENT; Schema: public; Owner: testdock
--

COMMENT ON COLUMN public.metric_summaries.value IS '缺失时为 NULL，不能补 0';


--
-- Name: COLUMN metric_summaries.missing_reason; Type: COMMENT; Schema: public; Owner: testdock
--

COMMENT ON COLUMN public.metric_summaries.missing_reason IS '缺失原因';


--
-- Name: COLUMN metric_summaries.created_at; Type: COMMENT; Schema: public; Owner: testdock
--

COMMENT ON COLUMN public.metric_summaries.created_at IS '创建时间，统一 UTC';


--
-- Name: project_members; Type: TABLE; Schema: public; Owner: testdock
--

CREATE TABLE public.project_members (
    id uuid NOT NULL,
    project_id uuid NOT NULL,
    identity_issuer text NOT NULL,
    identity_subject text NOT NULL,
    role text NOT NULL,
    created_at timestamp with time zone DEFAULT now() NOT NULL,
    CONSTRAINT ck_project_members_role_allowed CHECK ((role = ANY (ARRAY['owner'::text, 'maintainer'::text, 'runner'::text, 'viewer'::text])))
);


ALTER TABLE public.project_members OWNER TO testdock;

--
-- Name: TABLE project_members; Type: COMMENT; Schema: public; Owner: testdock
--

COMMENT ON TABLE public.project_members IS '复用身份提供方，以项目角色授权，不在业务库保存登录口令。 角色必须由后端检查；project_id 外键不等于行级访问控制。';


--
-- Name: COLUMN project_members.id; Type: COMMENT; Schema: public; Owner: testdock
--

COMMENT ON COLUMN public.project_members.id IS '服务端生成 UUID';


--
-- Name: COLUMN project_members.project_id; Type: COMMENT; Schema: public; Owner: testdock
--

COMMENT ON COLUMN public.project_members.project_id IS '项目归属';


--
-- Name: COLUMN project_members.identity_issuer; Type: COMMENT; Schema: public; Owner: testdock
--

COMMENT ON COLUMN public.project_members.identity_issuer IS '身份提供方标识';


--
-- Name: COLUMN project_members.identity_subject; Type: COMMENT; Schema: public; Owner: testdock
--

COMMENT ON COLUMN public.project_members.identity_subject IS '提供方内稳定用户 ID';


--
-- Name: COLUMN project_members.role; Type: COMMENT; Schema: public; Owner: testdock
--

COMMENT ON COLUMN public.project_members.role IS '项目角色';


--
-- Name: COLUMN project_members.created_at; Type: COMMENT; Schema: public; Owner: testdock
--

COMMENT ON COLUMN public.project_members.created_at IS '创建时间，统一 UTC';


--
-- Name: projects; Type: TABLE; Schema: public; Owner: testdock
--

CREATE TABLE public.projects (
    id uuid NOT NULL,
    code text NOT NULL,
    name text NOT NULL,
    archived_at timestamp with time zone,
    created_at timestamp with time zone DEFAULT now() NOT NULL,
    origin text,
    CONSTRAINT ck_projects_origin_allowed CHECK ((origin = ANY (ARRAY['manual'::text, 'demo_seed'::text])))
);


ALTER TABLE public.projects OWNER TO testdock;

--
-- Name: TABLE projects; Type: COMMENT; Schema: public; Owner: testdock
--

COMMENT ON TABLE public.projects IS '产品级隔离单元，Android、iOS、Web 应用归属于同一项目。';


--
-- Name: COLUMN projects.id; Type: COMMENT; Schema: public; Owner: testdock
--

COMMENT ON COLUMN public.projects.id IS '项目 UUID';


--
-- Name: COLUMN projects.code; Type: COMMENT; Schema: public; Owner: testdock
--

COMMENT ON COLUMN public.projects.code IS '稳定项目代号';


--
-- Name: COLUMN projects.name; Type: COMMENT; Schema: public; Owner: testdock
--

COMMENT ON COLUMN public.projects.name IS '展示名称';


--
-- Name: COLUMN projects.archived_at; Type: COMMENT; Schema: public; Owner: testdock
--

COMMENT ON COLUMN public.projects.archived_at IS '归档时间，保留历史引用';


--
-- Name: COLUMN projects.created_at; Type: COMMENT; Schema: public; Owner: testdock
--

COMMENT ON COLUMN public.projects.created_at IS '创建时间，统一 UTC';


--
-- Name: COLUMN projects.origin; Type: COMMENT; Schema: public; Owner: testdock
--

COMMENT ON COLUMN public.projects.origin IS '来源标记：manual=页面/接口建立，demo_seed=显式演示导入；存量行 NULL=未标记';


--
-- Name: resource_leases; Type: TABLE; Schema: public; Owner: testdock
--

CREATE TABLE public.resource_leases (
    id uuid NOT NULL,
    project_id uuid NOT NULL,
    resource_id uuid NOT NULL,
    run_id uuid,
    debug_session_id uuid,
    fencing_token bigint NOT NULL,
    holder_id text NOT NULL,
    expires_at timestamp with time zone NOT NULL,
    released_at timestamp with time zone,
    release_reason text,
    created_at timestamp with time zone DEFAULT now() NOT NULL,
    check_id uuid,
    CONSTRAINT ck_resource_leases_expires_at_after_created CHECK ((expires_at > created_at)),
    CONSTRAINT ck_resource_leases_fencing_token_positive CHECK ((fencing_token > 0)),
    CONSTRAINT ck_resource_leases_released_at_not_before_created CHECK (((released_at IS NULL) OR (released_at >= created_at))),
    CONSTRAINT ck_resource_leases_single_holder CHECK ((num_nonnulls(run_id, debug_session_id, check_id) = 1))
);


ALTER TABLE public.resource_leases OWNER TO testdock;

--
-- Name: TABLE resource_leases; Type: COMMENT; Schema: public; Owner: testdock
--

COMMENT ON TABLE public.resource_leases IS '保留运行或调试的独占历史，用 fencing token 拒绝过期执行者。 部分唯一索引保证每实例、运行或调试会话最多一条未释放租约；超时回收仍需 Agent 隔离旧进程。';


--
-- Name: COLUMN resource_leases.id; Type: COMMENT; Schema: public; Owner: testdock
--

COMMENT ON COLUMN public.resource_leases.id IS '服务端生成 UUID';


--
-- Name: COLUMN resource_leases.project_id; Type: COMMENT; Schema: public; Owner: testdock
--

COMMENT ON COLUMN public.resource_leases.project_id IS '项目归属';


--
-- Name: COLUMN resource_leases.resource_id; Type: COMMENT; Schema: public; Owner: testdock
--

COMMENT ON COLUMN public.resource_leases.resource_id IS '被占用实例';


--
-- Name: COLUMN resource_leases.run_id; Type: COMMENT; Schema: public; Owner: testdock
--

COMMENT ON COLUMN public.resource_leases.run_id IS '自动运行归属，与调试会话二选一';


--
-- Name: COLUMN resource_leases.debug_session_id; Type: COMMENT; Schema: public; Owner: testdock
--

COMMENT ON COLUMN public.resource_leases.debug_session_id IS '人工调试归属，与运行二选一';


--
-- Name: COLUMN resource_leases.fencing_token; Type: COMMENT; Schema: public; Owner: testdock
--

COMMENT ON COLUMN public.resource_leases.fencing_token IS '分配时递增并写入实例计数器';


--
-- Name: COLUMN resource_leases.holder_id; Type: COMMENT; Schema: public; Owner: testdock
--

COMMENT ON COLUMN public.resource_leases.holder_id IS 'Agent 实例标识，不含凭据';


--
-- Name: COLUMN resource_leases.expires_at; Type: COMMENT; Schema: public; Owner: testdock
--

COMMENT ON COLUMN public.resource_leases.expires_at IS '心跳到期时间';


--
-- Name: COLUMN resource_leases.released_at; Type: COMMENT; Schema: public; Owner: testdock
--

COMMENT ON COLUMN public.resource_leases.released_at IS '显式释放，过期不等于安全释放';


--
-- Name: COLUMN resource_leases.release_reason; Type: COMMENT; Schema: public; Owner: testdock
--

COMMENT ON COLUMN public.resource_leases.release_reason IS '正常完成、取消确认、失联隔离等';


--
-- Name: COLUMN resource_leases.created_at; Type: COMMENT; Schema: public; Owner: testdock
--

COMMENT ON COLUMN public.resource_leases.created_at IS '创建时间，统一 UTC';


--
-- Name: COLUMN resource_leases.check_id; Type: COMMENT; Schema: public; Owner: testdock
--

COMMENT ON COLUMN public.resource_leases.check_id IS '短检查（device_checks）通道；与 run_id/debug_session_id 三选一';


--
-- Name: resource_profiles; Type: TABLE; Schema: public; Owner: testdock
--

CREATE TABLE public.resource_profiles (
    id uuid NOT NULL,
    project_id uuid NOT NULL,
    platform text NOT NULL,
    name text NOT NULL,
    fingerprint text NOT NULL,
    spec jsonb NOT NULL,
    created_at timestamp with time zone DEFAULT now() NOT NULL,
    CONSTRAINT ck_resource_profiles_fingerprint_hex64 CHECK ((fingerprint ~ '^[0-9a-f]{64}$'::text)),
    CONSTRAINT ck_resource_profiles_platform_allowed CHECK ((platform = ANY (ARRAY['android'::text, 'ios'::text, 'web'::text]))),
    CONSTRAINT ck_resource_profiles_spec_object CHECK ((jsonb_typeof(spec) = 'object'::text))
);


ALTER TABLE public.resource_profiles OWNER TO testdock;

--
-- Name: TABLE resource_profiles; Type: COMMENT; Schema: public; Owner: testdock
--

COMMENT ON TABLE public.resource_profiles IS '不可变的可比性档案：系统、设备或浏览器、采集器、分辨率、指标版本。 档案内容变化新增记录，不覆盖旧记录；性能比较还须校验应用、场景和指标口径。';


--
-- Name: COLUMN resource_profiles.id; Type: COMMENT; Schema: public; Owner: testdock
--

COMMENT ON COLUMN public.resource_profiles.id IS '服务端生成 UUID';


--
-- Name: COLUMN resource_profiles.project_id; Type: COMMENT; Schema: public; Owner: testdock
--

COMMENT ON COLUMN public.resource_profiles.project_id IS '项目归属';


--
-- Name: COLUMN resource_profiles.platform; Type: COMMENT; Schema: public; Owner: testdock
--

COMMENT ON COLUMN public.resource_profiles.platform IS '目标端';


--
-- Name: COLUMN resource_profiles.name; Type: COMMENT; Schema: public; Owner: testdock
--

COMMENT ON COLUMN public.resource_profiles.name IS '档案展示名';


--
-- Name: COLUMN resource_profiles.fingerprint; Type: COMMENT; Schema: public; Owner: testdock
--

COMMENT ON COLUMN public.resource_profiles.fingerprint IS '规范化档案的 SHA-256';


--
-- Name: COLUMN resource_profiles.spec; Type: COMMENT; Schema: public; Owner: testdock
--

COMMENT ON COLUMN public.resource_profiles.spec IS '结构化档案及 schemaVersion';


--
-- Name: COLUMN resource_profiles.created_at; Type: COMMENT; Schema: public; Owner: testdock
--

COMMENT ON COLUMN public.resource_profiles.created_at IS '创建时间，统一 UTC';


--
-- Name: run_components; Type: TABLE; Schema: public; Owner: testdock
--

CREATE TABLE public.run_components (
    id uuid NOT NULL,
    project_id uuid NOT NULL,
    run_id uuid NOT NULL,
    kind text NOT NULL,
    adapter_key text NOT NULL,
    adapter_version text NOT NULL,
    external_run_id text,
    state text NOT NULL,
    outcome text,
    summary jsonb DEFAULT '{}'::jsonb NOT NULL,
    created_at timestamp with time zone DEFAULT now() NOT NULL,
    reason_code text,
    CONSTRAINT ck_run_components_kind_allowed CHECK ((kind = ANY (ARRAY['ui'::text, 'performance'::text]))),
    CONSTRAINT ck_run_components_outcome_allowed CHECK ((outcome = ANY (ARRAY['passed'::text, 'failed'::text, 'not_tested'::text]))),
    CONSTRAINT ck_run_components_reason_code_required CHECK (((outcome <> 'not_tested'::text) OR (reason_code IS NOT NULL))),
    CONSTRAINT ck_run_components_state_allowed CHECK ((state = ANY (ARRAY['pending'::text, 'running'::text, 'completed'::text, 'errored'::text, 'cancelled'::text]))),
    CONSTRAINT ck_run_components_state_outcome_pair CHECK ((((state = 'completed'::text) AND (outcome IS NOT NULL)) OR ((state <> 'completed'::text) AND (outcome IS NULL)))),
    CONSTRAINT ck_run_components_summary_object CHECK ((jsonb_typeof(summary) = 'object'::text))
);


ALTER TABLE public.run_components OWNER TO testdock;

--
-- Name: TABLE run_components; Type: COMMENT; Schema: public; Owner: testdock
--

COMMENT ON TABLE public.run_components IS '一次运行下的 UI/性能子结果。联动共用运行和租约，分别保留结论。';


--
-- Name: COLUMN run_components.id; Type: COMMENT; Schema: public; Owner: testdock
--

COMMENT ON COLUMN public.run_components.id IS '服务端生成 UUID';


--
-- Name: COLUMN run_components.project_id; Type: COMMENT; Schema: public; Owner: testdock
--

COMMENT ON COLUMN public.run_components.project_id IS '项目归属';


--
-- Name: COLUMN run_components.run_id; Type: COMMENT; Schema: public; Owner: testdock
--

COMMENT ON COLUMN public.run_components.run_id IS '平台运行';


--
-- Name: COLUMN run_components.kind; Type: COMMENT; Schema: public; Owner: testdock
--

COMMENT ON COLUMN public.run_components.kind IS '子任务能力';


--
-- Name: COLUMN run_components.adapter_key; Type: COMMENT; Schema: public; Owner: testdock
--

COMMENT ON COLUMN public.run_components.adapter_key IS '适配器名';


--
-- Name: COLUMN run_components.adapter_version; Type: COMMENT; Schema: public; Owner: testdock
--

COMMENT ON COLUMN public.run_components.adapter_version IS '适配器版本';


--
-- Name: COLUMN run_components.external_run_id; Type: COMMENT; Schema: public; Owner: testdock
--

COMMENT ON COLUMN public.run_components.external_run_id IS '组件原始 runId';


--
-- Name: COLUMN run_components.state; Type: COMMENT; Schema: public; Owner: testdock
--

COMMENT ON COLUMN public.run_components.state IS '组件状态';


--
-- Name: COLUMN run_components.outcome; Type: COMMENT; Schema: public; Owner: testdock
--

COMMENT ON COLUMN public.run_components.outcome IS '测试结论';


--
-- Name: COLUMN run_components.summary; Type: COMMENT; Schema: public; Owner: testdock
--

COMMENT ON COLUMN public.run_components.summary IS '计数、警告、完整性、原始 schemaVersion';


--
-- Name: COLUMN run_components.created_at; Type: COMMENT; Schema: public; Owner: testdock
--

COMMENT ON COLUMN public.run_components.created_at IS '创建时间，统一 UTC';


--
-- Name: run_events; Type: TABLE; Schema: public; Owner: testdock
--

CREATE TABLE public.run_events (
    id uuid NOT NULL,
    project_id uuid NOT NULL,
    run_id uuid NOT NULL,
    sequence bigint NOT NULL,
    source_key text NOT NULL,
    source_event_id text NOT NULL,
    event_type text NOT NULL,
    payload jsonb DEFAULT '{}'::jsonb NOT NULL,
    occurred_at timestamp with time zone NOT NULL,
    created_at timestamp with time zone DEFAULT now() NOT NULL,
    CONSTRAINT ck_run_events_payload_object CHECK ((jsonb_typeof(payload) = 'object'::text)),
    CONSTRAINT ck_run_events_sequence_positive CHECK ((sequence > 0))
);


ALTER TABLE public.run_events OWNER TO testdock;

--
-- Name: TABLE run_events; Type: COMMENT; Schema: public; Owner: testdock
--

COMMENT ON TABLE public.run_events IS '状态变化、步骤标记、接入事件按运行顺序追加，支持断线续看。';


--
-- Name: COLUMN run_events.id; Type: COMMENT; Schema: public; Owner: testdock
--

COMMENT ON COLUMN public.run_events.id IS '服务端生成 UUID';


--
-- Name: COLUMN run_events.project_id; Type: COMMENT; Schema: public; Owner: testdock
--

COMMENT ON COLUMN public.run_events.project_id IS '项目归属';


--
-- Name: COLUMN run_events.run_id; Type: COMMENT; Schema: public; Owner: testdock
--

COMMENT ON COLUMN public.run_events.run_id IS '运行';


--
-- Name: COLUMN run_events.sequence; Type: COMMENT; Schema: public; Owner: testdock
--

COMMENT ON COLUMN public.run_events.sequence IS '服务端在运行锁内分配的顺序号';


--
-- Name: COLUMN run_events.source_key; Type: COMMENT; Schema: public; Owner: testdock
--

COMMENT ON COLUMN public.run_events.source_key IS '事件生产者';


--
-- Name: COLUMN run_events.source_event_id; Type: COMMENT; Schema: public; Owner: testdock
--

COMMENT ON COLUMN public.run_events.source_event_id IS '生产者侧幂等事件 ID';


--
-- Name: COLUMN run_events.event_type; Type: COMMENT; Schema: public; Owner: testdock
--

COMMENT ON COLUMN public.run_events.event_type IS '状态、步骤标记或警告类型';


--
-- Name: COLUMN run_events.payload; Type: COMMENT; Schema: public; Owner: testdock
--

COMMENT ON COLUMN public.run_events.payload IS '小体积脱敏负载；完整日志走 artifacts';


--
-- Name: COLUMN run_events.occurred_at; Type: COMMENT; Schema: public; Owner: testdock
--

COMMENT ON COLUMN public.run_events.occurred_at IS '事件发生时间';


--
-- Name: COLUMN run_events.created_at; Type: COMMENT; Schema: public; Owner: testdock
--

COMMENT ON COLUMN public.run_events.created_at IS '创建时间，统一 UTC';


--
-- Name: suite_versions; Type: TABLE; Schema: public; Owner: testdock
--

CREATE TABLE public.suite_versions (
    id uuid NOT NULL,
    project_id uuid NOT NULL,
    application_id uuid NOT NULL,
    suite_id uuid NOT NULL,
    version integer NOT NULL,
    source_ref text NOT NULL,
    source_commit text NOT NULL,
    manifest jsonb NOT NULL,
    created_at timestamp with time zone DEFAULT now() NOT NULL,
    CONSTRAINT ck_suite_versions_manifest_object CHECK ((jsonb_typeof(manifest) = 'object'::text)),
    CONSTRAINT ck_suite_versions_version_positive CHECK ((version > 0))
);


ALTER TABLE public.suite_versions OWNER TO testdock;

--
-- Name: TABLE suite_versions; Type: COMMENT; Schema: public; Owner: testdock
--

COMMENT ON TABLE public.suite_versions IS '固定仓库、提交及选择器，旧运行可追溯到当时的用例。';


--
-- Name: COLUMN suite_versions.id; Type: COMMENT; Schema: public; Owner: testdock
--

COMMENT ON COLUMN public.suite_versions.id IS '服务端生成 UUID';


--
-- Name: COLUMN suite_versions.project_id; Type: COMMENT; Schema: public; Owner: testdock
--

COMMENT ON COLUMN public.suite_versions.project_id IS '项目归属';


--
-- Name: COLUMN suite_versions.application_id; Type: COMMENT; Schema: public; Owner: testdock
--

COMMENT ON COLUMN public.suite_versions.application_id IS '应用关联约束';


--
-- Name: COLUMN suite_versions.suite_id; Type: COMMENT; Schema: public; Owner: testdock
--

COMMENT ON COLUMN public.suite_versions.suite_id IS '逻辑套件';


--
-- Name: COLUMN suite_versions.version; Type: COMMENT; Schema: public; Owner: testdock
--

COMMENT ON COLUMN public.suite_versions.version IS '套件修订序号';


--
-- Name: COLUMN suite_versions.source_ref; Type: COMMENT; Schema: public; Owner: testdock
--

COMMENT ON COLUMN public.suite_versions.source_ref IS '不含凭据的仓库或受控用例来源';


--
-- Name: COLUMN suite_versions.source_commit; Type: COMMENT; Schema: public; Owner: testdock
--

COMMENT ON COLUMN public.suite_versions.source_commit IS '固定提交标识';


--
-- Name: COLUMN suite_versions.manifest; Type: COMMENT; Schema: public; Owner: testdock
--

COMMENT ON COLUMN public.suite_versions.manifest IS '用例 key、入口、场景及 schemaVersion';


--
-- Name: COLUMN suite_versions.created_at; Type: COMMENT; Schema: public; Owner: testdock
--

COMMENT ON COLUMN public.suite_versions.created_at IS '创建时间，统一 UTC';


--
-- Name: task_request_keys; Type: TABLE; Schema: public; Owner: testdock
--

CREATE TABLE public.task_request_keys (
    id uuid NOT NULL,
    project_id uuid NOT NULL,
    request_key text NOT NULL,
    fingerprint text NOT NULL,
    task_id uuid NOT NULL,
    created_at timestamp with time zone DEFAULT now() NOT NULL,
    CONSTRAINT ck_task_request_keys_request_key_not_empty CHECK ((length(request_key) > 0))
);


ALTER TABLE public.task_request_keys OWNER TO testdock;

--
-- Name: TABLE task_request_keys; Type: COMMENT; Schema: public; Owner: testdock
--

COMMENT ON TABLE public.task_request_keys IS '任务创建幂等键；跨重启复用';


--
-- Name: COLUMN task_request_keys.request_key; Type: COMMENT; Schema: public; Owner: testdock
--

COMMENT ON COLUMN public.task_request_keys.request_key IS '项目内请求幂等键';


--
-- Name: COLUMN task_request_keys.fingerprint; Type: COMMENT; Schema: public; Owner: testdock
--

COMMENT ON COLUMN public.task_request_keys.fingerprint IS '规范化创建内容摘要';


--
-- Name: COLUMN task_request_keys.task_id; Type: COMMENT; Schema: public; Owner: testdock
--

COMMENT ON COLUMN public.task_request_keys.task_id IS '键首次绑定的任务';


--
-- Name: task_revisions; Type: TABLE; Schema: public; Owner: testdock
--

CREATE TABLE public.task_revisions (
    id uuid NOT NULL,
    project_id uuid NOT NULL,
    application_id uuid NOT NULL,
    task_id uuid NOT NULL,
    revision integer NOT NULL,
    environment_id uuid NOT NULL,
    build_id uuid,
    suite_version_id uuid,
    test_type text NOT NULL,
    readiness text DEFAULT 'draft'::text NOT NULL,
    config jsonb NOT NULL,
    created_by text NOT NULL,
    created_at timestamp with time zone DEFAULT now() NOT NULL,
    CONSTRAINT ck_task_revisions_config_object CHECK ((jsonb_typeof(config) = 'object'::text)),
    CONSTRAINT ck_task_revisions_readiness_allowed CHECK ((readiness = ANY (ARRAY['draft'::text, 'validated'::text]))),
    CONSTRAINT ck_task_revisions_readiness_requires_build_and_suite CHECK (((readiness = 'draft'::text) OR ((build_id IS NOT NULL) AND (suite_version_id IS NOT NULL)))),
    CONSTRAINT ck_task_revisions_revision_positive CHECK ((revision > 0)),
    CONSTRAINT ck_task_revisions_test_type_allowed CHECK ((test_type = ANY (ARRAY['ui'::text, 'performance'::text, 'joint'::text])))
);


ALTER TABLE public.task_revisions OWNER TO testdock;

--
-- Name: TABLE task_revisions; Type: COMMENT; Schema: public; Owner: testdock
--

COMMENT ON TABLE public.task_revisions IS '每次保存新增不可变修订；运行只引用已验证修订。 只有字段完整不代表可运行；适配器能力、套件类型及配置 schema 仍由提交事务验证。';


--
-- Name: COLUMN task_revisions.id; Type: COMMENT; Schema: public; Owner: testdock
--

COMMENT ON COLUMN public.task_revisions.id IS '服务端生成 UUID';


--
-- Name: COLUMN task_revisions.project_id; Type: COMMENT; Schema: public; Owner: testdock
--

COMMENT ON COLUMN public.task_revisions.project_id IS '项目归属';


--
-- Name: COLUMN task_revisions.application_id; Type: COMMENT; Schema: public; Owner: testdock
--

COMMENT ON COLUMN public.task_revisions.application_id IS '应用关联约束';


--
-- Name: COLUMN task_revisions.task_id; Type: COMMENT; Schema: public; Owner: testdock
--

COMMENT ON COLUMN public.task_revisions.task_id IS '逻辑任务';


--
-- Name: COLUMN task_revisions.revision; Type: COMMENT; Schema: public; Owner: testdock
--

COMMENT ON COLUMN public.task_revisions.revision IS '配置版本号';


--
-- Name: COLUMN task_revisions.environment_id; Type: COMMENT; Schema: public; Owner: testdock
--

COMMENT ON COLUMN public.task_revisions.environment_id IS '环境';


--
-- Name: COLUMN task_revisions.build_id; Type: COMMENT; Schema: public; Owner: testdock
--

COMMENT ON COLUMN public.task_revisions.build_id IS '草稿可缺构建，提交前校验';


--
-- Name: COLUMN task_revisions.suite_version_id; Type: COMMENT; Schema: public; Owner: testdock
--

COMMENT ON COLUMN public.task_revisions.suite_version_id IS '草稿可缺套件版本，提交前校验';


--
-- Name: COLUMN task_revisions.test_type; Type: COMMENT; Schema: public; Owner: testdock
--

COMMENT ON COLUMN public.task_revisions.test_type IS '类型快照';


--
-- Name: COLUMN task_revisions.readiness; Type: COMMENT; Schema: public; Owner: testdock
--

COMMENT ON COLUMN public.task_revisions.readiness IS '配置校验状态';


--
-- Name: COLUMN task_revisions.config; Type: COMMENT; Schema: public; Owner: testdock
--

COMMENT ON COLUMN public.task_revisions.config IS '脱敏配置、资源需求、适配器及 schemaVersion';


--
-- Name: COLUMN task_revisions.created_by; Type: COMMENT; Schema: public; Owner: testdock
--

COMMENT ON COLUMN public.task_revisions.created_by IS '保存者引用';


--
-- Name: COLUMN task_revisions.created_at; Type: COMMENT; Schema: public; Owner: testdock
--

COMMENT ON COLUMN public.task_revisions.created_at IS '创建时间，统一 UTC';


--
-- Name: test_runs; Type: TABLE; Schema: public; Owner: testdock
--

CREATE TABLE public.test_runs (
    id uuid NOT NULL,
    project_id uuid NOT NULL,
    application_id uuid NOT NULL,
    platform text NOT NULL,
    revision_id uuid NOT NULL,
    parent_run_id uuid,
    request_key text NOT NULL,
    state text DEFAULT 'queued'::text NOT NULL,
    outcome text,
    reason_code text,
    resource_id uuid,
    profile_id uuid,
    config_snapshot jsonb NOT NULL,
    lock_version integer DEFAULT 1 NOT NULL,
    started_at timestamp with time zone,
    ended_at timestamp with time zone,
    created_by text NOT NULL,
    created_at timestamp with time zone DEFAULT now() NOT NULL,
    not_tested_reason text,
    cancel_requested_at timestamp with time zone,
    cancel_requested_by text,
    display_no bigint NOT NULL,
    CONSTRAINT ck_test_runs_config_snapshot_object CHECK ((jsonb_typeof(config_snapshot) = 'object'::text)),
    CONSTRAINT ck_test_runs_ended_at_not_before_created CHECK (((ended_at IS NULL) OR (ended_at >= created_at))),
    CONSTRAINT ck_test_runs_ended_at_not_before_started CHECK (((ended_at IS NULL) OR (started_at IS NULL) OR (ended_at >= started_at))),
    CONSTRAINT ck_test_runs_lock_version_positive CHECK ((lock_version > 0)),
    CONSTRAINT ck_test_runs_not_tested_reason_required CHECK (((outcome <> 'not_tested'::text) OR (not_tested_reason IS NOT NULL))),
    CONSTRAINT ck_test_runs_outcome_allowed CHECK ((outcome = ANY (ARRAY['passed'::text, 'failed'::text, 'not_tested'::text]))),
    CONSTRAINT ck_test_runs_platform_allowed CHECK ((platform = ANY (ARRAY['android'::text, 'ios'::text, 'web'::text]))),
    CONSTRAINT ck_test_runs_resource_id_profile_pair CHECK (((resource_id IS NULL) = (profile_id IS NULL))),
    CONSTRAINT ck_test_runs_started_at_not_before_created CHECK (((started_at IS NULL) OR (started_at >= created_at))),
    CONSTRAINT ck_test_runs_state_allowed CHECK ((state = ANY (ARRAY['queued'::text, 'dispatching'::text, 'running'::text, 'finalizing'::text, 'completed'::text, 'errored'::text, 'cancelled'::text]))),
    CONSTRAINT ck_test_runs_state_executing_needs_resource CHECK (((state <> ALL (ARRAY['running'::text, 'finalizing'::text, 'completed'::text])) OR ((resource_id IS NOT NULL) AND (started_at IS NOT NULL)))),
    CONSTRAINT ck_test_runs_state_outcome_pair CHECK ((((state = 'completed'::text) AND (outcome IS NOT NULL)) OR ((state <> 'completed'::text) AND (outcome IS NULL)))),
    CONSTRAINT ck_test_runs_state_terminal_needs_ended_at CHECK (((state = ANY (ARRAY['completed'::text, 'errored'::text, 'cancelled'::text])) = (ended_at IS NOT NULL)))
);


ALTER TABLE public.test_runs OWNER TO testdock;

--
-- Name: TABLE test_runs; Type: COMMENT; Schema: public; Owner: testdock
--

COMMENT ON TABLE public.test_runs IS '一次提交或重跑对应一行，保留执行状态、最终结论和当时配置。 终态只追加新运行或新试算，不改原始结论；这种不可变性及状态转换须由后端写入边界实现。';


--
-- Name: COLUMN test_runs.id; Type: COMMENT; Schema: public; Owner: testdock
--

COMMENT ON COLUMN public.test_runs.id IS '服务端生成 UUID';


--
-- Name: COLUMN test_runs.project_id; Type: COMMENT; Schema: public; Owner: testdock
--

COMMENT ON COLUMN public.test_runs.project_id IS '项目归属';


--
-- Name: COLUMN test_runs.application_id; Type: COMMENT; Schema: public; Owner: testdock
--

COMMENT ON COLUMN public.test_runs.application_id IS '目标应用';


--
-- Name: COLUMN test_runs.platform; Type: COMMENT; Schema: public; Owner: testdock
--

COMMENT ON COLUMN public.test_runs.platform IS '目标端查询维度';


--
-- Name: COLUMN test_runs.revision_id; Type: COMMENT; Schema: public; Owner: testdock
--

COMMENT ON COLUMN public.test_runs.revision_id IS '固定任务修订';


--
-- Name: COLUMN test_runs.parent_run_id; Type: COMMENT; Schema: public; Owner: testdock
--

COMMENT ON COLUMN public.test_runs.parent_run_id IS '重跑来源；同项目同应用';


--
-- Name: COLUMN test_runs.request_key; Type: COMMENT; Schema: public; Owner: testdock
--

COMMENT ON COLUMN public.test_runs.request_key IS '项目内提交幂等键';


--
-- Name: COLUMN test_runs.state; Type: COMMENT; Schema: public; Owner: testdock
--

COMMENT ON COLUMN public.test_runs.state IS '执行状态，与测试结论分离';


--
-- Name: COLUMN test_runs.outcome; Type: COMMENT; Schema: public; Owner: testdock
--

COMMENT ON COLUMN public.test_runs.outcome IS '完成时的测试结论';


--
-- Name: COLUMN test_runs.reason_code; Type: COMMENT; Schema: public; Owner: testdock
--

COMMENT ON COLUMN public.test_runs.reason_code IS '未判定、取消或基础设施错误原因码';


--
-- Name: COLUMN test_runs.resource_id; Type: COMMENT; Schema: public; Owner: testdock
--

COMMENT ON COLUMN public.test_runs.resource_id IS '实际执行实例，排队时为空';


--
-- Name: COLUMN test_runs.profile_id; Type: COMMENT; Schema: public; Owner: testdock
--

COMMENT ON COLUMN public.test_runs.profile_id IS '实际使用的固定档案';


--
-- Name: COLUMN test_runs.config_snapshot; Type: COMMENT; Schema: public; Owner: testdock
--

COMMENT ON COLUMN public.test_runs.config_snapshot IS '固定配置、版本及脱敏环境快照';


--
-- Name: COLUMN test_runs.lock_version; Type: COMMENT; Schema: public; Owner: testdock
--

COMMENT ON COLUMN public.test_runs.lock_version IS '状态更新 CAS 版本';


--
-- Name: COLUMN test_runs.started_at; Type: COMMENT; Schema: public; Owner: testdock
--

COMMENT ON COLUMN public.test_runs.started_at IS '实际开始时间';


--
-- Name: COLUMN test_runs.ended_at; Type: COMMENT; Schema: public; Owner: testdock
--

COMMENT ON COLUMN public.test_runs.ended_at IS '终态时间';


--
-- Name: COLUMN test_runs.created_by; Type: COMMENT; Schema: public; Owner: testdock
--

COMMENT ON COLUMN public.test_runs.created_by IS '触发者引用';


--
-- Name: COLUMN test_runs.created_at; Type: COMMENT; Schema: public; Owner: testdock
--

COMMENT ON COLUMN public.test_runs.created_at IS '创建时间，统一 UTC';


--
-- Name: COLUMN test_runs.cancel_requested_at; Type: COMMENT; Schema: public; Owner: testdock
--

COMMENT ON COLUMN public.test_runs.cancel_requested_at IS '取消受理时间；持久化事实，重复受理不改写';


--
-- Name: COLUMN test_runs.cancel_requested_by; Type: COMMENT; Schema: public; Owner: testdock
--

COMMENT ON COLUMN public.test_runs.cancel_requested_by IS '取消受理人';


--
-- Name: COLUMN test_runs.display_no; Type: COMMENT; Schema: public; Owner: testdock
--

COMMENT ON COLUMN public.test_runs.display_no IS '全局展示序号，RUN-0001 由它格式化；持久分配，历史变动不重编号';


--
-- Name: test_run_display_no_seq; Type: SEQUENCE; Schema: public; Owner: testdock
--

CREATE SEQUENCE public.test_run_display_no_seq
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;


ALTER SEQUENCE public.test_run_display_no_seq OWNER TO testdock;

--
-- Name: test_run_display_no_seq; Type: SEQUENCE OWNED BY; Schema: public; Owner: testdock
--

ALTER SEQUENCE public.test_run_display_no_seq OWNED BY public.test_runs.display_no;


--
-- Name: test_suites; Type: TABLE; Schema: public; Owner: testdock
--

CREATE TABLE public.test_suites (
    id uuid NOT NULL,
    project_id uuid NOT NULL,
    application_id uuid NOT NULL,
    name text NOT NULL,
    test_type text NOT NULL,
    archived_at timestamp with time zone,
    created_at timestamp with time zone DEFAULT now() NOT NULL,
    CONSTRAINT ck_test_suites_test_type_allowed CHECK ((test_type = ANY (ARRAY['ui'::text, 'performance'::text, 'joint'::text])))
);


ALTER TABLE public.test_suites OWNER TO testdock;

--
-- Name: TABLE test_suites; Type: COMMENT; Schema: public; Owner: testdock
--

COMMENT ON TABLE public.test_suites IS '登记代码维护的 UI 用例或性能场景，不把脚本正文塞进数据库。';


--
-- Name: COLUMN test_suites.id; Type: COMMENT; Schema: public; Owner: testdock
--

COMMENT ON COLUMN public.test_suites.id IS '服务端生成 UUID';


--
-- Name: COLUMN test_suites.project_id; Type: COMMENT; Schema: public; Owner: testdock
--

COMMENT ON COLUMN public.test_suites.project_id IS '项目归属';


--
-- Name: COLUMN test_suites.application_id; Type: COMMENT; Schema: public; Owner: testdock
--

COMMENT ON COLUMN public.test_suites.application_id IS '所属应用';


--
-- Name: COLUMN test_suites.name; Type: COMMENT; Schema: public; Owner: testdock
--

COMMENT ON COLUMN public.test_suites.name IS '套件或场景名';


--
-- Name: COLUMN test_suites.test_type; Type: COMMENT; Schema: public; Owner: testdock
--

COMMENT ON COLUMN public.test_suites.test_type IS '测试类型；joint 为编排';


--
-- Name: COLUMN test_suites.archived_at; Type: COMMENT; Schema: public; Owner: testdock
--

COMMENT ON COLUMN public.test_suites.archived_at IS '归档时间';


--
-- Name: COLUMN test_suites.created_at; Type: COMMENT; Schema: public; Owner: testdock
--

COMMENT ON COLUMN public.test_suites.created_at IS '创建时间，统一 UTC';


--
-- Name: test_tasks; Type: TABLE; Schema: public; Owner: testdock
--

CREATE TABLE public.test_tasks (
    id uuid NOT NULL,
    project_id uuid NOT NULL,
    application_id uuid NOT NULL,
    name text NOT NULL,
    lifecycle text DEFAULT 'draft'::text NOT NULL,
    lock_version integer DEFAULT 1 NOT NULL,
    created_by text NOT NULL,
    updated_at timestamp with time zone DEFAULT now() NOT NULL,
    created_at timestamp with time zone DEFAULT now() NOT NULL,
    CONSTRAINT ck_test_tasks_lifecycle_allowed CHECK ((lifecycle = ANY (ARRAY['draft'::text, 'ready'::text, 'archived'::text]))),
    CONSTRAINT ck_test_tasks_lock_version_positive CHECK ((lock_version > 0))
);


ALTER TABLE public.test_tasks OWNER TO testdock;

--
-- Name: TABLE test_tasks; Type: COMMENT; Schema: public; Owner: testdock
--

COMMENT ON TABLE public.test_tasks IS '用户可编辑的逻辑任务；不存通过或失败结果。 Web/iOS 未接入时只能是 draft；计划能力不能用设备数据冒充已就绪。';


--
-- Name: COLUMN test_tasks.id; Type: COMMENT; Schema: public; Owner: testdock
--

COMMENT ON COLUMN public.test_tasks.id IS '服务端生成 UUID';


--
-- Name: COLUMN test_tasks.project_id; Type: COMMENT; Schema: public; Owner: testdock
--

COMMENT ON COLUMN public.test_tasks.project_id IS '项目归属';


--
-- Name: COLUMN test_tasks.application_id; Type: COMMENT; Schema: public; Owner: testdock
--

COMMENT ON COLUMN public.test_tasks.application_id IS '所属应用';


--
-- Name: COLUMN test_tasks.name; Type: COMMENT; Schema: public; Owner: testdock
--

COMMENT ON COLUMN public.test_tasks.name IS '任务名';


--
-- Name: COLUMN test_tasks.lifecycle; Type: COMMENT; Schema: public; Owner: testdock
--

COMMENT ON COLUMN public.test_tasks.lifecycle IS '配置生命周期，非执行状态';


--
-- Name: COLUMN test_tasks.lock_version; Type: COMMENT; Schema: public; Owner: testdock
--

COMMENT ON COLUMN public.test_tasks.lock_version IS '乐观锁版本';


--
-- Name: COLUMN test_tasks.created_by; Type: COMMENT; Schema: public; Owner: testdock
--

COMMENT ON COLUMN public.test_tasks.created_by IS '身份主体或服务账号引用';


--
-- Name: COLUMN test_tasks.updated_at; Type: COMMENT; Schema: public; Owner: testdock
--

COMMENT ON COLUMN public.test_tasks.updated_at IS '服务端更新时显式赋值';


--
-- Name: COLUMN test_tasks.created_at; Type: COMMENT; Schema: public; Owner: testdock
--

COMMENT ON COLUMN public.test_tasks.created_at IS '创建时间，统一 UTC';


--
-- Name: workspace_settings; Type: TABLE; Schema: public; Owner: testdock
--

CREATE TABLE public.workspace_settings (
    id smallint NOT NULL,
    name text NOT NULL,
    customized_at timestamp with time zone,
    updated_at timestamp with time zone DEFAULT now() NOT NULL,
    CONSTRAINT ck_workspace_settings_name_length CHECK (((char_length(btrim(name)) >= 1) AND (char_length(btrim(name)) <= 60))),
    CONSTRAINT ck_workspace_settings_singleton CHECK ((id = 1))
);


ALTER TABLE public.workspace_settings OWNER TO testdock;

--
-- Name: TABLE workspace_settings; Type: COMMENT; Schema: public; Owner: testdock
--

COMMENT ON TABLE public.workspace_settings IS '工作空间设置（单行）：唯一工作空间的显示名称';


--
-- Name: COLUMN workspace_settings.id; Type: COMMENT; Schema: public; Owner: testdock
--

COMMENT ON COLUMN public.workspace_settings.id IS '单行固定值 1';


--
-- Name: COLUMN workspace_settings.name; Type: COMMENT; Schema: public; Owner: testdock
--

COMMENT ON COLUMN public.workspace_settings.name IS '工作空间显示名称（去空白后 1-60 字符）';


--
-- Name: COLUMN workspace_settings.customized_at; Type: COMMENT; Schema: public; Owner: testdock
--

COMMENT ON COLUMN public.workspace_settings.customized_at IS '用户显式改名时间；NULL 表示仍是默认名称';


--
-- Name: COLUMN workspace_settings.updated_at; Type: COMMENT; Schema: public; Owner: testdock
--

COMMENT ON COLUMN public.workspace_settings.updated_at IS '最近更新时间';


--
-- Name: workspace_settings_id_seq; Type: SEQUENCE; Schema: public; Owner: testdock
--

CREATE SEQUENCE public.workspace_settings_id_seq
    AS smallint
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;


ALTER SEQUENCE public.workspace_settings_id_seq OWNER TO testdock;

--
-- Name: workspace_settings_id_seq; Type: SEQUENCE OWNED BY; Schema: public; Owner: testdock
--

ALTER SEQUENCE public.workspace_settings_id_seq OWNED BY public.workspace_settings.id;


--
-- Name: test_runs display_no; Type: DEFAULT; Schema: public; Owner: testdock
--

ALTER TABLE ONLY public.test_runs ALTER COLUMN display_no SET DEFAULT nextval('public.test_run_display_no_seq'::regclass);


--
-- Name: workspace_settings id; Type: DEFAULT; Schema: public; Owner: testdock
--

ALTER TABLE ONLY public.workspace_settings ALTER COLUMN id SET DEFAULT nextval('public.workspace_settings_id_seq'::regclass);


--
-- Data for Name: alembic_version; Type: TABLE DATA; Schema: public; Owner: testdock
--

COPY public.alembic_version (version_num) FROM stdin;
0011
\.


--
-- Data for Name: app_builds; Type: TABLE DATA; Schema: public; Owner: testdock
--

COPY public.app_builds (id, project_id, application_id, version, build_key, source_commit, storage_key, sha256, metadata, created_at) FROM stdin;
9ad14e07-1190-409e-b02c-684ed932f5dd	540f2fa1-53f8-4e43-9841-8eb881a0c529	a9feb4f2-9d51-4d6e-9ea1-aeb423901f5f	15.0.14	315000014	\N	\N	\N	{"identity": {"state": "confirmed", "checks": [{"items": [{"name": "package_name", "status": "match", "expected": "com.miui.calculator", "observed": "com.miui.calculator"}, {"name": "version_name", "status": "match", "expected": "15.0.14", "observed": "15.0.14"}, {"name": "version_code", "status": "observed", "expected": null, "observed": 315000014}], "device": {"serial": "749622c9", "resource_id": "fab1ee61-4ece-4fc5-92bc-4bc0b13427a2"}, "result": "match", "purpose": "manual", "blocking": [], "check_id": "b1bd262e-abbd-4fec-8442-c97aa27bc0fa", "expected": {"package_name": "com.miui.calculator", "version_code": null, "version_name": "15.0.14"}, "observed": {"package_name": "com.miui.calculator", "version_code": 315000014, "version_name": "15.0.14"}, "resource": {"id": "fab1ee61-4ece-4fc5-92bc-4bc0b13427a2", "serial": "749622c9"}, "test_type": "ui", "checked_at": "2026-11-08T12:11:01.549094+00:00", "superseded_at": null, "superseded_by": null, "identity_state": "pending", "execution_allowed": true, "verification_note": "身份核对等级：设备上已安装包的包名、versionName 与 versionCode（只读读取）；未验证 APK 文件摘要，sha256 仅为登记声明。", "verification_level": "package_identity_observed", "apk_digest_verified": false}], "baseline": {"check_id": "b1bd262e-abbd-4fec-8442-c97aa27bc0fa", "resource": {"id": "fab1ee61-4ece-4fc5-92bc-4bc0b13427a2", "serial": "749622c9"}, "confirmed_at": "2026-11-08T12:12:08.938872+00:00", "package_name": "com.miui.calculator", "version_code": 315000014, "version_name": "15.0.14"}, "confirmed_at": "2026-11-08T12:12:08.938872+00:00", "verification_level": "package_identity_observed", "apk_digest_verified": false}}	2026-11-08 20:10:04.225976+08
\.


--
-- Data for Name: applications; Type: TABLE DATA; Schema: public; Owner: testdock
--

COPY public.applications (id, project_id, platform, name, identifier, archived_at, created_at, origin) FROM stdin;
a9feb4f2-9d51-4d6e-9ea1-aeb423901f5f	540f2fa1-53f8-4e43-9841-8eb881a0c529	android	计算器	com.miui.calculator	\N	2026-11-08 20:02:59.51475+08	\N
4a9b66e3-1752-4de8-a130-ea8c9161f906	5000b728-a110-4878-bcc1-41725ae5603b	android	计算器	com.miui.calculator	\N	2026-11-08 21:29:02.619958+08	\N
\.


--
-- Data for Name: artifacts; Type: TABLE DATA; Schema: public; Owner: testdock
--

COPY public.artifacts (id, project_id, run_id, component_id, logical_key, kind, storage_key, mime_type, byte_size, sha256, schema_version, availability, expires_at, created_at) FROM stdin;
cb51cf46-3c42-4cdc-8712-f5bbd0181032	540f2fa1-53f8-4e43-9841-8eb881a0c529	8dd151a4-cfdb-45be-8775-94a84b86c834	\N	actions.jsonl	report_json	8dd151a4-cfdb-45be-8775-94a84b86c834/actions.jsonl	application/octet-stream	553	943ebad13fcb13b626cdaeba5f5d055b8e180a4d0a1b9a8b332054d7252e5b90	1	available	\N	2026-11-08 20:18:08.719638+08
24820679-f3bd-44ad-b838-c3e9d7ccf61e	540f2fa1-53f8-4e43-9841-8eb881a0c529	8dd151a4-cfdb-45be-8775-94a84b86c834	\N	junit.xml	other	8dd151a4-cfdb-45be-8775-94a84b86c834/junit.xml	text/xml	1502	806419b09631a4299248988d011e06308d17978f8a68143fd611717e6b47d734	1	available	\N	2026-11-08 20:18:08.719638+08
69d68faa-35e7-4f77-a350-d169130cbd88	540f2fa1-53f8-4e43-9841-8eb881a0c529	8dd151a4-cfdb-45be-8775-94a84b86c834	\N	mobile-config.toml	other	8dd151a4-cfdb-45be-8775-94a84b86c834/mobile-config.toml	application/octet-stream	271	dbf2d09be6c0056e6eb592d8be6970121309952106d880904edba405dfef0bb9	1	available	\N	2026-11-08 20:18:08.719638+08
308320da-377e-4019-9779-2367f9aa26a9	540f2fa1-53f8-4e43-9841-8eb881a0c529	8dd151a4-cfdb-45be-8775-94a84b86c834	\N	runs/main.json	report_json	8dd151a4-cfdb-45be-8775-94a84b86c834/runs/main.json	application/json	143	53ee3d20e8ae94a3b331cb43fe7ddc0b0baa135d2c6f2fdbd1facbea60ed6be0	1	available	\N	2026-11-08 20:18:08.719638+08
f6b4d271-85b6-4b1e-b788-4d10f4fd5bbc	540f2fa1-53f8-4e43-9841-8eb881a0c529	ba117777-b04d-48e0-ba3d-7af289d66244	\N	actions.jsonl	report_json	ba117777-b04d-48e0-ba3d-7af289d66244/actions.jsonl	application/octet-stream	553	8a66497647c983fe7e88e5946c81b7ccefce4c1d6dc00a57a399b96746701e89	1	available	\N	2026-11-08 20:46:22.70876+08
1bbd0421-e5a1-490d-ae08-cfe7af414d08	540f2fa1-53f8-4e43-9841-8eb881a0c529	ba117777-b04d-48e0-ba3d-7af289d66244	\N	junit.xml	other	ba117777-b04d-48e0-ba3d-7af289d66244/junit.xml	text/xml	1502	7aa85c9c91383792fcabe5c1de40fd97f470fd9cc0eeeaef0334bf532216a0bd	1	available	\N	2026-11-08 20:46:22.70876+08
93ea547a-eefb-4dbb-bd9f-a653b03535f5	540f2fa1-53f8-4e43-9841-8eb881a0c529	ba117777-b04d-48e0-ba3d-7af289d66244	\N	mobile-config.toml	other	ba117777-b04d-48e0-ba3d-7af289d66244/mobile-config.toml	application/octet-stream	271	b20922e5d5ca81c6da444e436e0f1c906bd61542db0c9274d41fb8d64d04a3ad	1	available	\N	2026-11-08 20:46:22.70876+08
143f4807-056a-4c11-854e-af80e50d85c9	540f2fa1-53f8-4e43-9841-8eb881a0c529	ba117777-b04d-48e0-ba3d-7af289d66244	\N	runs/main.json	report_json	ba117777-b04d-48e0-ba3d-7af289d66244/runs/main.json	application/json	142	f5ff8da78bef92f1fa8b0ae46a2e1db9adc5591b64cb2f0bcb804c9f586af8d0	1	available	\N	2026-11-08 20:46:22.70876+08
2b88fc3f-514f-4471-bcda-670cddd5ee27	540f2fa1-53f8-4e43-9841-8eb881a0c529	7ca839a0-d955-4a7e-aa64-290382c63453	\N	perf.sqlite3	other	7ca839a0-d955-4a7e-aa64-290382c63453/perf.sqlite3	application/octet-stream	4096	42f67cde08aaa4db17432058fdd3521a7199a1dfd4afe740ca486d6b49226302	1	available	\N	2026-11-08 20:53:33.424816+08
f5a08244-138e-4dc0-9cc0-88e2fab3966b	540f2fa1-53f8-4e43-9841-8eb881a0c529	7ca839a0-d955-4a7e-aa64-290382c63453	\N	perf.sqlite3-shm	other	7ca839a0-d955-4a7e-aa64-290382c63453/perf.sqlite3-shm	application/octet-stream	32768	59acf04eb75f01a1d32c82b69b737a6d9741f8566dd7d8a3be1226e5181f48ce	1	available	\N	2026-11-08 20:53:33.424816+08
6aab8ebc-5e47-4e8d-852d-049347423225	540f2fa1-53f8-4e43-9841-8eb881a0c529	7ca839a0-d955-4a7e-aa64-290382c63453	\N	perf.sqlite3-wal	other	7ca839a0-d955-4a7e-aa64-290382c63453/perf.sqlite3-wal	application/octet-stream	98912	896297e8fdab540320d56a6b568aa13011469c62567ff447fa66b56ea513bb25	1	available	\N	2026-11-08 20:53:33.424816+08
e4190f49-dcf5-4e3b-89a7-e57895a2eb8a	540f2fa1-53f8-4e43-9841-8eb881a0c529	7ca839a0-d955-4a7e-aa64-290382c63453	\N	report.json	report_json	7ca839a0-d955-4a7e-aa64-290382c63453/report.json	application/json	33284	4e2bc5ee6abc316e82669e4c8fcbf6f791defa909c5fd112d525e9e99cbf3b0a	1	available	\N	2026-11-08 20:53:33.424816+08
23b984a3-0cc7-4913-90fd-799c82abf5bc	540f2fa1-53f8-4e43-9841-8eb881a0c529	7ca839a0-d955-4a7e-aa64-290382c63453	\N	perf/7ca839a0-d955-4a7e-aa64-290382c63453/meta.json	report_json	7ca839a0-d955-4a7e-aa64-290382c63453/perf/7ca839a0-d955-4a7e-aa64-290382c63453/meta.json	application/json	1114	2989373de768db34b2e276b98847a7c948530af6fd97f8ff37e54e8f2bf04ca0	1	available	\N	2026-11-08 20:53:33.424816+08
acb86f78-da77-459c-a25e-d226bdec13b7	540f2fa1-53f8-4e43-9841-8eb881a0c529	7ca839a0-d955-4a7e-aa64-290382c63453	\N	perf/7ca839a0-d955-4a7e-aa64-290382c63453/report.html	report_html	7ca839a0-d955-4a7e-aa64-290382c63453/perf/7ca839a0-d955-4a7e-aa64-290382c63453/report.html	text/html	1057527	b7ac2626da15212f76d940a5b342f54c5231afae679c65fd024727a1cbb73e67	1	available	\N	2026-11-08 20:53:33.424816+08
347a71b1-6094-4e04-85e0-d04c596eee75	540f2fa1-53f8-4e43-9841-8eb881a0c529	7ca839a0-d955-4a7e-aa64-290382c63453	\N	perf/7ca839a0-d955-4a7e-aa64-290382c63453/report.json	report_json	7ca839a0-d955-4a7e-aa64-290382c63453/perf/7ca839a0-d955-4a7e-aa64-290382c63453/report.json	application/json	33286	0b47460522e2502bb98687959592c81e2bd7761426ad28c95bbec167aed9da3a	1	available	\N	2026-11-08 20:53:33.424816+08
784c452c-4b0b-42cb-8328-e30fc85e2775	540f2fa1-53f8-4e43-9841-8eb881a0c529	7ca839a0-d955-4a7e-aa64-290382c63453	\N	perf/7ca839a0-d955-4a7e-aa64-290382c63453/artifacts/app_process-main-20746_CPU_4ab0dda64ef0ee99_1794142381927_1794142413586.csv	other	7ca839a0-d955-4a7e-aa64-290382c63453/perf/7ca839a0-d955-4a7e-aa64-290382c63453/artifacts/app_process-main-20746_CPU_4ab0dda64ef0ee99_1794142381927_1794142413586.csv	text/csv	1898	d391fcd9272d434ac525d7fe3a1f5030b1725e1d8ebeceb7ed178f0f9ff3848e	1	available	\N	2026-11-08 20:53:33.424816+08
784415d5-9321-4566-9375-2c9a2d2c8465	540f2fa1-53f8-4e43-9841-8eb881a0c529	7ca839a0-d955-4a7e-aa64-290382c63453	\N	perf/7ca839a0-d955-4a7e-aa64-290382c63453/artifacts/fps_FPS_7f0cfdad4bb20c28_1794142381927_1794142413589.csv	other	7ca839a0-d955-4a7e-aa64-290382c63453/perf/7ca839a0-d955-4a7e-aa64-290382c63453/artifacts/fps_FPS_7f0cfdad4bb20c28_1794142381927_1794142413589.csv	text/csv	1525	2b5f6fbdfb0795ac47bcdfc29ac33846181f7bc3c6c1b3f6a5a4290ad503d9d3	1	available	\N	2026-11-08 20:53:33.424816+08
d5578864-88e0-4968-b123-abc35f058a2c	540f2fa1-53f8-4e43-9841-8eb881a0c529	7ca839a0-d955-4a7e-aa64-290382c63453	\N	perf/7ca839a0-d955-4a7e-aa64-290382c63453/artifacts/frame_delay_count_FPS_818e82e5512ee305_1794142381927_1794142413589.csv	other	7ca839a0-d955-4a7e-aa64-290382c63453/perf/7ca839a0-d955-4a7e-aa64-290382c63453/artifacts/frame_delay_count_FPS_818e82e5512ee305_1794142381927_1794142413589.csv	text/csv	1465	7aec08905fd1976510285b534f12967c72e97fd2c4b43d0adee2c49e3a7521bc	1	available	\N	2026-11-08 20:53:33.424816+08
46ef4bdc-8b7a-4b7b-8f66-726a5280d8fa	540f2fa1-53f8-4e43-9841-8eb881a0c529	7ca839a0-d955-4a7e-aa64-290382c63453	\N	perf/7ca839a0-d955-4a7e-aa64-290382c63453/artifacts/frame_delay_max_FPS_2bd2769d504d958e_1794142381927_1794142413589.csv	other	7ca839a0-d955-4a7e-aa64-290382c63453/perf/7ca839a0-d955-4a7e-aa64-290382c63453/artifacts/frame_delay_max_FPS_2bd2769d504d958e_1794142381927_1794142413589.csv	text/csv	1501	909155edc58e77eabb130a8a425021c33f69bba3d534e1c8fc5c42b5d86764f5	1	available	\N	2026-11-08 20:53:33.424816+08
c661ec76-870f-403c-a60c-443733536352	540f2fa1-53f8-4e43-9841-8eb881a0c529	7ca839a0-d955-4a7e-aa64-290382c63453	\N	perf/7ca839a0-d955-4a7e-aa64-290382c63453/artifacts/frame_delay_ratio_FPS_e87078755f8aba34_1794142381927_1794142413589.csv	other	7ca839a0-d955-4a7e-aa64-290382c63453/perf/7ca839a0-d955-4a7e-aa64-290382c63453/artifacts/frame_delay_ratio_FPS_e87078755f8aba34_1794142381927_1794142413589.csv	text/csv	1624	cfe54347c0280530a35b70f51aa88c0f10c6832cabc2143d38e5c2956357ffe3	1	available	\N	2026-11-08 20:53:33.424816+08
394f2a71-15da-4f43-a222-dc1c413a5769	540f2fa1-53f8-4e43-9841-8eb881a0c529	7ca839a0-d955-4a7e-aa64-290382c63453	\N	perf/7ca839a0-d955-4a7e-aa64-290382c63453/artifacts/global_usage_CPU_c213d5293f9cc52f_1794142381927_1794142413586.csv	other	7ca839a0-d955-4a7e-aa64-290382c63453/perf/7ca839a0-d955-4a7e-aa64-290382c63453/artifacts/global_usage_CPU_c213d5293f9cc52f_1794142381927_1794142413586.csv	text/csv	1934	ef71b3411d29dc6cbdd9f5eb043492095b679b0d8ed046a85a9df60eda152934	1	available	\N	2026-11-08 20:53:33.424816+08
0b858356-2d03-45d7-a485-ea4e81da031e	540f2fa1-53f8-4e43-9841-8eb881a0c529	7ca839a0-d955-4a7e-aa64-290382c63453	\N	perf/7ca839a0-d955-4a7e-aa64-290382c63453/artifacts/global_usage_Memory_e23a071593b1a6e4_1794142381927_1794142413589.csv	other	7ca839a0-d955-4a7e-aa64-290382c63453/perf/7ca839a0-d955-4a7e-aa64-290382c63453/artifacts/global_usage_Memory_e23a071593b1a6e4_1794142381927_1794142413589.csv	text/csv	955	c93b1a69680483677ad2f6a22f470babaf19751afcd8e389a90f531675a8f84e	1	available	\N	2026-11-08 20:53:33.424816+08
7331e595-7b69-40a8-9213-4ef99e151301	540f2fa1-53f8-4e43-9841-8eb881a0c529	b7899bcf-7d37-48ec-81be-0407340d0b03	\N	actions.jsonl	report_json	b7899bcf-7d37-48ec-81be-0407340d0b03/actions.jsonl	application/octet-stream	446	ad973638295f82355ea050b7ad1bbc265bd4b197efd624a8b9bca098513c9ec8	1	available	\N	2026-11-08 21:15:15.668193+08
0fb3051a-e80c-4bf7-9627-776455f8e8e6	540f2fa1-53f8-4e43-9841-8eb881a0c529	7ca839a0-d955-4a7e-aa64-290382c63453	\N	perf/7ca839a0-d955-4a7e-aa64-290382c63453/artifacts/privatedirty-main-20746_Memory_a23d7f4a8438d385_1794142381927_1794142413589.csv	other	7ca839a0-d955-4a7e-aa64-290382c63453/perf/7ca839a0-d955-4a7e-aa64-290382c63453/artifacts/privatedirty-main-20746_Memory_a23d7f4a8438d385_1794142381927_1794142413589.csv	text/csv	983	1fe12894e198b30250b510114012931ad409940d551b52c876ac90903279273d	1	available	\N	2026-11-08 20:53:33.424816+08
2238178e-d88c-4a77-a43b-869c56fab5cc	540f2fa1-53f8-4e43-9841-8eb881a0c529	7ca839a0-d955-4a7e-aa64-290382c63453	\N	perf/7ca839a0-d955-4a7e-aa64-290382c63453/artifacts/pss-main-20746_Memory_838d082a3f6e0995_1794142381927_1794142413589.csv	other	7ca839a0-d955-4a7e-aa64-290382c63453/perf/7ca839a0-d955-4a7e-aa64-290382c63453/artifacts/pss-main-20746_Memory_838d082a3f6e0995_1794142381927_1794142413589.csv	text/csv	975	bbe8cdf054705212f6ed42f4023c7caaaf700bd8b4c8054ecd72948e79404a78	1	available	\N	2026-11-08 20:53:33.424816+08
db53244c-418e-4f2a-b6fb-4a99c3424592	540f2fa1-53f8-4e43-9841-8eb881a0c529	7ca839a0-d955-4a7e-aa64-290382c63453	\N	perf/7ca839a0-d955-4a7e-aa64-290382c63453/artifacts/supplement_thermal_gpu.csv	other	7ca839a0-d955-4a7e-aa64-290382c63453/perf/7ca839a0-d955-4a7e-aa64-290382c63453/artifacts/supplement_thermal_gpu.csv	text/csv	373	e0b51bb2ed55af212391962bd522bfc983b58b2ded72d4f82c39c69a3b805f85	1	available	\N	2026-11-08 20:53:33.424816+08
ef4540fd-6b91-4784-9187-f187b8fa677d	540f2fa1-53f8-4e43-9841-8eb881a0c529	ec832d64-466a-437a-8dcc-6a2efb9eede6	\N	actions.jsonl	report_json	ec832d64-466a-437a-8dcc-6a2efb9eede6/actions.jsonl	application/octet-stream	552	9855e0d2b37eff2597d0f006673b7cdfbe3e34a3890d7bd9416c0e04eb0b4ff9	1	available	\N	2026-11-08 21:12:46.205621+08
7972f789-a958-4af8-ba43-40d6ba25c227	540f2fa1-53f8-4e43-9841-8eb881a0c529	ec832d64-466a-437a-8dcc-6a2efb9eede6	\N	junit.xml	other	ec832d64-466a-437a-8dcc-6a2efb9eede6/junit.xml	text/xml	1502	0da0eb68a2830728c349c8f8bbbe17d9a71ba4f931b4ed0c8ac398f6c03fb386	1	available	\N	2026-11-08 21:12:46.205621+08
52b9a46b-bbf5-4640-9bfd-eabd940ed37e	540f2fa1-53f8-4e43-9841-8eb881a0c529	ec832d64-466a-437a-8dcc-6a2efb9eede6	\N	mobile-config.toml	other	ec832d64-466a-437a-8dcc-6a2efb9eede6/mobile-config.toml	application/octet-stream	271	cb890ce41345c9da22a478315b5d4d1d4131627555aae02944cbd8669020e990	1	available	\N	2026-11-08 21:12:46.205621+08
85b4a432-8d78-4e15-9c11-b95591adaa47	540f2fa1-53f8-4e43-9841-8eb881a0c529	ec832d64-466a-437a-8dcc-6a2efb9eede6	\N	perf.sqlite3	other	ec832d64-466a-437a-8dcc-6a2efb9eede6/perf.sqlite3	application/octet-stream	4096	42f67cde08aaa4db17432058fdd3521a7199a1dfd4afe740ca486d6b49226302	1	available	\N	2026-11-08 21:12:46.205621+08
f58a346d-a5e0-4a87-b62d-23aa8a56cdeb	540f2fa1-53f8-4e43-9841-8eb881a0c529	ec832d64-466a-437a-8dcc-6a2efb9eede6	\N	perf.sqlite3-shm	other	ec832d64-466a-437a-8dcc-6a2efb9eede6/perf.sqlite3-shm	application/octet-stream	32768	8645f18fca9dde4bfaf1e2a3e8d8d250c7e4cd8940f739237f0e219f4370d521	1	available	\N	2026-11-08 21:12:46.205621+08
5aba857a-a62e-4167-8543-09567e2bcc62	540f2fa1-53f8-4e43-9841-8eb881a0c529	ec832d64-466a-437a-8dcc-6a2efb9eede6	\N	perf.sqlite3-wal	other	ec832d64-466a-437a-8dcc-6a2efb9eede6/perf.sqlite3-wal	application/octet-stream	98912	adebce03aff23ec2817f6de15c7f141ebdeaefc7d84a385d8704092796e04145	1	available	\N	2026-11-08 21:12:46.205621+08
a26c01d5-ee6e-4597-8227-68a2221b60d3	540f2fa1-53f8-4e43-9841-8eb881a0c529	ec832d64-466a-437a-8dcc-6a2efb9eede6	\N	report.json	report_json	ec832d64-466a-437a-8dcc-6a2efb9eede6/report.json	application/json	22810	72593a1c0e34aa6cf8ae537b81ddc5572cfb55972b0299b21f791a988277ca14	1	available	\N	2026-11-08 21:12:46.205621+08
6b47d7d3-eb51-42da-89dd-4badfd37d04f	540f2fa1-53f8-4e43-9841-8eb881a0c529	ec832d64-466a-437a-8dcc-6a2efb9eede6	\N	perf-runs/ec832d64-466a-437a-8dcc-6a2efb9eede6/meta.json	report_json	ec832d64-466a-437a-8dcc-6a2efb9eede6/perf-runs/ec832d64-466a-437a-8dcc-6a2efb9eede6/meta.json	application/json	1118	447827a5b3cdff9fd676512f55bf818ff09d2de7db960ef2e205d97819114851	1	available	\N	2026-11-08 21:12:46.205621+08
d6eae0d2-2151-4d8b-adc4-6a5ebf7acf7c	540f2fa1-53f8-4e43-9841-8eb881a0c529	ec832d64-466a-437a-8dcc-6a2efb9eede6	\N	perf-runs/ec832d64-466a-437a-8dcc-6a2efb9eede6/report.html	report_html	ec832d64-466a-437a-8dcc-6a2efb9eede6/perf-runs/ec832d64-466a-437a-8dcc-6a2efb9eede6/report.html	text/html	1056821	16cc97b1dbe23d192f57348437f71ad5df9a2b27a501aa72a2565534776b4c17	1	available	\N	2026-11-08 21:12:46.205621+08
3d45c0d8-e352-4529-b60b-cf4b3b2b8ad2	540f2fa1-53f8-4e43-9841-8eb881a0c529	ec832d64-466a-437a-8dcc-6a2efb9eede6	\N	perf-runs/ec832d64-466a-437a-8dcc-6a2efb9eede6/report.json	report_json	ec832d64-466a-437a-8dcc-6a2efb9eede6/perf-runs/ec832d64-466a-437a-8dcc-6a2efb9eede6/report.json	application/json	26040	699d44d5abfbe20fd7ee10c39fde2a268f27574463d3573c5ad0ad8a8fcc83c2	1	available	\N	2026-11-08 21:12:46.205621+08
4a147618-89d7-4b1b-8b70-1f0f133ebb1f	540f2fa1-53f8-4e43-9841-8eb881a0c529	ec832d64-466a-437a-8dcc-6a2efb9eede6	\N	perf-runs/ec832d64-466a-437a-8dcc-6a2efb9eede6/artifacts/app_process-main-20746_CPU_e43c0b2d66eee287_1794143544985_1794143566226.csv	other	ec832d64-466a-437a-8dcc-6a2efb9eede6/perf-runs/ec832d64-466a-437a-8dcc-6a2efb9eede6/artifacts/app_process-main-20746_CPU_e43c0b2d66eee287_1794143544985_1794143566226.csv	text/csv	374	4e73b5018bfde5e9647f78998d9ef764af50643b53468fbb8eec5efb4ed4ae5f	1	available	\N	2026-11-08 21:12:46.205621+08
28cf8f8d-2fa1-4e84-baed-eec6854fcd34	540f2fa1-53f8-4e43-9841-8eb881a0c529	ec832d64-466a-437a-8dcc-6a2efb9eede6	\N	perf-runs/ec832d64-466a-437a-8dcc-6a2efb9eede6/artifacts/app_process-main-28639_CPU_f6be690fa38a3f6d_1794143544985_1794143566226.csv	other	ec832d64-466a-437a-8dcc-6a2efb9eede6/perf-runs/ec832d64-466a-437a-8dcc-6a2efb9eede6/artifacts/app_process-main-28639_CPU_f6be690fa38a3f6d_1794143544985_1794143566226.csv	text/csv	980	83ca35a7b7d06975ba313ba29527121e824741a6bcdd5258766395bc756e4dc7	1	available	\N	2026-11-08 21:12:46.205621+08
536e0c6b-613a-40b4-98b7-a126bc29fbda	540f2fa1-53f8-4e43-9841-8eb881a0c529	ec832d64-466a-437a-8dcc-6a2efb9eede6	\N	perf-runs/ec832d64-466a-437a-8dcc-6a2efb9eede6/artifacts/fps_FPS_1237bddbf66ff20c_1794143544985_1794143566227.csv	other	ec832d64-466a-437a-8dcc-6a2efb9eede6/perf-runs/ec832d64-466a-437a-8dcc-6a2efb9eede6/artifacts/fps_FPS_1237bddbf66ff20c_1794143544985_1794143566227.csv	text/csv	1013	9d4b1c1f06290d51c4185294601fa5f78dc92a905c9d8d658d6fe79245c51a7f	1	available	\N	2026-11-08 21:12:46.205621+08
4b28ee5e-a5d6-41d4-9b80-b36791a43925	540f2fa1-53f8-4e43-9841-8eb881a0c529	ec832d64-466a-437a-8dcc-6a2efb9eede6	\N	perf-runs/ec832d64-466a-437a-8dcc-6a2efb9eede6/artifacts/frame_delay_count_FPS_5399dc00cc3b24be_1794143544985_1794143566227.csv	other	ec832d64-466a-437a-8dcc-6a2efb9eede6/perf-runs/ec832d64-466a-437a-8dcc-6a2efb9eede6/artifacts/frame_delay_count_FPS_5399dc00cc3b24be_1794143544985_1794143566227.csv	text/csv	975	115d771ae8126b35dd1b8accdf0ad9a898d5657b5523a96c05ad618799c87d48	1	available	\N	2026-11-08 21:12:46.205621+08
306a995d-927f-4705-922e-f709bdc1e987	540f2fa1-53f8-4e43-9841-8eb881a0c529	ec832d64-466a-437a-8dcc-6a2efb9eede6	\N	perf-runs/ec832d64-466a-437a-8dcc-6a2efb9eede6/artifacts/frame_delay_max_FPS_33a91b97934dbd55_1794143544985_1794143566227.csv	other	ec832d64-466a-437a-8dcc-6a2efb9eede6/perf-runs/ec832d64-466a-437a-8dcc-6a2efb9eede6/artifacts/frame_delay_max_FPS_33a91b97934dbd55_1794143544985_1794143566227.csv	text/csv	984	13fbe4bf8dd6f844b43d93acab35e8ab48aa98e5cae8f117e38d00a1027e92ab	1	available	\N	2026-11-08 21:12:46.205621+08
7bbe4bee-33e0-4903-98a5-c6290b4f3c96	540f2fa1-53f8-4e43-9841-8eb881a0c529	ec832d64-466a-437a-8dcc-6a2efb9eede6	\N	perf-runs/ec832d64-466a-437a-8dcc-6a2efb9eede6/artifacts/frame_delay_ratio_FPS_c026b13363e32243_1794143544985_1794143566227.csv	other	ec832d64-466a-437a-8dcc-6a2efb9eede6/perf-runs/ec832d64-466a-437a-8dcc-6a2efb9eede6/artifacts/frame_delay_ratio_FPS_c026b13363e32243_1794143544985_1794143566227.csv	text/csv	995	a2cd4790dc53e0e15296df4f42c1c3ae9a142b301a239b664c285c2c794e40b7	1	available	\N	2026-11-08 21:12:46.205621+08
222757ef-5b98-4baf-ba2d-a47d4cd42b7a	540f2fa1-53f8-4e43-9841-8eb881a0c529	ec832d64-466a-437a-8dcc-6a2efb9eede6	\N	perf-runs/ec832d64-466a-437a-8dcc-6a2efb9eede6/artifacts/global_usage_CPU_64d4ae78a838e72b_1794143544985_1794143566226.csv	other	ec832d64-466a-437a-8dcc-6a2efb9eede6/perf-runs/ec832d64-466a-437a-8dcc-6a2efb9eede6/artifacts/global_usage_CPU_64d4ae78a838e72b_1794143544985_1794143566226.csv	text/csv	1351	3e68f0951ede0b123958110ecf4ca519e056df160018909cbca8765b7857c8f6	1	available	\N	2026-11-08 21:12:46.205621+08
397e06b1-f393-4af5-a000-aba5cbfaf55a	540f2fa1-53f8-4e43-9841-8eb881a0c529	d8c1ea76-e45d-4629-8152-bb2697af04f0	\N	junit.xml	other	d8c1ea76-e45d-4629-8152-bb2697af04f0/junit.xml	text/xml	1502	6c1b68ab6954f2eb7e93a2bbde2447f1919b097b8fd041d1a0aa9992cd88f55a	1	available	\N	2026-11-08 21:24:09.471599+08
00c600dd-df7b-4134-b330-dcd957f21238	540f2fa1-53f8-4e43-9841-8eb881a0c529	ec832d64-466a-437a-8dcc-6a2efb9eede6	\N	perf-runs/ec832d64-466a-437a-8dcc-6a2efb9eede6/artifacts/global_usage_Memory_5eafd47eb79635f1_1794143544985_1794143566226.csv	other	ec832d64-466a-437a-8dcc-6a2efb9eede6/perf-runs/ec832d64-466a-437a-8dcc-6a2efb9eede6/artifacts/global_usage_Memory_5eafd47eb79635f1_1794143544985_1794143566226.csv	text/csv	635	54787cebff035af41602d8a08b9c3224ffb39a4b27edd2b5ac31ecea721df9df	1	available	\N	2026-11-08 21:12:46.205621+08
1188c2ed-9262-4786-9370-62ed0fd4b82f	540f2fa1-53f8-4e43-9841-8eb881a0c529	ec832d64-466a-437a-8dcc-6a2efb9eede6	\N	perf-runs/ec832d64-466a-437a-8dcc-6a2efb9eede6/artifacts/privatedirty-main-20746_Memory_2815c7f4974a9407_1794143544985_1794143566226.csv	other	ec832d64-466a-437a-8dcc-6a2efb9eede6/perf-runs/ec832d64-466a-437a-8dcc-6a2efb9eede6/artifacts/privatedirty-main-20746_Memory_2815c7f4974a9407_1794143544985_1794143566226.csv	text/csv	117	2e8ff39db034e2b53c590229f50f816f1afce7cc5ad0d30fbbd42d027fcb2733	1	available	\N	2026-11-08 21:12:46.205621+08
4f56030b-f08f-42a7-b8cf-5ed96a3deb80	540f2fa1-53f8-4e43-9841-8eb881a0c529	ec832d64-466a-437a-8dcc-6a2efb9eede6	\N	perf-runs/ec832d64-466a-437a-8dcc-6a2efb9eede6/artifacts/privatedirty-main-28639_Memory_bc3ed4afa2e49a60_1794143544985_1794143566226.csv	other	ec832d64-466a-437a-8dcc-6a2efb9eede6/perf-runs/ec832d64-466a-437a-8dcc-6a2efb9eede6/artifacts/privatedirty-main-28639_Memory_bc3ed4afa2e49a60_1794143544985_1794143566226.csv	text/csv	514	688fd52968b65063d49bb514213c583e50b78825c90d85706a9533d2fbb1dc82	1	available	\N	2026-11-08 21:12:46.205621+08
85ba1ec3-1ae3-48ab-b637-4042caa8972c	540f2fa1-53f8-4e43-9841-8eb881a0c529	ec832d64-466a-437a-8dcc-6a2efb9eede6	\N	perf-runs/ec832d64-466a-437a-8dcc-6a2efb9eede6/artifacts/pss-main-20746_Memory_c601e4a3c8a971ec_1794143544985_1794143566226.csv	other	ec832d64-466a-437a-8dcc-6a2efb9eede6/perf-runs/ec832d64-466a-437a-8dcc-6a2efb9eede6/artifacts/pss-main-20746_Memory_c601e4a3c8a971ec_1794143544985_1794143566226.csv	text/csv	107	7fa94e6b329da789d769cb687d8fb5ad62b9a429949fe1fd730a642b9b0e2964	1	available	\N	2026-11-08 21:12:46.205621+08
2a998901-e3c3-4dcf-8fbe-86326f0f602e	540f2fa1-53f8-4e43-9841-8eb881a0c529	ec832d64-466a-437a-8dcc-6a2efb9eede6	\N	perf-runs/ec832d64-466a-437a-8dcc-6a2efb9eede6/artifacts/pss-main-28639_Memory_36202ef104d5d594_1794143544985_1794143566226.csv	other	ec832d64-466a-437a-8dcc-6a2efb9eede6/perf-runs/ec832d64-466a-437a-8dcc-6a2efb9eede6/artifacts/pss-main-28639_Memory_36202ef104d5d594_1794143544985_1794143566226.csv	text/csv	509	f6c2dbf298ae680121fce69c58b3679c249ed5da678c497d51b2a52e664160c0	1	available	\N	2026-11-08 21:12:46.205621+08
18b32182-285f-43b0-aeee-1250fe397118	540f2fa1-53f8-4e43-9841-8eb881a0c529	ec832d64-466a-437a-8dcc-6a2efb9eede6	\N	perf-runs/ec832d64-466a-437a-8dcc-6a2efb9eede6/artifacts/supplement_thermal_gpu.csv	other	ec832d64-466a-437a-8dcc-6a2efb9eede6/perf-runs/ec832d64-466a-437a-8dcc-6a2efb9eede6/artifacts/supplement_thermal_gpu.csv	text/csv	396	27c026bbd46023442c1a97dd0e4c7e130733343050f357fb5e90deb02bf57e92	1	available	\N	2026-11-08 21:12:46.205621+08
59eefd8d-9dfb-46cc-8f8b-dfe67af44f97	540f2fa1-53f8-4e43-9841-8eb881a0c529	ec832d64-466a-437a-8dcc-6a2efb9eede6	\N	runs/main.json	report_json	ec832d64-466a-437a-8dcc-6a2efb9eede6/runs/main.json	application/json	142	bf63ad456809abb50c1011efd6138abe3b3a35185a2b5fb1305cf3c1b3428d64	1	available	\N	2026-11-08 21:12:46.205621+08
c39e329f-1195-4fe0-aa88-7f37bcf3ac78	540f2fa1-53f8-4e43-9841-8eb881a0c529	b7899bcf-7d37-48ec-81be-0407340d0b03	\N	mobile-config.toml	other	b7899bcf-7d37-48ec-81be-0407340d0b03/mobile-config.toml	application/octet-stream	271	9580be04e40cecbd5985c801d2bee371d0dfa3280a15f627c5a70e5887bfa5ee	1	available	\N	2026-11-08 21:15:15.668193+08
7f4a9e1e-0327-41a4-a384-dd26eca38a16	540f2fa1-53f8-4e43-9841-8eb881a0c529	b7899bcf-7d37-48ec-81be-0407340d0b03	\N	runs/main.json	report_json	b7899bcf-7d37-48ec-81be-0407340d0b03/runs/main.json	application/json	254	3fe68bf2ac320c744c484f18e50a2ea531d307b49c190415f25aed9a64489599	1	available	\N	2026-11-08 21:15:15.668193+08
bb8d46f7-6db5-4438-9620-aa0ba58977cb	540f2fa1-53f8-4e43-9841-8eb881a0c529	2b814545-aada-4196-90ae-706dbbaf4d76	\N	actions.jsonl	report_json	2b814545-aada-4196-90ae-706dbbaf4d76/actions.jsonl	application/octet-stream	553	f040db51bbd17cbf3aaa163eb3d6292bafcf0541a78e776c9746d99cdc2923f8	1	available	\N	2026-11-08 21:17:03.102559+08
535210b5-8ccb-4d54-b564-ebf1b2dfd919	540f2fa1-53f8-4e43-9841-8eb881a0c529	2b814545-aada-4196-90ae-706dbbaf4d76	\N	junit.xml	other	2b814545-aada-4196-90ae-706dbbaf4d76/junit.xml	text/xml	1502	e6a705ee5e7341c4fac4970ea5d164e55bfd46ee9d9f130a05164e9a4dde7062	1	available	\N	2026-11-08 21:17:03.102559+08
382f659c-dc9f-4c48-b51e-1faed2e30594	540f2fa1-53f8-4e43-9841-8eb881a0c529	2b814545-aada-4196-90ae-706dbbaf4d76	\N	mobile-config.toml	other	2b814545-aada-4196-90ae-706dbbaf4d76/mobile-config.toml	application/octet-stream	271	ab051dafe3f526ccf9bbec8296eb1c8d082f3e4c061e60e956653d531e7322e1	1	available	\N	2026-11-08 21:17:03.102559+08
573d2f20-8c31-4448-82b8-0c806207fbf9	540f2fa1-53f8-4e43-9841-8eb881a0c529	2b814545-aada-4196-90ae-706dbbaf4d76	\N	perf.sqlite3	other	2b814545-aada-4196-90ae-706dbbaf4d76/perf.sqlite3	application/octet-stream	4096	42f67cde08aaa4db17432058fdd3521a7199a1dfd4afe740ca486d6b49226302	1	available	\N	2026-11-08 21:17:03.102559+08
3e0abf03-7c5e-44b7-9959-5d89b57f2a8c	540f2fa1-53f8-4e43-9841-8eb881a0c529	2b814545-aada-4196-90ae-706dbbaf4d76	\N	perf.sqlite3-shm	other	2b814545-aada-4196-90ae-706dbbaf4d76/perf.sqlite3-shm	application/octet-stream	32768	93938a56a448c7ef4f8955dce2e947fefca28483a0900cf62ff69eb5f5a96c14	1	available	\N	2026-11-08 21:17:03.102559+08
5f181a02-a3b4-415e-abba-3b2f89e634c1	540f2fa1-53f8-4e43-9841-8eb881a0c529	2b814545-aada-4196-90ae-706dbbaf4d76	\N	perf.sqlite3-wal	other	2b814545-aada-4196-90ae-706dbbaf4d76/perf.sqlite3-wal	application/octet-stream	98912	3d3d9f8b764621bf926fdeb0f89c93506e23ff597207b00bcb36d5abc3326f6d	1	available	\N	2026-11-08 21:17:03.102559+08
a8a34df9-678c-4479-a028-73c33866aa48	540f2fa1-53f8-4e43-9841-8eb881a0c529	2b814545-aada-4196-90ae-706dbbaf4d76	\N	report.json	report_json	2b814545-aada-4196-90ae-706dbbaf4d76/report.json	application/json	22880	18072703fec7d7c2c538d723b9b404f32bec59e08c101f91b27791e8393f0b7e	1	available	\N	2026-11-08 21:17:03.102559+08
88ed5e9d-f094-473b-8984-707e616b3067	540f2fa1-53f8-4e43-9841-8eb881a0c529	2b814545-aada-4196-90ae-706dbbaf4d76	\N	perf-runs/2b814545-aada-4196-90ae-706dbbaf4d76/meta.json	report_json	2b814545-aada-4196-90ae-706dbbaf4d76/perf-runs/2b814545-aada-4196-90ae-706dbbaf4d76/meta.json	application/json	1119	40e36091287784f57ccaed9ec151794f6d065db57c6c013afedab1e3c11f3fa4	1	available	\N	2026-11-08 21:17:03.102559+08
8b778f19-4cf5-4b76-8ee6-ca948871179f	540f2fa1-53f8-4e43-9841-8eb881a0c529	2b814545-aada-4196-90ae-706dbbaf4d76	\N	perf-runs/2b814545-aada-4196-90ae-706dbbaf4d76/report.html	report_html	2b814545-aada-4196-90ae-706dbbaf4d76/perf-runs/2b814545-aada-4196-90ae-706dbbaf4d76/report.html	text/html	1056857	d332b2db6d9835f8243f1e912c66dcc7c5a7b163bf941056aee83797e297b49b	1	available	\N	2026-11-08 21:17:03.102559+08
b5e23436-8252-41fe-b84a-6cb2fcae3103	540f2fa1-53f8-4e43-9841-8eb881a0c529	2b814545-aada-4196-90ae-706dbbaf4d76	\N	perf-runs/2b814545-aada-4196-90ae-706dbbaf4d76/report.json	report_json	2b814545-aada-4196-90ae-706dbbaf4d76/perf-runs/2b814545-aada-4196-90ae-706dbbaf4d76/report.json	application/json	26107	6b46f1867850e8ea4707e5be59208d0e7cf867e59ed702da6da03165f319edd2	1	available	\N	2026-11-08 21:17:03.102559+08
2d45928d-65a1-4f9c-a24d-c8cd1dd7074b	540f2fa1-53f8-4e43-9841-8eb881a0c529	2b814545-aada-4196-90ae-706dbbaf4d76	\N	perf-runs/2b814545-aada-4196-90ae-706dbbaf4d76/artifacts/app_process-main-30412_CPU_1fee0f5fc29abc8c_1794143801262_1794143823035.csv	other	2b814545-aada-4196-90ae-706dbbaf4d76/perf-runs/2b814545-aada-4196-90ae-706dbbaf4d76/artifacts/app_process-main-30412_CPU_1fee0f5fc29abc8c_1794143801262_1794143823035.csv	text/csv	380	b6777d1e064efdff757d2372c8d74b7f920820da0a9bda1d3950b265e667e40a	1	available	\N	2026-11-08 21:17:03.102559+08
d60c08b5-70f0-463b-b1d7-30b1c19fcbb6	540f2fa1-53f8-4e43-9841-8eb881a0c529	2b814545-aada-4196-90ae-706dbbaf4d76	\N	perf-runs/2b814545-aada-4196-90ae-706dbbaf4d76/artifacts/app_process-main-3765_CPU_86eb9055323935d0_1794143801262_1794143823035.csv	other	2b814545-aada-4196-90ae-706dbbaf4d76/perf-runs/2b814545-aada-4196-90ae-706dbbaf4d76/artifacts/app_process-main-3765_CPU_86eb9055323935d0_1794143801262_1794143823035.csv	text/csv	1003	abadfda29a959be4ff9c2faf5179a53672303adcea323f54a376bbabc213d105	1	available	\N	2026-11-08 21:17:03.102559+08
9a1af21b-650b-4661-a1ff-0a523586b62b	540f2fa1-53f8-4e43-9841-8eb881a0c529	2b814545-aada-4196-90ae-706dbbaf4d76	\N	perf-runs/2b814545-aada-4196-90ae-706dbbaf4d76/artifacts/fps_FPS_db6e768ebd1f5c77_1794143801262_1794143823036.csv	other	2b814545-aada-4196-90ae-706dbbaf4d76/perf-runs/2b814545-aada-4196-90ae-706dbbaf4d76/artifacts/fps_FPS_db6e768ebd1f5c77_1794143801262_1794143823036.csv	text/csv	1024	64a54320d05ae55637057c2581e0386cb04e857a6fcf8336c9856e03f70dd88f	1	available	\N	2026-11-08 21:17:03.102559+08
62725238-3daf-4350-b950-2b6c7b3779f7	540f2fa1-53f8-4e43-9841-8eb881a0c529	2b814545-aada-4196-90ae-706dbbaf4d76	\N	perf-runs/2b814545-aada-4196-90ae-706dbbaf4d76/artifacts/frame_delay_count_FPS_a553bfc3e42b5494_1794143801262_1794143823036.csv	other	2b814545-aada-4196-90ae-706dbbaf4d76/perf-runs/2b814545-aada-4196-90ae-706dbbaf4d76/artifacts/frame_delay_count_FPS_a553bfc3e42b5494_1794143801262_1794143823036.csv	text/csv	974	1e7846b386346d299fbf98d469a9255ca3d6d1f7e89f7503ba978d59d3d479c3	1	available	\N	2026-11-08 21:17:03.102559+08
760e6c7e-cbbf-4b2b-9296-1ed6e4c4fd5c	540f2fa1-53f8-4e43-9841-8eb881a0c529	2b814545-aada-4196-90ae-706dbbaf4d76	\N	perf-runs/2b814545-aada-4196-90ae-706dbbaf4d76/artifacts/frame_delay_max_FPS_0d0b62721e290729_1794143801262_1794143823036.csv	other	2b814545-aada-4196-90ae-706dbbaf4d76/perf-runs/2b814545-aada-4196-90ae-706dbbaf4d76/artifacts/frame_delay_max_FPS_0d0b62721e290729_1794143801262_1794143823036.csv	text/csv	985	2067c3c5a0ee29c0dda9594039b77972dd237e9375dcbbef171699165c608ded	1	available	\N	2026-11-08 21:17:03.102559+08
cefba76a-9dd2-46e9-b895-2a5c0a7ada00	540f2fa1-53f8-4e43-9841-8eb881a0c529	2b814545-aada-4196-90ae-706dbbaf4d76	\N	perf-runs/2b814545-aada-4196-90ae-706dbbaf4d76/artifacts/frame_delay_ratio_FPS_2112f0a728ed7bae_1794143801262_1794143823036.csv	other	2b814545-aada-4196-90ae-706dbbaf4d76/perf-runs/2b814545-aada-4196-90ae-706dbbaf4d76/artifacts/frame_delay_ratio_FPS_2112f0a728ed7bae_1794143801262_1794143823036.csv	text/csv	1004	7447751170ac0320a36ae43f460799ddaf19acbd3608198854f46bddd3924699	1	available	\N	2026-11-08 21:17:03.102559+08
9b59f876-9351-47c6-acfb-9e00c4d5d90d	540f2fa1-53f8-4e43-9841-8eb881a0c529	2b814545-aada-4196-90ae-706dbbaf4d76	\N	perf-runs/2b814545-aada-4196-90ae-706dbbaf4d76/artifacts/global_usage_CPU_de972f84a13258b9_1794143801262_1794143823035.csv	other	2b814545-aada-4196-90ae-706dbbaf4d76/perf-runs/2b814545-aada-4196-90ae-706dbbaf4d76/artifacts/global_usage_CPU_de972f84a13258b9_1794143801262_1794143823035.csv	text/csv	1390	d036825ccf0001fefb3425003bc1a339bfefe86890d0f0346b56fc0199342eb2	1	available	\N	2026-11-08 21:17:03.102559+08
483410f6-0c9f-408d-ad51-c6b9758a2630	540f2fa1-53f8-4e43-9841-8eb881a0c529	2b814545-aada-4196-90ae-706dbbaf4d76	\N	perf-runs/2b814545-aada-4196-90ae-706dbbaf4d76/artifacts/global_usage_Memory_d05439466a81d551_1794143801262_1794143823035.csv	other	2b814545-aada-4196-90ae-706dbbaf4d76/perf-runs/2b814545-aada-4196-90ae-706dbbaf4d76/artifacts/global_usage_Memory_d05439466a81d551_1794143801262_1794143823035.csv	text/csv	581	cf0a50568fc77f9022da98bb48d0d1cd1d23fc000006e10c06eac6445c2db3fe	1	available	\N	2026-11-08 21:17:03.102559+08
2bc42939-0dcf-4bf7-8327-6344518b765c	540f2fa1-53f8-4e43-9841-8eb881a0c529	2b814545-aada-4196-90ae-706dbbaf4d76	\N	perf-runs/2b814545-aada-4196-90ae-706dbbaf4d76/artifacts/privatedirty-main-30412_Memory_b39a15c73560bee1_1794143801262_1794143823035.csv	other	2b814545-aada-4196-90ae-706dbbaf4d76/perf-runs/2b814545-aada-4196-90ae-706dbbaf4d76/artifacts/privatedirty-main-30412_Memory_b39a15c73560bee1_1794143801262_1794143823035.csv	text/csv	118	da56ce0b4f076e16150e095277525f21b220ae05737bb8f7ed538cd9fbfff251	1	available	\N	2026-11-08 21:17:03.102559+08
5429a424-1ce2-4960-ba43-32a5b78cb2e9	540f2fa1-53f8-4e43-9841-8eb881a0c529	2b814545-aada-4196-90ae-706dbbaf4d76	\N	perf-runs/2b814545-aada-4196-90ae-706dbbaf4d76/artifacts/privatedirty-main-3765_Memory_61f06a0eb6a87c69_1794143801262_1794143823035.csv	other	2b814545-aada-4196-90ae-706dbbaf4d76/perf-runs/2b814545-aada-4196-90ae-706dbbaf4d76/artifacts/privatedirty-main-3765_Memory_61f06a0eb6a87c69_1794143801262_1794143823035.csv	text/csv	493	93c4ef5639800a827e20fc47b6605b2bd22cac4ac0f1889e0e9b8c242dde8f7b	1	available	\N	2026-11-08 21:17:03.102559+08
f554d98e-82b1-4cda-b948-e2984808a00c	540f2fa1-53f8-4e43-9841-8eb881a0c529	2b814545-aada-4196-90ae-706dbbaf4d76	\N	perf-runs/2b814545-aada-4196-90ae-706dbbaf4d76/artifacts/pss-main-30412_Memory_695ae28bc5fbcb84_1794143801262_1794143823035.csv	other	2b814545-aada-4196-90ae-706dbbaf4d76/perf-runs/2b814545-aada-4196-90ae-706dbbaf4d76/artifacts/pss-main-30412_Memory_695ae28bc5fbcb84_1794143801262_1794143823035.csv	text/csv	108	9fb4db0d32d14e3a9f943645ecf0bb4154fd25c75f459e25cded6908f289ecbc	1	available	\N	2026-11-08 21:17:03.102559+08
088f41b9-af03-4da9-ab53-d9f2d6fae241	540f2fa1-53f8-4e43-9841-8eb881a0c529	2b814545-aada-4196-90ae-706dbbaf4d76	\N	perf-runs/2b814545-aada-4196-90ae-706dbbaf4d76/artifacts/pss-main-3765_Memory_4be25369b9fda2c5_1794143801262_1794143823035.csv	other	2b814545-aada-4196-90ae-706dbbaf4d76/perf-runs/2b814545-aada-4196-90ae-706dbbaf4d76/artifacts/pss-main-3765_Memory_4be25369b9fda2c5_1794143801262_1794143823035.csv	text/csv	477	f6068edfc6a87e62379161794c9c4418a73ea226d858fa7d05125f5f45b4e27f	1	available	\N	2026-11-08 21:17:03.102559+08
bbe60eb7-93db-410c-89cb-5baf566f41c0	540f2fa1-53f8-4e43-9841-8eb881a0c529	2b814545-aada-4196-90ae-706dbbaf4d76	\N	perf-runs/2b814545-aada-4196-90ae-706dbbaf4d76/artifacts/supplement_thermal_gpu.csv	other	2b814545-aada-4196-90ae-706dbbaf4d76/perf-runs/2b814545-aada-4196-90ae-706dbbaf4d76/artifacts/supplement_thermal_gpu.csv	text/csv	414	3d57a7bab60e703048b19dcc531ddfb7fa6b23a55bf42b2451703825f30f07ae	1	available	\N	2026-11-08 21:17:03.102559+08
1992663e-7fda-4096-9a2d-c7d60c0ffaca	540f2fa1-53f8-4e43-9841-8eb881a0c529	2b814545-aada-4196-90ae-706dbbaf4d76	\N	runs/main.json	report_json	2b814545-aada-4196-90ae-706dbbaf4d76/runs/main.json	application/json	143	ddd090de4fcaba5354770ccc989bf4a0ba6b50611c07ae4e5c73d3f276af3403	1	available	\N	2026-11-08 21:17:03.102559+08
0dd0822c-eaa2-46eb-8408-80823937ab9e	540f2fa1-53f8-4e43-9841-8eb881a0c529	99e0459d-5d6d-40ec-9d33-7d4848664a0f	\N	actions.jsonl	report_json	99e0459d-5d6d-40ec-9d33-7d4848664a0f/actions.jsonl	application/octet-stream	552	97c12793c315c81d949028a5514143bf8a0f707acd95fd381496b4c6a6dea2eb	1	available	\N	2026-11-08 21:21:55.980553+08
18b24a81-86f4-4081-b437-410edc7844b1	540f2fa1-53f8-4e43-9841-8eb881a0c529	99e0459d-5d6d-40ec-9d33-7d4848664a0f	\N	junit.xml	other	99e0459d-5d6d-40ec-9d33-7d4848664a0f/junit.xml	text/xml	1502	39b8346651689f72e44d6fe5c19433936d4c907ddd826e16ec26b17a25e99b6c	1	available	\N	2026-11-08 21:21:55.980553+08
d15d3a51-2321-44f5-8403-ffdb0a2f57b8	540f2fa1-53f8-4e43-9841-8eb881a0c529	99e0459d-5d6d-40ec-9d33-7d4848664a0f	\N	mobile-config.toml	other	99e0459d-5d6d-40ec-9d33-7d4848664a0f/mobile-config.toml	application/octet-stream	271	ef5a340dd3e6aaa659b861369b640904087b84752c3e760b2d16f763df13bc4c	1	available	\N	2026-11-08 21:21:55.980553+08
b2885d6e-b921-4ef2-867a-dc60c7e5922c	540f2fa1-53f8-4e43-9841-8eb881a0c529	99e0459d-5d6d-40ec-9d33-7d4848664a0f	\N	perf.sqlite3	other	99e0459d-5d6d-40ec-9d33-7d4848664a0f/perf.sqlite3	application/octet-stream	4096	42f67cde08aaa4db17432058fdd3521a7199a1dfd4afe740ca486d6b49226302	1	available	\N	2026-11-08 21:21:55.980553+08
544b84fe-cd65-4d70-bf16-88f682c922e5	540f2fa1-53f8-4e43-9841-8eb881a0c529	99e0459d-5d6d-40ec-9d33-7d4848664a0f	\N	perf.sqlite3-shm	other	99e0459d-5d6d-40ec-9d33-7d4848664a0f/perf.sqlite3-shm	application/octet-stream	32768	538320d290696f3bc2155b4befa7a73877f2c5139c6fe3117cc787fa538f0bed	1	available	\N	2026-11-08 21:21:55.980553+08
92932667-7bfa-4c49-9031-b3c75b3cb3bb	540f2fa1-53f8-4e43-9841-8eb881a0c529	99e0459d-5d6d-40ec-9d33-7d4848664a0f	\N	perf.sqlite3-wal	other	99e0459d-5d6d-40ec-9d33-7d4848664a0f/perf.sqlite3-wal	application/octet-stream	98912	ee647520c8304e01dec7943f68e88e8cad7aa0eb6d5cfba977754a0cab7b85b8	1	available	\N	2026-11-08 21:21:55.980553+08
49b29659-c442-4db6-a4f8-1e713e4399c5	540f2fa1-53f8-4e43-9841-8eb881a0c529	99e0459d-5d6d-40ec-9d33-7d4848664a0f	\N	report.json	report_json	99e0459d-5d6d-40ec-9d33-7d4848664a0f/report.json	application/json	22632	eeed863f31ee81e67121c0100bc9abe794c2018ab11fb6c03140e206bba6cc9d	1	available	\N	2026-11-08 21:21:55.980553+08
3b8fa434-7b62-4da0-90b6-cb93c0ee33db	540f2fa1-53f8-4e43-9841-8eb881a0c529	99e0459d-5d6d-40ec-9d33-7d4848664a0f	\N	perf-runs/99e0459d-5d6d-40ec-9d33-7d4848664a0f/meta.json	report_json	99e0459d-5d6d-40ec-9d33-7d4848664a0f/perf-runs/99e0459d-5d6d-40ec-9d33-7d4848664a0f/meta.json	application/json	1118	45969c3dce690dc816ec28fb91ca126e9a5adea6282a871c2625bb4ceeab8893	1	available	\N	2026-11-08 21:21:55.980553+08
e481b470-701c-4758-ba34-0af57ea6cdfe	540f2fa1-53f8-4e43-9841-8eb881a0c529	99e0459d-5d6d-40ec-9d33-7d4848664a0f	\N	perf-runs/99e0459d-5d6d-40ec-9d33-7d4848664a0f/report.html	report_html	99e0459d-5d6d-40ec-9d33-7d4848664a0f/perf-runs/99e0459d-5d6d-40ec-9d33-7d4848664a0f/report.html	text/html	1056709	313fb64c37268058fe65fb1c39e3a5a256b4737a14afa033e00e58d68ec5358b	1	available	\N	2026-11-08 21:21:55.980553+08
26e5f562-a0b4-4656-b824-e05f6cc6af62	540f2fa1-53f8-4e43-9841-8eb881a0c529	99e0459d-5d6d-40ec-9d33-7d4848664a0f	\N	perf-runs/99e0459d-5d6d-40ec-9d33-7d4848664a0f/report.json	report_json	99e0459d-5d6d-40ec-9d33-7d4848664a0f/perf-runs/99e0459d-5d6d-40ec-9d33-7d4848664a0f/report.json	application/json	25856	6b3c6b1dfcd32d3359fec1d684c9fde6f0f83e14bceee26223c2a329dfb2ab29	1	available	\N	2026-11-08 21:21:55.980553+08
85a008b2-e355-4334-b9a0-4d3c35b95817	540f2fa1-53f8-4e43-9841-8eb881a0c529	99e0459d-5d6d-40ec-9d33-7d4848664a0f	\N	perf-runs/99e0459d-5d6d-40ec-9d33-7d4848664a0f/artifacts/app_process-main-3765_CPU_65e10b588bf3ec21_1794144094648_1794144115958.csv	other	99e0459d-5d6d-40ec-9d33-7d4848664a0f/perf-runs/99e0459d-5d6d-40ec-9d33-7d4848664a0f/artifacts/app_process-main-3765_CPU_65e10b588bf3ec21_1794144094648_1794144115958.csv	text/csv	378	98bb8890a49e75d130cf6a44316d777cbbeaf8f7cd64b79f2a17ee7edb3a0d74	1	available	\N	2026-11-08 21:21:55.980553+08
cbb69e89-0006-4d8c-a936-0674c1a9c72c	540f2fa1-53f8-4e43-9841-8eb881a0c529	99e0459d-5d6d-40ec-9d33-7d4848664a0f	\N	perf-runs/99e0459d-5d6d-40ec-9d33-7d4848664a0f/artifacts/app_process-main-7260_CPU_4afa2e642289f560_1794144094648_1794144115958.csv	other	99e0459d-5d6d-40ec-9d33-7d4848664a0f/perf-runs/99e0459d-5d6d-40ec-9d33-7d4848664a0f/artifacts/app_process-main-7260_CPU_4afa2e642289f560_1794144094648_1794144115958.csv	text/csv	954	95b876565413ec5da1202614bdfe415539bc2886fcad3fee19ba4cba83a72496	1	available	\N	2026-11-08 21:21:55.980553+08
99d0e76c-39cb-46f3-b1d6-a5a53ea74aef	540f2fa1-53f8-4e43-9841-8eb881a0c529	99e0459d-5d6d-40ec-9d33-7d4848664a0f	\N	perf-runs/99e0459d-5d6d-40ec-9d33-7d4848664a0f/artifacts/fps_FPS_1601e2d382c906f8_1794144094648_1794144115958.csv	other	99e0459d-5d6d-40ec-9d33-7d4848664a0f/perf-runs/99e0459d-5d6d-40ec-9d33-7d4848664a0f/artifacts/fps_FPS_1601e2d382c906f8_1794144094648_1794144115958.csv	text/csv	966	5d62a7e8c2a47a066e92442d6b5e0ea6410c3566c16b4929a53a40f7285b9275	1	available	\N	2026-11-08 21:21:55.980553+08
d7c6472b-f4ff-4988-b099-867fef5b53f4	540f2fa1-53f8-4e43-9841-8eb881a0c529	99e0459d-5d6d-40ec-9d33-7d4848664a0f	\N	perf-runs/99e0459d-5d6d-40ec-9d33-7d4848664a0f/artifacts/frame_delay_count_FPS_9be226aa96a18b70_1794144094648_1794144115958.csv	other	99e0459d-5d6d-40ec-9d33-7d4848664a0f/perf-runs/99e0459d-5d6d-40ec-9d33-7d4848664a0f/artifacts/frame_delay_count_FPS_9be226aa96a18b70_1794144094648_1794144115958.csv	text/csv	930	73545ad56584594f0e18383d26a95862645b9aab6becfa808d83af865974acea	1	available	\N	2026-11-08 21:21:55.980553+08
0927d37e-efd0-4fc6-8046-d9a6cba62e33	540f2fa1-53f8-4e43-9841-8eb881a0c529	99e0459d-5d6d-40ec-9d33-7d4848664a0f	\N	perf-runs/99e0459d-5d6d-40ec-9d33-7d4848664a0f/artifacts/frame_delay_max_FPS_a4b3f0af7587fcb8_1794144094648_1794144115958.csv	other	99e0459d-5d6d-40ec-9d33-7d4848664a0f/perf-runs/99e0459d-5d6d-40ec-9d33-7d4848664a0f/artifacts/frame_delay_max_FPS_a4b3f0af7587fcb8_1794144094648_1794144115958.csv	text/csv	938	5ddd06402d1143522e3fc3718b98cca2241258122ff1bb768f59fa5d2e74c2b8	1	available	\N	2026-11-08 21:21:55.980553+08
e9d89fbb-3de0-472c-9bfc-34b768a80005	540f2fa1-53f8-4e43-9841-8eb881a0c529	d8c1ea76-e45d-4629-8152-bb2697af04f0	\N	actions.jsonl	report_json	d8c1ea76-e45d-4629-8152-bb2697af04f0/actions.jsonl	application/octet-stream	553	e26d280f71e7a2ad91147f07449affd23d31ea7da3653f28109624d72812fad1	1	available	\N	2026-11-08 21:24:09.471599+08
853b40f6-91f5-412a-a58e-0d81374362f8	540f2fa1-53f8-4e43-9841-8eb881a0c529	99e0459d-5d6d-40ec-9d33-7d4848664a0f	\N	perf-runs/99e0459d-5d6d-40ec-9d33-7d4848664a0f/artifacts/frame_delay_ratio_FPS_2dee4927f205d740_1794144094648_1794144115958.csv	other	99e0459d-5d6d-40ec-9d33-7d4848664a0f/perf-runs/99e0459d-5d6d-40ec-9d33-7d4848664a0f/artifacts/frame_delay_ratio_FPS_2dee4927f205d740_1794144094648_1794144115958.csv	text/csv	948	eeae19af8fca1d98f7a3835a363e6bf68fa59b8adb642969b2c9489a70802f81	1	available	\N	2026-11-08 21:21:55.980553+08
c1dc353f-054e-4ecb-86c2-f13ee5c02a70	540f2fa1-53f8-4e43-9841-8eb881a0c529	99e0459d-5d6d-40ec-9d33-7d4848664a0f	\N	perf-runs/99e0459d-5d6d-40ec-9d33-7d4848664a0f/artifacts/global_usage_CPU_10f74577c68779a5_1794144094648_1794144115958.csv	other	99e0459d-5d6d-40ec-9d33-7d4848664a0f/perf-runs/99e0459d-5d6d-40ec-9d33-7d4848664a0f/artifacts/global_usage_CPU_10f74577c68779a5_1794144094648_1794144115958.csv	text/csv	1349	0fa8e72b62bea3c2618f77a7152a40e7eb1e0aac2702c96720a4e14f237819dd	1	available	\N	2026-11-08 21:21:55.980553+08
98e795e5-3ce5-4cca-9d5a-0eebcfd6b0f9	540f2fa1-53f8-4e43-9841-8eb881a0c529	99e0459d-5d6d-40ec-9d33-7d4848664a0f	\N	perf-runs/99e0459d-5d6d-40ec-9d33-7d4848664a0f/artifacts/global_usage_Memory_28f39911d220c029_1794144094648_1794144115958.csv	other	99e0459d-5d6d-40ec-9d33-7d4848664a0f/perf-runs/99e0459d-5d6d-40ec-9d33-7d4848664a0f/artifacts/global_usage_Memory_28f39911d220c029_1794144094648_1794144115958.csv	text/csv	639	b5d607d3f5fc1490f4c85cae9708f3cc71038a9a5f5db4c78e9c18366e0e8c06	1	available	\N	2026-11-08 21:21:55.980553+08
b7c29a25-01ab-4886-9e5e-514016975515	540f2fa1-53f8-4e43-9841-8eb881a0c529	99e0459d-5d6d-40ec-9d33-7d4848664a0f	\N	perf-runs/99e0459d-5d6d-40ec-9d33-7d4848664a0f/artifacts/privatedirty-main-3765_Memory_af257823d1ac55a7_1794144094648_1794144115958.csv	other	99e0459d-5d6d-40ec-9d33-7d4848664a0f/perf-runs/99e0459d-5d6d-40ec-9d33-7d4848664a0f/artifacts/privatedirty-main-3765_Memory_af257823d1ac55a7_1794144094648_1794144115958.csv	text/csv	145	148ed91dde1e92451233427b335caec7f744b9c1894bff1ae9252785425f3894	1	available	\N	2026-11-08 21:21:55.980553+08
0437ed4a-d092-4b70-906a-78c95c496693	540f2fa1-53f8-4e43-9841-8eb881a0c529	99e0459d-5d6d-40ec-9d33-7d4848664a0f	\N	perf-runs/99e0459d-5d6d-40ec-9d33-7d4848664a0f/artifacts/privatedirty-main-7260_Memory_7b459cc664f5ff31_1794144094648_1794144115958.csv	other	99e0459d-5d6d-40ec-9d33-7d4848664a0f/perf-runs/99e0459d-5d6d-40ec-9d33-7d4848664a0f/artifacts/privatedirty-main-7260_Memory_7b459cc664f5ff31_1794144094648_1794144115958.csv	text/csv	519	31f84b29543b64a5c352682a5ecdd3770b34a990636894e86acd29150ea5acd4	1	available	\N	2026-11-08 21:21:55.980553+08
b3a037a0-5186-401f-9c5c-d685990fce49	540f2fa1-53f8-4e43-9841-8eb881a0c529	99e0459d-5d6d-40ec-9d33-7d4848664a0f	\N	perf-runs/99e0459d-5d6d-40ec-9d33-7d4848664a0f/artifacts/pss-main-3765_Memory_80e0f8a704df256c_1794144094648_1794144115958.csv	other	99e0459d-5d6d-40ec-9d33-7d4848664a0f/perf-runs/99e0459d-5d6d-40ec-9d33-7d4848664a0f/artifacts/pss-main-3765_Memory_80e0f8a704df256c_1794144094648_1794144115958.csv	text/csv	139	482939adfb0f082b0fc24fc03a36588d93447144bd76149671939fcd39dd2666	1	available	\N	2026-11-08 21:21:55.980553+08
b05e6940-54d7-4eb5-bd37-53f24a7beb1b	540f2fa1-53f8-4e43-9841-8eb881a0c529	99e0459d-5d6d-40ec-9d33-7d4848664a0f	\N	perf-runs/99e0459d-5d6d-40ec-9d33-7d4848664a0f/artifacts/pss-main-7260_Memory_7f594b01ac9486eb_1794144094648_1794144115958.csv	other	99e0459d-5d6d-40ec-9d33-7d4848664a0f/perf-runs/99e0459d-5d6d-40ec-9d33-7d4848664a0f/artifacts/pss-main-7260_Memory_7f594b01ac9486eb_1794144094648_1794144115958.csv	text/csv	509	be20a7d272adf3bba6bbbe4f0304ee1cfcc170099f009b96fed290da25cb0ad7	1	available	\N	2026-11-08 21:21:55.980553+08
7fdc50f6-8f98-46fe-b57d-16759ac37941	540f2fa1-53f8-4e43-9841-8eb881a0c529	99e0459d-5d6d-40ec-9d33-7d4848664a0f	\N	perf-runs/99e0459d-5d6d-40ec-9d33-7d4848664a0f/artifacts/supplement_thermal_gpu.csv	other	99e0459d-5d6d-40ec-9d33-7d4848664a0f/perf-runs/99e0459d-5d6d-40ec-9d33-7d4848664a0f/artifacts/supplement_thermal_gpu.csv	text/csv	384	f4429f00422370919dbbd7969972b9ee1e48aa0b58e1bb408cc3f66b370cbcb1	1	available	\N	2026-11-08 21:21:55.980553+08
8923f2f5-b594-4b1b-841d-4d4b853187d1	540f2fa1-53f8-4e43-9841-8eb881a0c529	99e0459d-5d6d-40ec-9d33-7d4848664a0f	\N	runs/main.json	report_json	99e0459d-5d6d-40ec-9d33-7d4848664a0f/runs/main.json	application/json	143	bcbde367b1ef7fe85230183799467cf0f11f514c863d59c2b5300697f9b3d065	1	available	\N	2026-11-08 21:21:55.980553+08
bb5db3d5-9053-4bd7-9796-ab24557595cb	540f2fa1-53f8-4e43-9841-8eb881a0c529	d8c1ea76-e45d-4629-8152-bb2697af04f0	\N	mobile-config.toml	other	d8c1ea76-e45d-4629-8152-bb2697af04f0/mobile-config.toml	application/octet-stream	271	4099dea684648a0031373da475e16db86fffdf18559aabe3eb5488fdb672742d	1	available	\N	2026-11-08 21:24:09.471599+08
ed183b8d-7440-4317-850c-8f2c946b1ddb	540f2fa1-53f8-4e43-9841-8eb881a0c529	d8c1ea76-e45d-4629-8152-bb2697af04f0	\N	perf.sqlite3	other	d8c1ea76-e45d-4629-8152-bb2697af04f0/perf.sqlite3	application/octet-stream	4096	42f67cde08aaa4db17432058fdd3521a7199a1dfd4afe740ca486d6b49226302	1	available	\N	2026-11-08 21:24:09.471599+08
9220cbbc-3cc9-4038-bb1e-218134cd39e9	540f2fa1-53f8-4e43-9841-8eb881a0c529	d8c1ea76-e45d-4629-8152-bb2697af04f0	\N	perf.sqlite3-shm	other	d8c1ea76-e45d-4629-8152-bb2697af04f0/perf.sqlite3-shm	application/octet-stream	32768	c46eba0fb4044dad177c6eda0c4b3360c3a98a045200563e5394fad1add5981d	1	available	\N	2026-11-08 21:24:09.471599+08
c59f31ab-4db9-4c78-94cc-b2b1353f5efc	540f2fa1-53f8-4e43-9841-8eb881a0c529	d8c1ea76-e45d-4629-8152-bb2697af04f0	\N	perf.sqlite3-wal	other	d8c1ea76-e45d-4629-8152-bb2697af04f0/perf.sqlite3-wal	application/octet-stream	98912	6212950f31c48ab84ad913340b89dca31999a534eb7ce4f7bbfa52adfc099d77	1	available	\N	2026-11-08 21:24:09.471599+08
26f7f828-0415-4b63-a6cf-a8e4a8fe8106	540f2fa1-53f8-4e43-9841-8eb881a0c529	d8c1ea76-e45d-4629-8152-bb2697af04f0	\N	report.json	report_json	d8c1ea76-e45d-4629-8152-bb2697af04f0/report.json	application/json	21792	701f67dca4181a79c06241319b14255758a3742f7567609f3601ef5e85362bcd	1	available	\N	2026-11-08 21:24:09.471599+08
4ac29b25-7c32-4d37-8983-c4e58463829c	540f2fa1-53f8-4e43-9841-8eb881a0c529	d8c1ea76-e45d-4629-8152-bb2697af04f0	\N	perf-runs/d8c1ea76-e45d-4629-8152-bb2697af04f0/meta.json	report_json	d8c1ea76-e45d-4629-8152-bb2697af04f0/perf-runs/d8c1ea76-e45d-4629-8152-bb2697af04f0/meta.json	application/json	1119	d11b05ffd84b79e20021f07b466618bec5d050293a6d3377e3560deab19b4d76	1	available	\N	2026-11-08 21:24:09.471599+08
21b802b5-3e0e-48dc-8390-180f90674025	540f2fa1-53f8-4e43-9841-8eb881a0c529	d8c1ea76-e45d-4629-8152-bb2697af04f0	\N	perf-runs/d8c1ea76-e45d-4629-8152-bb2697af04f0/report.html	report_html	d8c1ea76-e45d-4629-8152-bb2697af04f0/perf-runs/d8c1ea76-e45d-4629-8152-bb2697af04f0/report.html	text/html	1056463	da54893289c80e3d9845bbf88017f919fc872f1041bddc31ca89702a1dd93b09	1	available	\N	2026-11-08 21:24:09.471599+08
4a1d6faf-8786-46fe-ad83-6d5b0e5a9c34	540f2fa1-53f8-4e43-9841-8eb881a0c529	d8c1ea76-e45d-4629-8152-bb2697af04f0	\N	perf-runs/d8c1ea76-e45d-4629-8152-bb2697af04f0/report.json	report_json	d8c1ea76-e45d-4629-8152-bb2697af04f0/perf-runs/d8c1ea76-e45d-4629-8152-bb2697af04f0/report.json	application/json	25016	ea9fcb01429bff97338c4bc4e9f1d344c75852e820e6721d569bf986e303ef3b	1	available	\N	2026-11-08 21:24:09.471599+08
5adb1814-c1a8-4fae-8887-68d24fda3f2c	540f2fa1-53f8-4e43-9841-8eb881a0c529	d8c1ea76-e45d-4629-8152-bb2697af04f0	\N	perf-runs/d8c1ea76-e45d-4629-8152-bb2697af04f0/artifacts/app_process-main-7260_CPU_e8c5887f106e39e6_1794144228772_1794144249466.csv	other	d8c1ea76-e45d-4629-8152-bb2697af04f0/perf-runs/d8c1ea76-e45d-4629-8152-bb2697af04f0/artifacts/app_process-main-7260_CPU_e8c5887f106e39e6_1794144228772_1794144249466.csv	text/csv	358	0ef3fac0774ce865f5b1f87a16f231e0bc2eb9b4657f369b7b4fa4c08082164b	1	available	\N	2026-11-08 21:24:09.471599+08
d52361fd-9b21-4a0c-b9cc-25cf5c195b03	540f2fa1-53f8-4e43-9841-8eb881a0c529	d8c1ea76-e45d-4629-8152-bb2697af04f0	\N	perf-runs/d8c1ea76-e45d-4629-8152-bb2697af04f0/artifacts/app_process-main-9438_CPU_ba135557f3052851_1794144228772_1794144249466.csv	other	d8c1ea76-e45d-4629-8152-bb2697af04f0/perf-runs/d8c1ea76-e45d-4629-8152-bb2697af04f0/artifacts/app_process-main-9438_CPU_ba135557f3052851_1794144228772_1794144249466.csv	text/csv	931	06b8c30b3e2791dc2536599c6728a0839d761d89e2a7f3355215750eade6d14d	1	available	\N	2026-11-08 21:24:09.471599+08
2878711c-84dc-4dc4-b7e7-471a687e03a7	540f2fa1-53f8-4e43-9841-8eb881a0c529	d8c1ea76-e45d-4629-8152-bb2697af04f0	\N	perf-runs/d8c1ea76-e45d-4629-8152-bb2697af04f0/artifacts/fps_FPS_c284f0ee54042fc7_1794144228772_1794144249467.csv	other	d8c1ea76-e45d-4629-8152-bb2697af04f0/perf-runs/d8c1ea76-e45d-4629-8152-bb2697af04f0/artifacts/fps_FPS_c284f0ee54042fc7_1794144228772_1794144249467.csv	text/csv	920	1eee836e2fb19810bb85454a66b22659ed82679f6a2f57a3dcace130e67e6146	1	available	\N	2026-11-08 21:24:09.471599+08
1f6fe0f0-07e4-4001-9809-75fca430e378	540f2fa1-53f8-4e43-9841-8eb881a0c529	d8c1ea76-e45d-4629-8152-bb2697af04f0	\N	perf-runs/d8c1ea76-e45d-4629-8152-bb2697af04f0/artifacts/frame_delay_count_FPS_b328f3a3f9cbfb98_1794144228772_1794144249467.csv	other	d8c1ea76-e45d-4629-8152-bb2697af04f0/perf-runs/d8c1ea76-e45d-4629-8152-bb2697af04f0/artifacts/frame_delay_count_FPS_b328f3a3f9cbfb98_1794144228772_1794144249467.csv	text/csv	886	89ae1b4532b60b1a40239920f5565684bf22986c5d3560a972a4c676439716d5	1	available	\N	2026-11-08 21:24:09.471599+08
40e57e33-dfde-47b4-94e9-456d4333ba9c	540f2fa1-53f8-4e43-9841-8eb881a0c529	d8c1ea76-e45d-4629-8152-bb2697af04f0	\N	perf-runs/d8c1ea76-e45d-4629-8152-bb2697af04f0/artifacts/frame_delay_max_FPS_e80f27c3c81dc4e3_1794144228772_1794144249467.csv	other	d8c1ea76-e45d-4629-8152-bb2697af04f0/perf-runs/d8c1ea76-e45d-4629-8152-bb2697af04f0/artifacts/frame_delay_max_FPS_e80f27c3c81dc4e3_1794144228772_1794144249467.csv	text/csv	894	383e758b705809ac4976def84406150637e4e91f3e46609741acb8996e5cb9af	1	available	\N	2026-11-08 21:24:09.471599+08
27f2efdc-3623-4fcb-9bc6-eef1abde6baa	540f2fa1-53f8-4e43-9841-8eb881a0c529	d8c1ea76-e45d-4629-8152-bb2697af04f0	\N	perf-runs/d8c1ea76-e45d-4629-8152-bb2697af04f0/artifacts/frame_delay_ratio_FPS_1e2e7579fb43ef3d_1794144228772_1794144249467.csv	other	d8c1ea76-e45d-4629-8152-bb2697af04f0/perf-runs/d8c1ea76-e45d-4629-8152-bb2697af04f0/artifacts/frame_delay_ratio_FPS_1e2e7579fb43ef3d_1794144228772_1794144249467.csv	text/csv	899	fac09962d5e862fcf2cc5d06ba6179b1b4ab544ffad6398b724b641d561f8539	1	available	\N	2026-11-08 21:24:09.471599+08
acf7f5d4-6585-43c4-a928-711bba8b8aae	540f2fa1-53f8-4e43-9841-8eb881a0c529	d8c1ea76-e45d-4629-8152-bb2697af04f0	\N	perf-runs/d8c1ea76-e45d-4629-8152-bb2697af04f0/artifacts/global_usage_CPU_9df5a9a664cc3464_1794144228772_1794144249466.csv	other	d8c1ea76-e45d-4629-8152-bb2697af04f0/perf-runs/d8c1ea76-e45d-4629-8152-bb2697af04f0/artifacts/global_usage_CPU_9df5a9a664cc3464_1794144228772_1794144249466.csv	text/csv	1315	d54e815051674938c0ac720f10d356421a980c34236c47cad42b45e73331e807	1	available	\N	2026-11-08 21:24:09.471599+08
f33f6f8a-2905-4807-bf96-dd80a5c3fcda	540f2fa1-53f8-4e43-9841-8eb881a0c529	d8c1ea76-e45d-4629-8152-bb2697af04f0	\N	perf-runs/d8c1ea76-e45d-4629-8152-bb2697af04f0/artifacts/global_usage_Memory_eb0b8117dbe559c5_1794144228772_1794144249467.csv	other	d8c1ea76-e45d-4629-8152-bb2697af04f0/perf-runs/d8c1ea76-e45d-4629-8152-bb2697af04f0/artifacts/global_usage_Memory_eb0b8117dbe559c5_1794144228772_1794144249467.csv	text/csv	577	906c163735f3910e877b156bfd1f1b75c306c5adcbba7732241af84209f48565	1	available	\N	2026-11-08 21:24:09.471599+08
0bda5774-580c-4f42-a2c0-c6c31527f98a	540f2fa1-53f8-4e43-9841-8eb881a0c529	d8c1ea76-e45d-4629-8152-bb2697af04f0	\N	perf-runs/d8c1ea76-e45d-4629-8152-bb2697af04f0/artifacts/privatedirty-main-7260_Memory_00dee0d095ae03dc_1794144228772_1794144249467.csv	other	d8c1ea76-e45d-4629-8152-bb2697af04f0/perf-runs/d8c1ea76-e45d-4629-8152-bb2697af04f0/artifacts/privatedirty-main-7260_Memory_00dee0d095ae03dc_1794144228772_1794144249467.csv	text/csv	116	7dc4be71c0c2ac4840da7d591387b4a2715f72447840538abc5f0d91444e73c1	1	available	\N	2026-11-08 21:24:09.471599+08
a67e7ee6-3421-456b-81fe-d1e3c7d53494	540f2fa1-53f8-4e43-9841-8eb881a0c529	d8c1ea76-e45d-4629-8152-bb2697af04f0	\N	perf-runs/d8c1ea76-e45d-4629-8152-bb2697af04f0/artifacts/privatedirty-main-9438_Memory_4ccd47be72f30dd1_1794144228772_1794144249467.csv	other	d8c1ea76-e45d-4629-8152-bb2697af04f0/perf-runs/d8c1ea76-e45d-4629-8152-bb2697af04f0/artifacts/privatedirty-main-9438_Memory_4ccd47be72f30dd1_1794144228772_1794144249467.csv	text/csv	452	8df7ee816bf94ab9a8317a9b762b4acfe9b13b8e0a07d679fbeb129ace58f49b	1	available	\N	2026-11-08 21:24:09.471599+08
06457b59-1b16-4396-b736-1b61e6c0754e	540f2fa1-53f8-4e43-9841-8eb881a0c529	d8c1ea76-e45d-4629-8152-bb2697af04f0	\N	perf-runs/d8c1ea76-e45d-4629-8152-bb2697af04f0/artifacts/pss-main-7260_Memory_ffb55af6c1185745_1794144228772_1794144249467.csv	other	d8c1ea76-e45d-4629-8152-bb2697af04f0/perf-runs/d8c1ea76-e45d-4629-8152-bb2697af04f0/artifacts/pss-main-7260_Memory_ffb55af6c1185745_1794144228772_1794144249467.csv	text/csv	107	918375cc80f817d41a5f143a72f07515d712ae1bb1f8705232e378ffe49208a0	1	available	\N	2026-11-08 21:24:09.471599+08
e079cac1-a16e-4fa3-9d78-b36e1689da48	540f2fa1-53f8-4e43-9841-8eb881a0c529	d8c1ea76-e45d-4629-8152-bb2697af04f0	\N	perf-runs/d8c1ea76-e45d-4629-8152-bb2697af04f0/artifacts/pss-main-9438_Memory_140167717d8a74fd_1794144228772_1794144249467.csv	other	d8c1ea76-e45d-4629-8152-bb2697af04f0/perf-runs/d8c1ea76-e45d-4629-8152-bb2697af04f0/artifacts/pss-main-9438_Memory_140167717d8a74fd_1794144228772_1794144249467.csv	text/csv	445	069c6cb0936ed31cf3f983e11fff2776ee286f714d3129bb4b86c3b2f39b8a22	1	available	\N	2026-11-08 21:24:09.471599+08
5e032804-3e6d-4929-bbaa-7c1498dd0f2b	540f2fa1-53f8-4e43-9841-8eb881a0c529	d8c1ea76-e45d-4629-8152-bb2697af04f0	\N	perf-runs/d8c1ea76-e45d-4629-8152-bb2697af04f0/artifacts/supplement_thermal_gpu.csv	other	d8c1ea76-e45d-4629-8152-bb2697af04f0/perf-runs/d8c1ea76-e45d-4629-8152-bb2697af04f0/artifacts/supplement_thermal_gpu.csv	text/csv	383	2be467a9e906ef917cfc0e42c287f6eea297a5d63fc90a9f46cc75ad15023996	1	available	\N	2026-11-08 21:24:09.471599+08
768c5140-06da-437b-bc0c-509892c4124a	540f2fa1-53f8-4e43-9841-8eb881a0c529	d8c1ea76-e45d-4629-8152-bb2697af04f0	\N	runs/main.json	report_json	d8c1ea76-e45d-4629-8152-bb2697af04f0/runs/main.json	application/json	143	43e67a6decd74caa7d948b683f042effaa54418caa4503b4781b68feb854ebcc	1	available	\N	2026-11-08 21:24:09.471599+08
\.


--
-- Data for Name: audit_events; Type: TABLE DATA; Schema: public; Owner: testdock
--

COPY public.audit_events (id, project_id, actor_ref, action, entity_type, entity_id, request_id, changes, created_at) FROM stdin;
9192cc7b-1a89-483a-9e66-71d4cb0d3409	540f2fa1-53f8-4e43-9841-8eb881a0c529	web-client	debug_session_created	debug_session	9319ff19-4689-4652-86e8-57e4900a92f1	2f6c0236ff0b40219608f8d908b92009	{"serial": "749622c9", "purpose": "定位排查", "lease_id": "681dd812-3a55-4055-ace4-74e686d018c1", "actor_ref": "web-client"}	2026-11-08 21:18:38.879955+08
d380cc74-0272-4c39-8eaa-2a3deb2612ea	540f2fa1-53f8-4e43-9841-8eb881a0c529	web-client	debug_session_closed	debug_session	9319ff19-4689-4652-86e8-57e4900a92f1	c089387376a44060b01c7403fb7b833b	{"reason": "client_closed"}	2026-11-08 21:21:11.376485+08
316b0ef0-d071-4306-9c58-174570344df8	540f2fa1-53f8-4e43-9841-8eb881a0c529	web-client	debug_session_created	debug_session	705f9c1c-57f2-4e20-8df9-3f6c244260ac	52556d9ee6e84060a52e507443940400	{"serial": "749622c9", "purpose": "定位排查", "lease_id": "51903e1c-f845-44b7-906e-ebcc68c7cf18", "actor_ref": "web-client"}	2026-11-08 21:22:04.362634+08
76140b58-dd11-45d8-bac8-7f6395dbdc5a	540f2fa1-53f8-4e43-9841-8eb881a0c529	web-client	debug_session_closed	debug_session	705f9c1c-57f2-4e20-8df9-3f6c244260ac	e62eb18b14e84ba88b7f4b4da8d6d632	{"reason": "client_closed"}	2026-11-08 21:23:43.562196+08
128e285a-7e18-413c-9f00-659942331b4a	540f2fa1-53f8-4e43-9841-8eb881a0c529	web-client	debug_session_created	debug_session	15b62103-1625-4c01-bcae-9d0bf36bdba9	a19ef167c4ab424fb951b4c2ff40c8a1	{"serial": "749622c9", "purpose": "", "lease_id": "9b3caa55-161b-4684-980c-3ea64e89f344", "actor_ref": "web-client"}	2026-11-08 21:24:11.039493+08
4292069e-c17d-4141-9dca-79dc39d9f5c8	540f2fa1-53f8-4e43-9841-8eb881a0c529	web-client	debug_session_closed	debug_session	15b62103-1625-4c01-bcae-9d0bf36bdba9	a1573e72ff334bf3a0e5d5d1a17c810e	{"reason": "client_closed"}	2026-11-08 21:25:45.171387+08
\.


--
-- Data for Name: baselines; Type: TABLE DATA; Schema: public; Owner: testdock
--

COPY public.baselines (id, project_id, application_id, environment_id, suite_version_id, profile_id, source_component_id, name, version, metrics_snapshot, created_at) FROM stdin;
\.


--
-- Data for Name: case_results; Type: TABLE DATA; Schema: public; Owner: testdock
--

COPY public.case_results (id, project_id, component_id, case_key, attempt, outcome, duration_ms, error_summary, steps, created_at) FROM stdin;
ac6bf141-03cf-43da-a9e0-8ff05c7b2cd5	540f2fa1-53f8-4e43-9841-8eb881a0c529	3c13d901-4633-4b88-9dc3-da5620086662	code-copies.b475bb18efac4d05bd903281643a50c1.test_deliberate_failure::test_deliberate_assertion_failure_for_evidence	1	failed	1	AssertionError: 预期内的故意失败：用于验证失败结论与证据产物保留（release-readiness 02）\nassert False	[]	2026-11-08 20:18:08.719638+08
cf376c38-61ce-4f59-9caf-5d898913873d	540f2fa1-53f8-4e43-9841-8eb881a0c529	3c13d901-4633-4b88-9dc3-da5620086662	code-copies.b475bb18efac4d05bd903281643a50c1.test_smoke::test_session_is_bound_to_dispatch_device	1	passed	1000	\N	[]	2026-11-08 20:18:08.719638+08
ec457954-c645-40d8-b3a1-71ec7072c6fd	540f2fa1-53f8-4e43-9841-8eb881a0c529	3c13d901-4633-4b88-9dc3-da5620086662	code-copies.b475bb18efac4d05bd903281643a50c1.test_smoke::test_app_launches_and_screenshot_is_a_real_frame	1	passed	2785	\N	[]	2026-11-08 20:18:08.719638+08
e93f0e6a-9364-4253-9aea-54684e4389b5	540f2fa1-53f8-4e43-9841-8eb881a0c529	3c13d901-4633-4b88-9dc3-da5620086662	code-copies.b475bb18efac4d05bd903281643a50c1.test_smoke::test_ui_stays_foreground_long_enough_for_perf_sampling	1	passed	15085	\N	[]	2026-11-08 20:18:08.719638+08
b9dfcdd9-92e9-42ca-a395-06c12b311a1f	540f2fa1-53f8-4e43-9841-8eb881a0c529	79752cae-37e0-45dc-9f62-25b95c075f10	code-copies.b475bb18efac4d05bd903281643a50c1.test_deliberate_failure::test_deliberate_assertion_failure_for_evidence	1	failed	1	AssertionError: 预期内的故意失败：用于验证失败结论与证据产物保留（release-readiness 02）\nassert False	[]	2026-11-08 20:46:22.70876+08
c6169f87-2e25-4473-92f2-ae28e7519bb2	540f2fa1-53f8-4e43-9841-8eb881a0c529	79752cae-37e0-45dc-9f62-25b95c075f10	code-copies.b475bb18efac4d05bd903281643a50c1.test_smoke::test_session_is_bound_to_dispatch_device	1	passed	1428	\N	[]	2026-11-08 20:46:22.70876+08
b8932533-a831-4353-a906-a6033f84d9fb	540f2fa1-53f8-4e43-9841-8eb881a0c529	79752cae-37e0-45dc-9f62-25b95c075f10	code-copies.b475bb18efac4d05bd903281643a50c1.test_smoke::test_app_launches_and_screenshot_is_a_real_frame	1	passed	2663	\N	[]	2026-11-08 20:46:22.70876+08
e3f455ea-c8dc-4e32-b823-221721f69e9a	540f2fa1-53f8-4e43-9841-8eb881a0c529	79752cae-37e0-45dc-9f62-25b95c075f10	code-copies.b475bb18efac4d05bd903281643a50c1.test_smoke::test_ui_stays_foreground_long_enough_for_perf_sampling	1	passed	15085	\N	[]	2026-11-08 20:46:22.70876+08
31941b26-e713-416c-ba29-7d3f4eb81471	540f2fa1-53f8-4e43-9841-8eb881a0c529	ce349940-a93a-4554-9c15-fd42ea93dca4	code-copies.79eac297a75b4783af700a43bb8dabee.test_deliberate_failure::test_deliberate_assertion_failure_for_evidence	1	failed	1	AssertionError: 预期内的故意失败：用于验证失败结论与证据产物保留（release-readiness 02）\nassert False	[]	2026-11-08 21:12:46.205621+08
6c1dc45e-e213-4ee1-a7fe-8efdf0b41cb4	540f2fa1-53f8-4e43-9841-8eb881a0c529	ce349940-a93a-4554-9c15-fd42ea93dca4	code-copies.79eac297a75b4783af700a43bb8dabee.test_smoke::test_session_is_bound_to_dispatch_device	1	passed	907	\N	[]	2026-11-08 21:12:46.205621+08
51b57578-1e58-462d-8faa-41e1bf670c27	540f2fa1-53f8-4e43-9841-8eb881a0c529	ce349940-a93a-4554-9c15-fd42ea93dca4	code-copies.79eac297a75b4783af700a43bb8dabee.test_smoke::test_app_launches_and_screenshot_is_a_real_frame	1	passed	2533	\N	[]	2026-11-08 21:12:46.205621+08
88a271a6-0cdb-4fd4-b6fb-93a30f96940b	540f2fa1-53f8-4e43-9841-8eb881a0c529	ce349940-a93a-4554-9c15-fd42ea93dca4	code-copies.79eac297a75b4783af700a43bb8dabee.test_smoke::test_ui_stays_foreground_long_enough_for_perf_sampling	1	passed	15079	\N	[]	2026-11-08 21:12:46.205621+08
4898e03f-fcb2-4528-912a-9fb90ff21ac3	540f2fa1-53f8-4e43-9841-8eb881a0c529	2ea7fd33-d842-4f0e-b51a-2c39469710da	code-copies.79eac297a75b4783af700a43bb8dabee.test_deliberate_failure::test_deliberate_assertion_failure_for_evidence	1	failed	1	AssertionError: 预期内的故意失败：用于验证失败结论与证据产物保留（release-readiness 02）\nassert False	[]	2026-11-08 21:17:03.102559+08
0fbc6311-bb36-46c8-aac7-344c77f39083	540f2fa1-53f8-4e43-9841-8eb881a0c529	2ea7fd33-d842-4f0e-b51a-2c39469710da	code-copies.79eac297a75b4783af700a43bb8dabee.test_smoke::test_session_is_bound_to_dispatch_device	1	passed	918	\N	[]	2026-11-08 21:17:03.102559+08
dac353dc-4cfb-4fb3-ac5b-def7e23d8e15	540f2fa1-53f8-4e43-9841-8eb881a0c529	2ea7fd33-d842-4f0e-b51a-2c39469710da	code-copies.79eac297a75b4783af700a43bb8dabee.test_smoke::test_app_launches_and_screenshot_is_a_real_frame	1	passed	2665	\N	[]	2026-11-08 21:17:03.102559+08
1ebd99bc-6f35-4ee1-9bc3-c38d44825143	540f2fa1-53f8-4e43-9841-8eb881a0c529	2ea7fd33-d842-4f0e-b51a-2c39469710da	code-copies.79eac297a75b4783af700a43bb8dabee.test_smoke::test_ui_stays_foreground_long_enough_for_perf_sampling	1	passed	15092	\N	[]	2026-11-08 21:17:03.102559+08
5646e2f5-0f0a-40e0-9c2e-8930a73a3f91	540f2fa1-53f8-4e43-9841-8eb881a0c529	74e67528-38b7-4b00-81ef-e90d4e18c2d9	code-copies.79eac297a75b4783af700a43bb8dabee.test_deliberate_failure::test_deliberate_assertion_failure_for_evidence	1	failed	1	AssertionError: 预期内的故意失败：用于验证失败结论与证据产物保留（release-readiness 02）\nassert False	[]	2026-11-08 21:21:55.980553+08
b15d79d4-855b-4ce4-a8a2-f08387f6da6b	540f2fa1-53f8-4e43-9841-8eb881a0c529	74e67528-38b7-4b00-81ef-e90d4e18c2d9	code-copies.79eac297a75b4783af700a43bb8dabee.test_smoke::test_session_is_bound_to_dispatch_device	1	passed	894	\N	[]	2026-11-08 21:21:55.980553+08
bd55a07d-18b7-4101-98d5-15e90af19d5b	540f2fa1-53f8-4e43-9841-8eb881a0c529	74e67528-38b7-4b00-81ef-e90d4e18c2d9	code-copies.79eac297a75b4783af700a43bb8dabee.test_smoke::test_app_launches_and_screenshot_is_a_real_frame	1	passed	2430	\N	[]	2026-11-08 21:21:55.980553+08
005fec5b-ac69-4804-aadc-fe39f3aacfaa	540f2fa1-53f8-4e43-9841-8eb881a0c529	74e67528-38b7-4b00-81ef-e90d4e18c2d9	code-copies.79eac297a75b4783af700a43bb8dabee.test_smoke::test_ui_stays_foreground_long_enough_for_perf_sampling	1	passed	15135	\N	[]	2026-11-08 21:21:55.980553+08
1eeead92-2e08-4ff0-8d44-ca628d01454f	540f2fa1-53f8-4e43-9841-8eb881a0c529	527179e4-94a8-464e-8710-090e8550654e	code-copies.79eac297a75b4783af700a43bb8dabee.test_deliberate_failure::test_deliberate_assertion_failure_for_evidence	1	failed	1	AssertionError: 预期内的故意失败：用于验证失败结论与证据产物保留（release-readiness 02）\nassert False	[]	2026-11-08 21:24:09.471599+08
bf860195-673a-4df7-a584-3125bef3b13a	540f2fa1-53f8-4e43-9841-8eb881a0c529	527179e4-94a8-464e-8710-090e8550654e	code-copies.79eac297a75b4783af700a43bb8dabee.test_smoke::test_session_is_bound_to_dispatch_device	1	passed	871	\N	[]	2026-11-08 21:24:09.471599+08
21853df9-6f1d-42af-9fbf-bdbaf06e3652	540f2fa1-53f8-4e43-9841-8eb881a0c529	527179e4-94a8-464e-8710-090e8550654e	code-copies.79eac297a75b4783af700a43bb8dabee.test_smoke::test_app_launches_and_screenshot_is_a_real_frame	1	passed	2422	\N	[]	2026-11-08 21:24:09.471599+08
b6c92541-8221-4a84-90fc-61764046f204	540f2fa1-53f8-4e43-9841-8eb881a0c529	527179e4-94a8-464e-8710-090e8550654e	code-copies.79eac297a75b4783af700a43bb8dabee.test_smoke::test_ui_stays_foreground_long_enough_for_perf_sampling	1	passed	15086	\N	[]	2026-11-08 21:24:09.471599+08
\.


--
-- Data for Name: debug_sessions; Type: TABLE DATA; Schema: public; Owner: testdock
--

COPY public.debug_sessions (id, project_id, resource_id, actor_ref, state, expires_at, closed_at, created_at) FROM stdin;
9319ff19-4689-4652-86e8-57e4900a92f1	540f2fa1-53f8-4e43-9841-8eb881a0c529	fab1ee61-4ece-4fc5-92bc-4bc0b13427a2	web-client	closed	2026-11-08 22:18:38.88472+08	2026-11-08 21:21:11.376485+08	2026-11-08 21:18:38.879955+08
705f9c1c-57f2-4e20-8df9-3f6c244260ac	540f2fa1-53f8-4e43-9841-8eb881a0c529	fab1ee61-4ece-4fc5-92bc-4bc0b13427a2	web-client	closed	2026-11-08 22:22:04.364453+08	2026-11-08 21:23:43.562196+08	2026-11-08 21:22:04.362634+08
15b62103-1625-4c01-bcae-9d0bf36bdba9	540f2fa1-53f8-4e43-9841-8eb881a0c529	fab1ee61-4ece-4fc5-92bc-4bc0b13427a2	web-client	closed	2026-11-08 22:24:11.040624+08	2026-11-08 21:25:45.171387+08	2026-11-08 21:24:11.039493+08
\.


--
-- Data for Name: device_checks; Type: TABLE DATA; Schema: public; Owner: testdock
--

COPY public.device_checks (id, project_id, resource_id, kind, test_type, holder_id, state, requested_at, started_at, finished_at, expires_at, result, error_code, created_at) FROM stdin;
b1bd262e-abbd-4fec-8442-c97aa27bc0fa	540f2fa1-53f8-4e43-9841-8eb881a0c529	fab1ee61-4ece-4fc5-92bc-4bc0b13427a2	identity	ui	web	finished	2026-11-08 20:11:01.353922+08	2026-11-08 20:11:01.353922+08	2026-11-08 20:11:01.353922+08	2026-11-08 20:11:31.353922+08	{"items": [{"name": "package_name", "status": "match", "expected": "com.miui.calculator", "observed": "com.miui.calculator"}, {"name": "version_name", "status": "match", "expected": "15.0.14", "observed": "15.0.14"}, {"name": "version_code", "status": "observed", "expected": null, "observed": 315000014}], "device": {"serial": "749622c9", "resource_id": "fab1ee61-4ece-4fc5-92bc-4bc0b13427a2"}, "result": "match", "purpose": "manual", "blocking": [], "check_id": "b1bd262e-abbd-4fec-8442-c97aa27bc0fa", "expected": {"package_name": "com.miui.calculator", "version_code": null, "version_name": "15.0.14"}, "observed": {"package_name": "com.miui.calculator", "version_code": 315000014, "version_name": "15.0.14"}, "resource": {"id": "fab1ee61-4ece-4fc5-92bc-4bc0b13427a2", "serial": "749622c9"}, "test_type": "ui", "checked_at": "2026-11-08T12:11:01.549094+00:00", "superseded_at": null, "superseded_by": null, "identity_state": "pending", "execution_allowed": true, "verification_note": "身份核对等级：设备上已安装包的包名、versionName 与 versionCode（只读读取）；未验证 APK 文件摘要，sha256 仅为登记声明。", "verification_level": "package_identity_observed", "apk_digest_verified": false}	\N	2026-11-08 20:11:01.353922+08
\.


--
-- Data for Name: environments; Type: TABLE DATA; Schema: public; Owner: testdock
--

COPY public.environments (id, project_id, name, config, secret_ref, archived_at, created_at) FROM stdin;
442e284e-2b71-402a-829d-b5679643a28c	540f2fa1-53f8-4e43-9841-8eb881a0c529	default	{}	\N	\N	2026-11-08 20:02:00.094623+08
94a87d9d-0e2c-45d0-a92b-ea051ac61ba6	5000b728-a110-4878-bcc1-41725ae5603b	default	{}	\N	\N	2026-11-08 21:27:57.751801+08
8a171549-e62a-4c63-95d1-e597f2a96c95	6b633466-73ee-47d2-9798-ab21021efe4c	default	{}	\N	\N	2026-11-08 21:43:28.635345+08
\.


--
-- Data for Name: execution_nodes; Type: TABLE DATA; Schema: public; Owner: testdock
--

COPY public.execution_nodes (id, project_id, name, agent_version, capabilities, status, heartbeat_at, created_at) FROM stdin;
0f81303b-272e-4ad9-baa1-ab9076921fe8	540f2fa1-53f8-4e43-9841-8eb881a0c529	本机执行节点	testdock-sync	{"adb": true, "local": true}	online	2026-11-08 20:04:08.667609+08	2026-11-08 20:04:08.667609+08
\.


--
-- Data for Name: execution_resources; Type: TABLE DATA; Schema: public; Owner: testdock
--

COPY public.execution_resources (id, project_id, node_id, profile_id, platform, resource_key, kind, status, fence_counter, created_at, last_seen_at) FROM stdin;
fab1ee61-4ece-4fc5-92bc-4bc0b13427a2	540f2fa1-53f8-4e43-9841-8eb881a0c529	0f81303b-272e-4ad9-baa1-ab9076921fe8	f2cac493-a152-47fb-b25a-fa7d5672dc85	android	749622c9	device	ready	13	2026-11-08 20:04:08.667609+08	2026-11-08 20:04:08.667609+08
\.


--
-- Data for Name: gate_evaluations; Type: TABLE DATA; Schema: public; Owner: testdock
--

COPY public.gate_evaluations (id, project_id, component_id, policy_id, baseline_id, mode, request_key, verdict, reason_code, checks, created_at) FROM stdin;
8577312e-f85e-4a72-81bc-39957bbdb938	540f2fa1-53f8-4e43-9841-8eb881a0c529	55e43783-2e99-4ba6-9a48-53d7221878cb	d32da8aa-7976-4a79-87a6-6f138ba3c1b5	\N	original	original:7ca839a0-d955-4a7e-aa64-290382c63453	not_tested	gate_policy_missing	[{"reason_code": "gate_policy_missing", "reason_text": "缺少门禁策略，无法判定"}]	2026-11-08 20:53:33.424816+08
2081aeb9-9ae6-4e06-ae8d-f8dff81c0ef0	540f2fa1-53f8-4e43-9841-8eb881a0c529	55e43783-2e99-4ba6-9a48-53d7221878cb	d32da8aa-7976-4a79-87a6-6f138ba3c1b5	\N	reanalysis	rr-reanalysis-1794142531	not_tested	baseline_missing	[{"reason_code": "baseline_missing", "reason_text": "缺少可比基线，无法判定"}]	2026-11-08 20:55:31.57482+08
fbb4dbbe-7d86-4050-a445-8b9d4baef84d	540f2fa1-53f8-4e43-9841-8eb881a0c529	1fd40ad8-d824-4a30-a169-3d636eadfb42	d32da8aa-7976-4a79-87a6-6f138ba3c1b5	\N	original	original:ec832d64-466a-437a-8dcc-6a2efb9eede6	not_tested	baseline_missing	[{"reason_code": "baseline_missing", "reason_text": "缺少可比基线，无法判定"}]	2026-11-08 21:12:46.205621+08
f16a1ce4-f226-48c9-ad04-d54bf0d9ea53	540f2fa1-53f8-4e43-9841-8eb881a0c529	9ad8f101-9763-4a10-90cc-92033b5fe9b3	d32da8aa-7976-4a79-87a6-6f138ba3c1b5	\N	original	original:2b814545-aada-4196-90ae-706dbbaf4d76	not_tested	baseline_missing	[{"reason_code": "baseline_missing", "reason_text": "缺少可比基线，无法判定"}]	2026-11-08 21:17:03.102559+08
d59210e6-e4f2-4213-9502-ab469898e023	540f2fa1-53f8-4e43-9841-8eb881a0c529	19feff9e-e556-4e05-932e-3bc8ff51f0ae	d32da8aa-7976-4a79-87a6-6f138ba3c1b5	\N	original	original:99e0459d-5d6d-40ec-9d33-7d4848664a0f	not_tested	baseline_missing	[{"reason_code": "baseline_missing", "reason_text": "缺少可比基线，无法判定"}]	2026-11-08 21:21:55.980553+08
98f61ea5-51e0-48eb-b3ad-2b641066dbb5	540f2fa1-53f8-4e43-9841-8eb881a0c529	206414d0-f279-464d-894c-b351afe61c79	d32da8aa-7976-4a79-87a6-6f138ba3c1b5	\N	original	original:d8c1ea76-e45d-4629-8152-bb2697af04f0	not_tested	baseline_missing	[{"reason_code": "baseline_missing", "reason_text": "缺少可比基线，无法判定"}]	2026-11-08 21:24:09.471599+08
\.


--
-- Data for Name: gate_policies; Type: TABLE DATA; Schema: public; Owner: testdock
--

COPY public.gate_policies (id, project_id, application_id, name, version, rules, created_at) FROM stdin;
d32da8aa-7976-4a79-87a6-6f138ba3c1b5	540f2fa1-53f8-4e43-9841-8eb881a0c529	a9feb4f2-9d51-4d6e-9ea1-aeb423901f5f	__missing_policy__	1	{}	2026-11-08 20:53:33.424816+08
\.


--
-- Data for Name: metric_summaries; Type: TABLE DATA; Schema: public; Owner: testdock
--

COPY public.metric_summaries (id, project_id, component_id, metric_key, metric_version, unit, scope, window_key, statistic, sample_count, value, missing_reason, created_at, missing_reason_text) FROM stdin;
daa3fe2c-d6d9-43fb-aa91-b69318e951af	540f2fa1-53f8-4e43-9841-8eb881a0c529	55e43783-2e99-4ba6-9a48-53d7221878cb	cpu_process_pct	1.0	%	component	2026-11-08T20:52:59+08:00/2026-11-08T20:53:33+08:00	min	61	0	\N	2026-11-08 20:53:33.424816+08	\N
a7de69fd-1edd-4f49-9eb1-f9ecf47b52f7	540f2fa1-53f8-4e43-9841-8eb881a0c529	55e43783-2e99-4ba6-9a48-53d7221878cb	cpu_process_pct	1.0	%	component	2026-11-08T20:52:59+08:00/2026-11-08T20:53:33+08:00	median	61	0.7518797	\N	2026-11-08 20:53:33.424816+08	\N
1401c972-c33d-49ee-bae6-59d05f0373fc	540f2fa1-53f8-4e43-9841-8eb881a0c529	55e43783-2e99-4ba6-9a48-53d7221878cb	cpu_process_pct	1.0	%	component	2026-11-08T20:52:59+08:00/2026-11-08T20:53:33+08:00	mean	61	1.6215666700000002	\N	2026-11-08 20:53:33.424816+08	\N
fd32451c-9d6f-4340-8bc7-4f1d5baf69db	540f2fa1-53f8-4e43-9841-8eb881a0c529	55e43783-2e99-4ba6-9a48-53d7221878cb	cpu_process_pct	1.0	%	component	2026-11-08T20:52:59+08:00/2026-11-08T20:53:33+08:00	max	61	4.511278	\N	2026-11-08 20:53:33.424816+08	\N
aba46414-def5-4bd1-8126-002159f5a4cd	540f2fa1-53f8-4e43-9841-8eb881a0c529	55e43783-2e99-4ba6-9a48-53d7221878cb	cpu_process_pct	1.0	%	component	2026-11-08T20:52:59+08:00/2026-11-08T20:53:33+08:00	p90	61	3.25	\N	2026-11-08 20:53:33.424816+08	\N
3cbe1daf-4acd-4998-98ae-485bddb7cb0b	540f2fa1-53f8-4e43-9841-8eb881a0c529	55e43783-2e99-4ba6-9a48-53d7221878cb	cpu_global_pct	1.0	%	component	2026-11-08T20:52:59+08:00/2026-11-08T20:53:33+08:00	min	61	4.556962	\N	2026-11-08 20:53:33.424816+08	\N
f1f33a6e-ff17-42ce-ac7f-7c95e9ea2e2e	540f2fa1-53f8-4e43-9841-8eb881a0c529	55e43783-2e99-4ba6-9a48-53d7221878cb	cpu_global_pct	1.0	%	component	2026-11-08T20:52:59+08:00/2026-11-08T20:53:33+08:00	median	61	13.819096	\N	2026-11-08 20:53:33.424816+08	\N
92f4a128-d0e9-4fa3-800b-223d5fa1d405	540f2fa1-53f8-4e43-9841-8eb881a0c529	55e43783-2e99-4ba6-9a48-53d7221878cb	cpu_global_pct	1.0	%	component	2026-11-08T20:52:59+08:00/2026-11-08T20:53:33+08:00	mean	61	14.771568637704917	\N	2026-11-08 20:53:33.424816+08	\N
f29c24ff-b590-4982-9ca8-0dd01c98b938	540f2fa1-53f8-4e43-9841-8eb881a0c529	55e43783-2e99-4ba6-9a48-53d7221878cb	cpu_global_pct	1.0	%	component	2026-11-08T20:52:59+08:00/2026-11-08T20:53:33+08:00	max	61	34.031414	\N	2026-11-08 20:53:33.424816+08	\N
48f3a048-8bf2-4173-a60e-d412e7c95320	540f2fa1-53f8-4e43-9841-8eb881a0c529	55e43783-2e99-4ba6-9a48-53d7221878cb	cpu_global_pct	1.0	%	component	2026-11-08T20:52:59+08:00/2026-11-08T20:53:33+08:00	p90	61	22.00489	\N	2026-11-08 20:53:33.424816+08	\N
bfdb67f3-4fb9-44f3-b2e7-de2729b57aa9	540f2fa1-53f8-4e43-9841-8eb881a0c529	55e43783-2e99-4ba6-9a48-53d7221878cb	mem_pss_mb	1.0	MB	component	2026-11-08T20:52:59+08:00/2026-11-08T20:53:33+08:00	min	30	39.277344	\N	2026-11-08 20:53:33.424816+08	\N
f225d752-83bf-4fb7-bf43-5b2061d5c196	540f2fa1-53f8-4e43-9841-8eb881a0c529	55e43783-2e99-4ba6-9a48-53d7221878cb	mem_pss_mb	1.0	MB	component	2026-11-08T20:52:59+08:00/2026-11-08T20:53:33+08:00	median	30	45.4677735	\N	2026-11-08 20:53:33.424816+08	\N
e52d20fd-de9b-4c4d-9694-806166c88a9f	540f2fa1-53f8-4e43-9841-8eb881a0c529	55e43783-2e99-4ba6-9a48-53d7221878cb	mem_pss_mb	1.0	MB	component	2026-11-08T20:52:59+08:00/2026-11-08T20:53:33+08:00	mean	30	45.0826173	\N	2026-11-08 20:53:33.424816+08	\N
cee66912-8eca-4959-965d-7bf83790f46b	540f2fa1-53f8-4e43-9841-8eb881a0c529	55e43783-2e99-4ba6-9a48-53d7221878cb	mem_pss_mb	1.0	MB	component	2026-11-08T20:52:59+08:00/2026-11-08T20:53:33+08:00	max	30	45.569336	\N	2026-11-08 20:53:33.424816+08	\N
f3cbdd8a-446f-456d-82f2-3159011afd7e	540f2fa1-53f8-4e43-9841-8eb881a0c529	55e43783-2e99-4ba6-9a48-53d7221878cb	mem_pss_mb	1.0	MB	component	2026-11-08T20:52:59+08:00/2026-11-08T20:53:33+08:00	p90	30	45.54668100000001	\N	2026-11-08 20:53:33.424816+08	\N
5ba4b412-3458-4579-8270-0c1259117076	540f2fa1-53f8-4e43-9841-8eb881a0c529	55e43783-2e99-4ba6-9a48-53d7221878cb	mem_privdirty_mb	1.0	MB	component	2026-11-08T20:52:59+08:00/2026-11-08T20:53:33+08:00	min	30	6.2070312	\N	2026-11-08 20:53:33.424816+08	\N
feba6866-19a2-4032-9bf2-bdd2de249c7a	540f2fa1-53f8-4e43-9841-8eb881a0c529	55e43783-2e99-4ba6-9a48-53d7221878cb	mem_privdirty_mb	1.0	MB	component	2026-11-08T20:52:59+08:00/2026-11-08T20:53:33+08:00	median	30	9.01171875	\N	2026-11-08 20:53:33.424816+08	\N
78dd54b5-f162-4ef7-b999-1885a0ab065c	540f2fa1-53f8-4e43-9841-8eb881a0c529	55e43783-2e99-4ba6-9a48-53d7221878cb	mem_privdirty_mb	1.0	MB	component	2026-11-08T20:52:59+08:00/2026-11-08T20:53:33+08:00	mean	30	11.577473973333333	\N	2026-11-08 20:53:33.424816+08	\N
3d46b675-b7d9-4547-9fed-a596a92faf87	540f2fa1-53f8-4e43-9841-8eb881a0c529	55e43783-2e99-4ba6-9a48-53d7221878cb	mem_privdirty_mb	1.0	MB	component	2026-11-08T20:52:59+08:00/2026-11-08T20:53:33+08:00	max	30	21.988281	\N	2026-11-08 20:53:33.424816+08	\N
fe82d6ad-5363-40a4-bf09-257a8b2e75dd	540f2fa1-53f8-4e43-9841-8eb881a0c529	55e43783-2e99-4ba6-9a48-53d7221878cb	mem_privdirty_mb	1.0	MB	component	2026-11-08T20:52:59+08:00/2026-11-08T20:53:33+08:00	p90	30	20.6496098	\N	2026-11-08 20:53:33.424816+08	\N
85da0e0c-e3f9-4759-9462-620d05cad43d	540f2fa1-53f8-4e43-9841-8eb881a0c529	55e43783-2e99-4ba6-9a48-53d7221878cb	mem_global_mb	1.0	MB	component	2026-11-08T20:52:59+08:00/2026-11-08T20:53:33+08:00	min	32	4147	\N	2026-11-08 20:53:33.424816+08	\N
dfa841bb-8082-4073-89dc-9951a663b1cb	540f2fa1-53f8-4e43-9841-8eb881a0c529	55e43783-2e99-4ba6-9a48-53d7221878cb	mem_global_mb	1.0	MB	component	2026-11-08T20:52:59+08:00/2026-11-08T20:53:33+08:00	median	32	4165	\N	2026-11-08 20:53:33.424816+08	\N
d7484598-95ae-49b9-b2ef-b0b233b04721	540f2fa1-53f8-4e43-9841-8eb881a0c529	55e43783-2e99-4ba6-9a48-53d7221878cb	mem_global_mb	1.0	MB	component	2026-11-08T20:52:59+08:00/2026-11-08T20:53:33+08:00	mean	32	4162.75	\N	2026-11-08 20:53:33.424816+08	\N
d32abbcb-579e-4017-a310-a77e9195555b	540f2fa1-53f8-4e43-9841-8eb881a0c529	55e43783-2e99-4ba6-9a48-53d7221878cb	mem_global_mb	1.0	MB	component	2026-11-08T20:52:59+08:00/2026-11-08T20:53:33+08:00	max	32	4178	\N	2026-11-08 20:53:33.424816+08	\N
c42ef15c-58e1-467a-8c50-5104afc12f82	540f2fa1-53f8-4e43-9841-8eb881a0c529	55e43783-2e99-4ba6-9a48-53d7221878cb	mem_global_mb	1.0	MB	component	2026-11-08T20:52:59+08:00/2026-11-08T20:53:33+08:00	p90	32	4174.5	\N	2026-11-08 20:53:33.424816+08	\N
95498048-fabc-4faf-8c1c-2585bd4e8365	540f2fa1-53f8-4e43-9841-8eb881a0c529	55e43783-2e99-4ba6-9a48-53d7221878cb	fps_frame	1.0	fps	component	2026-11-08T20:52:59+08:00/2026-11-08T20:53:33+08:00	min	32	118	\N	2026-11-08 20:53:33.424816+08	\N
9222cf21-d3b5-49d0-b90e-c0df777e1d21	540f2fa1-53f8-4e43-9841-8eb881a0c529	55e43783-2e99-4ba6-9a48-53d7221878cb	fps_frame	1.0	fps	component	2026-11-08T20:52:59+08:00/2026-11-08T20:53:33+08:00	median	32	118	\N	2026-11-08 20:53:33.424816+08	\N
945c8b33-8fa6-46db-9226-fd85f3e6a0a3	540f2fa1-53f8-4e43-9841-8eb881a0c529	55e43783-2e99-4ba6-9a48-53d7221878cb	fps_frame	1.0	fps	component	2026-11-08T20:52:59+08:00/2026-11-08T20:53:33+08:00	mean	32	118	\N	2026-11-08 20:53:33.424816+08	\N
0338b5f3-f13f-44e4-89aa-38ba2c0d3d07	540f2fa1-53f8-4e43-9841-8eb881a0c529	55e43783-2e99-4ba6-9a48-53d7221878cb	fps_frame	1.0	fps	component	2026-11-08T20:52:59+08:00/2026-11-08T20:53:33+08:00	max	32	118	\N	2026-11-08 20:53:33.424816+08	\N
e6ed0d0e-73c8-497e-afb0-cade44a1abf4	540f2fa1-53f8-4e43-9841-8eb881a0c529	55e43783-2e99-4ba6-9a48-53d7221878cb	fps_frame	1.0	fps	component	2026-11-08T20:52:59+08:00/2026-11-08T20:53:33+08:00	p90	32	118	\N	2026-11-08 20:53:33.424816+08	\N
7f57d2af-c689-4d20-a258-d8ee4e7f55f3	540f2fa1-53f8-4e43-9841-8eb881a0c529	55e43783-2e99-4ba6-9a48-53d7221878cb	frame_delay_ratio_pct	1.0	%	component	2026-11-08T20:52:59+08:00/2026-11-08T20:53:33+08:00	min	32	66.66667	\N	2026-11-08 20:53:33.424816+08	\N
f839a20b-7cb7-4d43-97cb-75073fb2e1d1	540f2fa1-53f8-4e43-9841-8eb881a0c529	55e43783-2e99-4ba6-9a48-53d7221878cb	frame_delay_ratio_pct	1.0	%	component	2026-11-08T20:52:59+08:00/2026-11-08T20:53:33+08:00	median	32	66.66667	\N	2026-11-08 20:53:33.424816+08	\N
615c43ea-66e9-49e0-b2c4-aae50aa01d31	540f2fa1-53f8-4e43-9841-8eb881a0c529	55e43783-2e99-4ba6-9a48-53d7221878cb	frame_delay_ratio_pct	1.0	%	component	2026-11-08T20:52:59+08:00/2026-11-08T20:53:33+08:00	mean	32	66.66667	\N	2026-11-08 20:53:33.424816+08	\N
37af033a-73a5-4dd3-95c1-2358d30a1503	540f2fa1-53f8-4e43-9841-8eb881a0c529	55e43783-2e99-4ba6-9a48-53d7221878cb	frame_delay_ratio_pct	1.0	%	component	2026-11-08T20:52:59+08:00/2026-11-08T20:53:33+08:00	max	32	66.66667	\N	2026-11-08 20:53:33.424816+08	\N
d9058f6d-ae30-4e6a-884a-37895b55365d	540f2fa1-53f8-4e43-9841-8eb881a0c529	55e43783-2e99-4ba6-9a48-53d7221878cb	frame_delay_ratio_pct	1.0	%	component	2026-11-08T20:52:59+08:00/2026-11-08T20:53:33+08:00	p90	32	66.66667	\N	2026-11-08 20:53:33.424816+08	\N
590744c8-a76f-4663-906e-a8e7416a94d2	540f2fa1-53f8-4e43-9841-8eb881a0c529	55e43783-2e99-4ba6-9a48-53d7221878cb	frame_delay_count	1.0	次	component	2026-11-08T20:52:59+08:00/2026-11-08T20:53:33+08:00	min	32	2	\N	2026-11-08 20:53:33.424816+08	\N
52d06389-df7b-469e-a359-f74c165d3809	540f2fa1-53f8-4e43-9841-8eb881a0c529	55e43783-2e99-4ba6-9a48-53d7221878cb	frame_delay_count	1.0	次	component	2026-11-08T20:52:59+08:00/2026-11-08T20:53:33+08:00	median	32	2	\N	2026-11-08 20:53:33.424816+08	\N
dbe11779-5067-47b8-9f84-73c4c4fc85a4	540f2fa1-53f8-4e43-9841-8eb881a0c529	55e43783-2e99-4ba6-9a48-53d7221878cb	frame_delay_count	1.0	次	component	2026-11-08T20:52:59+08:00/2026-11-08T20:53:33+08:00	mean	32	2	\N	2026-11-08 20:53:33.424816+08	\N
9cd773d9-8027-4c49-a004-ee9d123996b2	540f2fa1-53f8-4e43-9841-8eb881a0c529	55e43783-2e99-4ba6-9a48-53d7221878cb	frame_delay_count	1.0	次	component	2026-11-08T20:52:59+08:00/2026-11-08T20:53:33+08:00	max	32	2	\N	2026-11-08 20:53:33.424816+08	\N
ab50f3d6-70e9-42a4-b1a3-3383b4ebbe73	540f2fa1-53f8-4e43-9841-8eb881a0c529	55e43783-2e99-4ba6-9a48-53d7221878cb	frame_delay_count	1.0	次	component	2026-11-08T20:52:59+08:00/2026-11-08T20:53:33+08:00	p90	32	2	\N	2026-11-08 20:53:33.424816+08	\N
5d010ea6-d62b-45ef-bf92-d1056a429f96	540f2fa1-53f8-4e43-9841-8eb881a0c529	55e43783-2e99-4ba6-9a48-53d7221878cb	frame_delay_max_ms	1.0	ms	component	2026-11-08T20:52:59+08:00/2026-11-08T20:53:33+08:00	min	32	14	\N	2026-11-08 20:53:33.424816+08	\N
a1f3a603-7a7e-4c2c-baae-239b524da988	540f2fa1-53f8-4e43-9841-8eb881a0c529	55e43783-2e99-4ba6-9a48-53d7221878cb	frame_delay_max_ms	1.0	ms	component	2026-11-08T20:52:59+08:00/2026-11-08T20:53:33+08:00	median	32	14	\N	2026-11-08 20:53:33.424816+08	\N
f1578f72-da74-4446-8e38-802ca81a7442	540f2fa1-53f8-4e43-9841-8eb881a0c529	55e43783-2e99-4ba6-9a48-53d7221878cb	frame_delay_max_ms	1.0	ms	component	2026-11-08T20:52:59+08:00/2026-11-08T20:53:33+08:00	mean	32	14	\N	2026-11-08 20:53:33.424816+08	\N
b52864ae-9a02-4b77-a57d-ea907a7d4aa9	540f2fa1-53f8-4e43-9841-8eb881a0c529	55e43783-2e99-4ba6-9a48-53d7221878cb	frame_delay_max_ms	1.0	ms	component	2026-11-08T20:52:59+08:00/2026-11-08T20:53:33+08:00	max	32	14	\N	2026-11-08 20:53:33.424816+08	\N
74a5fb66-2220-453e-ae15-9dcf16ed9366	540f2fa1-53f8-4e43-9841-8eb881a0c529	55e43783-2e99-4ba6-9a48-53d7221878cb	frame_delay_max_ms	1.0	ms	component	2026-11-08T20:52:59+08:00/2026-11-08T20:53:33+08:00	p90	32	14	\N	2026-11-08 20:53:33.424816+08	\N
c110c5d4-d2f9-4d56-9359-b236da55e81b	540f2fa1-53f8-4e43-9841-8eb881a0c529	55e43783-2e99-4ba6-9a48-53d7221878cb	app_jank_light_count	1.0	次	component	2026-11-08T20:52:59+08:00/2026-11-08T20:53:33+08:00	min	1	0	\N	2026-11-08 20:53:33.424816+08	\N
076aa7a1-9485-421d-b27f-558bc624b4c4	540f2fa1-53f8-4e43-9841-8eb881a0c529	55e43783-2e99-4ba6-9a48-53d7221878cb	app_jank_light_count	1.0	次	component	2026-11-08T20:52:59+08:00/2026-11-08T20:53:33+08:00	median	1	0	\N	2026-11-08 20:53:33.424816+08	\N
8137bb7e-b214-44c6-b48c-366189e0297e	540f2fa1-53f8-4e43-9841-8eb881a0c529	55e43783-2e99-4ba6-9a48-53d7221878cb	app_jank_light_count	1.0	次	component	2026-11-08T20:52:59+08:00/2026-11-08T20:53:33+08:00	mean	1	0	\N	2026-11-08 20:53:33.424816+08	\N
7cee5aec-2b6c-4e0b-96da-a2fa0be1c56c	540f2fa1-53f8-4e43-9841-8eb881a0c529	55e43783-2e99-4ba6-9a48-53d7221878cb	app_jank_light_count	1.0	次	component	2026-11-08T20:52:59+08:00/2026-11-08T20:53:33+08:00	max	1	0	\N	2026-11-08 20:53:33.424816+08	\N
0a007fb4-d014-4357-ba77-11488b415cdd	540f2fa1-53f8-4e43-9841-8eb881a0c529	55e43783-2e99-4ba6-9a48-53d7221878cb	app_jank_light_count	1.0	次	component	2026-11-08T20:52:59+08:00/2026-11-08T20:53:33+08:00	p90	1	0	\N	2026-11-08 20:53:33.424816+08	\N
3dd66bb0-9003-4ee5-b3b2-c4daff0d90a9	540f2fa1-53f8-4e43-9841-8eb881a0c529	55e43783-2e99-4ba6-9a48-53d7221878cb	app_jank_heavy_count	1.0	次	component	2026-11-08T20:52:59+08:00/2026-11-08T20:53:33+08:00	min	1	0	\N	2026-11-08 20:53:33.424816+08	\N
cd6b3e17-de96-47b2-aaa9-220dea762661	540f2fa1-53f8-4e43-9841-8eb881a0c529	55e43783-2e99-4ba6-9a48-53d7221878cb	app_jank_heavy_count	1.0	次	component	2026-11-08T20:52:59+08:00/2026-11-08T20:53:33+08:00	median	1	0	\N	2026-11-08 20:53:33.424816+08	\N
2fc59ca9-6b7d-4a2d-b5af-987b02c9f975	540f2fa1-53f8-4e43-9841-8eb881a0c529	55e43783-2e99-4ba6-9a48-53d7221878cb	app_jank_heavy_count	1.0	次	component	2026-11-08T20:52:59+08:00/2026-11-08T20:53:33+08:00	mean	1	0	\N	2026-11-08 20:53:33.424816+08	\N
e8e3ae69-84e5-48d7-8a27-8fbabb3b58ae	540f2fa1-53f8-4e43-9841-8eb881a0c529	55e43783-2e99-4ba6-9a48-53d7221878cb	app_jank_heavy_count	1.0	次	component	2026-11-08T20:52:59+08:00/2026-11-08T20:53:33+08:00	max	1	0	\N	2026-11-08 20:53:33.424816+08	\N
8400761f-8b5f-436c-a55a-d48c492ffcd8	540f2fa1-53f8-4e43-9841-8eb881a0c529	55e43783-2e99-4ba6-9a48-53d7221878cb	app_jank_heavy_count	1.0	次	component	2026-11-08T20:52:59+08:00/2026-11-08T20:53:33+08:00	p90	1	0	\N	2026-11-08 20:53:33.424816+08	\N
1bce74ac-2675-4371-ba50-05026e9e7919	540f2fa1-53f8-4e43-9841-8eb881a0c529	55e43783-2e99-4ba6-9a48-53d7221878cb	app_jank_severe_count	1.0	次	component	2026-11-08T20:52:59+08:00/2026-11-08T20:53:33+08:00	min	1	0	\N	2026-11-08 20:53:33.424816+08	\N
f55ac186-02d5-4b5f-a2a2-b115d790437b	540f2fa1-53f8-4e43-9841-8eb881a0c529	55e43783-2e99-4ba6-9a48-53d7221878cb	app_jank_severe_count	1.0	次	component	2026-11-08T20:52:59+08:00/2026-11-08T20:53:33+08:00	median	1	0	\N	2026-11-08 20:53:33.424816+08	\N
ee571a8a-031d-4e5f-b9be-7784bfc75357	540f2fa1-53f8-4e43-9841-8eb881a0c529	55e43783-2e99-4ba6-9a48-53d7221878cb	app_jank_severe_count	1.0	次	component	2026-11-08T20:52:59+08:00/2026-11-08T20:53:33+08:00	mean	1	0	\N	2026-11-08 20:53:33.424816+08	\N
9753ec5b-1029-47ca-84d0-6067eb9139e6	540f2fa1-53f8-4e43-9841-8eb881a0c529	55e43783-2e99-4ba6-9a48-53d7221878cb	app_jank_severe_count	1.0	次	component	2026-11-08T20:52:59+08:00/2026-11-08T20:53:33+08:00	max	1	0	\N	2026-11-08 20:53:33.424816+08	\N
a3c01811-4e8f-4bf2-a0dd-dcb8b1c768b1	540f2fa1-53f8-4e43-9841-8eb881a0c529	55e43783-2e99-4ba6-9a48-53d7221878cb	app_jank_severe_count	1.0	次	component	2026-11-08T20:52:59+08:00/2026-11-08T20:53:33+08:00	p90	1	0	\N	2026-11-08 20:53:33.424816+08	\N
7f4e6e06-6345-4192-86a3-e67fc000d103	540f2fa1-53f8-4e43-9841-8eb881a0c529	55e43783-2e99-4ba6-9a48-53d7221878cb	temp_battery_c	1.0	°C	component	2026-11-08T20:52:59+08:00/2026-11-08T20:53:33+08:00	min	15	32.8	\N	2026-11-08 20:53:33.424816+08	\N
1b063990-292f-4c6c-a918-00797bf474a6	540f2fa1-53f8-4e43-9841-8eb881a0c529	55e43783-2e99-4ba6-9a48-53d7221878cb	temp_battery_c	1.0	°C	component	2026-11-08T20:52:59+08:00/2026-11-08T20:53:33+08:00	median	15	32.8	\N	2026-11-08 20:53:33.424816+08	\N
a57980f5-5ecb-431c-af18-ae72b0914764	540f2fa1-53f8-4e43-9841-8eb881a0c529	55e43783-2e99-4ba6-9a48-53d7221878cb	temp_battery_c	1.0	°C	component	2026-11-08T20:52:59+08:00/2026-11-08T20:53:33+08:00	mean	15	32.8	\N	2026-11-08 20:53:33.424816+08	\N
221146c1-a56f-4ca9-acea-ae7f2ed5a20c	540f2fa1-53f8-4e43-9841-8eb881a0c529	55e43783-2e99-4ba6-9a48-53d7221878cb	temp_battery_c	1.0	°C	component	2026-11-08T20:52:59+08:00/2026-11-08T20:53:33+08:00	max	15	32.8	\N	2026-11-08 20:53:33.424816+08	\N
534c0295-01dc-4988-96fd-cc751f806c29	540f2fa1-53f8-4e43-9841-8eb881a0c529	55e43783-2e99-4ba6-9a48-53d7221878cb	temp_battery_c	1.0	°C	component	2026-11-08T20:52:59+08:00/2026-11-08T20:53:33+08:00	p90	15	32.8	\N	2026-11-08 20:53:33.424816+08	\N
62505f71-8dec-49f7-9525-94e904a9ee64	540f2fa1-53f8-4e43-9841-8eb881a0c529	55e43783-2e99-4ba6-9a48-53d7221878cb	gpu_util_pct	1.0	%	component	2026-11-08T20:52:59+08:00/2026-11-08T20:53:33+08:00	min	15	0	\N	2026-11-08 20:53:33.424816+08	\N
942a226d-14be-47c0-aaee-31796ded007d	540f2fa1-53f8-4e43-9841-8eb881a0c529	55e43783-2e99-4ba6-9a48-53d7221878cb	gpu_util_pct	1.0	%	component	2026-11-08T20:52:59+08:00/2026-11-08T20:53:33+08:00	median	15	0	\N	2026-11-08 20:53:33.424816+08	\N
2c7fa607-2c2a-416a-9516-628d6edbd00d	540f2fa1-53f8-4e43-9841-8eb881a0c529	55e43783-2e99-4ba6-9a48-53d7221878cb	gpu_util_pct	1.0	%	component	2026-11-08T20:52:59+08:00/2026-11-08T20:53:33+08:00	mean	15	0.67004506676902	\N	2026-11-08 20:53:33.424816+08	\N
a5f7de9a-ac2e-45c3-a43c-6371f72964c7	540f2fa1-53f8-4e43-9841-8eb881a0c529	55e43783-2e99-4ba6-9a48-53d7221878cb	gpu_util_pct	1.0	%	component	2026-11-08T20:52:59+08:00/2026-11-08T20:53:33+08:00	max	15	6.178479999053303	\N	2026-11-08 20:53:33.424816+08	\N
b5b327b9-0543-4165-a39a-2878766c6f90	540f2fa1-53f8-4e43-9841-8eb881a0c529	55e43783-2e99-4ba6-9a48-53d7221878cb	gpu_util_pct	1.0	%	component	2026-11-08T20:52:59+08:00/2026-11-08T20:53:33+08:00	p90	15	2.3233176014891965	\N	2026-11-08 20:53:33.424816+08	\N
6de78e2a-8443-4816-9fa7-628a309cb090	540f2fa1-53f8-4e43-9841-8eb881a0c529	55e43783-2e99-4ba6-9a48-53d7221878cb	gpu_mem_mb	1.0	MB	component	2026-11-08T20:52:59+08:00/2026-11-08T20:53:33+08:00	min	15	4.75	\N	2026-11-08 20:53:33.424816+08	\N
3e1801f0-b614-4a41-91f4-18854676c1a7	540f2fa1-53f8-4e43-9841-8eb881a0c529	55e43783-2e99-4ba6-9a48-53d7221878cb	gpu_mem_mb	1.0	MB	component	2026-11-08T20:52:59+08:00/2026-11-08T20:53:33+08:00	median	15	4.75	\N	2026-11-08 20:53:33.424816+08	\N
e104d486-d9b4-4f83-a713-b5963f8046ad	540f2fa1-53f8-4e43-9841-8eb881a0c529	55e43783-2e99-4ba6-9a48-53d7221878cb	gpu_mem_mb	1.0	MB	component	2026-11-08T20:52:59+08:00/2026-11-08T20:53:33+08:00	mean	15	4.75	\N	2026-11-08 20:53:33.424816+08	\N
158a9680-cc99-4829-b1ae-4ff4ca02be07	540f2fa1-53f8-4e43-9841-8eb881a0c529	55e43783-2e99-4ba6-9a48-53d7221878cb	gpu_mem_mb	1.0	MB	component	2026-11-08T20:52:59+08:00/2026-11-08T20:53:33+08:00	max	15	4.75	\N	2026-11-08 20:53:33.424816+08	\N
3c85a59a-59e8-48d0-983b-f7044a785f05	540f2fa1-53f8-4e43-9841-8eb881a0c529	55e43783-2e99-4ba6-9a48-53d7221878cb	gpu_mem_mb	1.0	MB	component	2026-11-08T20:52:59+08:00/2026-11-08T20:53:33+08:00	p90	15	4.75	\N	2026-11-08 20:53:33.424816+08	\N
31b93f93-b7a9-4eb4-b470-65cb0aa04cdb	540f2fa1-53f8-4e43-9841-8eb881a0c529	1fd40ad8-d824-4a30-a169-3d636eadfb42	cpu_process_pct	1.0	%	component	2026-11-08T21:12:22+08:00/2026-11-08T21:12:45+08:00	min	42	0	\N	2026-11-08 21:12:46.205621+08	\N
a18c6439-d341-404c-b60e-947758560fdc	540f2fa1-53f8-4e43-9841-8eb881a0c529	1fd40ad8-d824-4a30-a169-3d636eadfb42	cpu_process_pct	1.0	%	component	2026-11-08T21:12:22+08:00/2026-11-08T21:12:45+08:00	median	42	0.25942475	\N	2026-11-08 21:12:46.205621+08	\N
487782c6-73e0-483b-aad6-a0d26810d452	540f2fa1-53f8-4e43-9841-8eb881a0c529	1fd40ad8-d824-4a30-a169-3d636eadfb42	cpu_process_pct	1.0	%	component	2026-11-08T21:12:22+08:00/2026-11-08T21:12:45+08:00	mean	42	0.5326057050166666	\N	2026-11-08 21:12:46.205621+08	\N
2ac55078-5c97-4ddc-9aa2-5712ee7e77a6	540f2fa1-53f8-4e43-9841-8eb881a0c529	1fd40ad8-d824-4a30-a169-3d636eadfb42	cpu_process_pct	1.0	%	component	2026-11-08T21:12:22+08:00/2026-11-08T21:12:45+08:00	max	42	2.9339855	\N	2026-11-08 21:12:46.205621+08	\N
e6d0c5dc-9213-428f-8862-505d84b2cc06	540f2fa1-53f8-4e43-9841-8eb881a0c529	1fd40ad8-d824-4a30-a169-3d636eadfb42	cpu_process_pct	1.0	%	component	2026-11-08T21:12:22+08:00/2026-11-08T21:12:45+08:00	p90	42	1.02511781	\N	2026-11-08 21:12:46.205621+08	\N
42a58787-0ba1-49a1-8a12-7099783e13d8	540f2fa1-53f8-4e43-9841-8eb881a0c529	1fd40ad8-d824-4a30-a169-3d636eadfb42	cpu_global_pct	1.0	%	component	2026-11-08T21:12:22+08:00/2026-11-08T21:12:45+08:00	min	42	5.3522053	\N	2026-11-08 21:12:46.205621+08	\N
8ee1ad3b-03fe-4615-bfa7-c748d66ed24c	540f2fa1-53f8-4e43-9841-8eb881a0c529	1fd40ad8-d824-4a30-a169-3d636eadfb42	cpu_global_pct	1.0	%	component	2026-11-08T21:12:22+08:00/2026-11-08T21:12:45+08:00	median	42	17.593733	\N	2026-11-08 21:12:46.205621+08	\N
c5baa002-b110-4939-bbf3-6af9180e8df5	540f2fa1-53f8-4e43-9841-8eb881a0c529	1fd40ad8-d824-4a30-a169-3d636eadfb42	cpu_global_pct	1.0	%	component	2026-11-08T21:12:22+08:00/2026-11-08T21:12:45+08:00	mean	42	20.050188792857142	\N	2026-11-08 21:12:46.205621+08	\N
fe1c56ee-b953-476d-b55e-07360a205a6f	540f2fa1-53f8-4e43-9841-8eb881a0c529	1fd40ad8-d824-4a30-a169-3d636eadfb42	cpu_global_pct	1.0	%	component	2026-11-08T21:12:22+08:00/2026-11-08T21:12:45+08:00	max	42	46.68305	\N	2026-11-08 21:12:46.205621+08	\N
06b15c33-1780-4205-80d7-0cf444565ebc	540f2fa1-53f8-4e43-9841-8eb881a0c529	1fd40ad8-d824-4a30-a169-3d636eadfb42	cpu_global_pct	1.0	%	component	2026-11-08T21:12:22+08:00/2026-11-08T21:12:45+08:00	p90	42	29.587587299999996	\N	2026-11-08 21:12:46.205621+08	\N
dad53099-66d4-416d-b76e-3b8de9a572f6	540f2fa1-53f8-4e43-9841-8eb881a0c529	1fd40ad8-d824-4a30-a169-3d636eadfb42	mem_pss_mb	1.0	MB	component	2026-11-08T21:12:22+08:00/2026-11-08T21:12:45+08:00	min	17	43.195312	\N	2026-11-08 21:12:46.205621+08	\N
879f598b-89b3-416d-88a4-59ddba5f8aeb	540f2fa1-53f8-4e43-9841-8eb881a0c529	1fd40ad8-d824-4a30-a169-3d636eadfb42	mem_pss_mb	1.0	MB	component	2026-11-08T21:12:22+08:00/2026-11-08T21:12:45+08:00	median	17	83.70117	\N	2026-11-08 21:12:46.205621+08	\N
eb7d2894-3481-4d1e-9582-6d8d49351969	540f2fa1-53f8-4e43-9841-8eb881a0c529	1fd40ad8-d824-4a30-a169-3d636eadfb42	mem_pss_mb	1.0	MB	component	2026-11-08T21:12:22+08:00/2026-11-08T21:12:45+08:00	mean	17	78.66141994117646	\N	2026-11-08 21:12:46.205621+08	\N
c4785dc6-cdd0-4ab5-afdf-079ce4e92329	540f2fa1-53f8-4e43-9841-8eb881a0c529	1fd40ad8-d824-4a30-a169-3d636eadfb42	mem_pss_mb	1.0	MB	component	2026-11-08T21:12:22+08:00/2026-11-08T21:12:45+08:00	max	17	84.05859	\N	2026-11-08 21:12:46.205621+08	\N
87d97738-bba0-4bc1-ba12-505246ad694e	540f2fa1-53f8-4e43-9841-8eb881a0c529	1fd40ad8-d824-4a30-a169-3d636eadfb42	mem_pss_mb	1.0	MB	component	2026-11-08T21:12:22+08:00/2026-11-08T21:12:45+08:00	p90	17	84.047658	\N	2026-11-08 21:12:46.205621+08	\N
8aa81aa3-bf46-439b-a613-27083bd6fb63	540f2fa1-53f8-4e43-9841-8eb881a0c529	1fd40ad8-d824-4a30-a169-3d636eadfb42	mem_privdirty_mb	1.0	MB	component	2026-11-08T21:12:22+08:00/2026-11-08T21:12:45+08:00	min	17	9.109375	\N	2026-11-08 21:12:46.205621+08	\N
0a3ae908-9885-4faf-921c-cb15daf51d37	540f2fa1-53f8-4e43-9841-8eb881a0c529	1fd40ad8-d824-4a30-a169-3d636eadfb42	mem_privdirty_mb	1.0	MB	component	2026-11-08T21:12:22+08:00/2026-11-08T21:12:45+08:00	median	17	61.14453	\N	2026-11-08 21:12:46.205621+08	\N
42208ded-c5d3-4c7a-b7cd-deb441070231	540f2fa1-53f8-4e43-9841-8eb881a0c529	1fd40ad8-d824-4a30-a169-3d636eadfb42	mem_privdirty_mb	1.0	MB	component	2026-11-08T21:12:22+08:00/2026-11-08T21:12:45+08:00	mean	17	55.07536773529412	\N	2026-11-08 21:12:46.205621+08	\N
b040a0e6-b939-4056-8d04-bff6059359b0	540f2fa1-53f8-4e43-9841-8eb881a0c529	1fd40ad8-d824-4a30-a169-3d636eadfb42	mem_privdirty_mb	1.0	MB	component	2026-11-08T21:12:22+08:00/2026-11-08T21:12:45+08:00	max	17	62.73047	\N	2026-11-08 21:12:46.205621+08	\N
842d2172-cfb9-4007-bc94-e0743544bd08	540f2fa1-53f8-4e43-9841-8eb881a0c529	1fd40ad8-d824-4a30-a169-3d636eadfb42	mem_privdirty_mb	1.0	MB	component	2026-11-08T21:12:22+08:00/2026-11-08T21:12:45+08:00	p90	17	61.4976564	\N	2026-11-08 21:12:46.205621+08	\N
dcd160a4-8309-4cc1-8133-05fb9ddf167c	540f2fa1-53f8-4e43-9841-8eb881a0c529	1fd40ad8-d824-4a30-a169-3d636eadfb42	mem_global_mb	1.0	MB	component	2026-11-08T21:12:22+08:00/2026-11-08T21:12:45+08:00	min	21	4201	\N	2026-11-08 21:12:46.205621+08	\N
54455bcd-1e59-4c67-99f4-36c9d308f73a	540f2fa1-53f8-4e43-9841-8eb881a0c529	1fd40ad8-d824-4a30-a169-3d636eadfb42	mem_global_mb	1.0	MB	component	2026-11-08T21:12:22+08:00/2026-11-08T21:12:45+08:00	median	21	4328	\N	2026-11-08 21:12:46.205621+08	\N
8fcfccd6-acdd-4968-b606-3fe7f311e875	540f2fa1-53f8-4e43-9841-8eb881a0c529	1fd40ad8-d824-4a30-a169-3d636eadfb42	mem_global_mb	1.0	MB	component	2026-11-08T21:12:22+08:00/2026-11-08T21:12:45+08:00	mean	21	4306.523809523809	\N	2026-11-08 21:12:46.205621+08	\N
2d66f287-a15c-4a85-ac7f-a22e9b8d18cc	540f2fa1-53f8-4e43-9841-8eb881a0c529	1fd40ad8-d824-4a30-a169-3d636eadfb42	mem_global_mb	1.0	MB	component	2026-11-08T21:12:22+08:00/2026-11-08T21:12:45+08:00	max	21	4339	\N	2026-11-08 21:12:46.205621+08	\N
2bde2800-0b9c-4886-8ac8-7a727fe16b8e	540f2fa1-53f8-4e43-9841-8eb881a0c529	1fd40ad8-d824-4a30-a169-3d636eadfb42	mem_global_mb	1.0	MB	component	2026-11-08T21:12:22+08:00/2026-11-08T21:12:45+08:00	p90	21	4337	\N	2026-11-08 21:12:46.205621+08	\N
f394bf45-ba8f-4a6b-99a4-45686e31b23b	540f2fa1-53f8-4e43-9841-8eb881a0c529	1fd40ad8-d824-4a30-a169-3d636eadfb42	fps_frame	1.0	fps	component	2026-11-08T21:12:22+08:00/2026-11-08T21:12:45+08:00	min	21	115	\N	2026-11-08 21:12:46.205621+08	\N
e1c42723-0c79-43da-a2ec-1d7e562dcbab	540f2fa1-53f8-4e43-9841-8eb881a0c529	1fd40ad8-d824-4a30-a169-3d636eadfb42	fps_frame	1.0	fps	component	2026-11-08T21:12:22+08:00/2026-11-08T21:12:45+08:00	median	21	120	\N	2026-11-08 21:12:46.205621+08	\N
ddcd9596-0f2b-422d-a077-c3c1796499fc	540f2fa1-53f8-4e43-9841-8eb881a0c529	1fd40ad8-d824-4a30-a169-3d636eadfb42	fps_frame	1.0	fps	component	2026-11-08T21:12:22+08:00/2026-11-08T21:12:45+08:00	mean	21	119.28571428571429	\N	2026-11-08 21:12:46.205621+08	\N
07cbd2e4-f897-4420-baa2-966e50a091e5	540f2fa1-53f8-4e43-9841-8eb881a0c529	1fd40ad8-d824-4a30-a169-3d636eadfb42	fps_frame	1.0	fps	component	2026-11-08T21:12:22+08:00/2026-11-08T21:12:45+08:00	max	21	120	\N	2026-11-08 21:12:46.205621+08	\N
2dd1fb57-ee90-4ec1-b7fa-8602b551132a	540f2fa1-53f8-4e43-9841-8eb881a0c529	1fd40ad8-d824-4a30-a169-3d636eadfb42	fps_frame	1.0	fps	component	2026-11-08T21:12:22+08:00/2026-11-08T21:12:45+08:00	p90	21	120	\N	2026-11-08 21:12:46.205621+08	\N
c9c890ca-337f-468f-9ebe-a0a671f51017	540f2fa1-53f8-4e43-9841-8eb881a0c529	1fd40ad8-d824-4a30-a169-3d636eadfb42	frame_delay_ratio_pct	1.0	%	component	2026-11-08T21:12:22+08:00/2026-11-08T21:12:45+08:00	min	21	0	\N	2026-11-08 21:12:46.205621+08	\N
5e175df9-462d-41c2-a6c7-1e296aae6c4e	540f2fa1-53f8-4e43-9841-8eb881a0c529	1fd40ad8-d824-4a30-a169-3d636eadfb42	frame_delay_ratio_pct	1.0	%	component	2026-11-08T21:12:22+08:00/2026-11-08T21:12:45+08:00	median	21	0	\N	2026-11-08 21:12:46.205621+08	\N
abea7df6-6b38-4bc8-b735-6b4e218052bf	540f2fa1-53f8-4e43-9841-8eb881a0c529	1fd40ad8-d824-4a30-a169-3d636eadfb42	frame_delay_ratio_pct	1.0	%	component	2026-11-08T21:12:22+08:00/2026-11-08T21:12:45+08:00	mean	21	16.269841904761904	\N	2026-11-08 21:12:46.205621+08	\N
72d8dea5-912a-4e80-9d17-c6188074ac1e	540f2fa1-53f8-4e43-9841-8eb881a0c529	1fd40ad8-d824-4a30-a169-3d636eadfb42	frame_delay_ratio_pct	1.0	%	component	2026-11-08T21:12:22+08:00/2026-11-08T21:12:45+08:00	max	21	75	\N	2026-11-08 21:12:46.205621+08	\N
425cc7d0-2411-470b-9dab-b1fa5f6ea0ff	540f2fa1-53f8-4e43-9841-8eb881a0c529	1fd40ad8-d824-4a30-a169-3d636eadfb42	frame_delay_ratio_pct	1.0	%	component	2026-11-08T21:12:22+08:00/2026-11-08T21:12:45+08:00	p90	21	66.66667	\N	2026-11-08 21:12:46.205621+08	\N
27d5b0d7-9c83-46e4-a4ba-aa5b111b843b	540f2fa1-53f8-4e43-9841-8eb881a0c529	1fd40ad8-d824-4a30-a169-3d636eadfb42	frame_delay_count	1.0	次	component	2026-11-08T21:12:22+08:00/2026-11-08T21:12:45+08:00	min	21	0	\N	2026-11-08 21:12:46.205621+08	\N
bd5647c5-4c43-4ccf-9cc8-830e7e60a1ea	540f2fa1-53f8-4e43-9841-8eb881a0c529	1fd40ad8-d824-4a30-a169-3d636eadfb42	frame_delay_count	1.0	次	component	2026-11-08T21:12:22+08:00/2026-11-08T21:12:45+08:00	median	21	0	\N	2026-11-08 21:12:46.205621+08	\N
059f1f24-d1d9-4298-a65b-030176da9380	540f2fa1-53f8-4e43-9841-8eb881a0c529	1fd40ad8-d824-4a30-a169-3d636eadfb42	frame_delay_count	1.0	次	component	2026-11-08T21:12:22+08:00/2026-11-08T21:12:45+08:00	mean	21	0.5238095238095238	\N	2026-11-08 21:12:46.205621+08	\N
7849e5d1-8db3-4da1-a8fc-792b10aecb4b	540f2fa1-53f8-4e43-9841-8eb881a0c529	1fd40ad8-d824-4a30-a169-3d636eadfb42	frame_delay_count	1.0	次	component	2026-11-08T21:12:22+08:00/2026-11-08T21:12:45+08:00	max	21	3	\N	2026-11-08 21:12:46.205621+08	\N
85896239-ef5e-4218-9778-2a91a80ce2a7	540f2fa1-53f8-4e43-9841-8eb881a0c529	1fd40ad8-d824-4a30-a169-3d636eadfb42	frame_delay_count	1.0	次	component	2026-11-08T21:12:22+08:00/2026-11-08T21:12:45+08:00	p90	21	2	\N	2026-11-08 21:12:46.205621+08	\N
9cb4aa4d-b6ba-49b5-90b9-6e2479ffa69e	540f2fa1-53f8-4e43-9841-8eb881a0c529	1fd40ad8-d824-4a30-a169-3d636eadfb42	frame_delay_max_ms	1.0	ms	component	2026-11-08T21:12:22+08:00/2026-11-08T21:12:45+08:00	min	21	5	\N	2026-11-08 21:12:46.205621+08	\N
60ebea55-ec92-4614-ad24-a2871b679c04	540f2fa1-53f8-4e43-9841-8eb881a0c529	1fd40ad8-d824-4a30-a169-3d636eadfb42	frame_delay_max_ms	1.0	ms	component	2026-11-08T21:12:22+08:00/2026-11-08T21:12:45+08:00	median	21	6	\N	2026-11-08 21:12:46.205621+08	\N
c747e5bd-87af-4ec0-8466-2c1cfcc9ab32	540f2fa1-53f8-4e43-9841-8eb881a0c529	1fd40ad8-d824-4a30-a169-3d636eadfb42	frame_delay_max_ms	1.0	ms	component	2026-11-08T21:12:22+08:00/2026-11-08T21:12:45+08:00	mean	21	9.714285714285714	\N	2026-11-08 21:12:46.205621+08	\N
38b93ec8-8375-4d92-ae46-9bbc39463184	540f2fa1-53f8-4e43-9841-8eb881a0c529	1fd40ad8-d824-4a30-a169-3d636eadfb42	frame_delay_max_ms	1.0	ms	component	2026-11-08T21:12:22+08:00/2026-11-08T21:12:45+08:00	max	21	32	\N	2026-11-08 21:12:46.205621+08	\N
60bf2fea-3529-4113-a12e-70228dd4bedc	540f2fa1-53f8-4e43-9841-8eb881a0c529	1fd40ad8-d824-4a30-a169-3d636eadfb42	frame_delay_max_ms	1.0	ms	component	2026-11-08T21:12:22+08:00/2026-11-08T21:12:45+08:00	p90	21	14	\N	2026-11-08 21:12:46.205621+08	\N
ebf83193-12c8-4eff-bb97-70d0471608fa	540f2fa1-53f8-4e43-9841-8eb881a0c529	1fd40ad8-d824-4a30-a169-3d636eadfb42	app_jank_light_count	1.0	次	component	2026-11-08T21:12:22+08:00/2026-11-08T21:12:45+08:00	min	1	0	\N	2026-11-08 21:12:46.205621+08	\N
7a44e759-d75a-4aee-b051-1632213fab17	540f2fa1-53f8-4e43-9841-8eb881a0c529	1fd40ad8-d824-4a30-a169-3d636eadfb42	app_jank_light_count	1.0	次	component	2026-11-08T21:12:22+08:00/2026-11-08T21:12:45+08:00	median	1	0	\N	2026-11-08 21:12:46.205621+08	\N
af0e6519-2ec3-4562-bafc-c7006036809c	540f2fa1-53f8-4e43-9841-8eb881a0c529	1fd40ad8-d824-4a30-a169-3d636eadfb42	app_jank_light_count	1.0	次	component	2026-11-08T21:12:22+08:00/2026-11-08T21:12:45+08:00	mean	1	0	\N	2026-11-08 21:12:46.205621+08	\N
9d43226f-54c1-44aa-b19a-904bb2acd3a4	540f2fa1-53f8-4e43-9841-8eb881a0c529	1fd40ad8-d824-4a30-a169-3d636eadfb42	app_jank_light_count	1.0	次	component	2026-11-08T21:12:22+08:00/2026-11-08T21:12:45+08:00	max	1	0	\N	2026-11-08 21:12:46.205621+08	\N
e50abd2d-d821-4cdf-876b-165f7ec3cb3c	540f2fa1-53f8-4e43-9841-8eb881a0c529	1fd40ad8-d824-4a30-a169-3d636eadfb42	app_jank_light_count	1.0	次	component	2026-11-08T21:12:22+08:00/2026-11-08T21:12:45+08:00	p90	1	0	\N	2026-11-08 21:12:46.205621+08	\N
6291feb0-69ee-476c-a74b-31555d67e43e	540f2fa1-53f8-4e43-9841-8eb881a0c529	1fd40ad8-d824-4a30-a169-3d636eadfb42	app_jank_heavy_count	1.0	次	component	2026-11-08T21:12:22+08:00/2026-11-08T21:12:45+08:00	min	1	0	\N	2026-11-08 21:12:46.205621+08	\N
4ecec733-ae73-41b5-9fee-dc36e49e45dc	540f2fa1-53f8-4e43-9841-8eb881a0c529	1fd40ad8-d824-4a30-a169-3d636eadfb42	app_jank_heavy_count	1.0	次	component	2026-11-08T21:12:22+08:00/2026-11-08T21:12:45+08:00	median	1	0	\N	2026-11-08 21:12:46.205621+08	\N
5d8c504f-5bdb-4c64-a147-67eacf3f49d2	540f2fa1-53f8-4e43-9841-8eb881a0c529	1fd40ad8-d824-4a30-a169-3d636eadfb42	app_jank_heavy_count	1.0	次	component	2026-11-08T21:12:22+08:00/2026-11-08T21:12:45+08:00	mean	1	0	\N	2026-11-08 21:12:46.205621+08	\N
5917883d-3a6c-4793-a4c5-3f61a6f269e2	540f2fa1-53f8-4e43-9841-8eb881a0c529	1fd40ad8-d824-4a30-a169-3d636eadfb42	app_jank_heavy_count	1.0	次	component	2026-11-08T21:12:22+08:00/2026-11-08T21:12:45+08:00	max	1	0	\N	2026-11-08 21:12:46.205621+08	\N
207d5746-7b4f-4048-9009-7861db111710	540f2fa1-53f8-4e43-9841-8eb881a0c529	1fd40ad8-d824-4a30-a169-3d636eadfb42	app_jank_heavy_count	1.0	次	component	2026-11-08T21:12:22+08:00/2026-11-08T21:12:45+08:00	p90	1	0	\N	2026-11-08 21:12:46.205621+08	\N
0baf9a43-34b2-496d-8ef7-ce2a5fdc61fa	540f2fa1-53f8-4e43-9841-8eb881a0c529	1fd40ad8-d824-4a30-a169-3d636eadfb42	app_jank_severe_count	1.0	次	component	2026-11-08T21:12:22+08:00/2026-11-08T21:12:45+08:00	min	1	0	\N	2026-11-08 21:12:46.205621+08	\N
06e98255-db41-4b0e-8560-00f6bd6c2041	540f2fa1-53f8-4e43-9841-8eb881a0c529	1fd40ad8-d824-4a30-a169-3d636eadfb42	app_jank_severe_count	1.0	次	component	2026-11-08T21:12:22+08:00/2026-11-08T21:12:45+08:00	median	1	0	\N	2026-11-08 21:12:46.205621+08	\N
28ac5d55-4219-442d-a526-c6a710fec458	540f2fa1-53f8-4e43-9841-8eb881a0c529	1fd40ad8-d824-4a30-a169-3d636eadfb42	app_jank_severe_count	1.0	次	component	2026-11-08T21:12:22+08:00/2026-11-08T21:12:45+08:00	mean	1	0	\N	2026-11-08 21:12:46.205621+08	\N
5de1c8a6-7b83-409f-b2f1-5011e2f9fafb	540f2fa1-53f8-4e43-9841-8eb881a0c529	1fd40ad8-d824-4a30-a169-3d636eadfb42	app_jank_severe_count	1.0	次	component	2026-11-08T21:12:22+08:00/2026-11-08T21:12:45+08:00	max	1	0	\N	2026-11-08 21:12:46.205621+08	\N
49104378-ab95-4d7a-be8b-41329e561f29	540f2fa1-53f8-4e43-9841-8eb881a0c529	1fd40ad8-d824-4a30-a169-3d636eadfb42	app_jank_severe_count	1.0	次	component	2026-11-08T21:12:22+08:00/2026-11-08T21:12:45+08:00	p90	1	0	\N	2026-11-08 21:12:46.205621+08	\N
e2a5efb5-c5de-4d5b-ba8d-6f0197b7df00	540f2fa1-53f8-4e43-9841-8eb881a0c529	1fd40ad8-d824-4a30-a169-3d636eadfb42	temp_battery_c	1.0	°C	component	2026-11-08T21:12:22+08:00/2026-11-08T21:12:45+08:00	min	9	33.2	\N	2026-11-08 21:12:46.205621+08	\N
da5685f1-2a26-456c-ba12-29cded31abe5	540f2fa1-53f8-4e43-9841-8eb881a0c529	1fd40ad8-d824-4a30-a169-3d636eadfb42	temp_battery_c	1.0	°C	component	2026-11-08T21:12:22+08:00/2026-11-08T21:12:45+08:00	median	9	33.2	\N	2026-11-08 21:12:46.205621+08	\N
bdfb8551-d9bc-4b78-bf9e-a035e5aa7a26	540f2fa1-53f8-4e43-9841-8eb881a0c529	1fd40ad8-d824-4a30-a169-3d636eadfb42	temp_battery_c	1.0	°C	component	2026-11-08T21:12:22+08:00/2026-11-08T21:12:45+08:00	mean	9	33.2	\N	2026-11-08 21:12:46.205621+08	\N
73ffa14c-411d-43ce-a2ee-983dd254d550	540f2fa1-53f8-4e43-9841-8eb881a0c529	1fd40ad8-d824-4a30-a169-3d636eadfb42	temp_battery_c	1.0	°C	component	2026-11-08T21:12:22+08:00/2026-11-08T21:12:45+08:00	max	9	33.2	\N	2026-11-08 21:12:46.205621+08	\N
6c2efb3d-f1ca-415a-8cd3-ea5b0ba5a339	540f2fa1-53f8-4e43-9841-8eb881a0c529	1fd40ad8-d824-4a30-a169-3d636eadfb42	temp_battery_c	1.0	°C	component	2026-11-08T21:12:22+08:00/2026-11-08T21:12:45+08:00	p90	9	33.2	\N	2026-11-08 21:12:46.205621+08	\N
52a0f90f-7e60-4948-992c-ef1b7741d025	540f2fa1-53f8-4e43-9841-8eb881a0c529	1fd40ad8-d824-4a30-a169-3d636eadfb42	gpu_util_pct	1.0	%	component	2026-11-08T21:12:22+08:00/2026-11-08T21:12:45+08:00	min	9	1.3642160319140646	\N	2026-11-08 21:12:46.205621+08	\N
6be549a5-b977-4f06-b506-7ca698c7565e	540f2fa1-53f8-4e43-9841-8eb881a0c529	1fd40ad8-d824-4a30-a169-3d636eadfb42	gpu_util_pct	1.0	%	component	2026-11-08T21:12:22+08:00/2026-11-08T21:12:45+08:00	median	9	1.4477410500695673	\N	2026-11-08 21:12:46.205621+08	\N
882bf798-13d1-46e8-861d-bee6a59d8dd1	540f2fa1-53f8-4e43-9841-8eb881a0c529	1fd40ad8-d824-4a30-a169-3d636eadfb42	gpu_util_pct	1.0	%	component	2026-11-08T21:12:22+08:00/2026-11-08T21:12:45+08:00	mean	9	2.5651034801518775	\N	2026-11-08 21:12:46.205621+08	\N
683218d7-1583-4bcc-8255-0ab2d44dddc7	540f2fa1-53f8-4e43-9841-8eb881a0c529	1fd40ad8-d824-4a30-a169-3d636eadfb42	gpu_util_pct	1.0	%	component	2026-11-08T21:12:22+08:00/2026-11-08T21:12:45+08:00	max	9	5.643846019158091	\N	2026-11-08 21:12:46.205621+08	\N
be16199b-bffe-42fe-b6ee-41a46711b857	540f2fa1-53f8-4e43-9841-8eb881a0c529	1fd40ad8-d824-4a30-a169-3d636eadfb42	gpu_util_pct	1.0	%	component	2026-11-08T21:12:22+08:00/2026-11-08T21:12:45+08:00	p90	9	5.643846019158091	\N	2026-11-08 21:12:46.205621+08	\N
ccf23fc6-61b0-4f80-bed1-291ac18f54c3	540f2fa1-53f8-4e43-9841-8eb881a0c529	1fd40ad8-d824-4a30-a169-3d636eadfb42	gpu_mem_mb	1.0	MB	component	2026-11-08T21:12:22+08:00/2026-11-08T21:12:45+08:00	min	9	4.75	\N	2026-11-08 21:12:46.205621+08	\N
f4e0819c-bc7d-4e6c-9f27-ba384d6751ca	540f2fa1-53f8-4e43-9841-8eb881a0c529	1fd40ad8-d824-4a30-a169-3d636eadfb42	gpu_mem_mb	1.0	MB	component	2026-11-08T21:12:22+08:00/2026-11-08T21:12:45+08:00	median	9	47.359375	\N	2026-11-08 21:12:46.205621+08	\N
7f007e05-3ea0-4899-8363-1a2ca2e77599	540f2fa1-53f8-4e43-9841-8eb881a0c529	1fd40ad8-d824-4a30-a169-3d636eadfb42	gpu_mem_mb	1.0	MB	component	2026-11-08T21:12:22+08:00/2026-11-08T21:12:45+08:00	mean	9	42.309895833333336	\N	2026-11-08 21:12:46.205621+08	\N
41e62992-f900-44e8-ad93-cbc1628e0c2a	540f2fa1-53f8-4e43-9841-8eb881a0c529	1fd40ad8-d824-4a30-a169-3d636eadfb42	gpu_mem_mb	1.0	MB	component	2026-11-08T21:12:22+08:00/2026-11-08T21:12:45+08:00	max	9	47.390625	\N	2026-11-08 21:12:46.205621+08	\N
34fb7d9c-6232-45e4-aad6-81b1327fd53f	540f2fa1-53f8-4e43-9841-8eb881a0c529	1fd40ad8-d824-4a30-a169-3d636eadfb42	gpu_mem_mb	1.0	MB	component	2026-11-08T21:12:22+08:00/2026-11-08T21:12:45+08:00	p90	9	47.365625	\N	2026-11-08 21:12:46.205621+08	\N
89955953-8a83-46eb-9c27-be2fa80f52a3	540f2fa1-53f8-4e43-9841-8eb881a0c529	9ad8f101-9763-4a10-90cc-92033b5fe9b3	cpu_process_pct	1.0	%	component	2026-11-08T21:16:39+08:00/2026-11-08T21:17:02+08:00	min	43	0	\N	2026-11-08 21:17:03.102559+08	\N
d790aac5-fc74-4bcd-9d28-2b0a94507ce5	540f2fa1-53f8-4e43-9841-8eb881a0c529	9ad8f101-9763-4a10-90cc-92033b5fe9b3	cpu_process_pct	1.0	%	component	2026-11-08T21:16:39+08:00/2026-11-08T21:17:02+08:00	median	43	0.25906736	\N	2026-11-08 21:17:03.102559+08	\N
57d04219-d277-4fd5-a294-5fc430cb0160	540f2fa1-53f8-4e43-9841-8eb881a0c529	9ad8f101-9763-4a10-90cc-92033b5fe9b3	cpu_process_pct	1.0	%	component	2026-11-08T21:16:39+08:00/2026-11-08T21:17:02+08:00	mean	43	0.5079167111627907	\N	2026-11-08 21:17:03.102559+08	\N
81ca653e-feb8-4351-bbf5-5079faac4bad	540f2fa1-53f8-4e43-9841-8eb881a0c529	9ad8f101-9763-4a10-90cc-92033b5fe9b3	cpu_process_pct	1.0	%	component	2026-11-08T21:16:39+08:00/2026-11-08T21:17:02+08:00	max	43	2.8645835	\N	2026-11-08 21:17:03.102559+08	\N
e3354c94-7878-4feb-be2f-2103eae4b132	540f2fa1-53f8-4e43-9841-8eb881a0c529	9ad8f101-9763-4a10-90cc-92033b5fe9b3	cpu_process_pct	1.0	%	component	2026-11-08T21:16:39+08:00/2026-11-08T21:17:02+08:00	p90	43	1.0373543600000001	\N	2026-11-08 21:17:03.102559+08	\N
cfd3b29e-1f6b-4da6-ad9f-31d157be76be	540f2fa1-53f8-4e43-9841-8eb881a0c529	9ad8f101-9763-4a10-90cc-92033b5fe9b3	cpu_global_pct	1.0	%	component	2026-11-08T21:16:39+08:00/2026-11-08T21:17:02+08:00	min	43	10.869565	\N	2026-11-08 21:17:03.102559+08	\N
f8a18d4d-fd50-4990-a099-2b5dbfba42af	540f2fa1-53f8-4e43-9841-8eb881a0c529	9ad8f101-9763-4a10-90cc-92033b5fe9b3	cpu_global_pct	1.0	%	component	2026-11-08T21:16:39+08:00/2026-11-08T21:17:02+08:00	median	43	16.70951	\N	2026-11-08 21:17:03.102559+08	\N
949666d9-4813-407e-9046-b9091c581e1c	540f2fa1-53f8-4e43-9841-8eb881a0c529	9ad8f101-9763-4a10-90cc-92033b5fe9b3	cpu_global_pct	1.0	%	component	2026-11-08T21:16:39+08:00/2026-11-08T21:17:02+08:00	mean	43	19.95002846511628	\N	2026-11-08 21:17:03.102559+08	\N
39202ab7-1810-4a0f-b5d0-4304a9f26bc1	540f2fa1-53f8-4e43-9841-8eb881a0c529	9ad8f101-9763-4a10-90cc-92033b5fe9b3	cpu_global_pct	1.0	%	component	2026-11-08T21:16:39+08:00/2026-11-08T21:17:02+08:00	max	43	48.812664	\N	2026-11-08 21:17:03.102559+08	\N
8fbbdf97-080f-46cc-8bfa-cfa3882da898	540f2fa1-53f8-4e43-9841-8eb881a0c529	9ad8f101-9763-4a10-90cc-92033b5fe9b3	cpu_global_pct	1.0	%	component	2026-11-08T21:16:39+08:00/2026-11-08T21:17:02+08:00	p90	43	30.254085400000005	\N	2026-11-08 21:17:03.102559+08	\N
c8e1f254-ed57-4f6f-a4be-bc2e94adcb56	540f2fa1-53f8-4e43-9841-8eb881a0c529	9ad8f101-9763-4a10-90cc-92033b5fe9b3	mem_pss_mb	1.0	MB	component	2026-11-08T21:16:39+08:00/2026-11-08T21:17:02+08:00	min	16	45.535156	\N	2026-11-08 21:17:03.102559+08	\N
fa3d3ffe-b4a5-4c5b-95a6-2c73bc3eb912	540f2fa1-53f8-4e43-9841-8eb881a0c529	9ad8f101-9763-4a10-90cc-92033b5fe9b3	mem_pss_mb	1.0	MB	component	2026-11-08T21:16:39+08:00/2026-11-08T21:17:02+08:00	median	16	84.78516	\N	2026-11-08 21:17:03.102559+08	\N
d51d4f86-4253-4155-8ecd-0fb0b0884140	540f2fa1-53f8-4e43-9841-8eb881a0c529	9ad8f101-9763-4a10-90cc-92033b5fe9b3	mem_pss_mb	1.0	MB	component	2026-11-08T21:16:39+08:00/2026-11-08T21:17:02+08:00	mean	16	79.6809085	\N	2026-11-08 21:17:03.102559+08	\N
278214c5-d7dc-4397-854e-8e20e6738a67	540f2fa1-53f8-4e43-9841-8eb881a0c529	9ad8f101-9763-4a10-90cc-92033b5fe9b3	mem_pss_mb	1.0	MB	component	2026-11-08T21:16:39+08:00/2026-11-08T21:17:02+08:00	max	16	85.33203	\N	2026-11-08 21:17:03.102559+08	\N
ada5fe9f-8133-4343-8897-aeacb8ff116c	540f2fa1-53f8-4e43-9841-8eb881a0c529	9ad8f101-9763-4a10-90cc-92033b5fe9b3	mem_pss_mb	1.0	MB	component	2026-11-08T21:16:39+08:00/2026-11-08T21:17:02+08:00	p90	16	85.3188475	\N	2026-11-08 21:17:03.102559+08	\N
b07e98ea-7bf3-493d-8ded-65167570531b	540f2fa1-53f8-4e43-9841-8eb881a0c529	9ad8f101-9763-4a10-90cc-92033b5fe9b3	mem_privdirty_mb	1.0	MB	component	2026-11-08T21:16:39+08:00/2026-11-08T21:17:02+08:00	min	16	20.429688	\N	2026-11-08 21:17:03.102559+08	\N
b90f0053-6fa9-460c-95f9-6726dd4d8edc	540f2fa1-53f8-4e43-9841-8eb881a0c529	9ad8f101-9763-4a10-90cc-92033b5fe9b3	mem_privdirty_mb	1.0	MB	component	2026-11-08T21:16:39+08:00/2026-11-08T21:17:02+08:00	median	16	61.1777345	\N	2026-11-08 21:17:03.102559+08	\N
9d6eb2ba-4ef7-4c1f-bab0-7c8915ad1968	540f2fa1-53f8-4e43-9841-8eb881a0c529	9ad8f101-9763-4a10-90cc-92033b5fe9b3	mem_privdirty_mb	1.0	MB	component	2026-11-08T21:16:39+08:00/2026-11-08T21:17:02+08:00	mean	16	56.1210938125	\N	2026-11-08 21:17:03.102559+08	\N
1d22ba0a-91c6-4bc7-b218-cd159d1e16a7	540f2fa1-53f8-4e43-9841-8eb881a0c529	9ad8f101-9763-4a10-90cc-92033b5fe9b3	mem_privdirty_mb	1.0	MB	component	2026-11-08T21:16:39+08:00/2026-11-08T21:17:02+08:00	max	16	62.65625	\N	2026-11-08 21:17:03.102559+08	\N
c8e444c3-4a50-4d50-a090-d743775730a2	540f2fa1-53f8-4e43-9841-8eb881a0c529	9ad8f101-9763-4a10-90cc-92033b5fe9b3	mem_privdirty_mb	1.0	MB	component	2026-11-08T21:16:39+08:00/2026-11-08T21:17:02+08:00	p90	16	61.4824225	\N	2026-11-08 21:17:03.102559+08	\N
daea6aea-a8d1-4a7d-867f-115257421e9f	540f2fa1-53f8-4e43-9841-8eb881a0c529	9ad8f101-9763-4a10-90cc-92033b5fe9b3	mem_global_mb	1.0	MB	component	2026-11-08T21:16:39+08:00/2026-11-08T21:17:02+08:00	min	19	4272	\N	2026-11-08 21:17:03.102559+08	\N
f65e1140-2da7-490a-980c-fa7fc6fafbbc	540f2fa1-53f8-4e43-9841-8eb881a0c529	9ad8f101-9763-4a10-90cc-92033b5fe9b3	mem_global_mb	1.0	MB	component	2026-11-08T21:16:39+08:00/2026-11-08T21:17:02+08:00	median	19	4408	\N	2026-11-08 21:17:03.102559+08	\N
6330bdc5-6291-40d7-b446-36a575a1295f	540f2fa1-53f8-4e43-9841-8eb881a0c529	9ad8f101-9763-4a10-90cc-92033b5fe9b3	mem_global_mb	1.0	MB	component	2026-11-08T21:16:39+08:00/2026-11-08T21:17:02+08:00	mean	19	4385.8421052631575	\N	2026-11-08 21:17:03.102559+08	\N
d257ae5c-61ed-465d-b243-ad81d719a42e	540f2fa1-53f8-4e43-9841-8eb881a0c529	9ad8f101-9763-4a10-90cc-92033b5fe9b3	mem_global_mb	1.0	MB	component	2026-11-08T21:16:39+08:00/2026-11-08T21:17:02+08:00	max	19	4423	\N	2026-11-08 21:17:03.102559+08	\N
2a1b9ea7-c7a4-4ac0-9041-58523a237675	540f2fa1-53f8-4e43-9841-8eb881a0c529	9ad8f101-9763-4a10-90cc-92033b5fe9b3	mem_global_mb	1.0	MB	component	2026-11-08T21:16:39+08:00/2026-11-08T21:17:02+08:00	p90	19	4417.2	\N	2026-11-08 21:17:03.102559+08	\N
d15a7ae7-b47e-4ff2-80c3-a4da165d2edd	540f2fa1-53f8-4e43-9841-8eb881a0c529	9ad8f101-9763-4a10-90cc-92033b5fe9b3	fps_frame	1.0	fps	component	2026-11-08T21:16:39+08:00/2026-11-08T21:17:02+08:00	min	21	116	\N	2026-11-08 21:17:03.102559+08	\N
59d0577f-ec5e-412e-8539-69dd38d30f99	540f2fa1-53f8-4e43-9841-8eb881a0c529	9ad8f101-9763-4a10-90cc-92033b5fe9b3	fps_frame	1.0	fps	component	2026-11-08T21:16:39+08:00/2026-11-08T21:17:02+08:00	median	21	120	\N	2026-11-08 21:17:03.102559+08	\N
cda11088-0a33-4493-888c-4588a37a9c65	540f2fa1-53f8-4e43-9841-8eb881a0c529	9ad8f101-9763-4a10-90cc-92033b5fe9b3	fps_frame	1.0	fps	component	2026-11-08T21:16:39+08:00/2026-11-08T21:17:02+08:00	mean	21	5083915.428571428	\N	2026-11-08 21:17:03.102559+08	\N
380a1229-a0fd-4b21-9652-3015d67aa5aa	540f2fa1-53f8-4e43-9841-8eb881a0c529	9ad8f101-9763-4a10-90cc-92033b5fe9b3	fps_frame	1.0	fps	component	2026-11-08T21:16:39+08:00/2026-11-08T21:17:02+08:00	max	21	53380908	\N	2026-11-08 21:17:03.102559+08	\N
5af8d936-2ebc-437d-9b99-3dde8afa5645	540f2fa1-53f8-4e43-9841-8eb881a0c529	9ad8f101-9763-4a10-90cc-92033b5fe9b3	fps_frame	1.0	fps	component	2026-11-08T21:16:39+08:00/2026-11-08T21:17:02+08:00	p90	21	120	\N	2026-11-08 21:17:03.102559+08	\N
5145bf79-2361-4715-9274-ddd3e48332b1	540f2fa1-53f8-4e43-9841-8eb881a0c529	9ad8f101-9763-4a10-90cc-92033b5fe9b3	frame_delay_ratio_pct	1.0	%	component	2026-11-08T21:16:39+08:00/2026-11-08T21:17:02+08:00	min	21	0	\N	2026-11-08 21:17:03.102559+08	\N
81dc4b05-d8a4-4b2e-80ce-76c12f1d8b8e	540f2fa1-53f8-4e43-9841-8eb881a0c529	9ad8f101-9763-4a10-90cc-92033b5fe9b3	frame_delay_ratio_pct	1.0	%	component	2026-11-08T21:16:39+08:00/2026-11-08T21:17:02+08:00	median	21	0	\N	2026-11-08 21:17:03.102559+08	\N
2d8ad77d-9559-4d9e-8f9c-f82c70a8d7a4	540f2fa1-53f8-4e43-9841-8eb881a0c529	9ad8f101-9763-4a10-90cc-92033b5fe9b3	frame_delay_ratio_pct	1.0	%	component	2026-11-08T21:16:39+08:00/2026-11-08T21:17:02+08:00	mean	21	11.031746571428572	\N	2026-11-08 21:17:03.102559+08	\N
970ee5f7-4169-4d72-864a-31aaf2fa1720	540f2fa1-53f8-4e43-9841-8eb881a0c529	9ad8f101-9763-4a10-90cc-92033b5fe9b3	frame_delay_ratio_pct	1.0	%	component	2026-11-08T21:16:39+08:00/2026-11-08T21:17:02+08:00	max	21	50	\N	2026-11-08 21:17:03.102559+08	\N
28d18b92-9e81-4ee0-8768-52b57d0384b0	540f2fa1-53f8-4e43-9841-8eb881a0c529	9ad8f101-9763-4a10-90cc-92033b5fe9b3	frame_delay_ratio_pct	1.0	%	component	2026-11-08T21:16:39+08:00/2026-11-08T21:17:02+08:00	p90	21	33.333336	\N	2026-11-08 21:17:03.102559+08	\N
69302181-8b4c-48b3-ae73-97a53f139517	540f2fa1-53f8-4e43-9841-8eb881a0c529	9ad8f101-9763-4a10-90cc-92033b5fe9b3	frame_delay_count	1.0	次	component	2026-11-08T21:16:39+08:00/2026-11-08T21:17:02+08:00	min	21	0	\N	2026-11-08 21:17:03.102559+08	\N
7795a141-f0d7-443e-bbf1-428b3ad4ad93	540f2fa1-53f8-4e43-9841-8eb881a0c529	9ad8f101-9763-4a10-90cc-92033b5fe9b3	frame_delay_count	1.0	次	component	2026-11-08T21:16:39+08:00/2026-11-08T21:17:02+08:00	median	21	0	\N	2026-11-08 21:17:03.102559+08	\N
567c4752-468f-4ccf-93d6-3ebab063d9c4	540f2fa1-53f8-4e43-9841-8eb881a0c529	9ad8f101-9763-4a10-90cc-92033b5fe9b3	frame_delay_count	1.0	次	component	2026-11-08T21:16:39+08:00/2026-11-08T21:17:02+08:00	mean	21	0.5238095238095238	\N	2026-11-08 21:17:03.102559+08	\N
2ae0777c-a209-4e1c-9489-ec7bb3d8ad1f	540f2fa1-53f8-4e43-9841-8eb881a0c529	9ad8f101-9763-4a10-90cc-92033b5fe9b3	frame_delay_count	1.0	次	component	2026-11-08T21:16:39+08:00/2026-11-08T21:17:02+08:00	max	21	3	\N	2026-11-08 21:17:03.102559+08	\N
11260548-3480-4ac4-9510-296ae8f25dc7	540f2fa1-53f8-4e43-9841-8eb881a0c529	9ad8f101-9763-4a10-90cc-92033b5fe9b3	frame_delay_count	1.0	次	component	2026-11-08T21:16:39+08:00/2026-11-08T21:17:02+08:00	p90	21	2	\N	2026-11-08 21:17:03.102559+08	\N
f7e9242a-8617-48cc-ae7a-e51c6752047e	540f2fa1-53f8-4e43-9841-8eb881a0c529	9ad8f101-9763-4a10-90cc-92033b5fe9b3	frame_delay_max_ms	1.0	ms	component	2026-11-08T21:16:39+08:00/2026-11-08T21:17:02+08:00	min	21	4	\N	2026-11-08 21:17:03.102559+08	\N
43619ae8-f9c7-486a-b8f4-c9536aba44fd	540f2fa1-53f8-4e43-9841-8eb881a0c529	9ad8f101-9763-4a10-90cc-92033b5fe9b3	frame_delay_max_ms	1.0	ms	component	2026-11-08T21:16:39+08:00/2026-11-08T21:17:02+08:00	median	21	8	\N	2026-11-08 21:17:03.102559+08	\N
fb579caa-f6c6-42df-bbda-481a2b8437bc	540f2fa1-53f8-4e43-9841-8eb881a0c529	9ad8f101-9763-4a10-90cc-92033b5fe9b3	frame_delay_max_ms	1.0	ms	component	2026-11-08T21:16:39+08:00/2026-11-08T21:17:02+08:00	mean	21	10.952380952380953	\N	2026-11-08 21:17:03.102559+08	\N
4bc60b84-06d0-4a1e-9ab8-24e4835cf0bd	540f2fa1-53f8-4e43-9841-8eb881a0c529	9ad8f101-9763-4a10-90cc-92033b5fe9b3	frame_delay_max_ms	1.0	ms	component	2026-11-08T21:16:39+08:00/2026-11-08T21:17:02+08:00	max	21	29	\N	2026-11-08 21:17:03.102559+08	\N
6bd0de2b-e407-4edc-8c29-994c559bc642	540f2fa1-53f8-4e43-9841-8eb881a0c529	9ad8f101-9763-4a10-90cc-92033b5fe9b3	frame_delay_max_ms	1.0	ms	component	2026-11-08T21:16:39+08:00/2026-11-08T21:17:02+08:00	p90	21	29	\N	2026-11-08 21:17:03.102559+08	\N
7413b582-52c0-4e9c-a2f1-258b5853da3c	540f2fa1-53f8-4e43-9841-8eb881a0c529	9ad8f101-9763-4a10-90cc-92033b5fe9b3	app_jank_light_count	1.0	次	component	2026-11-08T21:16:39+08:00/2026-11-08T21:17:02+08:00	min	1	0	\N	2026-11-08 21:17:03.102559+08	\N
1c367818-819e-4ed1-bac1-27dba76ca87b	540f2fa1-53f8-4e43-9841-8eb881a0c529	9ad8f101-9763-4a10-90cc-92033b5fe9b3	app_jank_light_count	1.0	次	component	2026-11-08T21:16:39+08:00/2026-11-08T21:17:02+08:00	median	1	0	\N	2026-11-08 21:17:03.102559+08	\N
6ef7a50f-c033-4445-9b0e-57a3ac694961	540f2fa1-53f8-4e43-9841-8eb881a0c529	9ad8f101-9763-4a10-90cc-92033b5fe9b3	app_jank_light_count	1.0	次	component	2026-11-08T21:16:39+08:00/2026-11-08T21:17:02+08:00	mean	1	0	\N	2026-11-08 21:17:03.102559+08	\N
8922e7b5-c2e8-4c59-a1df-7862cdac7cd3	540f2fa1-53f8-4e43-9841-8eb881a0c529	9ad8f101-9763-4a10-90cc-92033b5fe9b3	app_jank_light_count	1.0	次	component	2026-11-08T21:16:39+08:00/2026-11-08T21:17:02+08:00	max	1	0	\N	2026-11-08 21:17:03.102559+08	\N
d69d685e-73c4-43a8-8666-40ec8178e97d	540f2fa1-53f8-4e43-9841-8eb881a0c529	9ad8f101-9763-4a10-90cc-92033b5fe9b3	app_jank_light_count	1.0	次	component	2026-11-08T21:16:39+08:00/2026-11-08T21:17:02+08:00	p90	1	0	\N	2026-11-08 21:17:03.102559+08	\N
14671557-d3ce-41a4-ae76-78ee72b26cdc	540f2fa1-53f8-4e43-9841-8eb881a0c529	9ad8f101-9763-4a10-90cc-92033b5fe9b3	app_jank_heavy_count	1.0	次	component	2026-11-08T21:16:39+08:00/2026-11-08T21:17:02+08:00	min	1	0	\N	2026-11-08 21:17:03.102559+08	\N
0efbfe0c-ab15-4eec-b013-b0926d3667cf	540f2fa1-53f8-4e43-9841-8eb881a0c529	9ad8f101-9763-4a10-90cc-92033b5fe9b3	app_jank_heavy_count	1.0	次	component	2026-11-08T21:16:39+08:00/2026-11-08T21:17:02+08:00	median	1	0	\N	2026-11-08 21:17:03.102559+08	\N
67d4d4ac-f0ff-4268-a4f8-f6dd35350635	540f2fa1-53f8-4e43-9841-8eb881a0c529	9ad8f101-9763-4a10-90cc-92033b5fe9b3	app_jank_heavy_count	1.0	次	component	2026-11-08T21:16:39+08:00/2026-11-08T21:17:02+08:00	mean	1	0	\N	2026-11-08 21:17:03.102559+08	\N
d674a5e3-03f6-4aaf-a069-9314e5472e9a	540f2fa1-53f8-4e43-9841-8eb881a0c529	9ad8f101-9763-4a10-90cc-92033b5fe9b3	app_jank_heavy_count	1.0	次	component	2026-11-08T21:16:39+08:00/2026-11-08T21:17:02+08:00	max	1	0	\N	2026-11-08 21:17:03.102559+08	\N
6083ba90-2c07-4a9c-8751-306be7428c29	540f2fa1-53f8-4e43-9841-8eb881a0c529	9ad8f101-9763-4a10-90cc-92033b5fe9b3	app_jank_heavy_count	1.0	次	component	2026-11-08T21:16:39+08:00/2026-11-08T21:17:02+08:00	p90	1	0	\N	2026-11-08 21:17:03.102559+08	\N
3ba617cd-067e-4f29-a2fe-259431014e48	540f2fa1-53f8-4e43-9841-8eb881a0c529	9ad8f101-9763-4a10-90cc-92033b5fe9b3	app_jank_severe_count	1.0	次	component	2026-11-08T21:16:39+08:00/2026-11-08T21:17:02+08:00	min	1	0	\N	2026-11-08 21:17:03.102559+08	\N
56613b25-e602-4244-aa29-2b6fd90a4d92	540f2fa1-53f8-4e43-9841-8eb881a0c529	9ad8f101-9763-4a10-90cc-92033b5fe9b3	app_jank_severe_count	1.0	次	component	2026-11-08T21:16:39+08:00/2026-11-08T21:17:02+08:00	median	1	0	\N	2026-11-08 21:17:03.102559+08	\N
f7215a07-6115-42e6-a192-b4e0fd9415e4	540f2fa1-53f8-4e43-9841-8eb881a0c529	9ad8f101-9763-4a10-90cc-92033b5fe9b3	app_jank_severe_count	1.0	次	component	2026-11-08T21:16:39+08:00/2026-11-08T21:17:02+08:00	mean	1	0	\N	2026-11-08 21:17:03.102559+08	\N
8e6e716e-eeea-4647-8055-611596b727fa	540f2fa1-53f8-4e43-9841-8eb881a0c529	9ad8f101-9763-4a10-90cc-92033b5fe9b3	app_jank_severe_count	1.0	次	component	2026-11-08T21:16:39+08:00/2026-11-08T21:17:02+08:00	max	1	0	\N	2026-11-08 21:17:03.102559+08	\N
8dda9299-d85f-4e25-8539-f1ff31bb3785	540f2fa1-53f8-4e43-9841-8eb881a0c529	9ad8f101-9763-4a10-90cc-92033b5fe9b3	app_jank_severe_count	1.0	次	component	2026-11-08T21:16:39+08:00/2026-11-08T21:17:02+08:00	p90	1	0	\N	2026-11-08 21:17:03.102559+08	\N
e3e3d13e-ef58-42ac-af68-a4874ceff757	540f2fa1-53f8-4e43-9841-8eb881a0c529	9ad8f101-9763-4a10-90cc-92033b5fe9b3	temp_battery_c	1.0	°C	component	2026-11-08T21:16:39+08:00/2026-11-08T21:17:02+08:00	min	10	33.6	\N	2026-11-08 21:17:03.102559+08	\N
be70326e-5b3c-4e09-abb4-097f7d7eff5b	540f2fa1-53f8-4e43-9841-8eb881a0c529	9ad8f101-9763-4a10-90cc-92033b5fe9b3	temp_battery_c	1.0	°C	component	2026-11-08T21:16:39+08:00/2026-11-08T21:17:02+08:00	median	10	33.6	\N	2026-11-08 21:17:03.102559+08	\N
35f01c15-8efc-41a5-90e0-8788335a9fa7	540f2fa1-53f8-4e43-9841-8eb881a0c529	9ad8f101-9763-4a10-90cc-92033b5fe9b3	temp_battery_c	1.0	°C	component	2026-11-08T21:16:39+08:00/2026-11-08T21:17:02+08:00	mean	10	33.6	\N	2026-11-08 21:17:03.102559+08	\N
1d62c1f2-75fc-4d45-9270-30b7082a085f	540f2fa1-53f8-4e43-9841-8eb881a0c529	9ad8f101-9763-4a10-90cc-92033b5fe9b3	temp_battery_c	1.0	°C	component	2026-11-08T21:16:39+08:00/2026-11-08T21:17:02+08:00	max	10	33.6	\N	2026-11-08 21:17:03.102559+08	\N
d5008687-e4fb-4c11-ab48-6e4a22952280	540f2fa1-53f8-4e43-9841-8eb881a0c529	9ad8f101-9763-4a10-90cc-92033b5fe9b3	temp_battery_c	1.0	°C	component	2026-11-08T21:16:39+08:00/2026-11-08T21:17:02+08:00	p90	10	33.6	\N	2026-11-08 21:17:03.102559+08	\N
bf482cca-0324-4236-8360-6f5565278d4c	540f2fa1-53f8-4e43-9841-8eb881a0c529	9ad8f101-9763-4a10-90cc-92033b5fe9b3	gpu_util_pct	1.0	%	component	2026-11-08T21:16:39+08:00/2026-11-08T21:17:02+08:00	min	10	0	\N	2026-11-08 21:17:03.102559+08	\N
d5fa027d-9018-43a5-bcfd-b870077e3b21	540f2fa1-53f8-4e43-9841-8eb881a0c529	9ad8f101-9763-4a10-90cc-92033b5fe9b3	gpu_util_pct	1.0	%	component	2026-11-08T21:16:39+08:00/2026-11-08T21:17:02+08:00	median	10	2.5352640907322765	\N	2026-11-08 21:17:03.102559+08	\N
1fe2a651-0fc9-465c-b228-2bf6a1385df9	540f2fa1-53f8-4e43-9841-8eb881a0c529	9ad8f101-9763-4a10-90cc-92033b5fe9b3	gpu_util_pct	1.0	%	component	2026-11-08T21:16:39+08:00/2026-11-08T21:17:02+08:00	mean	10	2.726228206086181	\N	2026-11-08 21:17:03.102559+08	\N
cbaf5831-710c-4eca-8a8a-6c3817b15b3d	540f2fa1-53f8-4e43-9841-8eb881a0c529	9ad8f101-9763-4a10-90cc-92033b5fe9b3	gpu_util_pct	1.0	%	component	2026-11-08T21:16:39+08:00/2026-11-08T21:17:02+08:00	max	10	5.4939324280178266	\N	2026-11-08 21:17:03.102559+08	\N
d8244443-5418-41d4-a466-732ac21330d6	540f2fa1-53f8-4e43-9841-8eb881a0c529	9ad8f101-9763-4a10-90cc-92033b5fe9b3	gpu_util_pct	1.0	%	component	2026-11-08T21:16:39+08:00/2026-11-08T21:17:02+08:00	p90	10	5.4939324280178266	\N	2026-11-08 21:17:03.102559+08	\N
fbf16367-f28c-4562-93a6-1a15c2fbef89	540f2fa1-53f8-4e43-9841-8eb881a0c529	9ad8f101-9763-4a10-90cc-92033b5fe9b3	gpu_mem_mb	1.0	MB	component	2026-11-08T21:16:39+08:00/2026-11-08T21:17:02+08:00	min	10	4.75	\N	2026-11-08 21:17:03.102559+08	\N
ce95b981-9c78-4aa7-b5f1-d25835f2fefa	540f2fa1-53f8-4e43-9841-8eb881a0c529	9ad8f101-9763-4a10-90cc-92033b5fe9b3	gpu_mem_mb	1.0	MB	component	2026-11-08T21:16:39+08:00/2026-11-08T21:17:02+08:00	median	10	47.05078125	\N	2026-11-08 21:17:03.102559+08	\N
cac4f682-b23d-4665-8e80-304a4d67785f	540f2fa1-53f8-4e43-9841-8eb881a0c529	9ad8f101-9763-4a10-90cc-92033b5fe9b3	gpu_mem_mb	1.0	MB	component	2026-11-08T21:16:39+08:00/2026-11-08T21:17:02+08:00	mean	10	38.553125	\N	2026-11-08 21:17:03.102559+08	\N
6cc20e33-1328-42c0-94c2-150ff2e69152	540f2fa1-53f8-4e43-9841-8eb881a0c529	9ad8f101-9763-4a10-90cc-92033b5fe9b3	gpu_mem_mb	1.0	MB	component	2026-11-08T21:16:39+08:00/2026-11-08T21:17:02+08:00	max	10	47.390625	\N	2026-11-08 21:17:03.102559+08	\N
b0bc0281-318f-45af-947f-91f209e8dc1a	540f2fa1-53f8-4e43-9841-8eb881a0c529	9ad8f101-9763-4a10-90cc-92033b5fe9b3	gpu_mem_mb	1.0	MB	component	2026-11-08T21:16:39+08:00/2026-11-08T21:17:02+08:00	p90	10	47.3625	\N	2026-11-08 21:17:03.102559+08	\N
1cf380c0-8d34-494e-93f6-807a2e789608	540f2fa1-53f8-4e43-9841-8eb881a0c529	19feff9e-e556-4e05-932e-3bc8ff51f0ae	cpu_process_pct	1.0	%	component	2026-11-08T21:21:32+08:00/2026-11-08T21:21:55+08:00	min	42	0	\N	2026-11-08 21:21:55.980553+08	\N
a9d171d2-aadd-42c6-ac0a-b9b842ff2a0e	540f2fa1-53f8-4e43-9841-8eb881a0c529	19feff9e-e556-4e05-932e-3bc8ff51f0ae	cpu_process_pct	1.0	%	component	2026-11-08T21:21:32+08:00/2026-11-08T21:21:55+08:00	median	42	0.25839965	\N	2026-11-08 21:21:55.980553+08	\N
00b60f63-b80e-4993-8cb6-1f42ad51f45b	540f2fa1-53f8-4e43-9841-8eb881a0c529	19feff9e-e556-4e05-932e-3bc8ff51f0ae	cpu_process_pct	1.0	%	component	2026-11-08T21:21:32+08:00/2026-11-08T21:21:55+08:00	mean	42	0.5411010855071429	\N	2026-11-08 21:21:55.980553+08	\N
99b5ccef-ea18-4ed1-ae96-3336e7040b66	540f2fa1-53f8-4e43-9841-8eb881a0c529	19feff9e-e556-4e05-932e-3bc8ff51f0ae	cpu_process_pct	1.0	%	component	2026-11-08T21:21:32+08:00/2026-11-08T21:21:55+08:00	max	42	4.3037972	\N	2026-11-08 21:21:55.980553+08	\N
66608c2d-1658-4cc6-8d81-631a60618c12	540f2fa1-53f8-4e43-9841-8eb881a0c529	19feff9e-e556-4e05-932e-3bc8ff51f0ae	cpu_process_pct	1.0	%	component	2026-11-08T21:21:32+08:00/2026-11-08T21:21:55+08:00	p90	42	1.02511781	\N	2026-11-08 21:21:55.980553+08	\N
16827c5d-1ae3-4fe0-96bd-d64e1e787aa1	540f2fa1-53f8-4e43-9841-8eb881a0c529	19feff9e-e556-4e05-932e-3bc8ff51f0ae	cpu_global_pct	1.0	%	component	2026-11-08T21:21:32+08:00/2026-11-08T21:21:55+08:00	min	42	5.8032246	\N	2026-11-08 21:21:55.980553+08	\N
9dfa5912-a023-4bf6-ad09-7f32516de996	540f2fa1-53f8-4e43-9841-8eb881a0c529	19feff9e-e556-4e05-932e-3bc8ff51f0ae	cpu_global_pct	1.0	%	component	2026-11-08T21:21:32+08:00/2026-11-08T21:21:55+08:00	median	42	17.396984	\N	2026-11-08 21:21:55.980553+08	\N
4cb02ae1-4515-483e-b91f-279c8cb4e04a	540f2fa1-53f8-4e43-9841-8eb881a0c529	19feff9e-e556-4e05-932e-3bc8ff51f0ae	cpu_global_pct	1.0	%	component	2026-11-08T21:21:32+08:00/2026-11-08T21:21:55+08:00	mean	42	20.117124552380954	\N	2026-11-08 21:21:55.980553+08	\N
00755722-529c-43e1-b0fd-f22c64ace72a	540f2fa1-53f8-4e43-9841-8eb881a0c529	19feff9e-e556-4e05-932e-3bc8ff51f0ae	cpu_global_pct	1.0	%	component	2026-11-08T21:21:32+08:00/2026-11-08T21:21:55+08:00	max	42	52.467533	\N	2026-11-08 21:21:55.980553+08	\N
977723be-4988-4cbd-a163-d71204962d39	540f2fa1-53f8-4e43-9841-8eb881a0c529	19feff9e-e556-4e05-932e-3bc8ff51f0ae	cpu_global_pct	1.0	%	component	2026-11-08T21:21:32+08:00/2026-11-08T21:21:55+08:00	p90	42	29.1353408	\N	2026-11-08 21:21:55.980553+08	\N
cfa0d166-6cf8-420a-8a78-b629d0a32e91	540f2fa1-53f8-4e43-9841-8eb881a0c529	19feff9e-e556-4e05-932e-3bc8ff51f0ae	mem_pss_mb	1.0	MB	component	2026-11-08T21:21:32+08:00/2026-11-08T21:21:55+08:00	min	18	37.978516	\N	2026-11-08 21:21:55.980553+08	\N
720fd4f7-20c4-4005-bb4c-c98764731743	540f2fa1-53f8-4e43-9841-8eb881a0c529	19feff9e-e556-4e05-932e-3bc8ff51f0ae	mem_pss_mb	1.0	MB	component	2026-11-08T21:21:32+08:00/2026-11-08T21:21:55+08:00	median	18	85.40527	\N	2026-11-08 21:21:55.980553+08	\N
6675c211-d121-4929-9aaf-4d59b1d90237	540f2fa1-53f8-4e43-9841-8eb881a0c529	19feff9e-e556-4e05-932e-3bc8ff51f0ae	mem_pss_mb	1.0	MB	component	2026-11-08T21:21:32+08:00/2026-11-08T21:21:55+08:00	mean	18	78.15543566666666	\N	2026-11-08 21:21:55.980553+08	\N
c88ec6c4-0695-4cc1-84d3-6b205134a6a2	540f2fa1-53f8-4e43-9841-8eb881a0c529	19feff9e-e556-4e05-932e-3bc8ff51f0ae	mem_pss_mb	1.0	MB	component	2026-11-08T21:21:32+08:00/2026-11-08T21:21:55+08:00	max	18	86.06836	\N	2026-11-08 21:21:55.980553+08	\N
3df681ed-a67c-4f45-abc1-065f2588166e	540f2fa1-53f8-4e43-9841-8eb881a0c529	19feff9e-e556-4e05-932e-3bc8ff51f0ae	mem_pss_mb	1.0	MB	component	2026-11-08T21:21:32+08:00/2026-11-08T21:21:55+08:00	p90	18	85.9648436	\N	2026-11-08 21:21:55.980553+08	\N
f295c26e-b9d5-416a-8070-a92843942d42	540f2fa1-53f8-4e43-9841-8eb881a0c529	19feff9e-e556-4e05-932e-3bc8ff51f0ae	mem_privdirty_mb	1.0	MB	component	2026-11-08T21:21:32+08:00/2026-11-08T21:21:55+08:00	min	18	4.921875	\N	2026-11-08 21:21:55.980553+08	\N
94f7ccc1-52f7-4ffd-862c-443b3d90adf7	540f2fa1-53f8-4e43-9841-8eb881a0c529	19feff9e-e556-4e05-932e-3bc8ff51f0ae	mem_privdirty_mb	1.0	MB	component	2026-11-08T21:21:32+08:00/2026-11-08T21:21:55+08:00	median	18	60.990234	\N	2026-11-08 21:21:55.980553+08	\N
559a7dd8-aa52-4049-8b34-4e864dea2569	540f2fa1-53f8-4e43-9841-8eb881a0c529	19feff9e-e556-4e05-932e-3bc8ff51f0ae	mem_privdirty_mb	1.0	MB	component	2026-11-08T21:21:32+08:00/2026-11-08T21:21:55+08:00	mean	18	52.30078122222223	\N	2026-11-08 21:21:55.980553+08	\N
94e40c43-6a58-4f8c-8967-b5a40d4cee96	540f2fa1-53f8-4e43-9841-8eb881a0c529	19feff9e-e556-4e05-932e-3bc8ff51f0ae	mem_privdirty_mb	1.0	MB	component	2026-11-08T21:21:32+08:00/2026-11-08T21:21:55+08:00	max	18	62.785156	\N	2026-11-08 21:21:55.980553+08	\N
3e5bf849-683d-4d71-b4fc-cc276e682805	540f2fa1-53f8-4e43-9841-8eb881a0c529	19feff9e-e556-4e05-932e-3bc8ff51f0ae	mem_privdirty_mb	1.0	MB	component	2026-11-08T21:21:32+08:00/2026-11-08T21:21:55+08:00	p90	18	61.5917968	\N	2026-11-08 21:21:55.980553+08	\N
1a3d0e77-e3ab-4c63-99da-88aa8046a889	540f2fa1-53f8-4e43-9841-8eb881a0c529	19feff9e-e556-4e05-932e-3bc8ff51f0ae	mem_global_mb	1.0	MB	component	2026-11-08T21:21:32+08:00/2026-11-08T21:21:55+08:00	min	21	4307	\N	2026-11-08 21:21:55.980553+08	\N
237a4fe1-2e41-4448-a6cc-6d460d81b781	540f2fa1-53f8-4e43-9841-8eb881a0c529	19feff9e-e556-4e05-932e-3bc8ff51f0ae	mem_global_mb	1.0	MB	component	2026-11-08T21:21:32+08:00/2026-11-08T21:21:55+08:00	median	21	4441	\N	2026-11-08 21:21:55.980553+08	\N
37ac284b-aab8-455f-b85f-7d9ff4dd37c9	540f2fa1-53f8-4e43-9841-8eb881a0c529	19feff9e-e556-4e05-932e-3bc8ff51f0ae	mem_global_mb	1.0	MB	component	2026-11-08T21:21:32+08:00/2026-11-08T21:21:55+08:00	mean	21	4418.333333333333	\N	2026-11-08 21:21:55.980553+08	\N
d0c1fb7f-aed1-4560-a1bb-f360ede78f89	540f2fa1-53f8-4e43-9841-8eb881a0c529	19feff9e-e556-4e05-932e-3bc8ff51f0ae	mem_global_mb	1.0	MB	component	2026-11-08T21:21:32+08:00/2026-11-08T21:21:55+08:00	max	21	4457	\N	2026-11-08 21:21:55.980553+08	\N
a65fe609-55e9-470f-b862-b1fc2a963ff8	540f2fa1-53f8-4e43-9841-8eb881a0c529	19feff9e-e556-4e05-932e-3bc8ff51f0ae	mem_global_mb	1.0	MB	component	2026-11-08T21:21:32+08:00/2026-11-08T21:21:55+08:00	p90	21	4450	\N	2026-11-08 21:21:55.980553+08	\N
735fcfb8-fc09-4a4a-b67d-8158ed5c2faa	540f2fa1-53f8-4e43-9841-8eb881a0c529	19feff9e-e556-4e05-932e-3bc8ff51f0ae	fps_frame	1.0	fps	component	2026-11-08T21:21:32+08:00/2026-11-08T21:21:55+08:00	min	20	115	\N	2026-11-08 21:21:55.980553+08	\N
fa71a7b5-0ad1-4c16-b25e-19e303ce20a1	540f2fa1-53f8-4e43-9841-8eb881a0c529	19feff9e-e556-4e05-932e-3bc8ff51f0ae	fps_frame	1.0	fps	component	2026-11-08T21:21:32+08:00/2026-11-08T21:21:55+08:00	median	20	120	\N	2026-11-08 21:21:55.980553+08	\N
09e60fb7-84c8-4c35-8ddd-ea8c9cfae383	540f2fa1-53f8-4e43-9841-8eb881a0c529	19feff9e-e556-4e05-932e-3bc8ff51f0ae	fps_frame	1.0	fps	component	2026-11-08T21:21:32+08:00/2026-11-08T21:21:55+08:00	mean	20	119.45	\N	2026-11-08 21:21:55.980553+08	\N
78756a8b-caa8-41f9-80f9-72b64d0f30a0	540f2fa1-53f8-4e43-9841-8eb881a0c529	19feff9e-e556-4e05-932e-3bc8ff51f0ae	fps_frame	1.0	fps	component	2026-11-08T21:21:32+08:00/2026-11-08T21:21:55+08:00	max	20	120	\N	2026-11-08 21:21:55.980553+08	\N
c84652be-cf64-411d-8fca-839029979192	540f2fa1-53f8-4e43-9841-8eb881a0c529	19feff9e-e556-4e05-932e-3bc8ff51f0ae	fps_frame	1.0	fps	component	2026-11-08T21:21:32+08:00/2026-11-08T21:21:55+08:00	p90	20	120	\N	2026-11-08 21:21:55.980553+08	\N
74ed4c1a-109b-4ae0-bb9c-9f8d8cce9c83	540f2fa1-53f8-4e43-9841-8eb881a0c529	19feff9e-e556-4e05-932e-3bc8ff51f0ae	frame_delay_ratio_pct	1.0	%	component	2026-11-08T21:21:32+08:00/2026-11-08T21:21:55+08:00	min	20	0	\N	2026-11-08 21:21:55.980553+08	\N
ad113330-eb76-411f-9db2-5c70e967a273	540f2fa1-53f8-4e43-9841-8eb881a0c529	19feff9e-e556-4e05-932e-3bc8ff51f0ae	frame_delay_ratio_pct	1.0	%	component	2026-11-08T21:21:32+08:00/2026-11-08T21:21:55+08:00	median	20	0	\N	2026-11-08 21:21:55.980553+08	\N
3b25b132-51cc-47d4-9f7a-495fe9e3258d	540f2fa1-53f8-4e43-9841-8eb881a0c529	19feff9e-e556-4e05-932e-3bc8ff51f0ae	frame_delay_ratio_pct	1.0	%	component	2026-11-08T21:21:32+08:00/2026-11-08T21:21:55+08:00	mean	20	7.5000004	\N	2026-11-08 21:21:55.980553+08	\N
7544dbba-1449-40e6-99d5-2b78c3319c3d	540f2fa1-53f8-4e43-9841-8eb881a0c529	19feff9e-e556-4e05-932e-3bc8ff51f0ae	frame_delay_ratio_pct	1.0	%	component	2026-11-08T21:21:32+08:00/2026-11-08T21:21:55+08:00	max	20	50	\N	2026-11-08 21:21:55.980553+08	\N
4e16d7eb-f880-46d4-accc-c665387c371f	540f2fa1-53f8-4e43-9841-8eb881a0c529	19feff9e-e556-4e05-932e-3bc8ff51f0ae	frame_delay_ratio_pct	1.0	%	component	2026-11-08T21:21:32+08:00/2026-11-08T21:21:55+08:00	p90	20	33.333336	\N	2026-11-08 21:21:55.980553+08	\N
e807b803-2d3c-4119-ae03-aa6e65d6bf16	540f2fa1-53f8-4e43-9841-8eb881a0c529	19feff9e-e556-4e05-932e-3bc8ff51f0ae	frame_delay_count	1.0	次	component	2026-11-08T21:21:32+08:00/2026-11-08T21:21:55+08:00	min	20	0	\N	2026-11-08 21:21:55.980553+08	\N
19824352-5d8b-40d5-b58d-bd663989c5c8	540f2fa1-53f8-4e43-9841-8eb881a0c529	19feff9e-e556-4e05-932e-3bc8ff51f0ae	frame_delay_count	1.0	次	component	2026-11-08T21:21:32+08:00/2026-11-08T21:21:55+08:00	median	20	0	\N	2026-11-08 21:21:55.980553+08	\N
4bee3cfe-e817-4756-bf74-f91d57a59294	540f2fa1-53f8-4e43-9841-8eb881a0c529	19feff9e-e556-4e05-932e-3bc8ff51f0ae	frame_delay_count	1.0	次	component	2026-11-08T21:21:32+08:00/2026-11-08T21:21:55+08:00	mean	20	0.25	\N	2026-11-08 21:21:55.980553+08	\N
18d0c677-390c-4422-8a19-7cb3584989c3	540f2fa1-53f8-4e43-9841-8eb881a0c529	19feff9e-e556-4e05-932e-3bc8ff51f0ae	frame_delay_count	1.0	次	component	2026-11-08T21:21:32+08:00/2026-11-08T21:21:55+08:00	max	20	2	\N	2026-11-08 21:21:55.980553+08	\N
9348e37d-c31e-4696-818c-dba48e6b8122	540f2fa1-53f8-4e43-9841-8eb881a0c529	19feff9e-e556-4e05-932e-3bc8ff51f0ae	frame_delay_count	1.0	次	component	2026-11-08T21:21:32+08:00/2026-11-08T21:21:55+08:00	p90	20	1	\N	2026-11-08 21:21:55.980553+08	\N
9f79124a-7900-43ba-a585-67e1a1a9e00b	540f2fa1-53f8-4e43-9841-8eb881a0c529	19feff9e-e556-4e05-932e-3bc8ff51f0ae	frame_delay_max_ms	1.0	ms	component	2026-11-08T21:21:32+08:00/2026-11-08T21:21:55+08:00	min	20	3	\N	2026-11-08 21:21:55.980553+08	\N
c0d0af1a-b006-487e-ae80-2689a76190e1	540f2fa1-53f8-4e43-9841-8eb881a0c529	19feff9e-e556-4e05-932e-3bc8ff51f0ae	frame_delay_max_ms	1.0	ms	component	2026-11-08T21:21:32+08:00/2026-11-08T21:21:55+08:00	median	20	6	\N	2026-11-08 21:21:55.980553+08	\N
2a763de2-f24e-45d6-bef8-f91b2455a56c	540f2fa1-53f8-4e43-9841-8eb881a0c529	19feff9e-e556-4e05-932e-3bc8ff51f0ae	frame_delay_max_ms	1.0	ms	component	2026-11-08T21:21:32+08:00/2026-11-08T21:21:55+08:00	mean	20	8.75	\N	2026-11-08 21:21:55.980553+08	\N
f465e015-e107-48f0-9394-f8d903876c45	540f2fa1-53f8-4e43-9841-8eb881a0c529	19feff9e-e556-4e05-932e-3bc8ff51f0ae	frame_delay_max_ms	1.0	ms	component	2026-11-08T21:21:32+08:00/2026-11-08T21:21:55+08:00	max	20	37	\N	2026-11-08 21:21:55.980553+08	\N
1ef8e917-63c5-4627-8b86-0acc5680707c	540f2fa1-53f8-4e43-9841-8eb881a0c529	19feff9e-e556-4e05-932e-3bc8ff51f0ae	frame_delay_max_ms	1.0	ms	component	2026-11-08T21:21:32+08:00/2026-11-08T21:21:55+08:00	p90	20	18	\N	2026-11-08 21:21:55.980553+08	\N
fd58403e-d960-4c50-9b20-f2f445148c20	540f2fa1-53f8-4e43-9841-8eb881a0c529	19feff9e-e556-4e05-932e-3bc8ff51f0ae	app_jank_light_count	1.0	次	component	2026-11-08T21:21:32+08:00/2026-11-08T21:21:55+08:00	min	1	0	\N	2026-11-08 21:21:55.980553+08	\N
81a87951-9ebf-4701-b720-1d5bf9d07cb1	540f2fa1-53f8-4e43-9841-8eb881a0c529	19feff9e-e556-4e05-932e-3bc8ff51f0ae	app_jank_light_count	1.0	次	component	2026-11-08T21:21:32+08:00/2026-11-08T21:21:55+08:00	median	1	0	\N	2026-11-08 21:21:55.980553+08	\N
cb94618f-48ce-42b1-9d3a-601a388f0b1f	540f2fa1-53f8-4e43-9841-8eb881a0c529	19feff9e-e556-4e05-932e-3bc8ff51f0ae	app_jank_light_count	1.0	次	component	2026-11-08T21:21:32+08:00/2026-11-08T21:21:55+08:00	mean	1	0	\N	2026-11-08 21:21:55.980553+08	\N
05f1af0b-8d4b-48e6-9988-a2c26f0c2cbd	540f2fa1-53f8-4e43-9841-8eb881a0c529	19feff9e-e556-4e05-932e-3bc8ff51f0ae	app_jank_light_count	1.0	次	component	2026-11-08T21:21:32+08:00/2026-11-08T21:21:55+08:00	max	1	0	\N	2026-11-08 21:21:55.980553+08	\N
b809be78-33d0-4402-b85d-4a9e17fee7e5	540f2fa1-53f8-4e43-9841-8eb881a0c529	19feff9e-e556-4e05-932e-3bc8ff51f0ae	app_jank_light_count	1.0	次	component	2026-11-08T21:21:32+08:00/2026-11-08T21:21:55+08:00	p90	1	0	\N	2026-11-08 21:21:55.980553+08	\N
50fd50b5-37ac-4973-a548-2508d3b18c84	540f2fa1-53f8-4e43-9841-8eb881a0c529	19feff9e-e556-4e05-932e-3bc8ff51f0ae	app_jank_heavy_count	1.0	次	component	2026-11-08T21:21:32+08:00/2026-11-08T21:21:55+08:00	min	1	0	\N	2026-11-08 21:21:55.980553+08	\N
a625e33e-6008-4045-bc9a-d349d20fe8c3	540f2fa1-53f8-4e43-9841-8eb881a0c529	19feff9e-e556-4e05-932e-3bc8ff51f0ae	app_jank_heavy_count	1.0	次	component	2026-11-08T21:21:32+08:00/2026-11-08T21:21:55+08:00	median	1	0	\N	2026-11-08 21:21:55.980553+08	\N
7ae8be81-a4a3-4d40-8f9e-d989c963c8db	540f2fa1-53f8-4e43-9841-8eb881a0c529	19feff9e-e556-4e05-932e-3bc8ff51f0ae	app_jank_heavy_count	1.0	次	component	2026-11-08T21:21:32+08:00/2026-11-08T21:21:55+08:00	mean	1	0	\N	2026-11-08 21:21:55.980553+08	\N
cb20f049-99eb-408a-95f1-b453fa449530	540f2fa1-53f8-4e43-9841-8eb881a0c529	19feff9e-e556-4e05-932e-3bc8ff51f0ae	app_jank_heavy_count	1.0	次	component	2026-11-08T21:21:32+08:00/2026-11-08T21:21:55+08:00	max	1	0	\N	2026-11-08 21:21:55.980553+08	\N
ba778747-8553-42d7-ab01-00ba718a0e15	540f2fa1-53f8-4e43-9841-8eb881a0c529	19feff9e-e556-4e05-932e-3bc8ff51f0ae	app_jank_heavy_count	1.0	次	component	2026-11-08T21:21:32+08:00/2026-11-08T21:21:55+08:00	p90	1	0	\N	2026-11-08 21:21:55.980553+08	\N
5963e6e6-e817-4fb2-8814-772e3169d649	540f2fa1-53f8-4e43-9841-8eb881a0c529	19feff9e-e556-4e05-932e-3bc8ff51f0ae	app_jank_severe_count	1.0	次	component	2026-11-08T21:21:32+08:00/2026-11-08T21:21:55+08:00	min	1	0	\N	2026-11-08 21:21:55.980553+08	\N
10038cb0-f336-499c-8620-7fb2ab3e8402	540f2fa1-53f8-4e43-9841-8eb881a0c529	19feff9e-e556-4e05-932e-3bc8ff51f0ae	app_jank_severe_count	1.0	次	component	2026-11-08T21:21:32+08:00/2026-11-08T21:21:55+08:00	median	1	0	\N	2026-11-08 21:21:55.980553+08	\N
f37a7a3b-609b-4573-bade-ffd7cc17d9eb	540f2fa1-53f8-4e43-9841-8eb881a0c529	19feff9e-e556-4e05-932e-3bc8ff51f0ae	app_jank_severe_count	1.0	次	component	2026-11-08T21:21:32+08:00/2026-11-08T21:21:55+08:00	mean	1	0	\N	2026-11-08 21:21:55.980553+08	\N
9734c9e7-3913-472e-b329-86b4a51db52a	540f2fa1-53f8-4e43-9841-8eb881a0c529	19feff9e-e556-4e05-932e-3bc8ff51f0ae	app_jank_severe_count	1.0	次	component	2026-11-08T21:21:32+08:00/2026-11-08T21:21:55+08:00	max	1	0	\N	2026-11-08 21:21:55.980553+08	\N
b8508319-4c32-49e4-863c-1b6600429cf2	540f2fa1-53f8-4e43-9841-8eb881a0c529	19feff9e-e556-4e05-932e-3bc8ff51f0ae	app_jank_severe_count	1.0	次	component	2026-11-08T21:21:32+08:00/2026-11-08T21:21:55+08:00	p90	1	0	\N	2026-11-08 21:21:55.980553+08	\N
ac90df6b-ef8f-4550-865a-312347c6f515	540f2fa1-53f8-4e43-9841-8eb881a0c529	19feff9e-e556-4e05-932e-3bc8ff51f0ae	temp_battery_c	1.0	°C	component	2026-11-08T21:21:32+08:00/2026-11-08T21:21:55+08:00	min	9	33.8	\N	2026-11-08 21:21:55.980553+08	\N
36f6b4eb-a22a-4983-8d03-af3cebee3cf3	540f2fa1-53f8-4e43-9841-8eb881a0c529	19feff9e-e556-4e05-932e-3bc8ff51f0ae	temp_battery_c	1.0	°C	component	2026-11-08T21:21:32+08:00/2026-11-08T21:21:55+08:00	median	9	33.8	\N	2026-11-08 21:21:55.980553+08	\N
9076f61d-7b01-408b-b381-330e059c90f2	540f2fa1-53f8-4e43-9841-8eb881a0c529	19feff9e-e556-4e05-932e-3bc8ff51f0ae	temp_battery_c	1.0	°C	component	2026-11-08T21:21:32+08:00/2026-11-08T21:21:55+08:00	mean	9	33.8	\N	2026-11-08 21:21:55.980553+08	\N
5fe4b769-9721-4ce2-9439-27d99703d9b6	540f2fa1-53f8-4e43-9841-8eb881a0c529	19feff9e-e556-4e05-932e-3bc8ff51f0ae	temp_battery_c	1.0	°C	component	2026-11-08T21:21:32+08:00/2026-11-08T21:21:55+08:00	max	9	33.8	\N	2026-11-08 21:21:55.980553+08	\N
cf9f8af9-8826-43b2-87c8-52d233d00f4f	540f2fa1-53f8-4e43-9841-8eb881a0c529	19feff9e-e556-4e05-932e-3bc8ff51f0ae	temp_battery_c	1.0	°C	component	2026-11-08T21:21:32+08:00/2026-11-08T21:21:55+08:00	p90	9	33.8	\N	2026-11-08 21:21:55.980553+08	\N
60e420aa-4a57-4ac9-bd0f-9d272c55775b	540f2fa1-53f8-4e43-9841-8eb881a0c529	19feff9e-e556-4e05-932e-3bc8ff51f0ae	gpu_util_pct	1.0	%	component	2026-11-08T21:21:32+08:00/2026-11-08T21:21:55+08:00	min	9	0	\N	2026-11-08 21:21:55.980553+08	\N
6a202c36-1baa-4926-a574-40e13d50e2b0	540f2fa1-53f8-4e43-9841-8eb881a0c529	19feff9e-e556-4e05-932e-3bc8ff51f0ae	gpu_util_pct	1.0	%	component	2026-11-08T21:21:32+08:00/2026-11-08T21:21:55+08:00	median	9	1.5989414831489097	\N	2026-11-08 21:21:55.980553+08	\N
16dff6ab-b18b-48a8-bec1-3b62f8a90257	540f2fa1-53f8-4e43-9841-8eb881a0c529	19feff9e-e556-4e05-932e-3bc8ff51f0ae	gpu_util_pct	1.0	%	component	2026-11-08T21:21:32+08:00/2026-11-08T21:21:55+08:00	mean	9	2.475992325991823	\N	2026-11-08 21:21:55.980553+08	\N
5bb81a96-6ee0-4979-ade2-5a58eca2ee4d	540f2fa1-53f8-4e43-9841-8eb881a0c529	19feff9e-e556-4e05-932e-3bc8ff51f0ae	gpu_util_pct	1.0	%	component	2026-11-08T21:21:32+08:00/2026-11-08T21:21:55+08:00	max	9	4.735229654756431	\N	2026-11-08 21:21:55.980553+08	\N
782cc6f3-332e-4b61-b705-b62624e80bfc	540f2fa1-53f8-4e43-9841-8eb881a0c529	19feff9e-e556-4e05-932e-3bc8ff51f0ae	gpu_util_pct	1.0	%	component	2026-11-08T21:21:32+08:00/2026-11-08T21:21:55+08:00	p90	9	4.659307577646208	\N	2026-11-08 21:21:55.980553+08	\N
6c2d58c7-a560-498f-8a1e-965580adc10a	540f2fa1-53f8-4e43-9841-8eb881a0c529	19feff9e-e556-4e05-932e-3bc8ff51f0ae	gpu_mem_mb	1.0	MB	component	2026-11-08T21:21:32+08:00/2026-11-08T21:21:55+08:00	min	9	6.0234375	\N	2026-11-08 21:21:55.980553+08	\N
0439dbef-d247-435e-aac5-2c33315f6e5a	540f2fa1-53f8-4e43-9841-8eb881a0c529	19feff9e-e556-4e05-932e-3bc8ff51f0ae	gpu_mem_mb	1.0	MB	component	2026-11-08T21:21:32+08:00/2026-11-08T21:21:55+08:00	median	9	47.359375	\N	2026-11-08 21:21:55.980553+08	\N
afd2123e-a9cc-42d9-a078-cbf7e45f7707	540f2fa1-53f8-4e43-9841-8eb881a0c529	19feff9e-e556-4e05-932e-3bc8ff51f0ae	gpu_mem_mb	1.0	MB	component	2026-11-08T21:21:32+08:00/2026-11-08T21:21:55+08:00	mean	9	42.451388888888886	\N	2026-11-08 21:21:55.980553+08	\N
b4def2da-9c42-4ec0-8a36-c47a424588e7	540f2fa1-53f8-4e43-9841-8eb881a0c529	19feff9e-e556-4e05-932e-3bc8ff51f0ae	gpu_mem_mb	1.0	MB	component	2026-11-08T21:21:32+08:00/2026-11-08T21:21:55+08:00	max	9	47.390625	\N	2026-11-08 21:21:55.980553+08	\N
71b7486a-5e62-40a5-8706-689e5d604020	540f2fa1-53f8-4e43-9841-8eb881a0c529	19feff9e-e556-4e05-932e-3bc8ff51f0ae	gpu_mem_mb	1.0	MB	component	2026-11-08T21:21:32+08:00/2026-11-08T21:21:55+08:00	p90	9	47.365625	\N	2026-11-08 21:21:55.980553+08	\N
70cb04d2-a4aa-4bcd-bfaa-d42c79e3083c	540f2fa1-53f8-4e43-9841-8eb881a0c529	206414d0-f279-464d-894c-b351afe61c79	cpu_process_pct	1.0	%	component	2026-11-08T21:23:46+08:00/2026-11-08T21:24:08+08:00	min	41	0	\N	2026-11-08 21:24:09.471599+08	\N
aca91b37-517d-4b50-9ff9-972e1e903553	540f2fa1-53f8-4e43-9841-8eb881a0c529	206414d0-f279-464d-894c-b351afe61c79	cpu_process_pct	1.0	%	component	2026-11-08T21:23:46+08:00/2026-11-08T21:24:08+08:00	median	41	0.25316456	\N	2026-11-08 21:24:09.471599+08	\N
5d081d08-b09b-4492-8847-a276932f748f	540f2fa1-53f8-4e43-9841-8eb881a0c529	206414d0-f279-464d-894c-b351afe61c79	cpu_process_pct	1.0	%	component	2026-11-08T21:23:46+08:00/2026-11-08T21:24:08+08:00	mean	41	0.4747812231707317	\N	2026-11-08 21:24:09.471599+08	\N
6241f5e6-96b3-4716-b618-117d2f3bd9e6	540f2fa1-53f8-4e43-9841-8eb881a0c529	206414d0-f279-464d-894c-b351afe61c79	cpu_process_pct	1.0	%	component	2026-11-08T21:23:46+08:00/2026-11-08T21:24:08+08:00	max	41	4.427083	\N	2026-11-08 21:24:09.471599+08	\N
2eb6928a-b7e8-42a9-95d9-d140a01a5dbc	540f2fa1-53f8-4e43-9841-8eb881a0c529	206414d0-f279-464d-894c-b351afe61c79	cpu_process_pct	1.0	%	component	2026-11-08T21:23:46+08:00/2026-11-08T21:24:08+08:00	p90	41	1.0282776	\N	2026-11-08 21:24:09.471599+08	\N
e64f41ce-ee27-44a4-9b12-707a1a0eec1e	540f2fa1-53f8-4e43-9841-8eb881a0c529	206414d0-f279-464d-894c-b351afe61c79	cpu_global_pct	1.0	%	component	2026-11-08T21:23:46+08:00/2026-11-08T21:24:08+08:00	min	41	6.880688	\N	2026-11-08 21:24:09.471599+08	\N
572a0767-7697-4bf6-8542-3fa023eb271c	540f2fa1-53f8-4e43-9841-8eb881a0c529	206414d0-f279-464d-894c-b351afe61c79	cpu_global_pct	1.0	%	component	2026-11-08T21:23:46+08:00/2026-11-08T21:24:08+08:00	median	41	15.949368	\N	2026-11-08 21:24:09.471599+08	\N
ea992563-8395-4bf5-9d7f-d9a3ad7d43b4	540f2fa1-53f8-4e43-9841-8eb881a0c529	206414d0-f279-464d-894c-b351afe61c79	cpu_global_pct	1.0	%	component	2026-11-08T21:23:46+08:00/2026-11-08T21:24:08+08:00	mean	41	19.469681036585364	\N	2026-11-08 21:24:09.471599+08	\N
ec302801-af15-4471-b104-8b3f0cf42ccf	540f2fa1-53f8-4e43-9841-8eb881a0c529	206414d0-f279-464d-894c-b351afe61c79	cpu_global_pct	1.0	%	component	2026-11-08T21:23:46+08:00/2026-11-08T21:24:08+08:00	max	41	43.137257	\N	2026-11-08 21:24:09.471599+08	\N
4e08b30c-f8ee-4a55-bcd3-48d465a49560	540f2fa1-53f8-4e43-9841-8eb881a0c529	206414d0-f279-464d-894c-b351afe61c79	cpu_global_pct	1.0	%	component	2026-11-08T21:23:46+08:00/2026-11-08T21:24:08+08:00	p90	41	29.024391	\N	2026-11-08 21:24:09.471599+08	\N
c372a753-c63d-49b1-89d0-7cd7eae336c2	540f2fa1-53f8-4e43-9841-8eb881a0c529	206414d0-f279-464d-894c-b351afe61c79	mem_pss_mb	1.0	MB	component	2026-11-08T21:23:46+08:00/2026-11-08T21:24:08+08:00	min	15	38.23633	\N	2026-11-08 21:24:09.471599+08	\N
3761e17b-9736-495d-becb-b2433d6a5167	540f2fa1-53f8-4e43-9841-8eb881a0c529	206414d0-f279-464d-894c-b351afe61c79	mem_pss_mb	1.0	MB	component	2026-11-08T21:23:46+08:00/2026-11-08T21:24:08+08:00	median	15	85.5957	\N	2026-11-08 21:24:09.471599+08	\N
95815dcb-b7d1-44fb-ad33-0d81a79b9a7b	540f2fa1-53f8-4e43-9841-8eb881a0c529	206414d0-f279-464d-894c-b351afe61c79	mem_pss_mb	1.0	MB	component	2026-11-08T21:23:46+08:00/2026-11-08T21:24:08+08:00	mean	15	79.44095093333334	\N	2026-11-08 21:24:09.471599+08	\N
c768c2ea-bdb6-468c-9e70-e5e902d2e751	540f2fa1-53f8-4e43-9841-8eb881a0c529	206414d0-f279-464d-894c-b351afe61c79	mem_pss_mb	1.0	MB	component	2026-11-08T21:23:46+08:00/2026-11-08T21:24:08+08:00	max	15	86.115234	\N	2026-11-08 21:24:09.471599+08	\N
ff828303-32f4-45d1-9895-f7a1444ba930	540f2fa1-53f8-4e43-9841-8eb881a0c529	206414d0-f279-464d-894c-b351afe61c79	mem_pss_mb	1.0	MB	component	2026-11-08T21:23:46+08:00/2026-11-08T21:24:08+08:00	p90	15	86.0437496	\N	2026-11-08 21:24:09.471599+08	\N
de68ad73-c2a3-4b3a-9410-c7cc0356328f	540f2fa1-53f8-4e43-9841-8eb881a0c529	206414d0-f279-464d-894c-b351afe61c79	mem_privdirty_mb	1.0	MB	component	2026-11-08T21:23:46+08:00/2026-11-08T21:24:08+08:00	min	15	4.6171875	\N	2026-11-08 21:24:09.471599+08	\N
581ef199-a198-4f85-8557-7246da7ce6fa	540f2fa1-53f8-4e43-9841-8eb881a0c529	206414d0-f279-464d-894c-b351afe61c79	mem_privdirty_mb	1.0	MB	component	2026-11-08T21:23:46+08:00/2026-11-08T21:24:08+08:00	median	15	61.160156	\N	2026-11-08 21:24:09.471599+08	\N
e650317e-495b-4e1e-aff6-37c6daddca88	540f2fa1-53f8-4e43-9841-8eb881a0c529	206414d0-f279-464d-894c-b351afe61c79	mem_privdirty_mb	1.0	MB	component	2026-11-08T21:23:46+08:00/2026-11-08T21:24:08+08:00	mean	15	54.0424479	\N	2026-11-08 21:24:09.471599+08	\N
445734ce-8b37-434f-b811-391183bcbcfc	540f2fa1-53f8-4e43-9841-8eb881a0c529	206414d0-f279-464d-894c-b351afe61c79	mem_privdirty_mb	1.0	MB	component	2026-11-08T21:23:46+08:00/2026-11-08T21:24:08+08:00	max	15	62.847656	\N	2026-11-08 21:24:09.471599+08	\N
2d352e02-3a81-4e25-b3b5-340258418e72	540f2fa1-53f8-4e43-9841-8eb881a0c529	206414d0-f279-464d-894c-b351afe61c79	mem_privdirty_mb	1.0	MB	component	2026-11-08T21:23:46+08:00/2026-11-08T21:24:08+08:00	p90	15	61.646094	\N	2026-11-08 21:24:09.471599+08	\N
e3177b96-1c5a-427f-8dc9-df97962d349a	540f2fa1-53f8-4e43-9841-8eb881a0c529	206414d0-f279-464d-894c-b351afe61c79	mem_global_mb	1.0	MB	component	2026-11-08T21:23:46+08:00/2026-11-08T21:24:08+08:00	min	19	4335	\N	2026-11-08 21:24:09.471599+08	\N
976e0c19-10bd-4dc0-88b5-a48e23636dd3	540f2fa1-53f8-4e43-9841-8eb881a0c529	206414d0-f279-464d-894c-b351afe61c79	mem_global_mb	1.0	MB	component	2026-11-08T21:23:46+08:00/2026-11-08T21:24:08+08:00	median	19	4470	\N	2026-11-08 21:24:09.471599+08	\N
ac5c84ee-a39f-4746-b684-05272f29d840	540f2fa1-53f8-4e43-9841-8eb881a0c529	206414d0-f279-464d-894c-b351afe61c79	mem_global_mb	1.0	MB	component	2026-11-08T21:23:46+08:00/2026-11-08T21:24:08+08:00	mean	19	4454.210526315789	\N	2026-11-08 21:24:09.471599+08	\N
dfbf24ad-c321-4eb7-b036-f98ea2c11f57	540f2fa1-53f8-4e43-9841-8eb881a0c529	206414d0-f279-464d-894c-b351afe61c79	mem_global_mb	1.0	MB	component	2026-11-08T21:23:46+08:00/2026-11-08T21:24:08+08:00	max	19	4486	\N	2026-11-08 21:24:09.471599+08	\N
c8c97438-6ea7-4150-b8bd-d13ef90605ac	540f2fa1-53f8-4e43-9841-8eb881a0c529	206414d0-f279-464d-894c-b351afe61c79	mem_global_mb	1.0	MB	component	2026-11-08T21:23:46+08:00/2026-11-08T21:24:08+08:00	p90	19	4480.8	\N	2026-11-08 21:24:09.471599+08	\N
75f9edf7-e89d-40f1-b210-fe09b50d0424	540f2fa1-53f8-4e43-9841-8eb881a0c529	206414d0-f279-464d-894c-b351afe61c79	fps_frame	1.0	fps	component	2026-11-08T21:23:46+08:00/2026-11-08T21:24:08+08:00	min	19	115	\N	2026-11-08 21:24:09.471599+08	\N
92f1597f-7968-408a-87c8-93fd3ec16a41	540f2fa1-53f8-4e43-9841-8eb881a0c529	206414d0-f279-464d-894c-b351afe61c79	fps_frame	1.0	fps	component	2026-11-08T21:23:46+08:00/2026-11-08T21:24:08+08:00	median	19	120	\N	2026-11-08 21:24:09.471599+08	\N
d5685908-b4e8-4133-9620-39074ba65fb3	540f2fa1-53f8-4e43-9841-8eb881a0c529	206414d0-f279-464d-894c-b351afe61c79	fps_frame	1.0	fps	component	2026-11-08T21:23:46+08:00/2026-11-08T21:24:08+08:00	mean	19	119.47368421052632	\N	2026-11-08 21:24:09.471599+08	\N
eada92a8-80d2-4962-9ddc-2e94f72b2ef4	540f2fa1-53f8-4e43-9841-8eb881a0c529	206414d0-f279-464d-894c-b351afe61c79	fps_frame	1.0	fps	component	2026-11-08T21:23:46+08:00/2026-11-08T21:24:08+08:00	max	19	120	\N	2026-11-08 21:24:09.471599+08	\N
584b8810-428a-4f9a-a7ab-bd7964908244	540f2fa1-53f8-4e43-9841-8eb881a0c529	206414d0-f279-464d-894c-b351afe61c79	fps_frame	1.0	fps	component	2026-11-08T21:23:46+08:00/2026-11-08T21:24:08+08:00	p90	19	120	\N	2026-11-08 21:24:09.471599+08	\N
61274971-df02-4ab3-b460-ac3c20cf8cc5	540f2fa1-53f8-4e43-9841-8eb881a0c529	206414d0-f279-464d-894c-b351afe61c79	frame_delay_ratio_pct	1.0	%	component	2026-11-08T21:23:46+08:00/2026-11-08T21:24:08+08:00	min	19	0	\N	2026-11-08 21:24:09.471599+08	\N
00748010-44c0-4a46-8db5-a2a73de89bc9	540f2fa1-53f8-4e43-9841-8eb881a0c529	206414d0-f279-464d-894c-b351afe61c79	frame_delay_ratio_pct	1.0	%	component	2026-11-08T21:23:46+08:00/2026-11-08T21:24:08+08:00	median	19	0	\N	2026-11-08 21:24:09.471599+08	\N
addf050b-c1e0-482a-9dfd-1f0d3556805f	540f2fa1-53f8-4e43-9841-8eb881a0c529	206414d0-f279-464d-894c-b351afe61c79	frame_delay_ratio_pct	1.0	%	component	2026-11-08T21:23:46+08:00/2026-11-08T21:24:08+08:00	mean	19	10.087719578947368	\N	2026-11-08 21:24:09.471599+08	\N
f8a428a2-9fd9-463a-8cd4-ffda1ee5f78d	540f2fa1-53f8-4e43-9841-8eb881a0c529	206414d0-f279-464d-894c-b351afe61c79	frame_delay_ratio_pct	1.0	%	component	2026-11-08T21:23:46+08:00/2026-11-08T21:24:08+08:00	max	19	75	\N	2026-11-08 21:24:09.471599+08	\N
c93adaa9-6de2-4d17-9b98-228d1ba7479f	540f2fa1-53f8-4e43-9841-8eb881a0c529	206414d0-f279-464d-894c-b351afe61c79	frame_delay_ratio_pct	1.0	%	component	2026-11-08T21:23:46+08:00/2026-11-08T21:24:08+08:00	p90	19	36.66666879999999	\N	2026-11-08 21:24:09.471599+08	\N
c79462af-0342-43c7-bdfd-818b6942d21b	540f2fa1-53f8-4e43-9841-8eb881a0c529	206414d0-f279-464d-894c-b351afe61c79	frame_delay_count	1.0	次	component	2026-11-08T21:23:46+08:00/2026-11-08T21:24:08+08:00	min	19	0	\N	2026-11-08 21:24:09.471599+08	\N
399cf2b7-e53b-4604-896e-83b580347e05	540f2fa1-53f8-4e43-9841-8eb881a0c529	206414d0-f279-464d-894c-b351afe61c79	frame_delay_count	1.0	次	component	2026-11-08T21:23:46+08:00/2026-11-08T21:24:08+08:00	median	19	0	\N	2026-11-08 21:24:09.471599+08	\N
55a91357-d302-4111-8fc9-204d3bbc7f51	540f2fa1-53f8-4e43-9841-8eb881a0c529	206414d0-f279-464d-894c-b351afe61c79	frame_delay_count	1.0	次	component	2026-11-08T21:23:46+08:00/2026-11-08T21:24:08+08:00	mean	19	0.3157894736842105	\N	2026-11-08 21:24:09.471599+08	\N
f98b1d5e-e946-4d8e-a845-352d252773a1	540f2fa1-53f8-4e43-9841-8eb881a0c529	206414d0-f279-464d-894c-b351afe61c79	frame_delay_count	1.0	次	component	2026-11-08T21:23:46+08:00/2026-11-08T21:24:08+08:00	max	19	3	\N	2026-11-08 21:24:09.471599+08	\N
53a52ca8-f6bc-4a3a-95e6-0f6e6c123e97	540f2fa1-53f8-4e43-9841-8eb881a0c529	206414d0-f279-464d-894c-b351afe61c79	frame_delay_count	1.0	次	component	2026-11-08T21:23:46+08:00/2026-11-08T21:24:08+08:00	p90	19	1	\N	2026-11-08 21:24:09.471599+08	\N
746dc4d6-9ea4-4441-ba9d-72e81b62ab97	540f2fa1-53f8-4e43-9841-8eb881a0c529	206414d0-f279-464d-894c-b351afe61c79	frame_delay_max_ms	1.0	ms	component	2026-11-08T21:23:46+08:00/2026-11-08T21:24:08+08:00	min	19	5	\N	2026-11-08 21:24:09.471599+08	\N
c8fe9be7-b1cc-4be1-ad26-601a2a72d065	540f2fa1-53f8-4e43-9841-8eb881a0c529	206414d0-f279-464d-894c-b351afe61c79	frame_delay_max_ms	1.0	ms	component	2026-11-08T21:23:46+08:00/2026-11-08T21:24:08+08:00	median	19	6	\N	2026-11-08 21:24:09.471599+08	\N
d52c39f6-387d-47e3-b5a1-5bd1905e1c98	540f2fa1-53f8-4e43-9841-8eb881a0c529	206414d0-f279-464d-894c-b351afe61c79	frame_delay_max_ms	1.0	ms	component	2026-11-08T21:23:46+08:00/2026-11-08T21:24:08+08:00	mean	19	8.789473684210526	\N	2026-11-08 21:24:09.471599+08	\N
d228f82e-f8af-4d11-a6c7-1c1cc8ee0565	540f2fa1-53f8-4e43-9841-8eb881a0c529	206414d0-f279-464d-894c-b351afe61c79	frame_delay_max_ms	1.0	ms	component	2026-11-08T21:23:46+08:00/2026-11-08T21:24:08+08:00	max	19	29	\N	2026-11-08 21:24:09.471599+08	\N
22a94e83-869f-4432-88ec-55597ae7b40e	540f2fa1-53f8-4e43-9841-8eb881a0c529	206414d0-f279-464d-894c-b351afe61c79	frame_delay_max_ms	1.0	ms	component	2026-11-08T21:23:46+08:00/2026-11-08T21:24:08+08:00	p90	19	18	\N	2026-11-08 21:24:09.471599+08	\N
b5a8e2ca-b8d7-4732-8d0d-2dfa0900ceeb	540f2fa1-53f8-4e43-9841-8eb881a0c529	206414d0-f279-464d-894c-b351afe61c79	app_jank_light_count	1.0	次	component	2026-11-08T21:23:46+08:00/2026-11-08T21:24:08+08:00	min	1	0	\N	2026-11-08 21:24:09.471599+08	\N
64624e2b-316a-4934-83e5-1a3ee20ca34d	540f2fa1-53f8-4e43-9841-8eb881a0c529	206414d0-f279-464d-894c-b351afe61c79	app_jank_light_count	1.0	次	component	2026-11-08T21:23:46+08:00/2026-11-08T21:24:08+08:00	median	1	0	\N	2026-11-08 21:24:09.471599+08	\N
20961edb-b79c-4f5b-a215-44b43d2cae6f	540f2fa1-53f8-4e43-9841-8eb881a0c529	206414d0-f279-464d-894c-b351afe61c79	app_jank_light_count	1.0	次	component	2026-11-08T21:23:46+08:00/2026-11-08T21:24:08+08:00	mean	1	0	\N	2026-11-08 21:24:09.471599+08	\N
7d60c36f-2c8d-4fe5-b6da-698ed4712911	540f2fa1-53f8-4e43-9841-8eb881a0c529	206414d0-f279-464d-894c-b351afe61c79	app_jank_light_count	1.0	次	component	2026-11-08T21:23:46+08:00/2026-11-08T21:24:08+08:00	max	1	0	\N	2026-11-08 21:24:09.471599+08	\N
7e45efa6-dab1-47be-8d41-288132a0ecbb	540f2fa1-53f8-4e43-9841-8eb881a0c529	206414d0-f279-464d-894c-b351afe61c79	app_jank_light_count	1.0	次	component	2026-11-08T21:23:46+08:00/2026-11-08T21:24:08+08:00	p90	1	0	\N	2026-11-08 21:24:09.471599+08	\N
384fa1d6-6ca1-48e6-bbf9-1f684769069a	540f2fa1-53f8-4e43-9841-8eb881a0c529	206414d0-f279-464d-894c-b351afe61c79	app_jank_heavy_count	1.0	次	component	2026-11-08T21:23:46+08:00/2026-11-08T21:24:08+08:00	min	1	0	\N	2026-11-08 21:24:09.471599+08	\N
7d088097-cad4-41e6-80f7-b335709edb94	540f2fa1-53f8-4e43-9841-8eb881a0c529	206414d0-f279-464d-894c-b351afe61c79	app_jank_heavy_count	1.0	次	component	2026-11-08T21:23:46+08:00/2026-11-08T21:24:08+08:00	median	1	0	\N	2026-11-08 21:24:09.471599+08	\N
5f0ff821-cdd2-4305-bca8-e666bc3dc97b	540f2fa1-53f8-4e43-9841-8eb881a0c529	206414d0-f279-464d-894c-b351afe61c79	app_jank_heavy_count	1.0	次	component	2026-11-08T21:23:46+08:00/2026-11-08T21:24:08+08:00	mean	1	0	\N	2026-11-08 21:24:09.471599+08	\N
11f49725-6a7b-49db-9459-b825542a5efd	540f2fa1-53f8-4e43-9841-8eb881a0c529	206414d0-f279-464d-894c-b351afe61c79	app_jank_heavy_count	1.0	次	component	2026-11-08T21:23:46+08:00/2026-11-08T21:24:08+08:00	max	1	0	\N	2026-11-08 21:24:09.471599+08	\N
0ccc0263-f6e3-4c82-ade8-58ef30757cad	540f2fa1-53f8-4e43-9841-8eb881a0c529	206414d0-f279-464d-894c-b351afe61c79	app_jank_heavy_count	1.0	次	component	2026-11-08T21:23:46+08:00/2026-11-08T21:24:08+08:00	p90	1	0	\N	2026-11-08 21:24:09.471599+08	\N
f72e70bf-4267-422c-8897-5ab308e5a0a6	540f2fa1-53f8-4e43-9841-8eb881a0c529	206414d0-f279-464d-894c-b351afe61c79	app_jank_severe_count	1.0	次	component	2026-11-08T21:23:46+08:00/2026-11-08T21:24:08+08:00	min	1	0	\N	2026-11-08 21:24:09.471599+08	\N
07a56fe8-931d-4e84-84d7-1c71a0b1c72d	540f2fa1-53f8-4e43-9841-8eb881a0c529	206414d0-f279-464d-894c-b351afe61c79	app_jank_severe_count	1.0	次	component	2026-11-08T21:23:46+08:00/2026-11-08T21:24:08+08:00	median	1	0	\N	2026-11-08 21:24:09.471599+08	\N
58981de6-3242-4d95-aa05-0e6442820f55	540f2fa1-53f8-4e43-9841-8eb881a0c529	206414d0-f279-464d-894c-b351afe61c79	app_jank_severe_count	1.0	次	component	2026-11-08T21:23:46+08:00/2026-11-08T21:24:08+08:00	mean	1	0	\N	2026-11-08 21:24:09.471599+08	\N
5b553999-1639-48e5-9eb2-8ab62279a601	540f2fa1-53f8-4e43-9841-8eb881a0c529	206414d0-f279-464d-894c-b351afe61c79	app_jank_severe_count	1.0	次	component	2026-11-08T21:23:46+08:00/2026-11-08T21:24:08+08:00	max	1	0	\N	2026-11-08 21:24:09.471599+08	\N
b104447d-5e42-43d7-8037-6d101fc341c2	540f2fa1-53f8-4e43-9841-8eb881a0c529	206414d0-f279-464d-894c-b351afe61c79	app_jank_severe_count	1.0	次	component	2026-11-08T21:23:46+08:00/2026-11-08T21:24:08+08:00	p90	1	0	\N	2026-11-08 21:24:09.471599+08	\N
32db9860-d227-4a8f-8223-0bcd5a92c9ad	540f2fa1-53f8-4e43-9841-8eb881a0c529	206414d0-f279-464d-894c-b351afe61c79	temp_battery_c	1.0	°C	component	2026-11-08T21:23:46+08:00/2026-11-08T21:24:08+08:00	min	9	33.9	\N	2026-11-08 21:24:09.471599+08	\N
b8f7f5eb-d516-400c-b59d-b39802ee37d0	540f2fa1-53f8-4e43-9841-8eb881a0c529	206414d0-f279-464d-894c-b351afe61c79	temp_battery_c	1.0	°C	component	2026-11-08T21:23:46+08:00/2026-11-08T21:24:08+08:00	median	9	33.9	\N	2026-11-08 21:24:09.471599+08	\N
f197eed1-e491-4912-9a94-8e165f29011f	540f2fa1-53f8-4e43-9841-8eb881a0c529	206414d0-f279-464d-894c-b351afe61c79	temp_battery_c	1.0	°C	component	2026-11-08T21:23:46+08:00/2026-11-08T21:24:08+08:00	mean	9	33.9	\N	2026-11-08 21:24:09.471599+08	\N
07fbdb60-a8d3-4154-9e37-690d58d5dfb1	540f2fa1-53f8-4e43-9841-8eb881a0c529	206414d0-f279-464d-894c-b351afe61c79	temp_battery_c	1.0	°C	component	2026-11-08T21:23:46+08:00/2026-11-08T21:24:08+08:00	max	9	33.9	\N	2026-11-08 21:24:09.471599+08	\N
d444f261-a1fb-4f1a-83a3-972fde3e07d4	540f2fa1-53f8-4e43-9841-8eb881a0c529	206414d0-f279-464d-894c-b351afe61c79	temp_battery_c	1.0	°C	component	2026-11-08T21:23:46+08:00/2026-11-08T21:24:08+08:00	p90	9	33.9	\N	2026-11-08 21:24:09.471599+08	\N
4ba52459-974c-4f50-998d-c283f3adf86e	540f2fa1-53f8-4e43-9841-8eb881a0c529	206414d0-f279-464d-894c-b351afe61c79	gpu_util_pct	1.0	%	component	2026-11-08T21:23:46+08:00/2026-11-08T21:24:08+08:00	min	9	0	\N	2026-11-08 21:24:09.471599+08	\N
81c581c9-9e07-49ca-85d6-ce9e44b7ceff	540f2fa1-53f8-4e43-9841-8eb881a0c529	206414d0-f279-464d-894c-b351afe61c79	gpu_util_pct	1.0	%	component	2026-11-08T21:23:46+08:00/2026-11-08T21:24:08+08:00	median	9	1.656243993017508	\N	2026-11-08 21:24:09.471599+08	\N
f1ab5969-5ab0-4883-bd64-d6b9775566bc	540f2fa1-53f8-4e43-9841-8eb881a0c529	206414d0-f279-464d-894c-b351afe61c79	gpu_util_pct	1.0	%	component	2026-11-08T21:23:46+08:00/2026-11-08T21:24:08+08:00	mean	9	2.8734263819869335	\N	2026-11-08 21:24:09.471599+08	\N
677d4894-6d18-49e7-8db1-d578f7ed8d4a	540f2fa1-53f8-4e43-9841-8eb881a0c529	206414d0-f279-464d-894c-b351afe61c79	gpu_util_pct	1.0	%	component	2026-11-08T21:23:46+08:00/2026-11-08T21:24:08+08:00	max	9	7.512594558831735	\N	2026-11-08 21:24:09.471599+08	\N
6a560890-4f6d-4e86-842e-8658b4e52ea1	540f2fa1-53f8-4e43-9841-8eb881a0c529	206414d0-f279-464d-894c-b351afe61c79	gpu_util_pct	1.0	%	component	2026-11-08T21:23:46+08:00/2026-11-08T21:24:08+08:00	p90	9	5.819200134818141	\N	2026-11-08 21:24:09.471599+08	\N
aaa1a515-9d08-4a2e-a05a-50b3647be502	540f2fa1-53f8-4e43-9841-8eb881a0c529	206414d0-f279-464d-894c-b351afe61c79	gpu_mem_mb	1.0	MB	component	2026-11-08T21:23:46+08:00/2026-11-08T21:24:08+08:00	min	9	6.0234375	\N	2026-11-08 21:24:09.471599+08	\N
f325c0d1-9e32-4685-881c-e2f00c47615d	540f2fa1-53f8-4e43-9841-8eb881a0c529	206414d0-f279-464d-894c-b351afe61c79	gpu_mem_mb	1.0	MB	component	2026-11-08T21:23:46+08:00/2026-11-08T21:24:08+08:00	median	9	47.359375	\N	2026-11-08 21:24:09.471599+08	\N
996b7ad3-6084-4545-b552-77079be38c84	540f2fa1-53f8-4e43-9841-8eb881a0c529	206414d0-f279-464d-894c-b351afe61c79	gpu_mem_mb	1.0	MB	component	2026-11-08T21:23:46+08:00/2026-11-08T21:24:08+08:00	mean	9	42.451388888888886	\N	2026-11-08 21:24:09.471599+08	\N
5929847a-5cb9-4193-bb2e-4365dbf1c1e3	540f2fa1-53f8-4e43-9841-8eb881a0c529	206414d0-f279-464d-894c-b351afe61c79	gpu_mem_mb	1.0	MB	component	2026-11-08T21:23:46+08:00/2026-11-08T21:24:08+08:00	max	9	47.390625	\N	2026-11-08 21:24:09.471599+08	\N
24c395a5-07ac-4dfb-9c1d-1a2082abedd3	540f2fa1-53f8-4e43-9841-8eb881a0c529	206414d0-f279-464d-894c-b351afe61c79	gpu_mem_mb	1.0	MB	component	2026-11-08T21:23:46+08:00/2026-11-08T21:24:08+08:00	p90	9	47.365625	\N	2026-11-08 21:24:09.471599+08	\N
\.


--
-- Data for Name: project_members; Type: TABLE DATA; Schema: public; Owner: testdock
--

COPY public.project_members (id, project_id, identity_issuer, identity_subject, role, created_at) FROM stdin;
\.


--
-- Data for Name: projects; Type: TABLE DATA; Schema: public; Owner: testdock
--

COPY public.projects (id, code, name, archived_at, created_at, origin) FROM stdin;
540f2fa1-53f8-4e43-9841-8eb881a0c529	delivery-acceptance	交付验收项目	\N	2026-11-08 20:02:00.094623+08	\N
5000b728-a110-4878-bcc1-41725ae5603b	context-b	context-project-b	\N	2026-11-08 21:27:57.751801+08	\N
6b633466-73ee-47d2-9798-ab21021efe4c	long-name-proj	超长显示名称验证用项目名称ABCDEFGHIJKLMNOPQRSTUVWXYLONGLABEL0123456789	\N	2026-11-08 21:43:28.635345+08	\N
\.


--
-- Data for Name: resource_leases; Type: TABLE DATA; Schema: public; Owner: testdock
--

COPY public.resource_leases (id, project_id, resource_id, run_id, debug_session_id, fencing_token, holder_id, expires_at, released_at, release_reason, created_at, check_id) FROM stdin;
fdd58f86-5f86-4270-b52c-b2feec678a46	540f2fa1-53f8-4e43-9841-8eb881a0c529	fab1ee61-4ece-4fc5-92bc-4bc0b13427a2	\N	\N	1	web	2026-11-08 20:11:31.353922+08	2026-11-08 20:11:01.353922+08	identity_complete	2026-11-08 20:11:01.353922+08	b1bd262e-abbd-4fec-8442-c97aa27bc0fa
da4bb721-daf1-408f-8e58-9777426ec4cb	540f2fa1-53f8-4e43-9841-8eb881a0c529	fab1ee61-4ece-4fc5-92bc-4bc0b13427a2	8dd151a4-cfdb-45be-8775-94a84b86c834	\N	2	dispatcher:16624	2026-11-08 20:20:08.629475+08	2026-11-08 20:18:08.719638+08	run_finished	2026-11-08 20:17:48.262323+08	\N
9b3caa55-161b-4684-980c-3ea64e89f344	540f2fa1-53f8-4e43-9841-8eb881a0c529	fab1ee61-4ece-4fc5-92bc-4bc0b13427a2	\N	15b62103-1625-4c01-bcae-9d0bf36bdba9	12	web-client	2026-11-08 21:27:41.266835+08	2026-11-08 21:25:45.171387+08	client_closed	2026-11-08 21:24:11.039493+08	\N
e22db3d3-d07b-4f87-bc6d-be155a1e2d15	540f2fa1-53f8-4e43-9841-8eb881a0c529	fab1ee61-4ece-4fc5-92bc-4bc0b13427a2	ba117777-b04d-48e0-ba3d-7af289d66244	\N	3	dispatcher:23932	2026-11-08 20:48:22.219814+08	2026-11-08 20:46:22.70876+08	run_finished	2026-11-08 20:46:01.712036+08	\N
eebae986-997a-4f3c-ac9a-ca3e045c67c6	540f2fa1-53f8-4e43-9841-8eb881a0c529	fab1ee61-4ece-4fc5-92bc-4bc0b13427a2	2e43d5e0-1374-4c71-8b4d-586ca1033e5a	\N	13	dispatcher:23932	2026-11-08 21:27:55.678858+08	2026-11-08 21:25:56.358498+08	cancel_requested	2026-11-08 21:25:55.678858+08	\N
03461d64-049b-479b-9dfc-6e59875f3747	540f2fa1-53f8-4e43-9841-8eb881a0c529	fab1ee61-4ece-4fc5-92bc-4bc0b13427a2	7ca839a0-d955-4a7e-aa64-290382c63453	\N	4	dispatcher:23932	2026-11-08 20:55:28.850399+08	2026-11-08 20:53:33.424816+08	run_finished	2026-11-08 20:52:58.50594+08	\N
5c5e5976-855d-4566-99a3-7b9626544d0d	540f2fa1-53f8-4e43-9841-8eb881a0c529	fab1ee61-4ece-4fc5-92bc-4bc0b13427a2	ec832d64-466a-437a-8dcc-6a2efb9eede6	\N	5	dispatcher:23932	2026-11-08 21:14:41.836967+08	2026-11-08 21:12:46.205621+08	run_finished	2026-11-08 21:12:21.511259+08	\N
5326d2cf-f970-4a46-b983-10bea354c87c	540f2fa1-53f8-4e43-9841-8eb881a0c529	fab1ee61-4ece-4fc5-92bc-4bc0b13427a2	b7899bcf-7d37-48ec-81be-0407340d0b03	\N	6	dispatcher:23932	2026-11-08 21:17:08.24699+08	2026-11-08 21:15:15.668193+08	cancel_requested	2026-11-08 21:14:57.886158+08	\N
b43753d9-ded2-4526-b8b7-4942753409f7	540f2fa1-53f8-4e43-9841-8eb881a0c529	fab1ee61-4ece-4fc5-92bc-4bc0b13427a2	2b814545-aada-4196-90ae-706dbbaf4d76	\N	7	dispatcher:23932	2026-11-08 21:18:56.602096+08	2026-11-08 21:17:03.102559+08	run_finished	2026-11-08 21:16:36.281681+08	\N
681dd812-3a55-4055-ace4-74e686d018c1	540f2fa1-53f8-4e43-9841-8eb881a0c529	fab1ee61-4ece-4fc5-92bc-4bc0b13427a2	\N	9319ff19-4689-4652-86e8-57e4900a92f1	8	web-client	2026-11-08 21:23:09.230006+08	2026-11-08 21:21:11.376485+08	client_closed	2026-11-08 21:18:38.879955+08	\N
4e1944b3-728e-4d9a-90ce-b5dbf6fa93ac	540f2fa1-53f8-4e43-9841-8eb881a0c529	fab1ee61-4ece-4fc5-92bc-4bc0b13427a2	99e0459d-5d6d-40ec-9d33-7d4848664a0f	\N	9	dispatcher:23932	2026-11-08 21:23:51.386265+08	2026-11-08 21:21:55.980553+08	run_finished	2026-11-08 21:21:30.993523+08	\N
51903e1c-f845-44b7-906e-ebcc68c7cf18	540f2fa1-53f8-4e43-9841-8eb881a0c529	fab1ee61-4ece-4fc5-92bc-4bc0b13427a2	\N	705f9c1c-57f2-4e20-8df9-3f6c244260ac	10	web-client	2026-11-08 21:25:34.569949+08	2026-11-08 21:23:43.562196+08	client_closed	2026-11-08 21:22:04.362634+08	\N
3a046409-54e6-4158-8757-6a519b550022	540f2fa1-53f8-4e43-9841-8eb881a0c529	fab1ee61-4ece-4fc5-92bc-4bc0b13427a2	d8c1ea76-e45d-4629-8152-bb2697af04f0	\N	11	dispatcher:23932	2026-11-08 21:26:05.613645+08	2026-11-08 21:24:09.471599+08	run_finished	2026-11-08 21:23:45.269276+08	\N
\.


--
-- Data for Name: resource_profiles; Type: TABLE DATA; Schema: public; Owner: testdock
--

COPY public.resource_profiles (id, project_id, platform, name, fingerprint, spec, created_at) FROM stdin;
f2cac493-a152-47fb-b25a-fa7d5672dc85	540f2fa1-53f8-4e43-9841-8eb881a0c529	android	Xiaomi 2206123SC / Android 14 / 1080x2400	57482cde2c88989f8dfe23b2a6f986579100666310cfda91e0920f425537c804	{"model": "2206123sc", "os_name": "Android", "os_version": "14", "screen_resolution": "1080x2400"}	2026-11-08 20:04:08.667609+08
\.


--
-- Data for Name: run_components; Type: TABLE DATA; Schema: public; Owner: testdock
--

COPY public.run_components (id, project_id, run_id, kind, adapter_key, adapter_version, external_run_id, state, outcome, summary, created_at, reason_code) FROM stdin;
3c13d901-4633-4b88-9dc3-da5620086662	540f2fa1-53f8-4e43-9841-8eb881a0c529	8dd151a4-cfdb-45be-8775-94a84b86c834	ui	mobile_auto	1	\N	completed	failed	{}	2026-11-08 20:18:08.719638+08	\N
79752cae-37e0-45dc-9f62-25b95c075f10	540f2fa1-53f8-4e43-9841-8eb881a0c529	ba117777-b04d-48e0-ba3d-7af289d66244	ui	mobile_auto	1	\N	completed	failed	{}	2026-11-08 20:46:22.70876+08	\N
55e43783-2e99-4ba6-9a48-53d7221878cb	540f2fa1-53f8-4e43-9841-8eb881a0c529	7ca839a0-d955-4a7e-aa64-290382c63453	performance	mobile_perf	1	\N	completed	not_tested	{"gpu": {"source": "dumpsys_and_sysfs", "enabled": true, "degraded": [], "gpuSource": "kgsl_gpubusy"}, "jank": {"granularity": "per_sampling_window", "sourceMetric": "frame_delay_max_ms", "thresholdsMs": {"heavy": 300.0, "light": 100.0, "severe": 700.0}}, "items": ["CPU", "Memory", "FPS"], "marks": [], "runId": "7ca839a0-d955-4a7e-aa64-290382c63453", "events": [], "serial": "749622c9", "series": {"fps_frame": {"unit": "fps", "points": [[0.0, 118.0], [1.003, 118.0], [2.005, 118.0], [3.007, 118.0], [4.009, 118.0], [5.011, 118.0], [6.013, 118.0], [7.018, 118.0], [8.02, 118.0], [9.024, 118.0], [10.025, 118.0], [11.029, 118.0], [12.032, 118.0], [13.039, 118.0], [14.043, 118.0], [15.043, 118.0], [16.047, 118.0], [17.048, 118.0], [18.051, 118.0], [19.054, 118.0], [20.057, 118.0], [21.059, 118.0], [22.059, 118.0], [23.061, 118.0], [24.062, 118.0], [25.066, 118.0], [26.069, 118.0], [27.075, 118.0], [28.077, 118.0], [29.084, 118.0], [30.09, 118.0], [31.091, 118.0]], "source": "solo_pi", "labelEn": "Frame rate", "labelZh": "帧率"}, "gpu_mem_mb": {"unit": "MB", "points": [[0.0, 4.75], [2.0, 4.75], [4.0, 4.75], [6.0, 4.75], [9.0, 4.75], [11.0, 4.75], [13.0, 4.75], [15.0, 4.75], [17.0, 4.75], [19.0, 4.75], [21.0, 4.75], [24.0, 4.75], [26.0, 4.75], [28.0, 4.75], [30.0, 4.75]], "source": "pc_supplement", "labelEn": "App GPU memory", "labelZh": "应用GPU显存"}, "mem_pss_mb": {"unit": "MB", "points": [[0.0, 39.822266], [0.961, 45.335938], [1.941, 45.56543], [2.941, 45.55371], [3.965, 45.54492], [4.959, 45.569336], [5.959, 45.5459], [7.015, 39.277344], [7.97, 45.45215], [8.988, 45.47461], [9.981, 45.45215], [10.986, 45.475586], [11.975, 45.463867], [13.016, 45.475586], [14.01, 45.470703], [15.016, 45.495117], [16.005, 45.47168], [17.006, 45.475586], [18.029, 45.461914], [19.044, 45.48047], [20.031, 45.44922], [21.043, 45.453125], [22.013, 45.466797], [23.046, 45.47461], [24.051, 45.46582], [25.029, 45.45117], [26.039, 45.466797], [27.036, 45.46875], [28.046, 45.466797], [29.068, 45.45117]], "source": "solo_pi", "labelEn": "Process PSS memory", "labelZh": "应用PSS内存"}, "gpu_util_pct": {"unit": "%", "points": [[0.0, 6.178479999053303], [2.0, 3.872196002481996], [4.0, 0.0], [6.0, 0.0], [9.0, 0.0], [11.0, 0.0], [13.0, 0.0], [15.0, 0.0], [17.0, 0.0], [19.0, 0.0], [21.0, 0.0], [24.0, 0.0], [26.0, 0.0], [28.0, 0.0], [30.0, 0.0]], "source": "pc_supplement", "labelEn": "GPU utilization", "labelZh": "GPU占用"}, "mem_global_mb": {"unit": "MB", "points": [[0.0, 4149.0], [1.217, 4161.0], [2.179, 4167.0], [3.159, 4169.0], [4.158, 4151.0], [5.182, 4160.0], [6.176, 4166.0], [7.177, 4170.0], [8.232, 4147.0], [9.187, 4153.0], [10.205, 4165.0], [11.198, 4166.0], [12.203, 4152.0], [13.192, 4157.0], [14.233, 4159.0], [15.227, 4169.0], [16.233, 4169.0], [17.222, 4151.0], [18.223, 4154.0], [19.246, 4152.0], [20.261, 4169.0], [21.249, 4175.0], [22.26, 4156.0], [23.23, 4166.0], [24.263, 4167.0], [25.268, 4178.0], [26.246, 4159.0], [27.256, 4165.0], [28.253, 4175.0], [29.263, 4177.0], [30.285, 4164.0], [31.159, 4170.0]], "source": "solo_pi", "labelEn": "Global memory usage", "labelZh": "全局内存占用"}, "cpu_global_pct": {"unit": "%", "points": [[0.0, 10.3274555], [0.496, 16.243654], [1.0, 4.556962], [1.493, 14.030612], [2.015, 9.158416], [2.506, 12.373737], [2.993, 12.564102], [3.507, 12.5], [3.995, 9.043927], [4.506, 25.552826], [5.007, 8.5], [5.496, 13.766233], [6.004, 6.203474], [6.513, 20.448877], [7.016, 9.774436], [7.518, 14.536341], [8.021, 6.075949], [8.509, 14.936708], [9.02, 11.838791], [9.51, 19.280205], [10.022, 11.881188], [10.526, 12.878788], [11.02, 9.6446705], [11.523, 7.035176], [12.027, 12.030075], [12.55, 12.342569], [13.049, 6.766917], [13.573, 17.28395], [14.047, 16.284986], [14.571, 28.967255], [15.062, 17.25], [15.599, 10.837439], [16.068, 17.662338], [16.58, 18.508997], [17.058, 6.4837904], [17.571, 18.159204], [18.075, 8.483291], [18.568, 16.666666], [19.048, 18.62245], [19.597, 25.853659], [20.076, 21.538462], [20.554, 21.818182], [21.077, 8.353808], [21.567, 14.536341], [22.078, 12.562814], [22.568, 13.819096], [23.08, 15.909091], [23.576, 14.030612], [24.056, 17.692308], [24.581, 22.00489], [25.087, 20.199501], [25.583, 10.714286], [26.083, 12.1890545], [26.596, 13.316583], [27.107, 17.75], [27.592, 13.69509], [28.083, 14.141414], [28.633, 8.872902], [29.118, 22.727272], [29.637, 25.806452], [30.098, 34.031414]], "source": "solo_pi", "labelEn": "Global CPU usage", "labelZh": "全局CPU占用"}, "temp_battery_c": {"unit": "°C", "points": [[0.0, 32.8], [2.0, 32.8], [4.0, 32.8], [6.0, 32.8], [9.0, 32.8], [11.0, 32.8], [13.0, 32.8], [15.0, 32.8], [17.0, 32.8], [19.0, 32.8], [21.0, 32.8], [24.0, 32.8], [26.0, 32.8], [28.0, 32.8], [30.0, 32.8]], "source": "pc_supplement", "labelEn": "Battery temperature", "labelZh": "电池温度"}, "cpu_process_pct": {"unit": "%", "points": [[0.0, 0.0], [0.496, 3.8071065], [1.0, 0.0], [1.493, 3.3163264], [2.015, 0.24752475], [2.506, 2.5252526], [2.993, 0.51282054], [3.507, 3.25], [3.995, 0.0], [4.506, 3.194103], [5.007, 0.5], [5.496, 3.116883], [6.004, 0.0], [6.513, 2.9925187], [7.016, 0.5012531], [7.518, 4.511278], [8.021, 0.0], [8.509, 3.2911394], [9.02, 0.25188917], [9.51, 2.8277636], [10.022, 0.4950495], [10.526, 3.030303], [11.02, 0.2538071], [11.523, 2.7638192], [12.027, 0.7518797], [12.55, 2.7707808], [13.049, 0.0], [13.573, 2.9629629], [14.047, 0.0], [14.571, 3.2745593], [15.062, 0.25], [15.599, 2.955665], [16.068, 0.25974026], [16.58, 3.084833], [17.058, 0.0], [17.571, 2.7363186], [18.075, 0.0], [18.568, 3.0769231], [19.048, 0.25510204], [19.597, 2.682927], [20.076, 0.51282054], [20.554, 2.857143], [21.077, 0.0], [21.567, 3.2581453], [22.078, 0.2512563], [22.568, 2.7638192], [23.08, 0.25252524], [23.576, 3.0612245], [24.056, 0.25641027], [24.581, 3.178484], [25.087, 0.24937657], [25.583, 2.8061223], [26.083, 0.24875621], [26.596, 2.7638192], [27.107, 0.5], [27.592, 3.1007752], [28.083, 0.25252524], [28.633, 2.3980815], [29.118, 0.25252524], [29.637, 2.9776676], [30.098, 0.5235602]], "source": "solo_pi", "labelEn": "Process CPU usage", "labelZh": "应用进程CPU占用"}, "mem_privdirty_mb": {"unit": "MB", "points": [[0.0, 21.988281], [0.961, 20.648438], [1.941, 20.660156], [2.941, 20.648438], [3.965, 20.640625], [4.959, 20.664062], [5.959, 20.640625], [7.015, 6.2070312], [7.97, 8.6328125], [8.988, 8.675781], [9.981, 8.6796875], [10.986, 8.703125], [11.975, 8.730469], [13.016, 8.746094], [14.01, 8.746094], [15.016, 8.7734375], [16.005, 8.75], [17.006, 8.753906], [18.029, 8.753906], [19.044, 9.0078125], [20.032, 8.984375], [21.043, 8.996094], [22.013, 9.015625], [23.046, 9.046875], [24.051, 9.0390625], [25.029, 9.0234375], [26.039, 9.0390625], [27.036, 9.046875], [28.046, 9.042969], [29.068, 9.0390625]], "source": "solo_pi", "labelEn": "Process PrivateDirty memory", "labelZh": "应用PrivateDirty内存"}, "frame_delay_count": {"unit": "次", "points": [[0.0, 2.0], [1.003, 2.0], [2.005, 2.0], [3.007, 2.0], [4.009, 2.0], [5.011, 2.0], [6.013, 2.0], [7.018, 2.0], [8.02, 2.0], [9.024, 2.0], [10.025, 2.0], [11.029, 2.0], [12.032, 2.0], [13.039, 2.0], [14.043, 2.0], [15.043, 2.0], [16.047, 2.0], [17.048, 2.0], [18.051, 2.0], [19.054, 2.0], [20.057, 2.0], [21.059, 2.0], [22.059, 2.0], [23.061, 2.0], [24.062, 2.0], [25.066, 2.0], [26.069, 2.0], [27.075, 2.0], [28.077, 2.0], [29.084, 2.0], [30.09, 2.0], [31.091, 2.0]], "source": "solo_pi", "labelEn": "Frame delay count", "labelZh": "帧延迟次数"}, "frame_delay_max_ms": {"unit": "ms", "points": [[0.0, 14.0], [1.003, 14.0], [2.005, 14.0], [3.007, 14.0], [4.009, 14.0], [5.011, 14.0], [6.013, 14.0], [7.018, 14.0], [8.02, 14.0], [9.024, 14.0], [10.025, 14.0], [11.029, 14.0], [12.032, 14.0], [13.039, 14.0], [14.043, 14.0], [15.043, 14.0], [16.047, 14.0], [17.048, 14.0], [18.051, 14.0], [19.054, 14.0], [20.057, 14.0], [21.059, 14.0], [22.059, 14.0], [23.061, 14.0], [24.062, 14.0], [25.066, 14.0], [26.069, 14.0], [27.075, 14.0], [28.077, 14.0], [29.084, 14.0], [30.09, 14.0], [31.091, 14.0]], "source": "solo_pi", "labelEn": "Max frame delay", "labelZh": "最长帧延迟"}, "frame_delay_ratio_pct": {"unit": "%", "points": [[0.0, 66.66667], [1.003, 66.66667], [2.005, 66.66667], [3.007, 66.66667], [4.009, 66.66667], [5.011, 66.66667], [6.013, 66.66667], [7.018, 66.66667], [8.02, 66.66667], [9.024, 66.66667], [10.025, 66.66667], [11.029, 66.66667], [12.032, 66.66667], [13.039, 66.66667], [14.043, 66.66667], [15.043, 66.66667], [16.047, 66.66667], [17.048, 66.66667], [18.051, 66.66667], [19.054, 66.66667], [20.057, 66.66667], [21.059, 66.66667], [22.059, 66.66667], [23.061, 66.66667], [24.062, 66.66667], [25.066, 66.66667], [26.069, 66.66667], [27.075, 66.66667], [28.077, 66.66667], [29.084, 66.66667], [30.09, 66.66667], [31.091, 66.66667]], "source": "solo_pi", "labelEn": "Frame delay ratio", "labelZh": "帧延迟占比"}}, "target": "com.miui.calculator", "startup": null, "artifacts": ["D:\\\\workspace\\\\claudecode-test\\\\testplat-auto\\\\.runtime\\\\rr-verify\\\\data\\\\artifacts\\\\7ca839a0-d955-4a7e-aa64-290382c63453\\\\perf\\\\7ca839a0-d955-4a7e-aa64-290382c63453\\\\artifacts\\\\app_process-main-20746_CPU_4ab0dda64ef0ee99_1794142381927_1794142413586.csv", "D:\\\\workspace\\\\claudecode-test\\\\testplat-auto\\\\.runtime\\\\rr-verify\\\\data\\\\artifacts\\\\7ca839a0-d955-4a7e-aa64-290382c63453\\\\perf\\\\7ca839a0-d955-4a7e-aa64-290382c63453\\\\artifacts\\\\fps_FPS_7f0cfdad4bb20c28_1794142381927_1794142413589.csv", "D:\\\\workspace\\\\claudecode-test\\\\testplat-auto\\\\.runtime\\\\rr-verify\\\\data\\\\artifacts\\\\7ca839a0-d955-4a7e-aa64-290382c63453\\\\perf\\\\7ca839a0-d955-4a7e-aa64-290382c63453\\\\artifacts\\\\frame_delay_count_FPS_818e82e5512ee305_1794142381927_1794142413589.csv", "D:\\\\workspace\\\\claudecode-test\\\\testplat-auto\\\\.runtime\\\\rr-verify\\\\data\\\\artifacts\\\\7ca839a0-d955-4a7e-aa64-290382c63453\\\\perf\\\\7ca839a0-d955-4a7e-aa64-290382c63453\\\\artifacts\\\\frame_delay_max_FPS_2bd2769d504d958e_1794142381927_1794142413589.csv", "D:\\\\workspace\\\\claudecode-test\\\\testplat-auto\\\\.runtime\\\\rr-verify\\\\data\\\\artifacts\\\\7ca839a0-d955-4a7e-aa64-290382c63453\\\\perf\\\\7ca839a0-d955-4a7e-aa64-290382c63453\\\\artifacts\\\\frame_delay_ratio_FPS_e87078755f8aba34_1794142381927_1794142413589.csv", "D:\\\\workspace\\\\claudecode-test\\\\testplat-auto\\\\.runtime\\\\rr-verify\\\\data\\\\artifacts\\\\7ca839a0-d955-4a7e-aa64-290382c63453\\\\perf\\\\7ca839a0-d955-4a7e-aa64-290382c63453\\\\artifacts\\\\global_usage_CPU_c213d5293f9cc52f_1794142381927_1794142413586.csv", "D:\\\\workspace\\\\claudecode-test\\\\testplat-auto\\\\.runtime\\\\rr-verify\\\\data\\\\artifacts\\\\7ca839a0-d955-4a7e-aa64-290382c63453\\\\perf\\\\7ca839a0-d955-4a7e-aa64-290382c63453\\\\artifacts\\\\global_usage_Memory_e23a071593b1a6e4_1794142381927_1794142413589.csv", "D:\\\\workspace\\\\claudecode-test\\\\testplat-auto\\\\.runtime\\\\rr-verify\\\\data\\\\artifacts\\\\7ca839a0-d955-4a7e-aa64-290382c63453\\\\perf\\\\7ca839a0-d955-4a7e-aa64-290382c63453\\\\artifacts\\\\privatedirty-main-20746_Memory_a23d7f4a8438d385_1794142381927_1794142413589.csv", "D:\\\\workspace\\\\claudecode-test\\\\testplat-auto\\\\.runtime\\\\rr-verify\\\\data\\\\artifacts\\\\7ca839a0-d955-4a7e-aa64-290382c63453\\\\perf\\\\7ca839a0-d955-4a7e-aa64-290382c63453\\\\artifacts\\\\pss-main-20746_Memory_838d082a3f6e0995_1794142381927_1794142413589.csv"], "durationS": 31.656, "hostRunId": "7ca839a0-d955-4a7e-aa64-290382c63453", "integrity": {"deviceRowCheck": "passed", "deviceDirRemoved": true}, "startedAt": "2026-11-08T20:52:59+08:00", "stoppedAt": "2026-11-08T20:53:33+08:00", "deviceProfile": null, "schemaVersion": 1, "soloSessionId": "f9cbdad3-be3a-45f1-91e2-4027ded5ceff", "metricsSummary": {"fps_frame": {"max": 118.0, "min": 118.0, "p90": 118.0, "mean": 118.0, "unit": "fps", "median": 118.0, "source": "solo_pi", "labelEn": "Frame rate", "labelZh": "帧率", "sampleCount": 32}, "gpu_mem_mb": {"max": 4.75, "min": 4.75, "p90": 4.75, "mean": 4.75, "unit": "MB", "median": 4.75, "source": "pc_supplement", "labelEn": "App GPU memory", "labelZh": "应用GPU显存", "sampleCount": 15}, "mem_pss_mb": {"max": 45.569336, "min": 39.277344, "p90": 45.54668100000001, "mean": 45.0826173, "unit": "MB", "median": 45.4677735, "source": "solo_pi", "labelEn": "Process PSS memory", "labelZh": "应用PSS内存", "sampleCount": 30}, "gpu_util_pct": {"max": 6.178479999053303, "min": 0.0, "p90": 2.3233176014891965, "mean": 0.67004506676902, "unit": "%", "median": 0.0, "source": "pc_supplement", "labelEn": "GPU utilization", "labelZh": "GPU占用", "sampleCount": 15}, "mem_global_mb": {"max": 4178.0, "min": 4147.0, "p90": 4174.5, "mean": 4162.75, "unit": "MB", "median": 4165.0, "source": "solo_pi", "labelEn": "Global memory usage", "labelZh": "全局内存占用", "sampleCount": 32}, "cpu_global_pct": {"max": 34.031414, "min": 4.556962, "p90": 22.00489, "mean": 14.771568637704917, "unit": "%", "median": 13.819096, "source": "solo_pi", "labelEn": "Global CPU usage", "labelZh": "全局CPU占用", "sampleCount": 61}, "temp_battery_c": {"max": 32.8, "min": 32.8, "p90": 32.8, "mean": 32.8, "unit": "°C", "median": 32.8, "source": "pc_supplement", "labelEn": "Battery temperature", "labelZh": "电池温度", "sampleCount": 15}, "cpu_process_pct": {"max": 4.511278, "min": 0.0, "p90": 3.25, "mean": 1.6215666700000002, "unit": "%", "median": 0.7518797, "source": "solo_pi", "labelEn": "Process CPU usage", "labelZh": "应用进程CPU占用", "sampleCount": 61}, "mem_privdirty_mb": {"max": 21.988281, "min": 6.2070312, "p90": 20.6496098, "mean": 11.577473973333333, "unit": "MB", "median": 9.01171875, "source": "solo_pi", "labelEn": "Process PrivateDirty memory", "labelZh": "应用PrivateDirty内存", "sampleCount": 30}, "frame_delay_count": {"max": 2.0, "min": 2.0, "p90": 2.0, "mean": 2.0, "unit": "次", "median": 2.0, "source": "solo_pi", "labelEn": "Frame delay count", "labelZh": "帧延迟次数", "sampleCount": 32}, "frame_delay_max_ms": {"max": 14.0, "min": 14.0, "p90": 14.0, "mean": 14.0, "unit": "ms", "median": 14.0, "source": "solo_pi", "labelEn": "Max frame delay", "labelZh": "最长帧延迟", "sampleCount": 32}, "app_jank_heavy_count": {"max": 0.0, "min": 0.0, "p90": 0.0, "mean": 0.0, "unit": "次", "median": 0.0, "source": "solo_pi", "labelEn": "Heavy jank windows (>300ms)", "labelZh": "重度卡顿窗口数(>300ms)", "sampleCount": 1}, "app_jank_light_count": {"max": 0.0, "min": 0.0, "p90": 0.0, "mean": 0.0, "unit": "次", "median": 0.0, "source": "solo_pi", "labelEn": "Light jank windows (>100ms)", "labelZh": "轻度卡顿窗口数(>100ms)", "sampleCount": 1}, "app_jank_severe_count": {"max": 0.0, "min": 0.0, "p90": 0.0, "mean": 0.0, "unit": "次", "median": 0.0, "source": "solo_pi", "labelEn": "Severe jank windows (>700ms)", "labelZh": "严重卡顿窗口数(>700ms)", "sampleCount": 1}, "frame_delay_ratio_pct": {"max": 66.66667, "min": 66.66667, "p90": 66.66667, "mean": 66.66667, "unit": "%", "median": 66.66667, "source": "solo_pi", "labelEn": "Frame delay ratio", "labelZh": "帧延迟占比", "sampleCount": 32}}}	2026-11-08 20:53:33.424816+08	gate_policy_missing
ce349940-a93a-4554-9c15-fd42ea93dca4	540f2fa1-53f8-4e43-9841-8eb881a0c529	ec832d64-466a-437a-8dcc-6a2efb9eede6	ui	mobile_auto	1	\N	completed	failed	{}	2026-11-08 21:12:46.205621+08	\N
1fd40ad8-d824-4a30-a169-3d636eadfb42	540f2fa1-53f8-4e43-9841-8eb881a0c529	ec832d64-466a-437a-8dcc-6a2efb9eede6	performance	mobile_perf	1	\N	completed	not_tested	{"jank": {"granularity": "per_sampling_window", "sourceMetric": "frame_delay_max_ms", "thresholdsMs": {"heavy": 300.0, "light": 100.0, "severe": 700.0}}, "mode": "original", "items": ["CPU", "Memory", "FPS"], "marks": [], "runId": "ec832d64-466a-437a-8dcc-6a2efb9eede6", "events": [], "serial": "749622c9", "series": {"fps_frame": {"unit": "fps", "points": [[0.0, 118.0], [0.998, 118.0], [2.0, 118.0], [3.0, 116.0], [4.006, 115.0], [5.007, 120.0], [6.009, 120.0], [7.012, 120.0], [8.014, 120.0], [9.02, 120.0], [10.019, 120.0], [11.022, 120.0], [12.025, 120.0], [13.027, 120.0], [14.029, 120.0], [15.031, 120.0], [16.033, 120.0], [17.037, 120.0], [18.039, 120.0], [19.041, 120.0], [20.043, 120.0]], "source": "solo_pi", "labelEn": "Frame rate", "labelZh": "帧率"}, "gpu_mem_mb": {"unit": "MB", "points": [[0.0, 4.75], [5.0, 47.359375], [7.0, 47.359375], [9.0, 47.359375], [11.0, 47.359375], [13.0, 47.390625], [15.0, 46.75], [17.0, 46.234375], [19.0, 46.2265625]], "source": "pc_supplement", "labelEn": "App GPU memory", "labelZh": "应用GPU显存"}, "mem_pss_mb": {"unit": "MB", "points": [[0.0, 43.195312], [0.982, 43.2666], [5.895, 78.89844], [6.884, 83.96582], [7.889, 84.01953], [8.896, 84.04297], [9.877, 84.05859], [10.9, 84.05469], [11.891, 84.00195], [12.887, 83.990234], [13.905, 83.70117], [14.906, 83.490234], [15.895, 83.30664], [16.9, 83.083984], [17.943, 83.143555], [18.926, 83.15137], [19.934, 83.87305]], "source": "solo_pi", "labelEn": "Process PSS memory", "labelZh": "应用PSS内存"}, "gpu_util_pct": {"unit": "%", "points": [[0.0, 3.3603032092610183], [5.0, 5.643846019158091], [7.0, 5.643846019158091], [9.0, 1.4477410500695673], [11.0, 1.4477410500695673], [13.0, 1.4477410500695673], [15.0, 1.3642160319140646], [17.0, 1.3642160319140646], [19.0, 1.3662808597528637]], "source": "pc_supplement", "labelEn": "GPU utilization", "labelZh": "GPU占用"}, "mem_global_mb": {"unit": "MB", "points": [[0.0, 4201.0], [0.98, 4207.0], [2.01, 4243.0], [2.853, 4268.0], [3.823, 4306.0], [4.826, 4328.0], [5.893, 4330.0], [6.882, 4324.0], [7.887, 4330.0], [8.894, 4324.0], [9.875, 4326.0], [10.899, 4334.0], [11.889, 4338.0], [12.885, 4334.0], [13.903, 4339.0], [14.905, 4328.0], [15.893, 4337.0], [16.898, 4330.0], [17.941, 4337.0], [18.925, 4333.0], [19.932, 4240.0]], "source": "solo_pi", "labelEn": "Global memory usage", "labelZh": "全局内存占用"}, "cpu_global_pct": {"unit": "%", "points": [[0.0, 5.3522053], [0.524, 24.694376], [1.021, 11.053985], [1.522, 15.151515], [1.994, 20.618557], [2.513, 46.68305], [2.988, 33.59375], [3.51, 34.878048], [4.006, 22.879177], [4.506, 29.923273], [5.006, 24.484535], [5.502, 24.810127], [6.022, 15.365239], [6.528, 16.153847], [7.023, 15.803109], [7.527, 14.545455], [8.032, 14.786967], [8.532, 17.662338], [9.035, 17.22365], [9.537, 15.856777], [10.02, 21.693121], [10.526, 21.938776], [11.031, 21.105528], [11.542, 17.091837], [12.038, 16.336634], [12.542, 16.710182], [13.031, 16.452442], [13.536, 16.202532], [14.047, 13.92405], [14.549, 17.525774], [15.049, 11.027569], [15.531, 22.371967], [16.034, 26.566416], [16.55, 12.564102], [17.046, 17.88413], [17.584, 18.2266], [18.043, 16.622692], [18.567, 17.661692], [19.062, 16.492147], [19.592, 21.497585], [20.076, 18.205128], [20.573, 42.487045]], "source": "solo_pi", "labelEn": "Global CPU usage", "labelZh": "全局CPU占用"}, "temp_battery_c": {"unit": "°C", "points": [[0.0, 33.2], [5.0, 33.2], [7.0, 33.2], [9.0, 33.2], [11.0, 33.2], [13.0, 33.2], [15.0, 33.2], [17.0, 33.2], [19.0, 33.2]], "source": "pc_supplement", "labelEn": "Battery temperature", "labelZh": "电池温度"}, "cpu_process_pct": {"unit": "%", "points": [[0.0, 0.0014459707], [0.524, 2.9339855], [1.021, 0.2570694], [1.522, 2.777778], [1.994, 0.0], [2.513, 0.0], [2.988, 0.0], [3.511, 0.0], [4.006, 0.0], [4.506, 0.0], [5.006, 0.0], [5.503, 0.0], [6.022, 0.0], [6.528, 1.0256411], [7.023, 0.0], [7.527, 1.2987013], [8.032, 0.0], [8.532, 0.77922076], [9.035, 0.2570694], [9.537, 0.7672635], [10.02, 0.52910054], [10.526, 0.7653061], [11.032, 0.0], [11.542, 1.0204082], [12.038, 0.24752475], [12.542, 0.7832898], [13.031, 0.5141388], [13.536, 0.75949365], [14.047, 0.25316456], [14.549, 0.77319586], [15.049, 0.25062656], [15.531, 0.8086253], [16.034, 0.25062656], [16.55, 0.7692308], [17.046, 0.25188917], [17.584, 0.7389163], [18.043, 0.5277045], [18.567, 0.74626863], [19.062, 0.2617801], [19.592, 0.7246377], [20.076, 0.0], [20.573, 1.2953368]], "source": "solo_pi", "labelEn": "Process CPU usage", "labelZh": "应用进程CPU占用"}, "mem_privdirty_mb": {"unit": "MB", "points": [[0.0, 9.109375], [0.982, 9.1171875], [5.895, 62.73047], [6.884, 61.45703], [7.889, 61.460938], [8.896, 61.484375], [9.877, 61.5], [10.901, 61.496094], [11.891, 61.445312], [12.887, 61.433594], [13.905, 61.14453], [14.906, 60.933594], [15.895, 60.75], [16.9, 60.527344], [17.943, 60.554688], [18.927, 60.5625], [19.934, 60.57422]], "source": "solo_pi", "labelEn": "Process PrivateDirty memory", "labelZh": "应用PrivateDirty内存"}, "frame_delay_count": {"unit": "次", "points": [[0.0, 2.0], [0.998, 2.0], [2.0, 2.0], [3.0, 2.0], [4.006, 3.0], [5.007, 0.0], [6.009, 0.0], [7.012, 0.0], [8.014, 0.0], [9.02, 0.0], [10.019, 0.0], [11.022, 0.0], [12.025, 0.0], [13.028, 0.0], [14.03, 0.0], [15.031, 0.0], [16.033, 0.0], [17.037, 0.0], [18.039, 0.0], [19.041, 0.0], [20.043, 0.0]], "source": "solo_pi", "labelEn": "Frame delay count", "labelZh": "帧延迟次数"}, "frame_delay_max_ms": {"unit": "ms", "points": [[0.0, 14.0], [0.998, 14.0], [2.0, 14.0], [3.0, 32.0], [4.006, 32.0], [5.007, 8.0], [6.009, 6.0], [7.012, 6.0], [8.014, 6.0], [9.02, 6.0], [10.019, 7.0], [11.022, 7.0], [12.025, 6.0], [13.028, 5.0], [14.03, 6.0], [15.031, 5.0], [16.034, 7.0], [17.037, 6.0], [18.039, 7.0], [19.041, 5.0], [20.043, 5.0]], "source": "solo_pi", "labelEn": "Max frame delay", "labelZh": "最长帧延迟"}, "frame_delay_ratio_pct": {"unit": "%", "points": [[0.0, 66.66667], [0.998, 66.66667], [2.0, 66.66667], [3.0, 66.66667], [4.006, 75.0], [5.007, 0.0], [6.009, 0.0], [7.012, 0.0], [8.014, 0.0], [9.02, 0.0], [10.019, 0.0], [11.022, 0.0], [12.025, 0.0], [13.028, 0.0], [14.03, 0.0], [15.031, 0.0], [16.034, 0.0], [17.037, 0.0], [18.039, 0.0], [19.041, 0.0], [20.043, 0.0]], "source": "solo_pi", "labelEn": "Frame delay ratio", "labelZh": "帧延迟占比"}}, "durationS": 21.39, "prototype": false, "startedAt": "2026-11-08T21:12:22+08:00", "stoppedAt": "2026-11-08T21:12:45+08:00", "collectWindow": {"ui": {"ended_at": "2026-11-08T13:12:44.104447+00:00", "timeout_s": 600, "started_at": "2026-11-08T13:12:24.451969+00:00"}, "collect_started_at": "2026-11-08T13:12:21.836286+00:00", "collect_stopped_at": "2026-11-08T13:12:46.170771+00:00"}, "metricsSummary": {"fps_frame": {"max": 120.0, "min": 115.0, "p90": 120.0, "mean": 119.28571428571429, "unit": "fps", "median": 120.0, "source": "solo_pi", "labelEn": "Frame rate", "labelZh": "帧率", "sampleCount": 21}, "gpu_mem_mb": {"max": 47.390625, "min": 4.75, "p90": 47.365625, "mean": 42.309895833333336, "unit": "MB", "median": 47.359375, "source": "pc_supplement", "labelEn": "App GPU memory", "labelZh": "应用GPU显存", "sampleCount": 9}, "mem_pss_mb": {"max": 84.05859, "min": 43.195312, "p90": 84.047658, "mean": 78.66141994117646, "unit": "MB", "median": 83.70117, "source": "solo_pi", "labelEn": "Process PSS memory", "labelZh": "应用PSS内存", "sampleCount": 17}, "gpu_util_pct": {"max": 5.643846019158091, "min": 1.3642160319140646, "p90": 5.643846019158091, "mean": 2.5651034801518775, "unit": "%", "median": 1.4477410500695673, "source": "pc_supplement", "labelEn": "GPU utilization", "labelZh": "GPU占用", "sampleCount": 9}, "mem_global_mb": {"max": 4339.0, "min": 4201.0, "p90": 4337.0, "mean": 4306.523809523809, "unit": "MB", "median": 4328.0, "source": "solo_pi", "labelEn": "Global memory usage", "labelZh": "全局内存占用", "sampleCount": 21}, "cpu_global_pct": {"max": 46.68305, "min": 5.3522053, "p90": 29.587587299999996, "mean": 20.050188792857142, "unit": "%", "median": 17.593733, "source": "solo_pi", "labelEn": "Global CPU usage", "labelZh": "全局CPU占用", "sampleCount": 42}, "temp_battery_c": {"max": 33.2, "min": 33.2, "p90": 33.2, "mean": 33.2, "unit": "°C", "median": 33.2, "source": "pc_supplement", "labelEn": "Battery temperature", "labelZh": "电池温度", "sampleCount": 9}, "cpu_process_pct": {"max": 2.9339855, "min": 0.0, "p90": 1.02511781, "mean": 0.5326057050166666, "unit": "%", "median": 0.25942475, "source": "solo_pi", "labelEn": "Process CPU usage", "labelZh": "应用进程CPU占用", "sampleCount": 42}, "mem_privdirty_mb": {"max": 62.73047, "min": 9.109375, "p90": 61.4976564, "mean": 55.07536773529412, "unit": "MB", "median": 61.14453, "source": "solo_pi", "labelEn": "Process PrivateDirty memory", "labelZh": "应用PrivateDirty内存", "sampleCount": 17}, "frame_delay_count": {"max": 3.0, "min": 0.0, "p90": 2.0, "mean": 0.5238095238095238, "unit": "次", "median": 0.0, "source": "solo_pi", "labelEn": "Frame delay count", "labelZh": "帧延迟次数", "sampleCount": 21}, "frame_delay_max_ms": {"max": 32.0, "min": 5.0, "p90": 14.0, "mean": 9.714285714285714, "unit": "ms", "median": 6.0, "source": "solo_pi", "labelEn": "Max frame delay", "labelZh": "最长帧延迟", "sampleCount": 21}, "app_jank_heavy_count": {"max": 0.0, "min": 0.0, "p90": 0.0, "mean": 0.0, "unit": "次", "median": 0.0, "source": "solo_pi", "labelEn": "Heavy jank windows (>300ms)", "labelZh": "重度卡顿窗口数(>300ms)", "sampleCount": 1}, "app_jank_light_count": {"max": 0.0, "min": 0.0, "p90": 0.0, "mean": 0.0, "unit": "次", "median": 0.0, "source": "solo_pi", "labelEn": "Light jank windows (>100ms)", "labelZh": "轻度卡顿窗口数(>100ms)", "sampleCount": 1}, "app_jank_severe_count": {"max": 0.0, "min": 0.0, "p90": 0.0, "mean": 0.0, "unit": "次", "median": 0.0, "source": "solo_pi", "labelEn": "Severe jank windows (>700ms)", "labelZh": "严重卡顿窗口数(>700ms)", "sampleCount": 1}, "frame_delay_ratio_pct": {"max": 75.0, "min": 0.0, "p90": 66.66667, "mean": 16.269841904761904, "unit": "%", "median": 0.0, "source": "solo_pi", "labelEn": "Frame delay ratio", "labelZh": "帧延迟占比", "sampleCount": 21}}, "thresholdsAtRun": {}}	2026-11-08 21:12:46.205621+08	baseline_missing
2ea7fd33-d842-4f0e-b51a-2c39469710da	540f2fa1-53f8-4e43-9841-8eb881a0c529	2b814545-aada-4196-90ae-706dbbaf4d76	ui	mobile_auto	1	\N	completed	failed	{}	2026-11-08 21:17:03.102559+08	\N
9ad8f101-9763-4a10-90cc-92033b5fe9b3	540f2fa1-53f8-4e43-9841-8eb881a0c529	2b814545-aada-4196-90ae-706dbbaf4d76	performance	mobile_perf	1	\N	completed	not_tested	{"jank": {"granularity": "per_sampling_window", "sourceMetric": "frame_delay_max_ms", "thresholdsMs": {"heavy": 300.0, "light": 100.0, "severe": 700.0}}, "mode": "original", "items": ["CPU", "Memory", "FPS"], "marks": [], "runId": "2b814545-aada-4196-90ae-706dbbaf4d76", "events": [], "serial": "749622c9", "series": {"fps_frame": {"unit": "fps", "points": [[0.0, 119.0], [0.997, 119.0], [1.997, 119.0], [4.003, 116.0], [5.005, 53379044.0], [6.005, 120.0], [7.008, 120.0], [8.009, 120.0], [9.012, 120.0], [10.013, 120.0], [11.014, 120.0], [12.016, 120.0], [13.018, 120.0], [14.02, 120.0], [15.022, 120.0], [16.024, 120.0], [17.026, 120.0], [18.031, 120.0], [19.03, 119.0], [20.037, 53380908.0], [21.033, 120.0]], "source": "solo_pi", "labelEn": "Frame rate", "labelZh": "帧率"}, "gpu_mem_mb": {"unit": "MB", "points": [[0.0, 4.75], [3.0, 4.75], [5.0, 47.3515625], [7.0, 47.359375], [9.0, 47.359375], [11.0, 47.359375], [13.0, 47.390625], [15.0, 46.75], [18.0, 46.234375], [20.0, 46.2265625]], "source": "pc_supplement", "labelEn": "App GPU memory", "labelZh": "应用GPU显存"}, "mem_pss_mb": {"unit": "MB", "points": [[0.0, 45.58203], [1.513, 45.535156], [5.934, 79.47363], [6.939, 85.22168], [8.431, 85.3125], [9.432, 85.33203], [10.428, 85.325195], [11.433, 85.27051], [12.46, 85.28516], [13.935, 85.140625], [14.933, 84.87891], [15.933, 84.69141], [16.939, 84.48828], [17.974, 84.42578], [18.975, 84.450195], [19.974, 84.481445]], "source": "solo_pi", "labelEn": "Process PSS memory", "labelZh": "应用PSS内存"}, "gpu_util_pct": {"unit": "%", "points": [[0.0, 3.554360221099479], [3.0, 3.554360221099479], [5.0, 3.554360221099479], [7.0, 5.4939324280178266], [9.0, 5.4939324280178266], [11.0, 1.5161679603650746], [13.0, 0.0], [15.0, 1.344004431884818], [18.0, 1.3755820746389122], [20.0, 1.3755820746389122]], "source": "pc_supplement", "labelEn": "GPU utilization", "labelZh": "GPU占用"}, "mem_global_mb": {"unit": "MB", "points": [[0.0, 4288.0], [1.512, 4272.0], [2.45, 4308.0], [3.461, 4315.0], [4.873, 4407.0], [5.933, 4409.0], [6.938, 4413.0], [8.431, 4402.0], [9.431, 4408.0], [10.427, 4396.0], [11.432, 4408.0], [12.459, 4409.0], [13.934, 4416.0], [14.932, 4406.0], [15.932, 4413.0], [16.938, 4422.0], [17.973, 4404.0], [18.974, 4412.0], [19.973, 4423.0]], "source": "solo_pi", "labelEn": "Global memory usage", "labelZh": "全局内存占用"}, "cpu_global_pct": {"unit": "%", "points": [[0.0, 24.829931], [0.489, 39.94778], [0.987, 11.111111], [1.512, 10.869565], [2.01, 24.739584], [2.495, 22.250639], [2.98, 48.812664], [3.581, 33.867275], [4.005, 20.391062], [4.49, 23.514212], [4.99, 30.512821], [5.497, 22.84264], [6.004, 22.807018], [6.5, 12.793734], [7.006, 16.030535], [7.497, 13.333333], [8.0, 14.545455], [8.502, 14.43038], [9.003, 15.979382], [9.508, 11.139896], [9.999, 16.70951], [10.53, 32.116787], [11.0, 23.705723], [11.51, 13.131313], [12.013, 15.544042], [12.521, 11.633663], [13.006, 13.612565], [13.509, 14.467005], [14.011, 12.953368], [14.512, 12.987013], [15.01, 13.486005], [15.514, 27.318296], [16.015, 23.155216], [16.514, 14.609571], [17.018, 16.541353], [17.523, 17.955112], [18.02, 14.652956], [18.536, 18.527918], [19.044, 16.161615], [19.541, 18.798956], [20.023, 17.391304], [20.561, 29.219143], [21.024, 28.423773]], "source": "solo_pi", "labelEn": "Global CPU usage", "labelZh": "全局CPU占用"}, "temp_battery_c": {"unit": "°C", "points": [[0.0, 33.6], [3.0, 33.6], [5.0, 33.6], [7.0, 33.6], [9.0, 33.6], [11.0, 33.6], [13.0, 33.6], [15.0, 33.6], [18.0, 33.6], [20.0, 33.6]], "source": "pc_supplement", "labelEn": "Battery temperature", "labelZh": "电池温度"}, "cpu_process_pct": {"unit": "%", "points": [[0.0, 0.0], [0.489, 2.610966], [0.987, 0.5050505], [1.512, 0.24154589], [2.01, 2.8645835], [2.495, 0.25575447], [2.98, 0.0], [3.581, 0.0], [4.005, 0.0], [4.49, 0.0], [4.99, 0.0], [5.497, 0.0], [6.004, 0.0], [6.5, 1.0443864], [7.006, 0.0], [7.497, 0.7692308], [8.0, 0.5194805], [8.502, 0.0], [9.003, 1.0309278], [9.508, 0.25906736], [9.999, 0.7712082], [10.53, 0.486618], [11.0, 0.27247956], [11.51, 0.5050505], [12.013, 0.77720207], [12.521, 0.24752475], [13.006, 1.0471205], [13.509, 0.2538071], [14.011, 0.0], [14.512, 1.038961], [15.01, 0.0], [15.514, 1.0025063], [16.015, 0.0], [16.514, 1.0075567], [17.018, 0.25062656], [17.523, 0.74812967], [18.02, 0.2570694], [18.536, 0.7614213], [19.045, 0.25252524], [19.541, 0.7832898], [20.023, 0.25575447], [20.561, 0.50377834], [21.024, 0.5167959]], "source": "solo_pi", "labelEn": "Process CPU usage", "labelZh": "应用进程CPU占用"}, "mem_privdirty_mb": {"unit": "MB", "points": [[0.0, 20.472656], [1.513, 20.429688], [5.934, 62.65625], [6.939, 61.429688], [8.432, 61.472656], [9.432, 61.484375], [10.428, 61.48047], [11.433, 61.42578], [12.46, 61.445312], [13.935, 61.308594], [14.933, 61.046875], [15.933, 60.859375], [16.939, 60.65625], [17.974, 60.558594], [18.975, 60.589844], [19.974, 60.621094]], "source": "solo_pi", "labelEn": "Process PrivateDirty memory", "labelZh": "应用PrivateDirty内存"}, "frame_delay_count": {"unit": "次", "points": [[0.0, 1.0], [0.996, 1.0], [1.996, 1.0], [4.002, 2.0], [5.004, 2.0], [6.005, 0.0], [7.007, 0.0], [8.008, 0.0], [9.011, 0.0], [10.012, 0.0], [11.013, 0.0], [12.015, 0.0], [13.017, 0.0], [14.019, 0.0], [15.021, 0.0], [16.023, 0.0], [17.025, 0.0], [18.03, 0.0], [19.029, 1.0], [20.036, 3.0], [21.032, 0.0]], "source": "solo_pi", "labelEn": "Frame delay count", "labelZh": "帧延迟次数"}, "frame_delay_max_ms": {"unit": "ms", "points": [[0.0, 15.0], [0.996, 15.0], [1.996, 15.0], [4.002, 29.0], [5.004, 29.0], [6.005, 9.0], [7.007, 8.0], [8.008, 5.0], [9.011, 6.0], [10.012, 6.0], [11.013, 4.0], [12.015, 8.0], [13.017, 8.0], [14.019, 6.0], [15.021, 6.0], [16.023, 5.0], [17.025, 5.0], [18.03, 5.0], [19.029, 13.0], [20.036, 29.0], [21.032, 4.0]], "source": "solo_pi", "labelEn": "Max frame delay", "labelZh": "最长帧延迟"}, "frame_delay_ratio_pct": {"unit": "%", "points": [[0.0, 33.333336], [0.996, 33.333336], [1.996, 33.333336], [4.002, 50.0], [5.004, 40.0], [6.005, 0.0], [7.007, 0.0], [8.008, 0.0], [9.011, 0.0], [10.012, 0.0], [11.013, 0.0], [12.015, 0.0], [13.017, 0.0], [14.019, 0.0], [15.021, 0.0], [16.023, 0.0], [17.025, 0.0], [18.03, 0.0], [19.029, 33.333336], [20.036, 8.333334], [21.032, 0.0]], "source": "solo_pi", "labelEn": "Frame delay ratio", "labelZh": "帧延迟占比"}}, "durationS": 21.86, "prototype": false, "startedAt": "2026-11-08T21:16:39+08:00", "stoppedAt": "2026-11-08T21:17:02+08:00", "collectWindow": {"ui": {"ended_at": "2026-11-08T13:17:00.880461+00:00", "timeout_s": 600, "started_at": "2026-11-08T13:16:40.745826+00:00"}, "collect_started_at": "2026-11-08T13:16:36.595398+00:00", "collect_stopped_at": "2026-11-08T13:17:03.063417+00:00"}, "metricsSummary": {"fps_frame": {"max": 53380908.0, "min": 116.0, "p90": 120.0, "mean": 5083915.428571428, "unit": "fps", "median": 120.0, "source": "solo_pi", "labelEn": "Frame rate", "labelZh": "帧率", "sampleCount": 21}, "gpu_mem_mb": {"max": 47.390625, "min": 4.75, "p90": 47.3625, "mean": 38.553125, "unit": "MB", "median": 47.05078125, "source": "pc_supplement", "labelEn": "App GPU memory", "labelZh": "应用GPU显存", "sampleCount": 10}, "mem_pss_mb": {"max": 85.33203, "min": 45.535156, "p90": 85.3188475, "mean": 79.6809085, "unit": "MB", "median": 84.78516, "source": "solo_pi", "labelEn": "Process PSS memory", "labelZh": "应用PSS内存", "sampleCount": 16}, "gpu_util_pct": {"max": 5.4939324280178266, "min": 0.0, "p90": 5.4939324280178266, "mean": 2.726228206086181, "unit": "%", "median": 2.5352640907322765, "source": "pc_supplement", "labelEn": "GPU utilization", "labelZh": "GPU占用", "sampleCount": 10}, "mem_global_mb": {"max": 4423.0, "min": 4272.0, "p90": 4417.2, "mean": 4385.8421052631575, "unit": "MB", "median": 4408.0, "source": "solo_pi", "labelEn": "Global memory usage", "labelZh": "全局内存占用", "sampleCount": 19}, "cpu_global_pct": {"max": 48.812664, "min": 10.869565, "p90": 30.254085400000005, "mean": 19.95002846511628, "unit": "%", "median": 16.70951, "source": "solo_pi", "labelEn": "Global CPU usage", "labelZh": "全局CPU占用", "sampleCount": 43}, "temp_battery_c": {"max": 33.6, "min": 33.6, "p90": 33.6, "mean": 33.6, "unit": "°C", "median": 33.6, "source": "pc_supplement", "labelEn": "Battery temperature", "labelZh": "电池温度", "sampleCount": 10}, "cpu_process_pct": {"max": 2.8645835, "min": 0.0, "p90": 1.0373543600000001, "mean": 0.5079167111627907, "unit": "%", "median": 0.25906736, "source": "solo_pi", "labelEn": "Process CPU usage", "labelZh": "应用进程CPU占用", "sampleCount": 43}, "mem_privdirty_mb": {"max": 62.65625, "min": 20.429688, "p90": 61.4824225, "mean": 56.1210938125, "unit": "MB", "median": 61.1777345, "source": "solo_pi", "labelEn": "Process PrivateDirty memory", "labelZh": "应用PrivateDirty内存", "sampleCount": 16}, "frame_delay_count": {"max": 3.0, "min": 0.0, "p90": 2.0, "mean": 0.5238095238095238, "unit": "次", "median": 0.0, "source": "solo_pi", "labelEn": "Frame delay count", "labelZh": "帧延迟次数", "sampleCount": 21}, "frame_delay_max_ms": {"max": 29.0, "min": 4.0, "p90": 29.0, "mean": 10.952380952380953, "unit": "ms", "median": 8.0, "source": "solo_pi", "labelEn": "Max frame delay", "labelZh": "最长帧延迟", "sampleCount": 21}, "app_jank_heavy_count": {"max": 0.0, "min": 0.0, "p90": 0.0, "mean": 0.0, "unit": "次", "median": 0.0, "source": "solo_pi", "labelEn": "Heavy jank windows (>300ms)", "labelZh": "重度卡顿窗口数(>300ms)", "sampleCount": 1}, "app_jank_light_count": {"max": 0.0, "min": 0.0, "p90": 0.0, "mean": 0.0, "unit": "次", "median": 0.0, "source": "solo_pi", "labelEn": "Light jank windows (>100ms)", "labelZh": "轻度卡顿窗口数(>100ms)", "sampleCount": 1}, "app_jank_severe_count": {"max": 0.0, "min": 0.0, "p90": 0.0, "mean": 0.0, "unit": "次", "median": 0.0, "source": "solo_pi", "labelEn": "Severe jank windows (>700ms)", "labelZh": "严重卡顿窗口数(>700ms)", "sampleCount": 1}, "frame_delay_ratio_pct": {"max": 50.0, "min": 0.0, "p90": 33.333336, "mean": 11.031746571428572, "unit": "%", "median": 0.0, "source": "solo_pi", "labelEn": "Frame delay ratio", "labelZh": "帧延迟占比", "sampleCount": 21}}, "thresholdsAtRun": {}}	2026-11-08 21:17:03.102559+08	baseline_missing
74e67528-38b7-4b00-81ef-e90d4e18c2d9	540f2fa1-53f8-4e43-9841-8eb881a0c529	99e0459d-5d6d-40ec-9d33-7d4848664a0f	ui	mobile_auto	1	\N	completed	failed	{}	2026-11-08 21:21:55.980553+08	\N
19feff9e-e556-4e05-932e-3bc8ff51f0ae	540f2fa1-53f8-4e43-9841-8eb881a0c529	99e0459d-5d6d-40ec-9d33-7d4848664a0f	performance	mobile_perf	1	\N	completed	not_tested	{"jank": {"granularity": "per_sampling_window", "sourceMetric": "frame_delay_max_ms", "thresholdsMs": {"heavy": 300.0, "light": 100.0, "severe": 700.0}}, "mode": "original", "items": ["CPU", "Memory", "FPS"], "marks": [], "runId": "99e0459d-5d6d-40ec-9d33-7d4848664a0f", "events": [], "serial": "749622c9", "series": {"fps_frame": {"unit": "fps", "points": [[0.0, 118.0], [1.004, 118.0], [2.008, 118.0], [4.012, 115.0], [5.015, 120.0], [6.017, 120.0], [7.02, 120.0], [8.023, 120.0], [9.025, 120.0], [10.027, 120.0], [11.031, 120.0], [12.033, 120.0], [13.035, 120.0], [14.038, 120.0], [15.041, 120.0], [16.043, 120.0], [17.046, 120.0], [18.049, 120.0], [19.052, 120.0], [20.054, 120.0]], "source": "solo_pi", "labelEn": "Frame rate", "labelZh": "帧率"}, "gpu_mem_mb": {"unit": "MB", "points": [[0.0, 6.0234375], [4.0, 47.359375], [6.0, 47.359375], [8.0, 47.359375], [11.0, 47.359375], [13.0, 47.390625], [15.0, 46.75], [17.0, 46.234375], [19.0, 46.2265625]], "source": "pc_supplement", "labelEn": "App GPU memory", "labelZh": "应用GPU显存"}, "mem_pss_mb": {"unit": "MB", "points": [[0.0, 37.978516], [0.989, 45.520508], [1.977, 44.850586], [6.374, 80.0166], [7.368, 86.06836], [8.357, 85.92383], [9.372, 85.94336], [10.375, 85.958984], [11.377, 85.978516], [12.377, 85.916016], [13.384, 85.74414], [14.383, 85.50195], [15.38, 85.30859], [16.392, 85.103516], [17.401, 85.00879], [18.418, 85.04199], [19.419, 85.06445], [20.451, 85.86914]], "source": "solo_pi", "labelEn": "Process PSS memory", "labelZh": "应用PSS内存"}, "gpu_util_pct": {"unit": "%", "points": [[0.0, 4.735229654756431], [4.0, 2.554631641752922], [6.0, 4.640327058368653], [8.0, 4.640327058368653], [11.0, 1.3333556428689537], [13.0, 1.3333556428689537], [15.0, 1.4477627517929297], [17.0, 0.0], [19.0, 1.5989414831489097]], "source": "pc_supplement", "labelEn": "GPU utilization", "labelZh": "GPU占用"}, "mem_global_mb": {"unit": "MB", "points": [[0.0, 4321.0], [0.987, 4307.0], [1.975, 4358.0], [3.365, 4330.0], [4.308, 4433.0], [5.315, 4440.0], [6.372, 4443.0], [7.367, 4450.0], [8.355, 4429.0], [9.37, 4441.0], [10.373, 4450.0], [11.375, 4433.0], [12.375, 4441.0], [13.382, 4449.0], [14.381, 4457.0], [15.378, 4441.0], [16.39, 4437.0], [17.4, 4444.0], [18.416, 4455.0], [19.417, 4441.0], [20.449, 4385.0]], "source": "solo_pi", "labelEn": "Global memory usage", "labelZh": "全局内存占用"}, "cpu_global_pct": {"unit": "%", "points": [[0.0, 5.8032246], [0.496, 25.56962], [1.011, 6.3414636], [1.501, 19.638243], [1.985, 24.226805], [2.529, 31.969309], [2.965, 52.467533], [3.496, 34.46602], [3.983, 28.759895], [4.492, 26.48515], [4.986, 25.520834], [5.496, 20.918367], [5.998, 17.424242], [6.509, 10.4325695], [7.017, 18.25], [7.499, 15.803109], [8.013, 14.8241205], [8.511, 16.368286], [9.012, 15.721649], [9.51, 16.372795], [9.998, 26.578947], [10.515, 20.448877], [11.008, 17.948717], [11.524, 14.861461], [12.021, 14.211886], [12.513, 14.683544], [13.011, 16.31579], [13.524, 17.369726], [14.028, 13.705584], [14.522, 13.333333], [15.015, 24.671917], [15.516, 25.773195], [16.034, 14.795918], [16.531, 16.494844], [17.037, 17.435898], [17.544, 15.104167], [18.056, 14.841849], [18.53, 16.621984], [19.061, 15.365239], [19.532, 23.316063], [20.073, 29.177057], [20.565, 34.5]], "source": "solo_pi", "labelEn": "Global CPU usage", "labelZh": "全局CPU占用"}, "temp_battery_c": {"unit": "°C", "points": [[0.0, 33.8], [4.0, 33.8], [6.0, 33.8], [8.0, 33.8], [11.0, 33.8], [13.0, 33.8], [15.0, 33.8], [17.0, 33.8], [19.0, 33.8]], "source": "pc_supplement", "labelEn": "Battery temperature", "labelZh": "电池温度"}, "cpu_process_pct": {"unit": "%", "points": [[0.0, 0.0041646613], [0.496, 4.3037972], [1.011, 0.0], [1.501, 2.8423774], [1.985, 0.25773194], [2.529, 0.0], [2.965, 0.0], [3.496, 0.0], [3.983, 0.0], [4.492, 0.0], [4.986, 0.0], [5.496, 0.0], [5.998, 0.0], [6.509, 0.0], [7.017, 1.25], [7.499, 0.25906736], [8.013, 1.0050251], [8.511, 0.0], [9.012, 0.77319586], [9.51, 0.25188917], [9.998, 1.0526316], [10.515, 0.0], [11.008, 1.0256411], [11.524, 0.0], [12.021, 0.7751938], [12.513, 0.5063291], [13.011, 0.78947365], [13.524, 0.24813895], [14.028, 0.7614213], [14.522, 0.25641027], [15.015, 0.78740156], [15.516, 0.0], [16.034, 1.0204082], [16.531, 0.25773194], [17.037, 0.7692308], [17.544, 0.0], [18.056, 0.729927], [18.53, 0.5361931], [19.061, 0.7556675], [19.532, 0.25906736], [20.073, 0.74812967], [20.565, 0.5]], "source": "solo_pi", "labelEn": "Process CPU usage", "labelZh": "应用进程CPU占用"}, "mem_privdirty_mb": {"unit": "MB", "points": [[0.0, 4.921875], [0.989, 8.890625], [1.977, 9.011719], [6.374, 62.785156], [7.369, 61.660156], [8.357, 61.507812], [9.372, 61.527344], [10.375, 61.54297], [11.377, 61.5625], [12.377, 61.5], [13.384, 61.328125], [14.383, 61.085938], [15.38, 60.89453], [16.392, 60.691406], [17.401, 60.5625], [18.418, 60.597656], [19.419, 60.621094], [20.451, 60.722656]], "source": "solo_pi", "labelEn": "Process PrivateDirty memory", "labelZh": "应用PrivateDirty内存"}, "frame_delay_count": {"unit": "次", "points": [[0.0, 1.0], [1.004, 1.0], [2.008, 1.0], [4.012, 2.0], [5.015, 0.0], [6.017, 0.0], [7.02, 0.0], [8.023, 0.0], [9.025, 0.0], [10.027, 0.0], [11.031, 0.0], [12.033, 0.0], [13.036, 0.0], [14.038, 0.0], [15.041, 0.0], [16.043, 0.0], [17.046, 0.0], [18.049, 0.0], [19.052, 0.0], [20.054, 0.0]], "source": "solo_pi", "labelEn": "Frame delay count", "labelZh": "帧延迟次数"}, "frame_delay_max_ms": {"unit": "ms", "points": [[0.0, 18.0], [1.004, 18.0], [2.008, 18.0], [4.012, 37.0], [5.015, 4.0], [6.017, 3.0], [7.02, 7.0], [8.023, 6.0], [9.025, 6.0], [10.027, 4.0], [11.031, 4.0], [12.033, 6.0], [13.036, 6.0], [14.038, 6.0], [15.041, 6.0], [16.043, 3.0], [17.046, 6.0], [18.049, 6.0], [19.052, 6.0], [20.054, 5.0]], "source": "solo_pi", "labelEn": "Max frame delay", "labelZh": "最长帧延迟"}, "frame_delay_ratio_pct": {"unit": "%", "points": [[0.0, 33.333336], [1.004, 33.333336], [2.008, 33.333336], [4.012, 50.0], [5.015, 0.0], [6.017, 0.0], [7.02, 0.0], [8.023, 0.0], [9.025, 0.0], [10.027, 0.0], [11.031, 0.0], [12.033, 0.0], [13.036, 0.0], [14.038, 0.0], [15.041, 0.0], [16.043, 0.0], [17.046, 0.0], [18.049, 0.0], [19.052, 0.0], [20.054, 0.0]], "source": "solo_pi", "labelEn": "Frame delay ratio", "labelZh": "帧延迟占比"}}, "durationS": 21.453, "prototype": false, "startedAt": "2026-11-08T21:21:32+08:00", "stoppedAt": "2026-11-08T21:21:55+08:00", "collectWindow": {"ui": {"ended_at": "2026-11-08T13:21:53.786323+00:00", "timeout_s": 600, "started_at": "2026-11-08T13:21:34.091196+00:00"}, "collect_started_at": "2026-11-08T13:21:31.371064+00:00", "collect_stopped_at": "2026-11-08T13:21:55.948160+00:00"}, "metricsSummary": {"fps_frame": {"max": 120.0, "min": 115.0, "p90": 120.0, "mean": 119.45, "unit": "fps", "median": 120.0, "source": "solo_pi", "labelEn": "Frame rate", "labelZh": "帧率", "sampleCount": 20}, "gpu_mem_mb": {"max": 47.390625, "min": 6.0234375, "p90": 47.365625, "mean": 42.451388888888886, "unit": "MB", "median": 47.359375, "source": "pc_supplement", "labelEn": "App GPU memory", "labelZh": "应用GPU显存", "sampleCount": 9}, "mem_pss_mb": {"max": 86.06836, "min": 37.978516, "p90": 85.9648436, "mean": 78.15543566666666, "unit": "MB", "median": 85.40527, "source": "solo_pi", "labelEn": "Process PSS memory", "labelZh": "应用PSS内存", "sampleCount": 18}, "gpu_util_pct": {"max": 4.735229654756431, "min": 0.0, "p90": 4.659307577646208, "mean": 2.475992325991823, "unit": "%", "median": 1.5989414831489097, "source": "pc_supplement", "labelEn": "GPU utilization", "labelZh": "GPU占用", "sampleCount": 9}, "mem_global_mb": {"max": 4457.0, "min": 4307.0, "p90": 4450.0, "mean": 4418.333333333333, "unit": "MB", "median": 4441.0, "source": "solo_pi", "labelEn": "Global memory usage", "labelZh": "全局内存占用", "sampleCount": 21}, "cpu_global_pct": {"max": 52.467533, "min": 5.8032246, "p90": 29.1353408, "mean": 20.117124552380954, "unit": "%", "median": 17.396984, "source": "solo_pi", "labelEn": "Global CPU usage", "labelZh": "全局CPU占用", "sampleCount": 42}, "temp_battery_c": {"max": 33.8, "min": 33.8, "p90": 33.8, "mean": 33.8, "unit": "°C", "median": 33.8, "source": "pc_supplement", "labelEn": "Battery temperature", "labelZh": "电池温度", "sampleCount": 9}, "cpu_process_pct": {"max": 4.3037972, "min": 0.0, "p90": 1.02511781, "mean": 0.5411010855071429, "unit": "%", "median": 0.25839965, "source": "solo_pi", "labelEn": "Process CPU usage", "labelZh": "应用进程CPU占用", "sampleCount": 42}, "mem_privdirty_mb": {"max": 62.785156, "min": 4.921875, "p90": 61.5917968, "mean": 52.30078122222223, "unit": "MB", "median": 60.990234, "source": "solo_pi", "labelEn": "Process PrivateDirty memory", "labelZh": "应用PrivateDirty内存", "sampleCount": 18}, "frame_delay_count": {"max": 2.0, "min": 0.0, "p90": 1.0, "mean": 0.25, "unit": "次", "median": 0.0, "source": "solo_pi", "labelEn": "Frame delay count", "labelZh": "帧延迟次数", "sampleCount": 20}, "frame_delay_max_ms": {"max": 37.0, "min": 3.0, "p90": 18.0, "mean": 8.75, "unit": "ms", "median": 6.0, "source": "solo_pi", "labelEn": "Max frame delay", "labelZh": "最长帧延迟", "sampleCount": 20}, "app_jank_heavy_count": {"max": 0.0, "min": 0.0, "p90": 0.0, "mean": 0.0, "unit": "次", "median": 0.0, "source": "solo_pi", "labelEn": "Heavy jank windows (>300ms)", "labelZh": "重度卡顿窗口数(>300ms)", "sampleCount": 1}, "app_jank_light_count": {"max": 0.0, "min": 0.0, "p90": 0.0, "mean": 0.0, "unit": "次", "median": 0.0, "source": "solo_pi", "labelEn": "Light jank windows (>100ms)", "labelZh": "轻度卡顿窗口数(>100ms)", "sampleCount": 1}, "app_jank_severe_count": {"max": 0.0, "min": 0.0, "p90": 0.0, "mean": 0.0, "unit": "次", "median": 0.0, "source": "solo_pi", "labelEn": "Severe jank windows (>700ms)", "labelZh": "严重卡顿窗口数(>700ms)", "sampleCount": 1}, "frame_delay_ratio_pct": {"max": 50.0, "min": 0.0, "p90": 33.333336, "mean": 7.5000004, "unit": "%", "median": 0.0, "source": "solo_pi", "labelEn": "Frame delay ratio", "labelZh": "帧延迟占比", "sampleCount": 20}}, "thresholdsAtRun": {}}	2026-11-08 21:21:55.980553+08	baseline_missing
527179e4-94a8-464e-8710-090e8550654e	540f2fa1-53f8-4e43-9841-8eb881a0c529	d8c1ea76-e45d-4629-8152-bb2697af04f0	ui	mobile_auto	1	\N	completed	failed	{}	2026-11-08 21:24:09.471599+08	\N
206414d0-f279-464d-894c-b351afe61c79	540f2fa1-53f8-4e43-9841-8eb881a0c529	d8c1ea76-e45d-4629-8152-bb2697af04f0	performance	mobile_perf	1	\N	completed	not_tested	{"jank": {"granularity": "per_sampling_window", "sourceMetric": "frame_delay_max_ms", "thresholdsMs": {"heavy": 300.0, "light": 100.0, "severe": 700.0}}, "mode": "original", "items": ["CPU", "Memory", "FPS"], "marks": [], "runId": "d8c1ea76-e45d-4629-8152-bb2697af04f0", "events": [], "serial": "749622c9", "series": {"fps_frame": {"unit": "fps", "points": [[0.0, 118.0], [0.997, 118.0], [4.005, 115.0], [5.007, 119.0], [6.008, 120.0], [7.01, 120.0], [8.012, 120.0], [9.014, 120.0], [10.016, 120.0], [11.017, 120.0], [12.02, 120.0], [13.021, 120.0], [14.023, 120.0], [15.025, 120.0], [16.026, 120.0], [17.032, 120.0], [18.029, 120.0], [19.03, 120.0], [20.031, 120.0]], "source": "solo_pi", "labelEn": "Frame rate", "labelZh": "帧率"}, "gpu_mem_mb": {"unit": "MB", "points": [[0.0, 6.0234375], [5.0, 47.359375], [7.0, 47.359375], [9.0, 47.359375], [11.0, 47.359375], [13.0, 47.390625], [15.0, 46.75], [17.0, 46.234375], [20.0, 46.2265625]], "source": "pc_supplement", "labelEn": "App GPU memory", "labelZh": "应用GPU显存"}, "mem_pss_mb": {"unit": "MB", "points": [[0.0, 38.23633], [1.467, 44.981445], [6.378, 79.953125], [7.357, 86.115234], [8.354, 85.99805], [9.362, 86.00195], [10.353, 86.024414], [11.359, 86.05664], [12.373, 85.93555], [13.364, 85.5957], [14.373, 85.45117], [15.372, 85.24805], [16.892, 85.03516], [18.383, 85.134766], [19.4, 85.84668]], "source": "solo_pi", "labelEn": "Process PSS memory", "labelZh": "应用PSS内存"}, "gpu_util_pct": {"unit": "%", "points": [[0.0, 7.512594558831735], [5.0, 5.395851528814743], [7.0, 5.395851528814743], [9.0, 1.656243993017508], [11.0, 1.656243993017508], [13.0, 1.4191289674599779], [15.0, 1.4191289674599779], [17.0, 0.0], [20.0, 1.4057939004662101]], "source": "pc_supplement", "labelEn": "GPU utilization", "labelZh": "GPU占用"}, "mem_global_mb": {"unit": "MB", "points": [[0.0, 4335.0], [1.464, 4384.0], [2.339, 4418.0], [3.304, 4466.0], [4.296, 4461.0], [5.3, 4472.0], [6.375, 4477.0], [7.354, 4461.0], [8.351, 4470.0], [9.359, 4477.0], [10.35, 4468.0], [11.356, 4478.0], [12.37, 4484.0], [13.361, 4480.0], [14.37, 4468.0], [15.369, 4480.0], [16.889, 4486.0], [18.38, 4473.0], [19.397, 4392.0]], "source": "solo_pi", "labelEn": "Global memory usage", "labelZh": "全局内存占用"}, "cpu_global_pct": {"unit": "%", "points": [[0.0, 6.880688], [0.471, 27.34375], [1.0, 11.691543], [1.476, 21.983913], [2.019, 43.137257], [2.461, 36.43617], [2.979, 37.19212], [3.486, 28.967255], [3.976, 24.409449], [4.478, 17.128464], [4.982, 12.564102], [5.482, 25.879396], [5.988, 20.25974], [6.498, 17.206982], [7.004, 13.065327], [7.495, 12.600536], [7.991, 14.795918], [8.494, 14.213198], [8.994, 13.624679], [9.494, 14.758269], [9.986, 15.521628], [10.515, 29.024391], [10.995, 23.180593], [11.5, 15.11335], [11.993, 15.228426], [12.499, 15.949368], [13.018, 12.5], [13.501, 13.5770235], [13.991, 13.953488], [14.511, 13.861386], [14.999, 16.919191], [15.517, 25.247524], [16.019, 19.895288], [16.503, 14.141414], [17.014, 18.387909], [17.546, 19.5], [18.037, 15.422886], [18.546, 12.21374], [19.033, 15.508021], [19.514, 21.212122], [19.996, 37.760418]], "source": "solo_pi", "labelEn": "Global CPU usage", "labelZh": "全局CPU占用"}, "temp_battery_c": {"unit": "°C", "points": [[0.0, 33.9], [5.0, 33.9], [7.0, 33.9], [9.0, 33.9], [11.0, 33.9], [13.0, 33.9], [15.0, 33.9], [17.0, 33.9], [20.0, 33.9]], "source": "pc_supplement", "labelEn": "Battery temperature", "labelZh": "电池温度"}, "cpu_process_pct": {"unit": "%", "points": [[0.0, 0.010001], [0.471, 4.427083], [1.0, 0.0], [1.476, 0.0], [2.019, 0.0], [2.461, 0.0], [2.979, 0.0], [3.486, 0.0], [3.976, 0.0], [4.478, 0.0], [4.982, 0.0], [5.482, 0.0], [5.988, 0.0], [6.498, 0.24937657], [7.004, 1.758794], [7.495, 0.26809654], [7.991, 0.7653061], [8.494, 0.0], [8.994, 1.0282776], [9.494, 0.2544529], [9.986, 0.7633588], [10.515, 0.4878049], [10.995, 0.53908354], [11.5, 0.0], [11.993, 1.0152284], [12.499, 0.25316456], [13.018, 1.0], [13.501, 0.0], [13.991, 0.7751938], [14.511, 0.24752475], [14.999, 0.75757575], [15.517, 0.0], [16.019, 1.0471205], [16.503, 0.25252524], [17.014, 0.0], [17.546, 1.0], [18.037, 0.49751243], [18.546, 0.2544529], [19.033, 0.26737967], [19.514, 0.5050505], [19.996, 1.0416667]], "source": "solo_pi", "labelEn": "Process CPU usage", "labelZh": "应用进程CPU占用"}, "mem_privdirty_mb": {"unit": "MB", "points": [[0.0, 4.6171875], [1.467, 8.792969], [6.378, 62.847656], [7.357, 61.66797], [8.354, 61.55078], [9.362, 61.554688], [10.353, 61.578125], [11.359, 61.61328], [12.373, 61.5], [13.364, 61.160156], [14.373, 61.015625], [15.372, 60.8125], [16.892, 60.601562], [18.383, 60.66797], [19.4, 60.65625]], "source": "solo_pi", "labelEn": "Process PrivateDirty memory", "labelZh": "应用PrivateDirty内存"}, "frame_delay_count": {"unit": "次", "points": [[0.0, 1.0], [0.997, 1.0], [4.005, 3.0], [5.007, 1.0], [6.008, 0.0], [7.01, 0.0], [8.013, 0.0], [9.014, 0.0], [10.016, 0.0], [11.017, 0.0], [12.02, 0.0], [13.021, 0.0], [14.023, 0.0], [15.025, 0.0], [16.026, 0.0], [17.032, 0.0], [18.029, 0.0], [19.031, 0.0], [20.031, 0.0]], "source": "solo_pi", "labelEn": "Frame delay count", "labelZh": "帧延迟次数"}, "frame_delay_max_ms": {"unit": "ms", "points": [[0.0, 18.0], [0.997, 18.0], [4.005, 29.0], [5.007, 10.0], [6.008, 5.0], [7.01, 9.0], [8.013, 6.0], [9.014, 5.0], [10.016, 6.0], [11.017, 5.0], [12.02, 6.0], [13.021, 6.0], [14.023, 6.0], [15.025, 6.0], [16.026, 6.0], [17.032, 6.0], [18.029, 7.0], [19.031, 7.0], [20.031, 6.0]], "source": "solo_pi", "labelEn": "Max frame delay", "labelZh": "最长帧延迟"}, "frame_delay_ratio_pct": {"unit": "%", "points": [[0.0, 33.333336], [0.997, 33.333336], [4.005, 75.0], [5.007, 50.0], [6.008, 0.0], [7.01, 0.0], [8.013, 0.0], [9.014, 0.0], [10.016, 0.0], [11.017, 0.0], [12.02, 0.0], [13.021, 0.0], [14.023, 0.0], [15.025, 0.0], [16.026, 0.0], [17.032, 0.0], [18.029, 0.0], [19.031, 0.0], [20.031, 0.0]], "source": "solo_pi", "labelEn": "Frame delay ratio", "labelZh": "帧延迟占比"}}, "durationS": 20.797, "prototype": false, "startedAt": "2026-11-08T21:23:46+08:00", "stoppedAt": "2026-11-08T21:24:08+08:00", "collectWindow": {"ui": {"ended_at": "2026-11-08T13:24:07.293642+00:00", "timeout_s": 600, "started_at": "2026-11-08T13:23:47.682199+00:00"}, "collect_started_at": "2026-11-08T13:23:45.609194+00:00", "collect_stopped_at": "2026-11-08T13:24:09.426045+00:00"}, "metricsSummary": {"fps_frame": {"max": 120.0, "min": 115.0, "p90": 120.0, "mean": 119.47368421052632, "unit": "fps", "median": 120.0, "source": "solo_pi", "labelEn": "Frame rate", "labelZh": "帧率", "sampleCount": 19}, "gpu_mem_mb": {"max": 47.390625, "min": 6.0234375, "p90": 47.365625, "mean": 42.451388888888886, "unit": "MB", "median": 47.359375, "source": "pc_supplement", "labelEn": "App GPU memory", "labelZh": "应用GPU显存", "sampleCount": 9}, "mem_pss_mb": {"max": 86.115234, "min": 38.23633, "p90": 86.0437496, "mean": 79.44095093333334, "unit": "MB", "median": 85.5957, "source": "solo_pi", "labelEn": "Process PSS memory", "labelZh": "应用PSS内存", "sampleCount": 15}, "gpu_util_pct": {"max": 7.512594558831735, "min": 0.0, "p90": 5.819200134818141, "mean": 2.8734263819869335, "unit": "%", "median": 1.656243993017508, "source": "pc_supplement", "labelEn": "GPU utilization", "labelZh": "GPU占用", "sampleCount": 9}, "mem_global_mb": {"max": 4486.0, "min": 4335.0, "p90": 4480.8, "mean": 4454.210526315789, "unit": "MB", "median": 4470.0, "source": "solo_pi", "labelEn": "Global memory usage", "labelZh": "全局内存占用", "sampleCount": 19}, "cpu_global_pct": {"max": 43.137257, "min": 6.880688, "p90": 29.024391, "mean": 19.469681036585364, "unit": "%", "median": 15.949368, "source": "solo_pi", "labelEn": "Global CPU usage", "labelZh": "全局CPU占用", "sampleCount": 41}, "temp_battery_c": {"max": 33.9, "min": 33.9, "p90": 33.9, "mean": 33.9, "unit": "°C", "median": 33.9, "source": "pc_supplement", "labelEn": "Battery temperature", "labelZh": "电池温度", "sampleCount": 9}, "cpu_process_pct": {"max": 4.427083, "min": 0.0, "p90": 1.0282776, "mean": 0.4747812231707317, "unit": "%", "median": 0.25316456, "source": "solo_pi", "labelEn": "Process CPU usage", "labelZh": "应用进程CPU占用", "sampleCount": 41}, "mem_privdirty_mb": {"max": 62.847656, "min": 4.6171875, "p90": 61.646094, "mean": 54.0424479, "unit": "MB", "median": 61.160156, "source": "solo_pi", "labelEn": "Process PrivateDirty memory", "labelZh": "应用PrivateDirty内存", "sampleCount": 15}, "frame_delay_count": {"max": 3.0, "min": 0.0, "p90": 1.0, "mean": 0.3157894736842105, "unit": "次", "median": 0.0, "source": "solo_pi", "labelEn": "Frame delay count", "labelZh": "帧延迟次数", "sampleCount": 19}, "frame_delay_max_ms": {"max": 29.0, "min": 5.0, "p90": 18.0, "mean": 8.789473684210526, "unit": "ms", "median": 6.0, "source": "solo_pi", "labelEn": "Max frame delay", "labelZh": "最长帧延迟", "sampleCount": 19}, "app_jank_heavy_count": {"max": 0.0, "min": 0.0, "p90": 0.0, "mean": 0.0, "unit": "次", "median": 0.0, "source": "solo_pi", "labelEn": "Heavy jank windows (>300ms)", "labelZh": "重度卡顿窗口数(>300ms)", "sampleCount": 1}, "app_jank_light_count": {"max": 0.0, "min": 0.0, "p90": 0.0, "mean": 0.0, "unit": "次", "median": 0.0, "source": "solo_pi", "labelEn": "Light jank windows (>100ms)", "labelZh": "轻度卡顿窗口数(>100ms)", "sampleCount": 1}, "app_jank_severe_count": {"max": 0.0, "min": 0.0, "p90": 0.0, "mean": 0.0, "unit": "次", "median": 0.0, "source": "solo_pi", "labelEn": "Severe jank windows (>700ms)", "labelZh": "严重卡顿窗口数(>700ms)", "sampleCount": 1}, "frame_delay_ratio_pct": {"max": 75.0, "min": 0.0, "p90": 36.66666879999999, "mean": 10.087719578947368, "unit": "%", "median": 0.0, "source": "solo_pi", "labelEn": "Frame delay ratio", "labelZh": "帧延迟占比", "sampleCount": 19}}, "thresholdsAtRun": {}}	2026-11-08 21:24:09.471599+08	baseline_missing
\.


--
-- Data for Name: run_events; Type: TABLE DATA; Schema: public; Owner: testdock
--

COPY public.run_events (id, project_id, run_id, sequence, source_key, source_event_id, event_type, payload, occurred_at, created_at) FROM stdin;
76974749-0e99-4b8e-b9aa-9dc23d580291	540f2fa1-53f8-4e43-9841-8eb881a0c529	8dd151a4-cfdb-45be-8775-94a84b86c834	1	api	created	queued	{"source": "api", "request_key": "bf2c39ae-ac3f-4947-a1a6-fde368a1be56"}	2026-11-08 20:17:47.299654+08	2026-11-08 20:17:47.299654+08
8d0144db-3dc7-4e94-ab84-3adba65ef325	540f2fa1-53f8-4e43-9841-8eb881a0c529	8dd151a4-cfdb-45be-8775-94a84b86c834	2	dispatcher	bed041e0f20c92f7ffe71365c95e5dbc	lease_acquired	{"stage": "lease", "serial": "749622c9", "resource_id": "fab1ee61-4ece-4fc5-92bc-4bc0b13427a2", "fencing_token": 2}	2026-11-08 20:17:48.262323+08	2026-11-08 20:17:48.262323+08
739d35b4-78de-4b95-b9ae-cbfdbf1f70c8	540f2fa1-53f8-4e43-9841-8eb881a0c529	8dd151a4-cfdb-45be-8775-94a84b86c834	3	dispatcher	590fcf8179d337420cc16ab7e54cf1ac	identity_verified	{"note": "已核对设备上已安装包的包名/versionName/versionCode；未验证 APK 文件摘要", "stage": "identity", "detail": "versionName=15.0.14 与固定基准一致（仅核对安装包字段，未验证 APK 摘要）", "reason": "identity_match", "serial": "749622c9", "verdict": "verified", "package_name": "com.miui.calculator", "execution_allowed": true, "verification_level": "package_identity_observed", "apk_digest_verified": false, "expected_version_code": 315000014, "expected_version_name": "15.0.14", "observed_version_code": 315000014, "observed_version_name": "15.0.14"}	2026-11-08 20:17:48.472952+08	2026-11-08 20:17:48.472952+08
cd46c660-fde2-4d8b-ac23-596c63e4b92c	540f2fa1-53f8-4e43-9841-8eb881a0c529	8dd151a4-cfdb-45be-8775-94a84b86c834	4	control	2bf9635cb9f83d1ce7e08e49c451bd48	ack	{"pid": 33708, "stage": "ack", "progress": 5, "revision_id": "629f6c29-1023-4ecb-beec-4e866029493a"}	2026-11-08 20:17:48.601617+08	2026-11-08 20:17:48.601617+08
3ccc533b-04e0-4e19-88a9-1be7b12967c4	540f2fa1-53f8-4e43-9841-8eb881a0c529	8dd151a4-cfdb-45be-8775-94a84b86c834	5	runner	b0124e86f47945c7d8bdc09f29cdd55f	stage	{"t": "stage", "name": "lease", "progress": 10}	2026-11-08 20:17:48.683357+08	2026-11-08 20:17:48.683357+08
b5652479-56e2-41f4-8f13-90b4decbba25	540f2fa1-53f8-4e43-9841-8eb881a0c529	8dd151a4-cfdb-45be-8775-94a84b86c834	6	runner	c5dc089b563a76dc074a10090b8ba93a	stage	{"t": "stage", "name": "ready", "progress": 20}	2026-11-08 20:17:48.686556+08	2026-11-08 20:17:48.686556+08
29939f3d-de20-4314-88b2-2520fd82e92c	540f2fa1-53f8-4e43-9841-8eb881a0c529	8dd151a4-cfdb-45be-8775-94a84b86c834	7	runner	2bf63b18c8cf729476044be0c1ebc208	text	{"t": "text", "name": "suite_copy", "targets": ["."], "suite_root": "D:\\\\workspace\\\\claudecode-test\\\\testplat-auto\\\\.runtime\\\\rr-verify\\\\data\\\\code-copies\\\\b475bb18efac4d05bd903281643a50c1", "tree_sha256": "86f5595fc981c237ac149cef560210020d47aef9f514830952a0df76500a9304", "suite_version_id": "0bfc19f5-96f6-499d-aa1b-3c97c8c720bb"}	2026-11-08 20:17:48.689144+08	2026-11-08 20:17:48.689144+08
0a6224db-1c86-4a09-8457-899ca35fc98a	540f2fa1-53f8-4e43-9841-8eb881a0c529	8dd151a4-cfdb-45be-8775-94a84b86c834	8	runner	291c195490a74f834e88ff2111fee945	stage	{"t": "stage", "cwd": "D:\\\\workspace\\\\claudecode-test\\\\testplat-auto\\\\.runtime\\\\rr-verify\\\\data\\\\code-copies\\\\b475bb18efac4d05bd903281643a50c1", "argv": ["D:\\\\python312\\\\python.exe", "-m", "pytest", "--mobile-evidence", "--mobile-devices", "749622c9", "--mobile-config", "D:\\\\workspace\\\\claudecode-test\\\\testplat-auto\\\\.runtime\\\\rr-verify\\\\data\\\\artifacts\\\\8dd151a4-cfdb-45be-8775-94a84b86c834\\\\mobile-config.toml", "-p", "testdock_runner.pytest_plugin", "-p", "no:mobile-perf", "-o", "addopts=", "--junit-xml", "D:\\\\workspace\\\\claudecode-test\\\\testplat-auto\\\\.runtime\\\\rr-verify\\\\data\\\\artifacts\\\\8dd151a4-cfdb-45be-8775-94a84b86c834\\\\junit.xml", "-p", "no:cacheprovider", "-q", "."], "name": "pytest", "progress": 40}	2026-11-08 20:17:48.691316+08	2026-11-08 20:17:48.691316+08
d662839f-102f-4139-bebd-39c4f18f5b3e	540f2fa1-53f8-4e43-9841-8eb881a0c529	8dd151a4-cfdb-45be-8775-94a84b86c834	9	control	7d7fdcd8bad65cf1a4559dfa3d738dbc	heartbeat	{"pid": 33708, "stage": 2, "progress": 40}	2026-11-08 20:17:58.609316+08	2026-11-08 20:17:58.609316+08
5245cdba-060f-4205-a365-8aa3d1dfc512	540f2fa1-53f8-4e43-9841-8eb881a0c529	8dd151a4-cfdb-45be-8775-94a84b86c834	10	runner	b93b6c6ebe3a04ddc1bf69b1fd843aa8	text	{"t": "text", "name": "pytest: F...                                                                     [100%]"}	2026-11-08 20:18:08.520967+08	2026-11-08 20:18:08.520967+08
2c8d7e84-1ef1-4dbb-aa88-bc005e604afa	540f2fa1-53f8-4e43-9841-8eb881a0c529	8dd151a4-cfdb-45be-8775-94a84b86c834	11	runner	cc432db2940d05304c76c1e421b69cb1	text	{"t": "text", "name": "pytest: ================================== FAILURES ==================================="}	2026-11-08 20:18:08.524117+08	2026-11-08 20:18:08.524117+08
de9845be-f386-480f-a910-a2f8636eae5b	540f2fa1-53f8-4e43-9841-8eb881a0c529	8dd151a4-cfdb-45be-8775-94a84b86c834	12	runner	70f84797395a55a243fe26145abd0097	text	{"t": "text", "name": "pytest: _______________ test_deliberate_assertion_failure_for_evidence ________________"}	2026-11-08 20:18:08.526442+08	2026-11-08 20:18:08.526442+08
9d2bca0a-401c-4935-bad1-6f7a89f4a0a2	540f2fa1-53f8-4e43-9841-8eb881a0c529	8dd151a4-cfdb-45be-8775-94a84b86c834	13	runner	18b54998af6bd7941a58b421f3a0d85f	text	{"t": "text", "name": "pytest: "}	2026-11-08 20:18:08.528606+08	2026-11-08 20:18:08.528606+08
fcf618fa-6eef-4cd4-97c3-518a7a3d089f	540f2fa1-53f8-4e43-9841-8eb881a0c529	8dd151a4-cfdb-45be-8775-94a84b86c834	14	runner	a7062e9f9d94aec372010643deab11d6	text	{"t": "text", "name": "pytest:     def test_deliberate_assertion_failure_for_evidence():"}	2026-11-08 20:18:08.530737+08	2026-11-08 20:18:08.530737+08
a7bbc37b-853e-4b47-acb4-d8b0d46aaaa5	540f2fa1-53f8-4e43-9841-8eb881a0c529	8dd151a4-cfdb-45be-8775-94a84b86c834	15	runner	c9206d2f98f3215118aa46fb791f760b	text	{"t": "text", "name": "pytest:         \\"\\"\\"永远失败：进入报告的失败证据链路（预期内，非产品缺陷）。\\"\\"\\""}	2026-11-08 20:18:08.533301+08	2026-11-08 20:18:08.533301+08
059722cf-e532-4e40-9af7-f0a3f7c25768	540f2fa1-53f8-4e43-9841-8eb881a0c529	8dd151a4-cfdb-45be-8775-94a84b86c834	16	runner	2c214c4162ad08fc03819222e6c239fa	text	{"t": "text", "name": "pytest: >       assert False, \\"预期内的故意失败：用于验证失败结论与证据产物保留（release-readiness 02）\\""}	2026-11-08 20:18:08.535657+08	2026-11-08 20:18:08.535657+08
71b5cb4b-5391-4515-b3fd-b22597d41054	540f2fa1-53f8-4e43-9841-8eb881a0c529	8dd151a4-cfdb-45be-8775-94a84b86c834	17	runner	47df7328eb4f6f6f319d0ce7ce280d82	text	{"t": "text", "name": "pytest: E       AssertionError: 预期内的故意失败：用于验证失败结论与证据产物保留（release-readiness 02）"}	2026-11-08 20:18:08.538063+08	2026-11-08 20:18:08.538063+08
ad60eb8f-614c-4f36-834d-e1848ceed44d	540f2fa1-53f8-4e43-9841-8eb881a0c529	8dd151a4-cfdb-45be-8775-94a84b86c834	18	runner	c9380a3aaea88feffb2055a3e6726dfd	text	{"t": "text", "name": "pytest: E       assert False"}	2026-11-08 20:18:08.540229+08	2026-11-08 20:18:08.540229+08
1167f656-4a89-4251-9e29-c7926648eac3	540f2fa1-53f8-4e43-9841-8eb881a0c529	8dd151a4-cfdb-45be-8775-94a84b86c834	19	runner	80f838a948597e9c6c8f81ee0563c1b7	text	{"t": "text", "name": "pytest: "}	2026-11-08 20:18:08.542615+08	2026-11-08 20:18:08.542615+08
bdb96ca9-e300-46c1-9c52-cbcfde1294a2	540f2fa1-53f8-4e43-9841-8eb881a0c529	8dd151a4-cfdb-45be-8775-94a84b86c834	20	runner	d10ea5b805ff1f449489ccda660552d5	text	{"t": "text", "name": "pytest: test_deliberate_failure.py:12: AssertionError"}	2026-11-08 20:18:08.544739+08	2026-11-08 20:18:08.544739+08
0ca39693-4de4-40ca-9023-8202ca1c7f84	540f2fa1-53f8-4e43-9841-8eb881a0c529	8dd151a4-cfdb-45be-8775-94a84b86c834	21	runner	14b175c4fe7f5256e60ee7782474a47c	text	{"t": "text", "name": "pytest: ---------------------------- mobile-auto-evidence -----------------------------"}	2026-11-08 20:18:08.548179+08	2026-11-08 20:18:08.548179+08
b845cafd-2ffc-4b85-96c6-ee84ed784bce	540f2fa1-53f8-4e43-9841-8eb881a0c529	8dd151a4-cfdb-45be-8775-94a84b86c834	22	runner	f9dab0d278e716435c9e10e5383e2445	text	{"t": "text", "name": "pytest: 未找到可用的 DeviceSession(提供 mobile_session fixture 或任何 DeviceSession funcarg),未采集证据"}	2026-11-08 20:18:08.550795+08	2026-11-08 20:18:08.550795+08
b181e9f4-6433-4e1b-9f8e-81a799fcf70d	540f2fa1-53f8-4e43-9841-8eb881a0c529	8dd151a4-cfdb-45be-8775-94a84b86c834	23	runner	7c86f35f7465b4b9d3a4dac947cde98d	text	{"t": "text", "name": "pytest: =========================== short test summary info ==========================="}	2026-11-08 20:18:08.553278+08	2026-11-08 20:18:08.553278+08
bdfe9ef1-7940-4d5e-9f0f-958a998eca31	540f2fa1-53f8-4e43-9841-8eb881a0c529	8dd151a4-cfdb-45be-8775-94a84b86c834	24	runner	adc9a8e80acfc7a833f1788e87f9b35e	text	{"t": "text", "name": "pytest: FAILED test_deliberate_failure.py::test_deliberate_assertion_failure_for_evidence"}	2026-11-08 20:18:08.555517+08	2026-11-08 20:18:08.555517+08
5de6ad7a-2233-4ec1-8be4-5a8ff74ff738	540f2fa1-53f8-4e43-9841-8eb881a0c529	8dd151a4-cfdb-45be-8775-94a84b86c834	25	runner	4c83e236fe9af681c00ac22d0ce75160	text	{"t": "text", "name": "pytest: 1 failed, 3 passed in 19.04s"}	2026-11-08 20:18:08.557805+08	2026-11-08 20:18:08.557805+08
c3623957-523c-4b3d-9d8b-ab23295634ef	540f2fa1-53f8-4e43-9841-8eb881a0c529	8dd151a4-cfdb-45be-8775-94a84b86c834	26	control	59a53405a9a5bb9fb8c8950280b2b5f6	heartbeat	{"pid": 33708, "stage": 2, "progress": 40}	2026-11-08 20:18:08.629475+08	2026-11-08 20:18:08.629475+08
2e3300b0-e4c7-42fa-96e0-4d4055e4220b	540f2fa1-53f8-4e43-9841-8eb881a0c529	8dd151a4-cfdb-45be-8775-94a84b86c834	28	runner	823ab843c052030dc847fd65a7fa48ee	stage	{"t": "stage", "name": "archive", "progress": 90}	2026-11-08 20:18:08.738724+08	2026-11-08 20:18:08.738724+08
5bb9a25e-2877-41d9-82ad-65d851e9f44f	540f2fa1-53f8-4e43-9841-8eb881a0c529	8dd151a4-cfdb-45be-8775-94a84b86c834	27	runtime	86d04ca58bb3ff6f5b1538fb37f27486	finish	{"cases": [{"outcome": "failed", "case_key": "code-copies.b475bb18efac4d05bd903281643a50c1.test_deliberate_failure::test_deliberate_assertion_failure_for_evidence", "duration_ms": 1, "error_summary": "AssertionError: 预期内的故意失败：用于验证失败结论与证据产物保留（release-readiness 02）\\nassert False"}, {"outcome": "passed", "case_key": "code-copies.b475bb18efac4d05bd903281643a50c1.test_smoke::test_session_is_bound_to_dispatch_device", "duration_ms": 1000, "error_summary": null}, {"outcome": "passed", "case_key": "code-copies.b475bb18efac4d05bd903281643a50c1.test_smoke::test_app_launches_and_screenshot_is_a_real_frame", "duration_ms": 2785, "error_summary": null}, {"outcome": "passed", "case_key": "code-copies.b475bb18efac4d05bd903281643a50c1.test_smoke::test_ui_stays_foreground_long_enough_for_perf_sampling", "duration_ms": 15085, "error_summary": null}], "junit": {"tests": 4, "errors": 0, "failed": 1, "present": true, "skipped": 0, "failures": 1}, "stage": "finish", "state": "completed", "reason": null, "outcome": "failed", "components": [{"kind": "ui", "state": "completed", "outcome": "failed", "reason_code": null}], "artifact_count": 4}	2026-11-08 20:18:08.719638+08	2026-11-08 20:18:08.719638+08
463e7203-d916-4d30-b4f3-573a813cb2aa	540f2fa1-53f8-4e43-9841-8eb881a0c529	8dd151a4-cfdb-45be-8775-94a84b86c834	29	runner	692e22638160fae7dbf68e8105fa3aab	stage	{"t": "stage", "name": "finalize", "stage": 3, "progress": 100}	2026-11-08 20:18:08.756197+08	2026-11-08 20:18:08.756197+08
83e79369-eadf-4925-a330-ab39d1d2a3ae	540f2fa1-53f8-4e43-9841-8eb881a0c529	8dd151a4-cfdb-45be-8775-94a84b86c834	30	runner	e5b6a08448914880782237811b79e7f4	result	{"t": "result", "fake": false, "files": 4, "junit": {"tests": 4, "errors": 0, "failed": 1, "present": true, "skipped": 0, "failures": 1, "parse_error": null}, "reason": "case_failure", "outcome": "failed"}	2026-11-08 20:18:08.759959+08	2026-11-08 20:18:08.759959+08
53df233d-f109-4a4f-b7dd-1fd3ac35ffb9	540f2fa1-53f8-4e43-9841-8eb881a0c529	ba117777-b04d-48e0-ba3d-7af289d66244	1	api	created	queued	{"source": "api", "request_key": "fff0db32-dda7-4990-8ae0-950f9c4748d9"}	2026-11-08 20:46:01.588043+08	2026-11-08 20:46:01.588043+08
03714ae8-cb3b-459e-a0b3-8b3c734898b9	540f2fa1-53f8-4e43-9841-8eb881a0c529	ba117777-b04d-48e0-ba3d-7af289d66244	2	dispatcher	9497d8417726e1259609022865242a25	lease_acquired	{"stage": "lease", "serial": "749622c9", "resource_id": "fab1ee61-4ece-4fc5-92bc-4bc0b13427a2", "fencing_token": 3}	2026-11-08 20:46:01.712036+08	2026-11-08 20:46:01.712036+08
2c1d975a-ab18-48e1-8ab6-8739294d7ec2	540f2fa1-53f8-4e43-9841-8eb881a0c529	ba117777-b04d-48e0-ba3d-7af289d66244	3	dispatcher	c5a53d24fda5417bdddbcfcd4bbcd7d4	identity_verified	{"note": "已核对设备上已安装包的包名/versionName/versionCode；未验证 APK 文件摘要", "stage": "identity", "detail": "versionName=15.0.14 与固定基准一致（仅核对安装包字段，未验证 APK 摘要）", "reason": "identity_match", "serial": "749622c9", "verdict": "verified", "package_name": "com.miui.calculator", "execution_allowed": true, "verification_level": "package_identity_observed", "apk_digest_verified": false, "expected_version_code": 315000014, "expected_version_name": "15.0.14", "observed_version_code": 315000014, "observed_version_name": "15.0.14"}	2026-11-08 20:46:02.051387+08	2026-11-08 20:46:02.051387+08
233f2d7c-2f08-420a-a9c9-b4b4bf04de6f	540f2fa1-53f8-4e43-9841-8eb881a0c529	ba117777-b04d-48e0-ba3d-7af289d66244	4	control	4950c5b0dd9bc9228e8a4bb064c00373	ack	{"pid": 11336, "stage": "ack", "progress": 5, "revision_id": "629f6c29-1023-4ecb-beec-4e866029493a"}	2026-11-08 20:46:02.197557+08	2026-11-08 20:46:02.197557+08
03c2f45b-56b0-4b98-8d75-6570e96e79a6	540f2fa1-53f8-4e43-9841-8eb881a0c529	ba117777-b04d-48e0-ba3d-7af289d66244	5	runner	1720038fd86cad42f439eff64f502a37	stage	{"t": "stage", "name": "lease", "progress": 10}	2026-11-08 20:46:02.241212+08	2026-11-08 20:46:02.241212+08
b9bedbcc-532d-415d-ae2c-ce4bb4f9d91f	540f2fa1-53f8-4e43-9841-8eb881a0c529	ba117777-b04d-48e0-ba3d-7af289d66244	6	runner	558ec76dce2d020f18c9aa6111645853	stage	{"t": "stage", "name": "ready", "progress": 20}	2026-11-08 20:46:02.244194+08	2026-11-08 20:46:02.244194+08
83a9d896-9c1c-4316-9f44-8ed3d01c7a74	540f2fa1-53f8-4e43-9841-8eb881a0c529	ba117777-b04d-48e0-ba3d-7af289d66244	7	runner	e182410ede54f5a771451da1b15c0784	text	{"t": "text", "name": "suite_copy", "targets": ["."], "suite_root": "D:\\\\workspace\\\\claudecode-test\\\\testplat-auto\\\\.runtime\\\\rr-verify\\\\data\\\\code-copies\\\\b475bb18efac4d05bd903281643a50c1", "tree_sha256": "86f5595fc981c237ac149cef560210020d47aef9f514830952a0df76500a9304", "suite_version_id": "0bfc19f5-96f6-499d-aa1b-3c97c8c720bb"}	2026-11-08 20:46:02.439815+08	2026-11-08 20:46:02.439815+08
f75ab9ba-8879-498d-bf8e-12804aa3359e	540f2fa1-53f8-4e43-9841-8eb881a0c529	ba117777-b04d-48e0-ba3d-7af289d66244	8	runner	ce8c582b618ad868048981b503067549	stage	{"t": "stage", "cwd": "D:\\\\workspace\\\\claudecode-test\\\\testplat-auto\\\\.runtime\\\\rr-verify\\\\data\\\\code-copies\\\\b475bb18efac4d05bd903281643a50c1", "argv": ["D:\\\\python312\\\\python.exe", "-m", "pytest", "--mobile-evidence", "--mobile-devices", "749622c9", "--mobile-config", "D:\\\\workspace\\\\claudecode-test\\\\testplat-auto\\\\.runtime\\\\rr-verify\\\\data\\\\artifacts\\\\ba117777-b04d-48e0-ba3d-7af289d66244\\\\mobile-config.toml", "-p", "testdock_runner.pytest_plugin", "-p", "no:mobile-perf", "-o", "addopts=", "--junit-xml", "D:\\\\workspace\\\\claudecode-test\\\\testplat-auto\\\\.runtime\\\\rr-verify\\\\data\\\\artifacts\\\\ba117777-b04d-48e0-ba3d-7af289d66244\\\\junit.xml", "-p", "no:cacheprovider", "-q", "."], "name": "pytest", "progress": 40}	2026-11-08 20:46:02.443219+08	2026-11-08 20:46:02.443219+08
d4a17e89-0f54-4ce8-af41-df217710d53f	540f2fa1-53f8-4e43-9841-8eb881a0c529	ba117777-b04d-48e0-ba3d-7af289d66244	9	control	736252e09812bb59405f5aff868a8d4f	heartbeat	{"pid": 11336, "stage": 2, "progress": 40}	2026-11-08 20:46:12.208224+08	2026-11-08 20:46:12.208224+08
ca40f821-3a8f-486b-b63e-0b516a99323c	540f2fa1-53f8-4e43-9841-8eb881a0c529	ba117777-b04d-48e0-ba3d-7af289d66244	10	control	9ca6ea7273a6f9b50dbc918000d60b63	heartbeat	{"pid": 11336, "stage": 2, "progress": 40}	2026-11-08 20:46:22.219814+08	2026-11-08 20:46:22.219814+08
1e52e223-b0ef-4d74-a107-da4057235843	540f2fa1-53f8-4e43-9841-8eb881a0c529	ba117777-b04d-48e0-ba3d-7af289d66244	11	runner	da629d834d195df5d9ae2e5dad277326	text	{"t": "text", "name": "pytest: F...                                                                     [100%]"}	2026-11-08 20:46:22.594397+08	2026-11-08 20:46:22.594397+08
fd50a820-0386-48b3-a20a-543885d515b3	540f2fa1-53f8-4e43-9841-8eb881a0c529	ba117777-b04d-48e0-ba3d-7af289d66244	12	runner	5255823b939a8f22ad8abc52670aeb6d	text	{"t": "text", "name": "pytest: ================================== FAILURES ==================================="}	2026-11-08 20:46:22.598469+08	2026-11-08 20:46:22.598469+08
c92996c9-72fd-4ca2-a116-f4db8cdd0563	540f2fa1-53f8-4e43-9841-8eb881a0c529	ba117777-b04d-48e0-ba3d-7af289d66244	13	runner	f1bc3b43d97c58b11c3bc835b951b9a7	text	{"t": "text", "name": "pytest: _______________ test_deliberate_assertion_failure_for_evidence ________________"}	2026-11-08 20:46:22.603113+08	2026-11-08 20:46:22.603113+08
b6a3b67b-90ff-4a11-9a4f-890155ac7576	540f2fa1-53f8-4e43-9841-8eb881a0c529	ba117777-b04d-48e0-ba3d-7af289d66244	14	runner	b3d983fed1a0fce1cd8e699d2f94159e	text	{"t": "text", "name": "pytest: "}	2026-11-08 20:46:22.606958+08	2026-11-08 20:46:22.606958+08
a4dd85cc-bf17-4f41-8dcf-e79748a96cb7	540f2fa1-53f8-4e43-9841-8eb881a0c529	ba117777-b04d-48e0-ba3d-7af289d66244	15	runner	06b922c026310740907f72e87320c428	text	{"t": "text", "name": "pytest:     def test_deliberate_assertion_failure_for_evidence():"}	2026-11-08 20:46:22.611055+08	2026-11-08 20:46:22.611055+08
b1a64750-c223-46b3-89c3-0b57bd55a7fe	540f2fa1-53f8-4e43-9841-8eb881a0c529	ba117777-b04d-48e0-ba3d-7af289d66244	16	runner	5454f95bbbcccfa83f5dfed188408043	text	{"t": "text", "name": "pytest:         \\"\\"\\"永远失败：进入报告的失败证据链路（预期内，非产品缺陷）。\\"\\"\\""}	2026-11-08 20:46:22.614816+08	2026-11-08 20:46:22.614816+08
f866dd5a-95fc-49ce-be2f-5889c8414edc	540f2fa1-53f8-4e43-9841-8eb881a0c529	ba117777-b04d-48e0-ba3d-7af289d66244	17	runner	24228f5bece9e0e7dc90ff20ca1fad0e	text	{"t": "text", "name": "pytest: >       assert False, \\"预期内的故意失败：用于验证失败结论与证据产物保留（release-readiness 02）\\""}	2026-11-08 20:46:22.618285+08	2026-11-08 20:46:22.618285+08
b1bafa11-ef85-438d-96d1-782aa5022119	540f2fa1-53f8-4e43-9841-8eb881a0c529	ba117777-b04d-48e0-ba3d-7af289d66244	18	runner	81908cf78d881e0d93603928a5bd0ae7	text	{"t": "text", "name": "pytest: E       AssertionError: 预期内的故意失败：用于验证失败结论与证据产物保留（release-readiness 02）"}	2026-11-08 20:46:22.621418+08	2026-11-08 20:46:22.621418+08
a6d814b7-a369-4236-9b9d-c38173ffad84	540f2fa1-53f8-4e43-9841-8eb881a0c529	ba117777-b04d-48e0-ba3d-7af289d66244	19	runner	f318693663e4b84f21d9999fb1a9359c	text	{"t": "text", "name": "pytest: E       assert False"}	2026-11-08 20:46:22.625209+08	2026-11-08 20:46:22.625209+08
c840078d-3344-486d-a419-2fbc4895a616	540f2fa1-53f8-4e43-9841-8eb881a0c529	ba117777-b04d-48e0-ba3d-7af289d66244	20	runner	5f68a25a9bcb33d10387fddbf83563b9	text	{"t": "text", "name": "pytest: "}	2026-11-08 20:46:22.628512+08	2026-11-08 20:46:22.628512+08
55ee78f3-c9c0-4f00-9df3-2cd177300d80	540f2fa1-53f8-4e43-9841-8eb881a0c529	ba117777-b04d-48e0-ba3d-7af289d66244	21	runner	3a77104f52c20a3a51689d775f528c5e	text	{"t": "text", "name": "pytest: test_deliberate_failure.py:12: AssertionError"}	2026-11-08 20:46:22.632304+08	2026-11-08 20:46:22.632304+08
630488cf-90ae-4981-999a-761dc47bd0ea	540f2fa1-53f8-4e43-9841-8eb881a0c529	ba117777-b04d-48e0-ba3d-7af289d66244	22	runner	e923c5dea494c581deb9efa45802c5e4	text	{"t": "text", "name": "pytest: ---------------------------- mobile-auto-evidence -----------------------------"}	2026-11-08 20:46:22.63822+08	2026-11-08 20:46:22.63822+08
3b00d95d-04ee-40a1-99ec-425e7c44a4ee	540f2fa1-53f8-4e43-9841-8eb881a0c529	ba117777-b04d-48e0-ba3d-7af289d66244	23	runner	5157219c6c79da0a645a27932e7ece9d	text	{"t": "text", "name": "pytest: 未找到可用的 DeviceSession(提供 mobile_session fixture 或任何 DeviceSession funcarg),未采集证据"}	2026-11-08 20:46:22.64402+08	2026-11-08 20:46:22.64402+08
371cbef3-e54f-4bb1-b800-de80e4e2fd8b	540f2fa1-53f8-4e43-9841-8eb881a0c529	ba117777-b04d-48e0-ba3d-7af289d66244	25	runner	fed712f08b485a6496f637bf3e0eca2c	text	{"t": "text", "name": "pytest: =========================== short test summary info ==========================="}	2026-11-08 20:46:22.71334+08	2026-11-08 20:46:22.71334+08
e87996c6-a48d-4949-81de-de4d3ea81e07	540f2fa1-53f8-4e43-9841-8eb881a0c529	ba117777-b04d-48e0-ba3d-7af289d66244	26	runner	8b2074d1a165e3fb1ed76a5de8ed3f79	text	{"t": "text", "name": "pytest: FAILED test_deliberate_failure.py::test_deliberate_assertion_failure_for_evidence"}	2026-11-08 20:46:22.746173+08	2026-11-08 20:46:22.746173+08
f0668324-6ff3-4a42-bd24-f21c5e66ba7a	540f2fa1-53f8-4e43-9841-8eb881a0c529	ba117777-b04d-48e0-ba3d-7af289d66244	24	runtime	dd30cf50d5353193d8d2b9cebd3c9723	finish	{"cases": [{"outcome": "failed", "case_key": "code-copies.b475bb18efac4d05bd903281643a50c1.test_deliberate_failure::test_deliberate_assertion_failure_for_evidence", "duration_ms": 1, "error_summary": "AssertionError: 预期内的故意失败：用于验证失败结论与证据产物保留（release-readiness 02）\\nassert False"}, {"outcome": "passed", "case_key": "code-copies.b475bb18efac4d05bd903281643a50c1.test_smoke::test_session_is_bound_to_dispatch_device", "duration_ms": 1428, "error_summary": null}, {"outcome": "passed", "case_key": "code-copies.b475bb18efac4d05bd903281643a50c1.test_smoke::test_app_launches_and_screenshot_is_a_real_frame", "duration_ms": 2663, "error_summary": null}, {"outcome": "passed", "case_key": "code-copies.b475bb18efac4d05bd903281643a50c1.test_smoke::test_ui_stays_foreground_long_enough_for_perf_sampling", "duration_ms": 15085, "error_summary": null}], "junit": {"tests": 4, "errors": 0, "failed": 1, "present": true, "skipped": 0, "failures": 1}, "stage": "finish", "state": "completed", "reason": null, "outcome": "failed", "components": [{"kind": "ui", "state": "completed", "outcome": "failed", "reason_code": null}], "artifact_count": 4}	2026-11-08 20:46:22.70876+08	2026-11-08 20:46:22.70876+08
0e7f7d6c-46e1-446d-a348-f1d1b1c60c5b	540f2fa1-53f8-4e43-9841-8eb881a0c529	ba117777-b04d-48e0-ba3d-7af289d66244	28	runner	c49b47ff0bbfc70fb23d5a6f61058586	stage	{"t": "stage", "name": "archive", "progress": 90}	2026-11-08 20:46:22.967138+08	2026-11-08 20:46:22.967138+08
8e781fd3-280f-4aca-906d-7f1462ac1c32	540f2fa1-53f8-4e43-9841-8eb881a0c529	ba117777-b04d-48e0-ba3d-7af289d66244	27	runner	3f48e0642e20bbdb23b3986f23174bb3	text	{"t": "text", "name": "pytest: 1 failed, 3 passed in 19.34s"}	2026-11-08 20:46:22.749597+08	2026-11-08 20:46:22.749597+08
96b35194-8f03-48be-bdaa-c3bb9efcf900	540f2fa1-53f8-4e43-9841-8eb881a0c529	ba117777-b04d-48e0-ba3d-7af289d66244	29	runner	9ab5a8c71470d1cce72a9b386b5ac4cc	stage	{"t": "stage", "name": "finalize", "stage": 3, "progress": 100}	2026-11-08 20:46:22.970598+08	2026-11-08 20:46:22.970598+08
1feb0c02-07c6-4919-84d6-d14dba729936	540f2fa1-53f8-4e43-9841-8eb881a0c529	ba117777-b04d-48e0-ba3d-7af289d66244	30	runner	365ed737cfb7f3f0e13685100252175f	result	{"t": "result", "fake": false, "files": 4, "junit": {"tests": 4, "errors": 0, "failed": 1, "present": true, "skipped": 0, "failures": 1, "parse_error": null}, "reason": "case_failure", "outcome": "failed"}	2026-11-08 20:46:22.974241+08	2026-11-08 20:46:22.974241+08
1ce6dc01-8fb2-4f15-b7d0-bcd7bb54e19b	540f2fa1-53f8-4e43-9841-8eb881a0c529	7ca839a0-d955-4a7e-aa64-290382c63453	1	api	created	queued	{"source": "api", "request_key": "1187cf1e-1cb6-4410-bc1d-cc46418c1cdb"}	2026-11-08 20:52:58.135038+08	2026-11-08 20:52:58.135038+08
788cfe27-bd9c-4afe-8785-d88abfba4274	540f2fa1-53f8-4e43-9841-8eb881a0c529	7ca839a0-d955-4a7e-aa64-290382c63453	2	dispatcher	71c58d401ad88cc138a558ceb5ffd035	lease_acquired	{"stage": "lease", "serial": "749622c9", "resource_id": "fab1ee61-4ece-4fc5-92bc-4bc0b13427a2", "fencing_token": 4}	2026-11-08 20:52:58.50594+08	2026-11-08 20:52:58.50594+08
f92d880e-cb27-4e30-b428-cfea1b2e65de	540f2fa1-53f8-4e43-9841-8eb881a0c529	7ca839a0-d955-4a7e-aa64-290382c63453	3	dispatcher	ffeed0615e79c1e83c8953908b447586	identity_verified	{"note": "已核对设备上已安装包的包名/versionName/versionCode；未验证 APK 文件摘要", "stage": "identity", "detail": "versionName=15.0.14 与固定基准一致（仅核对安装包字段，未验证 APK 摘要）", "reason": "identity_match", "serial": "749622c9", "verdict": "verified", "package_name": "com.miui.calculator", "execution_allowed": true, "verification_level": "package_identity_observed", "apk_digest_verified": false, "expected_version_code": 315000014, "expected_version_name": "15.0.14", "observed_version_code": 315000014, "observed_version_name": "15.0.14"}	2026-11-08 20:52:58.690786+08	2026-11-08 20:52:58.690786+08
07668102-4750-42c2-9571-d9471ca80802	540f2fa1-53f8-4e43-9841-8eb881a0c529	7ca839a0-d955-4a7e-aa64-290382c63453	4	control	5ad8c9c21184811a8b5a35d565821573	ack	{"pid": 32068, "stage": "ack", "progress": 5, "revision_id": "3af97316-61f7-403c-ae6c-e0f78590340b"}	2026-11-08 20:52:58.825284+08	2026-11-08 20:52:58.825284+08
a6f97d32-fe26-429b-9c59-da214ec57984	540f2fa1-53f8-4e43-9841-8eb881a0c529	7ca839a0-d955-4a7e-aa64-290382c63453	5	runner	b2b2021d46f57c510ab6fb3bfef775ac	stage	{"t": "stage", "name": "collect", "progress": 40}	2026-11-08 20:53:00.067579+08	2026-11-08 20:53:00.067579+08
ba291561-a855-4959-9d67-1d7edac63755	540f2fa1-53f8-4e43-9841-8eb881a0c529	7ca839a0-d955-4a7e-aa64-290382c63453	6	control	3b90d0a2dcaa9042f0039bd8be2ae334	heartbeat	{"pid": 32068, "stage": 2, "progress": 40}	2026-11-08 20:53:08.833019+08	2026-11-08 20:53:08.833019+08
27f0edf5-79d5-4ba6-9e88-d1ffb03fb92e	540f2fa1-53f8-4e43-9841-8eb881a0c529	7ca839a0-d955-4a7e-aa64-290382c63453	7	control	e95edccf56d74082e3204e6e5b77864d	heartbeat	{"pid": 32068, "stage": 2, "progress": 40}	2026-11-08 20:53:18.842146+08	2026-11-08 20:53:18.842146+08
be6b0f8f-8360-44fd-b5f5-81588b745375	540f2fa1-53f8-4e43-9841-8eb881a0c529	7ca839a0-d955-4a7e-aa64-290382c63453	8	control	6acab78409c8d5621a08a866f7b49440	heartbeat	{"pid": 32068, "stage": 2, "progress": 40}	2026-11-08 20:53:28.850399+08	2026-11-08 20:53:28.850399+08
7e708ce0-34ee-4c51-9fbe-276e610fe8f2	540f2fa1-53f8-4e43-9841-8eb881a0c529	7ca839a0-d955-4a7e-aa64-290382c63453	9	runtime	62c5ff1fff06d4cdc7b52f3700502a84	finish	{"cases": [], "junit": {"present": false}, "stage": "finish", "state": "completed", "reason": "gate_policy_missing", "outcome": "not_tested", "components": [{"kind": "performance", "state": "completed", "outcome": "not_tested", "reason_code": "gate_policy_missing"}], "artifact_count": 17}	2026-11-08 20:53:33.424816+08	2026-11-08 20:53:33.424816+08
48f88b2f-1354-49a7-b3a5-efe8cd2fe392	540f2fa1-53f8-4e43-9841-8eb881a0c529	7ca839a0-d955-4a7e-aa64-290382c63453	10	runner	5718a8de980fbfb0423453bba0883574	stage	{"t": "stage", "name": "finalize", "stage": 3, "progress": 100}	2026-11-08 20:53:33.487313+08	2026-11-08 20:53:33.487313+08
16f40ae7-e3ca-40ad-806a-adb25e8d12e3	540f2fa1-53f8-4e43-9841-8eb881a0c529	7ca839a0-d955-4a7e-aa64-290382c63453	11	runner	a048dcac638fea3f10ad2adb7e320420	result	{"t": "result", "fake": false, "files": 17, "junit": {}, "reason": "gate_policy_missing", "outcome": "not_tested"}	2026-11-08 20:53:33.526385+08	2026-11-08 20:53:33.526385+08
7860ec47-1c9a-48a9-8127-5dc2b5cc243e	540f2fa1-53f8-4e43-9841-8eb881a0c529	ec832d64-466a-437a-8dcc-6a2efb9eede6	1	api	created	queued	{"source": "api", "request_key": "5e5d2504-9ca4-4fd5-9334-fd2db969a2d4"}	2026-11-08 21:12:19.796903+08	2026-11-08 21:12:19.796903+08
8f4a9f3e-6bda-4df7-902e-9db2b50bb897	540f2fa1-53f8-4e43-9841-8eb881a0c529	ec832d64-466a-437a-8dcc-6a2efb9eede6	2	dispatcher	70d86ee375a5c7692f98c401a63f8aed	lease_acquired	{"stage": "lease", "serial": "749622c9", "resource_id": "fab1ee61-4ece-4fc5-92bc-4bc0b13427a2", "fencing_token": 5}	2026-11-08 21:12:21.511259+08	2026-11-08 21:12:21.511259+08
0d1f618c-5963-48b9-a71f-a423403069e0	540f2fa1-53f8-4e43-9841-8eb881a0c529	ec832d64-466a-437a-8dcc-6a2efb9eede6	3	dispatcher	78b2f3025bde40fc46be2f853613d6e0	identity_verified	{"note": "已核对设备上已安装包的包名/versionName/versionCode；未验证 APK 文件摘要", "stage": "identity", "detail": "versionName=15.0.14 与固定基准一致（仅核对安装包字段，未验证 APK 摘要）", "reason": "identity_match", "serial": "749622c9", "verdict": "verified", "package_name": "com.miui.calculator", "execution_allowed": true, "verification_level": "package_identity_observed", "apk_digest_verified": false, "expected_version_code": 315000014, "expected_version_name": "15.0.14", "observed_version_code": 315000014, "observed_version_name": "15.0.14"}	2026-11-08 21:12:21.691002+08	2026-11-08 21:12:21.691002+08
9286155c-4c6e-438a-aa69-a34d5a3f730b	540f2fa1-53f8-4e43-9841-8eb881a0c529	ec832d64-466a-437a-8dcc-6a2efb9eede6	4	control	773db3be4b63ea3db512ead59b5009dd	ack	{"pid": 24428, "stage": "ack", "progress": 5, "revision_id": "0440b605-94d6-4312-a161-1285f4d40c04"}	2026-11-08 21:12:21.821138+08	2026-11-08 21:12:21.821138+08
acb4caf7-3ede-40fd-9886-6d6d46f9c30f	540f2fa1-53f8-4e43-9841-8eb881a0c529	ec832d64-466a-437a-8dcc-6a2efb9eede6	5	runner	1739eb581c9478ecbe9cc640e4cf7d61	stage	{"t": "stage", "name": "perf_collect_start", "stage": 1, "progress": 10}	2026-11-08 21:12:21.905048+08	2026-11-08 21:12:21.905048+08
662eb000-e8a8-41e1-a02a-00b1460bd6a8	540f2fa1-53f8-4e43-9841-8eb881a0c529	ec832d64-466a-437a-8dcc-6a2efb9eede6	6	runner	c41039803a1a404524bc2ba63c8bed6d	stage	{"t": "stage", "name": "lease", "progress": 10}	2026-11-08 21:12:24.494911+08	2026-11-08 21:12:24.494911+08
90c58e02-04ee-4c3d-be6d-86729b45d08d	540f2fa1-53f8-4e43-9841-8eb881a0c529	ec832d64-466a-437a-8dcc-6a2efb9eede6	7	runner	7300176b23169015f6fc5af9602700e9	stage	{"t": "stage", "name": "ready", "progress": 20}	2026-11-08 21:12:24.497604+08	2026-11-08 21:12:24.497604+08
7de2d555-77e2-46fb-becc-da93e8a753f5	540f2fa1-53f8-4e43-9841-8eb881a0c529	ec832d64-466a-437a-8dcc-6a2efb9eede6	8	runner	e8b6c16f4f706cfabd8bdf36452e7672	text	{"t": "text", "name": "suite_copy", "targets": ["."], "suite_root": "D:\\\\workspace\\\\claudecode-test\\\\testplat-auto\\\\.runtime\\\\rr-verify\\\\data\\\\code-copies\\\\79eac297a75b4783af700a43bb8dabee", "tree_sha256": "86f5595fc981c237ac149cef560210020d47aef9f514830952a0df76500a9304", "suite_version_id": "d0b33707-1ba7-49fd-831a-29575869de14"}	2026-11-08 21:12:24.691591+08	2026-11-08 21:12:24.691591+08
e02d469e-7532-4d9e-8638-5d3363bc1383	540f2fa1-53f8-4e43-9841-8eb881a0c529	ec832d64-466a-437a-8dcc-6a2efb9eede6	9	runner	aa7be440026466f0721a2f3e68f9451a	stage	{"t": "stage", "cwd": "D:\\\\workspace\\\\claudecode-test\\\\testplat-auto\\\\.runtime\\\\rr-verify\\\\data\\\\code-copies\\\\79eac297a75b4783af700a43bb8dabee", "argv": ["D:\\\\python312\\\\python.exe", "-m", "pytest", "--mobile-evidence", "--mobile-devices", "749622c9", "--mobile-config", "D:\\\\workspace\\\\claudecode-test\\\\testplat-auto\\\\.runtime\\\\rr-verify\\\\data\\\\artifacts\\\\ec832d64-466a-437a-8dcc-6a2efb9eede6\\\\mobile-config.toml", "-p", "testdock_runner.pytest_plugin", "-p", "no:mobile-perf", "-o", "addopts=", "--junit-xml", "D:\\\\workspace\\\\claudecode-test\\\\testplat-auto\\\\.runtime\\\\rr-verify\\\\data\\\\artifacts\\\\ec832d64-466a-437a-8dcc-6a2efb9eede6\\\\junit.xml", "-p", "no:cacheprovider", "-q", "."], "name": "pytest", "progress": 40}	2026-11-08 21:12:24.69412+08	2026-11-08 21:12:24.69412+08
1938ef05-6556-40da-b72b-c28a70cf1caa	540f2fa1-53f8-4e43-9841-8eb881a0c529	ec832d64-466a-437a-8dcc-6a2efb9eede6	10	control	a230771558c73c3ffef0a67c021c21e0	heartbeat	{"pid": 24428, "stage": 2, "progress": 40}	2026-11-08 21:12:31.830696+08	2026-11-08 21:12:31.830696+08
062ac661-51aa-4668-b6ce-85bc7c1a28fc	540f2fa1-53f8-4e43-9841-8eb881a0c529	ec832d64-466a-437a-8dcc-6a2efb9eede6	11	control	2718141a2051a0852b713fa8548bba57	heartbeat	{"pid": 24428, "stage": 2, "progress": 40}	2026-11-08 21:12:41.836967+08	2026-11-08 21:12:41.836967+08
46169a53-0139-45c9-88fb-9f3c1416cdd8	540f2fa1-53f8-4e43-9841-8eb881a0c529	ec832d64-466a-437a-8dcc-6a2efb9eede6	12	runner	bf151f570fa6c126e504759229c04af6	text	{"t": "text", "name": "pytest: F...                                                                     [100%]"}	2026-11-08 21:12:44.053527+08	2026-11-08 21:12:44.053527+08
e63d7cea-00f6-4032-af82-ccfc46704559	540f2fa1-53f8-4e43-9841-8eb881a0c529	ec832d64-466a-437a-8dcc-6a2efb9eede6	13	runner	60c6b9573da4a7372933182c9d45940c	text	{"t": "text", "name": "pytest: ================================== FAILURES ==================================="}	2026-11-08 21:12:44.057061+08	2026-11-08 21:12:44.057061+08
d288fd09-bad9-44f2-8bd9-b4659d024be7	540f2fa1-53f8-4e43-9841-8eb881a0c529	ec832d64-466a-437a-8dcc-6a2efb9eede6	18	runner	121953f022cf949ea17a82a7eaa67464	text	{"t": "text", "name": "pytest: >       assert False, \\"预期内的故意失败：用于验证失败结论与证据产物保留（release-readiness 02）\\""}	2026-11-08 21:12:44.070992+08	2026-11-08 21:12:44.070992+08
1399146d-64a5-4f3c-9ad2-796ebfd68db0	540f2fa1-53f8-4e43-9841-8eb881a0c529	ec832d64-466a-437a-8dcc-6a2efb9eede6	23	runner	a7afdbaf69d9f9ab2592663baeeb6810	text	{"t": "text", "name": "pytest: ---------------------------- mobile-auto-evidence -----------------------------"}	2026-11-08 21:12:44.081808+08	2026-11-08 21:12:44.081808+08
07fd2eef-928f-4f82-8d71-8d28c933c1df	540f2fa1-53f8-4e43-9841-8eb881a0c529	ec832d64-466a-437a-8dcc-6a2efb9eede6	28	runner	bd9db8afdd8393d9f5444ca902a58166	stage	{"t": "stage", "name": "archive", "progress": 90}	2026-11-08 21:12:44.278297+08	2026-11-08 21:12:44.278297+08
106af6f3-ec18-419f-bdc0-aa282d70839a	540f2fa1-53f8-4e43-9841-8eb881a0c529	ec832d64-466a-437a-8dcc-6a2efb9eede6	30	runner	2e8939a393ff89e48b97c1be008d94ab	stage	{"t": "stage", "name": "perf_collect_stop", "stage": 2, "progress": 90}	2026-11-08 21:12:46.237955+08	2026-11-08 21:12:46.237955+08
f4894433-11b3-481a-9359-174493771dda	540f2fa1-53f8-4e43-9841-8eb881a0c529	b7899bcf-7d37-48ec-81be-0407340d0b03	2	dispatcher	c3a26c3f6468c3d85dfe98b0c24152f3	lease_acquired	{"stage": "lease", "serial": "749622c9", "resource_id": "fab1ee61-4ece-4fc5-92bc-4bc0b13427a2", "fencing_token": 6}	2026-11-08 21:14:57.886158+08	2026-11-08 21:14:57.886158+08
14343a59-7e2e-4bc9-b6f0-5a0c92646419	540f2fa1-53f8-4e43-9841-8eb881a0c529	b7899bcf-7d37-48ec-81be-0407340d0b03	7	runner	77e469cdcc875c728199b64dd93fc179	stage	{"t": "stage", "name": "ready", "progress": 20}	2026-11-08 21:15:00.893774+08	2026-11-08 21:15:00.893774+08
b452f09d-57b3-434e-b395-40dc7445f3c8	540f2fa1-53f8-4e43-9841-8eb881a0c529	b7899bcf-7d37-48ec-81be-0407340d0b03	11	control	cancel	cancel_requested	{"from_state": "dispatching", "requested_by": "web"}	2026-11-08 21:15:15.329637+08	2026-11-08 21:15:15.329637+08
ece763d8-b34c-4ee9-8bf8-f152aa35e710	540f2fa1-53f8-4e43-9841-8eb881a0c529	2b814545-aada-4196-90ae-706dbbaf4d76	5	runner	196fcc7e225d9f1c7dc1beb19e8bac60	stage	{"t": "stage", "name": "perf_collect_start", "stage": 1, "progress": 10}	2026-11-08 21:16:36.665413+08	2026-11-08 21:16:36.665413+08
b363ff86-d42f-42cc-a4a6-9c5a35c98c1d	540f2fa1-53f8-4e43-9841-8eb881a0c529	2b814545-aada-4196-90ae-706dbbaf4d76	10	runner	ba454af5e837639932721e4ff430ff57	stage	{"t": "stage", "cwd": "D:\\\\workspace\\\\claudecode-test\\\\testplat-auto\\\\.runtime\\\\rr-verify\\\\data\\\\code-copies\\\\79eac297a75b4783af700a43bb8dabee", "argv": ["D:\\\\python312\\\\python.exe", "-m", "pytest", "--mobile-evidence", "--mobile-devices", "749622c9", "--mobile-config", "D:\\\\workspace\\\\claudecode-test\\\\testplat-auto\\\\.runtime\\\\rr-verify\\\\data\\\\artifacts\\\\2b814545-aada-4196-90ae-706dbbaf4d76\\\\mobile-config.toml", "-p", "testdock_runner.pytest_plugin", "-p", "no:mobile-perf", "-o", "addopts=", "--junit-xml", "D:\\\\workspace\\\\claudecode-test\\\\testplat-auto\\\\.runtime\\\\rr-verify\\\\data\\\\artifacts\\\\2b814545-aada-4196-90ae-706dbbaf4d76\\\\junit.xml", "-p", "no:cacheprovider", "-q", "."], "name": "pytest", "progress": 40}	2026-11-08 21:16:40.888374+08	2026-11-08 21:16:40.888374+08
f1333ef1-4739-42b5-b5af-1cfdfbfd11bb	540f2fa1-53f8-4e43-9841-8eb881a0c529	ec832d64-466a-437a-8dcc-6a2efb9eede6	14	runner	13a33184a4a22e6fc923ae630f93f744	text	{"t": "text", "name": "pytest: _______________ test_deliberate_assertion_failure_for_evidence ________________"}	2026-11-08 21:12:44.060063+08	2026-11-08 21:12:44.060063+08
b3f65ee7-8ecd-4074-8764-10ac20007bd0	540f2fa1-53f8-4e43-9841-8eb881a0c529	ec832d64-466a-437a-8dcc-6a2efb9eede6	19	runner	daae6749715e325a3463e6e01f4cd100	text	{"t": "text", "name": "pytest: E       AssertionError: 预期内的故意失败：用于验证失败结论与证据产物保留（release-readiness 02）"}	2026-11-08 21:12:44.073433+08	2026-11-08 21:12:44.073433+08
b0a8ac14-b211-4562-9d37-4bdc898fff59	540f2fa1-53f8-4e43-9841-8eb881a0c529	ec832d64-466a-437a-8dcc-6a2efb9eede6	24	runner	438c1e8746b998399e0722a3a29df386	text	{"t": "text", "name": "pytest: 未找到可用的 DeviceSession(提供 mobile_session fixture 或任何 DeviceSession funcarg),未采集证据"}	2026-11-08 21:12:44.08415+08	2026-11-08 21:12:44.08415+08
ea41da52-ba6e-4bf9-bd11-0111dd38dbb9	540f2fa1-53f8-4e43-9841-8eb881a0c529	2b814545-aada-4196-90ae-706dbbaf4d76	4	control	6f67a7619692d4aed7d6952fba8b1fb0	ack	{"pid": 25096, "stage": "ack", "progress": 5, "revision_id": "0440b605-94d6-4312-a161-1285f4d40c04"}	2026-11-08 21:16:36.582881+08	2026-11-08 21:16:36.582881+08
c1905553-d6af-4ae2-b248-afcb2cf7745f	540f2fa1-53f8-4e43-9841-8eb881a0c529	2b814545-aada-4196-90ae-706dbbaf4d76	8	runner	75a74d93f984b177d6b27e808af769ac	stage	{"t": "stage", "name": "ready", "progress": 20}	2026-11-08 21:16:40.87868+08	2026-11-08 21:16:40.87868+08
52867413-a53a-46aa-900a-2b4357833bab	540f2fa1-53f8-4e43-9841-8eb881a0c529	ec832d64-466a-437a-8dcc-6a2efb9eede6	15	runner	11f69e3e1e19d4a26603edd0f04742dc	text	{"t": "text", "name": "pytest: "}	2026-11-08 21:12:44.062397+08	2026-11-08 21:12:44.062397+08
cf3b8c1f-a3bb-4756-9ce5-ff3d96c57dcc	540f2fa1-53f8-4e43-9841-8eb881a0c529	ec832d64-466a-437a-8dcc-6a2efb9eede6	20	runner	32d94ea12c2b94b31a3dba4ec0a5422a	text	{"t": "text", "name": "pytest: E       assert False"}	2026-11-08 21:12:44.075473+08	2026-11-08 21:12:44.075473+08
eb7f7310-6064-4d73-8148-d0a46a02d259	540f2fa1-53f8-4e43-9841-8eb881a0c529	ec832d64-466a-437a-8dcc-6a2efb9eede6	25	runner	8eb836944372baa7b2836d490ea37d9e	text	{"t": "text", "name": "pytest: =========================== short test summary info ==========================="}	2026-11-08 21:12:44.086316+08	2026-11-08 21:12:44.086316+08
0e648b82-080a-4f5c-8d2d-121a0d85ad5c	540f2fa1-53f8-4e43-9841-8eb881a0c529	ec832d64-466a-437a-8dcc-6a2efb9eede6	31	runner	ba61ee4a78fe9acdc29fe38c3d90c339	stage	{"t": "stage", "name": "finalize", "stage": 3, "progress": 100}	2026-11-08 21:12:46.378669+08	2026-11-08 21:12:46.378669+08
77934c63-8b83-4aab-825f-9d28e7145727	540f2fa1-53f8-4e43-9841-8eb881a0c529	b7899bcf-7d37-48ec-81be-0407340d0b03	4	control	f5141d68e7930eb1c38f6680ee3eeb26	ack	{"pid": 2556, "stage": "ack", "progress": 5, "revision_id": "0440b605-94d6-4312-a161-1285f4d40c04"}	2026-11-08 21:14:58.224475+08	2026-11-08 21:14:58.224475+08
9e43b645-74c6-4720-97c1-e7402f6b4b56	540f2fa1-53f8-4e43-9841-8eb881a0c529	b7899bcf-7d37-48ec-81be-0407340d0b03	6	runner	7d9471970e654b71271525b137860fda	stage	{"t": "stage", "name": "lease", "progress": 10}	2026-11-08 21:15:00.890125+08	2026-11-08 21:15:00.890125+08
6f1f603b-4099-487d-b37e-36d1ac1b6572	540f2fa1-53f8-4e43-9841-8eb881a0c529	2b814545-aada-4196-90ae-706dbbaf4d76	2	dispatcher	513cefe0e1d9c6df4dc82420cb6bcc87	lease_acquired	{"stage": "lease", "serial": "749622c9", "resource_id": "fab1ee61-4ece-4fc5-92bc-4bc0b13427a2", "fencing_token": 7}	2026-11-08 21:16:36.281681+08	2026-11-08 21:16:36.281681+08
ba801775-1f94-4385-b735-bae01f00b326	540f2fa1-53f8-4e43-9841-8eb881a0c529	2b814545-aada-4196-90ae-706dbbaf4d76	9	runner	606da57d914e5e7a8aab1166f2456e54	text	{"t": "text", "name": "suite_copy", "targets": ["."], "suite_root": "D:\\\\workspace\\\\claudecode-test\\\\testplat-auto\\\\.runtime\\\\rr-verify\\\\data\\\\code-copies\\\\79eac297a75b4783af700a43bb8dabee", "tree_sha256": "86f5595fc981c237ac149cef560210020d47aef9f514830952a0df76500a9304", "suite_version_id": "d0b33707-1ba7-49fd-831a-29575869de14"}	2026-11-08 21:16:40.883683+08	2026-11-08 21:16:40.883683+08
f244c469-fd74-4186-9cd3-8b4d0b0612ae	540f2fa1-53f8-4e43-9841-8eb881a0c529	2b814545-aada-4196-90ae-706dbbaf4d76	11	control	d76414fc8298435c578bd156c8ff523f	heartbeat	{"pid": 25096, "stage": 2, "progress": 40}	2026-11-08 21:16:46.591497+08	2026-11-08 21:16:46.591497+08
edd4e8d2-8979-4906-8208-4636d683e6f1	540f2fa1-53f8-4e43-9841-8eb881a0c529	ec832d64-466a-437a-8dcc-6a2efb9eede6	16	runner	6600a1605cc3137cadf1f75eba4a4d68	text	{"t": "text", "name": "pytest:     def test_deliberate_assertion_failure_for_evidence():"}	2026-11-08 21:12:44.065424+08	2026-11-08 21:12:44.065424+08
d05e5728-75e8-4ce1-bc58-1f855904522b	540f2fa1-53f8-4e43-9841-8eb881a0c529	ec832d64-466a-437a-8dcc-6a2efb9eede6	21	runner	6acb76070bca1624c999aa06caca0a7a	text	{"t": "text", "name": "pytest: "}	2026-11-08 21:12:44.077646+08	2026-11-08 21:12:44.077646+08
2f3981aa-aced-4490-b718-74032d4cf350	540f2fa1-53f8-4e43-9841-8eb881a0c529	ec832d64-466a-437a-8dcc-6a2efb9eede6	26	runner	a7d43c0679d617cabaf84b5eb06e6ce3	text	{"t": "text", "name": "pytest: FAILED test_deliberate_failure.py::test_deliberate_assertion_failure_for_evidence"}	2026-11-08 21:12:44.089198+08	2026-11-08 21:12:44.089198+08
1eb208ea-77a7-4be0-8679-fa6ccf7a7bb9	540f2fa1-53f8-4e43-9841-8eb881a0c529	ec832d64-466a-437a-8dcc-6a2efb9eede6	32	runner	d2db1f42dd91c82a41b2179cc8068d11	result	{"t": "result", "fake": false, "files": 4, "junit": {"tests": 4, "errors": 0, "failed": 1, "present": true, "skipped": 0, "failures": 1, "parse_error": null}, "reason": "case_failure", "outcome": "failed"}	2026-11-08 21:12:46.382576+08	2026-11-08 21:12:46.382576+08
444f5cbe-35f0-4afa-bcdf-07ba78a8e80d	540f2fa1-53f8-4e43-9841-8eb881a0c529	b7899bcf-7d37-48ec-81be-0407340d0b03	1	api	created	queued	{"source": "api", "request_key": "9570973b-c3ac-4246-847c-3909a013aa4d"}	2026-11-08 21:14:57.103059+08	2026-11-08 21:14:57.103059+08
036412ab-6957-4331-b456-178c0a4b89a1	540f2fa1-53f8-4e43-9841-8eb881a0c529	b7899bcf-7d37-48ec-81be-0407340d0b03	3	dispatcher	3e0e074d84e01e5573791024f47c9f7b	identity_verified	{"note": "已核对设备上已安装包的包名/versionName/versionCode；未验证 APK 文件摘要", "stage": "identity", "detail": "versionName=15.0.14 与固定基准一致（仅核对安装包字段，未验证 APK 摘要）", "reason": "identity_match", "serial": "749622c9", "verdict": "verified", "package_name": "com.miui.calculator", "execution_allowed": true, "verification_level": "package_identity_observed", "apk_digest_verified": false, "expected_version_code": 315000014, "expected_version_name": "15.0.14", "observed_version_code": 315000014, "observed_version_name": "15.0.14"}	2026-11-08 21:14:58.086365+08	2026-11-08 21:14:58.086365+08
2a0ca170-dca9-4243-901f-eea502f7a374	540f2fa1-53f8-4e43-9841-8eb881a0c529	b7899bcf-7d37-48ec-81be-0407340d0b03	9	runner	70fdea13ce6d413f1a4154fe01fead96	stage	{"t": "stage", "cwd": "D:\\\\workspace\\\\claudecode-test\\\\testplat-auto\\\\.runtime\\\\rr-verify\\\\data\\\\code-copies\\\\79eac297a75b4783af700a43bb8dabee", "argv": ["D:\\\\python312\\\\python.exe", "-m", "pytest", "--mobile-evidence", "--mobile-devices", "749622c9", "--mobile-config", "D:\\\\workspace\\\\claudecode-test\\\\testplat-auto\\\\.runtime\\\\rr-verify\\\\data\\\\artifacts\\\\b7899bcf-7d37-48ec-81be-0407340d0b03\\\\mobile-config.toml", "-p", "testdock_runner.pytest_plugin", "-p", "no:mobile-perf", "-o", "addopts=", "--junit-xml", "D:\\\\workspace\\\\claudecode-test\\\\testplat-auto\\\\.runtime\\\\rr-verify\\\\data\\\\artifacts\\\\b7899bcf-7d37-48ec-81be-0407340d0b03\\\\junit.xml", "-p", "no:cacheprovider", "-q", "."], "name": "pytest", "progress": 40}	2026-11-08 21:15:00.901066+08	2026-11-08 21:15:00.901066+08
410f2c5d-8c0b-4fbb-9167-4cf06e87e68e	540f2fa1-53f8-4e43-9841-8eb881a0c529	b7899bcf-7d37-48ec-81be-0407340d0b03	10	control	20239cdac05294b8b454f8d4abb7cca0	heartbeat	{"pid": 2556, "stage": 2, "progress": 40}	2026-11-08 21:15:08.24699+08	2026-11-08 21:15:08.24699+08
27801cf5-99d5-4a95-9a4a-e0e4a9b04aa3	540f2fa1-53f8-4e43-9841-8eb881a0c529	b7899bcf-7d37-48ec-81be-0407340d0b03	12	runtime	fd002d428bebe2b87d693706e9cc572c	finish	{"junit": {"present": false}, "stage": "finish", "state": "cancelled", "reason": "cancel_requested", "outcome": null, "artifact_count": 3, "runner_terminated": true, "cancel_requested_by": "web"}	2026-11-08 21:15:15.668193+08	2026-11-08 21:15:15.668193+08
03ed7f39-c8da-43b0-afef-4f526be5f64d	540f2fa1-53f8-4e43-9841-8eb881a0c529	2b814545-aada-4196-90ae-706dbbaf4d76	1	api	created	queued	{"source": "api", "request_key": "rr-joint-complete-1794143794"}	2026-11-08 21:16:34.267508+08	2026-11-08 21:16:34.267508+08
a6fdae87-063f-4204-8fd4-79c076c4ceb8	540f2fa1-53f8-4e43-9841-8eb881a0c529	2b814545-aada-4196-90ae-706dbbaf4d76	6	runner	a03d81cf5000ce294f0f65e412c6c280	text	{"t": "text", "name": "perf_stale_recording_stopped", "target": "com.miui.calculator", "session_id": "df9de05f-18a6-4ff8-abc0-434400aed344", "duration_ms": 97318}	2026-11-08 21:16:39.058138+08	2026-11-08 21:16:39.058138+08
6f40f40a-0677-4549-9391-a4ac7310e662	540f2fa1-53f8-4e43-9841-8eb881a0c529	2b814545-aada-4196-90ae-706dbbaf4d76	7	runner	39950bdc4236e5dc895ca6d718b6ac2f	stage	{"t": "stage", "name": "lease", "progress": 10}	2026-11-08 21:16:40.874268+08	2026-11-08 21:16:40.874268+08
66a5b2a2-69cd-4983-8187-4bb59bcd357c	540f2fa1-53f8-4e43-9841-8eb881a0c529	2b814545-aada-4196-90ae-706dbbaf4d76	12	control	9adcc1d8a2e22ad3333e9193f941055f	heartbeat	{"pid": 25096, "stage": 2, "progress": 40}	2026-11-08 21:16:56.602096+08	2026-11-08 21:16:56.602096+08
eb271730-68d9-44a8-816d-5fd6f460422b	540f2fa1-53f8-4e43-9841-8eb881a0c529	ec832d64-466a-437a-8dcc-6a2efb9eede6	17	runner	7f5cc2d159fcc9827629977a68792864	text	{"t": "text", "name": "pytest:         \\"\\"\\"永远失败：进入报告的失败证据链路（预期内，非产品缺陷）。\\"\\"\\""}	2026-11-08 21:12:44.068126+08	2026-11-08 21:12:44.068126+08
cf4dc5f2-d0fc-435a-be54-e8782f544668	540f2fa1-53f8-4e43-9841-8eb881a0c529	ec832d64-466a-437a-8dcc-6a2efb9eede6	22	runner	692d256b260a225144cdb903f7c826db	text	{"t": "text", "name": "pytest: test_deliberate_failure.py:12: AssertionError"}	2026-11-08 21:12:44.079571+08	2026-11-08 21:12:44.079571+08
2def0aaa-93c9-4fb5-bf2d-e242e23cef59	540f2fa1-53f8-4e43-9841-8eb881a0c529	ec832d64-466a-437a-8dcc-6a2efb9eede6	27	runner	10e89660dafbf126307524184659a6a7	text	{"t": "text", "name": "pytest: 1 failed, 3 passed in 18.68s"}	2026-11-08 21:12:44.091375+08	2026-11-08 21:12:44.091375+08
4b76d968-ce39-4aba-aa7f-7804bd650ea3	540f2fa1-53f8-4e43-9841-8eb881a0c529	ec832d64-466a-437a-8dcc-6a2efb9eede6	29	runtime	53b06295f6c91c759b5ca5802bf359e9	finish	{"cases": [{"outcome": "failed", "case_key": "code-copies.79eac297a75b4783af700a43bb8dabee.test_deliberate_failure::test_deliberate_assertion_failure_for_evidence", "duration_ms": 1, "error_summary": "AssertionError: 预期内的故意失败：用于验证失败结论与证据产物保留（release-readiness 02）\\nassert False"}, {"outcome": "passed", "case_key": "code-copies.79eac297a75b4783af700a43bb8dabee.test_smoke::test_session_is_bound_to_dispatch_device", "duration_ms": 907, "error_summary": null}, {"outcome": "passed", "case_key": "code-copies.79eac297a75b4783af700a43bb8dabee.test_smoke::test_app_launches_and_screenshot_is_a_real_frame", "duration_ms": 2533, "error_summary": null}, {"outcome": "passed", "case_key": "code-copies.79eac297a75b4783af700a43bb8dabee.test_smoke::test_ui_stays_foreground_long_enough_for_perf_sampling", "duration_ms": 15079, "error_summary": null}], "junit": {"tests": 4, "errors": 0, "failed": 1, "present": true, "skipped": 0, "failures": 1}, "stage": "finish", "state": "completed", "reason": null, "outcome": "failed", "components": [{"kind": "ui", "state": "completed", "outcome": "failed", "reason_code": null}, {"kind": "performance", "state": "completed"}], "artifact_count": 24}	2026-11-08 21:12:46.205621+08	2026-11-08 21:12:46.205621+08
914b73ab-8fb2-40d8-b5ec-6c7a6498649d	540f2fa1-53f8-4e43-9841-8eb881a0c529	b7899bcf-7d37-48ec-81be-0407340d0b03	5	runner	68e1db174764689b6a46c8de27528755	stage	{"t": "stage", "name": "perf_collect_start", "stage": 1, "progress": 10}	2026-11-08 21:14:58.291017+08	2026-11-08 21:14:58.291017+08
dde90a96-ef7b-43f7-a6b1-6f9fd79909f8	540f2fa1-53f8-4e43-9841-8eb881a0c529	b7899bcf-7d37-48ec-81be-0407340d0b03	8	runner	f9136943ef5995d86d698be5ad517e29	text	{"t": "text", "name": "suite_copy", "targets": ["."], "suite_root": "D:\\\\workspace\\\\claudecode-test\\\\testplat-auto\\\\.runtime\\\\rr-verify\\\\data\\\\code-copies\\\\79eac297a75b4783af700a43bb8dabee", "tree_sha256": "86f5595fc981c237ac149cef560210020d47aef9f514830952a0df76500a9304", "suite_version_id": "d0b33707-1ba7-49fd-831a-29575869de14"}	2026-11-08 21:15:00.897423+08	2026-11-08 21:15:00.897423+08
f85b216b-4624-457e-8eb0-1ba61b9eb252	540f2fa1-53f8-4e43-9841-8eb881a0c529	2b814545-aada-4196-90ae-706dbbaf4d76	3	dispatcher	6fc9a6817b445ddce8b385e688bbf156	identity_verified	{"note": "已核对设备上已安装包的包名/versionName/versionCode；未验证 APK 文件摘要", "stage": "identity", "detail": "versionName=15.0.14 与固定基准一致（仅核对安装包字段，未验证 APK 摘要）", "reason": "identity_match", "serial": "749622c9", "verdict": "verified", "package_name": "com.miui.calculator", "execution_allowed": true, "verification_level": "package_identity_observed", "apk_digest_verified": false, "expected_version_code": 315000014, "expected_version_name": "15.0.14", "observed_version_code": 315000014, "observed_version_name": "15.0.14"}	2026-11-08 21:16:36.452097+08	2026-11-08 21:16:36.452097+08
c9c2e5b4-ebf5-4987-8010-a7eb811fb0ce	540f2fa1-53f8-4e43-9841-8eb881a0c529	2b814545-aada-4196-90ae-706dbbaf4d76	13	runner	b91a12778735980f0d22817b5463e234	text	{"t": "text", "name": "pytest: F...                                                                     [100%]"}	2026-11-08 21:17:00.74085+08	2026-11-08 21:17:00.74085+08
5d026363-7e29-4004-8827-98d560b32a70	540f2fa1-53f8-4e43-9841-8eb881a0c529	2b814545-aada-4196-90ae-706dbbaf4d76	14	runner	43ae31af89c021c47031d25f00a8933c	text	{"t": "text", "name": "pytest: ================================== FAILURES ==================================="}	2026-11-08 21:17:00.748881+08	2026-11-08 21:17:00.748881+08
b407ddff-a7d0-4b90-a942-4d733e9e373c	540f2fa1-53f8-4e43-9841-8eb881a0c529	2b814545-aada-4196-90ae-706dbbaf4d76	15	runner	d68785fad69784ee326c78416e613515	text	{"t": "text", "name": "pytest: _______________ test_deliberate_assertion_failure_for_evidence ________________"}	2026-11-08 21:17:00.753894+08	2026-11-08 21:17:00.753894+08
ed084285-5fe6-4b0e-a295-08c2a868afaa	540f2fa1-53f8-4e43-9841-8eb881a0c529	2b814545-aada-4196-90ae-706dbbaf4d76	16	runner	6483ffd3edebaef737c3284ec030d897	text	{"t": "text", "name": "pytest: "}	2026-11-08 21:17:00.758862+08	2026-11-08 21:17:00.758862+08
d88b0216-2d9f-4157-a41d-d5751b709a0c	540f2fa1-53f8-4e43-9841-8eb881a0c529	2b814545-aada-4196-90ae-706dbbaf4d76	17	runner	fc7b65a4fe338865c8f999097009eb11	text	{"t": "text", "name": "pytest:     def test_deliberate_assertion_failure_for_evidence():"}	2026-11-08 21:17:00.763115+08	2026-11-08 21:17:00.763115+08
c6d0f2a3-81aa-4e4f-8b1e-bd2bf5ed6aef	540f2fa1-53f8-4e43-9841-8eb881a0c529	2b814545-aada-4196-90ae-706dbbaf4d76	18	runner	90cdb866c1d48c9b3090f72ee9db42e8	text	{"t": "text", "name": "pytest:         \\"\\"\\"永远失败：进入报告的失败证据链路（预期内，非产品缺陷）。\\"\\"\\""}	2026-11-08 21:17:00.767448+08	2026-11-08 21:17:00.767448+08
1ab4f81d-a929-4833-bd15-3d4883e4be68	540f2fa1-53f8-4e43-9841-8eb881a0c529	2b814545-aada-4196-90ae-706dbbaf4d76	19	runner	0d9111f56f1356c144332debdb0398be	text	{"t": "text", "name": "pytest: >       assert False, \\"预期内的故意失败：用于验证失败结论与证据产物保留（release-readiness 02）\\""}	2026-11-08 21:17:00.770686+08	2026-11-08 21:17:00.770686+08
1033bf05-e6dd-45d7-8068-82380079a2bf	540f2fa1-53f8-4e43-9841-8eb881a0c529	2b814545-aada-4196-90ae-706dbbaf4d76	20	runner	a76095c868b2728f7fe78664aab8f706	text	{"t": "text", "name": "pytest: E       AssertionError: 预期内的故意失败：用于验证失败结论与证据产物保留（release-readiness 02）"}	2026-11-08 21:17:00.773538+08	2026-11-08 21:17:00.773538+08
7855e841-99f8-401c-ad03-6ce5ecc3f6b2	540f2fa1-53f8-4e43-9841-8eb881a0c529	2b814545-aada-4196-90ae-706dbbaf4d76	21	runner	6a75063eb46c342839180839ea255e4a	text	{"t": "text", "name": "pytest: E       assert False"}	2026-11-08 21:17:00.776343+08	2026-11-08 21:17:00.776343+08
525fb88c-85e1-4a58-b0f8-14a1ae9f4f85	540f2fa1-53f8-4e43-9841-8eb881a0c529	2b814545-aada-4196-90ae-706dbbaf4d76	22	runner	46f4336040558fc4c8b29be318fc8c81	text	{"t": "text", "name": "pytest: "}	2026-11-08 21:17:00.779179+08	2026-11-08 21:17:00.779179+08
55f14736-8e4d-4376-a194-fa4669ba1c92	540f2fa1-53f8-4e43-9841-8eb881a0c529	2b814545-aada-4196-90ae-706dbbaf4d76	23	runner	ebc7a8ae67cc8081558310f167532a00	text	{"t": "text", "name": "pytest: test_deliberate_failure.py:12: AssertionError"}	2026-11-08 21:17:00.783094+08	2026-11-08 21:17:00.783094+08
711af0d0-29a1-47c6-83a9-86c7cdc68649	540f2fa1-53f8-4e43-9841-8eb881a0c529	2b814545-aada-4196-90ae-706dbbaf4d76	24	runner	187a502cd22fa505bcbc658419b1383a	text	{"t": "text", "name": "pytest: ---------------------------- mobile-auto-evidence -----------------------------"}	2026-11-08 21:17:00.786594+08	2026-11-08 21:17:00.786594+08
93b3d2c8-9385-4618-a505-ecec4557e744	540f2fa1-53f8-4e43-9841-8eb881a0c529	2b814545-aada-4196-90ae-706dbbaf4d76	25	runner	298c3ae137eddefedb7876fec0051c21	text	{"t": "text", "name": "pytest: 未找到可用的 DeviceSession(提供 mobile_session fixture 或任何 DeviceSession funcarg),未采集证据"}	2026-11-08 21:17:00.790663+08	2026-11-08 21:17:00.790663+08
33f13eb2-1bed-42d0-820a-71f53edb1315	540f2fa1-53f8-4e43-9841-8eb881a0c529	2b814545-aada-4196-90ae-706dbbaf4d76	26	runner	c2d3f05305021692878fff07f6aa874f	text	{"t": "text", "name": "pytest: =========================== short test summary info ==========================="}	2026-11-08 21:17:00.794829+08	2026-11-08 21:17:00.794829+08
437a4216-2245-40a5-9749-5057544b914f	540f2fa1-53f8-4e43-9841-8eb881a0c529	2b814545-aada-4196-90ae-706dbbaf4d76	27	runner	1eb33d7519af0307f9825efb14767ace	text	{"t": "text", "name": "pytest: FAILED test_deliberate_failure.py::test_deliberate_assertion_failure_for_evidence"}	2026-11-08 21:17:00.798539+08	2026-11-08 21:17:00.798539+08
9c1e6fa4-26d8-426a-8172-9d5cbdb38813	540f2fa1-53f8-4e43-9841-8eb881a0c529	2b814545-aada-4196-90ae-706dbbaf4d76	28	runner	27dbc7b65c7273361a65d6e99f49657c	text	{"t": "text", "name": "pytest: 1 failed, 3 passed in 18.90s"}	2026-11-08 21:17:00.802077+08	2026-11-08 21:17:00.802077+08
0431b7c6-5a33-40a5-8bf9-c2328b5d87a3	540f2fa1-53f8-4e43-9841-8eb881a0c529	2b814545-aada-4196-90ae-706dbbaf4d76	29	runner	8f6a95ce2eba914e6eb3ba772fb80380	stage	{"t": "stage", "name": "archive", "progress": 90}	2026-11-08 21:17:01.002518+08	2026-11-08 21:17:01.002518+08
ddacf147-8a4e-42cb-99fa-4b9bd83382f1	540f2fa1-53f8-4e43-9841-8eb881a0c529	2b814545-aada-4196-90ae-706dbbaf4d76	30	runtime	d52c787a76c9818eea5536eb1aa77af2	finish	{"cases": [{"outcome": "failed", "case_key": "code-copies.79eac297a75b4783af700a43bb8dabee.test_deliberate_failure::test_deliberate_assertion_failure_for_evidence", "duration_ms": 1, "error_summary": "AssertionError: 预期内的故意失败：用于验证失败结论与证据产物保留（release-readiness 02）\\nassert False"}, {"outcome": "passed", "case_key": "code-copies.79eac297a75b4783af700a43bb8dabee.test_smoke::test_session_is_bound_to_dispatch_device", "duration_ms": 918, "error_summary": null}, {"outcome": "passed", "case_key": "code-copies.79eac297a75b4783af700a43bb8dabee.test_smoke::test_app_launches_and_screenshot_is_a_real_frame", "duration_ms": 2665, "error_summary": null}, {"outcome": "passed", "case_key": "code-copies.79eac297a75b4783af700a43bb8dabee.test_smoke::test_ui_stays_foreground_long_enough_for_perf_sampling", "duration_ms": 15092, "error_summary": null}], "junit": {"tests": 4, "errors": 0, "failed": 1, "present": true, "skipped": 0, "failures": 1}, "stage": "finish", "state": "completed", "reason": null, "outcome": "failed", "components": [{"kind": "ui", "state": "completed", "outcome": "failed", "reason_code": null}, {"kind": "performance", "state": "completed"}], "artifact_count": 24}	2026-11-08 21:17:03.102559+08	2026-11-08 21:17:03.102559+08
3991d52d-2951-4f51-abc9-4a74d0690d57	540f2fa1-53f8-4e43-9841-8eb881a0c529	99e0459d-5d6d-40ec-9d33-7d4848664a0f	3	dispatcher	74a0fa4196ee16006a058a00057d05ce	identity_verified	{"note": "已核对设备上已安装包的包名/versionName/versionCode；未验证 APK 文件摘要", "stage": "identity", "detail": "versionName=15.0.14 与固定基准一致（仅核对安装包字段，未验证 APK 摘要）", "reason": "identity_match", "serial": "749622c9", "verdict": "verified", "package_name": "com.miui.calculator", "execution_allowed": true, "verification_level": "package_identity_observed", "apk_digest_verified": false, "expected_version_code": 315000014, "expected_version_name": "15.0.14", "observed_version_code": 315000014, "observed_version_name": "15.0.14"}	2026-11-08 21:21:31.19914+08	2026-11-08 21:21:31.19914+08
78cd6816-3384-4b2b-8ae0-1795b4b3333f	540f2fa1-53f8-4e43-9841-8eb881a0c529	99e0459d-5d6d-40ec-9d33-7d4848664a0f	9	runner	e8150d02fb2589013cba860d687951ae	stage	{"t": "stage", "cwd": "D:\\\\workspace\\\\claudecode-test\\\\testplat-auto\\\\.runtime\\\\rr-verify\\\\data\\\\code-copies\\\\79eac297a75b4783af700a43bb8dabee", "argv": ["D:\\\\python312\\\\python.exe", "-m", "pytest", "--mobile-evidence", "--mobile-devices", "749622c9", "--mobile-config", "D:\\\\workspace\\\\claudecode-test\\\\testplat-auto\\\\.runtime\\\\rr-verify\\\\data\\\\artifacts\\\\99e0459d-5d6d-40ec-9d33-7d4848664a0f\\\\mobile-config.toml", "-p", "testdock_runner.pytest_plugin", "-p", "no:mobile-perf", "-o", "addopts=", "--junit-xml", "D:\\\\workspace\\\\claudecode-test\\\\testplat-auto\\\\.runtime\\\\rr-verify\\\\data\\\\artifacts\\\\99e0459d-5d6d-40ec-9d33-7d4848664a0f\\\\junit.xml", "-p", "no:cacheprovider", "-q", "."], "name": "pytest", "progress": 40}	2026-11-08 21:21:34.196652+08	2026-11-08 21:21:34.196652+08
8c6129ee-a0c0-4bac-b631-2de9e3e6e5fd	540f2fa1-53f8-4e43-9841-8eb881a0c529	99e0459d-5d6d-40ec-9d33-7d4848664a0f	16	runner	0059a80d0bddf1c84f579ac831480fca	text	{"t": "text", "name": "pytest:     def test_deliberate_assertion_failure_for_evidence():"}	2026-11-08 21:21:53.703851+08	2026-11-08 21:21:53.703851+08
54766754-e37f-481d-9557-6b508516cec0	540f2fa1-53f8-4e43-9841-8eb881a0c529	99e0459d-5d6d-40ec-9d33-7d4848664a0f	21	runner	72901127d9628d6e50c686d81ca7160a	text	{"t": "text", "name": "pytest: "}	2026-11-08 21:21:53.723026+08	2026-11-08 21:21:53.723026+08
94853346-3656-4758-94ec-bf0ade3a86fb	540f2fa1-53f8-4e43-9841-8eb881a0c529	99e0459d-5d6d-40ec-9d33-7d4848664a0f	26	runner	f12b843f6f44d12d7954e7b6e09c2f33	text	{"t": "text", "name": "pytest: FAILED test_deliberate_failure.py::test_deliberate_assertion_failure_for_evidence"}	2026-11-08 21:21:53.741915+08	2026-11-08 21:21:53.741915+08
03262d30-3e11-4df0-bfff-c675e0e1e8fb	540f2fa1-53f8-4e43-9841-8eb881a0c529	99e0459d-5d6d-40ec-9d33-7d4848664a0f	30	runner	523deacc6fd09061d49fb1d39e83b052	stage	{"t": "stage", "name": "perf_collect_stop", "stage": 2, "progress": 90}	2026-11-08 21:21:56.146922+08	2026-11-08 21:21:56.146922+08
1f316766-bca1-4a74-a258-df37de622845	540f2fa1-53f8-4e43-9841-8eb881a0c529	d8c1ea76-e45d-4629-8152-bb2697af04f0	3	dispatcher	9d797c6f4bcb3b4b60c9dec1e58d7a9c	identity_verified	{"note": "已核对设备上已安装包的包名/versionName/versionCode；未验证 APK 文件摘要", "stage": "identity", "detail": "versionName=15.0.14 与固定基准一致（仅核对安装包字段，未验证 APK 摘要）", "reason": "identity_match", "serial": "749622c9", "verdict": "verified", "package_name": "com.miui.calculator", "execution_allowed": true, "verification_level": "package_identity_observed", "apk_digest_verified": false, "expected_version_code": 315000014, "expected_version_name": "15.0.14", "observed_version_code": 315000014, "observed_version_name": "15.0.14"}	2026-11-08 21:23:45.457823+08	2026-11-08 21:23:45.457823+08
acd21659-93f7-4950-acf0-bb65bdb6721b	540f2fa1-53f8-4e43-9841-8eb881a0c529	d8c1ea76-e45d-4629-8152-bb2697af04f0	9	runner	bc06cfd1bd5f8456dbdb7c7a1254d60a	stage	{"t": "stage", "cwd": "D:\\\\workspace\\\\claudecode-test\\\\testplat-auto\\\\.runtime\\\\rr-verify\\\\data\\\\code-copies\\\\79eac297a75b4783af700a43bb8dabee", "argv": ["D:\\\\python312\\\\python.exe", "-m", "pytest", "--mobile-evidence", "--mobile-devices", "749622c9", "--mobile-config", "D:\\\\workspace\\\\claudecode-test\\\\testplat-auto\\\\.runtime\\\\rr-verify\\\\data\\\\artifacts\\\\d8c1ea76-e45d-4629-8152-bb2697af04f0\\\\mobile-config.toml", "-p", "testdock_runner.pytest_plugin", "-p", "no:mobile-perf", "-o", "addopts=", "--junit-xml", "D:\\\\workspace\\\\claudecode-test\\\\testplat-auto\\\\.runtime\\\\rr-verify\\\\data\\\\artifacts\\\\d8c1ea76-e45d-4629-8152-bb2697af04f0\\\\junit.xml", "-p", "no:cacheprovider", "-q", "."], "name": "pytest", "progress": 40}	2026-11-08 21:23:47.859301+08	2026-11-08 21:23:47.859301+08
94516fd9-0286-4d59-ba2d-30b58be87b21	540f2fa1-53f8-4e43-9841-8eb881a0c529	d8c1ea76-e45d-4629-8152-bb2697af04f0	10	control	9273055b519f069de9bbf38bbf8043f1	heartbeat	{"pid": 33844, "stage": 2, "progress": 40}	2026-11-08 21:23:55.603752+08	2026-11-08 21:23:55.603752+08
80236753-f784-4b55-9266-4aa727668ac1	540f2fa1-53f8-4e43-9841-8eb881a0c529	2b814545-aada-4196-90ae-706dbbaf4d76	31	runner	bc5e69d1b429f4169b0280a4721ce08b	stage	{"t": "stage", "name": "perf_collect_stop", "stage": 2, "progress": 90}	2026-11-08 21:17:03.161687+08	2026-11-08 21:17:03.161687+08
bbd1e949-a2a5-433a-865c-83807bf9f759	540f2fa1-53f8-4e43-9841-8eb881a0c529	99e0459d-5d6d-40ec-9d33-7d4848664a0f	1	api	created	queued	{"source": "api", "request_key": "rr-after-debug-1794144090"}	2026-11-08 21:21:30.473663+08	2026-11-08 21:21:30.473663+08
05f3105c-e9bc-4047-acd2-49f3945bf928	540f2fa1-53f8-4e43-9841-8eb881a0c529	99e0459d-5d6d-40ec-9d33-7d4848664a0f	12	runner	0155fee147419c711be5f0b2858b5fa0	text	{"t": "text", "name": "pytest: F...                                                                     [100%]"}	2026-11-08 21:21:53.688767+08	2026-11-08 21:21:53.688767+08
4cafa344-2bca-48ee-8572-fd5147e0a7ee	540f2fa1-53f8-4e43-9841-8eb881a0c529	99e0459d-5d6d-40ec-9d33-7d4848664a0f	17	runner	7dc1568e9ac10526702761953ebe7663	text	{"t": "text", "name": "pytest:         \\"\\"\\"永远失败：进入报告的失败证据链路（预期内，非产品缺陷）。\\"\\"\\""}	2026-11-08 21:21:53.707428+08	2026-11-08 21:21:53.707428+08
ba563469-5459-4602-8d19-e18994989868	540f2fa1-53f8-4e43-9841-8eb881a0c529	99e0459d-5d6d-40ec-9d33-7d4848664a0f	22	runner	157d1d8ce414d3f6c32aa9513cf1904c	text	{"t": "text", "name": "pytest: test_deliberate_failure.py:12: AssertionError"}	2026-11-08 21:21:53.726118+08	2026-11-08 21:21:53.726118+08
4703ed33-cbcb-44ab-810c-53e0ff38d8bd	540f2fa1-53f8-4e43-9841-8eb881a0c529	99e0459d-5d6d-40ec-9d33-7d4848664a0f	27	runner	c1e0d576f3ead5cb510aef7644dda782	text	{"t": "text", "name": "pytest: 1 failed, 3 passed in 18.63s"}	2026-11-08 21:21:53.745781+08	2026-11-08 21:21:53.745781+08
a4fbdade-0fa3-4ef8-a03b-94124e8b7adb	540f2fa1-53f8-4e43-9841-8eb881a0c529	99e0459d-5d6d-40ec-9d33-7d4848664a0f	31	runner	0eea415d107d3b49b35f63c113b8d8ff	stage	{"t": "stage", "name": "finalize", "stage": 3, "progress": 100}	2026-11-08 21:21:56.150604+08	2026-11-08 21:21:56.150604+08
7fc2d927-944f-417a-a9e3-cc0c36dfec48	540f2fa1-53f8-4e43-9841-8eb881a0c529	d8c1ea76-e45d-4629-8152-bb2697af04f0	1	api	created	queued	{"source": "api", "request_key": "rr-mutex-1794144223"}	2026-11-08 21:23:43.645086+08	2026-11-08 21:23:43.645086+08
e43aa753-db72-4584-8ec4-6c419d8ed071	540f2fa1-53f8-4e43-9841-8eb881a0c529	2b814545-aada-4196-90ae-706dbbaf4d76	32	runner	99f75ee82d450e6817a7781e4049fb85	stage	{"t": "stage", "name": "finalize", "stage": 3, "progress": 100}	2026-11-08 21:17:03.269951+08	2026-11-08 21:17:03.269951+08
8a489c82-8c95-4d95-a1d7-0485bcc454ba	540f2fa1-53f8-4e43-9841-8eb881a0c529	99e0459d-5d6d-40ec-9d33-7d4848664a0f	4	control	e8d7b86c36bcabc68255201a3c986ed1	ack	{"pid": 24400, "stage": "ack", "progress": 5, "revision_id": "0440b605-94d6-4312-a161-1285f4d40c04"}	2026-11-08 21:21:31.355805+08	2026-11-08 21:21:31.355805+08
406cb5d7-a6bf-41ba-b76f-d7efa5e09182	540f2fa1-53f8-4e43-9841-8eb881a0c529	99e0459d-5d6d-40ec-9d33-7d4848664a0f	6	runner	de5966945c4d30f28839929793226786	stage	{"t": "stage", "name": "lease", "progress": 10}	2026-11-08 21:21:34.185792+08	2026-11-08 21:21:34.185792+08
5d753c99-f55b-4ec9-9f94-74c1f57c68a7	540f2fa1-53f8-4e43-9841-8eb881a0c529	99e0459d-5d6d-40ec-9d33-7d4848664a0f	10	control	25671b6347124686f07a649d6a91cb50	heartbeat	{"pid": 24400, "stage": 2, "progress": 40}	2026-11-08 21:21:41.374275+08	2026-11-08 21:21:41.374275+08
15474358-4bc6-4e29-9655-2f5e4cc47623	540f2fa1-53f8-4e43-9841-8eb881a0c529	99e0459d-5d6d-40ec-9d33-7d4848664a0f	13	runner	e685f404b89ee90af3b61d590d2306cd	text	{"t": "text", "name": "pytest: ================================== FAILURES ==================================="}	2026-11-08 21:21:53.693288+08	2026-11-08 21:21:53.693288+08
4fa074e2-6594-47c2-8c3a-5bea77837838	540f2fa1-53f8-4e43-9841-8eb881a0c529	99e0459d-5d6d-40ec-9d33-7d4848664a0f	18	runner	961f5b57aee8d1cfb920ebdccf8f9fa6	text	{"t": "text", "name": "pytest: >       assert False, \\"预期内的故意失败：用于验证失败结论与证据产物保留（release-readiness 02）\\""}	2026-11-08 21:21:53.710851+08	2026-11-08 21:21:53.710851+08
c377f826-1977-4707-afaa-d2ffc3a22f93	540f2fa1-53f8-4e43-9841-8eb881a0c529	99e0459d-5d6d-40ec-9d33-7d4848664a0f	23	runner	7b51029cd16ca2a0372ba13248627350	text	{"t": "text", "name": "pytest: ---------------------------- mobile-auto-evidence -----------------------------"}	2026-11-08 21:21:53.730023+08	2026-11-08 21:21:53.730023+08
8c013afa-24df-4c49-a3b4-9158dd95c103	540f2fa1-53f8-4e43-9841-8eb881a0c529	99e0459d-5d6d-40ec-9d33-7d4848664a0f	28	runner	1ac0ec4b461c583b28410e54a08d0eb4	stage	{"t": "stage", "name": "archive", "progress": 90}	2026-11-08 21:21:53.949504+08	2026-11-08 21:21:53.949504+08
ce628c92-1872-48c4-bc8f-6e4c4d3a3937	540f2fa1-53f8-4e43-9841-8eb881a0c529	99e0459d-5d6d-40ec-9d33-7d4848664a0f	32	runner	21705bbb3a08532b5eefd5b62d7440d0	result	{"t": "result", "fake": false, "files": 4, "junit": {"tests": 4, "errors": 0, "failed": 1, "present": true, "skipped": 0, "failures": 1, "parse_error": null}, "reason": "case_failure", "outcome": "failed"}	2026-11-08 21:21:56.153615+08	2026-11-08 21:21:56.153615+08
cb99a860-4927-4ee0-b4cb-203da0837a49	540f2fa1-53f8-4e43-9841-8eb881a0c529	d8c1ea76-e45d-4629-8152-bb2697af04f0	4	control	a6f415a1e6f76384e6ca3b423216ff1e	ack	{"pid": 33844, "stage": "ack", "progress": 5, "revision_id": "0440b605-94d6-4312-a161-1285f4d40c04"}	2026-11-08 21:23:45.595391+08	2026-11-08 21:23:45.595391+08
8e6da9bc-56b6-485f-b0c3-da78efd310f7	540f2fa1-53f8-4e43-9841-8eb881a0c529	d8c1ea76-e45d-4629-8152-bb2697af04f0	6	runner	ca2247727706871384ff72f7b5c77275	stage	{"t": "stage", "name": "lease", "progress": 10}	2026-11-08 21:23:47.847618+08	2026-11-08 21:23:47.847618+08
bb431cca-2951-49d9-b3b0-b5f90bea1214	540f2fa1-53f8-4e43-9841-8eb881a0c529	2b814545-aada-4196-90ae-706dbbaf4d76	33	runner	d3c99137e32d980dec00d2c7d77ebf94	result	{"t": "result", "fake": false, "files": 4, "junit": {"tests": 4, "errors": 0, "failed": 1, "present": true, "skipped": 0, "failures": 1, "parse_error": null}, "reason": "case_failure", "outcome": "failed"}	2026-11-08 21:17:03.275605+08	2026-11-08 21:17:03.275605+08
bc7a7c39-befb-44e8-a780-d439adcdc49e	540f2fa1-53f8-4e43-9841-8eb881a0c529	99e0459d-5d6d-40ec-9d33-7d4848664a0f	5	runner	096763bb34948259a13702f181bb458e	stage	{"t": "stage", "name": "perf_collect_start", "stage": 1, "progress": 10}	2026-11-08 21:21:31.401284+08	2026-11-08 21:21:31.401284+08
efa5ef29-adb6-4c00-a61d-86cd875077b6	540f2fa1-53f8-4e43-9841-8eb881a0c529	99e0459d-5d6d-40ec-9d33-7d4848664a0f	8	runner	f13955b7c706d8d6ea50f8d8f7e8f274	text	{"t": "text", "name": "suite_copy", "targets": ["."], "suite_root": "D:\\\\workspace\\\\claudecode-test\\\\testplat-auto\\\\.runtime\\\\rr-verify\\\\data\\\\code-copies\\\\79eac297a75b4783af700a43bb8dabee", "tree_sha256": "86f5595fc981c237ac149cef560210020d47aef9f514830952a0df76500a9304", "suite_version_id": "d0b33707-1ba7-49fd-831a-29575869de14"}	2026-11-08 21:21:34.193268+08	2026-11-08 21:21:34.193268+08
d74b0d52-2be6-4f02-afb2-0847912c907e	540f2fa1-53f8-4e43-9841-8eb881a0c529	99e0459d-5d6d-40ec-9d33-7d4848664a0f	11	control	6e83df76e7e5632f2292f96223b69964	heartbeat	{"pid": 24400, "stage": 2, "progress": 40}	2026-11-08 21:21:51.386265+08	2026-11-08 21:21:51.386265+08
764e29b7-f67d-4ff8-a383-c22b4bdbf0c9	540f2fa1-53f8-4e43-9841-8eb881a0c529	99e0459d-5d6d-40ec-9d33-7d4848664a0f	15	runner	f4af50fbb18ba6ce82d81e2479c56c89	text	{"t": "text", "name": "pytest: "}	2026-11-08 21:21:53.70061+08	2026-11-08 21:21:53.70061+08
b4669b58-b5e8-493c-9b7a-ecba5d6ad8b8	540f2fa1-53f8-4e43-9841-8eb881a0c529	99e0459d-5d6d-40ec-9d33-7d4848664a0f	20	runner	e384021976595bec55a159251df9e045	text	{"t": "text", "name": "pytest: E       assert False"}	2026-11-08 21:21:53.719296+08	2026-11-08 21:21:53.719296+08
42b66014-e5c1-4f48-a054-496bdae306d3	540f2fa1-53f8-4e43-9841-8eb881a0c529	99e0459d-5d6d-40ec-9d33-7d4848664a0f	25	runner	75d3ce6408650579af241694a162775c	text	{"t": "text", "name": "pytest: =========================== short test summary info ==========================="}	2026-11-08 21:21:53.737574+08	2026-11-08 21:21:53.737574+08
cb6eace1-2c37-4c29-bae5-48879650c545	540f2fa1-53f8-4e43-9841-8eb881a0c529	d8c1ea76-e45d-4629-8152-bb2697af04f0	2	dispatcher	9b82e6ca47d30e1c07e60bbc162406a4	lease_acquired	{"stage": "lease", "serial": "749622c9", "resource_id": "fab1ee61-4ece-4fc5-92bc-4bc0b13427a2", "fencing_token": 11}	2026-11-08 21:23:45.269276+08	2026-11-08 21:23:45.269276+08
a6b63108-ba35-4ea7-ac28-8a9804f9e1ad	540f2fa1-53f8-4e43-9841-8eb881a0c529	d8c1ea76-e45d-4629-8152-bb2697af04f0	7	runner	56193d56faf724250888f7f0842d8d39	stage	{"t": "stage", "name": "ready", "progress": 20}	2026-11-08 21:23:47.851923+08	2026-11-08 21:23:47.851923+08
ba71c091-e570-478e-9214-341281ada12e	540f2fa1-53f8-4e43-9841-8eb881a0c529	99e0459d-5d6d-40ec-9d33-7d4848664a0f	2	dispatcher	acfdb4b3c18a9d93459ae40708a5e266	lease_acquired	{"stage": "lease", "serial": "749622c9", "resource_id": "fab1ee61-4ece-4fc5-92bc-4bc0b13427a2", "fencing_token": 9}	2026-11-08 21:21:30.993523+08	2026-11-08 21:21:30.993523+08
872a4772-159d-4177-bca1-568b00a9b64c	540f2fa1-53f8-4e43-9841-8eb881a0c529	99e0459d-5d6d-40ec-9d33-7d4848664a0f	7	runner	72532884abef666b9c86b239fb5e1d75	stage	{"t": "stage", "name": "ready", "progress": 20}	2026-11-08 21:21:34.189614+08	2026-11-08 21:21:34.189614+08
b8ba3e41-3086-4367-8dce-1bec8dee0983	540f2fa1-53f8-4e43-9841-8eb881a0c529	99e0459d-5d6d-40ec-9d33-7d4848664a0f	14	runner	75579e8957ea3315c80c43584a967312	text	{"t": "text", "name": "pytest: _______________ test_deliberate_assertion_failure_for_evidence ________________"}	2026-11-08 21:21:53.696857+08	2026-11-08 21:21:53.696857+08
0dbe8bc1-50c9-4154-8378-493f745631b0	540f2fa1-53f8-4e43-9841-8eb881a0c529	99e0459d-5d6d-40ec-9d33-7d4848664a0f	19	runner	4347cc041f4edb9d617615e94ca21198	text	{"t": "text", "name": "pytest: E       AssertionError: 预期内的故意失败：用于验证失败结论与证据产物保留（release-readiness 02）"}	2026-11-08 21:21:53.71457+08	2026-11-08 21:21:53.71457+08
449b93d8-5664-4953-85f1-a81ff5afa504	540f2fa1-53f8-4e43-9841-8eb881a0c529	99e0459d-5d6d-40ec-9d33-7d4848664a0f	24	runner	679cc1cdf8921d4d33852239b6eb6c05	text	{"t": "text", "name": "pytest: 未找到可用的 DeviceSession(提供 mobile_session fixture 或任何 DeviceSession funcarg),未采集证据"}	2026-11-08 21:21:53.733524+08	2026-11-08 21:21:53.733524+08
55338d56-1b09-4f88-891d-85ce1447231d	540f2fa1-53f8-4e43-9841-8eb881a0c529	99e0459d-5d6d-40ec-9d33-7d4848664a0f	29	runtime	77a2307ff47f1429bb93c48b5be715e7	finish	{"cases": [{"outcome": "failed", "case_key": "code-copies.79eac297a75b4783af700a43bb8dabee.test_deliberate_failure::test_deliberate_assertion_failure_for_evidence", "duration_ms": 1, "error_summary": "AssertionError: 预期内的故意失败：用于验证失败结论与证据产物保留（release-readiness 02）\\nassert False"}, {"outcome": "passed", "case_key": "code-copies.79eac297a75b4783af700a43bb8dabee.test_smoke::test_session_is_bound_to_dispatch_device", "duration_ms": 894, "error_summary": null}, {"outcome": "passed", "case_key": "code-copies.79eac297a75b4783af700a43bb8dabee.test_smoke::test_app_launches_and_screenshot_is_a_real_frame", "duration_ms": 2430, "error_summary": null}, {"outcome": "passed", "case_key": "code-copies.79eac297a75b4783af700a43bb8dabee.test_smoke::test_ui_stays_foreground_long_enough_for_perf_sampling", "duration_ms": 15135, "error_summary": null}], "junit": {"tests": 4, "errors": 0, "failed": 1, "present": true, "skipped": 0, "failures": 1}, "stage": "finish", "state": "completed", "reason": null, "outcome": "failed", "components": [{"kind": "ui", "state": "completed", "outcome": "failed", "reason_code": null}, {"kind": "performance", "state": "completed"}], "artifact_count": 24}	2026-11-08 21:21:55.980553+08	2026-11-08 21:21:55.980553+08
b5c37237-1b7e-4297-915d-1bfaf80f5f65	540f2fa1-53f8-4e43-9841-8eb881a0c529	d8c1ea76-e45d-4629-8152-bb2697af04f0	5	runner	d4649008df88e3f906b26acebf7895a1	stage	{"t": "stage", "name": "perf_collect_start", "stage": 1, "progress": 10}	2026-11-08 21:23:45.678523+08	2026-11-08 21:23:45.678523+08
5c394017-9351-48f2-8641-1b79a9541a1f	540f2fa1-53f8-4e43-9841-8eb881a0c529	d8c1ea76-e45d-4629-8152-bb2697af04f0	8	runner	3592137b12b9c4837e35c5d0c5b9cf47	text	{"t": "text", "name": "suite_copy", "targets": ["."], "suite_root": "D:\\\\workspace\\\\claudecode-test\\\\testplat-auto\\\\.runtime\\\\rr-verify\\\\data\\\\code-copies\\\\79eac297a75b4783af700a43bb8dabee", "tree_sha256": "86f5595fc981c237ac149cef560210020d47aef9f514830952a0df76500a9304", "suite_version_id": "d0b33707-1ba7-49fd-831a-29575869de14"}	2026-11-08 21:23:47.855732+08	2026-11-08 21:23:47.855732+08
48d0a5b5-00b8-4471-b59b-5336d926f908	540f2fa1-53f8-4e43-9841-8eb881a0c529	d8c1ea76-e45d-4629-8152-bb2697af04f0	11	control	4e054db71fee0083db4c35fc4cd979c0	heartbeat	{"pid": 33844, "stage": 2, "progress": 40}	2026-11-08 21:24:05.613645+08	2026-11-08 21:24:05.613645+08
df23f60f-5180-4a9c-be65-b22c7ad60cda	540f2fa1-53f8-4e43-9841-8eb881a0c529	d8c1ea76-e45d-4629-8152-bb2697af04f0	12	runner	11168b3b87d4a2c6690ba6dd5630e51f	text	{"t": "text", "name": "pytest: F...                                                                     [100%]"}	2026-11-08 21:24:07.215806+08	2026-11-08 21:24:07.215806+08
0f2b6e62-6a57-4a79-988e-a8b42cf77ad4	540f2fa1-53f8-4e43-9841-8eb881a0c529	d8c1ea76-e45d-4629-8152-bb2697af04f0	13	runner	72fe6950aa439fa6dc24ae5a0a99f23a	text	{"t": "text", "name": "pytest: ================================== FAILURES ==================================="}	2026-11-08 21:24:07.220452+08	2026-11-08 21:24:07.220452+08
16a674bb-b88d-4b68-8e6e-91bea12fa39f	540f2fa1-53f8-4e43-9841-8eb881a0c529	d8c1ea76-e45d-4629-8152-bb2697af04f0	14	runner	c8940c9e8dfedb6f43cb44affe2854a4	text	{"t": "text", "name": "pytest: _______________ test_deliberate_assertion_failure_for_evidence ________________"}	2026-11-08 21:24:07.225978+08	2026-11-08 21:24:07.225978+08
bd58ce86-1263-4d65-8e18-85fa94ff1bfc	540f2fa1-53f8-4e43-9841-8eb881a0c529	d8c1ea76-e45d-4629-8152-bb2697af04f0	15	runner	f39aa5d1b4444d4c714a285c2e142d12	text	{"t": "text", "name": "pytest: "}	2026-11-08 21:24:07.231486+08	2026-11-08 21:24:07.231486+08
971a43ef-4fbd-43b3-963a-047a472c08b5	540f2fa1-53f8-4e43-9841-8eb881a0c529	d8c1ea76-e45d-4629-8152-bb2697af04f0	16	runner	055a130f9f825dda42a8fd08e1abf160	text	{"t": "text", "name": "pytest:     def test_deliberate_assertion_failure_for_evidence():"}	2026-11-08 21:24:07.237436+08	2026-11-08 21:24:07.237436+08
ded562ba-2048-438b-bbb0-36e8b38adb0a	540f2fa1-53f8-4e43-9841-8eb881a0c529	d8c1ea76-e45d-4629-8152-bb2697af04f0	17	runner	d12d0670f85a4d9e4550b3b484a25d6f	text	{"t": "text", "name": "pytest:         \\"\\"\\"永远失败：进入报告的失败证据链路（预期内，非产品缺陷）。\\"\\"\\""}	2026-11-08 21:24:07.241235+08	2026-11-08 21:24:07.241235+08
df2378b5-9a63-46c8-a839-80f348b7a299	540f2fa1-53f8-4e43-9841-8eb881a0c529	d8c1ea76-e45d-4629-8152-bb2697af04f0	18	runner	359efc1185f518e6e38ce3dc5d39e8f9	text	{"t": "text", "name": "pytest: >       assert False, \\"预期内的故意失败：用于验证失败结论与证据产物保留（release-readiness 02）\\""}	2026-11-08 21:24:07.244701+08	2026-11-08 21:24:07.244701+08
b91d2064-1156-40fa-a4a3-6af6676593bd	540f2fa1-53f8-4e43-9841-8eb881a0c529	d8c1ea76-e45d-4629-8152-bb2697af04f0	19	runner	3eba3c0d6def6eeb3869e1523eafae96	text	{"t": "text", "name": "pytest: E       AssertionError: 预期内的故意失败：用于验证失败结论与证据产物保留（release-readiness 02）"}	2026-11-08 21:24:07.248589+08	2026-11-08 21:24:07.248589+08
fafeaaa4-34fb-448e-9a3f-2dcfcddca964	540f2fa1-53f8-4e43-9841-8eb881a0c529	d8c1ea76-e45d-4629-8152-bb2697af04f0	20	runner	d5cb091df959c132974711790c2aaa82	text	{"t": "text", "name": "pytest: E       assert False"}	2026-11-08 21:24:07.251859+08	2026-11-08 21:24:07.251859+08
36f1a46a-5e10-486b-8b60-d5dbccc536e3	540f2fa1-53f8-4e43-9841-8eb881a0c529	d8c1ea76-e45d-4629-8152-bb2697af04f0	21	runner	8b255d9fe1f38539e3f7d6652ce71b5c	text	{"t": "text", "name": "pytest: "}	2026-11-08 21:24:07.25539+08	2026-11-08 21:24:07.25539+08
467a6928-5229-42a5-a774-eda1f3ba1302	540f2fa1-53f8-4e43-9841-8eb881a0c529	d8c1ea76-e45d-4629-8152-bb2697af04f0	22	runner	70ada476d24c8324c391084a8778a234	text	{"t": "text", "name": "pytest: test_deliberate_failure.py:12: AssertionError"}	2026-11-08 21:24:07.259179+08	2026-11-08 21:24:07.259179+08
948ec1bf-801f-4f05-885c-9b75c1a3fd43	540f2fa1-53f8-4e43-9841-8eb881a0c529	d8c1ea76-e45d-4629-8152-bb2697af04f0	23	runner	cd4eb3d67b8d631836ea4a8c85a28208	text	{"t": "text", "name": "pytest: ---------------------------- mobile-auto-evidence -----------------------------"}	2026-11-08 21:24:07.262795+08	2026-11-08 21:24:07.262795+08
75321d09-dba1-4f7b-964a-b573fed66ccc	540f2fa1-53f8-4e43-9841-8eb881a0c529	d8c1ea76-e45d-4629-8152-bb2697af04f0	24	runner	8a17da6499a09269cd599de3fcd21478	text	{"t": "text", "name": "pytest: 未找到可用的 DeviceSession(提供 mobile_session fixture 或任何 DeviceSession funcarg),未采集证据"}	2026-11-08 21:24:07.265703+08	2026-11-08 21:24:07.265703+08
5605d0d8-72b8-4259-bafc-db0b5c5bab36	540f2fa1-53f8-4e43-9841-8eb881a0c529	d8c1ea76-e45d-4629-8152-bb2697af04f0	25	runner	8969f89073ab8879267b9014aa11a3e8	text	{"t": "text", "name": "pytest: =========================== short test summary info ==========================="}	2026-11-08 21:24:07.268672+08	2026-11-08 21:24:07.268672+08
a0bfa061-26db-42a6-8259-3fdd7fde0064	540f2fa1-53f8-4e43-9841-8eb881a0c529	d8c1ea76-e45d-4629-8152-bb2697af04f0	26	runner	e5da2143d80b1acc136de2fa7a300abd	text	{"t": "text", "name": "pytest: FAILED test_deliberate_failure.py::test_deliberate_assertion_failure_for_evidence"}	2026-11-08 21:24:07.272138+08	2026-11-08 21:24:07.272138+08
a450e091-d3a3-4c2a-b6a2-30c23278bd33	540f2fa1-53f8-4e43-9841-8eb881a0c529	d8c1ea76-e45d-4629-8152-bb2697af04f0	27	runner	52f7b542f085f63192b95df4613f1b18	text	{"t": "text", "name": "pytest: 1 failed, 3 passed in 18.54s"}	2026-11-08 21:24:07.276672+08	2026-11-08 21:24:07.276672+08
6a0887a8-8cac-4ddf-9048-7d9ac8038524	540f2fa1-53f8-4e43-9841-8eb881a0c529	d8c1ea76-e45d-4629-8152-bb2697af04f0	28	runner	52cf575b76653379ad4307f498688293	stage	{"t": "stage", "name": "archive", "progress": 90}	2026-11-08 21:24:07.478132+08	2026-11-08 21:24:07.478132+08
cbca7b1a-db97-47fc-9352-266376c10149	540f2fa1-53f8-4e43-9841-8eb881a0c529	d8c1ea76-e45d-4629-8152-bb2697af04f0	30	runner	283155ec55d4edf6538c8897e03e6e1e	stage	{"t": "stage", "name": "perf_collect_stop", "stage": 2, "progress": 90}	2026-11-08 21:24:09.472937+08	2026-11-08 21:24:09.472937+08
48a1c796-0946-404d-a31b-133ad5e4b6d2	540f2fa1-53f8-4e43-9841-8eb881a0c529	8d475676-44ec-42b3-a239-911a9ec3f7cb	2	control	cancel	cancel_requested	{"from_state": "queued", "requested_by": "web"}	2026-11-08 21:25:23.230891+08	2026-11-08 21:25:23.230891+08
12794961-b7f5-44d7-9bbf-eaee8a3792b8	540f2fa1-53f8-4e43-9841-8eb881a0c529	2e43d5e0-1374-4c71-8b4d-586ca1033e5a	2	dispatcher	fe611691ace1d549c629f43cca6258c5	lease_acquired	{"stage": "lease", "serial": "749622c9", "resource_id": "fab1ee61-4ece-4fc5-92bc-4bc0b13427a2", "fencing_token": 13}	2026-11-08 21:25:55.678858+08	2026-11-08 21:25:55.678858+08
95cfa3e2-6f78-4e1a-a806-490672974ad0	540f2fa1-53f8-4e43-9841-8eb881a0c529	2e43d5e0-1374-4c71-8b4d-586ca1033e5a	5	control	854911a8d241507952b11e1669678886	ack	{"pid": 34696, "stage": "ack", "progress": 5, "revision_id": "0440b605-94d6-4312-a161-1285f4d40c04"}	2026-11-08 21:25:56.026737+08	2026-11-08 21:25:56.026737+08
35169235-e3b2-4774-893c-b80efa9fda55	540f2fa1-53f8-4e43-9841-8eb881a0c529	2e43d5e0-1374-4c71-8b4d-586ca1033e5a	7	runtime	787a647726b047442cbb9ad9e0846713	finish	{"junit": {"present": false}, "stage": "finish", "state": "cancelled", "reason": "cancel_requested", "outcome": null, "artifact_count": 0, "runner_terminated": true, "cancel_requested_by": "web"}	2026-11-08 21:25:56.358498+08	2026-11-08 21:25:56.358498+08
7edf651a-74c1-4331-a59f-30f5ef764cc4	540f2fa1-53f8-4e43-9841-8eb881a0c529	d8c1ea76-e45d-4629-8152-bb2697af04f0	29	runtime	b01d2282ff02841edf076da452e94ea8	finish	{"cases": [{"outcome": "failed", "case_key": "code-copies.79eac297a75b4783af700a43bb8dabee.test_deliberate_failure::test_deliberate_assertion_failure_for_evidence", "duration_ms": 1, "error_summary": "AssertionError: 预期内的故意失败：用于验证失败结论与证据产物保留（release-readiness 02）\\nassert False"}, {"outcome": "passed", "case_key": "code-copies.79eac297a75b4783af700a43bb8dabee.test_smoke::test_session_is_bound_to_dispatch_device", "duration_ms": 871, "error_summary": null}, {"outcome": "passed", "case_key": "code-copies.79eac297a75b4783af700a43bb8dabee.test_smoke::test_app_launches_and_screenshot_is_a_real_frame", "duration_ms": 2422, "error_summary": null}, {"outcome": "passed", "case_key": "code-copies.79eac297a75b4783af700a43bb8dabee.test_smoke::test_ui_stays_foreground_long_enough_for_perf_sampling", "duration_ms": 15086, "error_summary": null}], "junit": {"tests": 4, "errors": 0, "failed": 1, "present": true, "skipped": 0, "failures": 1}, "stage": "finish", "state": "completed", "reason": null, "outcome": "failed", "components": [{"kind": "ui", "state": "completed", "outcome": "failed", "reason_code": null}, {"kind": "performance", "state": "completed"}], "artifact_count": 24}	2026-11-08 21:24:09.471599+08	2026-11-08 21:24:09.471599+08
19a70e60-1944-42c1-92dc-c74dc3cddbb7	540f2fa1-53f8-4e43-9841-8eb881a0c529	2e43d5e0-1374-4c71-8b4d-586ca1033e5a	1	api	created	queued	{"source": "api", "request_key": "rr-mutex2-1794144354"}	2026-11-08 21:25:54.397665+08	2026-11-08 21:25:54.397665+08
9764e1b4-9cf2-4d36-9ff0-3b50aa67e300	540f2fa1-53f8-4e43-9841-8eb881a0c529	2e43d5e0-1374-4c71-8b4d-586ca1033e5a	6	runner	5b6f6bdd3c57e2aa859768f5d445db30	stage	{"t": "stage", "name": "perf_collect_start", "stage": 1, "progress": 10}	2026-11-08 21:25:56.104582+08	2026-11-08 21:25:56.104582+08
bdfc13a8-5bfa-4e61-bcf6-888abf1b9ec3	540f2fa1-53f8-4e43-9841-8eb881a0c529	d8c1ea76-e45d-4629-8152-bb2697af04f0	31	runner	97522889c0ecfbe0d97356c29ebb15e6	stage	{"t": "stage", "name": "finalize", "stage": 3, "progress": 100}	2026-11-08 21:24:09.610707+08	2026-11-08 21:24:09.610707+08
5da976fd-1edd-47da-aefc-9df07a8308ee	540f2fa1-53f8-4e43-9841-8eb881a0c529	2e43d5e0-1374-4c71-8b4d-586ca1033e5a	3	dispatcher	f725faee17b06961c4e22cddc23047a6	identity_verified	{"note": "已核对设备上已安装包的包名/versionName/versionCode；未验证 APK 文件摘要", "stage": "identity", "detail": "versionName=15.0.14 与固定基准一致（仅核对安装包字段，未验证 APK 摘要）", "reason": "identity_match", "serial": "749622c9", "verdict": "verified", "package_name": "com.miui.calculator", "execution_allowed": true, "verification_level": "package_identity_observed", "apk_digest_verified": false, "expected_version_code": 315000014, "expected_version_name": "15.0.14", "observed_version_code": 315000014, "observed_version_name": "15.0.14"}	2026-11-08 21:25:55.881198+08	2026-11-08 21:25:55.881198+08
ac9e0a58-2855-47b3-809e-bd0395a03022	540f2fa1-53f8-4e43-9841-8eb881a0c529	d8c1ea76-e45d-4629-8152-bb2697af04f0	32	runner	b683e8a13f351f207399a5c923022923	result	{"t": "result", "fake": false, "files": 4, "junit": {"tests": 4, "errors": 0, "failed": 1, "present": true, "skipped": 0, "failures": 1, "parse_error": null}, "reason": "case_failure", "outcome": "failed"}	2026-11-08 21:24:09.615588+08	2026-11-08 21:24:09.615588+08
dea3cc2a-5edd-489d-92ed-0947884b026a	540f2fa1-53f8-4e43-9841-8eb881a0c529	8d475676-44ec-42b3-a239-911a9ec3f7cb	1	api	created	queued	{"source": "api", "request_key": "rr-mutex2-1794144302"}	2026-11-08 21:25:02.908528+08	2026-11-08 21:25:02.908528+08
dceb7597-b7d5-464d-9c30-8eb80268878e	540f2fa1-53f8-4e43-9841-8eb881a0c529	2e43d5e0-1374-4c71-8b4d-586ca1033e5a	4	control	cancel	cancel_requested	{"from_state": "dispatching", "requested_by": "web"}	2026-11-08 21:25:55.997381+08	2026-11-08 21:25:55.997381+08
\.


--
-- Data for Name: suite_versions; Type: TABLE DATA; Schema: public; Owner: testdock
--

COPY public.suite_versions (id, project_id, application_id, suite_id, version, source_ref, source_commit, manifest, created_at) FROM stdin;
0bfc19f5-96f6-499d-aa1b-3c97c8c720bb	540f2fa1-53f8-4e43-9841-8eb881a0c529	a9feb4f2-9d51-4d6e-9ea1-aeb423901f5f	cab2999d-7bda-44fd-9d98-c35b4fec1f5d	1	calc-smoke	local	{"cases": [{"file": "test_deliberate_failure.py", "tags": [], "entry": "test_deliberate_assertion_failure_for_evidence", "node_id": "test_deliberate_failure.py::test_deliberate_assertion_failure_for_evidence", "case_key": "test_deliberate_failure.py::test_deliberate_assertion_failure_for_evidence"}, {"file": "test_smoke.py", "tags": [], "entry": "test_session_is_bound_to_dispatch_device", "node_id": "test_smoke.py::test_session_is_bound_to_dispatch_device", "case_key": "test_smoke.py::test_session_is_bound_to_dispatch_device"}, {"file": "test_smoke.py", "tags": [], "entry": "test_app_launches_and_screenshot_is_a_real_frame", "node_id": "test_smoke.py::test_app_launches_and_screenshot_is_a_real_frame", "case_key": "test_smoke.py::test_app_launches_and_screenshot_is_a_real_frame"}, {"file": "test_smoke.py", "tags": [], "entry": "test_ui_stays_foreground_long_enough_for_perf_sampling", "node_id": "test_smoke.py::test_ui_stays_foreground_long_enough_for_perf_sampling", "case_key": "test_smoke.py::test_ui_stays_foreground_long_enough_for_perf_sampling"}], "code_copy": {"files": [{"path": "FILES.sha256", "size": 173, "sha256": "e18b28049cfe02bb7f68c2133817fd297254bff7dfa39c35051c50750e913da6"}, {"path": "PROVENANCE.md", "size": 739, "sha256": "4235602457f5158424d834da39279511b79cae24f1657f9c4e7c5a38a514afe6"}, {"path": "test_deliberate_failure.py", "size": 593, "sha256": "7477e77c8bb7d3154d9dab69d5b0ca6603b01deb52dedfbf2f71d200bbb8a679"}, {"path": "test_smoke.py", "size": 1683, "sha256": "5179b0f3047b5535b6e2e457465c7a4553c5e21d2156c93f944083ce30a0ab89"}], "copy_id": "b475bb18efac4d05bd903281643a50c1", "root_rel": "b475bb18efac4d05bd903281643a50c1", "copied_at": "2026-11-08T12:07:02.669222+00:00", "source_id": "calc-smoke", "file_count": 4, "tree_sha256": "86f5595fc981c237ac149cef560210020d47aef9f514830952a0df76500a9304", "schema_version": 1}, "source_id": "calc-smoke", "test_type": "ui", "case_count": 4, "schema_version": 1}	2026-11-08 20:07:02.653805+08
fdfa55d6-a8c9-481c-941d-a37dedc913f4	540f2fa1-53f8-4e43-9841-8eb881a0c529	a9feb4f2-9d51-4d6e-9ea1-aeb423901f5f	3edfd7c2-454b-4bb9-8850-33f4e25bbbd4	1	suite:3edfd7c2-454b-4bb9-8850-33f4e25bbbd4	local	{"cases": [], "scenario": {"items": ["CPU", "Memory", "FPS"], "duration_s": 300}, "test_type": "performance", "case_count": 0, "schema_version": 1}	2026-11-08 20:50:55.968316+08
e440c2ee-c6a4-449c-a27b-db63779ed052	540f2fa1-53f8-4e43-9841-8eb881a0c529	a9feb4f2-9d51-4d6e-9ea1-aeb423901f5f	3edfd7c2-454b-4bb9-8850-33f4e25bbbd4	2	suite:3edfd7c2-454b-4bb9-8850-33f4e25bbbd4	local	{"cases": [], "scenario": {"items": ["CPU", "Memory", "FPS"], "duration_s": 30}, "test_type": "performance", "case_count": 0, "schema_version": 1}	2026-11-08 20:51:26.83451+08
3650944f-8f88-4465-9693-29c218563e0e	540f2fa1-53f8-4e43-9841-8eb881a0c529	a9feb4f2-9d51-4d6e-9ea1-aeb423901f5f	6c3aa40d-a113-4f38-86e0-b51fb28cc078	1	calc-smoke	local	{"cases": [{"file": "test_deliberate_failure.py", "tags": [], "entry": "test_deliberate_assertion_failure_for_evidence", "node_id": "test_deliberate_failure.py::test_deliberate_assertion_failure_for_evidence", "case_key": "test_deliberate_failure.py::test_deliberate_assertion_failure_for_evidence"}, {"file": "test_smoke.py", "tags": [], "entry": "test_session_is_bound_to_dispatch_device", "node_id": "test_smoke.py::test_session_is_bound_to_dispatch_device", "case_key": "test_smoke.py::test_session_is_bound_to_dispatch_device"}, {"file": "test_smoke.py", "tags": [], "entry": "test_app_launches_and_screenshot_is_a_real_frame", "node_id": "test_smoke.py::test_app_launches_and_screenshot_is_a_real_frame", "case_key": "test_smoke.py::test_app_launches_and_screenshot_is_a_real_frame"}, {"file": "test_smoke.py", "tags": [], "entry": "test_ui_stays_foreground_long_enough_for_perf_sampling", "node_id": "test_smoke.py::test_ui_stays_foreground_long_enough_for_perf_sampling", "case_key": "test_smoke.py::test_ui_stays_foreground_long_enough_for_perf_sampling"}], "code_copy": {"files": [{"path": "FILES.sha256", "size": 173, "sha256": "e18b28049cfe02bb7f68c2133817fd297254bff7dfa39c35051c50750e913da6"}, {"path": "PROVENANCE.md", "size": 739, "sha256": "4235602457f5158424d834da39279511b79cae24f1657f9c4e7c5a38a514afe6"}, {"path": "test_deliberate_failure.py", "size": 593, "sha256": "7477e77c8bb7d3154d9dab69d5b0ca6603b01deb52dedfbf2f71d200bbb8a679"}, {"path": "test_smoke.py", "size": 1683, "sha256": "5179b0f3047b5535b6e2e457465c7a4553c5e21d2156c93f944083ce30a0ab89"}], "copy_id": "2214553b75d74e43a204fb36b724ccbc", "root_rel": "2214553b75d74e43a204fb36b724ccbc", "copied_at": "2026-11-08T13:10:14.427332+00:00", "source_id": "calc-smoke", "file_count": 4, "tree_sha256": "86f5595fc981c237ac149cef560210020d47aef9f514830952a0df76500a9304", "schema_version": 1}, "source_id": "calc-smoke", "test_type": "joint", "case_count": 4, "performance": {"items": ["CPU", "Memory", "FPS"], "duration_s": 300}, "ui_timeout_s": 600, "schema_version": 1}	2026-11-08 21:10:14.409631+08
d0b33707-1ba7-49fd-831a-29575869de14	540f2fa1-53f8-4e43-9841-8eb881a0c529	a9feb4f2-9d51-4d6e-9ea1-aeb423901f5f	6c3aa40d-a113-4f38-86e0-b51fb28cc078	2	calc-smoke	local	{"cases": [{"file": "test_deliberate_failure.py", "tags": [], "entry": "test_deliberate_assertion_failure_for_evidence", "node_id": "test_deliberate_failure.py::test_deliberate_assertion_failure_for_evidence", "case_key": "test_deliberate_failure.py::test_deliberate_assertion_failure_for_evidence"}, {"file": "test_smoke.py", "tags": [], "entry": "test_session_is_bound_to_dispatch_device", "node_id": "test_smoke.py::test_session_is_bound_to_dispatch_device", "case_key": "test_smoke.py::test_session_is_bound_to_dispatch_device"}, {"file": "test_smoke.py", "tags": [], "entry": "test_app_launches_and_screenshot_is_a_real_frame", "node_id": "test_smoke.py::test_app_launches_and_screenshot_is_a_real_frame", "case_key": "test_smoke.py::test_app_launches_and_screenshot_is_a_real_frame"}, {"file": "test_smoke.py", "tags": [], "entry": "test_ui_stays_foreground_long_enough_for_perf_sampling", "node_id": "test_smoke.py::test_ui_stays_foreground_long_enough_for_perf_sampling", "case_key": "test_smoke.py::test_ui_stays_foreground_long_enough_for_perf_sampling"}], "code_copy": {"files": [{"path": "FILES.sha256", "size": 173, "sha256": "e18b28049cfe02bb7f68c2133817fd297254bff7dfa39c35051c50750e913da6"}, {"path": "PROVENANCE.md", "size": 739, "sha256": "4235602457f5158424d834da39279511b79cae24f1657f9c4e7c5a38a514afe6"}, {"path": "test_deliberate_failure.py", "size": 593, "sha256": "7477e77c8bb7d3154d9dab69d5b0ca6603b01deb52dedfbf2f71d200bbb8a679"}, {"path": "test_smoke.py", "size": 1683, "sha256": "5179b0f3047b5535b6e2e457465c7a4553c5e21d2156c93f944083ce30a0ab89"}], "copy_id": "79eac297a75b4783af700a43bb8dabee", "root_rel": "79eac297a75b4783af700a43bb8dabee", "copied_at": "2026-11-08T13:11:32.223716+00:00", "source_id": "calc-smoke", "file_count": 4, "tree_sha256": "86f5595fc981c237ac149cef560210020d47aef9f514830952a0df76500a9304", "schema_version": 1}, "source_id": "calc-smoke", "test_type": "joint", "case_count": 4, "performance": {"items": ["CPU", "Memory", "FPS"], "duration_s": 30}, "ui_timeout_s": 600, "schema_version": 1}	2026-11-08 21:11:32.2063+08
\.


--
-- Data for Name: task_request_keys; Type: TABLE DATA; Schema: public; Owner: testdock
--

COPY public.task_request_keys (id, project_id, request_key, fingerprint, task_id, created_at) FROM stdin;
ff327678-84c6-4e2c-912e-398d3e40681c	540f2fa1-53f8-4e43-9841-8eb881a0c529	8c790109-c772-4b5b-a4a2-6b2f7d7a9fe3	9d865163ae189473460c30f3686278dbb6c5afbd60c78ac27b0b92b7d1844e97	68791794-33e0-4f11-826d-62b95952e978	2026-11-08 20:16:47.799756+08
6148d243-3bcc-4ed6-9e29-c01e7219dda2	540f2fa1-53f8-4e43-9841-8eb881a0c529	1f7551de-fabf-4d32-9182-cd64c6c4b2be	0169091f61495de9f797bc4457cb76ffaa8e0e0738c5069c92b6de145e8438be	d8b3deec-8b19-4f9d-9a31-c04bfcfdf2a0	2026-11-08 20:52:04.506103+08
dd98e731-5586-429d-ae3f-23e048f5fba5	540f2fa1-53f8-4e43-9841-8eb881a0c529	9cf14847-1f9f-4c2b-b9aa-0edc6c4f7fe8	fcc42e1f1a5b1647dfb5fb2eeeaf9ba41ee840a600e63cf7909f9e9e104e0d76	02fb058b-7091-48cd-887d-7dd61c725e4f	2026-11-08 21:11:51.436902+08
\.


--
-- Data for Name: task_revisions; Type: TABLE DATA; Schema: public; Owner: testdock
--

COPY public.task_revisions (id, project_id, application_id, task_id, revision, environment_id, build_id, suite_version_id, test_type, readiness, config, created_by, created_at) FROM stdin;
957387a6-3629-4539-a21c-d6947b4db8d4	540f2fa1-53f8-4e43-9841-8eb881a0c529	a9feb4f2-9d51-4d6e-9ea1-aeb423901f5f	68791794-33e0-4f11-826d-62b95952e978	1	442e284e-2b71-402a-829d-b5679643a28c	9ad14e07-1190-409e-b02c-684ed932f5dd	0bfc19f5-96f6-499d-aa1b-3c97c8c720bb	ui	draft	{"device": {"resource_id": "fab1ee61-4ece-4fc5-92bc-4bc0b13427a2", "allow_busy_queue": true}, "scenario": null, "app_version": null, "package_name": "com.miui.calculator", "application_platform": "android"}	web-client	2026-11-08 20:16:47.799756+08
629f6c29-1023-4ecb-beec-4e866029493a	540f2fa1-53f8-4e43-9841-8eb881a0c529	a9feb4f2-9d51-4d6e-9ea1-aeb423901f5f	68791794-33e0-4f11-826d-62b95952e978	2	442e284e-2b71-402a-829d-b5679643a28c	9ad14e07-1190-409e-b02c-684ed932f5dd	0bfc19f5-96f6-499d-aa1b-3c97c8c720bb	ui	validated	{"device": {"resource_id": "fab1ee61-4ece-4fc5-92bc-4bc0b13427a2", "allow_busy_queue": true}, "scenario": null, "app_version": null, "package_name": "com.miui.calculator", "application_platform": "android"}	web-client	2026-11-08 20:17:31.95634+08
88dace21-6785-466e-a5bf-81f078aee011	540f2fa1-53f8-4e43-9841-8eb881a0c529	a9feb4f2-9d51-4d6e-9ea1-aeb423901f5f	d8b3deec-8b19-4f9d-9a31-c04bfcfdf2a0	1	442e284e-2b71-402a-829d-b5679643a28c	9ad14e07-1190-409e-b02c-684ed932f5dd	e440c2ee-c6a4-449c-a27b-db63779ed052	performance	draft	{"perf": {"items": ["CPU", "Memory", "FPS"], "duration_s": 30}, "device": {"resource_id": "fab1ee61-4ece-4fc5-92bc-4bc0b13427a2", "allow_busy_queue": true}, "scenario": null, "app_version": null, "package_name": "com.miui.calculator", "application_platform": "android"}	web-client	2026-11-08 20:52:04.506103+08
3af97316-61f7-403c-ae6c-e0f78590340b	540f2fa1-53f8-4e43-9841-8eb881a0c529	a9feb4f2-9d51-4d6e-9ea1-aeb423901f5f	d8b3deec-8b19-4f9d-9a31-c04bfcfdf2a0	2	442e284e-2b71-402a-829d-b5679643a28c	9ad14e07-1190-409e-b02c-684ed932f5dd	e440c2ee-c6a4-449c-a27b-db63779ed052	performance	validated	{"perf": {"items": ["CPU", "Memory", "FPS"], "duration_s": 30}, "device": {"resource_id": "fab1ee61-4ece-4fc5-92bc-4bc0b13427a2", "allow_busy_queue": true}, "scenario": null, "app_version": null, "package_name": "com.miui.calculator", "application_platform": "android"}	web-client	2026-11-08 20:52:42.341354+08
40fafdf8-90dd-45cb-897c-2e95543bef2b	540f2fa1-53f8-4e43-9841-8eb881a0c529	a9feb4f2-9d51-4d6e-9ea1-aeb423901f5f	02fb058b-7091-48cd-887d-7dd61c725e4f	1	442e284e-2b71-402a-829d-b5679643a28c	9ad14e07-1190-409e-b02c-684ed932f5dd	d0b33707-1ba7-49fd-831a-29575869de14	joint	draft	{"perf": {"items": ["CPU", "Memory", "FPS"], "duration_s": 30}, "device": {"resource_id": "fab1ee61-4ece-4fc5-92bc-4bc0b13427a2", "allow_busy_queue": true}, "scenario": null, "app_version": null, "package_name": "com.miui.calculator", "application_platform": "android"}	web-client	2026-11-08 21:11:51.436902+08
0440b605-94d6-4312-a161-1285f4d40c04	540f2fa1-53f8-4e43-9841-8eb881a0c529	a9feb4f2-9d51-4d6e-9ea1-aeb423901f5f	02fb058b-7091-48cd-887d-7dd61c725e4f	2	442e284e-2b71-402a-829d-b5679643a28c	9ad14e07-1190-409e-b02c-684ed932f5dd	d0b33707-1ba7-49fd-831a-29575869de14	joint	validated	{"perf": {"items": ["CPU", "Memory", "FPS"], "duration_s": 30}, "device": {"resource_id": "fab1ee61-4ece-4fc5-92bc-4bc0b13427a2", "allow_busy_queue": true}, "scenario": null, "app_version": null, "package_name": "com.miui.calculator", "application_platform": "android"}	web-client	2026-11-08 21:12:05.750753+08
\.


--
-- Data for Name: test_runs; Type: TABLE DATA; Schema: public; Owner: testdock
--

COPY public.test_runs (id, project_id, application_id, platform, revision_id, parent_run_id, request_key, state, outcome, reason_code, resource_id, profile_id, config_snapshot, lock_version, started_at, ended_at, created_by, created_at, not_tested_reason, cancel_requested_at, cancel_requested_by, display_no) FROM stdin;
8dd151a4-cfdb-45be-8775-94a84b86c834	540f2fa1-53f8-4e43-9841-8eb881a0c529	a9feb4f2-9d51-4d6e-9ea1-aeb423901f5f	android	629f6c29-1023-4ecb-beec-4e866029493a	\N	bf2c39ae-ac3f-4947-a1a6-fde368a1be56	completed	failed	\N	fab1ee61-4ece-4fc5-92bc-4bc0b13427a2	f2cac493-a152-47fb-b25a-fa7d5672dc85	{"device": {"resource_id": "fab1ee61-4ece-4fc5-92bc-4bc0b13427a2", "allow_busy_queue": true}, "module": "ui", "source": "api", "platform": "android", "scenario": null, "app_version": null, "gate_policy": null, "request_key": "bf2c39ae-ac3f-4947-a1a6-fde368a1be56", "package_name": "com.miui.calculator", "submitted_at": "2026-11-08T12:17:47.306148+00:00", "application_id": "a9feb4f2-9d51-4d6e-9ea1-aeb423901f5f", "application_platform": "android", "requested_resource_id": "fab1ee61-4ece-4fc5-92bc-4bc0b13427a2"}	6	2026-11-08 20:18:08.719638+08	2026-11-08 20:18:08.719638+08	web	2026-11-08 20:17:47.299654+08	\N	\N	\N	1
ba117777-b04d-48e0-ba3d-7af289d66244	540f2fa1-53f8-4e43-9841-8eb881a0c529	a9feb4f2-9d51-4d6e-9ea1-aeb423901f5f	android	629f6c29-1023-4ecb-beec-4e866029493a	8dd151a4-cfdb-45be-8775-94a84b86c834	fff0db32-dda7-4990-8ae0-950f9c4748d9	completed	failed	\N	fab1ee61-4ece-4fc5-92bc-4bc0b13427a2	f2cac493-a152-47fb-b25a-fa7d5672dc85	{"device": {"resource_id": "fab1ee61-4ece-4fc5-92bc-4bc0b13427a2", "allow_busy_queue": true}, "module": "ui", "source": "api", "platform": "android", "scenario": null, "app_version": null, "gate_policy": null, "request_key": "fff0db32-dda7-4990-8ae0-950f9c4748d9", "package_name": "com.miui.calculator", "submitted_at": "2026-11-08T12:46:01.593278+00:00", "application_id": "a9feb4f2-9d51-4d6e-9ea1-aeb423901f5f", "application_platform": "android", "requested_resource_id": "fab1ee61-4ece-4fc5-92bc-4bc0b13427a2"}	6	2026-11-08 20:46:01.726143+08	2026-11-08 20:46:22.70876+08	web	2026-11-08 20:46:01.588043+08	\N	\N	\N	2
7ca839a0-d955-4a7e-aa64-290382c63453	540f2fa1-53f8-4e43-9841-8eb881a0c529	a9feb4f2-9d51-4d6e-9ea1-aeb423901f5f	android	3af97316-61f7-403c-ae6c-e0f78590340b	\N	1187cf1e-1cb6-4410-bc1d-cc46418c1cdb	completed	not_tested	gate_policy_missing	fab1ee61-4ece-4fc5-92bc-4bc0b13427a2	f2cac493-a152-47fb-b25a-fa7d5672dc85	{"perf": {"items": ["CPU", "Memory", "FPS"], "duration_s": 30}, "device": {"resource_id": "fab1ee61-4ece-4fc5-92bc-4bc0b13427a2", "allow_busy_queue": true}, "module": "perf", "source": "api", "platform": "android", "scenario": null, "app_version": null, "gate_policy": null, "perf_source": "suite_manifest", "request_key": "1187cf1e-1cb6-4410-bc1d-cc46418c1cdb", "package_name": "com.miui.calculator", "submitted_at": "2026-11-08T12:52:58.140947+00:00", "application_id": "a9feb4f2-9d51-4d6e-9ea1-aeb423901f5f", "application_platform": "android", "requested_resource_id": "fab1ee61-4ece-4fc5-92bc-4bc0b13427a2"}	6	2026-11-08 20:52:58.510732+08	2026-11-08 20:53:33.424816+08	web	2026-11-08 20:52:58.135038+08	gate_policy_missing	\N	\N	3
b7899bcf-7d37-48ec-81be-0407340d0b03	540f2fa1-53f8-4e43-9841-8eb881a0c529	a9feb4f2-9d51-4d6e-9ea1-aeb423901f5f	android	0440b605-94d6-4312-a161-1285f4d40c04	\N	9570973b-c3ac-4246-847c-3909a013aa4d	cancelled	\N	cancel_requested	fab1ee61-4ece-4fc5-92bc-4bc0b13427a2	f2cac493-a152-47fb-b25a-fa7d5672dc85	{"perf": {"items": ["CPU", "Memory", "FPS"], "duration_s": 30}, "device": {"resource_id": "fab1ee61-4ece-4fc5-92bc-4bc0b13427a2", "allow_busy_queue": true}, "module": "joint", "source": "api", "platform": "android", "scenario": null, "app_version": null, "gate_policy": {"id": "d32da8aa-7976-4a79-87a6-6f138ba3c1b5", "rules": {}, "version": 1}, "perf_source": "suite_manifest", "request_key": "9570973b-c3ac-4246-847c-3909a013aa4d", "package_name": "com.miui.calculator", "submitted_at": "2026-11-08T13:14:57.109820+00:00", "application_id": "a9feb4f2-9d51-4d6e-9ea1-aeb423901f5f", "application_platform": "android", "requested_resource_id": "fab1ee61-4ece-4fc5-92bc-4bc0b13427a2"}	4	2026-11-08 21:14:57.899955+08	2026-11-08 21:15:15.668193+08	web	2026-11-08 21:14:57.103059+08	\N	2026-11-08 21:15:15.329637+08	web	5
ec832d64-466a-437a-8dcc-6a2efb9eede6	540f2fa1-53f8-4e43-9841-8eb881a0c529	a9feb4f2-9d51-4d6e-9ea1-aeb423901f5f	android	0440b605-94d6-4312-a161-1285f4d40c04	\N	5e5d2504-9ca4-4fd5-9334-fd2db969a2d4	completed	failed	\N	fab1ee61-4ece-4fc5-92bc-4bc0b13427a2	f2cac493-a152-47fb-b25a-fa7d5672dc85	{"perf": {"items": ["CPU", "Memory", "FPS"], "duration_s": 30}, "device": {"resource_id": "fab1ee61-4ece-4fc5-92bc-4bc0b13427a2", "allow_busy_queue": true}, "module": "joint", "source": "api", "platform": "android", "scenario": null, "app_version": null, "gate_policy": {"id": "d32da8aa-7976-4a79-87a6-6f138ba3c1b5", "rules": {}, "version": 1}, "perf_source": "suite_manifest", "request_key": "5e5d2504-9ca4-4fd5-9334-fd2db969a2d4", "package_name": "com.miui.calculator", "submitted_at": "2026-11-08T13:12:19.800147+00:00", "application_id": "a9feb4f2-9d51-4d6e-9ea1-aeb423901f5f", "application_platform": "android", "requested_resource_id": "fab1ee61-4ece-4fc5-92bc-4bc0b13427a2"}	6	2026-11-08 21:12:21.520049+08	2026-11-08 21:12:46.205621+08	web	2026-11-08 21:12:19.796903+08	\N	\N	\N	4
2b814545-aada-4196-90ae-706dbbaf4d76	540f2fa1-53f8-4e43-9841-8eb881a0c529	a9feb4f2-9d51-4d6e-9ea1-aeb423901f5f	android	0440b605-94d6-4312-a161-1285f4d40c04	\N	rr-joint-complete-1794143794	completed	failed	\N	fab1ee61-4ece-4fc5-92bc-4bc0b13427a2	f2cac493-a152-47fb-b25a-fa7d5672dc85	{"perf": {"items": ["CPU", "Memory", "FPS"], "duration_s": 30}, "device": {"resource_id": "fab1ee61-4ece-4fc5-92bc-4bc0b13427a2", "allow_busy_queue": true}, "module": "joint", "source": "api", "platform": "android", "scenario": null, "app_version": null, "gate_policy": {"id": "d32da8aa-7976-4a79-87a6-6f138ba3c1b5", "rules": {}, "version": 1}, "perf_source": "suite_manifest", "request_key": "rr-joint-complete-1794143794", "package_name": "com.miui.calculator", "submitted_at": "2026-11-08T13:16:34.271497+00:00", "application_id": "a9feb4f2-9d51-4d6e-9ea1-aeb423901f5f", "application_platform": "android", "requested_resource_id": "fab1ee61-4ece-4fc5-92bc-4bc0b13427a2"}	6	2026-11-08 21:16:36.28887+08	2026-11-08 21:17:03.102559+08	web	2026-11-08 21:16:34.267508+08	\N	\N	\N	6
99e0459d-5d6d-40ec-9d33-7d4848664a0f	540f2fa1-53f8-4e43-9841-8eb881a0c529	a9feb4f2-9d51-4d6e-9ea1-aeb423901f5f	android	0440b605-94d6-4312-a161-1285f4d40c04	\N	rr-after-debug-1794144090	completed	failed	\N	fab1ee61-4ece-4fc5-92bc-4bc0b13427a2	f2cac493-a152-47fb-b25a-fa7d5672dc85	{"perf": {"items": ["CPU", "Memory", "FPS"], "duration_s": 30}, "device": {"resource_id": "fab1ee61-4ece-4fc5-92bc-4bc0b13427a2", "allow_busy_queue": true}, "module": "joint", "source": "api", "platform": "android", "scenario": null, "app_version": null, "gate_policy": {"id": "d32da8aa-7976-4a79-87a6-6f138ba3c1b5", "rules": {}, "version": 1}, "perf_source": "suite_manifest", "request_key": "rr-after-debug-1794144090", "package_name": "com.miui.calculator", "submitted_at": "2026-11-08T13:21:30.478704+00:00", "application_id": "a9feb4f2-9d51-4d6e-9ea1-aeb423901f5f", "application_platform": "android", "requested_resource_id": "fab1ee61-4ece-4fc5-92bc-4bc0b13427a2"}	6	2026-11-08 21:21:31.003452+08	2026-11-08 21:21:55.980553+08	web	2026-11-08 21:21:30.473663+08	\N	\N	\N	7
d8c1ea76-e45d-4629-8152-bb2697af04f0	540f2fa1-53f8-4e43-9841-8eb881a0c529	a9feb4f2-9d51-4d6e-9ea1-aeb423901f5f	android	0440b605-94d6-4312-a161-1285f4d40c04	\N	rr-mutex-1794144223	completed	failed	\N	fab1ee61-4ece-4fc5-92bc-4bc0b13427a2	f2cac493-a152-47fb-b25a-fa7d5672dc85	{"perf": {"items": ["CPU", "Memory", "FPS"], "duration_s": 30}, "device": {"resource_id": "fab1ee61-4ece-4fc5-92bc-4bc0b13427a2", "allow_busy_queue": true}, "module": "joint", "source": "api", "platform": "android", "scenario": null, "app_version": null, "gate_policy": {"id": "d32da8aa-7976-4a79-87a6-6f138ba3c1b5", "rules": {}, "version": 1}, "perf_source": "suite_manifest", "request_key": "rr-mutex-1794144223", "package_name": "com.miui.calculator", "submitted_at": "2026-11-08T13:23:43.650774+00:00", "application_id": "a9feb4f2-9d51-4d6e-9ea1-aeb423901f5f", "application_platform": "android", "requested_resource_id": "fab1ee61-4ece-4fc5-92bc-4bc0b13427a2"}	6	2026-11-08 21:23:45.279794+08	2026-11-08 21:24:09.471599+08	web	2026-11-08 21:23:43.645086+08	\N	\N	\N	8
8d475676-44ec-42b3-a239-911a9ec3f7cb	540f2fa1-53f8-4e43-9841-8eb881a0c529	a9feb4f2-9d51-4d6e-9ea1-aeb423901f5f	android	0440b605-94d6-4312-a161-1285f4d40c04	\N	rr-mutex2-1794144302	cancelled	\N	cancel_requested	\N	\N	{"perf": {"items": ["CPU", "Memory", "FPS"], "duration_s": 30}, "device": {"resource_id": "fab1ee61-4ece-4fc5-92bc-4bc0b13427a2", "allow_busy_queue": true}, "module": "joint", "source": "api", "platform": "android", "scenario": null, "app_version": null, "gate_policy": {"id": "d32da8aa-7976-4a79-87a6-6f138ba3c1b5", "rules": {}, "version": 1}, "perf_source": "suite_manifest", "request_key": "rr-mutex2-1794144302", "package_name": "com.miui.calculator", "submitted_at": "2026-11-08T13:25:02.917102+00:00", "application_id": "a9feb4f2-9d51-4d6e-9ea1-aeb423901f5f", "application_platform": "android", "requested_resource_id": "fab1ee61-4ece-4fc5-92bc-4bc0b13427a2"}	2	\N	2026-11-08 21:25:23.230891+08	web	2026-11-08 21:25:02.908528+08	\N	2026-11-08 21:25:23.230891+08	web	9
2e43d5e0-1374-4c71-8b4d-586ca1033e5a	540f2fa1-53f8-4e43-9841-8eb881a0c529	a9feb4f2-9d51-4d6e-9ea1-aeb423901f5f	android	0440b605-94d6-4312-a161-1285f4d40c04	\N	rr-mutex2-1794144354	cancelled	\N	cancel_requested	fab1ee61-4ece-4fc5-92bc-4bc0b13427a2	f2cac493-a152-47fb-b25a-fa7d5672dc85	{"perf": {"items": ["CPU", "Memory", "FPS"], "duration_s": 30}, "device": {"resource_id": "fab1ee61-4ece-4fc5-92bc-4bc0b13427a2", "allow_busy_queue": true}, "module": "joint", "source": "api", "platform": "android", "scenario": null, "app_version": null, "gate_policy": {"id": "d32da8aa-7976-4a79-87a6-6f138ba3c1b5", "rules": {}, "version": 1}, "perf_source": "suite_manifest", "request_key": "rr-mutex2-1794144354", "package_name": "com.miui.calculator", "submitted_at": "2026-11-08T13:25:54.402946+00:00", "application_id": "a9feb4f2-9d51-4d6e-9ea1-aeb423901f5f", "application_platform": "android", "requested_resource_id": "fab1ee61-4ece-4fc5-92bc-4bc0b13427a2"}	4	2026-11-08 21:25:55.695293+08	2026-11-08 21:25:56.358498+08	web	2026-11-08 21:25:54.397665+08	\N	2026-11-08 21:25:55.997381+08	web	10
\.


--
-- Data for Name: test_suites; Type: TABLE DATA; Schema: public; Owner: testdock
--

COPY public.test_suites (id, project_id, application_id, name, test_type, archived_at, created_at) FROM stdin;
cab2999d-7bda-44fd-9d98-c35b4fec1f5d	540f2fa1-53f8-4e43-9841-8eb881a0c529	a9feb4f2-9d51-4d6e-9ea1-aeb423901f5f	计算器冒烟套件	ui	\N	2026-11-08 20:07:02.653805+08
3edfd7c2-454b-4bb9-8850-33f4e25bbbd4	540f2fa1-53f8-4e43-9841-8eb881a0c529	a9feb4f2-9d51-4d6e-9ea1-aeb423901f5f	计算器性能场景-30s	performance	\N	2026-11-08 20:50:55.95919+08
6c3aa40d-a113-4f38-86e0-b51fb28cc078	540f2fa1-53f8-4e43-9841-8eb881a0c529	a9feb4f2-9d51-4d6e-9ea1-aeb423901f5f	计算器联动套件	joint	\N	2026-11-08 20:58:14.336005+08
\.


--
-- Data for Name: test_tasks; Type: TABLE DATA; Schema: public; Owner: testdock
--

COPY public.test_tasks (id, project_id, application_id, name, lifecycle, lock_version, created_by, updated_at, created_at) FROM stdin;
68791794-33e0-4f11-826d-62b95952e978	540f2fa1-53f8-4e43-9841-8eb881a0c529	a9feb4f2-9d51-4d6e-9ea1-aeb423901f5f	计算器冒烟-成功基线	ready	2	web-client	2026-11-08 20:17:31.95634+08	2026-11-08 20:16:47.799756+08
d8b3deec-8b19-4f9d-9a31-c04bfcfdf2a0	540f2fa1-53f8-4e43-9841-8eb881a0c529	a9feb4f2-9d51-4d6e-9ea1-aeb423901f5f	计算器性能采集-30s	ready	2	web-client	2026-11-08 20:52:42.341354+08	2026-11-08 20:52:04.506103+08
02fb058b-7091-48cd-887d-7dd61c725e4f	540f2fa1-53f8-4e43-9841-8eb881a0c529	a9feb4f2-9d51-4d6e-9ea1-aeb423901f5f	计算器联动-30s	ready	2	web-client	2026-11-08 21:12:05.750753+08	2026-11-08 21:11:51.436902+08
\.


--
-- Data for Name: workspace_settings; Type: TABLE DATA; Schema: public; Owner: testdock
--

COPY public.workspace_settings (id, name, customized_at, updated_at) FROM stdin;
1	交付验收工作空间	2026-11-08 20:01:19.6491+08	2026-11-08 20:01:19.6491+08
\.


--
-- Name: test_run_display_no_seq; Type: SEQUENCE SET; Schema: public; Owner: testdock
--

SELECT pg_catalog.setval('public.test_run_display_no_seq', 10, true);


--
-- Name: workspace_settings_id_seq; Type: SEQUENCE SET; Schema: public; Owner: testdock
--

SELECT pg_catalog.setval('public.workspace_settings_id_seq', 1, false);


--
-- Name: alembic_version alembic_version_pkc; Type: CONSTRAINT; Schema: public; Owner: testdock
--

ALTER TABLE ONLY public.alembic_version
    ADD CONSTRAINT alembic_version_pkc PRIMARY KEY (version_num);


--
-- Name: app_builds app_builds_pkey; Type: CONSTRAINT; Schema: public; Owner: testdock
--

ALTER TABLE ONLY public.app_builds
    ADD CONSTRAINT app_builds_pkey PRIMARY KEY (id);


--
-- Name: applications applications_pkey; Type: CONSTRAINT; Schema: public; Owner: testdock
--

ALTER TABLE ONLY public.applications
    ADD CONSTRAINT applications_pkey PRIMARY KEY (id);


--
-- Name: artifacts artifacts_pkey; Type: CONSTRAINT; Schema: public; Owner: testdock
--

ALTER TABLE ONLY public.artifacts
    ADD CONSTRAINT artifacts_pkey PRIMARY KEY (id);


--
-- Name: audit_events audit_events_pkey; Type: CONSTRAINT; Schema: public; Owner: testdock
--

ALTER TABLE ONLY public.audit_events
    ADD CONSTRAINT audit_events_pkey PRIMARY KEY (id);


--
-- Name: baselines baselines_pkey; Type: CONSTRAINT; Schema: public; Owner: testdock
--

ALTER TABLE ONLY public.baselines
    ADD CONSTRAINT baselines_pkey PRIMARY KEY (id);


--
-- Name: case_results case_results_pkey; Type: CONSTRAINT; Schema: public; Owner: testdock
--

ALTER TABLE ONLY public.case_results
    ADD CONSTRAINT case_results_pkey PRIMARY KEY (id);


--
-- Name: debug_sessions debug_sessions_pkey; Type: CONSTRAINT; Schema: public; Owner: testdock
--

ALTER TABLE ONLY public.debug_sessions
    ADD CONSTRAINT debug_sessions_pkey PRIMARY KEY (id);


--
-- Name: device_checks device_checks_pkey; Type: CONSTRAINT; Schema: public; Owner: testdock
--

ALTER TABLE ONLY public.device_checks
    ADD CONSTRAINT device_checks_pkey PRIMARY KEY (id);


--
-- Name: environments environments_pkey; Type: CONSTRAINT; Schema: public; Owner: testdock
--

ALTER TABLE ONLY public.environments
    ADD CONSTRAINT environments_pkey PRIMARY KEY (id);


--
-- Name: execution_nodes execution_nodes_pkey; Type: CONSTRAINT; Schema: public; Owner: testdock
--

ALTER TABLE ONLY public.execution_nodes
    ADD CONSTRAINT execution_nodes_pkey PRIMARY KEY (id);


--
-- Name: execution_resources execution_resources_pkey; Type: CONSTRAINT; Schema: public; Owner: testdock
--

ALTER TABLE ONLY public.execution_resources
    ADD CONSTRAINT execution_resources_pkey PRIMARY KEY (id);


--
-- Name: gate_evaluations gate_evaluations_pkey; Type: CONSTRAINT; Schema: public; Owner: testdock
--

ALTER TABLE ONLY public.gate_evaluations
    ADD CONSTRAINT gate_evaluations_pkey PRIMARY KEY (id);


--
-- Name: gate_policies gate_policies_pkey; Type: CONSTRAINT; Schema: public; Owner: testdock
--

ALTER TABLE ONLY public.gate_policies
    ADD CONSTRAINT gate_policies_pkey PRIMARY KEY (id);


--
-- Name: metric_summaries metric_summaries_pkey; Type: CONSTRAINT; Schema: public; Owner: testdock
--

ALTER TABLE ONLY public.metric_summaries
    ADD CONSTRAINT metric_summaries_pkey PRIMARY KEY (id);


--
-- Name: project_members project_members_pkey; Type: CONSTRAINT; Schema: public; Owner: testdock
--

ALTER TABLE ONLY public.project_members
    ADD CONSTRAINT project_members_pkey PRIMARY KEY (id);


--
-- Name: projects projects_code_key; Type: CONSTRAINT; Schema: public; Owner: testdock
--

ALTER TABLE ONLY public.projects
    ADD CONSTRAINT projects_code_key UNIQUE (code);


--
-- Name: projects projects_pkey; Type: CONSTRAINT; Schema: public; Owner: testdock
--

ALTER TABLE ONLY public.projects
    ADD CONSTRAINT projects_pkey PRIMARY KEY (id);


--
-- Name: resource_leases resource_leases_pkey; Type: CONSTRAINT; Schema: public; Owner: testdock
--

ALTER TABLE ONLY public.resource_leases
    ADD CONSTRAINT resource_leases_pkey PRIMARY KEY (id);


--
-- Name: resource_profiles resource_profiles_pkey; Type: CONSTRAINT; Schema: public; Owner: testdock
--

ALTER TABLE ONLY public.resource_profiles
    ADD CONSTRAINT resource_profiles_pkey PRIMARY KEY (id);


--
-- Name: run_components run_components_pkey; Type: CONSTRAINT; Schema: public; Owner: testdock
--

ALTER TABLE ONLY public.run_components
    ADD CONSTRAINT run_components_pkey PRIMARY KEY (id);


--
-- Name: run_events run_events_pkey; Type: CONSTRAINT; Schema: public; Owner: testdock
--

ALTER TABLE ONLY public.run_events
    ADD CONSTRAINT run_events_pkey PRIMARY KEY (id);


--
-- Name: suite_versions suite_versions_pkey; Type: CONSTRAINT; Schema: public; Owner: testdock
--

ALTER TABLE ONLY public.suite_versions
    ADD CONSTRAINT suite_versions_pkey PRIMARY KEY (id);


--
-- Name: task_request_keys task_request_keys_pkey; Type: CONSTRAINT; Schema: public; Owner: testdock
--

ALTER TABLE ONLY public.task_request_keys
    ADD CONSTRAINT task_request_keys_pkey PRIMARY KEY (id);


--
-- Name: task_revisions task_revisions_pkey; Type: CONSTRAINT; Schema: public; Owner: testdock
--

ALTER TABLE ONLY public.task_revisions
    ADD CONSTRAINT task_revisions_pkey PRIMARY KEY (id);


--
-- Name: test_runs test_runs_pkey; Type: CONSTRAINT; Schema: public; Owner: testdock
--

ALTER TABLE ONLY public.test_runs
    ADD CONSTRAINT test_runs_pkey PRIMARY KEY (id);


--
-- Name: test_suites test_suites_pkey; Type: CONSTRAINT; Schema: public; Owner: testdock
--

ALTER TABLE ONLY public.test_suites
    ADD CONSTRAINT test_suites_pkey PRIMARY KEY (id);


--
-- Name: test_tasks test_tasks_pkey; Type: CONSTRAINT; Schema: public; Owner: testdock
--

ALTER TABLE ONLY public.test_tasks
    ADD CONSTRAINT test_tasks_pkey PRIMARY KEY (id);


--
-- Name: app_builds uq_app_builds_project_id_application_id_build_key; Type: CONSTRAINT; Schema: public; Owner: testdock
--

ALTER TABLE ONLY public.app_builds
    ADD CONSTRAINT uq_app_builds_project_id_application_id_build_key UNIQUE (project_id, application_id, build_key);


--
-- Name: app_builds uq_app_builds_project_id_application_id_id; Type: CONSTRAINT; Schema: public; Owner: testdock
--

ALTER TABLE ONLY public.app_builds
    ADD CONSTRAINT uq_app_builds_project_id_application_id_id UNIQUE (project_id, application_id, id);


--
-- Name: app_builds uq_app_builds_project_id_id; Type: CONSTRAINT; Schema: public; Owner: testdock
--

ALTER TABLE ONLY public.app_builds
    ADD CONSTRAINT uq_app_builds_project_id_id UNIQUE (project_id, id);


--
-- Name: applications uq_applications_project_id_id; Type: CONSTRAINT; Schema: public; Owner: testdock
--

ALTER TABLE ONLY public.applications
    ADD CONSTRAINT uq_applications_project_id_id UNIQUE (project_id, id);


--
-- Name: applications uq_applications_project_id_id_platform; Type: CONSTRAINT; Schema: public; Owner: testdock
--

ALTER TABLE ONLY public.applications
    ADD CONSTRAINT uq_applications_project_id_id_platform UNIQUE (project_id, id, platform);


--
-- Name: applications uq_applications_project_id_platform_identifier; Type: CONSTRAINT; Schema: public; Owner: testdock
--

ALTER TABLE ONLY public.applications
    ADD CONSTRAINT uq_applications_project_id_platform_identifier UNIQUE (project_id, platform, identifier);


--
-- Name: artifacts uq_artifacts_project_id_id; Type: CONSTRAINT; Schema: public; Owner: testdock
--

ALTER TABLE ONLY public.artifacts
    ADD CONSTRAINT uq_artifacts_project_id_id UNIQUE (project_id, id);


--
-- Name: artifacts uq_artifacts_project_id_run_id_logical_key; Type: CONSTRAINT; Schema: public; Owner: testdock
--

ALTER TABLE ONLY public.artifacts
    ADD CONSTRAINT uq_artifacts_project_id_run_id_logical_key UNIQUE (project_id, run_id, logical_key);


--
-- Name: artifacts uq_artifacts_project_id_storage_key; Type: CONSTRAINT; Schema: public; Owner: testdock
--

ALTER TABLE ONLY public.artifacts
    ADD CONSTRAINT uq_artifacts_project_id_storage_key UNIQUE (project_id, storage_key);


--
-- Name: audit_events uq_audit_events_project_id_id; Type: CONSTRAINT; Schema: public; Owner: testdock
--

ALTER TABLE ONLY public.audit_events
    ADD CONSTRAINT uq_audit_events_project_id_id UNIQUE (project_id, id);


--
-- Name: baselines uq_baselines_project_id_application_id_name_version; Type: CONSTRAINT; Schema: public; Owner: testdock
--

ALTER TABLE ONLY public.baselines
    ADD CONSTRAINT uq_baselines_project_id_application_id_name_version UNIQUE (project_id, application_id, name, version);


--
-- Name: baselines uq_baselines_project_id_id; Type: CONSTRAINT; Schema: public; Owner: testdock
--

ALTER TABLE ONLY public.baselines
    ADD CONSTRAINT uq_baselines_project_id_id UNIQUE (project_id, id);


--
-- Name: case_results uq_case_results_project_id_component_id_case_key_attempt; Type: CONSTRAINT; Schema: public; Owner: testdock
--

ALTER TABLE ONLY public.case_results
    ADD CONSTRAINT uq_case_results_project_id_component_id_case_key_attempt UNIQUE (project_id, component_id, case_key, attempt);


--
-- Name: case_results uq_case_results_project_id_id; Type: CONSTRAINT; Schema: public; Owner: testdock
--

ALTER TABLE ONLY public.case_results
    ADD CONSTRAINT uq_case_results_project_id_id UNIQUE (project_id, id);


--
-- Name: debug_sessions uq_debug_sessions_project_id_id; Type: CONSTRAINT; Schema: public; Owner: testdock
--

ALTER TABLE ONLY public.debug_sessions
    ADD CONSTRAINT uq_debug_sessions_project_id_id UNIQUE (project_id, id);


--
-- Name: debug_sessions uq_debug_sessions_project_id_id_resource_id; Type: CONSTRAINT; Schema: public; Owner: testdock
--

ALTER TABLE ONLY public.debug_sessions
    ADD CONSTRAINT uq_debug_sessions_project_id_id_resource_id UNIQUE (project_id, id, resource_id);


--
-- Name: device_checks uq_device_checks_project_id_id; Type: CONSTRAINT; Schema: public; Owner: testdock
--

ALTER TABLE ONLY public.device_checks
    ADD CONSTRAINT uq_device_checks_project_id_id UNIQUE (project_id, id);


--
-- Name: device_checks uq_device_checks_project_id_id_resource_id; Type: CONSTRAINT; Schema: public; Owner: testdock
--

ALTER TABLE ONLY public.device_checks
    ADD CONSTRAINT uq_device_checks_project_id_id_resource_id UNIQUE (project_id, id, resource_id);


--
-- Name: environments uq_environments_project_id_id; Type: CONSTRAINT; Schema: public; Owner: testdock
--

ALTER TABLE ONLY public.environments
    ADD CONSTRAINT uq_environments_project_id_id UNIQUE (project_id, id);


--
-- Name: environments uq_environments_project_id_name; Type: CONSTRAINT; Schema: public; Owner: testdock
--

ALTER TABLE ONLY public.environments
    ADD CONSTRAINT uq_environments_project_id_name UNIQUE (project_id, name);


--
-- Name: execution_nodes uq_execution_nodes_project_id_id; Type: CONSTRAINT; Schema: public; Owner: testdock
--

ALTER TABLE ONLY public.execution_nodes
    ADD CONSTRAINT uq_execution_nodes_project_id_id UNIQUE (project_id, id);


--
-- Name: execution_nodes uq_execution_nodes_project_id_name; Type: CONSTRAINT; Schema: public; Owner: testdock
--

ALTER TABLE ONLY public.execution_nodes
    ADD CONSTRAINT uq_execution_nodes_project_id_name UNIQUE (project_id, name);


--
-- Name: execution_resources uq_execution_resources_project_id_id; Type: CONSTRAINT; Schema: public; Owner: testdock
--

ALTER TABLE ONLY public.execution_resources
    ADD CONSTRAINT uq_execution_resources_project_id_id UNIQUE (project_id, id);


--
-- Name: execution_resources uq_execution_resources_project_id_id_platform; Type: CONSTRAINT; Schema: public; Owner: testdock
--

ALTER TABLE ONLY public.execution_resources
    ADD CONSTRAINT uq_execution_resources_project_id_id_platform UNIQUE (project_id, id, platform);


--
-- Name: execution_resources uq_execution_resources_project_id_node_id_resource_key; Type: CONSTRAINT; Schema: public; Owner: testdock
--

ALTER TABLE ONLY public.execution_resources
    ADD CONSTRAINT uq_execution_resources_project_id_node_id_resource_key UNIQUE (project_id, node_id, resource_key);


--
-- Name: gate_evaluations uq_gate_evaluations_project_id_id; Type: CONSTRAINT; Schema: public; Owner: testdock
--

ALTER TABLE ONLY public.gate_evaluations
    ADD CONSTRAINT uq_gate_evaluations_project_id_id UNIQUE (project_id, id);


--
-- Name: gate_evaluations uq_gate_evaluations_project_id_request_key; Type: CONSTRAINT; Schema: public; Owner: testdock
--

ALTER TABLE ONLY public.gate_evaluations
    ADD CONSTRAINT uq_gate_evaluations_project_id_request_key UNIQUE (project_id, request_key);


--
-- Name: gate_policies uq_gate_policies_project_id_application_id_name_version; Type: CONSTRAINT; Schema: public; Owner: testdock
--

ALTER TABLE ONLY public.gate_policies
    ADD CONSTRAINT uq_gate_policies_project_id_application_id_name_version UNIQUE (project_id, application_id, name, version);


--
-- Name: gate_policies uq_gate_policies_project_id_id; Type: CONSTRAINT; Schema: public; Owner: testdock
--

ALTER TABLE ONLY public.gate_policies
    ADD CONSTRAINT uq_gate_policies_project_id_id UNIQUE (project_id, id);


--
-- Name: metric_summaries uq_metric_summaries_project_id_component_id_metric_key_44fb8051; Type: CONSTRAINT; Schema: public; Owner: testdock
--

ALTER TABLE ONLY public.metric_summaries
    ADD CONSTRAINT uq_metric_summaries_project_id_component_id_metric_key_44fb8051 UNIQUE (project_id, component_id, metric_key, metric_version, scope, window_key, statistic);


--
-- Name: metric_summaries uq_metric_summaries_project_id_id; Type: CONSTRAINT; Schema: public; Owner: testdock
--

ALTER TABLE ONLY public.metric_summaries
    ADD CONSTRAINT uq_metric_summaries_project_id_id UNIQUE (project_id, id);


--
-- Name: project_members uq_project_members_project_id_identity_issuer_identity_subject; Type: CONSTRAINT; Schema: public; Owner: testdock
--

ALTER TABLE ONLY public.project_members
    ADD CONSTRAINT uq_project_members_project_id_identity_issuer_identity_subject UNIQUE (project_id, identity_issuer, identity_subject);


--
-- Name: resource_leases uq_resource_leases_project_id_id; Type: CONSTRAINT; Schema: public; Owner: testdock
--

ALTER TABLE ONLY public.resource_leases
    ADD CONSTRAINT uq_resource_leases_project_id_id UNIQUE (project_id, id);


--
-- Name: resource_leases uq_resource_leases_project_id_resource_id_fencing_token; Type: CONSTRAINT; Schema: public; Owner: testdock
--

ALTER TABLE ONLY public.resource_leases
    ADD CONSTRAINT uq_resource_leases_project_id_resource_id_fencing_token UNIQUE (project_id, resource_id, fencing_token);


--
-- Name: resource_profiles uq_resource_profiles_project_id_id; Type: CONSTRAINT; Schema: public; Owner: testdock
--

ALTER TABLE ONLY public.resource_profiles
    ADD CONSTRAINT uq_resource_profiles_project_id_id UNIQUE (project_id, id);


--
-- Name: resource_profiles uq_resource_profiles_project_id_id_platform; Type: CONSTRAINT; Schema: public; Owner: testdock
--

ALTER TABLE ONLY public.resource_profiles
    ADD CONSTRAINT uq_resource_profiles_project_id_id_platform UNIQUE (project_id, id, platform);


--
-- Name: resource_profiles uq_resource_profiles_project_id_platform_fingerprint; Type: CONSTRAINT; Schema: public; Owner: testdock
--

ALTER TABLE ONLY public.resource_profiles
    ADD CONSTRAINT uq_resource_profiles_project_id_platform_fingerprint UNIQUE (project_id, platform, fingerprint);


--
-- Name: run_components uq_run_components_project_id_id; Type: CONSTRAINT; Schema: public; Owner: testdock
--

ALTER TABLE ONLY public.run_components
    ADD CONSTRAINT uq_run_components_project_id_id UNIQUE (project_id, id);


--
-- Name: run_components uq_run_components_project_id_run_id_id; Type: CONSTRAINT; Schema: public; Owner: testdock
--

ALTER TABLE ONLY public.run_components
    ADD CONSTRAINT uq_run_components_project_id_run_id_id UNIQUE (project_id, run_id, id);


--
-- Name: run_components uq_run_components_project_id_run_id_kind; Type: CONSTRAINT; Schema: public; Owner: testdock
--

ALTER TABLE ONLY public.run_components
    ADD CONSTRAINT uq_run_components_project_id_run_id_kind UNIQUE (project_id, run_id, kind);


--
-- Name: run_events uq_run_events_project_id_id; Type: CONSTRAINT; Schema: public; Owner: testdock
--

ALTER TABLE ONLY public.run_events
    ADD CONSTRAINT uq_run_events_project_id_id UNIQUE (project_id, id);


--
-- Name: run_events uq_run_events_project_id_run_id_sequence; Type: CONSTRAINT; Schema: public; Owner: testdock
--

ALTER TABLE ONLY public.run_events
    ADD CONSTRAINT uq_run_events_project_id_run_id_sequence UNIQUE (project_id, run_id, sequence);


--
-- Name: run_events uq_run_events_project_id_run_id_source_key_source_event_id; Type: CONSTRAINT; Schema: public; Owner: testdock
--

ALTER TABLE ONLY public.run_events
    ADD CONSTRAINT uq_run_events_project_id_run_id_source_key_source_event_id UNIQUE (project_id, run_id, source_key, source_event_id);


--
-- Name: suite_versions uq_suite_versions_project_id_application_id_id; Type: CONSTRAINT; Schema: public; Owner: testdock
--

ALTER TABLE ONLY public.suite_versions
    ADD CONSTRAINT uq_suite_versions_project_id_application_id_id UNIQUE (project_id, application_id, id);


--
-- Name: suite_versions uq_suite_versions_project_id_id; Type: CONSTRAINT; Schema: public; Owner: testdock
--

ALTER TABLE ONLY public.suite_versions
    ADD CONSTRAINT uq_suite_versions_project_id_id UNIQUE (project_id, id);


--
-- Name: suite_versions uq_suite_versions_project_id_suite_id_version; Type: CONSTRAINT; Schema: public; Owner: testdock
--

ALTER TABLE ONLY public.suite_versions
    ADD CONSTRAINT uq_suite_versions_project_id_suite_id_version UNIQUE (project_id, suite_id, version);


--
-- Name: task_request_keys uq_task_request_keys_project_id_request_key; Type: CONSTRAINT; Schema: public; Owner: testdock
--

ALTER TABLE ONLY public.task_request_keys
    ADD CONSTRAINT uq_task_request_keys_project_id_request_key UNIQUE (project_id, request_key);


--
-- Name: task_revisions uq_task_revisions_project_id_application_id_id; Type: CONSTRAINT; Schema: public; Owner: testdock
--

ALTER TABLE ONLY public.task_revisions
    ADD CONSTRAINT uq_task_revisions_project_id_application_id_id UNIQUE (project_id, application_id, id);


--
-- Name: task_revisions uq_task_revisions_project_id_id; Type: CONSTRAINT; Schema: public; Owner: testdock
--

ALTER TABLE ONLY public.task_revisions
    ADD CONSTRAINT uq_task_revisions_project_id_id UNIQUE (project_id, id);


--
-- Name: task_revisions uq_task_revisions_project_id_task_id_revision; Type: CONSTRAINT; Schema: public; Owner: testdock
--

ALTER TABLE ONLY public.task_revisions
    ADD CONSTRAINT uq_task_revisions_project_id_task_id_revision UNIQUE (project_id, task_id, revision);


--
-- Name: test_runs uq_test_runs_project_id_application_id_id; Type: CONSTRAINT; Schema: public; Owner: testdock
--

ALTER TABLE ONLY public.test_runs
    ADD CONSTRAINT uq_test_runs_project_id_application_id_id UNIQUE (project_id, application_id, id);


--
-- Name: test_runs uq_test_runs_project_id_id; Type: CONSTRAINT; Schema: public; Owner: testdock
--

ALTER TABLE ONLY public.test_runs
    ADD CONSTRAINT uq_test_runs_project_id_id UNIQUE (project_id, id);


--
-- Name: test_runs uq_test_runs_project_id_id_resource_id; Type: CONSTRAINT; Schema: public; Owner: testdock
--

ALTER TABLE ONLY public.test_runs
    ADD CONSTRAINT uq_test_runs_project_id_id_resource_id UNIQUE (project_id, id, resource_id);


--
-- Name: test_runs uq_test_runs_project_id_request_key; Type: CONSTRAINT; Schema: public; Owner: testdock
--

ALTER TABLE ONLY public.test_runs
    ADD CONSTRAINT uq_test_runs_project_id_request_key UNIQUE (project_id, request_key);


--
-- Name: test_suites uq_test_suites_project_id_application_id_id; Type: CONSTRAINT; Schema: public; Owner: testdock
--

ALTER TABLE ONLY public.test_suites
    ADD CONSTRAINT uq_test_suites_project_id_application_id_id UNIQUE (project_id, application_id, id);


--
-- Name: test_suites uq_test_suites_project_id_application_id_name; Type: CONSTRAINT; Schema: public; Owner: testdock
--

ALTER TABLE ONLY public.test_suites
    ADD CONSTRAINT uq_test_suites_project_id_application_id_name UNIQUE (project_id, application_id, name);


--
-- Name: test_suites uq_test_suites_project_id_id; Type: CONSTRAINT; Schema: public; Owner: testdock
--

ALTER TABLE ONLY public.test_suites
    ADD CONSTRAINT uq_test_suites_project_id_id UNIQUE (project_id, id);


--
-- Name: test_tasks uq_test_tasks_project_id_application_id_id; Type: CONSTRAINT; Schema: public; Owner: testdock
--

ALTER TABLE ONLY public.test_tasks
    ADD CONSTRAINT uq_test_tasks_project_id_application_id_id UNIQUE (project_id, application_id, id);


--
-- Name: test_tasks uq_test_tasks_project_id_id; Type: CONSTRAINT; Schema: public; Owner: testdock
--

ALTER TABLE ONLY public.test_tasks
    ADD CONSTRAINT uq_test_tasks_project_id_id UNIQUE (project_id, id);


--
-- Name: workspace_settings workspace_settings_pkey; Type: CONSTRAINT; Schema: public; Owner: testdock
--

ALTER TABLE ONLY public.workspace_settings
    ADD CONSTRAINT workspace_settings_pkey PRIMARY KEY (id);


--
-- Name: artifacts_expiry; Type: INDEX; Schema: public; Owner: testdock
--

CREATE INDEX artifacts_expiry ON public.artifacts USING btree (expires_at) WHERE (availability = 'available'::text);


--
-- Name: audits_project_time; Type: INDEX; Schema: public; Owner: testdock
--

CREATE INDEX audits_project_time ON public.audit_events USING btree (project_id, created_at DESC, id DESC);


--
-- Name: evaluations_component; Type: INDEX; Schema: public; Owner: testdock
--

CREATE INDEX evaluations_component ON public.gate_evaluations USING btree (project_id, component_id, created_at DESC);


--
-- Name: gate_one_original; Type: INDEX; Schema: public; Owner: testdock
--

CREATE UNIQUE INDEX gate_one_original ON public.gate_evaluations USING btree (project_id, component_id) WHERE (mode = 'original'::text);


--
-- Name: ix_debug_sessions_resource_state; Type: INDEX; Schema: public; Owner: testdock
--

CREATE INDEX ix_debug_sessions_resource_state ON public.debug_sessions USING btree (project_id, resource_id) WHERE (state = ANY (ARRAY['opening'::text, 'active'::text, 'closing'::text]));


--
-- Name: ix_metric_summaries_metric_key; Type: INDEX; Schema: public; Owner: testdock
--

CREATE INDEX ix_metric_summaries_metric_key ON public.metric_summaries USING btree (project_id, metric_key, metric_version, scope, window_key);


--
-- Name: ix_task_revisions_task; Type: INDEX; Schema: public; Owner: testdock
--

CREATE INDEX ix_task_revisions_task ON public.task_revisions USING btree (project_id, task_id);


--
-- Name: ix_test_runs_parent_run; Type: INDEX; Schema: public; Owner: testdock
--

CREATE INDEX ix_test_runs_parent_run ON public.test_runs USING btree (project_id, parent_run_id) WHERE (parent_run_id IS NOT NULL);


--
-- Name: leases_expiry; Type: INDEX; Schema: public; Owner: testdock
--

CREATE INDEX leases_expiry ON public.resource_leases USING btree (expires_at) WHERE (released_at IS NULL);


--
-- Name: leases_one_live_check; Type: INDEX; Schema: public; Owner: testdock
--

CREATE UNIQUE INDEX leases_one_live_check ON public.resource_leases USING btree (project_id, check_id) WHERE (released_at IS NULL);


--
-- Name: leases_one_live_debug; Type: INDEX; Schema: public; Owner: testdock
--

CREATE UNIQUE INDEX leases_one_live_debug ON public.resource_leases USING btree (project_id, debug_session_id) WHERE (released_at IS NULL);


--
-- Name: leases_one_live_resource; Type: INDEX; Schema: public; Owner: testdock
--

CREATE UNIQUE INDEX leases_one_live_resource ON public.resource_leases USING btree (project_id, resource_id) WHERE (released_at IS NULL);


--
-- Name: leases_one_live_run; Type: INDEX; Schema: public; Owner: testdock
--

CREATE UNIQUE INDEX leases_one_live_run ON public.resource_leases USING btree (project_id, run_id) WHERE (released_at IS NULL);


--
-- Name: resources_ready; Type: INDEX; Schema: public; Owner: testdock
--

CREATE INDEX resources_ready ON public.execution_resources USING btree (project_id, platform, status);


--
-- Name: runs_app_recent; Type: INDEX; Schema: public; Owner: testdock
--

CREATE INDEX runs_app_recent ON public.test_runs USING btree (project_id, application_id, created_at DESC, id DESC);


--
-- Name: runs_platform_recent; Type: INDEX; Schema: public; Owner: testdock
--

CREATE INDEX runs_platform_recent ON public.test_runs USING btree (project_id, platform, created_at DESC, id DESC);


--
-- Name: runs_project_recent; Type: INDEX; Schema: public; Owner: testdock
--

CREATE INDEX runs_project_recent ON public.test_runs USING btree (project_id, created_at DESC, id DESC);


--
-- Name: runs_queue; Type: INDEX; Schema: public; Owner: testdock
--

CREATE INDEX runs_queue ON public.test_runs USING btree (created_at, id) WHERE (state = 'queued'::text);


--
-- Name: runs_resource; Type: INDEX; Schema: public; Owner: testdock
--

CREATE INDEX runs_resource ON public.test_runs USING btree (project_id, resource_id);


--
-- Name: runs_revision; Type: INDEX; Schema: public; Owner: testdock
--

CREATE INDEX runs_revision ON public.test_runs USING btree (project_id, revision_id);


--
-- Name: task_request_keys_task; Type: INDEX; Schema: public; Owner: testdock
--

CREATE INDEX task_request_keys_task ON public.task_request_keys USING btree (task_id);


--
-- Name: test_runs_display_no_key; Type: INDEX; Schema: public; Owner: testdock
--

CREATE UNIQUE INDEX test_runs_display_no_key ON public.test_runs USING btree (display_no);


--
-- Name: app_builds app_builds_project_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: testdock
--

ALTER TABLE ONLY public.app_builds
    ADD CONSTRAINT app_builds_project_id_fkey FOREIGN KEY (project_id) REFERENCES public.projects(id);


--
-- Name: applications applications_project_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: testdock
--

ALTER TABLE ONLY public.applications
    ADD CONSTRAINT applications_project_id_fkey FOREIGN KEY (project_id) REFERENCES public.projects(id);


--
-- Name: artifacts artifacts_project_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: testdock
--

ALTER TABLE ONLY public.artifacts
    ADD CONSTRAINT artifacts_project_id_fkey FOREIGN KEY (project_id) REFERENCES public.projects(id);


--
-- Name: audit_events audit_events_project_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: testdock
--

ALTER TABLE ONLY public.audit_events
    ADD CONSTRAINT audit_events_project_id_fkey FOREIGN KEY (project_id) REFERENCES public.projects(id);


--
-- Name: baselines baselines_project_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: testdock
--

ALTER TABLE ONLY public.baselines
    ADD CONSTRAINT baselines_project_id_fkey FOREIGN KEY (project_id) REFERENCES public.projects(id);


--
-- Name: case_results case_results_project_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: testdock
--

ALTER TABLE ONLY public.case_results
    ADD CONSTRAINT case_results_project_id_fkey FOREIGN KEY (project_id) REFERENCES public.projects(id);


--
-- Name: debug_sessions debug_sessions_project_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: testdock
--

ALTER TABLE ONLY public.debug_sessions
    ADD CONSTRAINT debug_sessions_project_id_fkey FOREIGN KEY (project_id) REFERENCES public.projects(id);


--
-- Name: device_checks device_checks_project_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: testdock
--

ALTER TABLE ONLY public.device_checks
    ADD CONSTRAINT device_checks_project_id_fkey FOREIGN KEY (project_id) REFERENCES public.projects(id);


--
-- Name: environments environments_project_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: testdock
--

ALTER TABLE ONLY public.environments
    ADD CONSTRAINT environments_project_id_fkey FOREIGN KEY (project_id) REFERENCES public.projects(id);


--
-- Name: execution_nodes execution_nodes_project_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: testdock
--

ALTER TABLE ONLY public.execution_nodes
    ADD CONSTRAINT execution_nodes_project_id_fkey FOREIGN KEY (project_id) REFERENCES public.projects(id);


--
-- Name: execution_resources execution_resources_project_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: testdock
--

ALTER TABLE ONLY public.execution_resources
    ADD CONSTRAINT execution_resources_project_id_fkey FOREIGN KEY (project_id) REFERENCES public.projects(id);


--
-- Name: app_builds fk_app_builds_project_id_application_id_applications; Type: FK CONSTRAINT; Schema: public; Owner: testdock
--

ALTER TABLE ONLY public.app_builds
    ADD CONSTRAINT fk_app_builds_project_id_application_id_applications FOREIGN KEY (project_id, application_id) REFERENCES public.applications(project_id, id);


--
-- Name: artifacts fk_artifacts_project_id_run_id_component_id_run_components; Type: FK CONSTRAINT; Schema: public; Owner: testdock
--

ALTER TABLE ONLY public.artifacts
    ADD CONSTRAINT fk_artifacts_project_id_run_id_component_id_run_components FOREIGN KEY (project_id, run_id, component_id) REFERENCES public.run_components(project_id, run_id, id);


--
-- Name: artifacts fk_artifacts_project_id_run_id_test_runs; Type: FK CONSTRAINT; Schema: public; Owner: testdock
--

ALTER TABLE ONLY public.artifacts
    ADD CONSTRAINT fk_artifacts_project_id_run_id_test_runs FOREIGN KEY (project_id, run_id) REFERENCES public.test_runs(project_id, id);


--
-- Name: baselines fk_baselines_project_id_application_id_applications; Type: FK CONSTRAINT; Schema: public; Owner: testdock
--

ALTER TABLE ONLY public.baselines
    ADD CONSTRAINT fk_baselines_project_id_application_id_applications FOREIGN KEY (project_id, application_id) REFERENCES public.applications(project_id, id);


--
-- Name: baselines fk_baselines_project_id_application_id_suite_version_i_bf7806e1; Type: FK CONSTRAINT; Schema: public; Owner: testdock
--

ALTER TABLE ONLY public.baselines
    ADD CONSTRAINT fk_baselines_project_id_application_id_suite_version_i_bf7806e1 FOREIGN KEY (project_id, application_id, suite_version_id) REFERENCES public.suite_versions(project_id, application_id, id);


--
-- Name: baselines fk_baselines_project_id_environment_id_environments; Type: FK CONSTRAINT; Schema: public; Owner: testdock
--

ALTER TABLE ONLY public.baselines
    ADD CONSTRAINT fk_baselines_project_id_environment_id_environments FOREIGN KEY (project_id, environment_id) REFERENCES public.environments(project_id, id);


--
-- Name: baselines fk_baselines_project_id_profile_id_resource_profiles; Type: FK CONSTRAINT; Schema: public; Owner: testdock
--

ALTER TABLE ONLY public.baselines
    ADD CONSTRAINT fk_baselines_project_id_profile_id_resource_profiles FOREIGN KEY (project_id, profile_id) REFERENCES public.resource_profiles(project_id, id);


--
-- Name: baselines fk_baselines_project_id_source_component_id_run_components; Type: FK CONSTRAINT; Schema: public; Owner: testdock
--

ALTER TABLE ONLY public.baselines
    ADD CONSTRAINT fk_baselines_project_id_source_component_id_run_components FOREIGN KEY (project_id, source_component_id) REFERENCES public.run_components(project_id, id);


--
-- Name: case_results fk_case_results_project_id_component_id_run_components; Type: FK CONSTRAINT; Schema: public; Owner: testdock
--

ALTER TABLE ONLY public.case_results
    ADD CONSTRAINT fk_case_results_project_id_component_id_run_components FOREIGN KEY (project_id, component_id) REFERENCES public.run_components(project_id, id);


--
-- Name: debug_sessions fk_debug_sessions_project_id_resource_id_execution_resources; Type: FK CONSTRAINT; Schema: public; Owner: testdock
--

ALTER TABLE ONLY public.debug_sessions
    ADD CONSTRAINT fk_debug_sessions_project_id_resource_id_execution_resources FOREIGN KEY (project_id, resource_id) REFERENCES public.execution_resources(project_id, id);


--
-- Name: device_checks fk_device_checks_project_id_resource_id_execution_resources; Type: FK CONSTRAINT; Schema: public; Owner: testdock
--

ALTER TABLE ONLY public.device_checks
    ADD CONSTRAINT fk_device_checks_project_id_resource_id_execution_resources FOREIGN KEY (project_id, resource_id) REFERENCES public.execution_resources(project_id, id);


--
-- Name: execution_resources fk_execution_resources_project_id_node_id_execution_nodes; Type: FK CONSTRAINT; Schema: public; Owner: testdock
--

ALTER TABLE ONLY public.execution_resources
    ADD CONSTRAINT fk_execution_resources_project_id_node_id_execution_nodes FOREIGN KEY (project_id, node_id) REFERENCES public.execution_nodes(project_id, id);


--
-- Name: execution_resources fk_execution_resources_project_id_profile_id_platform_2498e5db; Type: FK CONSTRAINT; Schema: public; Owner: testdock
--

ALTER TABLE ONLY public.execution_resources
    ADD CONSTRAINT fk_execution_resources_project_id_profile_id_platform_2498e5db FOREIGN KEY (project_id, profile_id, platform) REFERENCES public.resource_profiles(project_id, id, platform);


--
-- Name: gate_evaluations fk_gate_evaluations_project_id_baseline_id_baselines; Type: FK CONSTRAINT; Schema: public; Owner: testdock
--

ALTER TABLE ONLY public.gate_evaluations
    ADD CONSTRAINT fk_gate_evaluations_project_id_baseline_id_baselines FOREIGN KEY (project_id, baseline_id) REFERENCES public.baselines(project_id, id);


--
-- Name: gate_evaluations fk_gate_evaluations_project_id_component_id_run_components; Type: FK CONSTRAINT; Schema: public; Owner: testdock
--

ALTER TABLE ONLY public.gate_evaluations
    ADD CONSTRAINT fk_gate_evaluations_project_id_component_id_run_components FOREIGN KEY (project_id, component_id) REFERENCES public.run_components(project_id, id);


--
-- Name: gate_evaluations fk_gate_evaluations_project_id_policy_id_gate_policies; Type: FK CONSTRAINT; Schema: public; Owner: testdock
--

ALTER TABLE ONLY public.gate_evaluations
    ADD CONSTRAINT fk_gate_evaluations_project_id_policy_id_gate_policies FOREIGN KEY (project_id, policy_id) REFERENCES public.gate_policies(project_id, id);


--
-- Name: gate_policies fk_gate_policies_project_id_application_id_applications; Type: FK CONSTRAINT; Schema: public; Owner: testdock
--

ALTER TABLE ONLY public.gate_policies
    ADD CONSTRAINT fk_gate_policies_project_id_application_id_applications FOREIGN KEY (project_id, application_id) REFERENCES public.applications(project_id, id);


--
-- Name: metric_summaries fk_metric_summaries_project_id_component_id_run_components; Type: FK CONSTRAINT; Schema: public; Owner: testdock
--

ALTER TABLE ONLY public.metric_summaries
    ADD CONSTRAINT fk_metric_summaries_project_id_component_id_run_components FOREIGN KEY (project_id, component_id) REFERENCES public.run_components(project_id, id);


--
-- Name: resource_leases fk_resource_leases_project_check_id_device_checks; Type: FK CONSTRAINT; Schema: public; Owner: testdock
--

ALTER TABLE ONLY public.resource_leases
    ADD CONSTRAINT fk_resource_leases_project_check_id_device_checks FOREIGN KEY (project_id, check_id, resource_id) REFERENCES public.device_checks(project_id, id, resource_id);


--
-- Name: resource_leases fk_resource_leases_project_id_debug_session_id_resourc_3b7f9216; Type: FK CONSTRAINT; Schema: public; Owner: testdock
--

ALTER TABLE ONLY public.resource_leases
    ADD CONSTRAINT fk_resource_leases_project_id_debug_session_id_resourc_3b7f9216 FOREIGN KEY (project_id, debug_session_id, resource_id) REFERENCES public.debug_sessions(project_id, id, resource_id);


--
-- Name: resource_leases fk_resource_leases_project_id_run_id_resource_id_test_runs; Type: FK CONSTRAINT; Schema: public; Owner: testdock
--

ALTER TABLE ONLY public.resource_leases
    ADD CONSTRAINT fk_resource_leases_project_id_run_id_resource_id_test_runs FOREIGN KEY (project_id, run_id, resource_id) REFERENCES public.test_runs(project_id, id, resource_id);


--
-- Name: run_components fk_run_components_project_id_run_id_test_runs; Type: FK CONSTRAINT; Schema: public; Owner: testdock
--

ALTER TABLE ONLY public.run_components
    ADD CONSTRAINT fk_run_components_project_id_run_id_test_runs FOREIGN KEY (project_id, run_id) REFERENCES public.test_runs(project_id, id);


--
-- Name: run_events fk_run_events_project_id_run_id_test_runs; Type: FK CONSTRAINT; Schema: public; Owner: testdock
--

ALTER TABLE ONLY public.run_events
    ADD CONSTRAINT fk_run_events_project_id_run_id_test_runs FOREIGN KEY (project_id, run_id) REFERENCES public.test_runs(project_id, id);


--
-- Name: suite_versions fk_suite_versions_project_id_application_id_suite_id_t_73de23ad; Type: FK CONSTRAINT; Schema: public; Owner: testdock
--

ALTER TABLE ONLY public.suite_versions
    ADD CONSTRAINT fk_suite_versions_project_id_application_id_suite_id_t_73de23ad FOREIGN KEY (project_id, application_id, suite_id) REFERENCES public.test_suites(project_id, application_id, id);


--
-- Name: task_request_keys fk_task_request_keys_project_id_task_id_test_tasks; Type: FK CONSTRAINT; Schema: public; Owner: testdock
--

ALTER TABLE ONLY public.task_request_keys
    ADD CONSTRAINT fk_task_request_keys_project_id_task_id_test_tasks FOREIGN KEY (project_id, task_id) REFERENCES public.test_tasks(project_id, id);


--
-- Name: task_revisions fk_task_revisions_project_id_application_id_build_id_app_builds; Type: FK CONSTRAINT; Schema: public; Owner: testdock
--

ALTER TABLE ONLY public.task_revisions
    ADD CONSTRAINT fk_task_revisions_project_id_application_id_build_id_app_builds FOREIGN KEY (project_id, application_id, build_id) REFERENCES public.app_builds(project_id, application_id, id);


--
-- Name: task_revisions fk_task_revisions_project_id_application_id_suite_vers_7280bd99; Type: FK CONSTRAINT; Schema: public; Owner: testdock
--

ALTER TABLE ONLY public.task_revisions
    ADD CONSTRAINT fk_task_revisions_project_id_application_id_suite_vers_7280bd99 FOREIGN KEY (project_id, application_id, suite_version_id) REFERENCES public.suite_versions(project_id, application_id, id);


--
-- Name: task_revisions fk_task_revisions_project_id_application_id_task_id_test_tasks; Type: FK CONSTRAINT; Schema: public; Owner: testdock
--

ALTER TABLE ONLY public.task_revisions
    ADD CONSTRAINT fk_task_revisions_project_id_application_id_task_id_test_tasks FOREIGN KEY (project_id, application_id, task_id) REFERENCES public.test_tasks(project_id, application_id, id);


--
-- Name: task_revisions fk_task_revisions_project_id_environment_id_environments; Type: FK CONSTRAINT; Schema: public; Owner: testdock
--

ALTER TABLE ONLY public.task_revisions
    ADD CONSTRAINT fk_task_revisions_project_id_environment_id_environments FOREIGN KEY (project_id, environment_id) REFERENCES public.environments(project_id, id);


--
-- Name: test_runs fk_test_runs_project_id_application_id_parent_run_id_test_runs; Type: FK CONSTRAINT; Schema: public; Owner: testdock
--

ALTER TABLE ONLY public.test_runs
    ADD CONSTRAINT fk_test_runs_project_id_application_id_parent_run_id_test_runs FOREIGN KEY (project_id, application_id, parent_run_id) REFERENCES public.test_runs(project_id, application_id, id);


--
-- Name: test_runs fk_test_runs_project_id_application_id_platform_applications; Type: FK CONSTRAINT; Schema: public; Owner: testdock
--

ALTER TABLE ONLY public.test_runs
    ADD CONSTRAINT fk_test_runs_project_id_application_id_platform_applications FOREIGN KEY (project_id, application_id, platform) REFERENCES public.applications(project_id, id, platform);


--
-- Name: test_runs fk_test_runs_project_id_application_id_revision_id_tas_e43fae07; Type: FK CONSTRAINT; Schema: public; Owner: testdock
--

ALTER TABLE ONLY public.test_runs
    ADD CONSTRAINT fk_test_runs_project_id_application_id_revision_id_tas_e43fae07 FOREIGN KEY (project_id, application_id, revision_id) REFERENCES public.task_revisions(project_id, application_id, id);


--
-- Name: test_runs fk_test_runs_project_id_profile_id_platform_resource_profiles; Type: FK CONSTRAINT; Schema: public; Owner: testdock
--

ALTER TABLE ONLY public.test_runs
    ADD CONSTRAINT fk_test_runs_project_id_profile_id_platform_resource_profiles FOREIGN KEY (project_id, profile_id, platform) REFERENCES public.resource_profiles(project_id, id, platform);


--
-- Name: test_runs fk_test_runs_project_id_resource_id_platform_execution_be04ac1d; Type: FK CONSTRAINT; Schema: public; Owner: testdock
--

ALTER TABLE ONLY public.test_runs
    ADD CONSTRAINT fk_test_runs_project_id_resource_id_platform_execution_be04ac1d FOREIGN KEY (project_id, resource_id, platform) REFERENCES public.execution_resources(project_id, id, platform);


--
-- Name: test_suites fk_test_suites_project_id_application_id_applications; Type: FK CONSTRAINT; Schema: public; Owner: testdock
--

ALTER TABLE ONLY public.test_suites
    ADD CONSTRAINT fk_test_suites_project_id_application_id_applications FOREIGN KEY (project_id, application_id) REFERENCES public.applications(project_id, id);


--
-- Name: test_tasks fk_test_tasks_project_id_application_id_applications; Type: FK CONSTRAINT; Schema: public; Owner: testdock
--

ALTER TABLE ONLY public.test_tasks
    ADD CONSTRAINT fk_test_tasks_project_id_application_id_applications FOREIGN KEY (project_id, application_id) REFERENCES public.applications(project_id, id);


--
-- Name: gate_evaluations gate_evaluations_project_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: testdock
--

ALTER TABLE ONLY public.gate_evaluations
    ADD CONSTRAINT gate_evaluations_project_id_fkey FOREIGN KEY (project_id) REFERENCES public.projects(id);


--
-- Name: gate_policies gate_policies_project_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: testdock
--

ALTER TABLE ONLY public.gate_policies
    ADD CONSTRAINT gate_policies_project_id_fkey FOREIGN KEY (project_id) REFERENCES public.projects(id);


--
-- Name: metric_summaries metric_summaries_project_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: testdock
--

ALTER TABLE ONLY public.metric_summaries
    ADD CONSTRAINT metric_summaries_project_id_fkey FOREIGN KEY (project_id) REFERENCES public.projects(id);


--
-- Name: project_members project_members_project_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: testdock
--

ALTER TABLE ONLY public.project_members
    ADD CONSTRAINT project_members_project_id_fkey FOREIGN KEY (project_id) REFERENCES public.projects(id);


--
-- Name: resource_leases resource_leases_project_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: testdock
--

ALTER TABLE ONLY public.resource_leases
    ADD CONSTRAINT resource_leases_project_id_fkey FOREIGN KEY (project_id) REFERENCES public.projects(id);


--
-- Name: resource_profiles resource_profiles_project_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: testdock
--

ALTER TABLE ONLY public.resource_profiles
    ADD CONSTRAINT resource_profiles_project_id_fkey FOREIGN KEY (project_id) REFERENCES public.projects(id);


--
-- Name: run_components run_components_project_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: testdock
--

ALTER TABLE ONLY public.run_components
    ADD CONSTRAINT run_components_project_id_fkey FOREIGN KEY (project_id) REFERENCES public.projects(id);


--
-- Name: run_events run_events_project_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: testdock
--

ALTER TABLE ONLY public.run_events
    ADD CONSTRAINT run_events_project_id_fkey FOREIGN KEY (project_id) REFERENCES public.projects(id);


--
-- Name: suite_versions suite_versions_project_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: testdock
--

ALTER TABLE ONLY public.suite_versions
    ADD CONSTRAINT suite_versions_project_id_fkey FOREIGN KEY (project_id) REFERENCES public.projects(id);


--
-- Name: task_request_keys task_request_keys_project_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: testdock
--

ALTER TABLE ONLY public.task_request_keys
    ADD CONSTRAINT task_request_keys_project_id_fkey FOREIGN KEY (project_id) REFERENCES public.projects(id);


--
-- Name: task_revisions task_revisions_project_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: testdock
--

ALTER TABLE ONLY public.task_revisions
    ADD CONSTRAINT task_revisions_project_id_fkey FOREIGN KEY (project_id) REFERENCES public.projects(id);


--
-- Name: test_runs test_runs_project_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: testdock
--

ALTER TABLE ONLY public.test_runs
    ADD CONSTRAINT test_runs_project_id_fkey FOREIGN KEY (project_id) REFERENCES public.projects(id);


--
-- Name: test_suites test_suites_project_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: testdock
--

ALTER TABLE ONLY public.test_suites
    ADD CONSTRAINT test_suites_project_id_fkey FOREIGN KEY (project_id) REFERENCES public.projects(id);


--
-- Name: test_tasks test_tasks_project_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: testdock
--

ALTER TABLE ONLY public.test_tasks
    ADD CONSTRAINT test_tasks_project_id_fkey FOREIGN KEY (project_id) REFERENCES public.projects(id);


--
-- PostgreSQL database dump complete
--

\unrestrict kVBbsDfRvhbfddaoNAwIE4O4EUr2wECL2OerjUWFPZ1nkjn32ozCDWssgG47Ty0

