-- Switch the runtime tenant key from user_id to phone without dropping legacy columns.

SET @ddl = IF((SELECT COUNT(*) FROM information_schema.columns WHERE table_schema=DATABASE() AND table_name='recordings' AND column_name='phone')=0, 'ALTER TABLE recordings ADD COLUMN phone VARCHAR(32) NULL AFTER recording_id', 'SELECT 1');
PREPARE ma_stmt FROM @ddl; EXECUTE ma_stmt; DEALLOCATE PREPARE ma_stmt;
SET @ddl = IF((SELECT COUNT(*) FROM information_schema.columns WHERE table_schema=DATABASE() AND table_name='chunks' AND column_name='phone')=0, 'ALTER TABLE chunks ADD COLUMN phone VARCHAR(32) NULL AFTER recording_id', 'SELECT 1');
PREPARE ma_stmt FROM @ddl; EXECUTE ma_stmt; DEALLOCATE PREPARE ma_stmt;
SET @ddl = IF((SELECT COUNT(*) FROM information_schema.columns WHERE table_schema=DATABASE() AND table_name='facts' AND column_name='phone')=0, 'ALTER TABLE facts ADD COLUMN phone VARCHAR(32) NULL AFTER recording_id', 'SELECT 1');
PREPARE ma_stmt FROM @ddl; EXECUTE ma_stmt; DEALLOCATE PREPARE ma_stmt;
SET @ddl = IF((SELECT COUNT(*) FROM information_schema.columns WHERE table_schema=DATABASE() AND table_name='todos' AND column_name='phone')=0, 'ALTER TABLE todos ADD COLUMN phone VARCHAR(32) NULL AFTER recording_id', 'SELECT 1');
PREPARE ma_stmt FROM @ddl; EXECUTE ma_stmt; DEALLOCATE PREPARE ma_stmt;

UPDATE recordings r JOIN user_meeting_info m ON m.id=CAST(r.recording_id AS UNSIGNED)
SET r.phone=m.phone WHERE r.phone IS NULL OR r.phone='';
UPDATE chunks c JOIN user_meeting_info m ON m.id=CAST(c.recording_id AS UNSIGNED)
SET c.phone=m.phone WHERE c.phone IS NULL OR c.phone='';
UPDATE facts f JOIN user_meeting_info m ON m.id=CAST(f.recording_id AS UNSIGNED)
SET f.phone=m.phone WHERE f.phone IS NULL OR f.phone='';
UPDATE todos t JOIN user_meeting_info m ON m.id=CAST(t.recording_id AS UNSIGNED)
SET t.phone=m.phone WHERE t.phone IS NULL OR t.phone='';

SET @ddl = IF((SELECT COUNT(*) FROM information_schema.statistics WHERE table_schema=DATABASE() AND table_name='recordings' AND index_name='idx_recordings_phone')=0, 'ALTER TABLE recordings ADD INDEX idx_recordings_phone (phone)', 'SELECT 1');
PREPARE ma_stmt FROM @ddl; EXECUTE ma_stmt; DEALLOCATE PREPARE ma_stmt;
SET @ddl = IF((SELECT COUNT(*) FROM information_schema.statistics WHERE table_schema=DATABASE() AND table_name='chunks' AND index_name='idx_chunks_tenant_recording_phone')=0, 'ALTER TABLE chunks ADD INDEX idx_chunks_tenant_recording_phone (phone, recording_id)', 'SELECT 1');
PREPARE ma_stmt FROM @ddl; EXECUTE ma_stmt; DEALLOCATE PREPARE ma_stmt;
SET @ddl = IF((SELECT COUNT(*) FROM information_schema.statistics WHERE table_schema=DATABASE() AND table_name='facts' AND index_name='idx_facts_tenant_status_phone')=0, 'ALTER TABLE facts ADD INDEX idx_facts_tenant_status_phone (phone, status)', 'SELECT 1');
PREPARE ma_stmt FROM @ddl; EXECUTE ma_stmt; DEALLOCATE PREPARE ma_stmt;
SET @ddl = IF((SELECT COUNT(*) FROM information_schema.statistics WHERE table_schema=DATABASE() AND table_name='todos' AND index_name='idx_todos_tenant_status_due_phone')=0, 'ALTER TABLE todos ADD INDEX idx_todos_tenant_status_due_phone (phone, status, due)', 'SELECT 1');
PREPARE ma_stmt FROM @ddl; EXECUTE ma_stmt; DEALLOCATE PREPARE ma_stmt;
