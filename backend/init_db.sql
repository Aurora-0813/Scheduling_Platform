-- 移动端预约与通知模块 MySQL 建表脚本（参考，字段对齐开发流程 §6.3 / §6.7）
-- 云数据库 smart_scheduler_dev 中表已由集成组创建完成（§6.5），此脚本仅作参考与文档。
-- 本模块只涉及以下 4 张表，其余表由队友模块负责。
-- 驱动统一 asyncmy（§3.4），建表由基础支撑与集成组执行。

CREATE TABLE IF NOT EXISTS space_resource (
  id              BIGINT UNSIGNED AUTO_INCREMENT PRIMARY KEY,
  space_name      VARCHAR(128) NOT NULL COMMENT '空间名称',
  space_type      INT NOT NULL DEFAULT 1 COMMENT '1会议室 2展厅 3多功能厅 4户外场地',
  capacity        INT NOT NULL DEFAULT 0 COMMENT '容纳人数',
  location        VARCHAR(255) DEFAULT '' COMMENT '位置',
  budget          DECIMAL(10,2) DEFAULT 0.00 COMMENT '预算',
  open_start_time TIME COMMENT '开放起始时间',
  open_end_time   TIME COMMENT '开放结束时间',
  status          INT NOT NULL DEFAULT 1 COMMENT '1可用 0停用',
  create_time     DATETIME DEFAULT CURRENT_TIMESTAMP COMMENT '创建时间',
  update_time     DATETIME DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP COMMENT '更新时间',
  INDEX idx_space_type (space_type),
  INDEX idx_capacity (capacity)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;

CREATE TABLE IF NOT EXISTS device_resource (
  id              BIGINT UNSIGNED AUTO_INCREMENT PRIMARY KEY,
  device_name     VARCHAR(128) NOT NULL COMMENT '设备名称',
  device_type     VARCHAR(64) DEFAULT '' COMMENT '设备类型',
  device_status   INT NOT NULL DEFAULT 1 COMMENT '1完好 2损坏 3缺失配件',
  total_count     INT NOT NULL DEFAULT 1 COMMENT '总数量',
  available_count INT NOT NULL DEFAULT 1 COMMENT '可用数量',
  create_time     DATETIME DEFAULT CURRENT_TIMESTAMP COMMENT '创建时间',
  update_time     DATETIME DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP COMMENT '更新时间',
  INDEX idx_device_type (device_type)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;

CREATE TABLE IF NOT EXISTS reserve_order (
  id            BIGINT UNSIGNED AUTO_INCREMENT PRIMARY KEY,
  user_id       BIGINT UNSIGNED NOT NULL COMMENT '预约人ID',
  space_id      BIGINT UNSIGNED NOT NULL COMMENT '空间ID',
  device_ids    JSON COMMENT '设备ID列表',
  start_time    DATETIME NOT NULL COMMENT '开始时间',
  end_time      DATETIME NOT NULL COMMENT '结束时间',
  order_status  INT NOT NULL DEFAULT 1 COMMENT '1待确认 2已确认 3已取消 4已完成',
  agent_request VARCHAR(1024) DEFAULT '' COMMENT '用户原始需求',
  agent_trace   JSON COMMENT 'AI思考过程追踪',
  create_time   DATETIME DEFAULT CURRENT_TIMESTAMP COMMENT '创建时间',
  update_time   DATETIME DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP COMMENT '更新时间',
  INDEX idx_user_id (user_id),
  INDEX idx_space_time (space_id, start_time, end_time),
  INDEX idx_status (order_status)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;

CREATE TABLE IF NOT EXISTS notify_message (
  id          BIGINT UNSIGNED AUTO_INCREMENT PRIMARY KEY,
  receiver_id BIGINT UNSIGNED NOT NULL COMMENT '接收人ID',
  notify_type INT NOT NULL DEFAULT 1 COMMENT '1预约提醒 2变更致歉 3故障告警',
  order_id    BIGINT UNSIGNED NULL COMMENT '关联订单ID',
  title       VARCHAR(255) DEFAULT '' COMMENT '通知标题',
  content     TEXT COMMENT '通知内容',
  is_read     INT NOT NULL DEFAULT 0 COMMENT '0未读 1已读',
  create_time DATETIME DEFAULT CURRENT_TIMESTAMP COMMENT '创建时间',
  INDEX idx_receiver_read (receiver_id, is_read)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;
