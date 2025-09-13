#!/bin/bash

# 简单的MySQL备份脚本
DB_PASSWORD="Xs527215!!!"
BACKUP_DIR="/volume3/backup/db"
DATE=$(date +%Y%m%d_%H%M%S)

# 创建备份目录
mkdir -p "$BACKUP_DIR"

# 备份所有数据库
mysqldump -uroot -p"$DB_PASSWORD" --all-databases > "$BACKUP_DIR/backup_$DATE.sql"

# 压缩备份文件
gzip "$BACKUP_DIR/backup_$DATE.sql"

echo "$(date) - 备份完成: backup_$DATE.sql.gz" >> "$BACKUP_DIR/backup.log"