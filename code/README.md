# 面向跨机构金融风控的隐私保护数据共享方案设计与实现

本仓库是本科毕业论文《面向跨机构金融风控的隐私保护数据共享方案设计与实现》的配套原型代码。项目面向银行、支付平台、电商平台等机构之间的联合风控场景，目标是在不直接交换原始用户标识和明细风险数据的前提下，完成高风险用户集合的隐私对齐，并在交集对象上输出约定范围内的统计结果。

系统基于两方半诚实模型实现。代码保留哈希基线和DH PSI作为对照方案，以ECDH PSI作为主要求交路线，并实现Socket ECDH PSI工程通信版本，用于评估消息帧封装、序列化、进程调度和通信量对端到端性能的影响。交集统计部分实现明文统计演示和可加统计掩码合成流程，用于支撑论文中“隐私对齐+交集联合统计”的整体方案。

## 核心功能

1. **实验数据生成**
   - 生成两方CSV数据文件。
   - 支持控制单方数据规模、交集比例和随机种子。
   - 保证预设交集规模可验证、实验输入可复现。

2. **PSI隐私对齐**
   - 哈希基线：仅作为不安全性能基线。
   - DH PSI：大整数模幂Diffie-Hellman双盲化对照方案。
   - ECDH PSI：基于椭圆曲线点乘的主要求交路线。
   - Socket ECDH PSI：在ECDH PSI基础上加入Socket通信封装的工程通信版本。

3. **交集统计与聚合**
   - 明文统计演示：展示交集对象上的统计口径。
   - 可加统计掩码合成：支持计数、求和、分桶统计等可加型指标。

4. **实验评测与图表生成**
   - 输出benchmark明细、汇总表和论文表格。
   - 生成总体耗时、交集比例影响、通信量和分阶段耗时图。
   - 记录协议耗时、端到端耗时、通信量、分阶段耗时和正确性校验结果。

## 项目结构

| 路径 | 说明 |
|---|---|
| `main.py` | 主流程入口，执行数据生成、PSI求交、交集校验、统计聚合和结果汇总 |
| `data/generate_data.py` | 生成两方实验CSV，支持数据规模、交集比例和随机种子控制 |
| `baseline/hash_psi.py` | 哈希基线求交方案，仅用于性能对照 |
| `psi/dh_psi.py` | DH PSI大整数模幂Diffie-Hellman双盲化对照方案 |
| `psi/ecdh_psi.py` | ECDH PSI主要求交路线，使用Hash-to-Scalar、椭圆曲线点乘和压缩点编码 |
| `psi/socket_ecdh_psi.py` | Socket ECDH PSI工程通信版本，包含消息帧、双进程通信和通信量统计 |
| `aggregation/secure_agg.py` | 明文统计演示与可加统计掩码合成 |
| `eval/benchmark.py` | 多规模、多比例、多方法性能评测与图表生成 |
| `eval/stats_schema.py` | benchmark统计字段规范化 |
| `requirements.txt` | Python依赖列表 |

## 环境准备

建议使用Python 3.13。进入项目根目录后安装依赖：

```powershell
pip install -r requirements.txt
```

核心依赖包括：

```text
pandas
numpy
matplotlib
coincurve
```

## 运行项目主流程

项目主流程入口是`main.py`。在项目根目录运行：

```powershell
python main.py
```

默认参数为：

```text
total_ids = 1000
intersection_ratio = 0.004
seed = 2026
```

指定数据规模、交集比例和随机种子：

```powershell
python main.py --total-ids 1000 --intersection-ratio 0.01 --seed 2026
```

跳过Socket ECDH PSI工程通信版本：

```powershell
python main.py --total-ids 1000 --intersection-ratio 0.01 --seed 2026 --skip-socket
```

只运行可加统计掩码合成，跳过明文统计演示：

```powershell
python main.py --skip-plain-agg
```

关闭PSI交集一致性校验：

```powershell
python main.py --no-validate
```

主流程会依次执行：

```text
数据生成 -> 哈希基线 -> DH PSI -> ECDH PSI -> Socket ECDH PSI -> 交集一致性校验 -> 交集统计与聚合 -> 结果汇总
```

## 运行实验评测

论文实验和图表生成入口是`eval/benchmark.py`。推荐命令如下：

```powershell
python eval/benchmark.py --sizes 1000,5000 --ratios 0.01,0.1 --repeats 1 --seed 2026
```

该命令会按照两种数据规模、两种交集比例和四种求交方法运行实验：

```text
hash_baseline
dh
ecdh
socket_ecdh
```

不运行Socket ECDH PSI：

```powershell
python eval/benchmark.py --sizes 1000,5000 --ratios 0.01,0.1 --repeats 1 --seed 2026 --no-socket
```

指定输出目录：

```powershell
python eval/benchmark.py --sizes 1000,5000 --ratios 0.01,0.1 --repeats 1 --seed 2026 --out-dir eval
```

指定Socket通信量图的采样规模：

```powershell
python eval/benchmark.py --sizes 1000,5000 --ratios 0.01,0.1 --repeats 1 --seed 2026 --comm-sizes 1000,1500,2000,2500,3000,3500,4000,4500,5000
```

如果不显式指定`--comm-sizes`，程序会在最小和最大`sizes`之间默认每500条生成一个Socket通信量采样点，用于展示通信量随数据规模的近似线性增长趋势。

## Benchmark输出文件

运行`eval/benchmark.py`后，默认在`eval/`目录生成以下文件：

| 文件 | 说明 |
|---|---|
| `benchmark_detail.csv` | 每次实验运行的明细结果 |
| `benchmark_summary.csv` | 按数据规模、交集比例和方法聚合后的汇总结果 |
| `benchmark_table4_1.csv` | 论文表4.1使用的精简表格 |
| `benchmark_comm_detail.csv` | Socket ECDH PSI通信量图专用采样结果 |
| `../average.csv` | 根目录下的均值结果文件，内容与本次benchmark汇总均值一致 |
| `run_meta.json` | 实验参数、运行环境和依赖版本 |
| `benchmark_by_size.png` | 不同数据规模下各方法协议耗时对比 |
| `benchmark_by_ratio.png` | 不同交集比例下各方法协议耗时对比 |
| `benchmark_comm_bytes_by_size.png` | Socket ECDH PSI通信量随数据规模变化 |
| `benchmark_phase_breakdown_ecdh.png` | ECDH PSI分阶段耗时结构 |
| `benchmark_phase_breakdown_socket_ecdh.png` | Socket ECDH PSI主要子阶段耗时结构 |
| `benchmark_result.png` | 与`benchmark_by_size.png`内容一致的兼容图名 |

## CSV字段说明

核心字段如下：

| 字段 | 含义 |
|---|---|
| `total_ids` | 单方输入数据规模 |
| `intersection_ratio` | 预设交集比例 |
| `expected_intersection_size` | 数据生成阶段预设交集规模 |
| `actual_intersection_size` | PSI方法实际输出交集规模 |
| `is_correct` | 实际交集规模是否等于预设交集规模 |
| `protocol_elapsed_ms` | PSI方法内部统计的协议核心耗时，单位为ms |
| `end_to_end_elapsed_ms` | 从外部调用开始到结束的端到端耗时，单位为ms |
| `comm_bytes` | A、B两端发送与接收字节数之和；哈希基线、DH PSI和ECDH PSI为协议逻辑通信量估算，Socket ECDH PSI为实际Socket收发统计 |
| `phase_map_ms` | ECDH PSI中标识映射或曲线点构造阶段耗时 |
| `phase_blind_ms` | ECDH PSI中盲化阶段耗时 |
| `phase_blind_a_ms` | Socket ECDH PSI中A侧第一轮盲化相关耗时 |
| `phase_blind_b_ms` | Socket ECDH PSI中B侧处理相关耗时 |
| `phase_blind_back_ms` | Socket ECDH PSI中回传盲化相关耗时 |
| `phase_compare_ms` | 双重盲化结果集合比较耗时 |

## 方法说明

### 哈希基线

`baseline/hash_psi.py`对`user_id`进行SHA-256哈希后求交。该方法速度快，但不能抵抗离线字典枚举和链接分析，仅作为不安全性能基线。

### DH PSI

`psi/dh_psi.py`实现大整数模幂Diffie-Hellman双盲化对照方案。核心形式为：

```text
Z(u)=g^{h(u)} mod p
A_1(x)=Z(x)^a mod p
B_1(y)=Z(y)^b mod p
B_2(x)=A_1(x)^b=g^{ab h(x)} mod p
A_2(y)=B_1(y)^a=g^{ab h(y)} mod p
```

该方法用于对照实验和公式说明，不作为主要求交路线。

### ECDH PSI

`psi/ecdh_psi.py`实现基于椭圆曲线点乘的主要求交路线。实现流程为：

```text
Hash-to-Scalar -> Q(u)=h(u)P -> 双重盲化 -> 压缩点编码比较
```

该实现使用secp256k1曲线和`coincurve`库，采用Hash-to-Scalar后乘基点的工程实现方式，不等同于标准Hash-to-Curve。

### Socket ECDH PSI

`psi/socket_ecdh_psi.py`在ECDH PSI基础上加入双进程Socket通信封装。该版本使用长度前缀、消息类型和压缩点列表payload传输协议消息，并统计A、B两端发送和接收字节数之和。

### 交集统计与可加统计掩码合成

`aggregation/secure_agg.py`包含交集统计演示和可加统计掩码合成。可加统计掩码合成流程为：

```text
m = v_A + r
t = m + v_B
v = t - r = v_A + v_B
```

该流程适用于计数、求和、分桶统计等可加型指标，不覆盖排序、Top-k、最大值等非线性任务。

## 数据文件说明

运行主流程或benchmark时，程序会在`data/`目录生成或覆盖实验CSV文件，例如：

```text
data/party_A.csv
data/party_B.csv
data/bench_A.csv
data/bench_B.csv
```

这些文件是实验输入和中间数据，可以通过重新运行命令生成。

## 复现建议

快速检查主流程：

```powershell
python main.py --total-ids 1000 --intersection-ratio 0.01 --seed 2026 --skip-socket
```

完整运行主流程：

```powershell
python main.py --total-ids 1000 --intersection-ratio 0.01 --seed 2026
```

生成论文实验结果和图表：

```powershell
python eval/benchmark.py --sizes 1000,5000 --ratios 0.01,0.1 --repeats 1 --seed 2026
```

如果需要记录十次实验并计算均值：

```powershell
python eval/benchmark.py --sizes 1000,5000 --ratios 0.01,0.1 --repeats 10 --seed 2026
```

该命令会在`eval/benchmark_detail.csv`中记录每一次运行，在`eval/benchmark_summary.csv`和根目录`average.csv`中记录十次实验的均值和标准差。

检查Python语法：

```powershell
python -m compileall .
```

## 注意事项

1. 本项目是本科毕业设计原型系统，不是工业级PSI或MPC平台。
2. 哈希基线仅用于性能对照，不满足严格隐私保护要求。
3. ECDH PSI是本文主要求交路线，Socket ECDH PSI用于观察工程通信开销。
4. `comm_bytes`统计的是双端发送和接收字节数之和；单进程方法使用逻辑通信量估算，Socket ECDH PSI使用实际Socket收发统计。
5. 当前可加统计掩码合成只覆盖可加型统计，不覆盖复杂非线性统计任务。
6. 如果修改数据生成、PSI实现或benchmark逻辑，应重新运行`eval/benchmark.py`并同步更新论文中的表格和图表。
