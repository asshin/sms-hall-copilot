# HarborTel SMS Hall Copilot

虚构运营商 **HarborTel** 的短信营业厅 AI 作品。业务模式来自运营商短厅的通用做法（短码菜单、隐性指令、2way、Y 确认、预付/后付、下游 BOSS），**不含任何现网代码、号码、菜单或真实接口**。

面试一句话：短厅是有限动作空间。精确指令走规则，口语走意图 JSON，敏感办理必须确认，列表选择只能命中当前 BOSS 返回项，余额和订购结果只来自工具。

## 文档

| 文档 | 内容 |
|------|------|
| [docs/DESIGN.md](docs/DESIGN.md) | 设计：规则优先、确认门、2way、语义对齐、配置人审 |
| [docs/IMPLEMENTATION.md](docs/IMPLEMENTATION.md) | 实现：模块、API、数据、扩展点 |
| [docs/ARCHITECTURE.md](docs/ARCHITECTURE.md) | 与现网短厅概念对照 |
| [docs/INTERVIEW.md](docs/INTERVIEW.md) | 面试 15 问 |
| [PLAN.md](PLAN.md) | 学习计划 |

## 能力

1. **用户短厅**：上行短信 → 规则 / 意图识别 → 会话（菜单、选列表、Y 确认）→ Mock BSS/BOSS → 合规短信 + trace。
2. **多接口资费 2way**：`OFFER` → 查语言 → 查可订购列表 → `1` / `第一个` / `50G本地流程` → `Y` → `msisdn+offer_id` 订购。
3. **配置助手**：指令草案（映射已有意图）或接口描述+出入参生成新意图；人工确认后写入配置，不自动调真实 CRM。

## 快速开始

```powershell
cd d:\work\chmk\sms-hall-copilot
python -m venv .venv
.\.venv\Scripts\Activate.ps1
pip install -r requirements.txt
copy .env.example .env
python -m uvicorn app.main:app --reload --port 8765
```

浏览器打开 http://127.0.0.1:8765

`.env` 里 `LLM_API_KEY` 可留空，走启发式，Demo 可离线。填入 DeepSeek / 通义等 OpenAI 兼容 Key 后，口语分类和列表语义对齐会走模型。

```powershell
python -m pytest tests -q
python -m app.eval_runner --mode heuristic
```

## 演示号码（虚构）

| 号码 | 套餐 | 场景 |
|------|------|------|
| 85259990001 | 预付 / 中文 | 余额、暂停数据、资费订购、游戏积分 `GPNT` |
| 85259990002 | 后付 / 英文 | 账单；不能短厅暂停数据 |
| 85259990003 | 预付 / 中文 | 数据已暂停、余额不足 |

## 建议演示顺序

| 步骤 | 上行 | 期望 |
|------|------|------|
| 精确指令 | `BAL` | 规则命中，余额来自工具 |
| 口语查询 | `帮我查下还剩多少话费` | 意图 `query_balance` |
| 确认门 | `STOP` → `Y` | 先要确认，Y 后才暂停 |
| 套餐门 | 后付号发 `STOP` | 直接拒绝，不进入确认 |
| 列表 2way | `OFFER` → `1` → `Y` | 先查 BOSS 列表，编号订购 |
| 语义选择 | `OFFER` → `第一个` 或 `50G本地流程` → `Y` | 不对编号也能对齐列表项 |
| 选不中 | `OFFER` → `天气` | 提示重选，不订购 |
| 自定义意图 | `GPNT` | 配置助手落地的游戏积分查询 |
| 配置助手 | 页内「新增意图」或「指令草案」 | 人审后才写入 |

## 路由策略

```
精确指令 / 菜单数字 / Y|N / 列表编号     → 规则（不调 LLM）
awaiting_select 且非编号                 → 序数/名称/纠错，必要时 LLM 映射到当前列表
未命中                                   → RAG + 意图 JSON（LLM 或启发式）
敏感意图                                 → 只挂起，等 Y
工具失败 / 模型超时                      → 降级启发式或拒绝，不编造办理结果
```

## 项目结构

```
app/engine.py           会话与分发
app/flow.py             资费 2way
app/select_match.py     列表语义对齐
app/boss.py             Mock 下游 BOSS
app/config_assist.py    指令草案
app/intent_assist.py    按接口合同生成意图
data/eval_set.json      评测集
```
