-- Uniform write contract across the legacy MCP schema (kind) and exported schema (fact_type).

SET @ddl = IF((SELECT COUNT(*) FROM information_schema.columns WHERE table_schema=DATABASE() AND table_name='facts' AND column_name='kind')=0, 'ALTER TABLE facts ADD COLUMN kind VARCHAR(64) NULL AFTER fact_type', 'SELECT 1');
PREPARE ma_stmt FROM @ddl;
EXECUTE ma_stmt;
DEALLOCATE PREPARE ma_stmt;

ALTER TABLE facts MODIFY COLUMN kind VARCHAR(64) NULL;

UPDATE facts
SET fact_type=COALESCE(fact_type, kind, 'general'),
    kind=COALESCE(kind, fact_type, 'general')
WHERE fact_type IS NULL OR kind IS NULL;
