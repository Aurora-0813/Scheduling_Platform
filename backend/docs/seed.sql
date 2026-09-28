-- ============================================================================
-- 演示种子数据（项目文档 6.9：3 用户 / 8 场地 / 15 设备 / 10 预约）
-- 实际行数：用户 5 行（3 个正常账号 + 2 个演示用异常账号，见 §2）、
--          角色 3 行、场地 8 行、设备 15 行、预约 10 行。
-- ----------------------------------------------------------------------------
-- 用途
--   把刚建好的库填成「打开就能演示」的状态：登录能进、资源列表有数据、
--   预约列表有各种状态、冲突检测与 Agent 有东西可跑。
--
-- 执行方式（**人工执行**，不要交给应用或 CI）
--   mysql --default-character-set=utf8mb4 -h 127.0.0.1 -P 3308 -u <user> -p <db> < docs/seed.sql
--   或：在 Navicat / DBeaver 里打开本文件、选中全部、执行。
--   前置条件：已跑过 `alembic upgrade head`（表与索引都存在）。
--
--   ⚠️ 本文件**不会**由自动化流程执行，也不要在云库以外的库上随手跑：
--      所有语句都在一个事务里，但 `ON DUPLICATE KEY UPDATE` 会**覆盖**
--      id 1..N 上的现有行。它是「演示库初始化」脚本，不是数据迁移脚本。
--
-- 幂等性
--   显式写主键 + `ON DUPLICATE KEY UPDATE`，因此可以重复执行；
--   重复执行的副作用是 `create_time` 保留原值、预约时间按当天重算（见下）。
--
-- 口令（安全相关，必读）
--   三个账号的口令是**占位口令**，写死在本文件里，因此：
--     * 首次部署后**必须立即修改**；
--     * 本文件不要提交到任何公开仓库之外的场合、不要贴到群里/文档里当默认密码用。
--   换口令的方法：`bash scripts/gen_seed_hashes.sh '新口令'` 得到 bcrypt 哈希，
--   再执行 `UPDATE sys_user SET password = '<哈希>' WHERE username = 'admin';`。
--   哈希用 cost=12 生成（与 .env 的 BCRYPT_ROUNDS 一致）；cost 低于 12 时
--   `scripts/gen_seed_hashes.sh` 会给出警告。
--
-- 时间字段为什么用 CURDATE() 算
--   预约单写死日期的话，演示时永远是「过去的预约」，看板上一条进行中的都没有。
--   因此所有时间都相对**执行当天**计算（+1 天、-2 天…），任何一天跑都能得到
--   一批「已完成 / 进行中 / 待开始」齐全的数据。
--
-- 本文件为什么要跳过 sys_permission
--   决策 3：鉴权的权威来源是 `sys_role.permissions`（本文件里的 JSON_ARRAY），
--   `sys_permission` 表降级为前端菜单渲染用的字典，**鉴权不查它**。
--   该字典的内容属于模块 2（前端集成）与菜单设计的一部分，改动它会牵动前端，
--   因此由前端负责人维护，不在这里塞一份可能与页面不同步的副本。
-- ============================================================================

SET NAMES utf8mb4;

START TRANSACTION;

-- ----------------------------------------------------------------------------
-- 1) 角色（sys_role）
--    权限码清单来自 app/core/permissions.py 的 ROLE_PERMISSIONS —— 这里是与
--    代码**逐字一致**的拷贝。结构上要保证 user ⊂ resource_admin ⊂ admin；
--    若哪天改了权限码，请同步本文件（`app/core/permissions.py` 是唯一权威）。
-- ----------------------------------------------------------------------------
INSERT INTO sys_role (id, role_name, permissions) VALUES
(
    1,
    'admin',
    JSON_ARRAY(
        'resource:view', 'order:view', 'order:create', 'order:cancel',
        'agent:schedule', 'agent:view_trace', 'voice:analyze', 'vision:analyze',
        'notify:view', 'inspect:view', 'resource:create', 'resource:update',
        'resource:delete', 'inspect:submit', 'conflict:view', 'conflict:resolve',
        'notify:send', 'order:approve', 'dashboard:view', 'user:view',
        'user:create', 'user:update', 'user:delete', 'user:reset_password',
        'role:assign', 'monitor:view'
    )
),
(
    2,
    'resource_admin',
    JSON_ARRAY(
        'resource:view', 'order:view', 'order:create', 'order:cancel',
        'agent:schedule', 'agent:view_trace', 'voice:analyze', 'vision:analyze',
        'notify:view', 'inspect:view', 'resource:create', 'resource:update',
        'resource:delete', 'inspect:submit', 'conflict:view', 'conflict:resolve',
        'notify:send', 'order:approve', 'dashboard:view'
    )
),
(
    3,
    'user',
    JSON_ARRAY(
        'resource:view', 'order:view', 'order:create', 'order:cancel',
        'agent:schedule', 'agent:view_trace', 'voice:analyze', 'vision:analyze',
        'notify:view', 'inspect:view'
    )
)
ON DUPLICATE KEY UPDATE
    role_name   = VALUES(role_name),
    permissions = VALUES(permissions);
-- 注：`VALUES(col)` 在 MySQL 8.0.20+ 已被标记为过时（仍可用，只提示警告）。
-- 不换成 `AS new` 别名写法是因为它要求 8.0.19+，而这里要兼容 5.7。


-- ----------------------------------------------------------------------------
-- 2) 用户（sys_user）
--    口令哈希与 scripts/gen_seed_hashes.sh 的 SEED_USERS 一一对应：
--      admin    / Admin@123456      （系统管理员）
--      resadmin / ResAdmin@123456   （资源管理员）
--      user01   / User@123456       （普通用户）
--    后面两个是**演示用异常账号**，用于现场演示 40108 / 40302 两个错误分支。
--    它们的口令与 user01 相同（User@123456），这样演示时能说明「密码是对的，
--    拦住你的不是密码」；不要记进任何「可用账号清单」：
--      user02  status=0     → 密码正确也返回 40108（账号已禁用）
--      user03  role_id=NULL → 密码正确但返回 40302（未分配角色）
-- ----------------------------------------------------------------------------
INSERT INTO sys_user (id, username, password, role_id, avatar, status) VALUES
(1, 'admin',
 '$2b$12$DecqRCdJHkcjaoEHiErOsuURL9aSE4kqTPKgvmsEQHIZ/9eq5vnRG', 1, NULL, 1),
(2, 'resadmin',
 '$2b$12$e1bzsSA9GcaTCEFwJHUugOEmzbHMA5i6o/gBf11Wi36N0fZyPzjAm', 2, NULL, 1),
(3, 'user01',
 '$2b$12$MU1JPUO94BzMast5psB8BuP7EzE7SCbcBFyQYosxoyXCqWPsiyAhW', 3, NULL, 1),
(4, 'user02',
 '$2b$12$ky9t5Z8sASn4Q.vJjHxhJux3ncsR37b2OWHDR94J.8IjduXaMX42y', 3, NULL, 0),
(5, 'user03',
 '$2b$12$5IA82t.P9hvK9D7rkjryf.LDM9g77h2IlTtkNktho7ijzmxIoOToa', NULL, NULL, 1)
ON DUPLICATE KEY UPDATE
    password = VALUES(password),
    role_id  = VALUES(role_id),
    status   = VALUES(status);
-- 五个账号的行数、id 与角色是固定的（幂等的前提），因此改口令请用
-- `UPDATE sys_user SET password = ... WHERE username = ...`，不要在这里改 id。
-- `avatar` 全部留 NULL：头像上传属于模块 1/6 的存储路径，演示库不放静态资源。


-- ----------------------------------------------------------------------------
-- 3) 场地（space_resource）8 条
--    space_type：1 会议室 / 2 展厅 / 3 多功能厅 / 4 户外场地
--    capacity 与 space_type 都有索引（文档 6.6），Agent 按类型/容量检索会用到。
-- ----------------------------------------------------------------------------
INSERT INTO space_resource
    (id, space_name, space_type, capacity, location, budget, open_start_time, open_end_time, status)
VALUES
(1, '第一会议室',   1,  10, 'A 座 3 层 301',   200.00, '08:00:00', '22:00:00', 1),
(2, '第二会议室',   1,  20, 'A 座 3 层 302',   350.00, '08:00:00', '22:00:00', 1),
(3, '多功能厅',     3, 120, 'B 座 1 层',      2000.00, '08:00:00', '21:00:00', 1),
(4, '产品展厅',     2,  80, 'B 座 2 层',       800.00, '09:00:00', '18:00:00', 1),
(5, '空中花园',     4,  60, 'C 座 顶楼',       500.00, '07:00:00', '20:00:00', 1),
(6, '路演厅',       1,  50, 'C 座 2 层',       600.00, '08:00:00', '22:00:00', 1),
(7, '培训教室',     1,  40, 'A 座 5 层',       300.00, '08:00:00', '20:00:00', 1),
(8, '篮球场',       4,  30, '室外东区',        NULL,  '06:00:00', '22:00:00', 0)
ON DUPLICATE KEY UPDATE
    space_name      = VALUES(space_name),
    space_type      = VALUES(space_type),
    capacity        = VALUES(capacity),
    location        = VALUES(location),
    budget          = VALUES(budget),
    open_start_time = VALUES(open_start_time),
    open_end_time   = VALUES(open_end_time),
    status          = VALUES(status);
-- 第 8 条 status=0（停用）是**刻意留的**：前端资源列表要能演示「停用场地不展示/
-- 不可预约」，模块 5 的冲突检测也要能跳过停用场地。


-- ----------------------------------------------------------------------------
-- 4) 设备（device_resource）15 条
--    device_status：1 完好 / 2 损坏 / 3 缺失配件
--    total_count 与 available_count 不一致的行，是给「可借数量」与
--    「巡检发现故障」两个场景准备的（模块 3 智能巡检、模块 6 冲突预警）。
-- ----------------------------------------------------------------------------
INSERT INTO device_resource
    (id, device_name, device_type, device_status, total_count, available_count)
VALUES
(1,  '激光投影仪-01',   '投影仪',   1,  2, 2),
(2,  '激光投影仪-02',   '投影仪',   2,  2, 1),
(3,  '全向麦克风-01',   '麦克风',   1,  4, 4),
(4,  '全向麦克风-02',   '麦克风',   1,  4, 3),
(5,  '落地音响-01',     '音响',     1,  2, 2),
(6,  '落地音响-02',     '音响',     3,  2, 1),
(7,  '云台摄像机-01',   '摄像头',   1,  3, 3),
(8,  '云台摄像机-02',   '摄像头',   1,  3, 2),
(9,  '直播一体机',      '直播设备', 1,  1, 1),
(10, '补光灯套装',      '灯光',     1,  4, 4),
(11, '航拍无人机-01',   '无人机',   1,  1, 1),
(12, '航拍无人机-02',   '无人机',   2,  1, 0),
(13, '移动白板',        '白板',     1,  6, 6),
(14, '对讲机套装',      '对讲机',   1,  8, 8),
(15, '会议平板-01',     '会议平板', 1,  2, 2)
ON DUPLICATE KEY UPDATE
    device_name     = VALUES(device_name),
    device_type     = VALUES(device_type),
    device_status   = VALUES(device_status),
    total_count     = VALUES(total_count),
    available_count = VALUES(available_count);


-- ----------------------------------------------------------------------------
-- 5) 预约（reserve_order）10 条
--    order_status：1 待确认 / 2 已确认 / 3 已取消 / 4 已完成
--    device_ids 是 JSON 数组，元素取自上面 15 台设备的 id。
--
--    时间全部相对 CURDATE() 计算：
--      -2 天 ~ -1 天 → 已完成（4）：用于数据洞察面板的历史统计
--      今天          → 已确认（2）：演示「进行中/今日安排」
--      +1 天 ~ +7 天 → 待确认（1）：演示审批流程与冲突检测
--      另有 1 条已取消（3）与 1 条故意**时段重叠**的已确认单，
--      给模块 6 的冲突扫描一个现成的例子（space_id=2 的两条）。
--
--    agent_request 是用户原始自然语言需求，供模块 4 的调度 Agent 回放；
--    agent_trace 留空 —— 追踪结构由模块 4 自己写入（本文件不猜它的格式）。
-- ----------------------------------------------------------------------------
INSERT INTO reserve_order
    (id, user_id, space_id, device_ids, start_time, end_time, order_status, agent_request)
VALUES
(1, 3, 1, JSON_ARRAY(1, 3),
    CURDATE() - INTERVAL 2 DAY + INTERVAL 9 HOUR,
    CURDATE() - INTERVAL 2 DAY + INTERVAL 11 HOUR, 4,
    '帮我订个能坐 10 人的会议室，下周一上午用两小时，要投影仪'),
(2, 3, 7, JSON_ARRAY(13),
    CURDATE() - INTERVAL 1 DAY + INTERVAL 14 HOUR,
    CURDATE() - INTERVAL 1 DAY + INTERVAL 16 HOUR, 4,
    '培训教室下午要放一块移动白板'),
(3, 1, 3, JSON_ARRAY(5, 9, 10),
    CURDATE() - INTERVAL 1 DAY + INTERVAL 19 HOUR,
    CURDATE() - INTERVAL 1 DAY + INTERVAL 21 HOUR, 3,
    '多功能厅昨晚的活动设备需求取消了'),
(4, 3, 2, JSON_ARRAY(1, 3, 5),
    CURDATE() + INTERVAL 9 HOUR,
    CURDATE() + INTERVAL 11 HOUR, 2,
    '今天上午第二会议室，20 人，要投影和音响'),
(5, 2, 2, JSON_ARRAY(2, 4),
    CURDATE() + INTERVAL 10 HOUR,
    CURDATE() + INTERVAL 12 HOUR, 2,
    NULL),
(6, 3, 6, JSON_ARRAY(7, 9, 14),
    CURDATE() + INTERVAL 1 DAY + INTERVAL 10 HOUR,
    CURDATE() + INTERVAL 1 DAY + INTERVAL 12 HOUR, 1,
    '明天上午路演厅要直播，需要云台摄像机和直播一体机'),
(7, 1, 4, JSON_ARRAY(9, 11, 10),
    CURDATE() + INTERVAL 2 DAY + INTERVAL 9 HOUR,
    CURDATE() + INTERVAL 2 DAY + INTERVAL 17 HOUR, 1,
    '产品展厅要拍宣传片，无人机航拍加补光'),
(8, 3, 5, JSON_ARRAY(),
    CURDATE() + INTERVAL 3 DAY + INTERVAL 16 HOUR,
    CURDATE() + INTERVAL 3 DAY + INTERVAL 18 HOUR, 1,
    '空中花园办个小型分享会，不用设备'),
(9, 2, 1, JSON_ARRAY(1),
    CURDATE() + INTERVAL 7 DAY + INTERVAL 9 HOUR,
    CURDATE() + INTERVAL 7 DAY + INTERVAL 10 HOUR, 1,
    '下周同一时间再用一次第一会议室'),
(10, 3, 3, JSON_ARRAY(5, 6, 10),
    CURDATE() + INTERVAL 14 DAY + INTERVAL 18 HOUR,
    CURDATE() + INTERVAL 14 DAY + INTERVAL 21 HOUR, 1,
    '两周后的多功能厅晚场活动，先用音响和补光灯')
ON DUPLICATE KEY UPDATE
    user_id       = VALUES(user_id),
    space_id      = VALUES(space_id),
    device_ids    = VALUES(device_ids),
    start_time    = VALUES(start_time),
    end_time      = VALUES(end_time),
    order_status  = VALUES(order_status),
    agent_request = VALUES(agent_request);

COMMIT;

-- ----------------------------------------------------------------------------
-- 6) 执行结果自查（这几条 SELECT 只读，执行完会打印小结果集）
--    期望行数：用户 5 / 角色 3 / 场地 8 / 设备 15 / 预约 10
-- ----------------------------------------------------------------------------
SELECT 'sys_role'       AS table_name, COUNT(*) AS rows_total FROM sys_role
UNION ALL SELECT 'sys_user',        COUNT(*) FROM sys_user
UNION ALL SELECT 'space_resource',  COUNT(*) FROM space_resource
UNION ALL SELECT 'device_resource', COUNT(*) FROM device_resource
UNION ALL SELECT 'reserve_order',   COUNT(*) FROM reserve_order;

-- 按状态分布（预约）：期望 1=5 条左右、2=2 条、3=1 条、4=2 条
SELECT order_status, COUNT(*) AS rows_total FROM reserve_order GROUP BY order_status;

-- 权限清单是否为空（决策 3：鉴权以 sys_role.permissions 为准）
-- 期望三行都有值；若某行为 NULL 或长度很短，说明上面的角色没插全，
-- 此时登录虽然能成功，但除「权限为空回落静态映射」的角色外会大面积 403。
SELECT id, role_name, JSON_LENGTH(permissions) AS permission_count FROM sys_role;

-- 口令可用性抽查（哈希形状：$2b$12$ + 53 字符）
SELECT id, username, status, role_id, LENGTH(password) AS pwd_len FROM sys_user;
