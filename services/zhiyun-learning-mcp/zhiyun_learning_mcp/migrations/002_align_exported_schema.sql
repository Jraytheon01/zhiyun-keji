-- Additive compatibility migration for the MySQL 5.7 schema exported on 2026-08-11.
-- No column/table is dropped and no production row is copied into the repository.

CREATE TABLE IF NOT EXISTS recordings (
  recording_id VARCHAR(64) PRIMARY KEY,
  user_id BIGINT NULL,
  uploaded_at TIMESTAMP NULL,
  speakers INT NULL,
  has_audio TINYINT(1) NULL,
  has_transcript TINYINT(1) NULL,
  has_summary TINYINT(1) NULL,
  ingestion_status VARCHAR(64) NULL,
  ingested_at TIMESTAMP NULL,
  chunk_count INT NULL,
  fact_count INT NULL,
  todo_count INT NULL,
  embed_model VARCHAR(128) NULL,
  extract_model VARCHAR(128) NULL,
  INDEX idx_recordings_user (user_id)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

SET @ddl = IF((SELECT COUNT(*) FROM information_schema.columns WHERE table_schema=DATABASE() AND table_name='chunks' AND column_name='chunk_index')=0, 'ALTER TABLE chunks ADD COLUMN chunk_index INT NULL COMMENT ''分块索引'' AFTER user_id', 'SELECT 1');
PREPARE ma_stmt FROM @ddl;
EXECUTE ma_stmt;
DEALLOCATE PREPARE ma_stmt;
SET @ddl = IF((SELECT COUNT(*) FROM information_schema.columns WHERE table_schema=DATABASE() AND table_name='chunks' AND column_name='kind')=0, 'ALTER TABLE chunks ADD COLUMN kind VARCHAR(64) NOT NULL DEFAULT ''transcript'' AFTER created_at', 'SELECT 1');
PREPARE ma_stmt FROM @ddl;
EXECUTE ma_stmt;
DEALLOCATE PREPARE ma_stmt;
SET @ddl = IF((SELECT COUNT(*) FROM information_schema.columns WHERE table_schema=DATABASE() AND table_name='chunks' AND column_name='speaker')=0, 'ALTER TABLE chunks ADD COLUMN speaker VARCHAR(255) NULL AFTER kind', 'SELECT 1');
PREPARE ma_stmt FROM @ddl;
EXECUTE ma_stmt;
DEALLOCATE PREPARE ma_stmt;
SET @ddl = IF((SELECT COUNT(*) FROM information_schema.columns WHERE table_schema=DATABASE() AND table_name='chunks' AND column_name='section')=0, 'ALTER TABLE chunks ADD COLUMN section VARCHAR(255) NULL AFTER speaker', 'SELECT 1');
PREPARE ma_stmt FROM @ddl;
EXECUTE ma_stmt;
DEALLOCATE PREPARE ma_stmt;
SET @ddl = IF((SELECT COUNT(*) FROM information_schema.columns WHERE table_schema=DATABASE() AND table_name='chunks' AND column_name='token_len')=0, 'ALTER TABLE chunks ADD COLUMN token_len INT NULL AFTER section', 'SELECT 1');
PREPARE ma_stmt FROM @ddl;
EXECUTE ma_stmt;
DEALLOCATE PREPARE ma_stmt;
SET @ddl = IF((SELECT COUNT(*) FROM information_schema.columns WHERE table_schema=DATABASE() AND table_name='chunks' AND column_name='user_id')=0, 'ALTER TABLE chunks ADD COLUMN user_id BIGINT NULL', 'SELECT 1');
PREPARE ma_stmt FROM @ddl;
EXECUTE ma_stmt;
DEALLOCATE PREPARE ma_stmt;

SET @ddl = IF((SELECT COUNT(*) FROM information_schema.columns WHERE table_schema=DATABASE() AND table_name='facts' AND column_name='meeting_id')=0, 'ALTER TABLE facts ADD COLUMN meeting_id VARCHAR(64) NULL COMMENT ''会议 ID'' AFTER user_id', 'SELECT 1');
PREPARE ma_stmt FROM @ddl;
EXECUTE ma_stmt;
DEALLOCATE PREPARE ma_stmt;
SET @ddl = IF((SELECT COUNT(*) FROM information_schema.columns WHERE table_schema=DATABASE() AND table_name='facts' AND column_name='fact_text')=0, 'ALTER TABLE facts ADD COLUMN fact_text TEXT NULL COMMENT ''事实内容'' AFTER meeting_id', 'SELECT 1');
PREPARE ma_stmt FROM @ddl;
EXECUTE ma_stmt;
DEALLOCATE PREPARE ma_stmt;
SET @ddl = IF((SELECT COUNT(*) FROM information_schema.columns WHERE table_schema=DATABASE() AND table_name='facts' AND column_name='fact_type')=0, 'ALTER TABLE facts ADD COLUMN fact_type VARCHAR(50) NULL DEFAULT ''general'' AFTER fact_text', 'SELECT 1');
PREPARE ma_stmt FROM @ddl;
EXECUTE ma_stmt;
DEALLOCATE PREPARE ma_stmt;
SET @ddl = IF((SELECT COUNT(*) FROM information_schema.columns WHERE table_schema=DATABASE() AND table_name='facts' AND column_name='confidence')=0, 'ALTER TABLE facts ADD COLUMN confidence DECIMAL(3,2) NULL DEFAULT 1.00 AFTER fact_type', 'SELECT 1');
PREPARE ma_stmt FROM @ddl;
EXECUTE ma_stmt;
DEALLOCATE PREPARE ma_stmt;
SET @ddl = IF((SELECT COUNT(*) FROM information_schema.columns WHERE table_schema=DATABASE() AND table_name='facts' AND column_name='source_chunk_id')=0, 'ALTER TABLE facts ADD COLUMN source_chunk_id BIGINT NULL AFTER confidence', 'SELECT 1');
PREPARE ma_stmt FROM @ddl;
EXECUTE ma_stmt;
DEALLOCATE PREPARE ma_stmt;
SET @ddl = IF((SELECT COUNT(*) FROM information_schema.columns WHERE table_schema=DATABASE() AND table_name='facts' AND column_name='subject')=0, 'ALTER TABLE facts ADD COLUMN subject VARCHAR(512) NULL AFTER source_chunk_id', 'SELECT 1');
PREPARE ma_stmt FROM @ddl;
EXECUTE ma_stmt;
DEALLOCATE PREPARE ma_stmt;
SET @ddl = IF((SELECT COUNT(*) FROM information_schema.columns WHERE table_schema=DATABASE() AND table_name='facts' AND column_name='detail')=0, 'ALTER TABLE facts ADD COLUMN detail JSON NULL AFTER subject', 'SELECT 1');
PREPARE ma_stmt FROM @ddl;
EXECUTE ma_stmt;
DEALLOCATE PREPARE ma_stmt;
SET @ddl = IF((SELECT COUNT(*) FROM information_schema.columns WHERE table_schema=DATABASE() AND table_name='facts' AND column_name='date')=0, 'ALTER TABLE facts ADD COLUMN date DATE NULL AFTER detail', 'SELECT 1');
PREPARE ma_stmt FROM @ddl;
EXECUTE ma_stmt;
DEALLOCATE PREPARE ma_stmt;
SET @ddl = IF((SELECT COUNT(*) FROM information_schema.columns WHERE table_schema=DATABASE() AND table_name='facts' AND column_name='status')=0, 'ALTER TABLE facts ADD COLUMN status VARCHAR(32) NULL DEFAULT ''active'' AFTER date', 'SELECT 1');
PREPARE ma_stmt FROM @ddl;
EXECUTE ma_stmt;
DEALLOCATE PREPARE ma_stmt;
SET @ddl = IF((SELECT COUNT(*) FROM information_schema.columns WHERE table_schema=DATABASE() AND table_name='facts' AND column_name='superseded_by')=0, 'ALTER TABLE facts ADD COLUMN superseded_by BIGINT NULL AFTER status', 'SELECT 1');
PREPARE ma_stmt FROM @ddl;
EXECUTE ma_stmt;
DEALLOCATE PREPARE ma_stmt;
SET @ddl = IF((SELECT COUNT(*) FROM information_schema.columns WHERE table_schema=DATABASE() AND table_name='facts' AND column_name='user_id')=0, 'ALTER TABLE facts ADD COLUMN user_id BIGINT NULL', 'SELECT 1');
PREPARE ma_stmt FROM @ddl;
EXECUTE ma_stmt;
DEALLOCATE PREPARE ma_stmt;

SET @ddl = IF((SELECT COUNT(*) FROM information_schema.columns WHERE table_schema=DATABASE() AND table_name='facts' AND column_name='kind')=1, 'UPDATE facts SET fact_type=COALESCE(fact_type, kind), fact_text=COALESCE(fact_text, CAST(detail AS CHAR)) WHERE fact_type IS NULL OR fact_text IS NULL', 'SELECT 1');
PREPARE ma_stmt FROM @ddl;
EXECUTE ma_stmt;
DEALLOCATE PREPARE ma_stmt;

SET @ddl = IF((SELECT COUNT(*) FROM information_schema.columns WHERE table_schema=DATABASE() AND table_name='mcp_api_keys' AND column_name='phone')=0, 'ALTER TABLE mcp_api_keys ADD COLUMN phone VARCHAR(20) NULL AFTER key_hash', 'SELECT 1');
PREPARE ma_stmt FROM @ddl;
EXECUTE ma_stmt;
DEALLOCATE PREPARE ma_stmt;

SET @ddl = IF((SELECT COUNT(*) FROM information_schema.columns WHERE table_schema=DATABASE() AND table_name='todos' AND column_name='user_id')=0, 'ALTER TABLE todos ADD COLUMN user_id BIGINT NULL', 'SELECT 1');
PREPARE ma_stmt FROM @ddl;
EXECUTE ma_stmt;
DEALLOCATE PREPARE ma_stmt;
SET @ddl = IF((SELECT COUNT(*) FROM information_schema.columns WHERE table_schema=DATABASE() AND table_name='todos' AND column_name='status')=0, 'ALTER TABLE todos ADD COLUMN status VARCHAR(20) NULL DEFAULT ''open''', 'SELECT 1');
PREPARE ma_stmt FROM @ddl;
EXECUTE ma_stmt;
DEALLOCATE PREPARE ma_stmt;
SET @ddl = IF((SELECT COUNT(*) FROM information_schema.columns WHERE table_schema=DATABASE() AND table_name='todos' AND column_name='due')=0, 'ALTER TABLE todos ADD COLUMN due DATETIME NULL', 'SELECT 1');
PREPARE ma_stmt FROM @ddl;
EXECUTE ma_stmt;
DEALLOCATE PREPARE ma_stmt;

SET @ddl = IF((SELECT COUNT(*) FROM information_schema.statistics WHERE table_schema=DATABASE() AND table_name='chunks' AND index_name='idx_chunks_tenant_recording')=0, 'ALTER TABLE chunks ADD INDEX idx_chunks_tenant_recording (user_id, recording_id)', 'SELECT 1');
PREPARE ma_stmt FROM @ddl;
EXECUTE ma_stmt;
DEALLOCATE PREPARE ma_stmt;
SET @ddl = IF((SELECT COUNT(*) FROM information_schema.statistics WHERE table_schema=DATABASE() AND table_name='facts' AND index_name='idx_facts_tenant_status')=0, 'ALTER TABLE facts ADD INDEX idx_facts_tenant_status (user_id, status)', 'SELECT 1');
PREPARE ma_stmt FROM @ddl;
EXECUTE ma_stmt;
DEALLOCATE PREPARE ma_stmt;
SET @ddl = IF((SELECT COUNT(*) FROM information_schema.statistics WHERE table_schema=DATABASE() AND table_name='todos' AND index_name='idx_todos_tenant_status_due')=0, 'ALTER TABLE todos ADD INDEX idx_todos_tenant_status_due (user_id, status, due)', 'SELECT 1');
PREPARE ma_stmt FROM @ddl;
EXECUTE ma_stmt;
DEALLOCATE PREPARE ma_stmt;
