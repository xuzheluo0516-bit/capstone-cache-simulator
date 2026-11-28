# 工作负载与批量实验设计

关联 [#11](https://github.com/xuzheluo0516-bit/capstone-cache-simulator/issues/11) 和 [#12](https://github.com/xuzheluo0516-bit/capstone-cache-simulator/issues/12)。生成数据置于 `data/generated/`，可重建的跑批产物置于 `data/experiments/`，已提交的正式结果置于 `data/results/`；教授给出的 `data/reference/` 文件保持原样。

## 资源集与容量

参考 `resources.csv` 有 21 条资源。参考输出 A–E 只是其中五个资源，总计 169 KiB；仅请求它们时，500 KB 以上容量不会产生淘汰。参考库的两个视频是 44,462,080 B 和 59,637,760 B，在 10 MB 缓存下均不能进入，不能用它们单独验证“大资源挤出小资源”。

生成器因此使用独立的 `experiment.example.invalid` URL 与相应 8 列资源元数据。原有十二个可缓存资源的大小分别为 8、12、16、20、24、32、40、48、64、96、128、384 KiB，总计 **872 KiB = 892,928 B**。`catalog[12]` 是 44 MiB 视频，用于验证超容量请求绕过缓存。顺序型负载在它**之后**追加专用资源：每个规模至少 60 个，实际为与请求数相同的 72、360 或 1440 个。新增资源大小在 16–256 KiB 之间轮换。前十三个资源的下标与重复型、混合型逻辑保持不变。每个输入文件均由现有 `load_inputs` 校验请求键唯一匹配。

默认容量以精确字节记录，分别为 32 KiB (32,768 B)、128 KiB (131,072 B)、256 KiB (262,144 B)、512 KiB (524,288 B)、1024 KiB (1,048,576 B)。最后一档可以装下重复型/混合型使用的 872 KiB 基础资源集，顺序型的扩大资源池在每一档都产生淘汰压力。混合负载的前缀先请求 11 个小资源，再请求 384 KiB 资源；在 512 KiB 下，真实 FIFO、LRU、LFU 事件都记录了它挤出小资源。参考测试的 100 KiB = 102,400 B 是独立的硬要求，不与本实验默认档位混淆。

## 三类负载

- `repeated`：单客户端，以 85% 概率访问前四个热点资源，其余访问十二个资源中的任意一个。
- `sequential`：单客户端，从按规模扩大的专用资源池中主要首次访问新资源；用固定种子随机选取约 12.5% 的请求位置重访已见资源。固定比例避免 72 条短 trace 因抽样波动偏离 10–15%。
- `mixed`：`browser` 反复访问小资源，`media` 访问 128/384 KiB 资源并访问超容量视频，`random` 访问十二个资源中的随机对象。视频在固定前缀第 14 条出现，此后约每 100 条请求出现一次（索引 100、200、……）；它保留绕过测试，但不再以每 17 条一次的频率淹没字节指标。固定前缀保证 512 KiB 条件有可观察的缓存竞争。
- `loop`：保留旧的十二资源 `index % 12` 循环，**仅作为额外最坏情形分析**。用 `--include-loop` 单独生成；默认三类正式负载与批量框架不包含它。

每类默认生成 72、360、1440 条请求（`small`、`medium`、`large`）。时间戳从固定 UTC 起点逐秒递增，方法为 GET，CSV 六列与真实请求输入一致。每个条件的随机流由总种子、类型和规模确定；相同配置与种子产生逐字节相同的资源与请求 CSV。`*_metadata.json` 记录生成命令、种子、请求数、客户端数、资源大小及活跃资源总大小。

调参专用输入使用**种子 `31415`**，生成到 `data/tuning/`；**这是调参用，不参与正式结果**。正式实验使用五个种子：`20261111`、`20261112`、`20261113`、`20261114`、`20261115`。调参后固定策略参数，再用五个正式种子运行，不依据正式结果重新选参。

```bash
python -m cache_simulator.workloads --output-dir data/tuning --seed 31415
python -m cache_simulator.workloads --output-dir data/generated --seed 20261111
python -m cache_simulator.workloads --output-dir data/loop --seed 31415 --include-loop
```

其他正式种子应分别写入独立目录，避免覆盖同名 CSV；例如 `data/generated/seed-20261112/`。`data/reference/` 不参与生成且保持原样。

## 跑批与审计

### 实验变量清单

- 自变量：负载类型（重复、顺序、混合；额外 loop 单独分析）、规模（72/360/1440 条）、缓存容量（精确字节数）、替换策略（FIFO/LRU/LFU/GDSF/CUSTOM），正式种子（上述五个）。
- 控制条件：同一条件下复用完全相同的资源与请求 CSV、种子、5 ms 命中延迟、空缓存初始状态、全请求计入统计且无预热；资源大小和源站延迟由输入 CSV 固定。
- 结果：请求命中率、字节命中率、平均响应时间、源站流量、逐客户端命中率与平均响应时间，以及逐请求事件。保存资源/请求哈希与代码标识，以便复核图表来源。


批量实验沿用 **同一负载和容量下所有策略读取同一对 CSV**、每轮从空缓存开始、所有请求计入统计、命中延迟 5 ms 的约定。FIFO、LRU、LFU、GDSF、CUSTOM 均已注册。`cache_simulator.experiments` 是早期批量框架；正式的调参、五策略主实验、公平性、消融、漂移与绘图统一使用 `d_experiments/run_all.py`。

```bash
python -m cache_simulator.experiments --output-dir data/experiments/seed-20261111 --seed 20261111
```

上面的命令仅供早期框架回归。正式主实验固定使用 `large` 规模，每个种子 **3 类负载 × 5 档容量 × 5 个策略 = 75 次运行**，五个正式种子共 375 次。运行 `python d_experiments/run_all.py` 可依次生成调参、主实验、公平性、消融、漂移和图表，默认输出到忽略的 `data/experiments/run_all/`，不会覆盖已提交的 `data/results/`。

### 已做的验收检查

- #11 验收 1：三个正式负载各生成 72、360、1440 条请求，共九组；每组都通过项目的 `load_inputs` 校验。同一配置/种子的资源和请求 CSV 逐字节一致。五个正式种子的顺序型 trace 在三个规模上均为 **12.5% 重访**。
- #11 验收 3：在 512 KiB 混合负载中，第 12 条请求的 384 KiB 资源进入缓存，FIFO、LRU、LFU 的真实引擎事件各记录 **10 个小资源被淘汰**。第 14 条超容量视频未进入缓存，也未淘汰原有内容。
- #12 淘汰压力与不变量：顺序型 360 条请求、种子 `20261111` 在五个默认容量下，FIFO/LRU/LFU 的每个组合均有实际淘汰事件（最少 119 次）。检查了 `hits + misses = requests`、`hit_bytes + origin_bytes = request_bytes` 和每步已用容量不超过配置。另用 D 提供的 RW-CSF/GDSF 文件做临时五策略集成试跑，225/225 次完成；该试跑用于接口验证，**不是正式五策略结果**，也不替代 D 的 PR 合入与验收。

输出包括每轮十列原始 `events/*.csv`、总体 `summary.csv`、逐客户端 `clients.csv` 和 `manifest.json`。清单写明计划/完成次数、配置、精确容量、种子、输入文件与 SHA-256、代码 Git SHA（若可用）及源代码 SHA-256、Python/包版本、策略参数与每轮状态。默认策略参数为空对象；若自定义策略有构造参数，可用 `--policy-parameters-json params.json` 传入如 `{"CUSTOM": {"weight": 0.5}}`，清单会记录实际参数。失败记录错误并以非零退出码停止，不静默缺失结果。指标不变量检查包括请求、客户端和字节守恒；引擎和指标模块检查容量上限。每次运行覆盖现有 #8 指标，结果可用输入哈希和事件文件追溯。

正式结果与输入/代码的独立审计见 [results-audit.md](results-audit.md)，可供报告使用的方法文字见 [report-experiment-method.md](report-experiment-method.md)。已提交的 `data/results/` 与可重建的 `data/experiments/` 应按审计文档中的归档边界分别处理。
