# DAG 任务编排调度平台

浏览器里拖拽设计有向无环任务图，后端调度器按拓扑序驱动执行：节点状态实时流转、
并发上限约束、节点级失败重试、上游失败跳过纯下游、运行状态持久化并支持调度器重启恢复。
节点执行为可配置时长与成败结果的模拟作业，不接入真实计算集群。

## 一键启动

```bash
docker compose up --build
```

| 入口 | 地址 |
| --- | --- |
| 编排画布（前端） | http://localhost:8080 |
| 后端 API | http://localhost:8000 （文档 `/docs`，健康检查 `/api/health`） |
| PostgreSQL 16 | localhost:5432 （`dag`/`dag`） |

打开页面后点「新建编排 → 载入示例 → 保存并运行」即可看到完整演示。

## 功能与规则

- **编排设计**：拖拽增删节点、连线声明依赖；节点携带模拟时长、成败策略
  （总是成功 / 总是失败 / 前 N 次失败后成功）与重试策略（最大重试次数、退避间隔）；
  整图设置最大并行节点数。
- **校验**：保存/运行前校验——成环（返回并高亮环路经过的节点）、连线指向不存在的
  节点、并发上限非正、重试次数/时长/间隔为负、节点标识重复或为空，都会被拒绝并说明原因；
  带环的图无法进入调度器（保存拒绝 + 运行前防御性复检）。
- **调度执行**：合法图按确定性拓扑序（Kahn + 字典序堆）推进；前驱全部成功才就绪；
  任一前驱失败/被跳过则该节点置为「跳过（不满足）」并沿拓扑序向下传播；互不依赖的
  分支并行推进；同一运行中任意时刻运行中节点数不超过并发上限，有节点结束才递补。
- **重试**：节点失败后按自己的重试次数与退避间隔重试（退避不占用并发额度、不阻塞
  无依赖分支）；重试用尽才判失败并向下游传播。
- **持久化与恢复**：图、运行实例、节点状态、每次尝试（成功/失败/中断）全部落库
  PostgreSQL；调度器重启后读回未完成的运行——运行中的节点记一次「中断」尝试
  （不消耗重试预算）并重新排队，已完成节点绝不重跑；同一图可发起多次运行，
  各次运行状态完全隔离（运行时快照节点配置、边与拓扑序）。

## 代码结构

```
backend/
  app/
    main.py          # FastAPI 入口与生命周期（等库、建表、启动调度器）
    config.py        # 环境变量配置
    db.py            # 引擎/会话/UTC 时钟
    models.py        # ORM：图、节点、边、运行、运行节点、尝试记录
    schemas.py       # API 载荷
    graph_logic.py   # 环检测（返回环路路径）、确定性拓扑排序、图校验
    executor.py      # 节点执行结果策略与重试状态机
    scheduler.py     # 调度循环、并发闸门、异步执行任务
    recovery.py      # 重启恢复：中断尝试标记 + 运行中节点重新排队
    service.py       # 图持久化转换、运行实例快照创建（运行前复检）
    serialize.py     # ORM -> API 转换
    routes/          # graphs.py（图 CRUD+校验） runs.py（发起运行/观测/重试历史）
  tests/             # pytest：图算法 / 调度行为 / 恢复 / API 校验
frontend/
  src/
    components/EditorCanvas.tsx  # 编排画布（拖拽、连线、校验、环路高亮）
    components/RunView.tsx       # 运行观测（状态着色、轮询、重试历史）
    components/TaskNode.tsx      # 画布节点（状态着色）
    components/NodePanel.tsx     # 节点配置面板
    components/GraphList.tsx     # 图列表与运行记录
```

## 运行测试

```bash
cd backend
pip install -r requirements-dev.txt
pytest
```

覆盖：成环检出并指明环路、拓扑序推进且可复现、无依赖分支并行、运行中节点数不超
并发上限、上游失败纯下游置为不满足、重试用尽才判失败且不阻塞旁支、多次运行状态
隔离、调度器重启后恢复而非全部重跑、连到不存在节点/并发上限非正/重试次数为负被拒。

## 主要 API

| 方法 | 路径 | 说明 |
| --- | --- | --- |
| GET/POST | `/api/graphs` | 图列表 / 创建（校验失败 400 并返回 `errors` 与 `cycle`） |
| GET/PUT/DELETE | `/api/graphs/{id}` | 查询 / 更新 / 删除 |
| POST | `/api/graphs/validate` | 不保存的实时校验（画布用） |
| POST | `/api/graphs/{id}/runs` | 发起运行（运行前复检，带环拒绝） |
| GET | `/api/runs` `/api/runs/{id}` | 运行列表 / 运行详情（含节点状态） |
| GET | `/api/runs/{id}/nodes/{key}/attempts` | 节点重试历史 |

## 本地开发（不用 Docker）

```bash
# 后端（默认连 localhost:5432 的 PostgreSQL，可用 DATABASE_URL 覆盖）
cd backend && pip install -r requirements.txt
uvicorn app.main:app --reload

# 前端（/api 代理到 localhost:8000）
cd frontend && npm install && npm run dev
```
