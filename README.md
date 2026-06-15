# cc-statusline

[![Python 3.8+](https://img.shields.io/badge/python-3.8%2B-blue)](https://www.python.org/)

**Claude Code 三行状态栏** — 模型/目录/git · 上下文/token/费用/余额 · 速率限制

纯 Python 标准库实现，零外部依赖。支持多模型提供商（DeepSeek / Mimo / 自定义），余额异步后台拉取不卡启动。

## 效果

```
12:46 | [deepseek-v4-pro] | /mnt/d/code/project | ⎇ main | +120 -15
███░░░░░░░ 30% (200K) | ↥15K(3K,20%) ↧2K | 💰CN¥0.0123 | 💳CN¥1006 | ⏱️ 3m20s
5h: 45% 7d: 60%
```

### 行说明

| 行 | 内容 |
|----|------|
| 第 1 行 | 时间 \| 模型名 + 思考/力度 \| 当前目录 \| repo 链接 \| git 分支 \| vim 模式 \| ±行数 |
| 第 2 行 | 上下文窗口进度条 \| 输入 token(缓存命中/率) ↧输出累积 \| 💰费用 \| 💳余额 \| ⏱️耗时 |
| 第 3 行 | 5 小时 / 7 天 API 速率限制（仅订阅用户显示） |

终端宽度 <100 列时自动精简。

## 特性

- **多提供商通用** — 配置文件切换 DeepSeek / Mimo / 自定义，不改代码
- **缓存感知计费** — 区分缓存写入（全价）和缓存命中（低价），精确到 0.0001
- **余额异步拉取** — 启动时不阻塞，后台拉取余额，后续刷新自动显示
- **提供商隔离** — 不同提供商的缓存/锁文件完全独立
- **自适应布局** — 窄终端自动隐藏费用/余额列
- **OSC 8 超链接** — 目录和仓库可点击跳转
- **零依赖** — 仅用 Python 标准库（json, subprocess, urllib）

## 安装

```bash
# 1. 复制文件
cp statusline.py ~/.claude/statusline.py
cp statusline_pricing.json ~/.claude/statusline_pricing.json
chmod +x ~/.claude/statusline.py

# 2. 配置 Claude Code
# 编辑 ~/.claude/settings.json，添加：
```

```json
{
  "statusLine": {
    "type": "command",
    "command": "python3 ~/.claude/statusline.py",
    "padding": 0,
    "refreshInterval": 10
  }
}
```

## 配置

编辑 `~/.claude/statusline_pricing.json`。

### 提供商配置

```json
{
  "providers": {
    "deepseek": {
      "balance": {
        "endpoint": "https://api.deepseek.com/user/balance",
        "key_env": "DEEPSEEK_API_KEY",
        "auth_header": "Authorization",
        "auth_prefix": "Bearer ",
        "response_path": "balance_infos.0.total_balance",
        "cache_ttl_s": 600
      }
    },
    "mimo": {
      "balance": null
    }
  },
  "models": {
    "deepseek-v4-pro": {"provider":"deepseek","input":3,"cache_input":0.025,"output":6,"currency":"CNY"},
    "mimo-v2.5-pro":   {"provider":"mimo","input":3,"cache_input":0.025,"output":6,"currency":"CNY"}
  }
}
```

### 字段说明

| 字段 | 说明 |
|------|------|
| `providers.<name>.balance` | 余额 API 配置，设为 `null` 禁用余额查询 |
| `balance.endpoint` | 余额查询 API 端点 |
| `balance.key_env` | API key 环境变量名（如 `DEEPSEEK_API_KEY`） |
| `balance.auth_header` | HTTP 认证头字段名（默认 `Authorization`） |
| `balance.auth_prefix` | token 前缀（默认 `Bearer `，Mimo 用 `api-key` 时为 `""`） |
| `balance.response_path` | JSON 响应中余额值的路径，`.` 分隔（如 `balance_infos.0.total_balance`） |
| `balance.cache_ttl_s` | 余额缓存秒数（默认 600） |
| `models.<id>.provider` | 所属提供商名，对应 `providers` 中的 key |
| `models.<id>.input` | 输入价格（元/百万 token） |
| `models.<id>.cache_input` | 缓存命中价格（元/百万 token） |
| `models.<id>.output` | 输出价格（元/百万 token） |
| `models.<id>.currency` | 货币代码（CNY/USD/EUR/JPY/GBP/KRW） |

### 添加新提供商

只需在 `providers` 和 `models` 中添加条目：

```json
"openai": {
  "balance": {
    "endpoint": "https://api.openai.com/v1/dashboard/billing/credit_grants",
    "key_env": "OPENAI_API_KEY",
    "auth_header": "Authorization",
    "auth_prefix": "Bearer ",
    "response_path": "total_granted",
    "cache_ttl_s": 600
  }
}
```

无余额 API 的提供商设置 `"balance": null`，statusline 显示 `💳-`。

### 设置 API Key

```bash
export DEEPSEEK_API_KEY="sk-..."
export MIMO_API_KEY="sk-..."
```

## 工作原理

1. Claude Code 每隔 `refreshInterval` 秒将当前会话 JSON 通过 stdin 管道传入脚本
2. 脚本解析 JSON → 提取模型/上下文/token/费用等字段 → 输出 1~3 行纯文本
3. 余额查询采用异步模式：首次/缓存过期时后台拉取 + 立即返回 `-`，下次刷新自动显示

## 兼容性

- **Claude Code** ≥ 1.0（通过 `statusLine` 配置项）
- **Python** ≥ 3.8
- **OS** Linux / macOS / WSL2
