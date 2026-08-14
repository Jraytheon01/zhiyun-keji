-- Zhiyun Learning MCP schema (MySQL 5.7+), stored in zhiyun_learning.
-- 多租户：所有表带 phone；recording_id = str(user_meeting_info.id)。
-- 字段以 2026-08-11 导出的真实 chunks/facts/todos/mcp_api_keys 为基线，
-- 只追加 MCP 语义检索/事实演进所需字段。生产已有表请运行 migrations，不要重建。

-- 教育课程源数据表。字段名沿用录音底座以兼容既有 ingest 代码，但本服务只在
-- 独立的 zhiyun_learning 数据库中读写，不会访问会议业务数据库。
CREATE TABLE IF NOT EXISTS user_meeting_info (
  id                  BIGINT NOT NULL,
  meeting_name        VARCHAR(255),
  user_id             BIGINT,
  phone               VARCHAR(32),
  create_time         DATETIME,
  update_time         DATETIME,
  record_url          VARCHAR(1024),
  during              BIGINT,
  title               VARCHAR(255),
  content             LONGTEXT,
  abstract_text       TEXT,
  abstract_content    TEXT,
  todo                TEXT,
  file_type           VARCHAR(5),
  label_id            INT,
  is_collect          VARCHAR(1) DEFAULT '0',
  file_path           VARCHAR(255),
  status              VARCHAR(1),
  short_flag          VARCHAR(2),
  is_guide_file       VARCHAR(2),
  del_flag            VARCHAR(1) DEFAULT '0',
  oper_source         VARCHAR(1),
  package_id          VARCHAR(10),
  package_name        VARCHAR(20),
  doc_path            VARCHAR(255),
  doc_url             VARCHAR(1024),
  asr_path            VARCHAR(255),
  asr_url             VARCHAR(1024),
  rebuild_status      VARCHAR(1) DEFAULT '0',
  core_topics_id      BIGINT,
  qa_summary_id       BIGINT,
  speakers_info_id    BIGINT,
  detail_summary_id   BIGINT,
  current_template_id VARCHAR(5),
  flow_content        TEXT,
  before_meeting_abstract TEXT,
  rc_file_type        TINYTEXT,
  device_id           VARCHAR(255),
  participants        VARCHAR(500),
  uuid                VARCHAR(50),
  rc_call_back_url    VARCHAR(128),
  data_json           LONGTEXT,
  PRIMARY KEY (id),
  INDEX idx_course_owner_created (phone, create_time),
  INDEX idx_course_source_compat (create_time, user_id, package_id, file_type)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

CREATE TABLE IF NOT EXISTS user_meeting_content (
  id          BIGINT NOT NULL AUTO_INCREMENT,
  begin_time  BIGINT,
  end_time    BIGINT,
  speaker     VARCHAR(255),
  content     MEDIUMTEXT,
  meet_id     BIGINT,
  create_time DATETIME,
  code        VARCHAR(2),
  type        VARCHAR(1),
  PRIMARY KEY (id),
  INDEX idx_course_content (meet_id)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

CREATE TABLE IF NOT EXISTS recordings (
  recording_id     VARCHAR(64) PRIMARY KEY,
  phone            VARCHAR(32)  NULL,
  uploaded_at      TIMESTAMP NULL,
  speakers         INT,
  has_audio        TINYINT(1),
  has_transcript   TINYINT(1),
  has_summary      TINYINT(1),
  ingestion_status VARCHAR(64),
  ingested_at      TIMESTAMP NULL,
  chunk_count      INT,
  fact_count       INT,
  todo_count       INT,
  embed_model      VARCHAR(128),
  extract_model    VARCHAR(128),
  INDEX idx_recordings_phone (phone)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

CREATE TABLE IF NOT EXISTS chunks (
  id           BIGINT NOT NULL AUTO_INCREMENT,
  recording_id VARCHAR(64) NOT NULL COMMENT '录音 ID',
  phone        VARCHAR(32) NULL COMMENT '用户手机号',
  chunk_index  INT NULL COMMENT '分块索引',
  text         MEDIUMTEXT NULL COMMENT '分块文本内容',
  embedding    BLOB NULL COMMENT '兼容字段；向量正文存 Milvus',
  created_at   DATETIME NULL DEFAULT CURRENT_TIMESTAMP,
  kind         VARCHAR(64) NOT NULL DEFAULT 'transcript',
  speaker      VARCHAR(255),
  section      VARCHAR(255),
  token_len    INT,
  PRIMARY KEY (id),
  INDEX idx_recording_id (recording_id),
  INDEX idx_chunks_phone (phone),
  INDEX idx_chunks_tenant_recording_phone (phone, recording_id),
  INDEX idx_chunks_recording_kind (recording_id, kind)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_general_ci;

CREATE TABLE IF NOT EXISTS facts (
  id              BIGINT NOT NULL AUTO_INCREMENT,
  recording_id    VARCHAR(64) NULL COMMENT '录音 ID',
  phone           VARCHAR(32) NOT NULL COMMENT '用户手机号',
  meeting_id      VARCHAR(64) NULL COMMENT '会议 ID（与 recording_id 相同）',
  fact_text       TEXT NOT NULL COMMENT '事实可读文本',
  fact_type       VARCHAR(50) NULL DEFAULT 'general',
  kind            VARCHAR(64) NULL COMMENT 'MCP 兼容类型，与 fact_type 同值',
  confidence      DECIMAL(3,2) NULL DEFAULT 1.00,
  source_chunk_id BIGINT NULL,
  created_at      DATETIME NULL DEFAULT CURRENT_TIMESTAMP,
  subject         VARCHAR(512) NOT NULL,
  detail          JSON NOT NULL,
  date          DATE,
  status        VARCHAR(32)  DEFAULT 'active',
  superseded_by BIGINT,
  PRIMARY KEY (id),
  INDEX idx_recording_id (recording_id),
  INDEX idx_facts_phone (phone),
  INDEX idx_meeting_id (meeting_id),
  INDEX idx_fact_type (fact_type),
  INDEX idx_facts_type_subject (fact_type, subject),
  INDEX idx_facts_tenant_status_phone (phone, status)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_general_ci;

CREATE TABLE IF NOT EXISTS todos (
  id           BIGINT NOT NULL AUTO_INCREMENT,
  recording_id VARCHAR(64) NULL,
  phone        VARCHAR(32) NOT NULL,
  task         VARCHAR(500) NOT NULL,
  owner        VARCHAR(100) NULL,
  due          DATETIME NULL,
  status       VARCHAR(20) NULL DEFAULT 'open',
  created_at   DATETIME NULL DEFAULT CURRENT_TIMESTAMP,
  completed_at DATETIME NULL,
  PRIMARY KEY (id),
  INDEX idx_recording_id (recording_id),
  INDEX idx_todos_phone (phone),
  INDEX idx_status (status),
  INDEX idx_todos_tenant_status_due_phone (phone, status, due)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_general_ci;

-- API key 鉴权：1 key <-> 1 phone。只存 sha256(key)，明文不落库。
CREATE TABLE IF NOT EXISTS mcp_api_keys (
  id           BIGINT NOT NULL AUTO_INCREMENT,
  key_hash     VARCHAR(64) NOT NULL,
  phone        VARCHAR(20) NOT NULL,
  name         VARCHAR(100) NULL,
  active       TINYINT(1) NULL DEFAULT 1,
  last_used_at DATETIME NULL,
  created_at   DATETIME NULL DEFAULT CURRENT_TIMESTAMP,
  PRIMARY KEY (id),
  UNIQUE INDEX uk_key_hash (key_hash),
  INDEX idx_phone (phone)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_general_ci;
