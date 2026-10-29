# 贡献指南

感谢你愿意花时间看这个项目。它很小，但规矩很明确 ——
因为它的每一行代码最终要出现在护士站的一块屏幕上，而那块屏幕前有人在排队。

## 一、先说红线（改之前必读）

本项目有几条约束来自真实访谈，是**不可协商**的，PR 里违反任何一条都会被直接拒：

| 编号 | 红线 | 为什么 |
|---|---|---|
| R1 | 任何情况下**不得写回** HIS / 预约平台 / 叫号系统 | 事实 f32：只读排班和队列 |
| R2 | **急症一律转人工**，算法不得输出临床结论 | 事实 f40 / f42 |
| R3 | 每条建议**必须带可追溯依据**（原始字段 + 快照版本） | 事实 f15 / f45 |
| R4 | 有歧义的记录**只能进人工队列**，不得进自动建议 | 事实 f33 |
| R5 | 不同角色的等待时间口径**必须分别记录，不得合并或择优** | 事实 f50 / f53 |
| R6 | 禁止因"节省工时"在财务口径上夸大收益 | 事实 f03 |

判断不了的，在 Issue 里先问。**先讨论，再写代码。**

## 二、开发准备

```bash
git clone https://github.com/<your-account>/clinic-triage-copilot.git
cd clinic-triage-copilot
python -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt

pytest -q                          # 测试必须全绿
python -m clinic_triage.main demo  # 跑一遍确认 out/ 正常产出
```

运行时**零第三方依赖**（只用标准库），请保持这一点。`requirements.txt`
里只能是开发期工具（pytest / ruff / mypy）。

## 三、代码规范

- Python 3.9+ 语法，类型注解用 `from __future__ import annotations`
- 行宽 88（`ruff check` 默认配置）
- 中文文档字符串，注释说明**为什么**而不是"这行做了什么"
- 新增规则必须在 `core/rules.py` 中实现 `Reason(code, label, weight, evidence, action, explain)`
  六要素齐全：**没有 evidence 的规则不会被合并**
- 所有对外的字符串 glossary（给患者的解释口径）集中在 `explain` 字段，不要在渲染层拼

## 四、提交流程

1. Fork 并新建分支：`git checkout -b feat/<一句话>` 或 `fix/<一句话>`
2. 小步提交，提交信息用中文，格式：`类型(范围): 简述`
   - 类型：`feat` / `fix` / `docs` / `refactor` / `test` / `chore`
   - 例：`feat(rules): 增加检查交接超时提示规则`
3. PR 描述里请回答三个问题：
   - 改了什么？
   - 对应哪条业务事实（编号见 `docs/业务挖掘与需求洞察.md`）？
   - 如何验证？（贴 `pytest` 或 `demo` 输出）
4. CI 通过后由维护者合并。**红线相关的改动需要至少一位具备医疗信息化背景的 reviewer 复核。**

## 五、报告问题

开 Issue 时请附：

- 版本号 / commit hash
- 复现命令与完整输出（去掉任何真实信息）
- 期望行为 vs 实际行为
- **如果是业务规则问题，请说明它违反或应该对应哪条事实编号**

安全与合规相关问题请私下联系维护者，不要在公开 Issue 中讨论。

## 六、许可证

你提交的任何 Contribution 默认以 Apache-2.0 许可，与本仓库保持一致。
