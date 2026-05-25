# CDK 接码兑换网站

这是基于 `buy_sms.py` 改造的轻量 Web 版本。游客输入 CDK 后先确认服务，确认后下单并等待验证码；管理员可以登录后台批量生成、导出、作废 CDK，并查看订单状态。

## 环境变量

必填：

```bash
export SMSVERIFY_TOKEN="你的平台 API Token"
export ADMIN_PASSWORD="后台密码"
export SESSION_SECRET="随机长字符串"
```

可选：

```bash
export ADMIN_USERNAME="admin"
export SMSVERIFY_COUNTRY="kh"
export SMSVERIFY_PROJECT="chatgpt"
export SMSVERIFY_DATABASE="data/smsverify.db"
export SMSVERIFY_GET_WAIT="30"
export SMSVERIFY_POLL_INTERVAL="5"
export SMSVERIFY_POLL_TIMEOUT="300"
```

## 启动

```bash
uv sync
uv run uvicorn app.main:app --reload
```

浏览器访问：

- 游客兑换页：`http://127.0.0.1:8000/`
- 管理后台：`http://127.0.0.1:8000/admin`

## Docker Compose 部署

准备 `.env`，填入至少这几个变量：

```bash
SMSVERIFY_TOKEN=你的平台 API Token
SMSVERIFY_BASE_URL=你的平台 API 地址
ADMIN_PASSWORD=后台密码
SESSION_SECRET=随机长字符串
```

一键启动：

```bash
docker compose up -d --build
```

查看日志：

```bash
docker compose logs -f smsverify-web
```

停止服务：

```bash
docker compose down
```

SQLite 数据保存在 Docker 命名卷 `smsverify-data`，容器重建不会丢失。

## 测试

```bash
uv run pytest
```
