-- Complete the additive runtime contract for partially existing test databases.
-- This migration never drops a table, column, index, or application row.

SET @ddl = IF((SELECT COUNT(*) FROM information_schema.columns WHERE table_schema=DATABASE() AND table_name='recordings' AND column_name='user_id')=0, 'ALTER TABLE recordings ADD COLUMN user_id BIGINT NULL AFTER recording_id', 'SELECT 1');
PREPARE ma_stmt FROM @ddl;
EXECUTE ma_stmt;
DEALLOCATE PREPARE ma_stmt;
SET @ddl = IF((SELECT COUNT(*) FROM information_schema.columns WHERE table_schema=DATABASE() AND table_name='recordings' AND column_name='ingestion_status')=0, 'ALTER TABLE recordings ADD COLUMN ingestion_status VARCHAR(64) NULL', 'SELECT 1');
PREPARE ma_stmt FROM @ddl;
EXECUTE ma_stmt;
DEALLOCATE PREPARE ma_stmt;
SET @ddl = IF((SELECT COUNT(*) FROM information_schema.columns WHERE table_schema=DATABASE() AND table_name='recordings' AND column_name='ingested_at')=0, 'ALTER TABLE recordings ADD COLUMN ingested_at TIMESTAMP NULL', 'SELECT 1');
PREPARE ma_stmt FROM @ddl;
EXECUTE ma_stmt;
DEALLOCATE PREPARE ma_stmt;
SET @ddl = IF((SELECT COUNT(*) FROM information_schema.statistics WHERE table_schema=DATABASE() AND table_name='recordings' AND index_name='idx_recordings_user')=0, 'ALTER TABLE recordings ADD INDEX idx_recordings_user (user_id)', 'SELECT 1');
PREPARE ma_stmt FROM @ddl;
EXECUTE ma_stmt;
DEALLOCATE PREPARE ma_stmt;

SET @ddl = IF((SELECT COUNT(*) FROM information_schema.columns WHERE table_schema=DATABASE() AND table_name='mcp_api_keys' AND column_name='user_id')=0, 'ALTER TABLE mcp_api_keys ADD COLUMN user_id BIGINT NULL AFTER phone', 'SELECT 1');
PREPARE ma_stmt FROM @ddl;
EXECUTE ma_stmt;
DEALLOCATE PREPARE ma_stmt;
SET @ddl = IF((SELECT COUNT(*) FROM information_schema.columns WHERE table_schema=DATABASE() AND table_name='mcp_api_keys' AND column_name='active')=0, 'ALTER TABLE mcp_api_keys ADD COLUMN active TINYINT(1) NULL DEFAULT 1', 'SELECT 1');
PREPARE ma_stmt FROM @ddl;
EXECUTE ma_stmt;
DEALLOCATE PREPARE ma_stmt;
SET @ddl = IF((SELECT COUNT(*) FROM information_schema.statistics WHERE table_schema=DATABASE() AND table_name='mcp_api_keys' AND index_name='uk_key_hash')=0, 'ALTER TABLE mcp_api_keys ADD UNIQUE INDEX uk_key_hash (key_hash)', 'SELECT 1');
PREPARE ma_stmt FROM @ddl;
EXECUTE ma_stmt;
DEALLOCATE PREPARE ma_stmt;
SET @ddl = IF((SELECT COUNT(*) FROM information_schema.statistics WHERE table_schema=DATABASE() AND table_name='mcp_api_keys' AND index_name='idx_user_id')=0, 'ALTER TABLE mcp_api_keys ADD INDEX idx_user_id (user_id)', 'SELECT 1');
PREPARE ma_stmt FROM @ddl;
EXECUTE ma_stmt;
DEALLOCATE PREPARE ma_stmt;

SET @ddl = IF((SELECT COUNT(*) FROM information_schema.statistics WHERE table_schema=DATABASE() AND table_name='chunks' AND index_name='idx_chunks_recording_kind')=0, 'ALTER TABLE chunks ADD INDEX idx_chunks_recording_kind (recording_id, kind)', 'SELECT 1');
PREPARE ma_stmt FROM @ddl;
EXECUTE ma_stmt;
DEALLOCATE PREPARE ma_stmt;
SET @ddl = IF((SELECT COUNT(*) FROM information_schema.statistics WHERE table_schema=DATABASE() AND table_name='facts' AND index_name='idx_facts_type_subject')=0, 'ALTER TABLE facts ADD INDEX idx_facts_type_subject (fact_type, subject)', 'SELECT 1');
PREPARE ma_stmt FROM @ddl;
EXECUTE ma_stmt;
DEALLOCATE PREPARE ma_stmt;

-- Ingest and MCP require the upstream-owned source tables to exist, but never create them.
-- The application preflight command reports missing source fields before deployment.
