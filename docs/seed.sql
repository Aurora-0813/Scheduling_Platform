-- ============================================================================
--  种子数据脚本  docs/seed.sql
--  依据《项目文档.md》6.9
-- ----------------------------------------------------------------------------
--  目标库：smart_scheduler_dev   （测试库 smart_scheduler_test 另建，结构一致）
--  内容：3 用户 / 3 角色 / 8 场地 / 15 设备 / 10 条历史预约
--
--  🔴 使用前必读
--  1. 本脚本只插数据，不含任何建表或改表语句（表结构见 docs/database.md 第六节）。
--  2. 执行前必须确认目标库。导入命令中的密码从本地 .env 取，不要写进命令行历史：
--       mysql -h "$DB_HOST" -P "$DB_PORT" -u "$DB_USER" -p smart_scheduler_dev < docs/seed.sql
--  3. 本脚本按固定 ID 插入，**重复执行会因主键冲突失败**。需要重置时执行文末的清理段。
--  4. 演示口令 Demo@123 是开发库专用，禁止用于任何真实环境。
--
--  数据不是随手编的：容量、预算、设备状态被五个评审场景的断言反向约束。
--  改动任何数值前，先读 docs/database.md 第 8.1 节。
-- ============================================================================

SET NAMES utf8mb4;
SET time_zone = '+08:00';

-- ============================================================================
--  1. sys_role 角色表（3 条）
--     按主文档 6.9「3 个用户（普通用户、管理员、系统管理员）」配套生成，
--     否则 sys_user.role_id 的外键无从成立。
-- ============================================================================
INSERT INTO sys_role (id, role_name, permissions, create_time) VALUES
(1, '普通用户',   JSON_ARRAY('space:query', 'device:query', 'order:add', 'order:list', 'order:cancel'), NOW()),
(2, '管理员',     JSON_ARRAY('space:*', 'device:*', 'order:*', 'inspect:*', 'ticket:*'),               NOW()),
(3, '系统管理员', JSON_ARRAY('*'),                                                                     NOW());

-- ============================================================================
--  2. sys_user 用户表（3 条）
--     password 为 bcrypt 哈希，明文是演示口令 Demo@123（见 database.md 8.2）
-- ============================================================================
INSERT INTO sys_user (id, username, password, role_id, avatar, status, create_time, update_time) VALUES
(1, 'zhangsan', '$2b$12$WPAzHZb7EolabiZR5BLNMeZs1iYXMklXA9S0GRF4B4soj3Jmh45N.', 1, NULL, 1, NOW(), NOW()),
(2, 'lisi',     '$2b$12$WPAzHZb7EolabiZR5BLNMeZs1iYXMklXA9S0GRF4B4soj3Jmh45N.', 2, NULL, 1, NOW(), NOW()),
(3, 'admin',    '$2b$12$WPAzHZb7EolabiZR5BLNMeZs1iYXMklXA9S0GRF4B4soj3Jmh45N.', 3, NULL, 1, NOW(), NOW());

-- ============================================================================
--  3. space_resource 空间资源表（8 条）
--     会议室 ×3、展厅 ×2、多功能厅 ×2、户外 ×1
--
--     ⚠️ 三条不可随意改动的约束（改动即导致评审场景失效）：
--        a) 会议室最大容量 30 < 40  → 场景 B「拆分」的前提
--        b) 无任何「容量 ≥40 且预算 ≤500」的场地 → 场景 D「需求矛盾」的前提
--        c) id=4 容量 50 / 预算 800 → 场景 A「预算降级」的落点
-- ============================================================================
INSERT INTO space_resource
  (id, space_name, space_type, capacity, location, budget, open_start_time, open_end_time, status, create_time, update_time) VALUES
-- 会议室 ×3（capacity 全部 < 40）
(1, 'A栋201会议室',       1,  12, 'A栋2楼东侧',       200.00, '08:00:00', '22:00:00', 1, NOW(), NOW()),
(2, 'A栋305会议室',       1,  20, 'A栋3楼西侧',       300.00, '08:00:00', '22:00:00', 1, NOW(), NOW()),
(3, 'B栋102会议室',       1,  30, 'B栋1楼大厅旁',     450.00, '08:00:00', '22:00:00', 1, NOW(), NOW()),
-- 展厅 ×2
(4, 'A栋3楼展厅',         2,  50, 'A栋3楼中庭',       800.00, '09:00:00', '21:00:00', 1, NOW(), NOW()),
(5, 'C栋1楼展厅',         2,  35, 'C栋1楼入口',       600.00, '09:00:00', '21:00:00', 1, NOW(), NOW()),
-- 多功能厅 ×2
(6, '综合楼大礼堂',       3,  80, '综合楼1楼',       1500.00, '08:00:00', '22:00:00', 1, NOW(), NOW()),
(7, '综合楼小多功能厅',   3,  25, '综合楼2楼',        400.00, '08:00:00', '22:00:00', 1, NOW(), NOW()),
-- 户外 ×1
(8, '中心广场',           4, 100, '园区中心',        1000.00, '06:00:00', '23:00:00', 1, NOW(), NOW());

-- ============================================================================
--  4. device_resource 设备资源表（15 条）
--     投影仪 ×4、音响 ×4、显示屏 ×3、无人机 ×2、直播设备 ×2
--
--     ⚠️ 三条约束：
--        a) id=1~4 投影仪必须全部 device_status=1 且 available_count=1。
--           场景 C「投影仪全占用」要靠**预约占用**触发，不能靠设备本身不可用蒙混。
--        b) id=13、id=15 是给「过滤条件必须真的过滤掉东西」准备的两个见证者，
--           且必须**互相独立**：
--             id=13 无人机02：device_status=2 但 available_count=1
--                             → 只被「状态」分支筛掉
--             id=15 直播设备02：device_status=1 但 available_count=0
--                             → 只被「可用数」分支筛掉
--           若一台设备同时满足两个坏条件（status=2 且 available=0），那么漏写
--           任一过滤条件的查询都会"碰巧"把它排除掉，用例就抓不到 bug 了。
--        c) id=13 的 available_count=1 是有意为之：设备报损后库存字段未同步，
--           这正是过滤条件要防的数据状态，不是笔误。
-- ============================================================================
INSERT INTO device_resource
  (id, device_name, device_type, device_status, total_count, available_count, create_time, update_time) VALUES
-- 投影仪 ×4（全部完好、全部可借）
( 1, '投影仪01',   '投影仪',   1, 1, 1, NOW(), NOW()),
( 2, '投影仪02',   '投影仪',   1, 1, 1, NOW(), NOW()),
( 3, '投影仪03',   '投影仪',   1, 1, 1, NOW(), NOW()),
( 4, '投影仪04',   '投影仪',   1, 1, 1, NOW(), NOW()),
-- 音响 ×4
( 5, '音响01',     '音响',     1, 1, 1, NOW(), NOW()),
( 6, '音响02',     '音响',     1, 1, 1, NOW(), NOW()),
( 7, '音响03',     '音响',     1, 1, 1, NOW(), NOW()),
( 8, '音响04',     '音响',     1, 2, 2, NOW(), NOW()),
-- 显示屏 ×3（场景 C 的替代设备）
( 9, 'LED显示屏01', '显示屏',  1, 1, 1, NOW(), NOW()),
(10, 'LED显示屏02', '显示屏',  1, 1, 1, NOW(), NOW()),
(11, 'LED显示屏03', '显示屏',  1, 1, 1, NOW(), NOW()),
-- 无人机 ×2
(12, '无人机01',   '无人机',   1, 2, 2, NOW(), NOW()),
(13, '无人机02',   '无人机',   2, 1, 1, NOW(), NOW()),   -- 损坏（device_status=2），库存字段未同步
-- 直播设备 ×2
(14, '直播设备01', '直播设备', 1, 1, 1, NOW(), NOW()),
(15, '直播设备02', '直播设备', 1, 1, 0, NOW(), NOW());   -- 完好但全部借出（available_count=0）

-- ============================================================================
--  5. reserve_order 历史预约表（10 条）
--     覆盖 4 种订单状态、不同时段。
--
--     📌 演示基准日 2026-10-15（周四）。针对评审场景的用例，请求时间窗应落在该日
--        或其前后 1 日内，否则命不中下面预设的占用状态。
--
--     📌 id=7~10 是场景 C 的关键：四台投影仪在 2026-10-15 13:00~17:00 被全部占用，
--        此时再请求该时段的投影仪只能走替代方案。改动这四条会使场景 C 失效。
--
--     📌 id=5、id=6 是场景 E 的关键：同一用户在同一天、同一场地连开两场，
--        构成「可合并」的历史依据。
--
--     📌 agent_trace 一律留 NULL：这批数据的时间早于 Agent 上线，
--        编造一个与真实 trace 格式未必一致的假 trace，会让前端联调时被误导。
-- ============================================================================
INSERT INTO reserve_order
  (id, user_id, space_id, device_ids, start_time, end_time, order_status, agent_request, agent_trace, create_time, update_time) VALUES
-- 已完成（order_status=4）：过去时段
( 1, 1, 3, JSON_ARRAY(1),        '2026-10-08 09:00:00', '2026-10-08 11:00:00', 4, '下周找个30人的会议室开部门例会，需要投影', NULL, '2026-10-07 10:12:00', '2026-10-08 11:05:00'),
( 2, 1, 1, JSON_ARRAY(5),        '2026-10-09 14:00:00', '2026-10-09 16:00:00', 4, '小会议室，12人左右，要个音响',             NULL, '2026-10-08 16:40:00', '2026-10-09 16:03:00'),
-- 已取消（order_status=3）：释放占位，用于验证「已取消不参与冲突判定」
( 3, 2, 4, JSON_ARRAY(9),        '2026-10-12 10:00:00', '2026-10-12 12:00:00', 3, '展厅办个小型产品体验，配一块屏幕',        NULL, '2026-10-10 09:20:00', '2026-10-11 15:30:00'),
-- 已确认（order_status=2）：本周
( 4, 3, 6, JSON_ARRAY(),         '2026-10-13 09:00:00', '2026-10-13 17:00:00', 2, '大礼堂全天，全员大会',                    NULL, '2026-10-09 11:00:00', '2026-10-09 11:30:00'),
-- 场景 E：同用户、同场地、同一天连开两场（下午场为待确认）
( 5, 1, 2, JSON_ARRAY(6),        '2026-10-15 09:00:00', '2026-10-15 12:00:00', 2, '15号上午A栋305开个20人的评审会，要音响',  NULL, '2026-10-10 14:00:00', '2026-10-10 14:20:00'),
( 6, 1, 2, JSON_ARRAY(7),        '2026-10-15 13:00:00', '2026-10-15 17:00:00', 1, '还是同一天下午，同一个房间，接着开',      NULL, '2026-10-10 14:25:00', '2026-10-10 14:25:00'),
-- 场景 C：演示基准日 13:00~17:00，四台投影仪被四个不同场地全部占用
( 7, 2, 1, JSON_ARRAY(1),        '2026-10-15 13:00:00', '2026-10-15 17:00:00', 2, 'A栋201下午培训，需要投影仪',              NULL, '2026-10-11 10:00:00', '2026-10-11 10:15:00'),
( 8, 2, 3, JSON_ARRAY(2),        '2026-10-15 13:00:00', '2026-10-15 17:00:00', 2, 'B栋102下午客户对接，需要投影仪',          NULL, '2026-10-11 10:20:00', '2026-10-11 10:35:00'),
( 9, 3, 4, JSON_ARRAY(3),        '2026-10-15 13:00:00', '2026-10-15 17:00:00', 1, 'A栋3楼展厅下午布展，需要投影仪',          NULL, '2026-10-12 09:00:00', '2026-10-12 09:00:00'),
(10, 3, 5, JSON_ARRAY(4),        '2026-10-15 13:00:00', '2026-10-15 17:00:00', 2, 'C栋1楼展厅下午路演，需要投影仪',          NULL, '2026-10-12 09:05:00', '2026-10-12 09:20:00');

-- ============================================================================
--  6. 导入自检
--     预期：3 / 3 / 8 / 15 / 10
-- ============================================================================
SELECT 'sys_role'        AS tbl, COUNT(*) AS n FROM sys_role
UNION ALL SELECT 'sys_user',        COUNT(*) FROM sys_user
UNION ALL SELECT 'space_resource',  COUNT(*) FROM space_resource
UNION ALL SELECT 'device_resource', COUNT(*) FROM device_resource
UNION ALL SELECT 'reserve_order',   COUNT(*) FROM reserve_order;

-- 场地类型分布，预期 3 / 2 / 2 / 1
SELECT space_type, COUNT(*) AS n FROM space_resource GROUP BY space_type ORDER BY space_type;

-- 设备类型分布，预期 4 / 4 / 3 / 2 / 2
SELECT device_type, COUNT(*) AS n FROM device_resource GROUP BY device_type ORDER BY device_type;

-- 场景 C 前提：基准日 13:00~17:00 应恰好占用 4 台投影仪
SELECT COUNT(*) AS occupied_projectors
FROM reserve_order r
JOIN device_resource d ON JSON_CONTAINS(r.device_ids, JSON_ARRAY(d.id))
WHERE d.device_type = '投影仪'
  AND r.order_status IN (1, 2)
  AND r.start_time < '2026-10-15 17:00:00'
  AND r.end_time   > '2026-10-15 13:00:00';
-- 预期 4。若小于 4，场景 C「设备替代」不再成立。

-- 场景 D 前提：必须返回 0 行
SELECT COUNT(*) AS contradictory_candidates
FROM space_resource
WHERE capacity >= 40 AND budget <= 500;
-- 预期 0。若不为 0，场景 D「需求矛盾」不再成立。

-- ============================================================================
--  7. 重置清理段（默认不执行）
--     需要重新导入时，取消下面的注释后执行，再跑本脚本。
--     注意：DELETE 会连带删除引用这些行的业务数据，仅在开发库使用。
-- ============================================================================
-- SET FOREIGN_KEY_CHECKS = 0;
-- DELETE FROM notify_message  WHERE order_id   BETWEEN 1 AND 100;
-- DELETE FROM repair_ticket   WHERE space_id   BETWEEN 1 AND 100 OR device_id BETWEEN 1 AND 100;
-- DELETE FROM inspect_record  WHERE space_id   BETWEEN 1 AND 100;
-- DELETE FROM reserve_order   WHERE id         BETWEEN 1 AND 10;
-- DELETE FROM device_resource WHERE id         BETWEEN 1 AND 15;
-- DELETE FROM space_resource  WHERE id         BETWEEN 1 AND 8;
-- DELETE FROM sys_user        WHERE id         BETWEEN 1 AND 3;
-- DELETE FROM sys_role        WHERE id         BETWEEN 1 AND 3;
-- SET FOREIGN_KEY_CHECKS = 1;
