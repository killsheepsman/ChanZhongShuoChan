# 缠中说禅三买三卖算法规则规格

来源文件：`C:\STOCK\缠中说禅.pdf`

本文目标：只整理“能落地到软件”的缠中说禅规则，用来识别三类买点和三类卖点。本文不做行情预测，不做投资建议。

## 1. 原文依据定位

当前 PDF 可稳定读取到的核心依据：

- 第 17 课，约 PDF 第 353-355 页：走势终完美、中枢、盘整、趋势的定义。
- 第 27 课，约 PDF 第 670 页：趋势背驰、盘整背驰、第二/三类买点与盘整背驰的关系。
- 第 53 课，约 PDF 第 998-1002 页：三类买卖点再分辨，特别是第二类买卖点、第三类买卖点定理。

## 2. 必须先实现的结构

三买三卖不能直接从 K 线涨跌上硬判，必须先有结构层。

```text
KLine
  -> 包含关系处理后的 KLine
  -> 分型
  -> 笔
  -> 线段
  -> 次级别走势类型
  -> 本级别中枢
  -> 本级别走势类型
  -> 背驰/盘整背驰
  -> 三类买卖点
```

最小可行版本可以先把“次级别走势类型”简化为“线段或线段组合”，但信号字段里必须标记 `confidence`，避免把临时结构当成确认结构。

## 3. 中枢变量定义

对某级别中枢 `Z`，建议保存以下字段：

```text
Z.components = [次级别走势1, 次级别走势2, 次级别走势3, ...]
ZG = min(component.high for first_three_components)  // 中枢上沿
ZD = max(component.low  for first_three_components)  // 中枢下沿
GG = max(component.high for all_components)
DD = min(component.low  for all_components)
```

有效中枢条件：

```text
ZD <= ZG
```

说明：

- `ZG`/`ZD` 是判断第三类买卖点的关键。
- 是否使用严格不破位需要做成参数：
  - 严格模式：三买要求 `pullback.low > ZG`，三卖要求 `rebound.high < ZD`。
  - 宽松模式：允许等于，即 `>= ZG` / `<= ZD`。

## 4. 第一类买点

### 4.1 规则含义

第一类买点是某级别下跌趋势的背驰点。它的意义是：一个本级别下跌走势类型结束或至少进入转折风险区。

第 53 课明确说第一类买卖点就是该级别的背驰点。第 27 课强调，真正趋势背驰一般至少发生在第二个同级别中枢之后；如果第一个中枢后就发生力度衰竭，更接近盘整背驰。

### 4.2 判定条件

```text
条件 B1:
1. 当前分析级别为 L。
2. L 级别走势类型为下跌趋势。
3. 该下跌趋势至少包含两个同向中枢。
4. 最后一段离开中枢的下跌段记为 C，前一可比较同向下跌段记为 A。
5. C 创新低或接近新低。
6. C 的走势力度弱于 A。
7. C 内部在更小级别出现完成迹象或底背驰。

满足时，C 段末端为第一类买点候选。
```

### 4.3 力度比较

力度比较不能只看 MACD。可用多指标投票：

```text
price_power:
  abs(C.price_change) < abs(A.price_change)

macd_area_power:
  abs(sum(MACD_histogram over C)) < abs(sum(MACD_histogram over A))

macd_peak_power:
  C.MACD_low_peak > A.MACD_low_peak

slope_power:
  abs(C.slope) < abs(A.slope)
```

建议第一版：

```text
divergence = macd_area_power and price_new_low
```

第二版再加入线段/中枢结构比较。

## 5. 第一类卖点

第一类卖点是第一类买点的反向规则。

```text
条件 S1:
1. 当前分析级别为 L。
2. L 级别走势类型为上涨趋势。
3. 该上涨趋势至少包含两个同向中枢。
4. 最后一段离开中枢的上涨段记为 C，前一可比较同向上涨段记为 A。
5. C 创新高或接近新高。
6. C 的走势力度弱于 A。
7. C 内部在更小级别出现完成迹象或顶背驰。

满足时，C 段末端为第一类卖点候选。
```

## 6. 第二类买点

### 6.1 规则含义

第 53 课说明：第二类买卖点是第一类买卖点的补充，尤其用于“小级别转大级别”时没有本级别第一类买卖点的情况。

它的结构意义：第二类买点出现后，后面至少还有一段次级别走势类型，并且会与前两段产生重叠，因此有形成更大级别中枢的倾向。

### 6.2 判定条件

第二类买点可由两种路径触发：

```text
路径 A: 第一类买点后的回抽确认
1. 已出现 L 级别第一类买点 B1，或更小级别底背驰引发向上转折。
2. 之后出现一个次级别向上走势。
3. 再出现一个次级别向下回抽走势。
4. 回抽不跌破 B1 低点，或回抽段出现盘整背驰/力度衰竭。
5. 回抽结束位置为第二类买点候选。

路径 B: 小级别转大级别
1. L 级别没有形成明确第一类买点。
2. 更小级别下跌背驰后向上。
3. 第一次向下回抽不创新低，或形成盘整背驰。
4. 回抽结束位置为第二类买点候选。
```

### 6.3 程序表达

```text
if previous_low_confirmed
and up_subtrend_after_low.exists
and pullback_subtrend.exists
and (
    pullback.low > previous_low
    or pullback.has_consolidation_divergence
):
    emit BuyPoint(type=2)
```

## 7. 第二类卖点

第二类卖点是第二类买点的反向规则。第 53 课给出的表达是：从高点一个次级别走势向下后，接一个次级别走势向上，如果不创新高或出现盘整背驰，构成第二类卖点。

```text
条件 S2:
1. 已出现 L 级别第一类卖点 S1，或更小级别顶背驰引发向下转折。
2. 之后出现一个次级别向下走势。
3. 再出现一个次级别向上反抽走势。
4. 反抽不突破前高，或反抽段出现盘整背驰/力度衰竭。
5. 反抽结束位置为第二类卖点候选。
```

程序表达：

```text
if previous_high_confirmed
and down_subtrend_after_high.exists
and rebound_subtrend.exists
and (
    rebound.high < previous_high
    or rebound.has_consolidation_divergence
):
    emit SellPoint(type=2)
```

## 8. 第三类买点

### 8.1 原文定理的程序化表达

第 53 课附录给出第三类买卖点定理：

- 一个次级别走势类型向上离开中枢。
- 然后以一个次级别走势类型回试。
- 回试低点不跌破 `ZG`。
- 构成第三类买点。

### 8.2 判定条件

```text
条件 B3:
1. 已有 L 级别中枢 Z。
2. 一个 L 的次级别走势 U 向上离开 Z。
3. 离开必须有效，即 U 的高低区间主要运行在 ZG 上方，或收盘/线段端点明确突破 ZG。
4. 随后一个 L 的次级别走势 D 回试 Z。
5. D.low > ZG，或宽松模式下 D.low >= ZG。
6. D 结束处为第三类买点候选。
```

程序表达：

```text
if center.confirmed
and leave.direction == "up"
and leave.is_sublevel_trend_or_completed_move
and leave.breaks_above(center.ZG)
and pullback.direction == "down"
and pullback.is_sublevel_completed_move
and pullback.low >= center.ZG:
    emit BuyPoint(type=3)
```

### 8.3 风险标记

第 53 课提醒：第三类买卖点后可能演化成更大级别震荡。因此信号需要标记后续演化：

```text
third_point_outcome:
  "continue_up"
  "larger_center_oscillation"
  "failed_breakout"
```

## 9. 第三类卖点

第三类卖点是第三类买点的反向规则。

第 53 课定理：

- 一个次级别走势类型向下离开中枢。
- 然后以一个次级别走势类型回抽。
- 回抽高点不升破 `ZD`。
- 构成第三类卖点。

程序条件：

```text
条件 S3:
1. 已有 L 级别中枢 Z。
2. 一个 L 的次级别走势 D 向下离开 Z。
3. 离开必须有效，即 D 的高低区间主要运行在 ZD 下方，或收盘/线段端点明确跌破 ZD。
4. 随后一个 L 的次级别走势 U 反抽 Z。
5. U.high < ZD，或宽松模式下 U.high <= ZD。
6. U 结束处为第三类卖点候选。
```

程序表达：

```text
if center.confirmed
and leave.direction == "down"
and leave.is_sublevel_trend_or_completed_move
and leave.breaks_below(center.ZD)
and rebound.direction == "up"
and rebound.is_sublevel_completed_move
and rebound.high <= center.ZD:
    emit SellPoint(type=3)
```

## 10. 盘整背驰辅助规则

第 27 课指出：在第一个中枢后出现的力度衰竭，通常不是趋势背驰，而是盘整背驰。盘整背驰的含义是试图脱离中枢的运动力度不足，被拉回中枢。

程序条件：

```text
if trend_or_range.has_only_one_center
and departure_from_center.exists
and departure_power_weaker_than_reference
and price_returns_to_center:
    divergence.type = "consolidation"
```

用途：

- 辅助第二类买卖点确认。
- 辅助中枢震荡中的低级别操作。
- 辅助判断三买/三卖是否失败并演化成更大级别震荡。

## 11. 信号输出字段

```text
Signal = {
  symbol,
  level,
  datetime,
  price,
  side: "buy" | "sell",
  type: 1 | 2 | 3,
  status: "candidate" | "confirmed" | "invalidated",
  source_structure: {
    center_id,
    trend_id,
    segment_id,
    parent_level,
    child_level
  },
  evidence: {
    center_ZG,
    center_ZD,
    previous_high,
    previous_low,
    divergence_type,
    macd_area_compare,
    power_compare,
    pullback_breaks_reference
  },
  risk: {
    may_expand_to_larger_center,
    small_level_signal,
    needs_confirmation
  }
}
```

## 12. 实现顺序

建议开发顺序：

1. 数据下载与复权选择。
2. K 线包含关系处理。
3. 分型识别。
4. 笔识别。
5. 线段识别。
6. 中枢识别，先实现 `ZG/ZD`。
7. 趋势/盘整分类。
8. MACD 面积与峰值计算。
9. 趋势背驰与盘整背驰识别。
10. 第一类买卖点。
11. 第二类买卖点。
12. 第三类买卖点。
13. 多级别联立与图形验证。

## 13. MVP 判定优先级

第一版不要追求“所有复杂情况都对”，先保证以下规则清楚：

```text
B1/S1: 趋势 + 至少两个中枢 + 同向段力度背驰
B2/S2: 第一类点或小转大后的第一次回抽/反抽不破前低/前高
B3/S3: 次级别离开中枢 + 次级别回试/回抽不破 ZG/ZD
```

只要这三组跑通，就已经能形成可测试的缠论买卖点识别器。
