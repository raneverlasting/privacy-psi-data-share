# 面向跨机构金融风控的隐私保护数据共享方案设计与实现

本仓库是本科毕业论文《面向跨机构金融风控的隐私保护数据共享方案设计与实现》的配套原型代码。项目面向银行、支付平台、电商平台等机构之间的联合风控场景，目标是在不直接交换原始用户标识和明细风险数据的前提下，完成高风险用户集合的隐私对齐，并在交集对象上输出约定范围内的统计结果。

系统基于两方半诚实模型实现。代码保留哈希基线和DH PSI作为对照方案，以ECDH PSI作为主要求交路线，并实现Socket ECDH PSI工程封装版本，用于评估消息帧封装、序列化、解码校验和通信量对协议性能的影响。交集统计部分实现明文统计演示和可加统计掩码合成流程，用于支撑论文中"隐私对齐+交集联合统计"的整体方案。

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
   - 生成总体协议耗时、交集比例影响、通信量和分阶段耗时图。
   - 核心CSV只记录协议耗时、通信量和正确性校验结果。

## 项目结构

| 路径 | 说明 |
|---|---|
| `main.py` | 主流程入口，执行数据生成、PSI求交、交集校验、统计聚合和结果汇总 |
| `data/generate_data.py` | 生成两方实验CSV，支持数据规模、交集比例和随机种子控制 |
| `baseline/hash_psi.py` | 哈希基线求交方案，仅用于性能对照 |
| `psi/dh_psi.py` | DH PSI大整数模幂Diffie-Hellman双盲化对照方案，使用RFC 7919 ffdhe2048参数 |
| `psi/ecdh_psi.py` | ECDH PSI主要求交路线，使用Hash-to-Scalar、椭圆曲线点乘和压缩点编码 |
| `psi/socket_ecdh_psi.py` | Socket ECDH PSI工程封装版本，包含消息帧、序列化、解码校验和通信量统计 |
| `aggregation/secure_agg.py` | 明文统计演示与可加统计掩码合成 |
| `eval/benchmark.py` | 多规模、多比例、多方法性能评测与图表生成 |
| `eval/stats_schema.py` | benchmark统计字段规范化 |
| `eval/reproduce_ecdh_socket.py` | 只复现ECDH PSI和Socket ECDH PSI两组核心实验的精简脚本 |
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

## Benchmark输出文件

运行`eval/benchmark.py`后，默认在`eval/`目录生成以下文件：

| 文件 | 说明 |
|---|---|
| `benchmark_detail.csv` | 每次实验运行的明细结果 |
| `benchmark_summary.csv` | 与 `benchmark_table4_1.csv` 和 `../average.csv` 内容一致，均为论文展示格式的核心指标均值表 |
| `benchmark_table4_1.csv` | 论文表4.1使用的核心指标表格 |
| `../average.csv` | 根目录下的均值结果文件，字段与核心指标表一致 |
| `run_meta.json` | 实验参数、运行环境和依赖版本 |
| `benchmark_by_size.png` | 不同数据规模下各方法协议耗时对比 |
| `benchmark_by_ratio.png` | 不同交集比例下各方法协议耗时对比 |
| `benchmark_comm_bytes_by_size.png` | Socket ECDH PSI通信量随数据规模变化 |
| `benchmark_phase_breakdown_ecdh.png` | ECDH PSI分阶段耗时结构 |
| `benchmark_phase_breakdown_socket_ecdh.png` | Socket ECDH PSI分阶段耗时结构 |
| `benchmark_result.png` | 与`benchmark_by_size.png`内容一致的兼容图名 |

## 图片生成逻辑

所有PNG图均由`eval/benchmark.py`在实验完成后根据本次`summary`数据生成，不额外改变协议运行逻辑。图中方法名称统一使用`哈希基线`、`DH PSI`、`ECDH PSI`和`Socket ECDH PSI`。

| 图片文件 | 数据来源 | 横轴 | 纵轴 | 字段与含义 |
|---|---|---|---|---|
| `benchmark_by_size.png` | `benchmark_summary.csv`核心均值结果 | `total_ids`，即单方数据规模 | `protocol_elapsed_ms_mean`，即协议耗时均值 | 固定第一个交集比例`intersection_ratios[0]`，比较不同数据规模下各方法协议耗时 |
| `benchmark_result.png` | 与`benchmark_by_size.png`相同 | 与`benchmark_by_size.png`相同 | 与`benchmark_by_size.png`相同 | 兼容旧论文插图文件名，内容等同于`benchmark_by_size.png` |
| `benchmark_by_ratio.png` | `benchmark_summary.csv`核心均值结果 | `intersection_ratio`，即交集比例 | `protocol_elapsed_ms_mean`，即协议耗时均值 | 固定最大数据规模`sizes[-1]`，比较不同交集比例下各方法协议耗时 |
| `benchmark_comm_bytes_by_size.png` | `benchmark_summary.csv`核心均值结果 | `total_ids`，即单方数据规模 | `comm_bytes_mean / 1024`，即Socket ECDH PSI通信量均值，单位为KB | 固定第一个交集比例`intersection_ratios[0]`，只绘制Socket ECDH PSI通信量随规模变化 |
| `benchmark_phase_breakdown_ecdh.png` | 内部summary中的分阶段统计字段 | `total_ids`，即单方数据规模 | 分阶段耗时均值，单位为ms | 固定第一个交集比例`intersection_ratios[0]`，堆叠展示ECDH PSI的`映射`和`盲化` |
| `benchmark_phase_breakdown_socket_ecdh.png` | 内部summary中的分阶段统计字段 | `total_ids`，即单方数据规模 | 分阶段耗时均值，单位为ms | 固定第一个交集比例`intersection_ratios[0]`，堆叠展示Socket ECDH PSI的`映射`和`盲化` |

分阶段耗时图中的`映射`指双方将`user_id`规范化后执行Hash-to-Scalar，并构造曲线点`Q(u)=h(u)P`的过程。`盲化`指双方使用随机私有标量对曲线点执行点乘，包括第一轮盲化、二次盲化和回传盲化，最终得到可比较但不暴露原始ID的双重盲化结果。

## CSV字段说明

> `benchmark_detail.csv` 列名为英文原始字段（`total_ids`、`protocol_elapsed_ms` 等），下方核心字段表适用于 `benchmark_summary.csv` / `benchmark_table4_1.csv` / `average.csv`。

核心字段如下：

| 字段 | 含义 |
|---|---|
| `方法` | 实验方法展示名 |
| `数据规模/条` | 单方输入数据规模 |
| `交集比例` | 预设交集比例 |
| `交集规模/条` | PSI方法实际输出交集规模 |
| `协议耗时/ms` | PSI方法内部统计的协议核心耗时均值，单位为ms |
| `通信量/byte` | A、B两端发送与接收字节数之和；哈希基线、DH PSI和ECDH PSI为协议逻辑通信量估算，Socket ECDH PSI为实际Socket收发统计 |
| `校验结果` | 实际交集规模是否等于预设交集规模 |

## 方法说明

### 哈希基线

`baseline/hash_psi.py`对`user_id`进行SHA-256哈希后求交。该方法速度快，但不能抵抗离线字典枚举和链接分析，仅作为不安全性能基线。

### DH PSI

`psi/dh_psi.py`实现大整数模幂Diffie-Hellman双盲化对照方案，当前模数使用RFC 7919中的ffdhe2048安全素数群。核心形式为：

```text
Z(u)=g^{h(u)} mod p
A_1(x)=Z(x)^a mod p
B_1(y)=Z(y)^b mod p
B_2(x)=A_1(x)^b=g^{ab h(x)} mod p
A_2(y)=B_1(y)^a=g^{ab h(y)} mod p
```

该方法用于对照实验和公式说明，不作为主要求交路线。由于ffdhe2048群元素编码长度约为256 byte，DH PSI通信量和运行耗时都会明显高于ECDH PSI。

### ECDH PSI

`psi/ecdh_psi.py`实现基于椭圆曲线点乘的主要求交路线。实现流程为：

```text
Hash-to-Scalar -> Q(u)=h(u)P -> 双重盲化 -> 压缩点编码比较
```

该实现使用secp256k1曲线和`coincurve`库，采用Hash-to-Scalar后乘基点的工程实现方式，不等同于标准Hash-to-Curve。

### Socket ECDH PSI

`psi/socket_ecdh_psi.py`在ECDH PSI基础上加入Socket消息帧封装。为控制变量，该版本采用单进程顺序执行，不引入双进程并行加速；程序使用长度前缀、消息类型和压缩点列表payload模拟协议消息封装与解析，并统计A、B两端发送和接收字节数之和。

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

从新环境开始复现实验数据，并运行十次取均值生成根目录`average.csv`，可以按下面顺序执行：

```powershell
cd <项目根目录>
python -m pip install --upgrade pip
pip install -r requirements.txt
python test.py
python -m compileall .
python eval/benchmark.py --sizes 1000,5000 --ratios 0.01,0.1 --repeats 10 --seed 2026
```

执行完成后，重点查看以下文件：

```text
average.csv
eval/benchmark_detail.csv
eval/benchmark_summary.csv
eval/benchmark_table4_1.csv
eval/benchmark_by_size.png
eval/benchmark_by_ratio.png
eval/benchmark_comm_bytes_by_size.png
eval/benchmark_phase_breakdown_ecdh.png
eval/benchmark_phase_breakdown_socket_ecdh.png
```

其中，`eval/benchmark_detail.csv`记录十次实验的每次运行结果，`eval/benchmark_summary.csv`和`average.csv`记录十次实验后的核心指标均值。

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

该命令会在`eval/benchmark_detail.csv`中记录每一次运行，在`eval/benchmark_summary.csv`和根目录`average.csv`中记录十次实验后的核心指标均值，并同步生成实验图表。

只复现ECDH PSI和Socket ECDH PSI两组核心实验：

```powershell
python eval/reproduce_ecdh_socket.py --sizes 1000,5000 --ratio 0.01 --repeats 5 --seed 2026
```

该命令只运行`1000×0.01`和`5000×0.01`两组数据，方法只包含`ECDH PSI`和`Socket ECDH PSI`，输出文件为：

```text
eval/reproduce_ecdh_socket.csv
eval/reproduce_ecdh_socket_average.csv
```

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
