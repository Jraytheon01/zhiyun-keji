-- Backfill additive compatibility columns without deleting or rewriting source data.

SET @ddl = IF((SELECT COUNT(*) FROM information_schema.columns WHERE table_schema=DATABASE() AND table_name='chunks' AND column_name='ordinal')=1, 'UPDATE chunks SET chunk_index=COALESCE(chunk_index, ordinal) WHERE chunk_index IS NULL', 'SELECT 1');
PREPARE ma_stmt FROM @ddl;
EXECUTE ma_stmt;
DEALLOCATE PREPARE ma_stmt;

UPDATE facts
SET meeting_id=COALESCE(meeting_id, recording_id),
    subject=COALESCE(subject, LEFT(fact_text, 512)),
    detail=COALESCE(detail, JSON_OBJECT('text', fact_text)),
    status=COALESCE(status, 'active')
WHERE meeting_id IS NULL OR subject IS NULL OR detail IS NULL OR status IS NULL;
