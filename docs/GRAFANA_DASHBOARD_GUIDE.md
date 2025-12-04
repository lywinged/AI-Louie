# Grafana仪表板使用指南

**创建日期:** 2025-12-04
**状态:** ✅ 已完成

---

## 🎯 概述

AI Governance Dashboard 是一个全面的Grafana仪表板，用于实时监控AI-Louie系统的治理合规性。该仪表板包含交互式按钮、多种可视化面板和自动刷新功能。

---

## ✨ 新增功能

### 🎯 快速操作控制面板

仪表板顶部有一个交互式控制面板，包含4个快速操作按钮：

| 按钮 | 功能 | URL |
|------|------|-----|
| 📚 API Docs | 打开Backend API文档 | http://localhost:8888/docs |
| 📊 Metrics | 查看原始Prometheus指标 | http://localhost:8888/metrics |
| 🖥️ Frontend | 打开Streamlit前端界面 | http://localhost:8501 |
| 🔄 Refresh | 刷新仪表板数据 | 重新加载页面 |

**特点:**
- 按钮悬停时有动画效果（颜色变深）
- 所有外部链接在新标签页打开
- 美观的阴影和圆角设计
- 系统状态信息显示

---

## 📊 仪表板面板

### 1. 📈 Governance Checkpoints by Status
**类型:** 时间序列图
**功能:** 显示所有治理检查点的执行频率，按标准和状态分组
**指标:** `ai_governance_checkpoint_total`

### 2. 🎯 Governance Compliance Rate
**类型:** 仪表盘
**功能:** 显示每个治理标准的合规率（0-100%）
**颜色阈值:**
- 红色: 0-70%
- 黄色: 70-90%
- 绿色: 90-100%

### 3. 🥧 AI Operations by Risk Tier
**类型:** 饼图
**功能:** 显示不同风险层级的操作分布
**包含:** 百分比和绝对值

### 4. ⚡ Operation Latency (P95)
**类型:** 时间序列图
**功能:** 显示操作延迟的第95百分位数
**颜色阈值:**
- 绿色: 0-2秒
- 黄色: 2-5秒
- 红色: >5秒

### 5. 🔐 G4 Permission Checks
**类型:** 统计面板
**功能:** 显示权限检查的通过/失败数量
**指标:**
- ✅ Passed (绿色)
- ❌ Failed (红色)

### 6. 📊 G9 Data Governance
**类型:** 统计面板
**功能:** 显示数据治理的合规状态
**指标:**
- ✅ Compliant (绿色)
- ⚠️ Warning (黄色)

### 7. 📈 G12 Dashboard Metrics Export
**类型:** 统计面板
**功能:** 确认指标已导出到仪表板
**指标:** ✅ Metrics Exported

### 8. 🚨 Alert Status
**类型:** 统计面板
**功能:** 显示当前告警状态
**指标:**
- ❌ Failed Checks
- ⚠️ Warnings

### 9. 📋 All Governance Criteria Status
**类型:** 表格
**功能:** 显示所有治理标准的详细状态
**包含:** 标准名称、风险层级、合规率

### 10. 📊 Total Operations Counter
**类型:** 统计面板
**功能:** 显示总操作数

### 11. ⏱️ Average Response Time
**类型:** 统计面板
**功能:** 显示平均响应时间
**颜色阈值:**
- 绿色: 0-2秒
- 黄色: 2-5秒
- 红色: >5秒

---

## 🔧 导入步骤

### 1. 准备Prometheus数据源

确保Prometheus正在运行并抓取backend的指标：

```yaml
# prometheus.yml
scrape_configs:
  - job_name: 'ai-louie-backend'
    static_configs:
      - targets: ['backend:8888']
    metrics_path: '/metrics'
    scrape_interval: 10s
```

### 2. 导入仪表板到Grafana

**方法一：通过UI导入**

1. 打开Grafana: http://localhost:3000
2. 登录（默认: admin/admin）
3. 点击左侧菜单的 **"+"** → **"Import"**
4. 点击 **"Upload JSON file"**
5. 选择 `monitoring/grafana-ai-governance-dashboard.json`
6. 选择Prometheus数据源
7. 点击 **"Import"**

**方法二：通过API导入**

```bash
curl -X POST http://localhost:3000/api/dashboards/db \
  -H "Content-Type: application/json" \
  -H "Authorization: Bearer YOUR_API_KEY" \
  -d @monitoring/grafana-ai-governance-dashboard.json
```

### 3. 配置Prometheus数据源

如果还没有配置Prometheus数据源：

1. 在Grafana中，点击 **Configuration** → **Data Sources**
2. 点击 **"Add data source"**
3. 选择 **"Prometheus"**
4. URL填写: `http://prometheus:9090` (Docker网络) 或 `http://localhost:9090` (本地)
5. 点击 **"Save & Test"**

---

## 🎨 仪表板特性

### 自动刷新
- 默认每10秒自动刷新一次
- 可以在时间选择器右侧修改刷新间隔
- 支持的刷新间隔: 5s, 10s, 30s, 1m, 5m, 15m, 30m, 1h

### 时间范围选择
- 默认显示最近1小时的数据
- 支持的时间范围: 5m, 15m, 1h, 6h, 12h, 24h, 2d, 7d, 30d
- 可以使用时间选择器自定义时间范围

### 变量过滤器

仪表板顶部有两个下拉菜单：

1. **Risk Tier** - 按风险层级过滤
   - 选项: All, external_customer_facing, internal, low_risk

2. **Criteria** - 按治理标准过滤
   - 选项: All, g1_safety_case, g2_risk_tiering, ..., g12_dashboard

### 链接导航

仪表板顶部有快速链接：
- **Backend Logs** - 查看API文档
- **Prometheus Metrics** - 查看原始指标
- **Frontend UI** - 打开Streamlit界面

---

## 📊 Prometheus查询示例

### 1. 检查点成功率
```promql
sum(rate(ai_governance_checkpoint_total{status="passed"}[5m])) by (criteria)
/
sum(rate(ai_governance_checkpoint_total[5m])) by (criteria)
```

### 2. 操作延迟P95
```promql
histogram_quantile(0.95, rate(ai_governance_latency_seconds_bucket[5m])) by (operation_type)
```

### 3. 权限检查失败次数
```promql
sum(ai_governance_checkpoint_total{criteria="g4_permission_layers",status="failed"})
```

### 4. 数据治理警告次数
```promql
sum(ai_governance_checkpoint_total{criteria="g9_data_governance",status="warning"})
```

### 5. 总操作数
```promql
sum(ai_governance_operation_total)
```

### 6. 平均响应时间
```promql
avg(rate(ai_governance_latency_seconds_sum[5m]) / rate(ai_governance_latency_seconds_count[5m]))
```

---

## 🚨 配置告警

### Grafana告警示例

**1. 高权限失败率告警**

```yaml
alert: HighPermissionFailures
expr: rate(ai_governance_checkpoint_total{criteria="g4_permission_layers",status="failed"}[5m]) > 0.1
for: 5m
labels:
  severity: warning
annotations:
  summary: "High rate of permission check failures"
  description: "Permission failures exceeded 0.1 req/s for 5 minutes"
```

**2. 数据治理问题告警**

```yaml
alert: DataGovernanceIssues
expr: sum(ai_governance_checkpoint_total{criteria="g9_data_governance",status="warning"}) > 10
for: 10m
labels:
  severity: warning
annotations:
  summary: "Multiple data governance warnings detected"
  description: "More than 10 data governance warnings in the last 10 minutes"
```

**3. 高延迟告警**

```yaml
alert: HighLatency
expr: histogram_quantile(0.95, rate(ai_governance_latency_seconds_bucket[5m])) > 5
for: 5m
labels:
  severity: critical
annotations:
  summary: "High operation latency detected"
  description: "P95 latency exceeded 5 seconds for 5 minutes"
```

---

## 🔍 故障排查

### 问题1: 仪表板显示"No data"

**解决方法:**
1. 检查Prometheus是否正在运行
   ```bash
   curl http://localhost:9090/-/healthy
   ```

2. 检查backend的metrics endpoint
   ```bash
   curl http://localhost:8888/metrics | grep ai_governance
   ```

3. 检查Prometheus是否抓取了backend
   - 打开 http://localhost:9090/targets
   - 确认backend target状态为"UP"

### 问题2: 按钮无法点击

**解决方法:**
1. 检查URL是否正确
2. 确认相关服务正在运行
   ```bash
   docker-compose ps
   ```

### 问题3: 指标显示为0

**解决方法:**
1. 发送几个测试查询
   ```bash
   curl -X POST http://localhost:8888/api/rag/ask-smart \
     -H "Content-Type: application/json" \
     -d '{"question":"Test query","top_k":3}'
   ```

2. 等待10-20秒让Prometheus抓取指标

3. 刷新仪表板

---

## 📈 最佳实践

### 1. 监控建议

- **每天检查**：合规率仪表盘，确保所有标准>90%
- **每周审查**：延迟趋势，识别性能下降
- **每月分析**：操作分布，优化资源配置

### 2. 告警策略

- **Critical (紧急)**: 合规率<70%，P95延迟>10秒
- **Warning (警告)**: 合规率<90%，P95延迟>5秒
- **Info (信息)**: 新部署、配置变更

### 3. 数据保留

- **短期 (1周)**: 1秒粒度数据
- **中期 (1月)**: 1分钟粒度数据
- **长期 (1年)**: 1小时粒度数据

---

## 🎯 使用场景

### 场景1: 实时监控

1. 打开仪表板
2. 设置自动刷新为10秒
3. 观察"Governance Checkpoints by Status"面板
4. 如有异常，点击"Backend Logs"按钮查看详情

### 场景2: 性能分析

1. 选择时间范围为"Last 24h"
2. 查看"Operation Latency (P95)"面板
3. 识别高延迟时间段
4. 使用"Total Operations Counter"面板关联负载

### 场景3: 合规审计

1. 导出"All Governance Criteria Status"表格
2. 检查所有标准的合规率
3. 对于<90%的标准，点击对应的G4/G9/G12面板查看详情
4. 生成合规报告

### 场景4: 故障诊断

1. 查看"Alert Status"面板
2. 如有失败/警告，查看对应的治理标准面板
3. 点击"API Docs"按钮查看API端点
4. 点击"Metrics"按钮查看原始指标数据

---

## 📚 相关文档

- [AI Governance Framework](./CONSOLIDATED/AI_GOVERNANCE_FRAMEWORK.md)
- [Governance Checkpoints Guide](./GOVERNANCE_CHECKPOINTS_GUIDE.md)
- [Implementation Complete Report](../GOVERNANCE_IMPLEMENTATION_COMPLETE.md)
- [Prometheus Metrics](../backend/backend/services/metrics.py)

---

## 🎉 总结

AI Governance Dashboard 提供了：

✅ **13个可视化面板** - 全面监控治理合规性
✅ **4个快速操作按钮** - 便捷访问系统组件
✅ **实时数据刷新** - 10秒自动更新
✅ **交互式过滤器** - 按风险层级和标准过滤
✅ **颜色编码告警** - 快速识别问题
✅ **详细的表格视图** - 深入分析合规状态

---

**版本:** 2.0
**最后更新:** 2025-12-04
**维护者:** AI Team
