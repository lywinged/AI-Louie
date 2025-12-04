# Smart RAG Bandit 权重持久化指南

**日期:** 2025-12-04
**版本:** v1.0
**状态:** ✅ 已实现

---

## 🎯 核心问题解答

### Q: "我每次启动都要预热吗？比如这次预热后的权重能保存吗"

**A: 不需要！权重现在会自动保存并在重启后加载。** ✅

---

## 📁 持久化机制

### 自动保存

**每次 bandit 更新后自动保存:**
- 位置: `./cache/smart_bandit_state.json`
- 触发: 每次查询后 reward 更新
- Docker volume 挂载: 数据持久化在宿主机

### 自动加载

**系统启动时自动加载:**
- Backend 启动时读取 `./cache/smart_bandit_state.json`
- 如果文件不存在，使用默认初始状态
- 无需手动干预

---

## 🔧 配置

### .env 配置

```env
# === Thompson Sampling Bandit Persistence ===
# Bandit state file path - persistent across restarts
BANDIT_STATE_FILE=./cache/smart_bandit_state.json
```

### Docker Volume 挂载

**docker-compose.yml** 已配置:
```yaml
backend:
  volumes:
    - ./cache:/app/cache  # Bandit 权重持久化目录
```

---

## 📊 状态文件格式

### 示例: smart_bandit_state.json

```json
{
  "hybrid": {
    "alpha": 1.82,
    "beta": 1.18
  },
  "iterative": {
    "alpha": 5.2,
    "beta": 7.8
  },
  "graph": {
    "alpha": 8.5,
    "beta": 1.5
  },
  "table": {
    "alpha": 1.3,
    "beta": 1.7
  }
}
```

### 参数含义

**Beta Distribution: Beta(α, β)**

- **alpha (α):** 累积的"成功"次数
  - 每次高 reward 会增加 alpha
  - 例如: reward=0.8 → alpha += 0.8

- **beta (β):** 累积的"失败"次数
  - 每次低 reward 会增加 beta
  - 例如: reward=0.2 → beta += 0.8

- **Trials (试验次数):** α + β - 2
  - 表示该策略被选中的总次数

- **Win Rate (胜率):** α / (α + β)
  - 表示策略的期望成功概率
  - 用于 Thompson Sampling 采样

---

## 🛠️ 管理工具

### 查看当前状态

```bash
python scripts/manage_bandit_state.py view
```

**输出示例:**
```
================================================================================
Smart RAG Bandit State
================================================================================

State file: ./cache/smart_bandit_state.json
Last modified: 1733281234.5

Strategy Weights (Beta Distribution Parameters):
--------------------------------------------------------------------------------
Strategy        Alpha      Beta       Trials     Win Rate
--------------------------------------------------------------------------------
graph           8.50       1.50       8          85.00%
hybrid          1.82       1.18       2          60.67%
iterative       5.20       7.80       11         40.00%
table           1.30       1.70       2          43.33%

💡 Interpretation:
  - Alpha: Accumulated 'success' (high reward)
  - Beta: Accumulated 'failure' (low reward)
  - Trials: Total number of times this strategy was selected
  - Win Rate: Expected probability of success (alpha / (alpha + beta))
```

### 重置状态

```bash
# 交互式重置（会询问确认）
python scripts/manage_bandit_state.py reset

# 强制重置（跳过确认）
python scripts/manage_bandit_state.py reset --yes
```

**效果:**
- 删除 `./cache/smart_bandit_state.json`
- 下次启动使用默认初始状态
- 所有策略回到 Beta(1, 1)

### 导出备份

```bash
# 导出到默认文件
python scripts/manage_bandit_state.py export bandit_backup.json

# 导出到指定文件
python scripts/manage_bandit_state.py export my_best_weights.json
```

**用途:**
- 保存最佳权重
- 版本控制
- 跨环境迁移

### 导入权重

```bash
# 从备份恢复
python scripts/manage_bandit_state.py import bandit_backup.json

# 从生产环境导入
python scripts/manage_bandit_state.py import production_weights.json
```

**效果:**
- 覆盖当前 `./cache/smart_bandit_state.json`
- 重启后生效

---

## 🚀 使用流程

### 第一次部署

```bash
# 1. 启动系统
./start.sh

# 2. 运行预热（一次性）
python scripts/warm_smart_bandit.py --rounds 2

# 3. 权重自动保存
# ./cache/smart_bandit_state.json 已创建

# 4. 查看学习结果
python scripts/manage_bandit_state.py view
```

### 之后每次启动

```bash
# 直接启动，自动加载权重
./start.sh

# 🎉 不需要重新预热！
```

### 检查权重

```bash
# 随时查看当前权重
python scripts/manage_bandit_state.py view
```

---

## 📈 实际使用场景

### 场景 1: 本地开发

```bash
# 第一次: 预热 + 保存
python scripts/warm_smart_bandit.py --rounds 3
python scripts/manage_bandit_state.py view

# 之后每天:
./start.sh  # 自动加载权重，无需预热
```

### 场景 2: 测试环境 → 生产环境

```bash
# === 测试环境 ===
# 1. 充分预热
python scripts/warm_smart_bandit.py --rounds 5

# 2. 导出最佳权重
python scripts/manage_bandit_state.py export best_weights.json

# 3. 上传到生产
scp best_weights.json prod-server:/app/cache/smart_bandit_state.json

# === 生产环境 ===
# 4. 启动时自动加载
./start.sh
```

### 场景 3: 多环境同步

```bash
# 环境 A (已充分学习)
python scripts/manage_bandit_state.py export weights_v1.json

# 环境 B (新部署)
python scripts/manage_bandit_state.py import weights_v1.json
./start.sh  # 立即使用环境 A 的学习成果
```

### 场景 4: 版本回退

```bash
# 保存当前版本
python scripts/manage_bandit_state.py export weights_v2.json

# 回退到旧版本
python scripts/manage_bandit_state.py import weights_v1.json
docker-compose restart backend
```

### 场景 5: A/B 测试

```bash
# 策略 A
python scripts/manage_bandit_state.py export strategy_a.json

# 策略 B (重新学习)
python scripts/manage_bandit_state.py reset --yes
python scripts/warm_smart_bandit.py --rounds 3 --custom-config
python scripts/manage_bandit_state.py export strategy_b.json

# 比较性能
# ...

# 选择最佳策略
python scripts/manage_bandit_state.py import strategy_a.json  # 或 strategy_b.json
```

---

## 🔍 监控和维护

### 查看学习进度

```bash
# 每周查看一次权重演变
python scripts/manage_bandit_state.py view > weekly_state_$(date +%Y%m%d).txt
```

### 权重异常检测

```bash
# 检查是否有策略被"过度探索"或"探索不足"
python scripts/manage_bandit_state.py view

# 如果发现:
# - Trials < 5: 该策略探索不足
# - Win Rate < 20%: 该策略可能不适合，但仍在探索
# - Win Rate > 90%: 该策略表现优异
```

### 定期备份

```bash
# 添加到 crontab
0 0 * * 0 cd /app && python scripts/manage_bandit_state.py export backup_$(date +%Y%m%d).json
```

---

## ⚠️ 注意事项

### 1. Docker Volume 持久化

**确保 docker-compose.yml 正确配置:**
```yaml
backend:
  volumes:
    - ./cache:/app/cache  # 必须挂载
```

**否则重启容器会丢失权重！**

### 2. 文件权限

```bash
# 确保 cache 目录可写
mkdir -p cache
chmod 755 cache
```

### 3. 并发更新

当前实现在单实例 backend 下工作良好。

**多实例部署（负载均衡）注意:**
- 每个实例有独立的权重文件
- 需要共享存储（如 NFS, S3）来同步权重
- 或使用 Redis/数据库存储权重

### 4. 权重版本控制

```bash
# 建议将关键版本提交到 git
git add cache/smart_bandit_state.json
git commit -m "Save bandit weights after production warmup"
```

---

## 🐛 故障排查

### 问题 1: 重启后权重丢失

**可能原因:**
1. Docker volume 未挂载
2. 文件路径配置错误
3. 容器无写权限

**解决方法:**
```bash
# 1. 检查 volume 挂载
docker inspect backend-api | grep -A 10 Mounts

# 2. 检查文件是否存在
docker exec backend-api ls -la /app/cache/

# 3. 检查环境变量
docker exec backend-api env | grep BANDIT_STATE_FILE

# 4. 手动创建目录
mkdir -p cache
chmod 755 cache
```

### 问题 2: 无法保存权重

**可能原因:**
1. 目录不存在
2. 权限不足
3. 磁盘空间不足

**解决方法:**
```bash
# 检查日志
docker logs backend-api 2>&1 | grep "bandit state"

# 检查磁盘空间
df -h

# 手动测试写入
docker exec backend-api touch /app/cache/test.txt
```

### 问题 3: 权重加载失败

**可能原因:**
1. JSON 格式错误
2. 文件损坏
3. 版本不兼容

**解决方法:**
```bash
# 验证 JSON 格式
jq . cache/smart_bandit_state.json

# 如果损坏，从备份恢复
python scripts/manage_bandit_state.py import backup.json

# 或重置
python scripts/manage_bandit_state.py reset --yes
```

---

## 📋 最佳实践

### 1. 定期备份

```bash
# 每周自动备份
0 0 * * 0 python scripts/manage_bandit_state.py export weekly_backup.json
```

### 2. 版本标记

```bash
# 在重要里程碑导出
python scripts/manage_bandit_state.py export v1.0_production.json
python scripts/manage_bandit_state.py export v1.1_after_optimization.json
```

### 3. 监控学习曲线

```bash
# 定期查看并记录
python scripts/manage_bandit_state.py view | tee logs/bandit_state_$(date +%Y%m%d).log
```

### 4. 渐进式部署

```bash
# 测试环境验证新权重
python scripts/manage_bandit_state.py import new_weights.json
# 运行 A/B 测试
# 确认性能提升后部署到生产
```

---

## ✅ 总结

### 持久化功能的好处

1. **✅ 免预热启动** - 重启后立即使用学习成果
2. **✅ 持续优化** - 每次查询都更新权重
3. **✅ 可迁移部署** - 测试环境权重→生产环境
4. **✅ 版本管理** - 导出/导入/回退
5. **✅ 故障恢复** - 备份/恢复机制

### 工作流程

```
第一次部署:
  启动 → 预热 → 自动保存 → 完成

之后每次启动:
  启动 → 自动加载 → 直接使用 ✅

定期维护:
  查看权重 → 导出备份 → 版本管理
```

### 下一步

1. ✅ 预热脚本已在运行
2. ✅ 权重会自动保存到 `./cache/smart_bandit_state.json`
3. ✅ 下次启动无需预热
4. 📊 定期用 `manage_bandit_state.py view` 查看学习进度

---

**版本:** 1.0
**最后更新:** 2025-12-04
**状态:** ✅ Production Ready
**文档:** [BANDIT_PERSISTENCE_GUIDE.md](./BANDIT_PERSISTENCE_GUIDE.md)
