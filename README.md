# Capstone Cache Simulator

F26 Introduction to Computer Science — **Shared Web Cache Simulator: Implementation and Experimentation**

本仓库用于团队 Capstone 项目。以下清单根据 2026-11-03 阅读的完整 Brightspace 项目说明及 Reference Trace 页面整理；课程页面是最终依据。当前已实现输入解析、共享缓存引擎、FIFO/LRU/LFU 三标准策略、指标与 CSV 输出、参考对账、CLI，以及 GDSF 基线与 RW-CSF 自定义策略；批量实验脚本、正式结果与图表已随 PR #32 合入 main。

## 组织与截止时间

- 团队：**4–5 人**；通过 Brightspace → More Tools → Groups 自行加入小组。
- 编程语言：Python（`>= 3.11`；CI 矩阵 3.11 / 3.12 / 3.13）。
- 截止时间：**2026 年 12 月 4 日（星期五）17:59，上海时间（UTC+8）**。
- 提交平台：**Brightspace**。GitHub 仓库本身不能替代最终提交。

## 要实现什么

实现由请求记录文件驱动的共享 HTTP 缓存模拟器。多个客户端共用一个容量有限的缓存。模拟器读取文件、逐条模拟请求、更新缓存并统计性能；不需要实现实际 HTTP 代理或建立网络连接。

输入有两类文件：

1. 资源元数据：资源标识、大小、源站获取延迟。
2. HTTP 请求记录：按时间顺序排列的多个客户端的请求。

模拟器已实现三个标准策略、一个 GDSF 对比基线和一个自定义策略 RW-CSF（CLI 名称 `CUSTOM`）：

| CLI 名称 | 策略 | 规则 |
| --- | --- | --- |
| `FIFO` | FIFO | 淘汰最早进入缓存的资源；命中不改变插入顺序。 |
| `LRU` | LRU | 淘汰最久没有访问的资源。 |
| `LFU` | LFU | 按资源自插入以来的访问次数淘汰最少使用者；次数相同时淘汰最久未访问者。 |
| `GDSF` | GDSF 基线 | 贪心双大小基线，使用累计频率与膨胀值老化，用于与自定义策略对比。 |
| `CUSTOM` | RW-CSF（自定义） | 按衰减频率 × 命中收益 ÷ 资源大小排序淘汰；设计与参数见 [docs/custom-policy-design.md](docs/custom-policy-design.md)。 |

> 说明：课程要求的"自定义策略"即 `CUSTOM`（RW-CSF）；`GDSF` 是对比基线。自定义策略不必在所有负载上胜过 FIFO/LRU/LFU。

空间不足时，应连续淘汰所需数量的资源，以容纳新资源。超过缓存总容量的资源始终从源站获取，不能存入缓存。

## 模拟规则

- 初始缓存为空；按时间顺序依次处理请求。
- 所有请求均视为可缓存的 HTTP GET；资源在模拟期间不改变。
- 不处理缓存过期；忽略 Cache-Control（包括 max-age）。
- 缓存容量可配置；参考测试使用 **100 KiB = 102,400 字节**。
- 命中延迟应可配置；课程参考配置固定为 **5 ms**。
- 未命中响应时间采用 resources.csv 给出的源站获取延迟。
- 每次未命中产生的源站流量等于所请求资源的大小；命中不产生额外源站流量。
- 各策略比较时必须使用相同工作负载、容量和模拟假设。

## 必须统计的指标

- 请求命中率：由缓存服务的请求占比。
- 字节命中率：由缓存服务的字节占总请求字节的比例。
- 平均响应时间。
- 源站总流量（字节）。
- 各客户端的命中率和平均响应时间；分析整体优化是否让某些客户端受损。

## 先通过参考测试

参考文件已原样上传至 [data/reference/](data/reference/)：

| 文件 | 用途 |
| --- | --- |
| [resources.csv](data/reference/resources.csv) | 21 条资源元数据 |
| [requests_reference.csv](data/reference/requests_reference.csv) | 3 个客户端的 15 条请求 |
| [expected_fifo.csv](data/reference/expected_fifo.csv) | FIFO 逐请求预期输出 |
| [expected_lru.csv](data/reference/expected_lru.csv) | LRU 逐请求预期输出 |
| [expected_lfu.csv](data/reference/expected_lfu.csv) | LFU 逐请求预期输出 |
| [reference_trace_answer_key.md](data/reference/reference_trace_answer_key.md) | 教授提供的参考解释与统计汇总 |

### 输入与输出格式

- 资源 CSV 字段：`scheme,host,path,status_code,content_type,size_bytes,origin_latency_ms,cache_control`。资源由 `(scheme, host, path)` 匹配，大小单位为字节，延迟单位为毫秒。
- 请求 CSV 字段：`timestamp,client_id,method,scheme,host,path`；参考请求已按时间排列。
- 预期输出字段：`step,resource_id,client_id,result,evicted,cache_contents_oldest_first,cache_used_KiB,response_ms,cumulative_origin_bytes,cumulative_hits`。
- 参考输出中的 A–E 对应关系见 answer key 的 Resource legend；输入文件没有独立的 `resource_id` 列。
- `cache_contents_oldest_first` 始终按**插入先后**排列，不是 LRU/LFU 的淘汰优先级；`evicted` 按实际淘汰顺序列出资源。
- CSV 中的多项缓存内容、淘汰列表及 Cache-Control 值含有引号包裹的逗号，解析时应使用支持标准 CSV 引号规则的解析器。
- 虽然资源文件包含 `private, no-store`、`max-age` 和状态码等字段，当前课程核心模拟仍按全部资源可缓存、忽略 Cache-Control 与过期处理。

### 验证步骤

1. 使用 `data/reference/resources.csv` 和 `data/reference/requests_reference.csv`，设置容量为 **102,400 字节**、命中延迟为 **5 ms**，每种策略从空缓存开始。
2. 分别运行 FIFO、LRU、LFU。标准策略在未命中且资源可放入缓存时应存入资源，并连续淘汰直到空间足够；LFU 的频率在淘汰并重新插入后重置。
3. 与对应 `expected_*.csv` 逐条核对命中/未命中、淘汰顺序、缓存内容、已用空间、响应时间及累计统计。
4. 核对下表汇总结果，再进行更大规模实验。

| 策略 | 命中 | 未命中 | 请求命中率 | 源站流量（字节） | 平均响应时间（ms） |
| --- | ---: | ---: | ---: | ---: | ---: |
| FIFO | 3 | 12 | 20.00% | 421,888 | 95.33 |
| LRU | 3 | 12 | 20.00% | 403,456 | 92.33 |
| LFU | 4 | 11 | 26.67% | 370,688 | 84.33 |

上表与 answer key 一致，可由 `python -m cache_simulator.reference_validation` 逐字段复现；该对账仅覆盖这三个标准策略。

### 目录结构

```
pyproject.toml             # 构建、Python 版本与依赖配置
requirements.txt           # 薄安装引用（-e .[dev,plot]）
Makefile                   # 类 Unix 构建目标
make.ps1                   # Windows PowerShell 薄映射
src/cache_simulator/
├── models.py                # ResourceKey / Resource / Request
├── engine.py                # SharedCacheEngine and RequestResult events
├── policies.py              # FIFO / LRU / LFU
├── gdsf.py                  # GDSF comparison baseline
├── rwcsf.py                 # RW-CSF custom policy (CUSTOM)
├── input_parser.py          # CSV parsing and validation
├── metrics.py               # Global and per-client metrics
├── output.py                # Ten-column CSV serialization
├── reference_validation.py  # Semantic expected-output comparator
├── workloads.py             # Reproducible workload generator
├── experiments.py           # Legacy batch scaffold (not the formal experiment entry)
├── cli.py                   # Command-line entry point
└── __main__.py              # Supports python -m cache_simulator
tests/                       # unittest suite
data/reference/              # Reference inputs and expected outputs
data/generated/              # Generated workload traces (small committed; medium/large ignored)
data/experiments/            # Batch experiment outputs (git-ignored)
data/results/                # Formal tables, manifests and figures (PR #32)
d_experiments/               # H tuning, main/ablation/drift experiments and plotting (PR #32)
docs/                        # Contracts, data dictionary, design doc, guidelines
```

### 安装

运行时零第三方依赖（仅 Python 标准库）。在仓库根目录执行：

| 用途 | 命令 |
| --- | --- |
| 核心运行 | `python -m pip install -e .` |
| 开发测试（pytest） | `python -m pip install -e ".[dev]"` |
| 实验绘图（matplotlib，可选） | `python -m pip install -e ".[plot]"` |
| 完整开发环境 | `python -m pip install -e ".[dev,plot]"`（或 `python -m pip install -r requirements.txt`） |

构建脚本：`Makefile`（类 Unix）与 `make.ps1`（Windows PowerShell），目标 `install` / `test` / `reference` / `experiments` / `experiments-small` / `figures` / `clean`。`experiments` 与 `experiments-small` 统一调用 `d_experiments/run_all.py`：`experiments` 默认输出到 `data/experiments/run_all/`，`experiments-small` 输出到独立的 `data/experiments/run_all_small/`，默认图表容量为 512 KiB，不写入 `data/results/`。`figures` 目标读取正式表，默认输出到 scratch `data/experiments/figures/` 并显式使用 512 KiB；只有显式设置 `FIGURES_DIR=data/results/figures` 才会刷新正式图表，存在覆盖风险。

### 实验运行

正式实验与快速自检都从仓库根执行；`experiments` 使用默认 `large` 规模和正式五个种子：

```bash
python d_experiments/run_all.py                 # 正式全量；默认 512 KiB；输出 data/experiments/run_all
python d_experiments/run_all.py --scale small --output-dir data/experiments/run_all_small  # 快速自检；独立输出目录

make experiments
make experiments-small

# Windows PowerShell
.\make.ps1 experiments
.\make.ps1 experiments-small
```

`data/results/` 是已提交的正式结果（27 个 tracked 文件），不是 scratch 目录；`data/experiments/` 是可重建的运行产物，已被 `.gitignore` 忽略，**不进入最终 ZIP**。正式结果与 scratch 输出必须分开保存。

### 命令行入口

单次运行通过模块入口执行（参数与错误处理详见 [HOWTO.md](HOWTO.md)）：

```bash
python -m cache_simulator --resources data/reference/resources.csv \
  --requests data/reference/requests_reference.csv --capacity 102400 \
  --hit-latency 5 --policy LFU
```

`--policy` 支持 `FIFO`、`LRU`、`LFU`、`GDSF`、`CUSTOM`；接口契约见
[docs/interface_v1.md](docs/interface_v1.md)。

### 设计决策

- **模块边界**：Engine 只产出逐请求结果事件，不做解析、指标累计或输出格式化；Metrics 是统计唯一来源，单次事实只记录一次；Output 只做只读 CSV 序列化；Strategy 只维护淘汰所需状态。
- **运行时依赖**：模拟器仅用标准库；`pytest` 为开发依赖，`matplotlib` 为可选绘图依赖，均不进入核心运行时。
- **Interface v1 已冻结**：策略接口与 Engine 结构不随意改动；自定义策略当前不做准入拒绝（`should_admit` 恒返回 `True`）。
- **参考对账范围**：`reference_validation` 目前只覆盖 `FIFO`、`LRU`、`LFU`（参考 trace 仅含这三个标准策略的预期输出）。`GDSF` 与 `CUSTOM` 尚未经过参考对账，其表现以正式实验结果为准。

## 实验要求

可复现工作负载与容量档位说明见 [实验说明](docs/experiments.md)；当前正式实验命令与快速自检见 [HOWTO 的正式实验与快速自检](HOWTO.md#正式实验与快速自检)。

至少评估三类工作负载：

1. 重复型：反复请求一小组资源。
2. 顺序型：请求许多不同资源，重复较少。
3. 混合型：多个客户端以不同浏览模式共享缓存，例如重复浏览者、大型媒体消费者和随机浏览者。

对 FIFO、LRU、LFU、自定义策略使用相同工作负载和多种缓存容量。课程给出的容量示例为 100 KB、500 KB、1 MB、5 MB、10 MB；这些是示例，并非指定必须使用的全部取值。参考测试的 100 KiB = 102,400 字节则是明确要求；实验中应明确容量单位。

用图表比较命中率随容量的变化、各策略平均响应时间和各客户端表现等，并解释结果成因。重点回答：

- 哪种策略最好，依据哪项指标？
- 工作负载或容量改变时，策略排名是否变化？
- 更高请求命中率是否一定减少源站流量？
- 最小平均响应时间是否也意味着最小网络流量？
- 整体性能改善是否使某个客户端体验变差？
- 自定义策略引入了什么优点、缺点及适用条件？

自定义策略**不必在所有工作负载上胜过 FIFO、LRU、LFU**。需要定义“更好”、解释设计、用实验展示有效条件，并承认局限。

## 最终提交清单

每组在 Brightspace 提交一个可复现的 ZIP，其中包括：

- [x] 全部模拟器源代码（核心模拟器、实验脚本与结果均已合入 main）。
- [x] 可执行文件，或 Makefile / 等效构建配置与构建说明。
- [x] README：项目结构、实现与设计决策。
- [x] HOWTO：编译、必要安装步骤、运行方式、输入文件与命令行参数。
- [x] 实验所需输入、实验结果、性能测量和比较图表；包含复现实验所需全部材料。
- [ ] **3–4 页技术报告**：自定义策略、数据结构、实验方法、比较图表、发现与结论。

另需录制演示视频，上传 **YouTube**，并在 Brightspace 提交链接（可设为 Unlisted）：

- **4 人组：12 分钟，每人 3 分钟。**
- **5 人组：10 分钟，每人 2 分钟。**
- 所有人必须参与并介绍自己的贡献。
- 内容应涵盖项目概览、数据结构与策略设计、运行请求记录的现场演示、输出统计、实验发现与个人贡献。

## 评分标准

| 项目 | 权重 |
| --- | ---: |
| 模拟器及标准策略正确性 | 30% |
| 性能测量与实验测试 | 20% |
| 自定义策略设计与论证 | 20% |
| 分析、可视化与结果解释 | 20% |
| 代码质量与文档 | 10% |

## 建议的实施顺序

以下为工作安排建议，不是教授额外指定的规则：

- [x] 阅读完整项目说明及参考测试说明。
- [x] 创建私有 GitHub 仓库并整理要求。
- [x] 确认开发语言为 Python（`>=3.11`）；小组名单与分工见 #1。
- [ ] 确认 4–5 人小组与最终分工（#1）。
- [x] 获取并上传参考文件，确认 CSV 字段与输出格式。
- [x] 实现输入解析、共享缓存状态及 FIFO、LRU、LFU。
- [x] 以参考数据验证逐条行为和全部统计指标。
- [x] 设计自定义策略并明确优化目标。
- [x] 准备至少三类工作负载及多种容量，完成公平比较。
- [ ] 生成图表，分析客户端公平性与策略取舍。
- [ ] 完成 README、HOWTO、3–4 页报告及可复现 ZIP。
- [ ] 全员录制视频，上传 YouTube，在截止前提交 ZIP 与视频链接。

## 课程来源

- [Capstone Project](https://brightspace.nyu.edu/d2l/le/lessons/628915/units/14114575)
- [Reference Trace](https://brightspace.nyu.edu/d2l/le/lessons/628915/lessons/14114628)
