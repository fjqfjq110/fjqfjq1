# LOF 实时数据查询系统

前后端分离项目，展示 LOF 基金的实时交易价格、溢价率和申购限额。

## 技术栈

| 端 | 技术 |
|---|---|
| 前端 | Vue 3 + Vite + Element Plus + Axios |
| 后端 | FastAPI + Uvicorn + akshare + pandas |

---

## 目录结构

```
lof_project/
├── start.sh            # 一键启动脚本
├── back/               # 后端服务
│   ├── main.py         # FastAPI 主程序
│   └── requirements.txt
├── front/              # 前端项目
│   └── vite-project/
│       ├── package.json
│       └── src/
└── README.md
```

---

## 快速启动（推荐）

> 一键同时启动前后端，自动切换 Node 版本。

```bash
./start.sh
```

脚本会自动完成：

1. 激活后端 Python 虚拟环境，启动 FastAPI（`http://localhost:8000`）
2. 通过 `nvm use` 切换到 `.nvmrc` 指定的 Node 版本，启动 Vite 开发服务器（`http://localhost:5173`）
3. 按 `Ctrl+C` 同时停止所有服务

---

## 一、后端服务（手动启动）

### 前置要求

- Python 3.10+（[下载地址](https://www.python.org/downloads/)）

### 1. 安装依赖

```bash
cd back

# 创建虚拟环境（推荐）
python -m venv venv

# 激活虚拟环境
# macOS / Linux
source venv/bin/activate

# Windows
venv\Scripts\activate

# 安装依赖
pip install -r requirements.txt
```

### 2. 启动服务

```bash
# 确保在 back 目录且虚拟环境已激活
source venv/bin/activate

uvicorn main:app --reload --port 8000
```

- `main:app` — `main.py` 中的 `app` 实例
- `--reload` — 开发模式，代码修改自动重启
- `--port 8000` — 服务端口

### 3. 验证

- API 文档：[http://127.0.0.1:8000/docs](http://127.0.0.1:8000/docs)
- LOF 数据接口：[http://127.0.0.1:8000/api/lof](http://127.0.0.1:8000/api/lof)

---

## 二、前端服务（手动启动）

> **前置要求**：电脑上需安装 [nvm](https://github.com/nvm-sh/nvm)（Node 版本管理工具）。

### 1. 切换 Node 版本

前端项目通过 `.nvmrc` 文件锁定 Node 版本（当前为 `v22.21.1`）。

**macOS / Linux：**

```bash
cd front/vite-project

# 自动读取 .nvmrc 中的版本并切换
nvm use

# 如果该版本未安装，先安装再切换
nvm install
nvm use
```

**Windows：**

Windows 版 nvm 不支持自动读取 `.nvmrc`，需显式指定版本号：

```bash
cd front/vite-project

nvm install v22.21.1
nvm use v22.21.1
```

### 2. 安装依赖

```bash
npm install
```

### 3. 启动服务

```bash
npm run dev
```

默认运行在 [http://localhost:5173](http://localhost:5173)

### 3. 构建生产包

```bash
npm run build
```

---

## 三、接口说明

### GET `/api/lof`

获取全量 LOF 实时数据。

**返回字段：**

| 字段 | 类型 | 说明 |
|---|---|---|
| `fundCode` | string | 基金代码 |
| `fundName` | string | 基金名称 |
| `tradePrice` | number | 最新交易价 |
| `increaseRate` | number | 涨跌幅（%）|
| `netValue` | number | 最新净值 |
| `premiumRate` | number | 溢价率（%）|
| `purchaseLimit` | string | 日申购限额 |
| `purchaseStatus` | string | 申购状态 |

**限额显示规则：**
- `不限` — 日限额 ≥ 1 亿
- `暂停申购` — 日限额为 0
- `xx元/日` — 日限额 < 1 万
- `xx万/日` — 日限额 ≥ 1 万

---

## 四、常见问题

### 1. 后端端口被占用

```bash
# 查找占用 8000 端口的进程并结束
lsof -ti:8000 | xargs kill -9
```

### 2. 前端请求后端接口失败

确保后端服务已启动，且 CORS 配置正确（默认允许所有来源）。
