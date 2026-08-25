# 实现说明

对应设计见 [DESIGN.md](DESIGN.md)。本文按代码现状记录模块、数据、接口和扩展点。

## 1. 运行与目录

```
sms-hall-copilot/
  app/                 FastAPI 应用与引擎
  app/static/          演示 UI
  data/                catalog、用户、评测、知识库、资费、券
  tests/               pytest
  docs/                设计 / 实现 / 架构对照 / 面试提纲
```

启动：`python -m uvicorn app.main:app --reload --port 8765`  
评测：`python -m app.eval_runner --mode heuristic`  
测试：`python -m pytest tests -q`

环境变量见根目录 `.env.example`。`LLM_API_KEY` 为空则分类与列表对齐都不调模型。

## 2. 请求入口

| 方法 | 路径 | 作用 |
|------|------|------|
| GET | `/` | 演示页 |
| GET | `/api/meta` | 短码、演示号码 |
| POST | `/api/sms` | `{msisdn, text}` → 下行、session、trace |
| POST | `/api/reset` | 清会话与运行时用户/券 |
| POST | `/api/eval` | 跑评测集 |
| POST | `/api/config` | 指令草案 |
| POST | `/api/config/intent` | 按接口合同生成新意图 |
| POST | `/api/config/apply` | 人审写入；`draft.kind=new_intent` 走意图落地 |

## 3. 办理主路径

`engine.handle_mo` 顺序：

1. 号码不在 `users.json` → 拒绝。
2. 会话 TTL 120s：若过期前是 `awaiting_select` / `awaiting_confirm`，本轮只回 `session_expired`，不执行该 MO。
3. `awaiting_confirm` → 只接受 Y/N。
4. `awaiting_select` → `flow.handle_offer_select`（资费列表选择）。
5. 空闲态重复 `Y` 且有上一笔成功回执 → 不再调工具。
6. `in_menu` 且目录 5 → 金额 30/50/100/200 进入 `topup` 确认门。
7. `matcher.match_rule`：短码/隐性指令/菜单数字/充值卡 `V`+8 位。
8. 未命中：RAG + `llm.classify` 或 `heuristic.plan`（分类结果经 intent 白名单）。
9. `_dispatch`：菜单、`browse_offers` 流程、out_of_scope、policy、确认门、`tools.run_tool`、模板短信。

会话（`session.py`，TTL 120s）：`idle | in_menu | awaiting_select | awaiting_confirm`。选择态保存 `select_list` 与 `process_id=subscribe_offer`。敏感办理成功后写入 `last_receipt`，空闲态再回 `Y` 只出回执。

短信（`sms.py`）：纯 GSM 7bit 160 字，否则 UCS-2 70 字，超长拆分。

## 4. 模块

| 文件 | 职责 |
|------|------|
| `matcher.py` | 精确指令与菜单，不调模型 |
| `heuristic.py` / `llm.py` | 口语 → intent JSON；分类结果经 `clamp_classify_intent` 白名单 |
| `policy.py` | 套餐、状态、确认集合 `SENSITIVE`、分类允许集 `CLASSIFY_INTENTS` |
| `tools.py` | 单意图 Mock BSS（余额、暂停、VAS、券、自定义意图 Mock） |
| `boss.py` | 下游 Mock：语言、可订购列表、订购 |
| `flow.py` | 资费 2way 编排 |
| `select_match.py` | 列表对齐：规则 → 序数/名称/纠错 → LLM |
| `replies.py` | 模板文案，不让模型写办理结果 |
| `catalog.py` | 读写 `catalog.json` |
| `intents_registry.py` | 读写 `intents.json` |
| `config_assist.py` | 指令草案 + 人审写入命令 |
| `intent_assist.py` | 接口描述+出入参 → 新意图 |
| `eval_runner.py` | 评测 |

自定义意图执行：`tools.has_tool` 查 registry，`run_registered` 返回配置里的 `mock_result`，短信用意图上的模板 `format`。

## 5. 数据文件

| 文件 | 内容 |
|------|------|
| `data/catalog.json` | 运营商、菜单、隐性指令（含 `OFFER`、`GPNT`） |
| `data/users.json` | 四个演示号码（含 003 余额不足、004 BOSS 超时） |
| `data/intents.json` | 配置助手写入的自定义意图 |
| `data/offers.json` | Mock BOSS 可订购资费 1–8 |
| `data/vouchers.json` | 演示卡密 |
| `data/knowledge.md` | RAG 片段（分类/配置约束，不进短信正文） |
| `data/eval_set.json` | 黄金集 |

运行时用户与券在内存 deepcopy，`/api/reset` 或评测每条 case 会重置。订购结果写在用户对象的 `offers` 列表，不回写 JSON 文件。

## 6. 资费 2way 实现要点

1. 指令 `OFFER` 或口语「可订购资费」→ intent `browse_offers`。
2. `start_offer_flow` 依次调 `query_language`、`query_offerable_offers`，列表进 session，下行编号列表。
3. `match_select`：数字按**当前 `select_list` 的原 index**（缩小后仍是 4、7，不是重排成 1、2）；「第 N 个」按当前可见顺序；名称/别名/纠错（`流程`→`流量`）。得分 ≥70 的若有多项 → `reason=ambiguous` + `candidates`，`flow` 把 `select_list` 换成候选并下行 `narrow_select`，不调 LLM 打破平局。唯一命中才进确认。仍完全对不上且启用了 LLM 则 `complete_json`，index 必须落在本轮可见列表。
4. 命中后挂起 `subscribe_offer`，Y 之后 `boss.subscribe_offer(msisdn, offer_id)`。
5. 已订购再选同一档 → `offer_already_on`。完全对不上 → `need_select`，列表不变。
6. 预付订购扣减余额；余额不足 → `insufficient_balance`。用户 `faults.subscribe_offer=boss_timeout`（演示号 004）→ 系统繁忙，不写入已订购。
7. 查询语言/列表若 BOSS 失败，不进入 `awaiting_select`。

评测：`o07` 为 `OFFER`+`本地流量` → `narrow_select`；`o08` 再回 `2`+`Y` 订 10G；`o09` 重复 `Y` 不再调工具；`o10`/`o11` 为余额不足与 BOSS 超时；`t01`–`t05` 为菜单金额充值。

不要在选择态把 `1` 交给菜单匹配：`awaiting_select` 必须在 `match_rule` 之前处理。

## 7. 配置助手实现要点

**指令草案** `draft_config`：检索知识 → 提案（先匹配已注册意图，再内置 hint）→ 占码改派 → policy → verdict。`already_configured` 当请求码已指向同一自定义意图。写入只追加 catalog 命令，不改 BOSS。

**新增意图** `draft_intent_from_api`：解析 JSON 或 `name: type` 行 → 生成 snake_case 意图、Mock、模板。`blocked` 不写。人审后 `append_intent` + `append_command`。LLM 若返回 `out_of_scope` 等保留名，回退启发式命名。

## 8. 扩展新的多接口流程

1. 在 `boss.py`（或同类适配器）增加 Mock 接口，出入参与合同一致。
2. 在 `flow.py` 增加过程：查 → 把列表/槽位写入 session → 等待 → 确认 → 办理。
3. 选择类步骤复用 `select_match.match_select`，禁止模型输出列表外 ID。
4. 入口指令写入 catalog；口语关键词写入 `heuristic.py`。
5. 在 `eval_set.json` 增加：列表展示、编号、名称/错别字、无法识别、确认后才出订购工具、超时/重复确认/余额不足/BOSS 超时。

## 9. 已知边界

- 自定义意图的 Mock 不改用户余额等运行时字段，除非另写工具。
- 配置助手不能从自然语言发明全新 BOSS 编排；多接口流程目前在代码里声明（资费订购），尚未做成可视化流程编辑器。
