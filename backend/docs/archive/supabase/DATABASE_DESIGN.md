# Supabase 数据库设计文档

## 概述

本文档详细说明了 Smart Excalidraw React 项目的历史 Supabase 数据库设计。数据库采用 PostgreSQL，利用 Supabase 的 Row Level Security (RLS) 确保数据安全。

> 归档说明：当前 FastAPI 运行时数据库 schema 由 `backend/app/db/bootstrap.py` 和 SQLAlchemy models 维护；本目录下 SQL 仅作为历史 Supabase 方案参考。

## 数据库版本

- **版本**: 1.0
- **创建日期**: 2026-02-09
- **初始化脚本**: `backend/docs/archive/supabase/002_complete_schema.sql`

---

## 表结构详解

### 1. `profiles` - 用户扩展信息

补充 `auth.users` 的基础信息，存储用户的额外资料和配额信息。

| 字段 | 类型 | 说明 | 约束 |
|------|------|------|------|
| `id` | uuid | 用户 ID（主键） | FK → auth.users |
| `email` | text | 邮箱地址 | NOT NULL |
| `full_name` | text | 全名 | - |
| `avatar_url` | text | 头像 URL | - |
| `bio` | text | 个人简介 | - |
| `tier` | text | 用户等级 | NOT NULL, DEFAULT 'free' |
| `usage_quota_monthly` | integer | 每月生成配额 | NOT NULL, DEFAULT 50 |
| `usage_quota_used` | integer | 已使用配额 | NOT NULL, DEFAULT 0 |
| `preferences` | jsonb | 用户偏好设置 | DEFAULT '{}' |
| `created_at` | timestamptz | 创建时间 | NOT NULL, DEFAULT now() |
| `updated_at` | timestamptz | 更新时间 | NOT NULL, DEFAULT now() |

**tier 枚举值**:
- `free`: 免费用户（每月 50 次生成）
- `pro`: Pro 用户（每月 500 次生成）
- `enterprise`: 企业用户（无限配额）

**索引**:
- `profiles_tier_idx`: 按等级查询
- `profiles_email_idx`: 按邮箱查询

**RLS 策略**:
- 用户可以查看和更新自己的 profile

---

### 2. `diagrams` - 图表数据

存储用户生成的所有图表，包括 Excalidraw 和 TLDraw 格式。

| 字段 | 类型 | 说明 | 约束 |
|------|------|------|------|
| `id` | uuid | 记录 ID（主键） | - |
| `user_id` | uuid | 用户 ID | FK → auth.users |
| `request_id` | text | 请求 ID | NOT NULL |
| `diagram_id` | text | 图表唯一标识 | NOT NULL |
| `prompt` | text | 用户输入的提示词 | NOT NULL |
| `diagram_type` | text | 图表类型 | NOT NULL |
| `style` | text | 图表风格 | NOT NULL |
| `summary` | text | 图表摘要 | - |
| `excalidraw_payload` | jsonb | Excalidraw JSON 数据 | - |
| `tldraw_snapshot` | jsonb | TLDraw 快照 | - |
| `preview_image_url` | text | 预览图 URL | - |
| `is_public` | boolean | 是否公开 | NOT NULL, DEFAULT false |
| `is_template` | boolean | 是否作为模板 | NOT NULL, DEFAULT false |
| `tags` | text[] | 标签数组 | DEFAULT '{}' |
| `metadata` | jsonb | 额外元数据 | DEFAULT '{}' |
| `view_count` | integer | 查看次数 | NOT NULL, DEFAULT 0 |
| `fork_count` | integer | 被复刻次数 | NOT NULL, DEFAULT 0 |
| `created_at` | timestamptz | 创建时间 | NOT NULL |
| `updated_at` | timestamptz | 更新时间 | NOT NULL |

**diagram_type 枚举值**:
- `flow`: 流程图
- `architecture`: 架构图
- `sequence`: 时序图
- `er`: ER 图
- `mindmap`: 思维导图
- `network`: 网络拓扑图
- `automated`: 自动识别

**style 枚举值**:
- `neutral`: 中性风格
- `playful`: 活泼风格
- `technical`: 技术风格
- `minimal`: 极简风格

**索引**:
- `diagrams_user_id_idx`: 按用户查询
- `diagrams_type_idx`: 按类型查询
- `diagrams_is_public_idx`: 按公开状态查询
- `diagrams_created_at_idx`: 按创建时间排序
- `diagrams_tags_idx`: 标签 GIN 索引
- `diagrams_prompt_idx`: 提示词全文搜索索引

**RLS 策略**:
- 用户可以增删改查自己的图表
- 所有人可以查看公开图表

---

### 3. `subscriptions` - 订阅信息

存储用户的 Stripe 订阅状态。

| 字段 | 类型 | 说明 | 约束 |
|------|------|------|------|
| `id` | uuid | 记录 ID（主键） | - |
| `user_id` | uuid | 用户 ID（唯一） | FK → auth.users |
| `status` | text | 订阅状态 | NOT NULL, DEFAULT 'free' |
| `price_id` | text | Stripe Price ID | - |
| `product_name` | text | 产品名称 | - |
| `current_period_start` | timestamptz | 当前周期开始 | - |
| `current_period_end` | timestamptz | 当前周期结束 | - |
| `cancel_at_period_end` | boolean | 周期结束后取消 | NOT NULL, DEFAULT false |
| `stripe_customer_id` | text | Stripe Customer ID | - |
| `stripe_subscription_id` | text | Stripe Subscription ID（唯一） | - |
| `cancel_url` | text | 取消订阅 URL | - |
| `update_url` | text | 更新订阅 URL | - |
| `created_at` | timestamptz | 创建时间 | NOT NULL |
| `updated_at` | timestamptz | 更新时间 | NOT NULL |

**status 枚举值**:
- `free`: 免费用户
- `trial`: 试用中
- `active`: 活跃订阅
- `past_due`: 逾期
- `canceled`: 已取消
- `unpaid`: 未支付

**索引**:
- `subscriptions_user_id_idx`: 按用户查询
- `subscriptions_status_idx`: 按状态查询
- `subscriptions_stripe_customer_idx`: 按 Stripe Customer ID 查询

**RLS 策略**:
- 用户可以查看自己的订阅信息

---

### 4. `diagram_templates` - 图表模板库

存储系统预置和用户贡献的图表模板。

| 字段 | 类型 | 说明 | 约束 |
|------|------|------|------|
| `id` | uuid | 模板 ID（主键） | - |
| `name` | text | 模板名称 | NOT NULL |
| `description` | text | 模板描述 | - |
| `diagram_type` | text | 图表类型 | NOT NULL |
| `category` | text | 模板分类 | NOT NULL |
| `excalidraw_payload` | jsonb | Excalidraw 数据 | - |
| `tldraw_snapshot` | jsonb | TLDraw 快照 | - |
| `preview_image_url` | text | 预览图 URL | - |
| `is_featured` | boolean | 是否精选 | NOT NULL, DEFAULT false |
| `is_official` | boolean | 是否官方模板 | NOT NULL, DEFAULT true |
| `usage_count` | integer | 使用次数 | NOT NULL, DEFAULT 0 |
| `created_by` | uuid | 创建者 | FK → auth.users |
| `created_at` | timestamptz | 创建时间 | NOT NULL |
| `updated_at` | timestamptz | 更新时间 | NOT NULL |

**category 枚举值**:
- `business`: 商业
- `engineering`: 工程
- `education`: 教育
- `design`: 设计
- `other`: 其他

**索引**:
- `diagram_templates_type_idx`: 按类型查询
- `diagram_templates_category_idx`: 按分类查询
- `diagram_templates_is_featured_idx`: 按精选状态查询

**RLS 策略**:
- 所有人可以查看模板
- 认证用户可以创建自定义模板

---

### 5. `collaborations` - 协作权限

管理图表的协作权限。

| 字段 | 类型 | 说明 | 约束 |
|------|------|------|------|
| `id` | uuid | 记录 ID（主键） | - |
| `diagram_id` | uuid | 图表 ID | FK → diagrams |
| `user_id` | uuid | 协作用户 ID | FK → auth.users |
| `role` | text | 角色权限 | NOT NULL, DEFAULT 'viewer' |
| `invited_by` | uuid | 邀请人 ID | FK → auth.users |
| `created_at` | timestamptz | 创建时间 | NOT NULL |

**role 枚举值**:
- `viewer`: 仅查看
- `editor`: 可编辑
- `owner`: 所有者

**索引**:
- `collaborations_diagram_id_idx`: 按图表查询
- `collaborations_user_id_idx`: 按用户查询
- `collaborations_diagram_user_idx`: 图表-用户唯一索引

**RLS 策略**:
- 用户可以查看自己参与的协作
- 用户可以查看自己拥有图表的协作

---

### 6. `usage_logs` - 使用日志

记录用户的 API 使用情况，用于计费和配额管理。

| 字段 | 类型 | 说明 | 约束 |
|------|------|------|------|
| `id` | uuid | 记录 ID（主键） | - |
| `user_id` | uuid | 用户 ID | FK → auth.users |
| `action_type` | text | 操作类型 | NOT NULL |
| `resource_type` | text | 资源类型 | NOT NULL |
| `resource_id` | text | 资源 ID | - |
| `metadata` | jsonb | 额外信息 | DEFAULT '{}' |
| `created_at` | timestamptz | 创建时间 | NOT NULL |

**action_type 枚举值**:
- `generate_diagram`: 生成图表
- `optimize_arrows`: 优化箭头
- `measure_difficulty`: 测量难度

**resource_type 枚举值**:
- `diagram`: 图表
- `api_call`: API 调用

**索引**:
- `usage_logs_user_id_idx`: 按用户查询
- `usage_logs_action_type_idx`: 按操作类型查询
- `usage_logs_created_at_idx`: 按时间排序

**RLS 策略**:
- 用户可以查看自己的使用日志

---

## 视图

### 1. `diagram_stats` - 图表统计视图

聚合用户的图表统计数据。

| 字段 | 类型 | 说明 |
|------|------|------|
| `user_id` | uuid | 用户 ID |
| `total_diagrams` | bigint | 图表总数 |
| `public_diagrams` | bigint | 公开图表数 |
| `template_diagrams` | bigint | 模板图表数 |
| `total_views` | bigint | 总查看次数 |
| `total_forks` | bigint | 总复刻次数 |
| `last_created_at` | timestamptz | 最后创建时间 |

### 2. `user_quota` - 用户配额视图

显示用户的配额使用情况和订阅状态。

| 字段 | 类型 | 说明 |
|------|------|------|
| `user_id` | uuid | 用户 ID |
| `tier` | text | 用户等级 |
| `usage_quota_monthly` | integer | 每月配额 |
| `usage_quota_used` | integer | 已使用配额 |
| `remaining_quota` | integer | 剩余配额 |
| `subscription_status` | text | 订阅状态 |
| `current_period_end` | timestamptz | 当前周期结束 |
| `current_period_start` | timestamptz | 当前周期开始 |

---

## 函数

### 1. `check_and_deduct_quota(p_user_id, p_amount)`

检查并扣除用户配额。

**参数**:
- `p_user_id`: 用户 ID
- `p_amount`: 扣除数量（默认 1）

**返回值**:
- `boolean`: 是否成功扣除

**逻辑**:
1. 获取用户配额信息
2. Enterprise 用户不受配额限制
3. 检查配额是否足够
4. 扣除配额并返回结果

**使用示例**:
```sql
SELECT public.check_and_deduct_quota('user-uuid', 1);
```

### 2. `search_diagrams(p_search_query, p_diagram_type, p_limit)`

搜索公开图表。

**参数**:
- `p_search_query`: 搜索关键词
- `p_diagram_type`: 图表类型（可选）
- `p_limit`: 返回数量（默认 20）

**返回值**:
- 包含匹配图表的表

**搜索范围**:
- 提示词全文搜索
- 标签匹配
- 图表 ID 匹配

**使用示例**:
```sql
SELECT * FROM public.search_diagrams('architecture', 'architecture', 10);
```

---

## 触发器

### 1. `on_auth_user_created`

当新用户注册时，自动创建对应的 `profiles` 记录。

### 2. `update_profiles_updated_at`

更新 `profiles` 表的 `updated_at` 字段。

### 3. `update_diagrams_updated_at`

更新 `diagrams` 表的 `updated_at` 字段。

### 4. `update_subscriptions_updated_at`

更新 `subscriptions` 表的 `updated_at` 字段。

### 5. `update_diagram_templates_updated_at`

更新 `diagram_templates` 表的 `updated_at` 字段。

---

## 扩展

数据库启用了以下 PostgreSQL 扩展：

1. **uuid-ossp**: UUID 生成
2. **pg_trgm**: 模糊搜索
3. **btree_gin**: JSONB 索引优化

---

## 初始化步骤

### 1. 创建 Supabase 项目

1. 访问 [Supabase Dashboard](https://supabase.com/dashboard)
2. 创建新项目
3. 等待数据库初始化完成

### 2. 执行 SQL 脚本

1. 在 Supabase Dashboard 中进入 SQL Editor
2. 复制 `backend/docs/archive/supabase/002_complete_schema.sql` 的内容
3. 点击 "Run" 执行脚本

### 3. 配置认证

在 Supabase Dashboard → Authentication → URL Configuration:

- **Site URL**: 你的前端域名（如 `https://yourdomain.com`）
- **Redirect URLs**: 添加 `https://yourdomain.com/**`

### 4. 配置 OAuth（可选）

#### Google OAuth

1. 在 [Google Cloud Console](https://console.cloud.google.com/) 创建 OAuth Client ID
2. 授权重定向 URI: `https://<project-ref>.supabase.co/auth/v1/callback`
3. 将 Client ID 和 Secret 填入 Supabase Dashboard

#### GitHub OAuth

1. 在 [GitHub Developer Settings](https://github.com/settings/developers) 创建 OAuth App
2. 授权回调 URL: `https://<project-ref>.supabase.co/auth/v1/callback`
3. 将 Client ID 和 Secret 填入 Supabase Dashboard

---

## 权限说明

### Row Level Security (RLS)

所有表都启用了 RLS，确保：

- 用户只能访问自己的数据
- 公开数据可以被所有人访问
- 协作数据可以被协作者访问

### 函数权限

认证用户可以执行以下函数：

- `check_and_deduct_quota`: 检查和扣除配额
- `search_diagrams`: 搜索公开图表

---

## 数据备份

建议定期备份数据库：

1. 在 Supabase Dashboard → Database → Backups
2. 配置自动备份策略
3. 设置保留时间

---

## 性能优化

### 索引策略

- 所有外键字段都有索引
- 常用查询字段有索引
- JSONB 和数组字段使用 GIN 索引
- 全文搜索使用 TSVector 索引

### 查询优化

- 使用视图简化复杂查询
- 使用函数封装业务逻辑
- 使用索引加速常用查询

---

## 安全建议

1. **启用 RLS**: 所有表都应启用 RLS
2. **限制 API Key**: 使用最小权限原则
3. **定期审计**: 定期检查用户和权限
4. **加密传输**: 始终使用 HTTPS
5. **日志监控**: 启用查询日志监控

---

## 常见问题

### Q: 如何重置用户配额？

A: 可以通过 Supabase Dashboard 直接修改 `profiles.usage_quota_used` 字段，或创建定时任务每月自动重置。

### Q: 如何导出数据？

A: 在 Supabase Dashboard → Database → Export 可以导出整个数据库或特定表。

### Q: 如何扩展数据库？

A: 根据使用情况升级 Supabase 项目的套餐，或考虑自托管 PostgreSQL。

---

## 更新日志

### v1.0 (2026-02-09)

- 初始版本
- 创建 6 个核心表
- 创建 2 个视图
- 创建 2 个函数
- 启用 RLS 策略
- 添加示例数据
