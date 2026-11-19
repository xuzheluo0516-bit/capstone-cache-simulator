# HOWTO

本指南说明如何在干净环境中安装、运行和测试 Shared Web Cache Simulator。

所有命令均在仓库根目录执行。

## 1. 环境要求



* **Python**：`>= 3.11`（开发与验证使用 Python 3.13）。

* **运行时依赖**：无。模拟器仅使用 Python 标准库。

* **开发依赖**：仅 `pytest`（用于运行测试），不是运行时依赖。

* 操作系统：Windows /macOS/ Linux 均可，命令示例以通用 shell 表示。

## 2. 安装

建议使用可编辑安装，便于开发：



```
python -m pip install --upgrade pip
python -m pip install -e .          # 仅安装模拟器（零第三方运行时依赖）
python -m pip install -e ".[dev]"   # 额外安装 pytest 等开发工具
```

## 3. 项目结构

```
src/cache_simulator/
├── models.py                # ResourceKey / Resource / Request
├── engine.py                # SharedCacheEngine and RequestResult events
├── policies.py              # FIFO / LRU / LFU
├── input_parser.py          # CSV parsing and validation
├── metrics.py               # Global and per-client metrics
├── output.py                # Ten-column CSV serialization
├── reference_validation.py  # Semantic expected-output comparator
├── cli.py                   # Command-line entry point
└── __main__.py              # Supports python -m cache_simulator
tests/                       # unittest suite
data/reference/              # Reference inputs and expected outputs
docs/                        # Interface contract and data dictionary
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
| `--policy`      | 选项     | LRU    | `FIFO` / `LRU` / `LFU` |



* 成功时输出与 `expected_*.csv` 同列名、同顺序的十列 CSV，并以退出码 `0` 结束。

* 参数、文件或解析错误打印信息并以**非零退出码**结束。

* CLI 把事件交给 `MetricsAccumulator` 累计一次，再将只读快照交给
  CSV 序列化器；输出模块不重复更新指标。


## 5. 运行测试

两种方式等价，测试均为标准库 `unittest` 风格，无需为 pytest 重写：



```
python -m unittest discover          # 标准库运行器
python -m pytest                     # 已安装开发依赖时
```

## 6. 自动参考验证

一次运行 FIFO、LRU、LFU，并逐行逐字段语义比较三个参考输出（不依赖
CSV 原始引号或换行字节完全相同）：

```bash
python -m cache_simulator.reference_validation
```

验证失败会报告策略、请求序号、字段、预期值和实际值，并返回非零退出码。

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



* 容量 `102400` 字节（100 KiB）、命中延迟 `5` ms、初始缓存为空。

* 每次独立运行都新建引擎与策略，不继承上一轮的缓存或策略状态。