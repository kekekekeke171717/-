# 接口说明 · clinic_triage

> 运行时零第三方依赖，Python 3.9+。
> 所有函数皆纯函数式或只读副作用明确，**无任何函数写回业务系统**。

---

## 0. 安装与导入路径

```bash
pip install -r requirements.txt        # 开发期工具，运行其实不需要
export PYTHONPATH=src                  # Windows: set PYTHONPATH=src
```

```python
from clinic_triage.core.models import Patient, Reason, Suggestion, Metrics
from clinic_triage.core.queue import Config, simulate, snapshot_at, metrics
from clinic_triage.core.rules import RuleContext, evaluate, band_of, score_of
from clinic_triage.core.audit import AuditLog, summary, replay_chain
from clinic_triage.utils import io as io_util, quality, config as cfg_util
```

---

## 1. CLI

```bash
python -m clinic_triage.main <command> [options]
```

| 命令 | 说明 | 主要产物 |
|---|---|---|
| `check` | 数据质量体检 | 控制台输出，不写文件 |
| `snapshot --at 09:20` | 打印某时刻建议队列 | 控制台输出 |
| `demo [--at 09:20]` | 全量回放 | `out/dashboard.html`、`out/suggestions.csv`、`out/replay.json`、`out/audit.jsonl` |
| `serve [--port 8765]` | 本地只读预览 | http://127.0.0.1:8765/dashboard.html |

通用选项：`--data`（CSV 路径）、`--config`（YAML 路径）、`--out`（输出目录）、`--root`（项目根）。

默认 `--at` 取 `config/default.yaml` 中 `simulation.snapshot`。

---

## 2. 数据模型 `core.models`

### `to_minutes(hhmm) -> int`
`"08:30"` → `510`；空串 → `-1`。

### `to_hhmm(minutes) -> str`
`510` → `"08:30"`。

### `Patient`

| 字段 | 类型 | 说明 |
|---|---|---|
| `appt_id` | str | 业务编号（唯一主键，审计追溯用） |
| `dept` | str | 科室 |
| `doctor` | str | 医生 |
| `appt_time` | str | 预约时间 `HH:MM` |
| `checkin_time` | str | 签到时间 `HH:MM`，未到院为空串 |
| `kind` | str | `预约` / `加号` / `回诊` |
| `age` | int | 年龄 |
| `vulnerable` | bool | 脆弱人群标记 |
| `emergency` | bool | 急症标记（**一旦为真强制转人工**） |
| `triage_level` | int | 1 最紧急 … 4 非紧急 |
| `consult_min` | int | 预计接诊分钟数 |
| `note` | str | 现场备注 |

只读属性：`appt_min`、`checkin_min`、`arrived`。

### `Reason`

| 字段 | 类型 | 说明 |
|---|---|---|
| `code` | str | 机器代号，如 `LATE_ARRIVAL` |
| `label` | str | 人读标签 |
| `weight` | int | **仅用于同带内排序**，非风险评分 |
| `evidence` | str | 触发依据，必须可追溯到原记录字段 |
| `action` | str | 建议动作（非指令） |
| `requires_human` | bool | 是否必须人工确认 |

### `Suggestion`

| 字段 | 类型 | 说明 |
|---|---|---|
| `patient` | Patient | 关联记录 |
| `reasons` | list[Reason] | 命中的规则，按权重降序 |
| `score` | int | 带内排序分 |
| `band` | str | `EMERGENCY` / `PRIORITY` / `NORMAL` / `DEFER` |
| `status` | str | `PENDING` / `ACCEPTED` / `REJECTED` / `ESCALATED` |
| `explain` | str | 面向患者的统一解释口径 |
| `order` | int | 同一医生内的建议次序 |

属性：`primary`（主依据标签）、`needs_human`（是否必转人工）。

### `Metrics`

`label / median_wait / p90_wait / avg_wait / max_wait / served / over30_ratio`，
`as_dict()` 产出可 JSON 化的字典（比率已转为百分数）。

---

## 3. 规则引擎 `core.rules`

### `RuleContext`

```python
RuleContext(now_min=600, late_grace_min=15, overrun_min=20,
            vulnerable_age_high=75, vulnerable_age_low=6,
            doctor_delay_min=0, snapshot_version="v0")
```

### `evaluate(p: Patient, ctx: RuleContext) -> list[Reason]`

返回该患者命中的所有理由，按 `weight` 降序。**永不返回涉及临床决策的内容。**

### `band_of(reasons) -> str`

| 条件 | 返回 |
|---|---|
| 含 `EMERGENCY` | `EMERGENCY` |
| 含 `COMEBACK` / `VULNERABLE` | `PRIORITY` |
| 含 `LATE_ARRIVAL` / `WALK_IN` | `DEFER` |
| 其他 | `NORMAL` |

### `score_of(reasons) -> int`

仅当 band 相同时用于排序，**跨带不比分**。

### 规则清单

| code | 触发条件 | 说明 |
|---|---|---|
| `EMERGENCY_FLAG` | `emergency=True` 或 `triage_level<=1` | 强制转人工 |
| `LATE_ARRIVAL` | `checkin - appt > late_grace_min` 且非加号 | 让出波次 |
| `WALK_IN` | `kind == "加号"` | 标注来源 |
| `COMEBACK` | `kind == "回诊"` | 优先复核 |
| `VULNERABLE` | `age>=75` 或 `age<=6` 或 `vulnerable` | 优先复核 |
| `DOCTOR_OVERRUN` | `doctor_delay_min > overrun_min` | 更正预计时段，**不承诺分钟** |
| `NO_SHOW_RISK` | 未签到且超过预约时间 30 分钟 | 列入爽约观察，不自动作废号源 |

---

## 4. 队列回放 `core.queue`

### `Config`

```python
Config.from_dict(raw)      # raw 为 utils.config.load() 的结果
```
字段：`clinic_name, scope, late_grace_min, overrun_min, vulnerable_age_high,
vulnerable_age_low, day_start_min, day_end_min, snapshot_min`。

### `simulate(patients, cfg, policy="fifo") -> tuple[dict, dict]`

按医生分组做离散事件回放。

- 返回 `(events, waits)`：`waits[appt_id]` 为该患者的等待分钟数
- `policy="fifo"`：纯按签到时间（现状基线）
- `policy="assisted"`：按 band 分带 + 带内 score 排序（建议策略）

> ⚠️ `assisted` 提高 tableau 效率的同时会拉长部分 DEFER 患者的等待，
> 这是设计预期 —— 见 `docs/design.md` §3 关于"跨带不比分"的说明。

### `snapshot_at(patients, cfg, policy="assisted", at=None) -> Snapshot`

产出某一时刻的建议队列。

```python
Snapshot(at=600, suggestions=[Suggestion...], counts={...})
```

`counts` 字段：

| 键 | 含义 |
|---|---|
| `total` | 候诊总人数 |
| `emergency` | 急症转人工条数 |
| `priority` | 优先复核条数 |
| `defer` | 让出波次条数 |
| `human` | 需人工复核条数（`needs_human` 为真，含全部 EMERGENCY） |

### `metrics(label, waits) -> Metrics`

从 `waits` 字典算中位 / P90 / 均值 / 最长 / 超 30 分钟占比。

### `render_card(suggestion, ctx, ahead) -> str`

把一条建议渲染成一屏可读文本（含依据、解释口径、前面还有几位）。

---

## 5. 审计 `core.audit`

### `AuditLog(path, snapshot_version="")`

追加写 JSONL。**只记业务编号，不记身份信息，不记口令。**

### `.record(appt_id, action, operator, reason_code, note="") -> dict`

写入一条并返回该条。`action ∈ {"suggest","accept","reject","escalate"}`。
每条自动带 `at`（本地时间）、`snapshot_version`、`prev_status`、`status`。

### `.read() -> list[dict]`

一次性读出全部记录。

### `replay_chain(records, appt_id) -> list[dict]`

按业务编号重建完整处理链路 —— 对应事实 f45 的可重建要求。

### `summary(records) -> dict`

产出汇总：总条数、按 action 分布、按 reason_code 分布、当前状态分布。

### `next_status(action) -> str`

`suggest→PENDING`、`accept→ACCEPTED`、`reject→REJECTED`、`escalate→ESCALATED`。

> 系统**只产出 PENDING**，最终状态只能由人工动作产生。

---

## 6. 工具 `utils`

### `utils.config`

- `load(path=None) -> dict` —— 读 YAML（**零依赖迷你解析器**，只支持本仓库配置用到的子集）
- `loads(text) -> dict` —— 从字符串解析
- `merge(base, override) -> dict` —— 深合并

> 之所以手写解析器而不是引入 PyYAML：保持运行时零依赖。
> 需要完整 YAML 能力时，请在自己项目里替换为 `yaml.safe_load`。

### `utils.io`

- `load_patients(path) -> list[Patient]` —— 读 `data/appointments.csv`（UTF-8-BOM 兼容）
- `write_suggestions(path, suggestions)` —— 写建议清单 CSV
- `write_report(path, payload)` —— 写 JSON
- `render_dashboard(path, ctx)` —— 生成**单文件** HTML 看板（内联 CSS，无外部资源）

`render_dashboard` 的 `ctx` 需包含：

```python
{
  "clinic": str, "snapshot": str, "version": str, "generated": str,
  "suggestions": [Suggestion], "counts": dict,
  "replay": {"fifo": dict, "assisted": dict},   # Metrics.as_dict()
  "quality": [dict],                             # utils.quality.check() 结果
  "rule_counts": dict, "total": int,
}
```

### `utils.quality`

- `check(patients) -> list[dict]` —— 返回问题清单，每项含
  `level`（`阻断`/`提示`/`正常`）、`code`、`message`、`ids`
- `wait_origin_report(patients) -> dict` —— 三套等待口径（到院/签到/预约）的差值报告

被标为 `阻断` 的记录须回原系统修正后才可参与建议计算（事实 f33：
有歧义的记录进入人工修复队列，不进入自动推荐样本）。

---

## 7. 输入 CSV 格式

`data/appointments.csv`，表头（顺序固定，UTF-8 with BOM）：

```
appt_id,dept,doctor,appt_time,checkin_time,kind,age,vulnerable,emergency,triage_level,consult_min,note
A0001,内科门诊,王医生,08:00,07:48,预约,42,0,0,4,8,
```

- 未到院：`checkin_time` 留空
- `vulnerable` / `emergency`：`0`/`1`
- `triage_level`：`1`–`4`
- **不得写入任何患者姓名、身份证、联系方式**（事实 f45：不记录账号口令等敏感信息）

用 `python scripts/gen_data.py` 可重新生成合成样例数据。

---

## 8. 输出文件

| 文件 | 内容 |
|---|---|
| `out/dashboard.html` | 单文件看板：队列分带 + 建议卡 + 边界面板 |
| `out/suggestions.csv` | 建议次序、依据、动作、状态、解释口径 |
| `out/replay.json` | 两套策略的指标、队列计数、规则命中分布、审计汇总 |
| `out/audit.jsonl` | 逐条建议流水，可按 `appt_id` 重建 |

---

## 9. 错误与边界行为

| 情况 | 行为 |
|---|---|
| 签到时间早于预约时间 | 正常，视为提前到院 |
| 签到时间晚于营业结束 | 标记 `WARN`，仍参与计算但注明 |
| `checkin_time` 为空且未过预约时间 | 视为未到院，不进队列 |
| `checkin_time` 为空且已过预约时间 | 触发 `NO_SHOW_RISK`，不自动取消号源 |
| 同一 `appt_id` 重复 | `阻断` 级 `DUPLICATE_CHECKIN`，须人工去重 |
| 快照时刻无候诊者 | `counts["total"] == 0`，正常返回空队列 |
