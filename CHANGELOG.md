# 变更记录

本项目所有版本遵循 [语义化版本](https://semver.org/lang/zh-CN/) `MAJOR.MINOR.PATCH`。

## [0.2.0] — 2026-10-31

把已经跑通的 MVP 整理成一套能拿去答辩的材料：23 页演示稿加逐页讲稿。

### 新增

- `docs/答辩演示.pptx` — 23 页。文本是文本框、数据是表格、流程是矢量图，
  全部原生可编辑，不是截图拼出来的页面
- `docs/答辩演讲稿.md` / `.docx` — 逐页讲稿，带时间预算（合计约 16 分 40 秒）
  和 15 分钟版本的裁剪建议
- `scripts/gen_ppt.py` — 演示稿与讲稿的生成脚本，改文案重跑即可，不用手工排版

### 说明

讲稿同时写进了每页的**备注栏**，放映时用「演示者视图」可以直接看。

## [0.1.0] — 2026-10-29

首版 MVP。目标不是"做一个能卖的产品"，而是把 Discovery Lab 访谈出来的
35 条现场事实，逐条翻译成可以运行、可以复核、可以演示的代码。

### 新增

**业务挖掘（FDE Discovery Lab）**
- `docs/业务挖掘与需求洞察.md`：6 个角色 × 35 条事实的完整采集结果，每条含原始证据与验收口径
- `docs/行业分析.md` / `.docx`：门诊预约与分诊赛道分析（政策、市场、竞品、定价）

**流程可视化**
- `docs/images/flow-current.svg` / `.png`：现状流程图（预约 → 到院登记 → 分诊 → 候诊 → 接诊 → 检查交接）
- `docs/images/flow-future.svg` / `.png`：数智化转型后流程图（只读快照 + 规则建议 + 人工复核）
- `scripts/gen_diagrams.py`：流程图生成脚本，改文案不用手动画图

**报价与方案**
- `docs/报价单.md` / `.docx`：首期 16 万预算内的分项报价、人天假设、验收与里程碑

**工程与开源骨架**
- `scripts/build.sh` — 一键自检：装依赖 → 造数据 → 画图 → 跑测试 → 出看板
- `scripts/deploy.sh` — 组装 Pages 产物目录 `docs-site/`
- `scripts/gen_docs.py` — 从 Markdown 生成 .docx 交付稿
- `.github/workflows/ci.yml` — Python 3.10/3.11/3.12 矩阵 + pytest 覆盖率 + 端到端冒烟
- `.github/workflows/pages.yml` — 推送 main 自动发布看板到 Pages
- `.github/ISSUE_TEMPLATE/` — 需求反馈 / 缺陷报告（含隐私自查勾选项）
- `.github/PULL_REQUEST_TEMPLATE.md` — 红线自查清单，缺项不予合并
- `.gitattributes` — 统一 LF，避免跨平台协作时整份文件"被改过"
- `requirements.txt` / `requirements-dev.txt` — 运行时零依赖，lint 工具单独放

**可运行代码**
- `src/clinic_triage/core/models.py` — 数据模型与时间换算
- `src/clinic_triage/core/rules.py` — 6 条可解释规则，每条必带 evidence / action / explain
- `src/clinic_triage/core/queue.py` — 队列回放、分带排序、指标计算
- `src/clinic_triage/core/audit.py` — 审计流水与"能重建当时现场"的检查
- `src/clinic_triage/utils/config.py` / `io.py` / `quality.py` — 配置、读写看板、数据质量
- `src/clinic_triage/main.py` — CLI 入口 `check` / `snapshot` / `demo` / `serve`
- `src/clinic_triage/__main__.py` — 支持 `python -m clinic_triage <子命令>` 简写，
  全局参数写在子命令前后都认
- `scripts/gen_data.py` — 合成数据生成器（120 条 / 2 科室，含故意注入的脏数据）
- `config/default.yaml` — 非机密默认参数（默认快照 09:20）
- `tests/test_core.py` — 34 项测试：规则、队列回放、审计流转、数据质量、CLI
- `examples/demo.py` — 可直接运行的示例（含"系统只产出 PENDING"的反证）

### 设计约束（写在代码注释里，不是写在 PPT 里）

- **只读**：不写回任何业务系统（事实 f32）
- **急症强制转人工**：任何情况下算法不得给出临床结论（事实 f40 / f42）
- **脏数据隔离**：有歧义记录进人工队列，不进自动建议样本（事实 f33）
- **断网可降级**：使用带时间戳快照，重连按业务编号去重补齐（事实 f35）
- **三套等待口径并存**：到院 / 签到 / 预约，各自记录不合并（事实 f50 / f53）
- **收益口径保守**：不把"节省工时"直接当现金回款（事实 f03）

### 已知不做

- 不接真实 HIS / 预约平台 / 叫号系统，只用合成数据
- 不做诊断、不做用药、不做医嘱，范围限定为"时间解释与队列信息辅助"
- 不做多院区、不做医保结算、不做移动端
