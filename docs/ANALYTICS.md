# 内测统计部署与口径

## 状态

客户端已实现：默认关闭、SQLite 持久化、每 30 秒最多上传 100 条、失败后重试、退出不阻塞、关闭后清除待上传队列。上限 50000 条，超出丢弃最旧记录；这是有损上限，内测应关注待上传数量。数据库位于 `%LOCALAPPDATA%/JevChat/analytics/events.sqlite3`。

没有真实账户、未做线上接收验证。当前无刷新和划走事件，不统计发送成功。填入只报告执行完成，未确认微信输入框真实内容。突然退出可能没有结束事件，因此未完成生成请求应单列为未知，不能算成功。

## 发布配置

1. 创建 PostHog 项目，选择 EU 或 US。项目地区一旦确定，所有测试者使用同一个项目。
2. 在 `app/analytics_config.py` 填写公开的 `phc_` 项目采集 Token 和区域，然后打包。禁止放入 `phx_` 个人密钥。首次安装将使用发布配置；已有安装需在统计设置中更新。
3. 测试者打开设置 → 内测使用统计 · PostHog，阅读说明并主动开启。默认不采集、不上传；未开启期间的行为不补采。测试者无需 PostHog 账户。
4. 发布说明必须填写组织者联系渠道、云端数据保留时间和删除申请方式。数据落在美国/欧盟；随机安装标识不等于法律意义的完全匿名。
5. 先使用合成对话进行一次生成、曝光、填入、复制，在 PostHog Activity 查看事件；核对字段没有聊天原文。调试期间不需要录屏、自动异常采集或模型内容采集。
6. 在 SQL insight 中粘贴 `analytics_overview.sql`，保存到名为 Jev Chat 内测的 Dashboard。SQL 尚未在线项目执行，需在项目中验证。留存按下文使用 Retention insight 配置。

关闭统计会删除未上报队列；已进入网络的请求不能撤回，已经上传的数据需要在云端另行处理。本地已上传记录仍保留至条数上限。客户端采集 Token 不是保密凭据，公开内测仍可能遇到伪造事件；扩大规模时应增加网关限流。网络服务可能收到 IP，即使关闭 GeoIP 也不表示网络层不处理 IP。

## 指标

- 分母为实际可操作的批次曝光，按 suggestion_id 去重。缓存重新展示不会新增批次曝光。Qt 可见区域检测每 500ms 采样一次，不表示用户真正阅读；短于采样周期的曝光可能漏记。
- 填入点击率：曝光批次中有 fill_clicked 的批次占比。重复点击不重复计批次。
- 复制率：曝光批次中有 reply_copied 的批次占比。
- 操作采用率：曝光批次中有任一上述行为的批次占比，不等于发送。
- 无操作离开：有 suggestion_left 且至查询时没有填入/复制。离开可能是会话切换或失效，不是拒绝；之后返回操作会改变这一结果。
- 生成成功率：generation_finished 中 status=success 的去重任务数 / 所有已完成任务。一个 suggestion_id 对应一个生成任务。
- 填入执行完成率：fill_execution_finished 中 executed_unverified / 所有去重 attempt_id，不是已确认填入成功。
- 展示耗时：suggestion_exposed.duration_ms，包括检索、生成及等待可见。缓存很晚才展示会增加时长，建议同时看 generation_finished.duration_ms。
- 推荐分布：fill_clicked/reply_copied 按 position、recommended 分组；原始 candidate_index 与 position 分开。三张卡片未逐张检测曝光，不能据此计算每张卡的曝光点击率。
- 次日/第7日留存：创建 Action `reply_used`，包含 fill_clicked 或 reply_copied。Retention 使用该 Action 的首次发生为起点、再次发生为返回，按自然日和 Asia/Shanghai 查看第 1/7 天。只看成熟批次，按安装实例统计。若当前 UI 不支持首次发生口径，需要 SQL cohort 查询，不能用普通任意回访留存替代。
- 关闭统计、重装或上传失败会导致缺失；仅代表参与统计的安装实例。用 app_version 筛选版本。

## 本地验证

```
python -m unittest evaluation_run.test_analytics evaluation_run.test_analytics_ui -v
```

测试使用临时数据库与假的网络发送器，不发送真实统计。UI 测试使用合成文本和模拟填入。
