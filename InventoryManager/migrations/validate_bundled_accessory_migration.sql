-- Validation SQL for bundled accessory migration
-- Run these queries after migration to verify correctness

-- 1. Check that new columns exist and have correct data types
SELECT 
    COLUMN_NAME, 
    DATA_TYPE, 
    IS_NULLABLE, 
    COLUMN_DEFAULT
FROM INFORMATION_SCHEMA.COLUMNS
WHERE TABLE_NAME = 'rentals' 
AND COLUMN_NAME IN ('includes_handle', 'includes_lens_mount');

-- Expected: 2 rows with TINYINT(1) type, NOT NULL, default 0

-- 2. Check that indexes were created
SHOW INDEXES FROM rentals 
WHERE Key_name IN ('idx_rentals_includes_handle', 'idx_rentals_includes_lens_mount');

-- Expected: 2 rows showing the indexes

-- 3. Verify data migration: Compare boolean flags with child rentals
-- This query finds any mismatches where boolean flag doesn't match child rental existence
SELECT 
    r.id,
    r.includes_handle,
    r.includes_lens_mount,
    COUNT(CASE WHEN d.name LIKE '%手柄%' THEN 1 END) as actual_handle_count,
    COUNT(CASE WHEN d.name LIKE '%镜头支架%' THEN 1 END) as actual_lens_mount_count
FROM rentals r
LEFT JOIN rentals child ON child.parent_rental_id = r.id
LEFT JOIN devices d ON child.device_id = d.id
WHERE r.parent_rental_id IS NULL
GROUP BY r.id, r.includes_handle, r.includes_lens_mount
HAVING 
    (r.includes_handle = 1 AND actual_handle_count = 0) OR
    (r.includes_handle = 0 AND actual_handle_count > 0) OR
    (r.includes_lens_mount = 1 AND actual_lens_mount_count = 0) OR
    (r.includes_lens_mount = 0 AND actual_lens_mount_count > 0);

-- Expected: 0 rows (no mismatches)

-- 4. Count distribution of bundled accessories
SELECT 
    includes_handle,
    includes_lens_mount,
    COUNT(*) as rental_count
FROM rentals
WHERE parent_rental_id IS NULL
GROUP BY includes_handle, includes_lens_mount
ORDER BY includes_handle, includes_lens_mount;

-- Expected: Reasonable distribution showing migration worked

-- 5. Sample check: Show a few rentals with their accessories
SELECT 
    r.id,
    r.customer_name,
    r.includes_handle,
    r.includes_lens_mount,
    GROUP_CONCAT(d.name SEPARATOR ', ') as child_accessories
FROM rentals r
LEFT JOIN rentals child ON child.parent_rental_id = r.id
LEFT JOIN devices d ON child.device_id = d.id
WHERE r.parent_rental_id IS NULL
GROUP BY r.id, r.customer_name, r.includes_handle, r.includes_lens_mount
LIMIT 10;

-- Expected: Boolean flags should align with presence of accessories in child_accessories
