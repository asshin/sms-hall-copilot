# HarborTel SMS Hall Copilot

虚构运营商 **HarborTel** 的短信营业厅 AI 作品。业务模式来自运营商短厅的通用做法（短码菜单、隐性指令、2way 二次确认、预付/后付差异），**不含任何现网代码、号码、菜单或接口**。

面试一句话：短厅是有限动作空间的生产系统。精确指令走规则，口语走模型，敏感办理必须确认，余额只来自工具。

## 两个能力

1. **用户短厅助手**：上行短信 → 规则匹配 / 意图识别 → 会话确认 → Mock BSS → 合规短信。
2. **配置助手**：自然语言需求 → 隐性指令/菜单草案 → 指令冲突与漏确认检查。

对应现网链路的讲法见 [docs/ARCHITECTURE.md](docs/ARCHITECTURE.md)，面试稿见 [docs/INTERVIEW.md](docs/INTERVIEW.md)。学习计划见 [PLAN.md](PLAN.md)。

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

无 API Key 时使用启发式意图识别，Demo 可离线跑。接入 DeepSeek / 通义等 OpenAI 兼容接口后，把 `.env` 里的 `LLM_API_KEY` 填上即可对比正确率。

```powershell
python -m app.eval_runner
```

## 演示账号（虚构）

| 号码 | 套餐 | 场景 |
|------|------|------|
| 85259990001 | 预付 | 有余额、可暂停数据 |
| 85259990002 | 后付 | 英文；不能办预付专属关停 |
| 85259990003 | 预付 | 数据已暂停、余额不足 |

试一条精确指令：`BAL`。再试一句口语：`帮我查下还剩多少话费`。再试敏感操作：`暂停数据` → 应先要 `Y` 确认。

## 路由策略

```
精确指令 / 菜单数字 / Y|N 确认  → 规则引擎（不调 LLM）
未命中                          → RAG + 意图结构化输出
敏感意图                        → 只挂起，等确认
工具失败 / 模型超时             → 菜单兜底，不编造办理结果
```
