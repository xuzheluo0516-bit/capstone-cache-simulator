# Interface v1 — Team Working Contract

> **Status: Interface v1 — Team Working Contract.**
>
> 团队负责人已授权 A 统一接口名称与规范，B、C、D、E 后续开发遵循本契约。
> 本文件取代此前的草案措辞；所有签名以仓库真实代码为基准，且 A 侧实现已落地。
>
> 本文件只定义契约，不包含具体实现。未来可能的扩展统一记录在 §12，
> **未确认的扩展不得影响当前 v1。**

---

## 1. 范围与术语

- 离线、trace 驱动的共享 HTTP 缓存模拟；初始缓存为空；所有请求均为可缓存 GET；
  忽略 Cache-Control 与过期；资源在模拟期间不变。
- **资源标识（identity）**：`ResourceKey = (scheme, host, path)`，不是单个 id 字符串。
- **稳定请求序号 `sequence`**：请求按时间戳稳定排序后，从 **1** 开始分配；
  相同时间戳保持源文件顺序。该序号是所有"同时间戳平局"的唯一裁决依据。
- **`step` 统一等于 `request.sequence`**，系统不另造第二套序号。
- **两种顺序不可混淆**：
  - *insertion order*：资源进入缓存的先后，仅用于展示 `cache_contents_oldest_first`。
  - *access order*：最近访问先后，仅服务于 LRU/LFU 的淘汰决策，由策略各自维护。

---

## 2. 数据结构（models 层）

### 2.1 ResourceKey（已存在，不改）

```python
@dataclass(frozen=True, order=True, slots=True)
class ResourceKey:
    scheme: str
    host: str
    path: str
```

- 冻结、可哈希、可排序（`order=True`），可作为 dict key 与确定性兜底排序键。

### 2.2 Resource（已存在，不改）

```python
@dataclass(frozen=True, slots=True)
class Resource:
    key: ResourceKey
    status_code: int
    content_type: str
    size_bytes: int          # 非负整数，单位字节
    origin_latency_ms: float # 非负有限数，单位 ms
    cache_control: str       # 核心模拟中忽略
```

- 引擎不按 `status_code` / `cache_control` 过滤；全部视为可缓存。

### 2.3 Request（已存在，不改）

```python
@dataclass(frozen=True, slots=True)
class Request:
    timestamp: datetime
    client_id: str
    method: str              # 仅允许 "GET"
    key: ResourceKey
    sequence: int            # 从 1 开始的稳定序号
    source_line: int         # 源文件物理行号，用于报错，不参与比较
```

### 2.4 CacheEntry（逻辑概念，不新增类）

缓存驻留项的物理实现是 `OrderedDict[ResourceKey, Resource]`；v1 不新增独立的
CacheEntry 类，也不单独保存 `insertion_sequence` 数值。

- 从 FIFO 所需的插入先后语义看，OrderedDict 的键顺序与按 `insertion_sequence`
  排序等价；但 OrderedDict 本身并不保存一个名为 `insertion_sequence` 的数值。
- OrderedDict 负责表达缓存插入顺序，`cache_contents_oldest_first` 直接取自该键顺序。
- LRU/LFU 的访问状态由各自策略维护，与缓存插入顺序分离，二者不混淆。
- 不把任何策略状态放进缓存数据结构；策略状态归策略对象所有。
- 本次不重构 Engine。

---

## 3. Strategy Protocol（策略接口）

v1 确定的方法集合（保留 `select_victim`，新增 `should_admit`）：

```python
class EvictionPolicy(Protocol):
    def on_hit(self, key: ResourceKey, *, step: int) -> None: ...
    def on_insert(self, key: ResourceKey, *, step: int) -> None: ...
    def should_admit(self, resource: Resource, *, step: int) -> bool: ...
    def select_victim(
        self, resident_keys: Sequence[ResourceKey], *, step: int
    ) -> ResourceKey: ...
    def on_evict(self, key: ResourceKey, *, step: int) -> None: ...
    def reset(self) -> None: ...
```

### 3.1 各方法契约

| 方法 | 时机 | 职责 / 返回 |
| --- | --- | --- |
| `on_hit(key, *, step)` | 命中、事件发出前 | 更新策略的访问状态；FIFO 故意不变 |
| `on_insert(key, *, step)` | 一次已提交的插入 | 初始化该 key 的策略状态（LFU 频率 = 1） |
| `should_admit(resource, *, step)` | miss、淘汰之前 | 返回 `bool` 决定是否准入；缺失时默认 `True` |
| `select_victim(resident_keys, *, step)` | 空间不足时 | 从驻留键中返回**一个**淘汰对象 |
| `on_evict(key, *, step)` | 一次已提交的淘汰 | 清除该 key 的策略状态 |
| `reset()` | 新一次独立运行 | 清空全部策略状态 |

### 3.2 回调风格约定

- 全部使用**仅限关键字参数** `step`，与现有代码一致。
- 策略只接收 `ResourceKey`（准入除外，需要 `Resource` 以读取大小/延迟）。
- `select_victim` 必须返回传入的驻留键之一；返回非驻留键时引擎抛
  `PolicyContractError`。
- 平局的确定性兜底：策略在排序键末尾附加 `ResourceKey`，保证手工/直接使用时结果确定。

### 3.3 should_admit 规则

- 签名：`should_admit(resource: Resource, *, step: int) -> bool`。
- Engine 提供 `should_admit` 作为**可选准入扩展接口**。未实现该方法的策略，引擎
  通过 `getattr` 防御性查找，默认视为允许准入，因此 C 已完成的 FIFO/LRU/LFU
  无需改动即可继续工作。
- **FIFO、LRU、LFU 必须始终允许准入，不得主动拒绝。**
- **Custom Policy 是否可以实际拒绝准入，须以组长/助教对课程要求的确认为前提。**
  在确认之前，Custom Policy 不得依赖拒绝准入行为。若最终课程不允许选择性准入，
  保留 Engine 的兼容接口即可，所有策略都返回 True。
- 当策略实现了 `should_admit` 时，其返回值必须是 `bool`；返回 `None`、字符串或
  整数等其他类型时，引擎抛 `PolicyContractError`，不做隐式真值判断。
- 调用次序：硬规则（超容量）优先，其次才问 `should_admit`；超容量时不调用策略。
- 准入被拒后的引擎行为见 §4.3。

---

## 4. Engine 接口（A 的核心）

### 4.1 构造（已存在，签名不变）

```python
SharedCacheEngine(
    resources: Mapping[ResourceKey, Resource],
    policy: EvictionPolicy,
    *,
    capacity_bytes: int = 102400,      # 100 KiB，字节
    hit_latency_ms: float = 5.0,       # ms，可配置
)
```

- 构造时校验容量（非负整数）、命中延迟（非负有限）、资源映射键与 `resource.key`
  一致、资源大小/延迟合法，并调用一次 `policy.reset()`。
- 只读属性：`capacity_bytes`、`hit_latency_ms`、`used_bytes`、
  `cache_contents_oldest_first`。

### 4.2 请求处理（`process` / `process_all` / `reset`）

```python
def process(self, request: Request) -> RequestResult: ...
def process_all(self, requests: Collection[Request]) -> tuple[RequestResult, ...]: ...
def reset(self) -> None: ...
```

- 重复处理同一 `sequence` 抛 `ValueError`。
- **`process_all()` 严格按传入顺序处理，不自行重新排序。**

**单请求处理顺序（权威流程）：**

1. 校验请求；登记 `sequence` 防重复。
2. 命中（key 已在缓存）：`policy.on_hit(...)` → 返回 HIT 事件。
3. 未命中，取 `resource`。
4. **硬规则**：`resource.size_bytes > capacity` → 不调用任何策略回调，直接返回 MISS，
   不插入、不淘汰、不改缓存；`size == capacity` 允许进入下一步。
5. **准入**：`policy.should_admit(resource, step)` 返回 False → 见 §4.3，返回 MISS；
   返回非布尔值 → 抛 `PolicyContractError`。
6. `while used + resource.size > capacity`：`select_victim` → 校验驻留 → 弹出并
   `on_evict`，循环直到放得下（连续淘汰，不只淘汰一个）。
7. 写入缓存、累加字节、`on_insert`。
8. 返回 MISS 事件。

### 4.3 准入拒绝 / 超容量的事件形态

下列"不写入"情形一旦发生，产生的事件形态一致，便于 B 统一处理：

- `hit=False`、`evicted=()`、`cache_contents_oldest_first` 与处理前相同、
  `response_ms = resource.origin_latency_ms`、`origin_bytes = resource.size_bytes`。
- 不调用 `on_insert`、`select_victim` 或 `on_evict`，不改变其他驻留项与策略状态。
- 两者区别仅在触发原因：超容量是引擎硬规则（无需询问策略）；准入拒绝是
  `should_admit` 返回 False 时的引擎行为。这里定义行为不代表选择性准入已获课程
  认可，其使用前提见 §3.3、§12。两种情况下该请求都仍按 miss 计入指标。

### 4.4 延迟与流量规则（不可更改的课程规则）

- HIT：`response_ms = hit_latency_ms`，`origin_bytes = 0`。
- MISS：`response_ms = origin_latency_ms`，**不叠加**命中延迟；
  `origin_bytes = size_bytes`。
- 任意时刻 `used_bytes <= capacity_bytes`。

---

## 5. Result Event 与 Metrics 的边界

### 5.1 RequestResult（已存在，已符合要求）

```python
@dataclass(frozen=True, slots=True)
class RequestResult:
    request: Request
    hit: bool
    evicted: tuple[ResourceKey, ...]
    cache_contents_oldest_first: tuple[ResourceKey, ...]
    cache_used_bytes: int
    response_ms: float
    origin_bytes: int
    # 便捷属性：step / resource_key / client_id / result("HIT"|"MISS")
```

- **只含这一条请求本身的事实，不含任何累计列**
  （无 `cumulative_origin_bytes`、无累计响应时间）。
- 每个请求恰好产生一个事件；引擎不做命中率/流量/均值等统计。

### 5.2 事件 → 参考输出 10 列的映射（供 B 实现 Output/Metrics）

| expected 列 | 来源 |
| --- | --- |
| `step` | `event.step` |
| `resource_id` | 图例映射 `event.resource_key`（A–E 仅参考用，引擎不写死） |
| `client_id` | `event.client_id` |
| `result` | `event.result` |
| `evicted` | 格式化 `event.evicted`；空列表输出 `-` |
| `cache_contents_oldest_first` | 格式化 `event.cache_contents_oldest_first`（插入顺序） |
| `cache_used_KiB` | `event.cache_used_bytes / 1024`（不截断） |
| `response_ms` | `event.response_ms` |
| `cumulative_origin_bytes` | **Metrics** 对 `origin_bytes` 累计 |
| `cumulative_hits` | **Metrics** 对 `hit` 累计 |

- 累计、命中率、字节命中率、平均响应、每客户端指标全部由 B 的 Metrics 从事件序列计算。
- 分母为 0 输出 `N/A`，不除零；累计值先不截断，展示层统一两位小数。

---

## 6. CLI 参数（单次运行，已确定）

基于标准库 `argparse`，不引入第三方依赖。

| 参数 | 类型 | 默认 | 单位 / 合法范围 | 说明 |
| --- | --- | --- | --- | --- |
| `--resources` | path | 必填 | 文件存在、可读 | 资源 CSV |
| `--requests` | path | 必填 | 文件存在、可读 | 请求 CSV |
| `--capacity` | int | `102400` | 字节，非负 | 缓存容量 |
| `--hit-latency` | float | `5.0` | ms，非负有限 | 命中延迟 |
| `--policy` | choice | **`LRU`** | `FIFO` / `LRU` / `LFU` | 选择策略 |

- **默认策略为 LRU**，当前支持 FIFO/LRU/LFU；策略名→类的注册表位于 A 的 `cli.py`。
- 错误处理：参数非法/越界由 argparse 报错并以非零退出码结束；解析或校验失败
  （B 的 `InputValidationError`）由 CLI 捕获、打印文件/行号信息，非零退出。
- CLI 只负责：解析参数 → 调 B 的 `load_inputs` → 构造策略与引擎 → `process_all` →
  把事件交给 B 的 Metrics/Output；**不重写引擎逻辑、不自行计算指标**。

---

## 7. 模块边界与依赖关系

| 模块 | 负责人 | 职责 | 明确不做 |
| --- | --- | --- | --- |
| Parser | B | CSV 读取/校验，产出 Resource/Request | 不做缓存/统计 |
| Engine | A | 共享缓存、容量、命中判定、淘汰调度、发事件 | 不解析、不统计、不格式化、不写死策略 |
| Strategy | C / D | 维护淘汰/准入所需状态并返回决策 | 不持有容量、不直接增删缓存 |
| Metrics | B | 消费事件，唯一负责累计与指标 | 不修改事件 |
| Output | B | 格式化为 10 列等并保存 | 只读事件，不重算 |
| Experiment Runner | E | 批量实验、运行隔离、固定种子 | 不跨运行复用引擎/策略状态 |

依赖方向（无环）：

```
CLI ──> Parser(B) ──> models
 │        │
 ├─> Strategy(C/D) ──> models
 ├─> Engine(A) ──> models + Strategy 接口
 └─> Metrics/Output(B) ──> 消费 RequestResult
Experiment Runner(E) ──> CLI/Engine + Parser + Strategy（每次新建实例）
```

---

## 8. 独立运行隔离

- 每次独立运行：新建 Engine 与 Strategy，初始缓存为空；`reset()` 同时清空缓存、
  字节计数、已处理序号与策略状态。
- Experiment Runner 不得在不同策略/容量/负载间复用可变缓存状态；
  随机负载必须记录种子以保证可复现。

---

## 9. 命名与结构决定（原冲突点的最终裁决）

### 9.1 保留 `select_victim`，不改为 `choose_victim`

二者语义等价。现有引擎、C 的三个策略与全部测试均已使用 `select_victim`；
改名是纯成本、零功能收益的破坏性变更。v1 冻结 `select_victim`。

### 9.2 `should_admit` 默认 True、旧策略兼容、Custom 拒绝待确认

见 §3.3、§4.3。标准策略必须始终允许准入且行为不变；Custom 能否实际拒绝以
组长/助教确认（§12）为前提；拒绝后仍按 miss 计、不淘汰不插入。

### 9.3 CacheEntry 保持 OrderedDict 逻辑表达，不重构

见 §2.4。插入顺序由 OrderedDict 保证，访问顺序由策略自管，二者不混淆。

---

## 10. 与现有代码的差异清单（已落地的净变更）

1. 新增 `should_admit`：Protocol 描述 + 引擎一个调用点（旧策略默认 True 兼容）。
2. 命名：冻结 `select_victim`，未改代码。
3. CacheEntry：定义为逻辑概念，未新增类、未重构。
4. 新增 CLI 模块（`cli.py`、`__main__.py`），不影响现有模块。
5. 新增 HOWTO、依赖记录与 pytest 开发依赖（文档/环境）。
6. `RequestResult` 现状已满足"无累计列"，无需改动。

---

## 11. 决策记录（队长授权 A 统一，已关闭）

- 策略方法集合与命名：见 §3、§9.1。
- `should_admit` 签名与默认行为：见 §3.3。
- CacheEntry 物理实现：见 §2.4、§9.3。
- CLI 默认策略与参数：见 §6。
- 模块归属：Metrics/Output 归 B，Experiment Runner 归 E（见 §7）。

---

## 12. Future Extensions（不影响当前 v1）

以下为未来**可能**需要的扩展，当前均未实现，也不得改变 v1 的行为或签名。
当前代码已为其中部分预留适配点；任何扩展在正式提出前都不构成依赖。

1. **准入决策使用 `client_id` 或完整 `Request`**：若 D 的自定义策略需要按客户端
   做公平性决策，可将 `should_admit` 扩展为接收 `Request`；当前签名仅接收 `Resource`。
2. **独立 `CacheEntry` dataclass**：若未来确需显式 `insertion_sequence` 字段，
   可在不改变事件输出的前提下新增；v1 暂不引入。
3. **`--output` 参数**：待 B 的 Output 模块定型后，在 CLI 增加输出位置参数；
   当前 `render_events` 是该适配点。
4. **注册表扩展自定义策略名**：D 的自定义策略完成后，将其名字与构造器加入
   `POLICY_REGISTRY`，不改变现有 FIFO/LRU/LFU 映射。
5. **Custom Policy 选择性准入的课程合规性**：关联 issue #10。Engine 已保留
   `should_admit` 兼容接口，但在组长/助教明确确认前，D 不得在最终 Custom Policy
   中实际使用拒绝准入；FIFO/LRU/LFU 始终允许准入。若课程不允许，所有策略返回
   True 即可，无需改动引擎。此条与 §3.3 一致。
