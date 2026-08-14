-- Foundation for legacy/partial test tables. Add only columns referenced by later
-- migrations; never drop or rename existing objects.

SET @ddl = IF((SELECT COUNT(*) FROM information_schema.columns WHERE table_schema=DATABASE() AND table_name='chunks' AND column_name='recording_id')=0, 'ALTER TABLE chunks ADD COLUMN recording_id VARCHAR(64) NULL', 'SELECT 1');
PREPARE ma_stmt FROM @ddl;
EXECUTE ma_stmt;
DEALLOCATE PREPARE ma_stmt;
SET @ddl = IF((SELECT COUNT(*) FROM information_schema.columns WHERE table_schema=DATABASE() AND table_name='chunks' AND column_name='user_id')=0, 'ALTER TABLE chunks ADD COLUMN user_id BIGINT NULL', 'SELECT 1');
PREPARE ma_stmt FROM @ddl;
EXECUTE ma_stmt;
DEALLOCATE PREPARE ma_stmt;
SET @ddl = IF((SELECT COUNT(*) FROM information_schema.columns WHERE table_schema=DATABASE() AND table_name='chunks' AND column_name='created_at')=0, 'ALTER TABLE chunks ADD COLUMN created_at DATETIME NULL DEFAULT CURRENT_TIMESTAMP', 'SELECT 1');
PREPARE ma_stmt FROM @ddl;
EXECUTE ma_stmt;
DEALLOCATE PREPARE ma_stmt;

SET @ddl = IF((SELECT COUNT(*) FROM information_schema.columns WHERE table_schema=DATABASE() AND table_name='facts' AND column_name='recording_id')=0, 'ALTER TABLE facts ADD COLUMN recording_id VARCHAR(64) NULL', 'SELECT 1');
PREPARE ma_stmt FROM @ddl;
EXECUTE ma_stmt;
DEALLOCATE PREPARE ma_stmt;
SET @ddl = IF((SELECT COUNT(*) FROM information_schema.columns WHERE table_schema=DATABASE() AND table_name='facts' AND column_name='user_id')=0, 'ALTER TABLE facts ADD COLUMN user_id BIGINT NULL', 'SELECT 1');
PREPARE ma_stmt FROM @ddl;
EXECUTE ma_stmt;
DEALLOCATE PREPARE ma_stmt;

SET @ddl = IF((SELECT COUNT(*) FROM information_schema.columns WHERE table_schema=DATABASE() AND table_name='todos' AND column_name='recording_id')=0, 'ALTER TABLE todos ADD COLUMN recording_id VARCHAR(64) NULL', 'SELECT 1');
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

SET @ddl = IF((SELECT COUNT(*) FROM information_schema.columns WHERE table_schema=DATABASE() AND table_name='mcp_api_keys' AND column_name='key_hash')=0, 'ALTER TABLE mcp_api_keys ADD COLUMN key_hash VARCHAR(64) NULL', 'SELECT 1');
PREPARE ma_stmt FROM @ddl;
EXECUTE ma_stmt;
DEALLOCATE PREPARE ma_stmt;
