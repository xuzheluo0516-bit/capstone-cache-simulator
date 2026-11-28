# 课程提供 trace 上的实验结果

> 脚本:`d_experiments/course/run_course.py`;作图:`d_experiments/course/make_course_plots.py`;
> 结果表:`data/results/course/`;图:`data/results/figures/course_*.png`;
> 固定的设置与披露:`d_experiments/course/COURSE_PREREGISTRATION.md`。
> 复现:`python d_experiments/course/run_course.py --output-dir data/experiments/course`。

## 1. 设置
课程提供三个 trace(sequential、repetitive、mixed,各 3000 个请求)和同一个 `resources.csv`(21 个资源)。
我们在这三个 trace 上运行 FIFO、LRU、LFU、GDSF、RW-CSF,六档容量:100 KiB、500 KiB、1 MiB、2 MiB、
**5 MiB(课程标准容量)**、10 MiB,共 90 次运行。trace 是固定文件,结果完全确定,没有种子和标准差,
也没有做显著性检验,所以差距小于约 1% 的不当作有区别。

**H 固定为 20,没有在这三个 trace 上重新调参。** 它是在合成调参 trace 上按预先规则选出的。
事后诊断显示这个值对课程 trace 偏小,见第 5 节;我们如实报告,不替换。

新增指标的定义:淘汰次数 = 被驱逐的资源总数;超大请求 = 资源大小大于缓存容量的请求数;
平均缓存利用率 = 每个请求处理后已用字节占容量的比例,对全部请求取平均。
这三项由实验脚本根据引擎事件计算,模拟器核心和命令行的汇总输出没有改动。

## 2. 工作负载特征(课程要求的 7 项)
| 负载 | 请求数 | 不同资源 | 客户端 | 请求数据总量(GiB) | 大于 5 MiB 的请求 |
|---|---|---|---|---|---|
| sequential | 3000 | 21 | 6 | 14.75 | 288 |
| repetitive | 3000 | 21 | 6 | 4.08 | 50 |
| mixed | 3000 | 21 | 6 | 13.07 | 234 |

最常被请求的五个资源:

| 负载 | 前五名资源(请求数) |
|---|---|
| sequential | learn.university.edu/static/main.css(148); pypi.org/project/requests/(148); video.university.edu/media/networking-demo-720p.mp4(148); cdn.university.edu/images/campus-banner.webp(147); learn.university.edu/api/course/ics/announcements(147) |
| repetitive | learn.university.edu/courses/ics/lecture08.pdf(680); learn.university.edu/static/logo.svg(666); learn.university.edu/static/app.js(630); learn.university.edu/courses/ics/index.html(629); library.university.edu/articles/cache-replacement.pdf(34) |
| mixed | developer.mozilla.org/static/assets/main.css(188); learn.university.edu/static/main.css(187); learn.university.edu/static/app.js(185); video.university.edu/media/intro-to-os-720p.mp4(173); library.university.edu/articles/cache-replacement.pdf(170) |

图:`course_workload_distribution.png`(每个负载里各资源的请求数,深色为大于 5 MiB、永远无法缓存的资源)。

- **sequential 并不是"几乎没有重复":** 21 个资源的请求数都在 136 到 148 之间,热度接近均匀,没有突出的热门。
- **repetitive 高度集中:** 前 4 个资源占 2605 个请求(86.8%)。其中 lecture08.pdf 大小为 2.16 MiB,
  比 2 MiB 容量还大,所以容量不超过 2 MiB 时它放不下。
- **mixed:** 16 个资源各约 150 至 188 次,另外 5 个资源各约 59 至 79 次。
- 两个视频(约 42 MiB 和 57 MiB)大于所有容量档,在 sequential 和 mixed 中分别带来 288 和 234 个永远无法缓存的请求,
  使这两个负载里约 95% 以上的请求字节只能从源站取回(LRU 在 5 MiB 下,sequential 97%,mixed 94.8%)。

## 3. 从特征推出的预期
这些预期是看过一次探索性试跑之后写的,不是确认性预测(见 `COURSE_PREREGISTRATION.md`):
sequential 热度均匀,大小和延迟信息应比频率更有用;repetitive 在 2 MiB 到 5 MiB 之间出现断崖;
mixed 里大小感知策略占优;两个视频使字节命中率很低、源站流量几乎不随策略变化。

## 4. 结果

### 4.1 策略对比(5 MiB,课程标准容量)
| 负载 | 策略 | 平均响应(ms) | 请求命中率 | 字节命中率 | 源站流量(MiB) | 淘汰次数 | 超大请求 | 平均利用率 |
|---|---|---|---|---|---|---|---|---|
| sequential | FIFO | 260.10 | 45.7% | 2.9% | 14671 | 1324 | 288 | 77.0% |
| sequential | LRU | 254.39 | 48.2% | 3.0% | 14646 | 1251 | 288 | 80.4% |
| sequential | LFU | 223.16 | 65.7% | 3.2% | 14615 | 724 | 288 | 69.9% |
| sequential | GDSF | **191.28** | 85.0% | 3.8% | 14523 | 143 | 288 | 84.6% |
| sequential | RW-CSF | 196.77 | 81.1% | 3.6% | 14557 | 262 | 288 | 82.8% |
| repetitive | FIFO | 47.40 | 91.8% | 38.8% | 2558 | 184 | 50 | 82.3% |
| repetitive | LRU | 44.91 | 92.9% | 39.3% | 2534 | 151 | 50 | 81.3% |
| repetitive | LFU | 43.35 | 94.0% | 39.4% | 2530 | 117 | 50 | 77.6% |
| repetitive | GDSF | **39.72** | 96.0% | 39.4% | 2530 | 53 | 50 | 80.7% |
| repetitive | RW-CSF | 41.50 | 94.9% | 39.4% | 2529 | 89 | 50 | 82.7% |
| mixed | FIFO | 191.44 | 69.5% | 5.2% | 12693 | 672 | 234 | 80.6% |
| mixed | LRU | 193.18 | 68.5% | 5.2% | 12697 | 699 | 234 | 78.4% |
| mixed | LFU | 184.69 | 78.7% | 5.0% | 12715 | 389 | 234 | 84.0% |
| mixed | GDSF | **168.35** | 85.8% | 4.9% | 12726 | 174 | 234 | 79.2% |
| mixed | RW-CSF | 173.40 | 82.6% | 5.0% | 12726 | 269 | 234 | 76.9% |

图:`course_policy_comparison_5MiB.png`。每个负载最低的平均响应时间加粗。

### 4.2 容量的影响(平均响应时间,ms)
| 负载 | 容量 | FIFO | LRU | LFU | GDSF | RW-CSF |
|---|---|---|---|---|---|---|
| sequential | 100K | 325.1 | 325.1 | 327.5 | **322.2** | 322.3 |
| sequential | 500K | 294.8 | 294.8 | 289.5 | **272.4** | 283.1 |
| sequential | 1M | 285.3 | 285.3 | 282.7 | **263.9** | 267.8 |
| sequential | 2M | 295.2 | 295.2 | 273.6 | **268.0** | 270.1 |
| sequential | 5M | 260.1 | 254.4 | 223.2 | **191.3** | 196.8 |
| sequential | 10M | **166.3** | **166.3** | **166.3** | **166.3** | **166.3** |
| repetitive | 100K | 206.6 | 206.0 | 205.4 | 205.3 | **205.2** |
| repetitive | 500K | 185.0 | 182.2 | 181.1 | **177.5** | 178.9 |
| repetitive | 1M | 180.2 | 178.0 | 176.1 | **173.8** | 175.8 |
| repetitive | 2M | 174.3 | 174.1 | 173.1 | **170.7** | 172.2 |
| repetitive | 5M | 47.4 | 44.9 | 43.4 | **39.7** | 41.5 |
| repetitive | 10M | **34.2** | **34.2** | **34.2** | **34.2** | **34.2** |
| mixed | 100K | 309.5 | 309.2 | 306.9 | **301.0** | 301.0 |
| mixed | 500K | 285.1 | 284.0 | 291.4 | **260.5** | 261.1 |
| mixed | 1M | 274.5 | 272.2 | 260.3 | 246.4 | **246.4** |
| mixed | 2M | 258.3 | 257.1 | 250.7 | **233.0** | 235.0 |
| mixed | 5M | 191.4 | 193.2 | 184.7 | **168.4** | 173.4 |
| mixed | 10M | **141.3** | **141.3** | **141.3** | **141.3** | **141.3** |

图:`course_response_time_vs_capacity.png`、`course_hit_rate_vs_capacity.png`、`course_evictions_vs_capacity.png`。
mixed 在 1 MiB 时 GDSF 与 RW-CSF 相同(取一位小数);repetitive 在 100 KiB 时最快与最慢的策略相差约 0.7%(205.2 对 206.6 ms)。

### 4.3 对各客户端的影响(mixed,5 MiB)
图:`course_per_client_mixed_5MiB.png`;数据:`course_clients.csv`、`course_fairness.csv`。

| 策略 | Jain 指数(各客户端请求命中率) | 最差客户端 | 最差客户端平均响应(ms) |
|---|---|---|---|
| FIFO | 0.989 | student-04 | 331.5 |
| LRU | 0.983 | student-04 | 335.0 |
| LFU | 0.977 | student-04 | 344.5 |
| GDSF | 0.994 | student-04 | 303.4 |
| RW-CSF | 0.991 | student-04 | 310.5 |

RW-CSF 相对 LRU 让**每个**客户端的平均响应时间都下降,幅度从 14.7 ms(student-01)到 27.9 ms(student-05);
相对 GDSF 每个客户端都慢 2.0 至 13.6 ms;相对 LFU,student-01 和 student-02 反而慢
8.9 ms 和 4.9 ms,其余四个客户端快 18.7 至 34.0 ms。

## 5. 诊断:RW-CSF 与 H(探索性,不用于选 H)
| 负载 | H=5 | H=20(正式) | H=100 | H=500 | H=∞ | GDSF |
|---|---|---|---|---|---|---|
| sequential | 214.1 | 196.8 | 191.3 | 191.3 | 191.3 | 191.3 |
| repetitive | 43.7 | 41.5 | 39.9 | 39.5 | 39.4 | 39.7 |
| mixed | 182.1 | 173.4 | 167.8 | 167.0 | 166.9 | 168.4 |

(5 MiB 下的平均响应时间,ms;完整结果见 `course_h_sensitivity.csv`。)
`scripts/audit_results.py` 对这张探索性表的全部 90 行逐行从原始 trace 用独立 RW-CSF 计算路径重算
`average_response_ms` 和 `request_hit_rate`;因此该表除结构和参数外,数值也纳入审计。
H 从 5 到 ∞,sequential 变化 12.0%、repetitive 11.0%、mixed 9.1%;H ≥ 100 时 RW-CSF 与 GDSF 基本相同,
H=∞(不衰减)在 mixed 和 repetitive 上甚至略好于 GDSF。这说明:
1. 这三个 trace 的热度分布是稳定的,衰减没有东西可以"忘记",固定的 H=20 反而丢掉了有用的历史频率,
   所以正式结果里 RW-CSF 比 GDSF 慢 2.9% 至 4.5%。
2. 之前在合成负载上得到的"RW-CSF 对 H 不敏感(四档只差 0.4%)"**不能推广**:在课程 trace 上 H 的影响约 9% 至 12%。
3. 这与之前的消融和漂移结果一致:衰减只在热点漂移的负载里有用,在热度稳定的负载里是代价。

我们没有把正式 H 改成 100,因为那是看过这些 trace 的结果之后才选的。如果团队决定改用 H=100,
报告里必须写明"H 在课程 trace 上重选",并把选择过程与这张表一并给出。

## 6. 回答课程的五个问题
1. **哪个策略最好,按什么指标?** 按平均响应时间和请求命中率,GDSF 在 5 MiB 下的三个负载上都最好;
   RW-CSF 第二,比 GDSF 慢 2.9%(sequential)、4.5%(repetitive)、3.0%(mixed),
   比 LFU 快 11.8%、4.3%、6.1%,比 LRU 快 22.7%、7.6%、10.2%,比 FIFO 快 24.3%、12.5%、9.4%。
   六档容量里,在 10 MiB 以下的 15 个(负载,容量)组合中,RW-CSF 总是第一或第二。
   按字节命中率和源站流量,策略之间几乎没有差别(5 MiB 下 sequential 和 mixed 的字节命中率只有 3% 至 5%)。
2. **负载特征如何影响策略表现?** sequential 热度均匀、大文件多,策略间差距最大(5 MiB 下 FIFO 260 ms 对 GDSF 191 ms),
   频率信息帮助有限,大小感知的 GDSF 和 RW-CSF 受益最多;repetitive 里 4 个热门资源占 87%,
   只要热门资源放得下(5 MiB),所有策略都大幅下降,策略间差距缩小到 47 对 40 ms;
   mixed 介于两者之间。无法缓存的两个视频让 sequential 和 mixed 的字节命中率很低。
3. **容量增大对相对表现的影响?** 容量很小(100 KiB)时几乎放不下什么,策略差距最小(sequential 约 1%);
   容量中等(500 KiB 到 5 MiB)差距最大;repetitive 在 2 MiB 与 5 MiB 之间断崖式下降
   (172 对 41 ms,因为 2.16 MiB 的 lecture08.pdf 终于放得下);10 MiB 时所有可缓存的资源都放得下,
   五个策略完全相同(166.3、34.2、141.3 ms)。
4. **整体改善是否让所有客户端同等受益?** 不是同等,但相对 LRU 每个客户端都受益(见 4.3)。
   mixed 在 5 MiB 下各客户端较相似,Jain 指数 0.977 至 0.994,最差客户端在所有策略下都是 student-04。
   sequential 差异大得多:5 MiB 下 FIFO 为 0.670、LRU 为 0.624,而 LFU 0.952、GDSF 0.997、RW-CSF 0.990;
   在 500 KiB 至 2 MiB,FIFO/LRU 的 Jain 约 0.56 至 0.58,GDSF/RW-CSF 约 0.91 至 0.95。
   也就是说,大小感知的策略(GDSF、RW-CSF)在 sequential 上明显让各客户端更均衡。
5. **自定义策略带来什么取舍?** 在课程 trace 上,RW-CSF 没有胜过 GDSF(慢 2.9% 至 4.5%),
   好于 FIFO、LRU、LFU;额外的代价是每个资源要保存衰减后的频率和上次访问序号,
   并要选 H。H=20 在这三个 trace 上偏小,每次决定都比 GDSF 多淘汰一些(5 MiB 下淘汰 89 至 269 次,GDSF 为 53 至 174 次)。
   我们没有实现准入拒绝,所以大文件仍会在插入时挤走别的资源。

### 补充问题
- **命中率最高的策略淘汰次数最少吗?** 是。5 MiB 下 GDSF 在三个负载上同时具有最高命中率和最少淘汰次数。
- **更高的命中率就意味着更少的源站流量吗?** 不一定。mixed 5 MiB 下 GDSF 命中率最高(85.8%),
  源站流量却最大(12726 MiB,FIFO 为 12693 MiB);差距只有 0.3%,因为约 95% 的流量来自无法缓存的视频。
- **资源大小如何影响替换?** 按大小归一化的策略(GDSF、RW-CSF)倾向保留小而常用的资源,因此命中率高、淘汰次数少;
  大文件被先淘汰,但字节命中率并没有因此提高(见各表)。
- **超大资源如何影响命中率和字节命中率?** 它们每次都是未命中且不占缓存,拉低命中率上限
  (sequential 有 9.6%、mixed 7.8%、repetitive 1.7% 的请求永远不可能命中),并使字节命中率远低于请求命中率。

## 验证
`tests/test_course_traces.py` 里有一个独立重写的模拟器:FIFO、LRU、LFU 按课程文字写成,GDSF 和 RW-CSF 按定义写成,
其中 RW-CSF 的衰减频率用访问历史的显式求和计算(策略类里是增量更新)。它在全部 90 个(负载、容量、策略)组合上,
命中数、源站流量、淘汰次数、超大请求数、平均响应时间、平均缓存利用率、命中率和字节命中率都与实验结果一致。
`scripts/audit_results.py` 现在也审计 `data/results/course/`(manifest、输入文件哈希、源码哈希、各表的完整性)。

## 7. 局限
- trace 固定,没有重复运行,所以没有标准差和显著性检验;约 1% 以内的差距不能解读。
- H=20 来自合成 trace,对这三个 trace 偏小(第 5 节)。第 5 节的诊断是看过结果之后做的,只用于解释。
- 容量档是我们按课程示例选的(第六档 2 MiB 是我们补的)。
- 公平性只用 Jain 指数(按各客户端请求命中率)和最差客户端描述,没有做进一步的客户端级分析。
- 没有实现准入拒绝。
