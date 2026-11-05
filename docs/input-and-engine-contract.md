# 输入解析与缓存引擎契约

本文件记录 issue #4 与 #5 的实现约定，供策略、指标和 CLI 模块接入。

## 输入解析

- `resources.csv` 必须依次包含 `scheme,host,path,status_code,content_type,size_bytes,origin_latency_ms,cache_control`。
- 请求 CSV 必须依次包含 `timestamp,client_id,method,scheme,host,path`。
- CSV 使用 Python 标准库 `csv` 解析，因此引号内的逗号会被视为字段内容。
- 资源唯一键为 `(scheme, host, path)`。重复键、未知请求资源、非 `GET` 请求、非法大小、延迟和时间戳都会抛出 `InputValidationError`，错误信息包含文件、行号及可用时的资源键。
- 请求先按时间戳稳定排序，再分配从 1 开始的 `sequence`。时间戳相同的请求保持原文件顺序。
- `size_bytes` 和容量均使用字节。大小必须是非负整数；延迟必须是非负有限数。
- 只有表头或完全为空的请求文件合法并解析为空请求序列。非空内容缺少表头或字段不完整则报错。

## 共享缓存引擎

- `SharedCacheEngine` 默认容量为 `102400` 字节，默认命中延迟为 `5.0` ms；两者均可通过构造参数修改。
- 缓存按 `ResourceKey` 共享，所有客户端访问同一资源时只有一个副本。
- 未命中且资源大小不超过容量时，引擎调用策略选择受害者并连续淘汰，直到资源能够放入后插入。
- 资源大小恰好等于容量时可以缓存；超过容量时不插入、不淘汰，也不改变已有缓存和策略状态。
- 命中响应时间只使用配置的 `hit_latency_ms`；未命中使用资源的 `origin_latency_ms`，不叠加命中延迟。
- 每次处理请求都会产生一个 `RequestResult`。事件包含请求、HIT/MISS、淘汰顺序、插入顺序、已用字节、响应时间和本次源站流量。指标累计由 #8 的事件消费者负责，引擎不重复计数。
- `reset()` 同时清空缓存、字节计数、已处理请求序号和策略状态。新的独立实验也可直接创建新的引擎实例。

## 策略接口

策略实现 `EvictionPolicy` 协议：

- `on_hit(key, step)`：观察一次命中。
- `on_insert(key, step)`：观察一次已提交的插入。
- `select_victim(resident_keys, step)`：从当前驻留键中选择淘汰对象。
- `on_evict(key, step)`：观察一次已提交的淘汰。
- `reset()`：清空策略状态。

引擎负责驻留集合和字节容量；策略只维护选择受害者所需状态。若策略返回非驻留资源键，引擎会抛出 `PolicyContractError`。
