# RAG功能对比工具使用指南

## 📋 概述

我为你创建了两个交互式对比工具，让你可以：
- ✅ 开关不同的高级RAG功能
- ✅ 实时对比性能差异
- ✅ 查看详细的指标对比表
- ✅ 导出测试结果

---

## 🛠️ 工具1: Bash交互式脚本

### 使用方法

```bash
./test_rag_comparison.sh
```

### 功能菜单

```
=========================================
RAG Feature Comparison Tool
=========================================

1) Standard RAG (baseline)           # 基准测试
2) Hybrid Search (BM25 + Vector)     # 混合搜索
3) Iterative Self-RAG                # 迭代检索
4) Smart RAG (auto-selection)        # 智能选择
5) Compare All Modes                 # 对比所有模式
6) Custom Comparison                 # 自定义对比
7) Toggle Feature Settings           # 切换功能开关
8) View Current Cache Stats          # 查看缓存统计
9) Clear Cache                       # 清除缓存
0) Exit
```

### 功能开关菜单 (选项7)

```
Feature Toggle (restart required)
=========================================

1) Toggle Hybrid Search             # 开关混合搜索
2) Toggle Query Cache               # 开关查询缓存
3) Toggle Query Classification      # 开关查询分类
4) Toggle Self-RAG                  # 开关Self-RAG
5) Adjust HYBRID_ALPHA              # 调整向量/BM25权重
6) Adjust Self-RAG Confidence       # 调整置信度阈值
```

### 示例对比输出

```
Mode                 Confidence   Chunks  API Time(ms)  Wall Time(ms)  Tokens      Cost($)    Iterations
---------------------------------------------------------------------------------------------------------------------------
Standard RAG         -1.6314      10      9875.59       10123          1543        $0.004532  1
Hybrid Search        -1.6314      10      6801.36       7043           1543        $0.004532  1
Self-RAG             2.1445       10      10099.82      10367          2187        $0.006421  1
Smart RAG            0.8500       10      15000.66      15289          2431        $0.007134  2
```

---

## 🐍 工具2: Python交互式Dashboard (推荐)

### 使用方法

```bash
python3 rag_compare_dashboard.py
```

### 功能特性

1. **彩色输出**: 高亮显示最佳性能指标
2. **实时统计**: 自动计算相对改进百分比
3. **详细洞察**: 对比基准线的改进/退化
4. **JSON导出**: 保存测试结果用于分析

### 示例输出

```
Mode                    Confidence   Chunks   API Time   Wall Time     Tokens        Cost  Iters
--------------------------------------------------------------------------------------------------------------------
Standard RAG                -1.6314        10    9875.6ms    10123.2ms       1543  $0.004532      1
Hybrid Search               -1.6314        10    6801.4ms     7043.1ms       1543  $0.004532      1  ← 快31%
Self-RAG Iterative           2.1445        10   10099.8ms    10367.4ms       2187  $0.006421      1
Smart RAG                    0.8500        10   15000.7ms    15289.3ms       2431  $0.007134      2

Key Insights (vs Standard RAG):

Hybrid Search:
  ✓ Confidence: +0.0%
  ✓ Latency: -31.1% faster
  ✓ Tokens: +0.0% more

Self-RAG Iterative:
  ✓ Confidence: +231.4%
  ✗ Latency: +2.3% slower
  ✗ Tokens: +41.8% more

Smart RAG:
  ✓ Confidence: +152.1%
  ✗ Latency: +51.9% slower
  ✗ Tokens: +57.6% more
```

---

## 📊 典型对比场景

### 场景1: 测试混合搜索的影响

**步骤**:
1. 运行 `python3 rag_compare_dashboard.py`
2. 选择 `6) Custom Comparison`
3. 输入 `1 2` (对比Standard和Hybrid)
4. 查看性能差异

**预期结果**:
- Hybrid应该更快（BM25索引已缓存）
- Token使用相同（都使用相同LLM）
- 置信度可能略有不同

---

### 场景2: 测试查询缓存效果

**步骤**:
1. 清除缓存: 选择 `9) Clear Cache`
2. 运行第一次查询: `2) Test Hybrid Search`
3. 修改问题为相似问题: `11) Change Test Question`
   - 原问题: "Who wrote Pride and Prejudice?"
   - 相似问题: "Who is the author of Pride and Prejudice?"
4. 再次运行: `2) Test Hybrid Search`
5. 查看缓存命中: `8) View Cache Stats`

**预期结果**:
```json
{
  "enabled": true,
  "hits": 1,
  "misses": 1,
  "hit_rate": 0.5,
  "cache_size": 1
}
```

---

### 场景3: 调整HYBRID_ALPHA对比

**目标**: 测试不同BM25权重对准确率的影响

**步骤** (使用Bash脚本):
1. `./test_rag_comparison.sh`
2. 选择 `7) Toggle Feature Settings`
3. 选择 `5) Adjust HYBRID_ALPHA`
4. 输入 `0.5` (50% vector, 50% BM25)
5. 重启backend: `docker-compose restart backend`
6. 等待30秒后，选择 `2) Hybrid Search`
7. 记录结果
8. 重复步骤3-7，测试不同alpha值: `0.7`, `0.8`, `0.9`

**预期观察**:
- Alpha=0.5: 关键词查询准确率更高
- Alpha=0.8: 语义查询准确率更高
- Alpha=0.7: 平衡最佳（默认值）

---

### 场景4: Self-RAG置信度阈值调优

**目标**: 找到最佳置信度阈值

**步骤**:
1. `./test_rag_comparison.sh`
2. 选择 `7) Toggle Feature Settings`
3. 选择 `6) Adjust Self-RAG Confidence Threshold`
4. 测试不同阈值:
   - `0.65`: 更容易达到，迭代次数少，但可能准确率低
   - `0.75`: 默认值，平衡
   - `0.85`: 更高准确率，但可能需要更多迭代
5. 每次修改后重启: `docker-compose restart backend`
6. 运行 `3) Iterative Self-RAG`
7. 对比迭代次数和置信度

---

## 🔧 高级用法

### 导出测试结果

```bash
# Python版本
python3 rag_compare_dashboard.py
# 选择 5) Compare All Modes
# 选择 10) Export Results to JSON
# 结果保存到 rag_comparison_results.json
```

### 批量测试脚本

创建 `batch_test.sh`:
```bash
#!/bin/bash

# Test different HYBRID_ALPHA values
for alpha in 0.3 0.5 0.7 0.9; do
    echo "Testing HYBRID_ALPHA=$alpha"

    # Update .env
    sed -i.bak "s/HYBRID_ALPHA=.*/HYBRID_ALPHA=$alpha/" .env

    # Restart backend
    docker-compose restart backend
    sleep 30

    # Run test
    curl -s -X POST http://localhost:8888/api/rag/ask-hybrid \
        -H "Content-Type: application/json" \
        -d '{"question": "Who wrote Pride and Prejudice?", "top_k": 5}' \
        | jq '{alpha: '$alpha', confidence: .confidence, time: .total_time_ms}' \
        >> alpha_test_results.jsonl
done
```

---

## 📈 关键指标解读

### 1. Confidence (置信度)
- **范围**: -∞ to +∞ (通常-10到+10)
- **含义**: LLM对答案的确定程度
- **越高越好**: >0通常表示高置信度
- **负值**: 表示LLM不太确定，但仍提供最佳答案

### 2. API Time vs Wall Time
- **API Time**: 后端报告的处理时间
- **Wall Time**: 实际curl往返时间 (包括网络)
- **差异**: 通常Wall Time稍高（网络延迟）

### 3. Tokens
- **Prompt Tokens**: 发送给LLM的上下文
- **Completion Tokens**: LLM生成的答案
- **Total**: Prompt + Completion
- **成本**: 直接影响OpenAI API费用

### 4. Iterations (迭代次数)
- **仅Self-RAG**: 检索-生成-反思的轮数
- **理想**: 1次迭代即收敛（高效）
- **多次迭代**: 复杂查询需要更多上下文

### 5. Converged (收敛)
- **true**: 达到置信度阈值停止
- **false**: 达到最大迭代次数停止

---

## 🎯 推荐的测试工作流

### 初次使用

```bash
# 1. 运行全面对比
python3 rag_compare_dashboard.py
# 选择 5) Compare All Modes

# 2. 查看缓存统计
# 选择 8) View Cache Stats

# 3. 导出结果
# 选择 10) Export Results
```

### 调优工作流

```bash
# 1. 运行基准测试
./test_rag_comparison.sh
# 选择 1) Standard RAG

# 2. 调整参数
# 选择 7) Toggle Feature Settings

# 3. 重启backend
docker-compose restart backend

# 4. 再次测试
# 选择对应模式

# 5. 对比结果
# 选择 5) Compare All Modes
```

---

## 🚨 注意事项

### 1. 首次查询慢
- **原因**: BM25索引构建（首次）
- **时间**: 30-120秒（取决于文档数量）
- **解决**: 后续查询会使用缓存的索引

### 2. 修改.env后必须重启
```bash
docker-compose restart backend
# 等待30秒后再测试
```

### 3. 缓存影响测试
- **问题**: 缓存命中会跳过检索，影响对比公平性
- **解决**: 每次对比前清除缓存
```bash
curl -X POST http://localhost:8888/api/rag/cache/clear
```

### 4. 查询相似度
- **缓存阈值**: 0.85 (很高)
- **问题**: 稍有不同的查询不会命中缓存
- **调优**: 降低 `QUERY_CACHE_SIMILARITY_THRESHOLD` 到0.80

---

## 📚 示例测试用例

### 简单查询 (测试缓存和分类)
```
"Who wrote Pride and Prejudice?"
"Who is the author of Moby Dick?"
"What year was 1984 published?"
```

### 复杂查询 (测试Self-RAG)
```
"What is the relationship between Sir Robert and Uncle Robert?"
"Explain the complex dynamics in the novel Sir Robert's Fortune"
"How does the character development of Sir Robert progress?"
```

### 关键词查询 (测试BM25权重)
```
"Find the quote: To be or not to be"
"Sir roberts fortune a novel, for what purpose..."
```

---

## 🎊 总结

现在你有两个强大的对比工具：

1. **Bash脚本** (`test_rag_comparison.sh`)
   - 快速切换功能开关
   - 直接修改.env文件
   - 适合快速测试

2. **Python Dashboard** (`rag_compare_dashboard.py`)
   - 彩色高亮输出
   - 详细性能洞察
   - JSON导出功能
   - **推荐日常使用**

开始对比吧！🚀

```bash
# 快速开始
python3 rag_compare_dashboard.py
```
