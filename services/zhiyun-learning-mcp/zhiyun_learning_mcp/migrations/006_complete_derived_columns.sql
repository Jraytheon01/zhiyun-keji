-- Add every derived-table column used by the current runtime when a test database
-- already has an older/partial version of these tables. Additive only.

SET @ddl = IF((SELECT COUNT(*) FROM information_schema.columns WHERE table_schema=DATABASE() AND table_name='recordings' AND column_name='uploaded_at')=0, 'ALTER TABLE recordings ADD COLUMN uploaded_at TIMESTAMP NULL', 'SELECT 1');
PREPARE ma_stmt FROM @ddl;
EXECUTE ma_stmt;
DEALLOCATE PREPARE ma_stmt;
SET @ddl = IF((SELECT COUNT(*) FROM information_schema.columns WHERE table_schema=DATABASE() AND table_name='recordings' AND column_name='has_audio')=0, 'ALTER TABLE recordings ADD COLUMN has_audio TINYINT(1) NULL', 'SELECT 1');
PREPARE ma_stmt FROM @ddl;
EXECUTE ma_stmt;
DEALLOCATE PREPARE ma_stmt;
SET @ddl = IF((SELECT COUNT(*) FROM information_schema.columns WHERE table_schema=DATABASE() AND table_name='recordings' AND column_name='has_transcript')=0, 'ALTER TABLE recordings ADD COLUMN has_transcript TINYINT(1) NULL', 'SELECT 1');
PREPARE ma_stmt FROM @ddl; EXECUTE ma_stmt; DEALLOCATE PREPARE ma_stmt;
SET @ddl = IF((SELECT COUNT(*) FROM information_schema.columns WHERE table_schema=DATABASE() AND table_name='recordings' AND column_name='has_summary')=0, 'ALTER TABLE recordings ADD COLUMN has_summary TINYINT(1) NULL', 'SELECT 1');
PREPARE ma_stmt FROM @ddl; EXECUTE ma_stmt; DEALLOCATE PREPARE ma_stmt;
SET @ddl = IF((SELECT COUNT(*) FROM information_schema.columns WHERE table_schema=DATABASE() AND table_name='recordings' AND column_name='chunk_count')=0, 'ALTER TABLE recordings ADD COLUMN chunk_count INT NULL', 'SELECT 1');
PREPARE ma_stmt FROM @ddl; EXECUTE ma_stmt; DEALLOCATE PREPARE ma_stmt;
SET @ddl = IF((SELECT COUNT(*) FROM information_schema.columns WHERE table_schema=DATABASE() AND table_name='recordings' AND column_name='fact_count')=0, 'ALTER TABLE recordings ADD COLUMN fact_count INT NULL', 'SELECT 1');
PREPARE ma_stmt FROM @ddl; EXECUTE ma_stmt; DEALLOCATE PREPARE ma_stmt;
SET @ddl = IF((SELECT COUNT(*) FROM information_schema.columns WHERE table_schema=DATABASE() AND table_name='recordings' AND column_name='todo_count')=0, 'ALTER TABLE recordings ADD COLUMN todo_count INT NULL', 'SELECT 1');
PREPARE ma_stmt FROM @ddl; EXECUTE ma_stmt; DEALLOCATE PREPARE ma_stmt;
SET @ddl = IF((SELECT COUNT(*) FROM information_schema.columns WHERE table_schema=DATABASE() AND table_name='recordings' AND column_name='embed_model')=0, 'ALTER TABLE recordings ADD COLUMN embed_model VARCHAR(128) NULL', 'SELECT 1');
PREPARE ma_stmt FROM @ddl; EXECUTE ma_stmt; DEALLOCATE PREPARE ma_stmt;
SET @ddl = IF((SELECT COUNT(*) FROM information_schema.columns WHERE table_schema=DATABASE() AND table_name='recordings' AND column_name='extract_model')=0, 'ALTER TABLE recordings ADD COLUMN extract_model VARCHAR(128) NULL', 'SELECT 1');
PREPARE ma_stmt FROM @ddl; EXECUTE ma_stmt; DEALLOCATE PREPARE ma_stmt;

SET @ddl = IF((SELECT COUNT(*) FROM information_schema.columns WHERE table_schema=DATABASE() AND table_name='chunks' AND column_name='recording_id')=0, 'ALTER TABLE chunks ADD COLUMN recording_id VARCHAR(64) NULL', 'SELECT 1');
PREPARE ma_stmt FROM @ddl; EXECUTE ma_stmt; DEALLOCATE PREPARE ma_stmt;
SET @ddl = IF((SELECT COUNT(*) FROM information_schema.columns WHERE table_schema=DATABASE() AND table_name='chunks' AND column_name='user_id')=0, 'ALTER TABLE chunks ADD COLUMN user_id BIGINT NULL', 'SELECT 1');
PREPARE ma_stmt FROM @ddl; EXECUTE ma_stmt; DEALLOCATE PREPARE ma_stmt;
SET @ddl = IF((SELECT COUNT(*) FROM information_schema.columns WHERE table_schema=DATABASE() AND table_name='chunks' AND column_name='text')=0, 'ALTER TABLE chunks ADD COLUMN text MEDIUMTEXT NULL', 'SELECT 1');
PREPARE ma_stmt FROM @ddl; EXECUTE ma_stmt; DEALLOCATE PREPARE ma_stmt;

SET @ddl = IF((SELECT COUNT(*) FROM information_schema.columns WHERE table_schema=DATABASE() AND table_name='facts' AND column_name='recording_id')=0, 'ALTER TABLE facts ADD COLUMN recording_id VARCHAR(64) NULL', 'SELECT 1');
PREPARE ma_stmt FROM @ddl; EXECUTE ma_stmt; DEALLOCATE PREPARE ma_stmt;
SET @ddl = IF((SELECT COUNT(*) FROM information_schema.columns WHERE table_schema=DATABASE() AND table_name='facts' AND column_name='user_id')=0, 'ALTER TABLE facts ADD COLUMN user_id BIGINT NULL', 'SELECT 1');
PREPARE ma_stmt FROM @ddl; EXECUTE ma_stmt; DEALLOCATE PREPARE ma_stmt;
SET @ddl = IF((SELECT COUNT(*) FROM information_schema.columns WHERE table_schema=DATABASE() AND table_name='facts' AND column_name='created_at')=0, 'ALTER TABLE facts ADD COLUMN created_at DATETIME NULL DEFAULT CURRENT_TIMESTAMP', 'SELECT 1');
PREPARE ma_stmt FROM @ddl; EXECUTE ma_stmt; DEALLOCATE PREPARE ma_stmt;

SET @ddl = IF((SELECT COUNT(*) FROM information_schema.columns WHERE table_schema=DATABASE() AND table_name='todos' AND column_name='recording_id')=0, 'ALTER TABLE todos ADD COLUMN recording_id VARCHAR(64) NULL', 'SELECT 1');
PREPARE ma_stmt FROM @ddl; EXECUTE ma_stmt; DEALLOCATE PREPARE ma_stmt;
SET @ddl = IF((SELECT COUNT(*) FROM information_schema.columns WHERE table_schema=DATABASE() AND table_name='todos' AND column_name='user_id')=0, 'ALTER TABLE todos ADD COLUMN user_id BIGINT NULL', 'SELECT 1');
PREPARE ma_stmt FROM @ddl; EXECUTE ma_stmt; DEALLOCATE PREPARE ma_stmt;
SET @ddl = IF((SELECT COUNT(*) FROM information_schema.columns WHERE table_schema=DATABASE() AND table_name='todos' AND column_name='task')=0, 'ALTER TABLE todos ADD COLUMN task VARCHAR(500) NULL', 'SELECT 1');
PREPARE ma_stmt FROM @ddl; EXECUTE ma_stmt; DEALLOCATE PREPARE ma_stmt;
SET @ddl = IF((SELECT COUNT(*) FROM information_schema.columns WHERE table_schema=DATABASE() AND table_name='todos' AND column_name='owner')=0, 'ALTER TABLE todos ADD COLUMN owner VARCHAR(100) NULL', 'SELECT 1');
PREPARE ma_stmt FROM @ddl; EXECUTE ma_stmt; DEALLOCATE PREPARE ma_stmt;
SET @ddl = IF((SELECT COUNT(*) FROM information_schema.columns WHERE table_schema=DATABASE() AND table_name='todos' AND column_name='due')=0, 'ALTER TABLE todos ADD COLUMN due DATETIME NULL', 'SELECT 1');
PREPARE ma_stmt FROM @ddl; EXECUTE ma_stmt; DEALLOCATE PREPARE ma_stmt;
SET @ddl = IF((SELECT COUNT(*) FROM information_schema.columns WHERE table_schema=DATABASE() AND table_name='todos' AND column_name='status')=0, 'ALTER TABLE todos ADD COLUMN status VARCHAR(20) NULL DEFAULT ''open''', 'SELECT 1');
PREPARE ma_stmt FROM @ddl; EXECUTE ma_stmt; DEALLOCATE PREPARE ma_stmt;

SET @ddl = IF((SELECT COUNT(*) FROM information_schema.columns WHERE table_schema=DATABASE() AND table_name='mcp_api_keys' AND column_name='key_hash')=0, 'ALTER TABLE mcp_api_keys ADD COLUMN key_hash VARCHAR(64) NULL', 'SELECT 1');
PREPARE ma_stmt FROM @ddl; EXECUTE ma_stmt; DEALLOCATE PREPARE ma_stmt;
