# HOWTO

本指南说明如何在干净环境中安装、运行和测试 Shared Web Cache Simulator。

所有命令均在仓库根目录执行。

## 1. 环境要求

* **Python**：`>= 3.11`。CI 在 3.11、3.12、3.13 上运行；本机另在 Python 3.14 实测通过。

* **运行时依赖**：无。模拟器仅使用 Python 标准库。

* **开发依赖**：`pytest`（可选，用于运行测试），不是运行时依赖。

* **绘图依赖（可选）**：`matplotlib`，仅生成实验图表时需要。

* 操作系统：Windows / macOS / Linux 均可；命令在仓库根目录以相对路径执行。

## 2. 安装

建议使用可编辑安装，便于开发：

```
python -m pip install --upgrade pip
python -m pip install -e .          # 仅安装模拟器（零第三方运行时依赖）
python -m pip install -e ".[dev]"  # 额外安装 pytest 等开发工具
python -m pip install -e ".[plot]"  # 额外安装 matplotlib（绘图，可选）
python -m pip install -e ".[dev,plot]"  # 完整开发环境（等价 requirements.txt）
```

## 3. 项目结构

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
├── reference_validation.py   # Semantic expected-output comparator
├── workloads.py             # Reproducible workload generator
├── experiments.py           # Batch experiment scaffold
├── cli.py                   # Command-line entry point
└── __main__.py              # Supports python -m cache_simulator
tests/                       # unittest suite
data/reference/              # Reference inputs and expected outputs
data/generated/              # Generated workload traces
data/experiments/            # Batch experiment outputs (git-ignored)
data/results/                # Committed formal results, manifests and figures
d_experiments/               # H tuning, main/ablation/drift runs and plotting
docs/                        # Contracts, data dictionary, design doc
```

## 4. 运行模拟（CLI）

单次运行入口：



```
python -m cache_simulator \
  --resources data/reference/resources.csv \
  --requests data/reference/requests_reference.csv \
  --capacity 102400 \
  --hit-latency 5 \
  --policy LFU
```



| 参数              | 类型     | 默认     | 说明                     |
| --------------- | ------ | ------ | ---------------------- |
| `--resources`   | 路径     | 必填     | 资源 CSV                 |
| `--requests`    | 路径     | 必填     | 请求 CSV                 |
| `--capacity`    | 整数（字节） | 102400 | 缓存容量，非负                |
| `--hit-latency` | 浮点（ms） | 5.0    | 命中延迟，非负                |
| `--policy`      | 选项     | LRU    | `FIFO` / `LRU` / `LFU` / `GDSF` / `CUSTOM` |



* 成功时输出与 `expected_*.csv` 同列名、同顺序的十列 CSV，并以退出码 `0` 结束。

* 参数、文件或解析错误打印信息并以**非零退出码**结束。

* CLI 把事件交给 `MetricsAccumulator` 累计一次，再将只读快照交给
  CSV 序列化器；输出模块不重复更新指标。

### 4.1 自定义策略用法

`--policy` 可取 `FIFO`、`LRU`、`LFU`、`GDSF`、`CUSTOM`：

* `CUSTOM` 是自定义策略 RW-CSF；`GDSF` 是用于对比的基线策略。设计原理、参数与半衰期 $H$ 的选取见 [docs/custom-policy-design.md](docs/custom-policy-design.md)。

* 示例命令：

```
python -m cache_simulator --resources data/reference/resources.csv \
  --requests data/reference/requests_reference.csv --policy CUSTOM
```

* **固定 5 ms 命中延迟**：`CUSTOM`/`GDSF` 的策略评分基于固定 5 ms 命中延迟。命令行 `--hit-latency X` 只传入引擎，**不会**传入策略评分（策略按默认 5.0 构造）；课程要求的 5 ms 下行为正确，若修改该参数需同步调整策略参数。


## 5. 运行测试

标准库 `unittest` 运行器（与 CI 一致，测试为 `unittest` 风格，无需为 pytest 重写）：

```
python -m unittest discover -s tests -t . -v
python -m pytest                     # 已安装 dev 依赖时等价运行
```

## 6. 自动参考验证

一次运行 FIFO、LRU、LFU，并逐行逐字段语义比较三个参考输出（不依赖
CSV 原始引号或换行字节完全相同）：

```bash
python -m cache_simulator.reference_validation
```

验证失败会报告策略、请求序号、字段、预期值和实际值，并返回非零退出码。

> 该对账只覆盖 `FIFO`、`LRU`、`LFU`；`GDSF` 与 `CUSTOM` 没有参考预期输出，不在此验证范围内。

## 7. 输入文件要求



* 资源 CSV 表头（8 列）：

  `scheme, host, path, status_code, content_type, size_bytes, origin_latency_ms, cache_control`

* 请求 CSV 表头（6 列）：

  `timestamp, client_id, method, scheme, host, path`

* 编码 UTF-8；请求方法必须为 `GET`；时间戳支持 ISO 8601 与 `Z` 后缀。

* 资源以 `(scheme, host, path)` 唯一标识；请求按时间戳稳定排序，

  相同时间戳保持源文件顺序，稳定序号从 1 开始。

* 解析或校验失败会报告文件名与行号。

## 8. 参考配置



* 容量以**字节**为单位（1 KiB = 1024 字节）：参考配置 `102400` 字节 = 100 KiB；命中延迟 `5` ms；初始缓存为空。`--capacity` 接收精确字节数。

* 每次独立运行都新建引擎与策略，不继承上一轮的缓存或策略状态。

## 9. 可复现实验输入与跑批

### 生成负载

生成三类负载、每类三个规模（small 72 / medium 360 / large 1440 请求）的 CSV，由项目解析器校验：

```bash
python -m cache_simulator.workloads --output-dir data/generated --seed 20261111
```

### 批量跑批

```bash
python -m cache_simulator.experiments --output-dir data/experiments/latest --seed 20261111
```

常用参数（与 `experiments.py` 一致）：

| 参数 | 默认 | 说明 |
| --- | --- | --- |
| `--output-dir` | `data/experiments/latest` | 跑批输出目录：`summary.csv`、`clients.csv`、`events/*.csv`、`manifest.json` |
| `--seed` | `20261111` | 随机种子；正式实验种子为 20261111–20261115；调参选 $H$ 用种子 31415，不参与正式结果 |
| `--capacities-bytes` | 32 / 128 / 256 / 512 / 1024 KiB | 容量档位，精确字节数 |
| `--policies` | 五策略 | 参与跑批的策略名 |
| `--policy-parameters-json` | 无 | JSON 文件，把构造参数传给对应策略（如 CUSTOM 的 `half_life`），并写入 `manifest.json` |
| `--hit-latency-ms` | `5.0` | 命中延迟（仅传入引擎） |

- `data/reference/` 不会被修改；`data/experiments/` 与 `data/generated/` 的中/大规模产物按 `.gitignore` 忽略。

### 一键正式实验与图表

已提交的正式结果可用一条命令重跑（会写入 `data/experiments/run_all/`，默认不覆盖 `data/results/`）：

```bash
python d_experiments/run_all.py --output-dir data/experiments/run_all
```

从已提交的结果表重新生成 6 张图：

```bash
make figures
# Windows PowerShell
.\make.ps1 figures
# 等价直接调用
python d_experiments/make_plots.py \
  --results-dir data/results/main \
  --tuning-dir data/results/h-tuning \
  --figures-dir data/results/figures
```

`make figures` 使用 `RESULTS_DIR`、`TUNING_DIR`、`FIGURES_DIR` 三个变量，默认分别指向 `data/results/main`、`data/results/h-tuning`、`data/results/figures`。绘图需要安装 `plot` 可选依赖：`python -m pip install -e ".[plot]"`。

### Windows

无 `make` 时直接运行上述 `python -m ...` 命令，或使用薄映射脚本：

```powershell
.\make.ps1 experiments
.\make.ps1 test
.\make.ps1 reference
```

仓库文本文件以 LF 保存。Git for Windows 默认可能启用 `core.autocrlf=true`，checkout 时把 LF 改写为 CRLF，导致按字节比较生成 CSV 的测试失败。首次 clone 后建议在仓库根目录执行：

```bash
git config core.autocrlf false
```

然后重新 clone 或重新 checkout 工作区。详细复现记录见 [docs/reproduction-log.md](docs/reproduction-log.md)。
