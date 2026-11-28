# Development Guidelines

本文件是 capstone-cache-simulator 团队的开发与协作规范，覆盖目录结构、分支与

PR 流程、代码风格、commit 规范、依赖与测试，以及关键 issue 的主责与 reviewer

对应表。



* 对应 issue：[#2 技术栈与开发规范](https://github.com/xuzheluo0516-bit/capstone-cache-simulator/issues/2)

  第 2、3、4、5、6、7、8、9 条，验收标准 1、3、4。

* 关联契约：[docs/interface\_v1.md](interface_v1.md)（Interface v1，已冻结）。

* 所有命令均在仓库根目录执行，路径一律使用相对路径。

* 标注约定：**Present** 表示当前分支已存在；**Planned** 表示分工表已规划、

  待对应分支合并或后续任务创建。

## 1. 项目目录结构

### 1.1 当前布局（Present）



```
.
├── .github/workflows/python-tests.yml   # CI：单元测试 + 参考对账 + 编译
├── data/
│   ├── reference/                       # 参考输入、预期输出与答案
│   ├── generated/                        # 生成的工作负载 trace（small 入库，medium/large 忽略）
│   ├── experiments/                      # 批量实验产物（git-ignored）
│   ├── results/                          # 正式实验表、manifest 与图（#33 验收时为 6 张图;加入课程 trace 结果后为 12 张图、13 份 manifest）
│   └── tuning/                           # 调参选 H 专用 trace（种子 31415）
├── d_experiments/                        # H 选取、主实验、消融、漂移、公平性与绘图脚本（#33 已验收）
├── docs/                                # 设计契约、数据字典、设计文档与本规范
├── src/cache_simulator/                 # 全部运行时代码（单一包）
├── tests/                               # unittest 测试套件
├── .gitignore
├── AGENTS.md                            # 代码评审与合并规则
├── HOWTO.md                             # 安装、运行与测试操作指南
├── README.md                            # 项目说明与设计决策
├── Makefile                             # 类 Unix 构建目标
├── make.ps1                             # Windows PowerShell 薄映射
├── requirements.txt                     # 薄安装引用（-e .[dev,plot]）
└── pyproject.toml                       # 构建、Python 版本与依赖配置
```

> 注：本目录树只呈现受版本控制的内容；被 `.gitignore` 忽略的本地产物（如 `.pytest_cache/`、`*.egg-info/`、`__pycache__/`）不列出。

### 1.2 各目录定位



| 目录                     | 状态                     | 定位                                                |
| ---------------------- | ---------------------- | ------------------------------------------------- |
| `src/cache_simulator/` | Present                | 全部运行时代码，标准库实现，包内使用相对导入                            |
| `tests/`               | Present                | `unittest` 风格测试；`tests/__init__.py` 负责注入 `src` 路径 |
| `data/reference/`      | Present                | 参考 trace 的资源、请求、预期 FIFO/LRU/LFU 输出与答案             |
| `docs/`                | Present                | 接口契约、数据字典、标准策略验证、自定义策略设计文档与开发规范        |
| `data/generated/`      | Present                | 工作负载生成器产出的资源 / 请求 / 元数据；small 入库，medium/large 被忽略 |
| `data/experiments/`    | Present（git-ignored）  | 批量实验 scratch 输出目录，按 `.gitignore` 忽略，不入库、不进入最终 ZIP |
| `data/tuning/`         | Present                | 调参专用 trace（种子 31415），仅用于选 H，不参与正式结果            |
| `data/results/`        | Present（#33 已验收）  | D 的正式汇总表、manifest 与图（#33 验收时 6 张，现为 12 张）；作为 #13/#15/#17 的输入 |
| `d_experiments/`       | Present（#33 已验收）  | H 选取、主实验、消融、漂移、公平性与绘图的一键脚本                |

> 说明：
> `src/capstone_cache_simulator.egg-info/`
> 是可编辑安装（
> `pip install -e .`
> ）
> 的本地产物，已被
> `.gitignore`
> 忽略，不属于版本控制内容。

### 1.3 构建与实验入口

- `make install` / `.\make.ps1 install` 安装 `.[dev,plot]`；仅需运行时可用 `pip install -e .`。
- `make experiments` / `.\make.ps1 experiments` 调用 `python d_experiments/run_all.py`，使用默认输出 `data/experiments/run_all/` 和默认 512 KiB 图表容量；不覆盖 `data/results/`。
- `make experiments-small` / `.\make.ps1 experiments-small` 调用 `python d_experiments/run_all.py --scale small --output-dir data/experiments/run_all_small`，使用独立 scratch 目录，避免覆盖 full 实验的 `data/experiments/run_all/`。
- `data/results/` 是已提交的正式结果；`data/experiments/` 是 scratch 产物，不进入最终 ZIP。
- `figures` 目标按 Option A 实现：默认输出 scratch `data/experiments/figures/` 并显式使用 512 KiB；只有显式设置 `FIGURES_DIR=data/results/figures` 才会刷新正式图表，存在覆盖风险。

## 2. Feature 分支与 PR 工作流程



1. **不直接推送&#x20;**`main`。所有改动在 feature 分支进行，再通过 Pull Request

   评审合入，对应 issue #2 第 3 条。

2. **分支命名**：使用描述性小写名称，以 `/` 分隔模块，例如

   `feature/8-metrics-output-docs`、`feature/10-custom-policies`。

3. **堆叠分支（stacked branches）**：当前分支链为线性堆叠，后一分支基于前一

   分支：

   `feature/engine-cli → feature/8 → feature/9 → feature/10`；

   `feature/11-12` 与 `feature/9` 同样基于 `feature/8`，二者平行。

4. **PR 流程**：创建 PR 时在描述中写明关联 issue、改动范围、验证命令与结果；

   保持 PR 与 issue 的关联，便于按验收标准逐项核对。

5. **评审与合并**：合并前必须完成 AGENTS.md 的逐项验收、CI 全绿、阻塞评论解决且无冲突。仓库 owner 已授权通过完整验收流程的 agent 在重新读取 head SHA、mergeability、review 与 check 状态后，使用 expected-head SHA guard 合并；未通过验收不得合并，也不得绕过分支保护。

   **当前集成状态**：

   * 早期堆叠链 #21 → #23 → #24 与 E 链 #22 → #26 已通过整合 PR #30 并入 `main`。PR #21 已关闭为 superseded by #30；PR #22 的脚手架内容已被 #26/#29 取代，按 #34 清理。
   * PR #32（D 实验脚本、结果与图，关联 #12）已通过 #33 验收并合入 `main`。PR #31（构建脚本与 README/HOWTO，关联 #2/#14）由 #36 验收并合并。
   * PR #25（B 文档，Draft）待 #34 按最新 `main` 复核后合入。
   * `feature/engine-cli` 基础分支已随整合链进入 `main`。

1. **分支保护**：受私有仓库套餐限制，若无法启用强制分支保护，则以本规范的

   人工评审流程作为替代约束，不变更仓库可见性或购买套餐。

## 3. 代码风格



* 遵循 **PEP 8**；建议以 black /ruff 作为格式化与静态检查工具（对应

  issue #2 第 4 条）。

* 每个模块顶部保留 `from __future__ import annotations`，并编写**完整类型**

  **注解**与**英文 docstring**。

* **优先使用 Python 标准库**：运行时零第三方依赖；不引入不必要的依赖。

* 包内导入使用**相对导入**（如 `from .engine import SharedCacheEngine`）。

* 严格遵守模块职责边界（对应 issue #2 第 6、7 条与 Interface v1）：


  * Engine 只负责缓存模拟并产出逐请求结果事件，不做解析、指标累计或输出格式化；

  * Metrics 是统计的唯一来源，单次事实只记录一次，不重复累计；

  * Output 只负责格式化（十列 CSV），不更新指标；

  * Strategy 只维护选择受害资源所需的状态，不承担解析与输出职责。

* 已冻结的 **Interface v1** 与 Engine、现有策略实现不得在未获团队确认时修改。

## 4. Commit Message 规范

采用 Conventional Commits，与仓库现有历史保持一致：



```
<type>: <简短描述>
```



* 常用 type（均在现有历史中使用）：`feat`、`fix`、`test`、`docs`、`refactor`、

  `ci`、`build`。

* 描述使用祈使句、简洁准确；一个 commit 聚焦一个内聚改动，不混合无关变更。

* 示例：`feat: add single-source global and per-client metrics`、

  `fix: reject malformed rows and non-finite numeric CSV values`。

## 5. .gitignore 约定

当前 `.gitignore` 忽略以下内容，并随构建需要在对应任务中增补：



```
__pycache__/
*.py[cod]
.pytest_cache/
.ruff_cache/
.venv/
build/
dist/
*.egg-info/
data/experiments/
data/generated/*_medium_*
data/generated/*_large_*
```

原则：忽略缓存、虚拟环境、构建产物与本地安装元数据；需要交付的源码、数据、

实验结果与文档不得被忽略。新增 `data/experiments`、`results/` 等规则时须避免

误伤需要提交的结果（对应 E6）。

## 6. Python 版本



* 构建配置：`pyproject.toml` 声明 `requires-python = ">=3.11"`。

* 本机开发：Python **3.14.6** 已实测通过（可编辑安装后可正常导入与运行）。

* CI：GitHub Actions 在 **3.11、3.12、3.13** 三个版本矩阵上运行。

* 跨版本复现：D 的原始结果环境为 Python **3.13.18**，C 的复核环境为 Python **3.14.6**。两个标准差字段存在 1-ULP 浮点差异，其余正式结果表数值一致；CSV 的 CRLF/LF 表示不同，统一为 LF 后 `source_sha256` 一致。详见 [reproduction-log.md](reproduction-log.md) 与 PR #32 的 Reproducibility Notes。

* 因此贡献代码须兼容 3.11 及以上，避免使用仅更新版本可用的语法而破坏 CI。

## 7. 依赖记录



| 类别          | 依赖           | 说明                                                         |
| ----------- | ------------ | ---------------------------------------------------------- |
| 运行时         | 无            | 模拟器仅使用 Python 标准库，核心 `[project.dependencies]` 为空          |
| 开发（dev）     | `pytest>=8`  | 已在 `pyproject.toml` 的 `[project.optional-dependencies]` 记录 |
| 绘图（plot，可选） | `matplotlib>=3.8` | 实验图表所需；已记录为 `plot` 可选依赖，不进入核心运行时；由 `d_experiments/make_plots.py` 使用 |

> 现状提示：运行时零第三方依赖；`pytest` 仅开发用，`matplotlib` 仅可选绘图用。版本约束统一在 `pyproject.toml` 维护，`requirements.txt` 仅作薄安装引用，不重复维护版本。

## 8. 测试命令

标准库 `unittest` 运行器（无需为 pytest 重写）：



```
python -m unittest discover -s tests -t . -v
```

其他验证命令：



```
python -m pytest                                  # 已安装 dev 依赖时等价运行
python -m cache_simulator.reference_validation    # 参考 trace 语义对账
python -m compileall -q src tests                 # 编译检查（CI 同用）
```

CI 会依次执行单元测试、参考对账与编译检查。任何 “测试通过” 的表述都必须以实际

运行结果为依据，未运行不得声称通过。

## 9. 关键 Issue 主责与 Reviewer 对应表

> 依据 issue #2 第 9 条，关键 issue 的主责与 reviewer 须由团队确认。下表的
> Owner 依据第二阶段分工表的模块归属推导，
> **仍待团队确认**
> ；除 #10 的
> reviewer 在分工表中明确为 C 外，其余 Reviewer 一律标记为
> **Pending confirmation**
> ，不预设人选。



| Issue | 主题                   | Owner（依据分工推导，待确认）    | Reviewer             |
| ----- | -------------------- | -------------------- | -------------------- |
| #1    | 团队组建与仓库权限            | Pending confirmation | Pending confirmation |
| #2    | 技术栈与开发规范             | A（本规范）               | Pending confirmation |
| #3    | 参考数据与输出格式研读          | B                    | Pending confirmation |
| #4    | 输入解析模块               | A                    | Pending confirmation |
| #5    | 缓存引擎核心               | A                    | Pending confirmation |
| #6    | FIFO 与 LRU 策略        | C（收尾）                | Pending confirmation |
| #7    | LFU 策略               | C（收尾）                | Pending confirmation |
| #8    | 输出与指标汇总模块            | B                    | Pending confirmation |
| #9    | 参考测试自动化验证            | C（收尾）                | Pending confirmation |
| #10   | 自定义策略设计、实现与测试        | D                    | **C（分工表明确）**         |
| #11   | 三类工作负载生成器            | E                    | Pending confirmation |
| #12   | 批量实验框架               | E                    | Pending confirmation |
| #13   | 可视化与公平性分析            | D（出图），B/C 评审         | Pending confirmation |
| #14   | 构建脚本、README 与 HOWTO  | A                    | Pending confirmation |
| #15   | 3–4 页技术报告            | B（统稿，待确认）            | Pending confirmation |
| #16   | 演示视频                 | C（剪辑，待确认）            | Pending confirmation |
| #17   | 最终打包与 Brightspace 提交 | A（建议提交）、B（建议复核）      | Pending confirmation |

## 10. 待确认事项（Pending confirmation）



1. 上表各关键 issue 的正式 Owner 与 Reviewer 人选（issue #2 第 9 条）。

2. 报告统稿人、视频剪辑人、最终提交人与复核人的最终确认。

3. 实验归档约定以 E5/E6 为准；`data/results/`（表、manifest、图）与 `d_experiments/`（脚本）已随 PR #32 合入并经 #33 验收。

## 11. 既有阶段目标

以下为团队计划（对应 issue #2 验收标准 4），不是额外课程截止日期：

| 里程碑 | 目标 | 计划完成 |
| --- | --- | --- |
| M1 | 参考验证 | 2026-11-16 |
| M2 | 策略实现 | 2026-11-20 |
| M3 | 实验分析 | 2026-11-27 |