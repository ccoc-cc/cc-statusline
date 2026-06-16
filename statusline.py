#!/usr/bin/env python3
# v2.0.0.20250615    Claude Code statusline — 多提供商通用 (DeepSeek/Mimo/...)
import json, re, sys, os, subprocess, time, urllib.request, urllib.error
from datetime import datetime

try:    d = json.loads(sys.stdin.read() or "{}")
except Exception: d = {}

# --- 加载定价配置 ---
PRICE_CFG, PROV_CFG = {}, {}
try:
    with open(os.path.expanduser("~/.claude/statusline_pricing.json")) as f:
        cfg = json.load(f)
    PRICE_CFG = cfg.get("models", {})
    PROV_CFG = cfg.get("providers", {})
except Exception:
    pass

# --- 提取字段 ---
sess_id  = d.get("session_id", "default")                         # 会话 ID
m        = (d.get("model") or {}).get("display_name", "?")        # 模型显示名
ctx      = d.get("context_window") or {}                          # 上下文窗口
pct      = int(ctx.get("used_percentage", 0) or 0)                # 窗口使用比例
in_tok   = ctx.get("total_input_tokens", 0) or 0                  # 输入 token 总数
out_tok  = ctx.get("total_output_tokens", 0) or 0                 # 输出 token 总数
usage    = ctx.get("current_usage") or {}                          # 细粒度 token 分解(含缓存)
fresh_in = usage.get("input_tokens", 0) or 0                      # 非缓存输入 token
cache_cre = usage.get("cache_creation_input_tokens", 0) or 0      # 缓存写入 token(按全价)
cache_rd = usage.get("cache_read_input_tokens", 0) or 0           # 缓存读取 token(按低价)
usage_out = usage.get("output_tokens", 0) or 0                    # 细粒度输出 token
win      = ctx.get("context_window_size", 200000) or 200000       # 窗口总大小
dir_     = (d.get("workspace") or {}).get("current_dir") or d.get("cwd", "?")  # 当前工作目录
cost     = (d.get("cost") or {}).get("total_cost_usd", 0) or 0    # Claude 计费(USD)
dur_ms   = (d.get("cost") or {}).get("total_duration_ms", 0) or 0 # 会话累计耗时(ms)
think    = (d.get("thinking") or {}).get("enabled", False)        # 扩展思考开关
effort   = (d.get("effort") or {}).get("level", "")               # 思考力度等级
rl       = d.get("rate_limits") or {}                             # API 速率限制
fh       = (rl.get("five_hour") or {}).get("used_percentage")     # 5h 限额使用比例
wk       = (rl.get("seven_day") or {}).get("used_percentage")     # 7d 限额使用比例
vim_mode = (d.get("vim") or {}).get("mode", "")                   # vim 模式
pd_      = (d.get("workspace") or {}).get("project_dir") or dir_  # 项目目录
sess_name = d.get("session_name", "")                             # 会话名称
repo     = (d.get("workspace") or {}).get("repo")                 # 仓库信息
lines_add = (d.get("cost") or {}).get("total_lines_added", 0) or 0  # 累计新增行数
lines_rm  = (d.get("cost") or {}).get("total_lines_removed", 0) or 0  # 累计删除行数

# --- 颜色 ---
C, G, Y, R, M, B, D, E = '\033[36m', '\033[32m', '\033[33m', '\033[31m', '\033[35m', '\033[34m', '\033[2m', '\033[0m'

# --- 便捷函数 ---
def ftok(n):  # 格式化 token 数: >=1K 显示 K, 否则显示原值
    return f"{n//1000}K" if n >= 1000 else str(n)

# --- 自适应宽度 ---
try:    cols = int(os.environ.get("COLUMNS", 120))
except Exception: cols = 120
narrow = cols < 100

# --- 累积输出 token 跟踪 (输入不累加, 缓存复用虚高) ---
def accum_out():
    state_file = f"/tmp/cc-statusline-tok-{sess_id}"
    acc, last_fp = 0, ""
    try:
        with open(state_file) as f:
            d = json.loads(f.read())
            acc, last_fp = d["out"], d.get("fp", "")
    except Exception:
        pass
    cur_fp = f"{fresh_in}|{cache_cre}|{cache_rd}|{usage_out}" if usage else ""
    if usage and cur_fp != last_fp:
        acc += usage_out
        last_fp = cur_fp
    try:
        with open(state_file, "w") as f:
            json.dump({"out": acc, "fp": last_fp}, f)
    except Exception:
        pass
    return acc

# --- Git 缓存 (5s, 按 session_id 隔离) ---
cache_file = f"/tmp/cc-statusline-git-{sess_id}"
branch = ""
try:
    st = os.stat(cache_file)
    if time.time() - st.st_mtime > 15: raise FileNotFoundError
    with open(cache_file) as f: branch = f.read().strip()
except FileNotFoundError:
    try:
        r = subprocess.run(["git", "branch", "--show-current"], capture_output=True, text=True,
                           cwd=pd_, timeout=2)
        branch = r.stdout.strip()
    except Exception: branch = ""
    try:
        with open(cache_file, "w") as f: f.write(branch)
    except Exception: pass
git_s = f" ⎇ {branch}" if branch else ""

# --- 币种代码+符号 ---
CCODE = {"CNY": "CN", "USD": "US", "EUR": "EU", "JPY": "JP", "GBP": "UK", "KRW": "KR"}
CUR_SYM = {"CNY": "¥", "USD": "$", "EUR": "€", "JPY": "¥", "GBP": "£", "KRW": "₩"}

# --- 余额后台拉取脚本 (Popen 执行, 脱离主进程) ---
_FETCH_BALANCE = """\
import json, os, sys, urllib.request
e, c, l, ke, ah, ap, rp = sys.argv[1], sys.argv[2], sys.argv[3], sys.argv[4], sys.argv[5], sys.argv[6], sys.argv[7]
k = os.environ.get(ke, "")
if not k:
 try: os.remove(l)
 except Exception: pass
 raise SystemExit(0)
try:
 r = urllib.request.Request(e, headers={ah: ap + k, "Accept":"application/json"})
 with urllib.request.urlopen(r, timeout=10) as resp:
  d = json.loads(resp.read())
 for p in rp.split("."):
  if p.isdigit(): d = d[int(p)]
  else: d = d[p]
 b = str(d) if isinstance(d, (int, float, str)) else "0"
 with open(c,"w") as f: f.write(b)
except Exception: pass
try: os.remove(l)
except Exception: pass
"""

# --- 余额查询 (缓存命中同步返回; 未命中后台拉取 + 立即返回 None) ---
def get_balance(provider):
    if not PROV_CFG or not provider:
        return None
    prov = PROV_CFG.get(provider)
    if not prov:
        return None
    bal = prov.get("balance")
    if not bal:
        return None
    cache_file = f"/tmp/cc-statusline-bal-{sess_id}-{provider}"
    lock_file = f"/tmp/cc-statusline-bal-{sess_id}-{provider}.lock"
    ttl = bal.get("cache_ttl_s", 600)
    if ttl <= 0:
        ttl = 600
    try:
        st = os.stat(cache_file)
        if time.time() - st.st_mtime < ttl:
            with open(cache_file) as f:
                return f.read().strip()
    except FileNotFoundError:
        pass
    # 已有后台任务则跳过
    try:
        lst = os.stat(lock_file)
        if time.time() - lst.st_mtime < 30:
            return None
    except FileNotFoundError:
        pass
    # 检查 key (优先环境变量，回退 ~/.claude.json)
    key_env = bal.get("key_env", "")
    if not key_env:
        return None
    key = os.environ.get(key_env, "")
    if not key:
        try:
            with open(os.path.expanduser("~/.claude.json")) as f:
                key = json.load(f).get("env", {}).get(key_env, "")
        except Exception:
            pass
        if not key:
            try:
                with open(os.path.expanduser("~/.claude.json")) as f:
                    key = json.load(f).get("env", {}).get("ANTHROPIC_AUTH_TOKEN", "")
            except Exception:
                pass
    if not key:
        return None
    # 写锁 + 启动后台拉取
    endpoint = bal.get("endpoint", "")
    if not endpoint:
        return None
    auth_header = bal.get("auth_header", "Authorization")
    auth_prefix = bal.get("auth_prefix", "Bearer ")
    response_path = bal.get("response_path", "balance_infos.0.total_balance")
    try:
        with open(lock_file, "w") as f:
            f.write(str(os.getpid()))
        subprocess.Popen(
            [sys.executable, "-c", _FETCH_BALANCE,
             endpoint, cache_file, lock_file, key_env,
             auth_header, auth_prefix, response_path],
            env={**os.environ, key_env: key},
            start_new_session=True, stdin=subprocess.DEVNULL,
            stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL
        )
    except Exception:
        try:
            os.remove(lock_file)
        except Exception:
            pass
    return None

# 仓库可点击链接
repo_s = ""
if repo:
    host  = repo.get("host", "github.com")
    owner = repo.get("owner", "")
    name  = repo.get("name", "")
    if owner and name:
        url = f"https://{host}/{owner}/{name}"
        repo_s = f" \033]8;;{url}\a{owner}/{name}\033]8;;\a"

# --- 第1行: time | model + vim + thinking/effort | dir (OSC8) | repo | git | session ---
now = datetime.now().strftime('%H:%M')
md = f"[{m}]"
if think:                                     md += " 🧠"
if effort in ("xhigh", "max"):                 md += f" ⚡{effort}"
elif effort and effort != "medium":           md += f"({effort})"
dir_link = f"\033]8;;file://{dir_}\a{dir_}\033]8;;\a"

repo_git = repo_s + git_s
line1 = f"{D}{now}{E} | {C}{md}{E} | {dir_link}"
if repo_git:
    line1 += f" |{repo_git}"
if vim_mode:
    line1 += f" | {B}{vim_mode}{E}"
if lines_add or lines_rm:
    line1 += f" | {G}+{lines_add}{E} {R}-{lines_rm}{E}"

print(line1)

# --- 第2行: context bar + tokens + cost + duration ---
bar_w = 5 if narrow else 10
fill_n = min(pct * bar_w // 100, bar_w)
bar = "█" * fill_n + "░" * (bar_w - fill_n)
bc = R if pct >= 90 else Y if pct >= 70 else G
mins, secs = divmod(dur_ms // 1000, 60)
acc_out = accum_out()                    # 会话累积输出
cache_pct = cache_rd * 100 // (fresh_in + cache_cre + cache_rd or 1) if usage else 0

parts = [
    f"{bc}{bar}{E} {pct}% ({ftok(win)})",
    f"{D}↥{ftok(in_tok)}"
    + (f"({ftok(cache_rd)},{cache_pct}%){E}" if usage and cache_rd else f"{E}")
    + f" {D}↧{ftok(acc_out)}{E}",
]
if not narrow:
    # --- 费用计算 (按模型定价) ---
    model_id = (d.get("model") or {}).get("display_name", "")
    price = PRICE_CFG.get(model_id) or PRICE_CFG.get(re.sub(r'\[.*\]', '', model_id).strip())
    cost_str = None
    cost_cur = "CNY"
    sym = "¥"
    code = "CN"
    provider = ""
    if price:
        # 缓存感知计费: 缓存写入按全价, 缓存读取按低价
        eff_out = usage_out if usage else out_tok
        p_in = price.get("input", 0)
        p_out = price.get("output", 0)
        if usage:
            cost_val = ((fresh_in + cache_cre) * p_in
                        + cache_rd * price.get("cache_input", p_in)
                        + eff_out * p_out) / 1e6
        else:
            cost_val = (in_tok * p_in + eff_out * p_out) / 1e6
        cost_cur = price.get("currency", "CNY")
        sym = CUR_SYM.get(cost_cur, cost_cur)
        code = CCODE.get(cost_cur, cost_cur)
        cost_str = f"💰{code}{sym}{cost_val:.4f}"
        provider = price.get("provider", "deepseek")
    if cost_str:
        parts.append(cost_str)
    else:
        parts.append(f"💰${cost:.2f}")
    # --- 余额 (缓存未命中显示 -，后台异步拉取) ---
    bal = get_balance(provider)
    parts.append(f"💳{code}{sym}{bal}" if bal else "💳-")
parts.append(f"⏱️ {mins}m{secs}s")

print(" | ".join(parts))

# --- 第3行: 速率限制 (仅 sub 用户存在) ---
lims = []
try:
    if fh is not None: lims.append(f"5h: {float(fh):.0f}%")
    if wk is not None: lims.append(f"7d: {float(wk):.0f}%")
except (ValueError, TypeError):
    pass
if lims: print(f"{M}{' '.join(lims)}{E}")
