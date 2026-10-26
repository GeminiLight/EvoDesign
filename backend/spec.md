# EvoDesign Backend 重构规范

## 一、概述

### 1.1 重构目标

将现有的 Express.js + TypeScript 后端服务重构为 FastAPI (Python) 框架，以实现：
- 更好的异步性能和类型安全
- 原生的 OpenAPI/Swagger 文档支持
- 与现有 Python 生态（如 agentic_system）的统一
- 更简洁的代码结构和更快的开发效率

### 1.2 现有架构分析

当前后端是一个典型的 Express.js 应用，包含以下核心模块：

| 模块 | 文件 | 功能 |
|------|------|------|
| 主入口 | `src/index.js` | Express 应用初始化、中间件配置、路由挂载 |
| 认证路由 | `src/routes/auth.js` | OAuth (Google/GitHub)、邮箱登录/注册、JWT 令牌 |
| 图表路由 | `src/routes/diagram.js` | 图表的 CRUD 操作 |
| 用户路由 | `src/routes/user.js` | 用户信息、订阅状态管理 |
| 计费服务 | `src/index.ts` | Stripe 集成、Webhook 处理 |
| 数据库 | `src/db/connection.js` | PostgreSQL/SQLite 双数据库支持 |
| 认证配置 | `src/config/passport.js` | Passport OAuth 策略 |
| JWT 工具 | `src/utils/jwt.js` | 令牌生成与验证 |
| 日志工具 | `src/utils/logger.js` | Winston 日志系统 |

---

## 二、技术选型

### 2.1 核心框架与库

| 用途 | 原技术 (Node.js) | 新技术 (Python) |
|------|------------------|-----------------|
| Web 框架 | Express.js | FastAPI |
| ORM | pg (原生 SQL) | SQLAlchemy 2.0 + asyncpg |
| 数据验证 | 手动校验 | Pydantic v2 |
| 认证 | Passport.js + JWT | python-jose (JWT) + httpx-oauth |
| 异步支持 | async/await | asyncio + async/await |
| 日志 | Winston | Loguru |
| 配置管理 | dotenv | Pydantic Settings |
| API 文档 | 无（需手动） | 内置 OpenAPI/Swagger |

### 2.2 依赖清单

```txt
# requirements.txt
fastapi>=0.109.0
uvicorn[standard]>=0.27.0
sqlalchemy[asyncio]>=2.0.25
asyncpg>=0.29.0
aiosqlite>=0.19.0
pydantic>=2.5.0
pydantic-settings>=2.1.0
python-jose[cryptography]>=3.3.0
passlib[bcrypt]>=1.7.4
httpx-oauth>=0.13.0
httpx>=0.26.0
stripe>=7.10.0
loguru>=0.7.2
python-multipart>=0.0.6
email-validator>=2.1.0
```

---

## 三、项目结构设计

```
backend/
├── app/
│   ├── __init__.py
│   ├── main.py                    # FastAPI 应用入口
│   ├── config.py                  # 配置管理 (Pydantic Settings)
│   │
│   ├── api/
│   │   ├── __init__.py
│   │   ├── deps.py                # 依赖注入 (DB session, 当前用户)
│   │   ├── v1/
│   │   │   ├── __init__.py
│   │   │   ├── router.py          # API v1 路由汇总
│   │   │   ├── endpoints/
│   │   │   │   ├── __init__.py
│   │   │   │   ├── auth.py        # 认证端点
│   │   │   │   ├── diagrams.py    # 图表端点
│   │   │   │   ├── users.py       # 用户端点
│   │   │   │   ├── billing.py     # 计费端点
│   │   │   │   └── health.py      # 健康检查
│   │   │   └── auth/
│   │   │       ├── __init__.py
│   │   │       ├── google.py      # Google OAuth
│   │   │       └── github.py      # GitHub OAuth
│   │
│   ├── core/
│   │   ├── __init__.py
│   │   ├── security.py            # JWT、密码哈希
│   │   ├── exceptions.py          # 自定义异常
│   │   └── middleware.py          # 中间件 (CORS, 限流等)
│   │
│   ├── models/
│   │   ├── __init__.py
│   │   ├── base.py                # SQLAlchemy Base 类
│   │   ├── user.py                # 用户模型
│   │   ├── diagram.py             # 图表模型
│   │   └── subscription.py        # 订阅模型
│   │
│   ├── schemas/
│   │   ├── __init__.py
│   │   ├── user.py                # 用户 Pydantic schemas
│   │   ├── diagram.py             # 图表 Pydantic schemas
│   │   ├── subscription.py        # 订阅 Pydantic schemas
│   │   ├── auth.py                # 认证请求/响应 schemas
│   │   └── common.py              # 通用 schemas (分页等)
│   │
│   ├── services/
│   │   ├── __init__.py
│   │   ├── auth_service.py        # 认证业务逻辑
│   │   ├── diagram_service.py     # 图表业务逻辑
│   │   ├── user_service.py        # 用户业务逻辑
│   │   └── billing_service.py     # Stripe 计费逻辑
│   │
│   └── db/
│       ├── __init__.py
│       ├── session.py             # 数据库会话管理
│       ├── base.py                # Base 类导出
│       └── migrations/            # Alembic 迁移文件
│
├── tests/
│   ├── __init__.py
│   ├── conftest.py                # pytest fixtures
│   ├── test_auth.py
│   ├── test_diagrams.py
│   └── test_users.py
│
├── alembic.ini                    # Alembic 配置
├── requirements.txt
├── pyproject.toml
├── .env.example
└── README.md
```

---

## 四、数据模型设计

### 4.1 SQLAlchemy 模型定义

#### User 模型 (`app/models/user.py`)

```python
from datetime import datetime
from sqlalchemy import String, Text, DateTime, Boolean
from sqlalchemy.orm import Mapped, mapped_column
from app.db.base import Base

class User(Base):
    __tablename__ = "users"

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    email: Mapped[str] = mapped_column(String(255), unique=True, nullable=False, index=True)
    name: Mapped[str | None] = mapped_column(String(255))
    avatar_url: Mapped[str | None] = mapped_column(Text)
    password_hash: Mapped[str | None] = mapped_column(String(255))
    provider: Mapped[str] = mapped_column(String(50), default="email")  # email, google, github
    provider_id: Mapped[str | None] = mapped_column(String(255))
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    # 关联
    diagrams: Mapped[list["Diagram"]] = relationship(back_populates="user", cascade="all, delete-orphan")
    subscription: Mapped["Subscription | None"] = relationship(back_populates="user", uselist=False)
```

#### Diagram 模型 (`app/models/diagram.py`)

```python
from datetime import datetime
from sqlalchemy import String, Text, DateTime, ForeignKey, JSON, Boolean, Integer
from sqlalchemy.orm import Mapped, mapped_column, relationship
from app.db.base import Base

class Diagram(Base):
    __tablename__ = "diagrams"

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id"), nullable=False, index=True)
    request_id: Mapped[str] = mapped_column(String(255), nullable=False)
    diagram_id: Mapped[str] = mapped_column(String(255), nullable=False)
    prompt: Mapped[str] = mapped_column(Text, nullable=False)
    diagram_type: Mapped[str] = mapped_column(String(50), nullable=False)  # flow, architecture, etc.
    style: Mapped[str | None] = mapped_column(String(50))
    summary: Mapped[str | None] = mapped_column(Text)
    excalidraw_payload: Mapped[dict | None] = mapped_column(JSON)
    tldraw_snapshot: Mapped[dict | None] = mapped_column(JSON)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, index=True)

    # 关联
    user: Mapped["User"] = relationship(back_populates="diagrams")
```

#### Subscription 模型 (`app/models/subscription.py`)

```python
from datetime import datetime
from sqlalchemy import String, DateTime, ForeignKey, Boolean
from sqlalchemy.orm import Mapped, mapped_column, relationship
from app.db.base import Base

class Subscription(Base):
    __tablename__ = "subscriptions"

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id"), unique=True, nullable=False)
    status: Mapped[str] = mapped_column(String(50), default="free")  # free, active, canceled, etc.
    price_id: Mapped[str | None] = mapped_column(String(255))
    current_period_end: Mapped[datetime | None] = mapped_column(DateTime)
    stripe_customer_id: Mapped[str | None] = mapped_column(String(255))
    stripe_subscription_id: Mapped[str | None] = mapped_column(String(255), unique=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    # 关联
    user: Mapped["User"] = relationship(back_populates="subscription")
```

---

## 五、API 端点映射

### 5.1 认证端点 (`/auth`)

| 功能 | 原端点 | 新端点 | 方法 |
|------|--------|--------|------|
| Google OAuth 登录 | `/auth/google` | `/api/v1/auth/google` | GET |
| Google OAuth 回调 | `/auth/google/callback` | `/api/v1/auth/google/callback` | GET |
| GitHub OAuth 登录 | `/auth/github` | `/api/v1/auth/github` | GET |
| GitHub OAuth 回调 | `/auth/github/callback` | `/api/v1/auth/github/callback` | GET |
| 邮箱登录 | `/auth/login` | `/api/v1/auth/login` | POST |
| 邮箱注册 | `/auth/register` | `/api/v1/auth/register` | POST |
| 获取当前用户 | `/auth/me` | `/api/v1/auth/me` | GET |

### 5.2 图表端点 (`/api/diagrams`)

| 功能 | 原端点 | 新端点 | 方法 |
|------|--------|--------|------|
| 保存图表 | `/api/diagrams` | `/api/v1/diagrams` | POST |
| 获取图表列表 | `/api/diagrams` | `/api/v1/diagrams` | GET |
| 获取单个图表 | `/api/diagrams/:id` | `/api/v1/diagrams/{id}` | GET |
| 删除图表 | `/api/diagrams/:id` | `/api/v1/diagrams/{id}` | DELETE |

### 5.3 用户端点 (`/api/users`)

| 功能 | 原端点 | 新端点 | 方法 |
|------|--------|--------|------|
| 获取订阅信息 | `/api/users/subscription` | `/api/v1/users/subscription` | GET |
| 更新用户信息 | `/api/users/profile` | `/api/v1/users/profile` | PUT |

### 5.4 计费端点 (`/billing`)

| 功能 | 原端点 | 新端点 | 方法 |
|------|--------|--------|------|
| 创建 Stripe Checkout Session | `/create-checkout-session` | `/api/v1/billing/checkout` | POST |
| 创建 Stripe Portal Session | `/create-portal-session` | `/api/v1/billing/portal` | POST |
| Stripe Webhook | `/webhooks/stripe` | `/api/v1/billing/webhooks/stripe` | POST |

### 5.5 健康检查

| 功能 | 原端点 | 新端点 | 方法 |
|------|--------|--------|------|
| 健康检查 | `/health` | `/health` | GET |

---

## 六、认证流程设计

### 6.1 OAuth 2.0 流程

```
┌─────────────┐     ┌─────────────┐     ┌─────────────┐     ┌─────────────┐
│   Frontend  │     │   FastAPI   │     │   OAuth     │     │  Database   │
└──────┬──────┘     └──────┬──────┘     │  Provider   │     └──────┬──────┘
       │                   │            └──────┬──────┘            │
       │  GET /auth/google │                   │                   │
       │──────────────────>│                   │                   │
       │                   │                   │                   │
       │  302 Redirect     │                   │                   │
       │<──────────────────│                   │                   │
       │                   │                   │                   │
       │  Authorize        │                   │                   │
       │──────────────────────────────────────>│                   │
       │                   │                   │                   │
       │  Callback + code  │                   │                   │
       │<──────────────────────────────────────│                   │
       │                   │                   │                   │
       │  GET /auth/google/callback?code=xxx   │                   │
       │──────────────────>│                   │                   │
       │                   │  Exchange token   │                   │
       │                   │──────────────────>│                   │
       │                   │  Access token     │                   │
       │                   │<──────────────────│                   │
       │                   │                   │                   │
       │                   │  Get user profile │                   │
       │                   │──────────────────>│                   │
       │                   │  Profile data     │                   │
       │                   │<──────────────────│                   │
       │                   │                   │                   │
       │                   │  Upsert user      │                   │
       │                   │──────────────────────────────────────>│
       │                   │                   │                   │
       │  302 Redirect + JWT token             │                   │
       │<──────────────────│                   │                   │
       │                   │                   │                   │
```

### 6.2 JWT 认证中间件

```python
# app/api/deps.py
from fastapi import Depends, HTTPException, status
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials
from sqlalchemy.ext.asyncio import AsyncSession
from app.core.security import verify_token
from app.db.session import get_db
from app.services.user_service import UserService

security = HTTPBearer()

async def get_current_user(
    credentials: HTTPAuthorizationCredentials = Depends(security),
    db: AsyncSession = Depends(get_db)
):
    token = credentials.credentials
    payload = verify_token(token)
    if not payload:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="无效或过期的认证令牌"
        )

    user_service = UserService(db)
    user = await user_service.get_by_id(payload["id"])
    if not user:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="用户不存在"
        )
    return user
```

---

## 七、配置管理

### 7.1 Pydantic Settings 配置类

```python
# app/config.py
from pydantic_settings import BaseSettings
from functools import lru_cache

class Settings(BaseSettings):
    # 应用配置
    app_name: str = "EvoDesign API"
    app_version: str = "1.0.0"
    debug: bool = False

    # 服务器配置
    host: str = "0.0.0.0"
    port: int = 3000

    # 数据库配置
    db_type: str = "sqlite"  # sqlite 或 postgres
    db_host: str = "localhost"
    db_port: int = 5432
    db_name: str = "evodiagram"
    db_user: str = "postgres"
    db_password: str | None = None

    # JWT 配置
    jwt_secret: str = "your-secret-key"
    jwt_algorithm: str = "HS256"
    jwt_expires_in: int = 60 * 60 * 24 * 7  # 7 天

    # OAuth 配置
    google_client_id: str | None = None
    google_client_secret: str | None = None
    google_callback_url: str = "http://localhost:3000/api/v1/auth/google/callback"

    github_client_id: str | None = None
    github_client_secret: str | None = None
    github_callback_url: str = "http://localhost:3000/api/v1/auth/github/callback"

    # Stripe 配置
    stripe_secret_key: str | None = None
    stripe_webhook_secret: str | None = None

    # CORS 配置
    frontend_url: str = "http://localhost:5173"
    cors_origins: list[str] = ["http://localhost:5173"]

    @property
    def database_url(self) -> str:
        if self.db_type == "sqlite":
            return f"sqlite+aiosqlite:///{self.db_name}.db"
        return f"postgresql+asyncpg://{self.db_user}:{self.db_password}@{self.db_host}:{self.db_port}/{self.db_name}"

    class Config:
        env_file = ".env"
        env_file_encoding = "utf-8"

@lru_cache
def get_settings() -> Settings:
    return Settings()
```

---

## 八、中间件设计

### 8.1 CORS 中间件

```python
# app/main.py
from fastapi.middleware.cors import CORSMiddleware

app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_origins,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)
```

### 8.2 请求限流

使用 `slowapi` 库实现：

```python
from slowapi import Limiter, _rate_limit_exceeded_handler
from slowapi.util import get_remote_address
from slowapi.errors import RateLimitExceeded

limiter = Limiter(key_func=get_remote_address)
app.state.limiter = limiter
app.add_exception_handler(RateLimitExceeded, _rate_limit_exceeded_handler)

# 在路由中使用
@app.get("/api/v1/diagrams")
@limiter.limit("100/15minute")
async def list_diagrams(...):
    ...
```

### 8.3 日志中间件

```python
from loguru import logger
from fastapi import Request
import time

@app.middleware("http")
async def log_requests(request: Request, call_next):
    start_time = time.time()
    response = await call_next(request)
    process_time = time.time() - start_time
    logger.info(
        f"{request.method} {request.url.path} - "
        f"{response.status_code} - {process_time:.3f}s"
    )
    return response
```

---

## 九、数据库迁移

### 9.1 Alembic 配置

```bash
# 初始化
alembic init app/db/migrations

# 生成迁移
alembic revision --autogenerate -m "Initial migration"

# 执行迁移
alembic upgrade head
```

### 9.2 现有数据迁移策略

1. **SQLite 数据导出**
   ```bash
   sqlite3 evodiagram.db .dump > backup.sql
   ```

2. **PostgreSQL 数据导入**
   - 使用 `pgloader` 或手动转换 SQL 语法

---

## 十、测试策略

### 10.1 测试框架

- **测试运行器**: pytest
- **异步测试**: pytest-asyncio
- **HTTP 测试**: httpx (TestClient)
- **数据库测试**: 使用内存 SQLite

### 10.2 测试覆盖率目标

- 单元测试: > 80%
- 端到端测试: 核心流程 100%

---

## 十一、部署考虑

### 11.1 进程管理

- **开发环境**: `uvicorn app.main:app --reload`
- **生产环境**: `gunicorn app.main:app -w 4 -k uvicorn.workers.UvicornWorker`

### 11.2 Docker 支持

```dockerfile
FROM python:3.11-slim

WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY . .

EXPOSE 3000

CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "3000"]
```

### 11.3 环境变量

保留与原 Node.js 应用相同的环境变量命名，便于迁移：

```env
NODE_ENV=production
PORT=3000
DB_TYPE=postgres
DB_HOST=...
DB_PASSWORD=...
JWT_SECRET=...
# ... 其他配置
```

---

## 十二、实施步骤

### Phase 1: 基础框架搭建 (1-2 天)
1. 创建项目目录结构
2. 配置 Pydantic Settings
3. 设置 SQLAlchemy 异步连接
4. 实现基础中间件 (CORS, 日志)

### Phase 2: 认证模块 (2-3 天)
1. 实现邮箱登录/注册
2. 实现 JWT 生成与验证
3. 实现 Google OAuth
4. 实现 GitHub OAuth

### Phase 3: 核心业务模块 (2-3 天)
1. 实现图表 CRUD
2. 实现用户信息管理
3. 实现订阅信息查询

### Phase 4: 计费模块 (1-2 天)
1. Stripe Checkout 集成
2. Stripe Portal 集成
3. Webhook 处理

### Phase 5: 测试与文档 (1-2 天)
1. 编写单元测试
2. 编写集成测试
3. OpenAPI 文档验证

### Phase 6: 部署与迁移 (1 天)
1. 数据库迁移
2. 服务部署
3. 监控配置

---

## 十三、风险与注意事项

### 13.1 兼容性风险

| 风险项 | 影响 | 缓解措施 |
|--------|------|----------|
| API 路径变更 | 前端需要同步修改 | 保持与原 API 路径兼容，通过路由前缀区分版本 |
| JWT 格式差异 | 旧 Token 失效 | 使用相同的 JWT secret 和算法 |
| 数据库兼容 | 迁移数据可能出错 | 充分测试迁移脚本，保留备份 |

### 13.2 性能考虑

- FastAPI 的异步特性可提升并发性能
- SQLAlchemy 2.0 的异步支持需要正确使用
- 数据库连接池配置需要根据负载调整

### 13.3 安全注意

- JWT secret 必须使用强随机字符串
- OAuth callback URL 必须与 Provider 配置一致
- Webhook 签名验证必须正确实现

---

## 十四、总结

本重构方案将现有的 Express.js 后端完整迁移至 FastAPI 框架，保持所有核心功能不变，同时利用 Python 生态的优势提供更好的类型安全、API 文档和异步性能。实施过程中需特别注意 API 兼容性和数据迁移的平滑过渡。
