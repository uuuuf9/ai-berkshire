---
name: stock-research
description: "AI Berkshire skill: 股票研究：数据驱动 + 四大师框架 + HTML 可视化报告. Source: skills/stock-research.md."
---

## Codex adapter note

This skill is generated from `skills/stock-research.md` so Claude Code and Codex users share one canonical workflow.

- Treat `$ARGUMENTS` as the user's request in the current Codex thread.
- When the source mentions Claude-only surfaces such as Task, Agent, WebSearch, Bash, Read, or Write, use the closest Codex capability available in this session: subagents when available, web search when needed, shell commands for local tools, and normal file edits for workspace files.
- Use shared project tools from `tools/` in this repository. Prefer running commands from the repository root with paths like `python3 tools/financial_rigor.py ...`; if the current thread starts outside the repo, locate the actual checkout path first instead of assuming a fixed home-directory path.
- Before starting research, run the `date` command to confirm today's date; treat it as the baseline for "latest" data and state the data cutoff date in the report header. Never assume the current date from training data.
- Preserve the research quality rules from `AGENTS.md`: cross-check financial data, use exact arithmetic tools for valuation/math, and clearly label uncertainty and source gaps.

# 股票研究：数据驱动 + 四大师框架 + HTML 可视化报告

对 $ARGUMENTS（股票代码/名称）进行系统化研究：拉取并缓存数据，基于巴菲特/芒格/段永平/李录四大师理论和个人投资理念分析，最终产出包含交互式数据图表的 HTML 研究报告。

研究配置（数据来源、关注要点、分析依据）定义在仓库根目录 `require.md` 中。执行前先读取该文件，按其内容驱动研究；若 `require.md` 不存在则使用本文件内嵌的默认配置（见附录）。

---

## 数据缓存目录

所有拉取的数据分类缓存到 `/Users/wujiaqi/workspace/finanace-data-ws/finanace-data/`，后续研究可直接复用，避免重复拉取。

### 目录结构

```
finanace-data/
├── stock-data/{market}/{ticker}/          # 股票行情与估值数据
│   ├── quote.json                          # 实时/最近行情快照
│   ├── valuation.json                      # 估值指标（PE/PB/PS/EV等）
│   ├── price-10y.json                      # 近10年前复权价格序列
│   └── meta.json                           # 股票元信息（名称/行业/市值/总股本）
├── financial-report/{market}/{ticker}/    # 财报数据
│   ├── annual-5y.json                      # 近5年年报关键财务数据
│   ├── quarterly-latest.json               # 近一年最新季度财报
│   └── raw/                                # 原始财报文件或链接
├── industry-data/{sector}/                # 行业第三方权威数据
│   └── {source}-{YYYYMMDD}.json            # 按数据源和日期命名
├── price-history/{category}/              # 近10年关键价格（周期性行业）
│   └── {item}-{YYYYMMDD}.json
├── analysis-summary/{market}/{ticker}/    # 关注要点分析摘要
│   └── key-points-{YYYYMMDD}.json
└── ai-berkshire-report/{market}/{ticker}/  # HTML 研究报告输出
    └── {ticker}-research-{YYYYMMDD}.html
```

### 市场分类

| 输入特征 | market 值 | 股票数据源（主/副） | 财报数据源（主/副） |
|---------|-----------|-------------------|-------------------|
| 6位数字，6/9开头（沪）或0/3开头（深） | `a` | 东方财富 / 巨潮资讯 | 东方财富 / 巨潮资讯 |
| 4-5位数字或 `.HK` 后缀 | `hongkong` | aastocks / macrotrends ADR | 港交所披露易 / macrotrends ADR |
| 字母代码，无后缀或 `.US` | `american` | macrotrends / stockanalysis | macrotrends / stockanalysis |

### 数据复用规则

1. 拉取数据前先检查缓存目录是否已有同 ticker 的数据文件。
2. 若缓存数据在 **7 天内** 且文件完整，直接复用，跳过网络拉取（在报告中标注"数据来源：本地缓存"）。
3. 若缓存数据超过 7 天或不完整，重新拉取并覆盖（旧文件移入 `raw/archive-{旧日期}/`）。
4. 缓存文件统一使用 JSON 格式，包含 `fetched_at`（ISO 时间戳）、`sources`（来源列表）、`data`（数据体）三个字段。

---

## 研究流程

### 前置步骤：确认日期与读取配置

1. 运行 `date` 命令确认今日日期，作为"最新数据"基准，写入报告头部。
2. 读取仓库根目录 `require.md`，提取三类配置：
   - **关注要点**：利润/收入、存货规模、债务情况、公司及行业发展速度、风险、发展计划
   - **主要数据来源**：股票数据源、财报数据源、行业第三方权威数据源（按行业分类）、近10年关键价格源（按周期品类分类）
   - **分析依据**：巴菲特/芒格/段永平/李录四大师理论 + 个人投资理念（长期持有优秀企业、相信复利、长期相信 AI）

### 第一步：识别股票与行业

1. 根据输入的股票代码/名称，确定 market 分类（见上表）。
2. 拉取股票元信息（名称、所属行业、市值、总股本），写入 `stock-data/{market}/{ticker}/meta.json`。
3. A股可用 `python3 tools/ashare_data.py search {名称}` 搜索代码，`python3 tools/ashare_data.py quote {代码}` 获取行情。
4. 根据公司所属行业，从 `require.md` 的行业第三方数据源列表中匹配对应的数据源（如半导体→SEMI/WSTS/Gartner/TrendForce）。
5. 判断是否属于周期性行业；若是，从 `require.md` 的近10年关键价格列表中匹配需拉取的价格品类。

### 第二步：数据拉取与缓存

按 `require.md` 中的数据来源分四类拉取，每类数据写入对应缓存目录。

#### 2.1 股票数据 → `stock-data/{market}/{ticker}/`

> 数据源规范参见 `skills/financial-data.md`。价格序列统一使用**前复权**。

- **quote.json**：当前股价、涨跌幅、成交量、市值、总股本、52周高低
- **valuation.json**：PE(TTM)、PE(Forward)、PB、PS、EV/Revenue、EV/EBITDA、股息率
- **price-10y.json**：近10年月度/周度前复权收盘价序列（用于历史估值分位、长期趋势）
- A股优先用 `python3 tools/ashare_data.py quote {code}` 和 `python3 tools/ashare_data.py valuation {code}`

#### 2.2 财报数据 → `financial-report/{market}/{ticker}/`

- **annual-5y.json**：近5年年报数据，每年包含：
  - 收入、收入同比增速、分部收入明细
  - 净利润（GAAP）、净利润同比增速、毛利率、经营利润率、净利率
  - 自由现金流、经营现金流、资本支出
  - 总资产、总负债、资产负债率、有息负债、净现金/净债务
  - 存货、存货同比增速、存货周转天数
  - 应收账款、ROE、ROIC
  - 研发费用、研发费用率
- **quarterly-latest.json**：近一年最新4个季度的季度财报（同上字段，用于跟踪近期趋势）
- A股优先用 `python3 tools/ashare_data.py financials {code}` 获取核心财务数据
- 每个关键数据点须来自至少2个独立来源，误差>1%按 `skills/financial-data.md` 规则标记

#### 2.3 行业第三方权威数据 → `industry-data/{sector}/`

根据公司所属行业，从 `require.md` 匹配数据源并拉取：

| 行业 | 数据源（require.md 定义） | 关键数据 |
|------|------------------------|---------|
| 电子制造/PCB | Prismark | 市场规模、增速、份额 |
| 半导体 | SEMI/WSTS/Gartner/TrendForce | 设备出货、销售统计、市场预测、存储报价 |
| 新能源/光伏 | BloombergNEF/InfoLink/SolarPower Europe | 装机量、产业链价格 |
| 锂电池 | SNE Research/Benchmark MI | 装机量、产能预测 |
| 汽车 | 中汽协/MarkLines/JATO | 产销数据 |
| 石油/能源 | IEA/OPEC/EIA | 能源展望、库存产量 |
| 钢铁 | World Steel Association | 粗钢产量、表观消费量 |
| 有色金属 | LME/ICSG | 期货价格、供需数据 |
| 医药 | IQVIA/EvaluatePharma | 市场数据、研发预测 |
| 消费电子 | IDC/Counterpoint/Canalys | 出货量数据 |
| 农产品 | USDA/FAO | 供需报告、价格数据 |
| 航运 | Clarksons/波罗的海交易所 | BDI、运价数据 |
| 化工 | ICIS | 化工品价格与分析 |

拉取的数据包含：行业市场规模（历史+预测）、行业增速（历史+预测）、公司在行业中的份额与排名。

#### 2.4 近10年关键价格 → `price-history/{category}/`（仅周期性行业）

若公司属于周期性行业，从 `require.md` 匹配并拉取近10年关键价格序列：

| 品类 | 数据项 |
|------|-------|
| 存储 | 存储晶圆价格 |
| 石油 | 原油价格 |
| 贵金属 | 金/银/铂等价格 |
| 煤炭 | 动力煤/焦煤/焦炭价格 |
| 化工 | 原油/乙烯/PTA/纯碱价格 |
| 航运 | BDI/SCFI 指数 |
| 水泥 | 水泥价格指数 |

### 第三步：关注要点分析总结

根据拉取的数据，逐项分析 `require.md` 中的6个关注要点，结果写入 `analysis-summary/{market}/{ticker}/key-points-{YYYYMMDD}.json`：

| # | 关注要点 | 分析内容 | 数据来源 |
|---|---------|---------|---------|
| 1 | 利润、收入等 | 近5年收入/净利润趋势、同比变化、毛利率/净利率趋势、分部收入结构 | annual-5y.json + quarterly-latest.json |
| 2 | 存货规模 | 近5年存货绝对值及同比变化、存货周转天数趋势、存货/收入比 | annual-5y.json |
| 3 | 债务情况 | 近5年资产负债率、有息负债规模、净现金/净债务、利息覆盖倍数 | annual-5y.json |
| 4 | 公司及行业发展速度 | 公司收入增速 vs 行业增速（历史5年+未来3年预测）、市场份额变化 | annual-5y.json + industry-data/ |
| 5 | 财报中面对的风险 | 从年报/季报"风险因素"章节提取，分类整理 | 财报原文 |
| 6 | 公司未来的发展计划 | 从年报/季报"发展战略""未来展望"章节提取 | 财报原文 |

**未来3年预测数据来源**：
- 公司收入/利润预测：卖方一致预期（东方财富/stockanalysis）+ 公司指引（guidance）
- 行业增速预测：第三方权威机构预测（require.md 中的行业数据源）
- 所有预测数据标注来源和置信度（高/中/低）

### 第四步：数据交叉验证（必须执行）

数据拉取完成后，调用工具对关键数据进行程序化验证：

```bash
# Step 1 - 市值验算
python3 tools/financial_rigor.py verify-market-cap \
  --price {股价} --shares {总股本} --reported {报告市值} --currency {币种}

# Step 2 - 关键数据多源交叉验证（对收入、净利润、现金储备分别执行）
python3 tools/financial_rigor.py cross-validate \
  --field {字段名} --values '{"来源1": 数值, "来源2": 数值}' --unit {单位}

# Step 3 - 估值指标精确验算
python3 tools/financial_rigor.py verify-valuation \
  --price {股价} --eps {EPS} --bvps {每股净资产} --fcf-per-share {每股FCF} --dividend {每股股息}

# Step 4 - 三情景估值
python3 tools/financial_rigor.py three-scenario \
  --price {股价} --eps {EPS} --shares {总股本亿} \
  --growth {乐观增速} {中性增速} {悲观增速} \
  --pe {乐观PE} {中性PE} {悲观PE} --years 3 --currency {币种}
```

验证结果嵌入 HTML 报告附录"关键数据交叉验证记录"。

### 第五步：四大师分析 + 个人投资理念

参考 `skills/investment-research.md` 的分析框架，结合 `require.md` 中的分析依据，按以下维度研究：

#### 5.1 生意本质 — 段永平"对的生意"

- 用一句话定义这门生意的本质（谁付钱、为什么付钱、什么稀缺、什么复购）
- 收入结构拆解（分部收入占比、增速）
- 商业模式：一次性销售 vs 订阅/复购？硬件 vs 软件 vs 平台？
- 毛利率水平与同行对比
- **段永平式追问**：这门生意好在哪？如果只能用一句话描述，是什么？

#### 5.2 护城河评估 — 巴菲特"经济护城河"

逐一验证：品牌/定价权、转换成本、网络效应、规模效应、技术/专利壁垒
- 分析护城河趋势：过去5年变宽还是变窄？未来5年预判
- **巴菲特式追问**：10年后这条护城河还在吗？什么能摧毁它？

#### 5.3 逆向思考与风险 — 芒格"反过来想"

- 列出"这家公司可能失败的所有路径"（表格：路径/概率/影响程度）
- 结合第三步提取的财报风险因素，评估实际影响
- 历史类比：找到历史上处于相似位置的公司，结局如何？
- **芒格式追问**：我最可能在哪里犯错？聪明人为什么会不买/做空这家公司？

#### 5.4 管理层评估 — 段永平"对的人" + 巴菲特"管理层诚信"

- CEO/创始人关键决策复盘（表格：时间/决策/结果/评分）
- 资本配置能力：研发回报率、并购成功率、回购时机
- 股东利益一致性：管理层持股、薪酬结构、减持记录
- **段永平式追问**：如果CEO退休，这家公司还能保持竞争力吗？

#### 5.5 行业与文明趋势 — 李录"文明演进框架"

- 结合第三步的行业数据，判断行业是否处于"文明级范式转移"
- TAM增长曲线与天花板分析（历史+未来预测）
- 公司在产业价值链中的位置、谁捕获利润池
- **李录式追问**：站在20年后回看，这家公司是"这个时代的标准石油"还是"昙花一现"？

#### 5.6 估值与安全边际 — 巴菲特"内在价值" + 段永平"对的价格"

- 当前市场定价（关键估值指标，必须通过工具验算）
- 反向DCF：当前股价隐含了什么增长预期？
- 三情景估值（必须通过 `financial_rigor.py three-scenario` 计算）
- 与自身历史估值对比（基于 price-10y.json 计算历史 PE 分位）
- **段永平式追问**：如果股市明天关闭5年，你愿意以这个价格持有吗？

#### 5.7 个人投资理念融合

将以下个人投资理念贯穿分析全程，在结论中明确体现：

1. **长期持有优秀企业**：评估公司是否具备长期持有（5-10年+）的品质——生意模式是否持久、护城河是否深厚、管理层是否值得信任
2. **相信复利**：评估公司的再投资回报率（ROIC）和复利能力——利润留存能否以高回报率再投资、自由现金流能否持续增长
3. **长期相信 AI**：评估 AI 对该公司的影响——是赋能者（降本增效/创造新收入）还是颠覆者（替代其产品/服务）？公司在 AI 时代的定位

### 第六步：生成 HTML 研究报告

将所有分析整合为一个**自包含的 HTML 文件**，使用 ECharts 渲染交互式图表，写入 `ai-berkshire-report/{market}/{ticker}/{ticker}-research-{YYYYMMDD}.html`。

#### 报告结构

```
<!DOCTYPE html>
<html lang="zh-CN">
<head>
  <meta charset="UTF-8">
  <meta name="viewport" content="width=device-width, initial-scale=1.0">
  <title>{公司名}（{ticker}）股票研究报告 - {YYYYMMDD}</title>
  <script src="https://cdn.jsdelivr.net/npm/echarts@5/dist/echarts.min.js"></script>
  <style> /* 内嵌样式 */ </style>
</head>
<body>
  <!-- 报告头部：公司名、代码、研究日期、数据截止日期、当前价、市值、关键估值 -->
  <!-- 第一部分：数据分析图表 -->
  <!-- 第二部分：当前重大风险与未来发展计划 -->
  <!-- 第三部分：四大师分析结论与行动建议 -->
  <!-- 附录：关键数据交叉验证记录 -->
</body>
</html>
```

#### 第一部分：数据分析图表（必须包含以下图表，均含同比变化标注）

**图表 1：收入与利润趋势（近5年历史 + 未来3年预测）**

- 类型：柱状图（收入/利润）+ 折线图（同比增速），双 Y 轴
- X 轴：近5个财年 + 未来3年预测（预测部分用虚线/浅色区分）
- 柱状：营业收入、净利润
- 折线：收入同比增速、净利润同比增速
- 预测数据标注来源（一致预期/公司指引）和置信度

**图表 2：债务情况（近5年）**

- 类型：柱状图 + 折线图，双 Y 轴
- 柱状：总有息负债、净债务（或净现金为负值显示）
- 折线：资产负债率、利息覆盖倍数
- 标注行业平均水平作为参考线

**图表 3：存货规模（近5年）**

- 类型：柱状图（存货绝对值）+ 折线图（存货同比增速、存货周转天数）
- 柱状：存货账面价值
- 折线：存货同比增速、存货周转天数
- 若存货异常增长（增速远超收入增速），用红色标注警示

**图表 4：公司发展 vs 行业发展速度（近5年历史 + 未来3年预测）**

- 类型：双折线图，双 Y 轴
- 折线 1：公司收入增速（历史实际 + 未来预测）
- 折线 2：行业增速（历史实际 + 未来预测，来源第三方权威数据）
- 标注市场份额变化趋势
- 预测部分用虚线区分

**图表 5：近10年关键价格（仅周期性行业）**

- 类型：折线图
- 若公司属于周期性行业，展示 require.md 中对应的近10年关键价格序列
- 标注当前价格在历史区间的分位（如"当前处于10年25%分位"）
- 非周期性行业可省略此图

**图表 6：毛利率与净利率趋势（近5年）**

- 类型：折线图
- 毛利率、经营利润率、净利率三条线
- 标注同行平均水平作为参考

#### 第二部分：当前重大风险与未来发展计划

**2.1 当前面临的重大风险**

从财报"风险因素"章节和芒格逆向分析中提取，以表格呈现：

| 风险类别 | 具体描述 | 发生概率 | 影响程度 | 应对/缓释措施 |
|---------|---------|---------|---------|-------------|

风险类别包括但不限于：地缘政治、监管政策、技术替代、供应链、竞争加剧、汇率、债务到期、客户集中度。

**2.2 未来发展计划**

从财报"发展战略""未来展望"章节提取，包括：
- 战略方向与目标（3年内）
- 产能/产品规划
- 资本开支计划
- 并购/合作意向
- 技术研发方向
以时间线或列表呈现，每项标注预期投入和预期回报。

#### 第三部分：四大师分析结论与行动建议

**3.1 综合评估汇总表**

| 维度 | 结论 | 信心度 |
|------|------|--------|
| 生意质量（段永平） | | 高/中/低 |
| 护城河（巴菲特） | | |
| 管理层（段永平+巴菲特） | | |
| 最大风险（芒格） | | |
| 行业趋势（李录） | | |
| 估值吸引力（巴菲特+段永平） | | |
| AI 时代定位（个人理念） | | |
| 长期持有适合度（个人理念） | | |
| 复利能力（个人理念） | | |

**3.2 四位大师模拟点评**

以引用格式，分别用巴菲特、芒格、段永平、李录的语气给出对该公司的点评（每人2-3句）。

**3.3 个人投资理念评估**

- **长期持有优秀企业**：是否适合长期（5-10年+）持有？理由
- **相信复利**：ROIC 水平、利润再投资回报率、复利路径分析
- **长期相信 AI**：AI 对公司的具体影响（赋能/中性/颠覆），长期定位

**3.4 行动建议**

| 策略 | 建议 | 触发条件/价格区间 |
|------|------|-----------------|
| 空仓者 | 买入/观望/回避 | 买入价格区间 |
| 持仓者 | 加仓/持有/减仓 | 加仓/减仓信号 |
| 卖出信号 | — | 明确的卖出条件 |
| 加仓信号 | — | 明确的加仓条件 |

估值部分必须给出具体的价格区间（基于三情景估值工具结果）。

#### 附录：关键数据交叉验证记录

嵌入第四步工具验证的完整输出。

#### HTML 技术要求

1. **自包含**：所有数据以 JSON 内嵌在 `<script>` 标签中，图表通过 ECharts 渲染；除 ECharts CDN 外不依赖外部资源。
2. **响应式**：图表容器使用百分比宽度，适配桌面和移动端。
3. **图表交互**：ECharts 默认支持 tooltip、缩放、数据筛选。
4. **打印友好**：提供打印样式（`@media print`），图表以固定尺寸渲染。
5. **数据溯源**：每个图表下方标注数据来源和拉取时间。
6. **颜色规范**：收入用蓝色系、利润用绿色系、债务用橙/红色系、预测数据用虚线+浅色。
7. **中文渲染**：`lang="zh-CN"`，ECharts 字体使用系统默认中文字体。

### 第七步：报告数据抽检

HTML 报告生成后，执行数据抽检（准出流程）：

```bash
# Step 1 - 提取抽检清单（15%随机抽样）
python3 tools/report_audit.py extract --report <报告文件路径>

# Step 2 - 取数核验（按 skills/financial-data.md 规范从可靠信源取数）

# Step 3 - 输出判决
python3 tools/report_audit.py verdict --results '<填好的JSON>' --report <报告文件名>
```

- **【准出】**：所有抽检点偏差 ≤ 1% → 报告可发布
- **【打回】**：任意点偏差 > 1% → 修正后重新抽检

---

## 输出要求

1. 最终产出为一个 HTML 文件，路径为 `ai-berkshire-report/{market}/{ticker}/{ticker}-research-{YYYYMMDD}.html`。
2. 所有数据必须先缓存到对应目录，HTML 中的数据来自缓存文件。
3. 图表必须有数据支撑，每张图标注数据来源和拉取时间。
4. 报告头部包含：公司名、代码、研究日期、数据截止日期、当前股价、市值、关键估值指标。
5. 结论明确，不回避给出买入/观望/回避的建议，估值部分给出具体价格区间。
6. 预测数据（未来3年）必须标注来源和置信度，与历史数据在图表中视觉区分。
7. 个人投资理念（长期持有优秀企业、相信复利、长期相信 AI）必须在结论中明确体现。
8. 报告末尾区分"AI 分析置信度"与"投资确定性"——前者取决于资料量，后者取决于生意本质。
9. 如果数据来源存在缺口（如某行业第三方数据无法获取），明确标注"数据缺口"并说明对结论的影响。

---

## 附录：require.md 默认配置（当 require.md 不存在时使用）

### 关注要点

1. 利润、收入等（需图形化 + 同比变化）
2. 存货规模（需图形化 + 同比变化）
3. 债务情况（需图形化）
4. 财报中公司的发展以及行业的发展速度图（历史 + 未来，需图形化）
5. 财报中面对的风险
6. 财报中公司未来的发展计划

### 主要数据来源

1. 股票数据：美股 macrotrends+stockanalysis；港股 aastocks+macrotrends ADR；A股 东方财富+巨潮资讯
2. 近5年财报：美股 macrotrends+stockanalysis；港股 港交所披露易+macrotrends ADR；A股 东方财富+巨潮资讯
3. 行业第三方权威数据：按行业匹配（Prismark/SEMI/WSTS/BloombergNEF/SNE Research/中汽协/IEA/LME/IQVIA/IDC/USDA/Clarksons/ICIS 等）
4. 近10年关键价格（周期性行业）：存储晶圆/石油/贵金属/煤炭/化工品/BDI·SCFI/水泥价格指数

### 分析依据

1. 巴菲特/芒格/段永平/李录大师分析理论（参考 `skills/investment-research.md`）
2. 个人投资理念：长期持有优秀企业，相信复利，长期相信 AI
