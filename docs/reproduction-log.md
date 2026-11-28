# 干净环境复现记录（#14 第 7 条、#17 第 3 条）— 初测

任务 C4。记录在一台未参与开发的机器/新虚拟环境中，按 [HOWTO](../HOWTO.md) 从零 clone 开始，完成安装、测试、参考对账与一次完整跑批。**状态：初测。** HOWTO 与 Makefile 由 A 在 #14 定稿（骨架 11/20、定稿 11/28），定稿后需按同一流程复测一次，本文件届时更新。

## 1. 复现对象

远程仓库 `main` 上目前只有文档，参考对账、负载与策略都还在未合并的功能分支里，因此本次复现使用按团队合并顺序得到的本地合并树：

| 组成 | 分支 / PR | commit |
| --- | --- | --- |
| 解析器、引擎、指标、输出、参考对账 | `feature/9-reference-acceptance`（PR #23） | `da796e1` |
| 自定义策略注册 | `feature/10-custom-policies`（PR #24） | `68bff1b` |
| 新负载、调参输入、批量框架 | `feature/11-12-sequential-tuning`（PR #26） | `6395789` |

本地合并提交：`f73957a`。合并无冲突，`HOWTO.md` 与 `tests/test_reference_validation.py` 自动合并成功。

## 2. 环境

| 项 | 值 |
| --- | --- |
| 操作系统 | Microsoft Windows 11 家庭中文版，build 22631，AMD64 |
| Python | 3.14.6（`python -m venv .venv`，仅标准库运行时依赖） |
| pip | 26.3（venv 内升级后） |
| Git | git version 2.55.0.windows.1；`core.autocrlf=true` 来自 Git for Windows 的系统配置 |
| 开发依赖 | `pytest 9.2.0`（执行 `pip install -e ".[dev]"` 后） |
| 网络 | 运行时安装不需要第三方包；`pip install -e .` 只用本地 setuptools 构建 |

本机只安装了 Python 3.14.x，CI 覆盖的 3.11–3.13 未能在本机复现；见问题 P5。

## 3. 按 HOWTO 执行的步骤与结果

| 步骤 | 命令 | 结果 |
| --- | --- | --- |
| 1 | `git clone <repo> repo` | 成功 |
| 2 | `python -m venv .venv` | 成功 |
| 3 | `python -m pip install --upgrade pip` | 成功 |
| 4 | `python -m pip install -e .` | 成功，`capstone-cache-simulator-0.1.0` 可编辑安装 |
| 5 | `python -m unittest discover`（HOWTO 第 5 节原文） | **失败 1 项 / 共 138 项**：`test_generated_inputs_reproduce_committed_csv` 报 CSV 字节不一致（`\n` 与 `\r\n`） |
| 6 | `git config core.autocrlf false` 后重新 checkout，再执行同一命令 | 138 项全部通过，退出码 0 |
| 7 | `python -m cache_simulator.reference_validation` | FIFO / LRU / LFU 三行 PASS，退出码 0 |
| 8 | `cache-sim-validate-reference`（`pyproject.toml` 注册的等价入口） | 同上，退出码 0 |
| 9 | `python -m cache_simulator --resources data/reference/resources.csv --requests data/reference/requests_reference.csv --capacity 102400 --hit-latency 5 --policy CUSTOM` | 退出码 0，输出 15 行十列 CSV |
| 10 | `cache-sim --policy GDSF ...`（控制台脚本） | 退出码 0 |
| 11 | `python -m cache_simulator.workloads --output-dir data/generated --seed 20261111` | 退出码 0，9 组输入经解析器校验 |
| 12 | `python -m cache_simulator.experiments --output-dir data/experiments/full --seed 20261111` | 退出码 0，**225/225 次运行**，耗时约 4 s；`summary.csv` 共 226 行（含表头） |
| 13 | `python -m pytest -q`（`.[dev]` 安装后） | 138 passed，755 subtests passed |
| 14 | 重新生成后再看 `git status` | 3 个 `data/generated/*_small_metadata.json` 被修改；CSV 未变 |

## 4. 发现的问题

### P1（阻断，影响所有 Windows 队友）测试在 Git for Windows 默认配置下失败

`tests/test_workloads_experiments.py` 的 `test_committed_small_examples_match_current_generator` 用 `read_bytes()` 逐字节比较生成的 CSV 与仓库里的同名 CSV。Git for Windows 安装时把 `core.autocrlf=true` 写入系统级配置（本机为 `C:/Program Files/Git/etc/gitconfig`），checkout 时把仓库中 LF 的 CSV 转成 CRLF，而生成器写出的仍是 LF，于是断言必然失败。当时仓库没有 `.gitattributes`，无法固定换行。

- 影响：#11 验收 2 的「同一配置和种子生成相同元数据」在 Windows 上表现为失败；任何队友在默认 Git 配置下都会遇到，且容易误判为代码缺陷。
- 建议（E）：加 `.gitattributes`，对 CSV 与生成数据不转换换行（例如 `*.csv -text`，避免影响 `data/reference/` 必须保持原样的 CRLF 文件），或把该断言改为按解析后的行/字段比较，而不是原始字节。责任人：E（测试作者），A 在 #2 规范里补换行约定。
- C 侧处置：本记录的步骤 6 用 `core.autocrlf=false` 绕过，并已确认这是唯一失败的测试。
- 收尾修复（2026-11-28）：新增 `.gitattributes`，将 `.py` 与 `.csv` 固定为 LF checkout，并用 `data/reference/** -text` 保留教授参考文件的原始 CRLF；`test_committed_small_examples_match_current_generator` 改为按 CSV 解析后的字段比较。在 `core.autocrlf=true` 的 Windows 工作区复跑全量测试、参考对账与结果审计均通过，正式 `data/results/` 未被修改。

### P2（文档矛盾，合并后才暴露）HOWTO 第 9 节与第 4.1 节互相矛盾

合并后 `HOWTO.md` 同时写着「`--policy` 可取 `FIFO`/`LRU`/`LFU`/`GDSF`/`CUSTOM`」（第 4.1 节）和「当前功能分支仅有 FIFO、LRU、LFU」「直接执行默认命令会明确报错 `policy not registered: CUSTOM`」（第 9 节）。按第 9 节执行会得到与人实际观察相反的说法。

- 建议（A，#14）：定稿时把第 9 节改成五策略现状，并把「未注册策略会报错」改写成「错误处理行为」而非当前状态。

### P3（悬空引用，PR #24 引入）HOWTO 第 4.1 节指向 README 中不存在的内容

`HOWTO.md` 写「策略的设计原理与参数见 README（由 D 提供），本指南不展开」，但当前 `README.md` 没有任何 CUSTOM / RW-CSF / GDSF 内容。提交 ZIP 后读者会找不到。

- 建议：D 在 #10 的设计文档（`docs/custom-policy-design.md`）落地后，把 HOWTO 的指向改为该文档，或在 README 增加「自定义策略」小节并链接设计文档。责任人：D，A 定稿时核对链接。

### P4（可追溯性）重新生成会把 3 个已提交的 metadata JSON 改脏

`*_metadata.json` 里的 `generator_command` 原样记录了调用时的 `--output-dir` 字符串（本机为 `data\generated`，仓库里是 `data/generated`），文件换行也与生成器输出不同。结果是「同样的种子、同样的命令」重新生成后工作区不干净，而且元数据无法逐字节复现。

- 影响：#11 验收 2 的「资源元数据逐字节一致」只对 CSV 成立，对 metadata JSON 不成立；#12 验收 2 的追溯也会因机器不同而漂移（`#14` 第 6 条要求不依赖某位成员的绝对路径）。
- 建议（E）：metadata 里记录规范化的命令（模块名 + 相对目录 + 种子），或只记录参数本身；统一换行。责任人：E。

### P5（环境覆盖）本机只有 Python 3.14，3.11–3.13 只在 CI 覆盖

HOWTO 声明 `>= 3.11`，CI 跑 3.11/3.12/3.13，团队本机是 3.14.x。C4 无法在本机验证 3.11–3.13。

- 建议（A）：HOWTO 写明「本机已验证 3.14，CI 验证 3.11–3.13」，并在干净环境复现记录里引用 CI 结果，避免读者以为每个版本都人工验证过。

### P6（体积）跑批输出需要 E6 与 #17 关注

单个种子的完整输出（5 策略 × 3 负载 × 3 规模 × 5 容量 = 225 次）占 **9.31 MB**，其中 `events/` 225 个文件共 **8.39 MB**；五个种子约 **47 MB**。`data/tuning/` 0.69 MB，`data/generated/` 0.69 MB。

- 影响：ZIP 体积可控，但 `.gitignore` 忽略 `data/experiments/`，最终结果不会进仓库，提交时必须确认这些文件确实被打包（#17 第 1 条）。
- 建议：按 E6 的归档约定，正式结果只提交 `summary.csv`、`clients.csv`、图表与 `manifest.json`，`events/` 压缩或按需保留。责任人：E、D。

## 5. 未能在本次覆盖的部分

- `Makefile` 与 #14 的最终 HOWTO 尚未存在（A 负责），因此「按 HOWTO 从零跑通参考测试与全部实验」只能按当前 HOWTO 初测，**不能据此认为 #14 第 7 条已满足**。
- #13 的可视化与公平性脚本尚未合并，绘图命令（#14 第 5 条）本轮无法执行。
- 正式五种子结果依赖 D 的实验 PR，本轮只用种子 `20261111` 验证流程可跑通。

## 6. C1 预检：比较器自测是否齐全

C1 要求在合并后的基线上确认「比较器自测齐全」。合并树上 `tests/test_reference_validation.py` 的 9 个用例覆盖情况如下，全部通过：

| 用例 | 覆盖点 |
| --- | --- |
| `test_all_standard_policies_match_every_reference_field` | 三策略 × 15 请求 × 10 字段与参考 CSV 逐字段一致 |
| `test_per_client_reference_metrics_are_correct` | 逐客户端命中率与平均响应时间 |
| `test_comparator_accepts_each_expected_file_as_actual` | 三份 expected 互为实际值时不误报 |
| `test_comparator_ignores_line_endings_quoting_and_numeric_spelling` | CRLF/LF、合法引号、`32` 与 `32.0` 不误报 |
| `test_comparator_detects_reordered_fifo_lists` | 淘汰顺序/缓存插入顺序被颠倒时能报错 |
| `test_comparator_reports_policy_step_and_wrong_field` | 报错信息给出策略、请求序号、字段 |
| `test_comparator_detects_eviction_and_cumulative_counter_mismatch` | 累计值被改错时能报错 |
| `test_comparator_checks_header_order_and_row_count` | 表头顺序与行数 |
| `test_comparator_rejects_rows_with_missing_or_extra_columns` | 缺列/多列 |

结论：比较器自测齐全，C1 中「确认比较器自测齐全」一项在合并后可直接复跑确认。但 C1 的另一个前提（「合并后在基线上运行」并勾选 #6/#7/#9 验收）仍取决于 A 先合并 PR #18 与 `feature/9-reference-acceptance`，本轮 `main` 上还没有这些代码，因此三个 issue 未关闭。

## 7. 结论

在 Windows 11 + Python 3.14.6 的全新 venv 中，按当前 HOWTO 可以完成安装、参考对账（三策略逐字段一致、退出码 0）、CLI 与批量跑批（225/225 次成功，约 4 s），说明工程链路本身是可复现的。除 P1 的换行问题外没有出现运行错误；P2–P6 属于文档与元数据规范化问题，不影响数值结果。定稿 HOWTO 后请按本文第 3 节重新执行一次，并把 P1–P3 的修复结果补进本文件。
