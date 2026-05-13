---
name: docker-compose-db-auth-troubleshoot
description: Troubleshoot Docker Compose application database authentication failures and password/login issues. Use when applications fail to connect to PostgreSQL/MySQL or when login credentials don't work after password resets.
license: MIT
---

# Docker Compose 数据库认证问题排查

## 适用场景
- Docker Compose 应用无法连接数据库（PostgreSQL/MySQL）
- 密码重置后仍无法登录
- 数据库认证失败错误（`password authentication failed`）
- 怀疑 `.env` 文件中的密码被截断或损坏

## 诊断流程

### 1. 检查应用日志确认错误类型
```bash
# 查看应用容器日志中的数据库连接错误
docker logs --tail 50 <app_container> 2>&1 | grep -i "password\|authentication\|database"
```

**常见错误模式：**
- `pq: password authentication failed for user "xxx"` - PostgreSQL 密码错误
- `acquire migrations lock: pq: password authentication failed` - 数据库密码不匹配导致迁移锁定

### 2. 验证 .env 文件密码完整性
```bash
# 检查密码是否被截断（显示 ... 表示有问题）
grep "^POSTGRES_PASSWORD=" .env

# 使用 xxd 检查二进制内容（确认没有隐藏字符或被截断）
sudo xxd .env | grep -B 2 "b2f382"
```

**⚠️ 常见问题**：长密码在 `.env` 文件中被截断为 `xxx...xxx` 格式，导致认证失败。

### 3. 检查运行容器的环境变量
```bash
# 查看容器实际使用的环境变量（确认与 .env 一致）
docker exec <postgres_container> env | grep POSTGRES_PASSWORD
docker inspect <app_container> | grep -A 5 "Env"
```

### 4. 修复 .env 文件中的密码

如果密码被截断，需要完整重写：
```bash
# 方法1: 使用 sed 替换（注意特殊字符）
sudo sed -i 's~POSTGRES_PASSWORD=.*~POSTGRES_PASSWORD=完整密码~' /path/to/.env

# 方法2: 使用 Python 脚本（更可靠）
sudo python3 << 'PYEOF'
import re
with open('/path/to/.env', 'r') as f:
    content = f.read()
new_content = re.sub(
    r'POSTGRES_PASSWORD=[^\s#]+',
    'POSTGRES_PASSWORD=完整密码',
    content
)
with open('/path/to/.env', 'w') as f:
    f.write(new_content)
PYEOF
```

### 5. 完全重启 Docker Compose 栈

**重要**：仅 `docker compose restart` 不会重新加载修改后的 `.env` 文件，必须 down/up：
```bash
cd /path/to/docker-compose
docker compose down
docker compose up -d
```

### 6. 验证服务健康状态
```bash
# 检查容器是否 healthy
docker ps

# 测试应用 API 响应
curl -s http://localhost:8081/health
```

### 7. 修复应用层密码（如登录密码）

如果数据库连接正常但用户登录失败：

```bash
# 生成正确的 bcrypt hash（用于 PostgreSQL 用户表）
htpasswd -nbB "" "新密码" | cut -d: -f2

# 在数据库中更新密码
docker exec <postgres_container> psql -U <user> -d <db> -c "
UPDATE users 
SET password_hash='\$2y\$05\$...生成的hash' 
WHERE id=1;
"
```

**注意**：bcrypt hash 中的 `$` 在 SQL 中需要转义为 `\$`。

## 验证登录
```bash
# 测试 API 登录端点
curl -sX POST "http://localhost:8081/api/v1/auth/login" \
  -H "Content-Type: application/json" \
  -d '{"email":"admin@example.com","password":"新密码"}'
```

## 常见陷阱
1. **想当然地认为 restart 会重载 env**：修改 `.env` 后必须 `down/up`，`restart` 不会重新读取环境变量
2. **密码显示被截断**：终端可能截断长密码显示，用 `xxd` 或 `wc -c` 验证实际长度
3. **bcrypt 格式错误**：手动修改 hash 时要确保格式正确，建议使用 `htpasswd -nbB` 生成
4. **特殊字符转义**：bcrypt hash 中的 `$` 在 SQL/bash 中需要转义

## 成功标志
- `docker logs <app>` 不再显示认证错误
- API 返回 `{"code":0,"message":"success",...}`
- Access Token 正常返回