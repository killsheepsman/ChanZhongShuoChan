# 缠论股票分析软件开发准备文档

来源文件：`C:\STOCK\缠中说禅.pdf`

生成目的：把 PDF 中可读的缠论体系整理成后续软件开发可执行的规则、数据结构和处理流程。本文不是全文摘录，也不是投资建议；它是面向程序实现的技术整理。

## 1. PDF 读取情况

- 文件大小约 110.73 MB，共 1414 页。
- PDF 未加密，可以读取。
- 书签目录完整，共抽取到 148 个目录项。
- 正文抽取质量不均：前几页和部分课程为正常中文，部分繁体/特殊编码页会出现乱码。
- 已生成中间文件：
  - `C:\STOCK\analysis\pdf_outline.json`
  - `C:\STOCK\analysis\key_page_samples.json`
  - `C:\STOCK\analysis\rule_candidates.json`

## 2. PDF 中对学习顺序的结构提示

PDF 第 5-11 页给出了学习大纲。对软件开发最有价值的部分应按以下顺序处理：

1. 分型、笔、线段篇
   - 第 62 课：分型、笔与线段
   - 第 65 课：再说说分型、笔、线段
   - 第 67 课：线段的划分标准
   - 第 71 课：线段划分标准的再分辨
   - 第 77、78、79 课：概念再分辨、线段继续划分、分型辅助操作
2. 中枢、走势类型和买卖点篇
   - 第 17 课：走势终完美
   - 第 20 课：中枢级别扩张及第三类买卖点
   - 第 21 课：买卖点分析的完备性
   - 第 53 课：三类买卖点的再分辨
   - 第 83 课：笔、线段、最小中枢结构
3. 背驰篇
   - 第 24 课：MACD 对背驰的辅助判断
   - 第 27 课：盘整背驰与历史性底部
   - 第 29、37、43、44、64 课：转折力度、背驰再分辨、小级别背驰引发大级别转折
4. 同级别分解篇
   - 第 33、36、38、39、40 课
5. 实战策略篇
   - 第 26、31、32、41、45、46、49、50、55、68、73、92、106、107、108 课

## 3. 核心概念的程序化理解

### 3.1 级别

级别可以理解为同一套规则在不同时间尺度上的应用。软件里建议不要把级别写死为“日线、30分钟、5分钟”，而是抽象成：

```text
Level = {
  name: "1m" | "5m" | "30m" | "daily" | ...,
  parent: Level | null,
  child: Level | null,
  bars: KLine[]
}
```

第 53 课强调：如果决定用 30 分钟观察，就等价于先把完成的 5 分钟走势看成没有内部结构的线段；进入背驰段后，再用更小级别精确定位。

### 3.2 走势终完美

第 17 课给出基础原理：

- 任何级别的走势，都可以分解为趋势与盘整。
- 趋势分为上涨和下跌。
- 任何级别的任何走势类型最终要完成，即“走势终完美”。

程序含义：

- 任意时刻的最新走势只能处于“未完成”状态。
- 已完成结构才能作为稳定输入参与更高级别结构构建。
- 系统输出必须区分：
  - confirmed：已确认结构
  - tentative：临时结构，后续 K 线可能改写

### 3.3 中枢

第 17 课给出的可程序化定义：

- 某级别走势类型中，至少三个连续次级别走势类型重叠的部分，称为该级别走势中枢。
- 对最低不可再分级别，可用至少三个该级别单位 K 线重叠部分定义。

建议数据结构：

```text
Center = {
  level,
  start_index,
  end_index,
  high,        // 重叠区间上沿
  low,         // 重叠区间下沿
  components, // 构成中枢的三个或更多次级别走势
  status: "forming" | "confirmed" | "extended" | "expanded" | "broken"
}
```

中枢重叠区间计算：

```text
center_high = min(component.high for first_three_components)
center_low  = max(component.low  for first_three_components)
valid when center_low <= center_high
```

### 3.4 盘整与趋势

第 17 课定义：

- 盘整：某完成走势类型只包含一个走势中枢。
- 趋势：某完成走势类型至少包含两个以上依次同向的走势中枢。
- 趋势方向分为上涨和下跌。

建议枚举：

```text
TrendType = "up" | "down" | "consolidation" | "unknown"
```

### 3.5 分型、笔、线段

这部分 PDF 抽取质量不稳定，但第 65、67、71 课可读度较高。

开发上建议分三层：

1. K 线预处理：处理包含关系。
2. 分型识别：顶分型、底分型。
3. 笔识别：由交替的顶/底分型连接。
4. 线段识别：由笔序列构成，通过特征序列判断结束。

初版可以先采用业界常见缠论实现规则：

- 顶分型：中间 K 线高点高于两侧，高点形成局部顶；低点关系需结合包含处理。
- 底分型：中间 K 线低点低于两侧，低点形成局部底。
- 笔：顶底分型交替，且两端之间满足最小 K 线数量要求。
- 线段：至少由三笔构成，并通过特征序列出现分型或被破坏来确认。

第 67 课线段关键点：

- 线段只有两种：从向上笔开始，或从向下笔开始。
- 对向上线段，可表示为 `S1 X1 S2 X2 S3 X3 ...`。
- 向上线段关注其向下笔序列 `X1 X2 ... Xn`，该序列称为特征序列。
- 向下线段关注其向上笔序列 `S1 S2 ... Sn`。
- 特征序列相邻元素无重合区间，称为特征序列缺口。
- 特征序列也要做包含关系处理，处理后的称为标准特征序列。

## 4. 买卖点规则整理

### 4.1 第一类买卖点

结合 PDF 中第 15、16、24、27 课候选句整理：

- 第一类买点：通常出现在某级别下跌趋势背驰后。
- 第一类卖点：通常出现在某级别上涨趋势背驰后。
- MACD 辅助规律：
  - 第一类买点常在 0 轴下方背驰形成。
  - 第一类卖点反向，常在 0 轴上方背驰形成。

程序判断框架：

```text
if trend.direction == "down"
and trend.has_at_least_two_centers()
and last_down_segment.power < previous_down_segment.power
and price_makes_new_low_or_near_low:
    emit BuyPoint(type=1)
```

### 4.2 第二类买卖点

PDF 候选句中提到：

- 第二类买点常见于第一次上 0 轴后回抽确认。
- 第二类卖点反向，常见于第一次下 0 轴后反弹确认。

程序判断框架：

```text
after type1_buy:
  if price rebounds above center/zero_axis_reference
  and pullback does not break type1_low
  and lower_level shows exhaustion:
      emit BuyPoint(type=2)
```

### 4.3 第三类买卖点

来自第 20、53 课主题，初步程序化理解：

- 第三类买点：走势离开中枢后，回试中枢上沿不重新进入中枢，形成继续向上的确认。
- 第三类卖点：走势离开中枢后，反抽中枢下沿不重新进入中枢，形成继续向下的确认。

程序判断框架：

```text
if price_leaves_center_up
and pullback.low > center.high
and lower_level_down_move_exhausted:
    emit BuyPoint(type=3)

if price_leaves_center_down
and rebound.high < center.low
and lower_level_up_move_exhausted:
    emit SellPoint(type=3)
```

## 5. 背驰与盘整背驰

### 5.1 趋势背驰

PDF 多次强调：不能把 MACD 柱缩短直接等同于背驰。背驰首先是走势结构问题，再用 MACD 或均线辅助判断。

判断顺序：

1. 明确级别。
2. 明确走势类型。
3. 确认至少两个同向中枢，形成趋势。
4. 比较前后同向走势段的力度。
5. 用 MACD、均线面积等辅助确认。

第 27 课提示：

- 真正趋势背驰通常不会发生在第一个中枢之后。
- 多数情况发生在第二个中枢之后。

### 5.2 盘整背驰

第 27 课可读内容：

- 如果在第一个中枢后出现力度衰竭，通常不是真正趋势背驰，而是盘整背驰。
- 盘整背驰的技术含义：企图脱离中枢的运动力度有限，被阻止后回到中枢。
- 第二、三类买点中，很多由盘整背驰构成。

程序判断：

```text
if only_one_center
and departure_from_center_fails
and return_to_center_occurs:
    mark Divergence(type="consolidation")
```

### 5.3 MACD 辅助

MACD 只能作为辅助层，不应作为主结构层。

可实现的辅助指标：

- DIF、DEA、MACD histogram。
- 0 轴位置。
- 红绿柱波段面积。
- 红绿柱峰值是否创新高/新低。
- DIF/DEA 是否创新高/新低。

候选规则：

```text
For downtrend:
  if price makes lower low
  and MACD histogram/DIF does not make corresponding lower low
  and MACD has returned near zero axis between compared legs:
      divergence_support = true

For uptrend:
  if price makes higher high
  and MACD histogram/DIF does not make corresponding higher high
  and MACD has returned near zero axis between compared legs:
      divergence_support = true
```

## 6. 软件模块建议

### 6.1 数据层

输入字段：

```text
symbol, datetime, open, high, low, close, volume, amount
```

建议同时保存：

- 不复权数据：保留真实交易价格、缺口、除权影响。
- 前复权数据：用于连续走势结构分析。

### 6.2 计算流水线

```text
RawKLine
  -> AdjustedKLine
  -> InclusionProcessedKLine
  -> Fractal
  -> Stroke/Bi
  -> Segment/Xianduan
  -> SubTrend
  -> Center/Zhongshu
  -> TrendType
  -> Divergence
  -> BuySellPoint
  -> MultiLevelSignal
```

### 6.3 状态机

每一层结构都应有状态：

```text
forming
candidate
confirmed
invalidated
extended
```

这很重要，因为缠论结构会被新 K 线重绘或扩展。

## 7. 第一版 MVP 范围

建议第一版不要一次实现全部 108 课，而是先实现：

1. AKShare 拉取 A 股 K 线。
2. K 线包含关系处理。
3. 顶/底分型识别。
4. 笔识别。
5. 基础线段识别。
6. 三段重叠识别最小中枢。
7. 趋势/盘整分类。
8. MACD 辅助背驰。
9. 粗粒度三类买卖点提示。
10. 图形输出：K 线、笔、线段、中枢框、买卖点标记。

## 8. 待核验项

由于 PDF 部分页码抽取乱码，以下规则需要后续通过页面截图/OCR 或人工核对加强：

- 第 62 课：分型、笔与线段的原始定义。
- 第 67、71、78 课：线段划分与特征序列细节。
- 第 20、21 课：中枢扩张、买卖点完备性的原文细节。
- 第 24 课：MACD 判断背驰的具体图例。
- 第 38-40 课：同级别分解的严谨规则。

## 9. 开发原则

- 结构优先，指标辅助。
- 先固定级别，再判断走势。
- 先判断趋势/盘整，再判断背驰。
- 买卖点必须带级别。
- 所有信号都要带置信状态，避免把临时结构当成确认信号。
- 图形验证比纯文本输出更重要。

## 10. 建议下一步

下一步可以开始建项目骨架：

```text
C:\STOCK
  data/
  docs/
  analysis/
  src/
    data_fetch/
    chanlun/
      kline.py
      fractal.py
      stroke.py
      segment.py
      center.py
      divergence.py
      signal.py
    visualize/
    tests/
```

第一条开发任务建议：先实现 AKShare 数据下载和 K 线包含关系处理，然后用一只股票的日线数据验证分型与笔。
