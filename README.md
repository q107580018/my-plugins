# my-plugins

MoviePilot 三方插件仓库。  
当前维护插件：`OpenListStrmSyncDel`（V2）。

## 安装说明

1. 打开 MoviePilot 插件市场。
2. 添加第三方插件仓库地址：

```text
https://github.com/q107580018/my-plugins
```

3. 刷新插件市场后，安装 `OpenListStrmSyncDel`。

## 插件集合

| 插件 | 版本 | 目录 | 说明 |
|---|---:|---|---|
| OpenListStrmSyncDel | 1.3 | `plugins.v2/openliststrmsyncdel` | 监听 `.strm` 删除事件，联动删除 OpenList 源文件并清理空目录 |

## 插件说明

### OpenListStrmSyncDel

- 仅处理“strm资源目录”内的 `.strm` 删除事件。
- 从 `.strm` 内容解析 OpenList 目标路径。
- 仅当目标路径命中“监控的源文件路径（OpenList 路径）”时，执行删除。
- 删除文件后会向上清理空目录（带保护逻辑，避免误删入口目录）。
- 启动时会做 `strm` 预扫描并建立缓存映射。

配置要点：

- `OpenList Token`：OpenList 接口鉴权。
- `监控的源文件路径`：填写 OpenList 路径前缀（如 `/115`、`/quark/videos`），不是本地 `/media/...`。
- `strm资源目录`：填写本地 `.strm` 存放目录（如 `/media/videos_strm/115_strm`）。
- 多个路径支持换行、英文逗号、中文逗号、分号分隔。

## 仓库结构

```text
my-plugins/
├── package.v2.json
├── icons/
│   └── Alist_B.png
└── plugins.v2/
    └── openliststrmsyncdel/
        └── __init__.py
```

## 版本同步规则

- 修改插件后请同步更新：
- `plugins.v2/openliststrmsyncdel/__init__.py` 中 `plugin_version`
- `package.v2.json` 中 `version` 与 `history`
