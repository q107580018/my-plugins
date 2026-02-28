# AGENTS

## 项目定位
- 这是一个独立插件仓库，不是完整 MoviePilot 主仓。
- 当前仅维护 1 个 V2 插件：`OpenListStrmSyncDel`。
- 目标：在删除事件触发时，同步删除 OpenList 中的源文件并清理空目录。

## 关键结构
- `plugins.v2/openliststrmsyncdel/__init__.py`：插件入口与全部业务逻辑。
- `package.v2.json`：V2 插件索引与展示元数据。
- `icons/Alist_B.png`：插件图标资源。
- `README.md`：仓库说明（结构简述）。

## 当前功能事实（以代码为准）
- 插件类：`OpenListStrmSyncDel`，继承 `_PluginBase`。
- 启用条件：`enabled=true` 且 `token` 非空 且 `monitor_source_paths` 解析后非空（见 `get_state`）。
- 监听事件：
- `EventType.TransferComplete`：入库后读取 `.strm` 并缓存 `strm -> base_url + target_path`。
- `EventType.DownloadFileDeleted`：处理源文件删除。
- `EventType.PluginAction`：仅处理 `action=networkdisk_del`。
- `EventType.WebhookMessage`：仅处理 `library.deleted` 与 `media_del`。
- 删除策略：
- 先从 `.strm` 内容或事件路径解析 OpenList 目标；必要时回退缓存与最近一次 `base_url`。
- 仅当目标路径命中 `monitor_source_paths` 前缀时才执行删除。
- 300 秒内同一路径重复删除会被去重。
- OpenList API：
- 删除文件/目录：`POST /api/fs/remove`。
- 判空目录：`POST /api/fs/list`（每页 1 条用于快速判空）。
- 目录清理：
- 删除文件成功后向上清理空目录。
- 若监控根是 `/`，会保护一级目录，避免误删入口目录（如 `/115`）。
- 缓存与历史：
- 数据键：`strm_content_map`、`history`。
- 上限：缓存 3000 条、历史 200 条。
- `token` 请求头先尝试原值，失败后自动补 `Bearer ` 前缀重试。
- `get_command`、`get_api`、`get_page` 目前未实现（`pass`）。

## 开发和发布规则
- 目录名保持小写：`plugins.v2/openliststrmsyncdel`。
- 入口文件固定：`plugins.v2/openliststrmsyncdel/__init__.py`。
- 修改版本时保持一致：
- 同步更新 `__init__.py` 中 `plugin_version`。
- 同步更新 `package.v2.json` 中对应 `version` 与 `history`。
- 图标名保持一致：代码/索引都引用 `Alist_B.png`。
- 提交前至少执行：
- `python3 -m py_compile plugins.v2/openliststrmsyncdel/__init__.py`
- `git diff -- plugins.v2/openliststrmsyncdel/__init__.py package.v2.json README.md`（仅在 Git 仓库内）

## 配置与安全
- `token` 属于敏感信息，只在运行环境插件配置中填写，不写入仓库文件。
- `monitor_source_paths` 支持每行一个路径；可写纯路径或可解析出路径的 URL。
- 仓库内无 `.env` 约定，配置以宿主系统插件表单为准。
- 日志会打印删除目标路径与事件名，生产环境注意日志访问权限。

## 维护建议
- 补齐 `get_page`，展示最近删除历史（当前已有 `history` 数据可复用）。
- 为 `__extract_openlist_path` 的多种 URL 形态补最小化测试样例。
- 在 API 异常分支增加更细粒度日志（区分鉴权失败、路径不存在、网络失败）。
- 若后续增加插件，优先保持“一插件一目录 + package.v2.json 显式索引”。
