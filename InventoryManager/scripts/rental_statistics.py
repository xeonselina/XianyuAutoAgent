SELECT 
    planProductName,
    ROUND(AVG(daily_ratio), 2) as avg_30day_elasticity_ratio,
    COUNT(*) as days_count,
    ROUND(MIN(daily_ratio), 2) as min_ratio,
    ROUND(MAX(daily_ratio), 2) as max_ratio
FROM (
    SELECT 
        planProductName,
        DATE(date) as usage_date,
        ROUND((1 - SUM(used) / (MAX(pod_replicas) * 24)) * 100, 2) as daily_ratio
    FROM t_product_quota_used_history_hour
    WHERE date >= CURRENT_DATE - INTERVAL 30 DAY
    GROUP BY planProductName, DATE(timestamp_hour)
    HAVING COUNT(*) = 24  -- 完整24小时数据
) daily_stats
GROUP BY plan_product
HAVING COUNT(*) >= 20  -- 至少20天有效数据
ORDER BY avg_30day_elasticity_ratio DESC;