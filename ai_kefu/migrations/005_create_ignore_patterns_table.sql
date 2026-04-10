-- Migration 005: Create ignore_patterns table
-- Stores message patterns that should be ignored (not processed by AI agent)
-- These are typically system messages from Xianyu like [图片], [买家已确认退回金额] etc.

CREATE TABLE IF NOT EXISTS ignore_patterns (
    id INT AUTO_INCREMENT PRIMARY KEY,
    pattern VARCHAR(500) NOT NULL COMMENT '要忽略的消息内容（精确匹配）',
    description VARCHAR(500) DEFAULT NULL COMMENT '描述说明',
    active BOOLEAN NOT NULL DEFAULT TRUE COMMENT '是否启用',
    created_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
    UNIQUE KEY uk_pattern (pattern)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci COMMENT='消息忽略白名单';

-- Insert default ignore patterns
INSERT IGNORE INTO ignore_patterns (pattern, description, active) VALUES
    ('[图片]', '图片消息', TRUE),
    ('[买家已确认退回金额，交易成功]', '退款成功系统消息', TRUE),
    ('[我完成了评价]', '评价系统消息', TRUE),
    ('[我已付款，等待你发货]', '付款系统消息', TRUE),
    ('[你关闭了订单，钱款已原路退返]', '关闭订单退款系统消息', TRUE),
    ('[未付款，买家关闭了订单]', '买家关闭订单系统消息', TRUE),
    ('[卡片消息]', '卡片消息', TRUE),
    ('[记得寄回发货]', '寄回提醒系统消息', TRUE),
    ('[待买家确认退回金额]', '待确认退款系统消息', TRUE),
    ('[视频]', '视频消息', TRUE),
    ('[买家已寄回]', '买家寄回系统消息', TRUE),
    ('[风险提示]', '风险提示系统消息', TRUE),
    ('[你已发货]', '发货系统消息', TRUE),
    ('[超时未付款，系统关闭了订单]', '超时关闭订单系统消息', TRUE),
    ('[待卖家确认退回金额]', '待卖家确认退款系统消息', TRUE),
    ('[不想宝贝被砍价?设置不砍价回复  ]', '砍价提示系统消息', TRUE),
    ('[订单派送中，请注意查收]', '派送中系统消息', TRUE),
    ('[我已发货，请查看发货凭证]', '发货凭证系统消息', TRUE),
    ('[物流已签收]', '签收系统消息', TRUE),
    ('[语音聊天]', '语音聊天消息', TRUE),
    ('[你已确认收货，交易成功]', '确认收货系统消息', TRUE),
    ('[未付款，你关闭了订单]', '卖家关闭订单系统消息', TRUE);
