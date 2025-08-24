-- 创建数据库
CREATE DATABASE IF NOT EXISTS inventory_db CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci;

-- 使用数据库
USE inventory_db;

-- 创建设备表
CREATE TABLE IF NOT EXISTS devices (
    id INT AUTO_INCREMENT PRIMARY KEY,
    name VARCHAR(100) NOT NULL COMMENT '设备名称',
    serial_number VARCHAR(100) UNIQUE COMMENT '设备序列号',
    status ENUM('idle', 'pending_ship', 'renting', 'pending_return', 'returned', 'offline') DEFAULT 'idle' COMMENT '设备状态',
    location VARCHAR(100) COMMENT '设备位置',
    created_at DATETIME DEFAULT CURRENT_TIMESTAMP COMMENT '创建时间',
    updated_at DATETIME DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP COMMENT '更新时间'
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

-- 创建租赁表
CREATE TABLE IF NOT EXISTS rentals (
    id INT AUTO_INCREMENT PRIMARY KEY,
    device_id INT NOT NULL COMMENT '设备ID',
    start_date DATE NOT NULL COMMENT '开始日期',
    end_date DATE NOT NULL COMMENT '结束日期',
    ship_out_time DATETIME COMMENT '寄出时间',
    ship_in_time DATETIME COMMENT '收回时间',
    customer_name VARCHAR(100) NOT NULL COMMENT '客户姓名',
    customer_phone VARCHAR(20) COMMENT '客户电话',
    destination TEXT COMMENT '目的地',
    ship_out_tracking_no VARCHAR(50) COMMENT '寄出快递单号',
    ship_in_tracking_no VARCHAR(50) COMMENT '寄回快递单号',
    status ENUM('pending', 'active', 'completed', 'cancelled', 'overdue') DEFAULT 'pending' COMMENT '租赁状态',
    created_at DATETIME DEFAULT CURRENT_TIMESTAMP COMMENT '创建时间',
    updated_at DATETIME DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP COMMENT '更新时间',
    FOREIGN KEY (device_id) REFERENCES devices(id) ON DELETE CASCADE
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

-- 创建审计日志表
CREATE TABLE IF NOT EXISTS audit_logs (
    id INT AUTO_INCREMENT PRIMARY KEY,
    device_id INT COMMENT '设备ID',
    rental_id INT COMMENT '租赁ID',
    action VARCHAR(50) NOT NULL COMMENT '操作类型',
    old_value TEXT COMMENT '原值',
    new_value TEXT COMMENT '新值',
    user_id VARCHAR(100) COMMENT '用户ID',
    timestamp DATETIME DEFAULT CURRENT_TIMESTAMP COMMENT '操作时间',
    FOREIGN KEY (device_id) REFERENCES devices(id) ON DELETE SET NULL,
    FOREIGN KEY (rental_id) REFERENCES rentals(id) ON DELETE SET NULL
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

-- 创建索引
CREATE INDEX idx_devices_status ON devices(status);
CREATE INDEX idx_rentals_device_id ON rentals(device_id);
CREATE INDEX idx_rentals_dates ON rentals(start_date, end_date);
CREATE INDEX idx_rentals_status ON rentals(status);
CREATE INDEX idx_rentals_tracking ON rentals(ship_out_tracking_no, ship_in_tracking_no);
CREATE INDEX idx_audit_logs_device_id ON audit_logs(device_id);
CREATE INDEX idx_audit_logs_rental_id ON audit_logs(rental_id);
CREATE INDEX idx_audit_logs_timestamp ON audit_logs(timestamp);

-- 插入示例数据
INSERT IGNORE INTO devices (name, serial_number, status, location) VALUES
('iPhone 15 Pro Max', 'IP15PM001', 'idle', '深圳仓库'),
('Canon EOS R5', 'CR5001', 'idle', '深圳仓库'),
('MacBook Pro 16"', 'MBP16001', 'idle', '深圳仓库'),
('DJI Mini 4 Pro', 'DM4P001', 'idle', '深圳仓库'),
('Sony A7R5', 'SA7R5001', 'idle', '深圳仓库');

-- 设置权限
GRANT ALL PRIVILEGES ON inventory_db.* TO 'inventory_user'@'%';
FLUSH PRIVILEGES;