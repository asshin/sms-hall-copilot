# W3 启发式 vs LLM

填 `.env` 的 `LLM_API_KEY` 后执行：

```powershell
python -m app.eval_runner --mode heuristic
python -m app.eval_runner --mode llm
python -m app.eval_runner --compare
```

实测（DeepSeek `deepseek-v4-flash`，2026-08-13）：

| 模式 | passed/total | 失败 id | 预估费用 | 备注 |
|------|----------------|---------|----------|------|
| heuristic | 44/44 | — | 0 | 不调模型 |
| llm | 44/44 | — | ~$0.0015 | 最后一轮走 LLM 的用例 16 条 |

精确指令两条模式都是 `route=rule`。差异只应出现在口语/安全集；本次评测集上两者打平。
