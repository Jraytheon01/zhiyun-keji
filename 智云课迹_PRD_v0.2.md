# 智云课迹 PRD v0.2

> 产品全称：智云课迹——基于 TeleAgent 的可信学习内容与成长管理平台  
> 品牌表达：智汇每堂课，云续成长迹  
> 产品口号：让每一堂课，都通向更懂你的下一步  
> 文档状态：可用于比赛 Demo 开发的需求基线  
> 更新时间：2026-08-13  
> 本版重点：基于当前真实数据库表设计平台功能与“学习成长中心”

---

## 1. 产品结论

“智云课迹”不是培训平台，不是录音产品，也不是另一套通用 AI 学习应用。它是 TeleAgent 学习场景背后的可信内容与长期状态管理平台：面向校内课堂、课后服务、家庭共学、社区公益课堂及合规辅导等已经发生的学习场景，把课程内容准备给 TeleAgent 使用，并保存互动后产生的学习结果、成长变化和下一步计划。

完整闭环为：

> 课程录入 → 内容理解 → 课后复盘 → 即时小测 → 作答判分 → 错题留痕 → 掌握状态变化 → 生成续学计划 → 下一次课程继续验证。

比赛版只证明一个核心价值：

> 学生的一次真实错答，能够依据课堂原文改变平台保存的学习状态，并影响“学习成长中心”中的下一步计划。

实施原则：

1. 课程原始数据直接复用 `user_meeting_info` 和 `user_meeting_content`，不再新建重复的课程主表和逐字稿表。
2. Ingest、Worker、MySQL、Milvus、Ark、MCP、Bridge、TeleAgent 链路继续复用。
3. 只新增教育业务缺失的数据：学生、课程教育属性、知识点、试卷、作答、错题、学习事件、掌握状态、教育记忆和续学计划。
4. ASR 可以面向展示；课程读取、试卷作答、判分、错题、状态更新和计划变化必须真实。

---

## 2. 名称与品牌立意

### 2.1 推荐名称

**智云课迹**

- **智**：TeleAgent、星辰大模型、教育 Skill 和内容理解能力。
- **云**：中国电信云网、跨终端入口、云端持续服务与可信数据承载。
- **课迹**：每堂课的原文证据、每次作答、每个错题和每一步成长都有迹可循。

“智汇每堂课，云续成长迹”是产品品牌表达，不作为页面或功能名称：

- “智汇每堂课”对应课程采集、结构化理解、TeleAgent 生成与跨课关联；
- “云续成长迹”表达课程结束后，云端仍持续保存学习证据并服务下一步；其产品功能统一承载在“学习成长中心”。

### 2.2 产品定位一句话

> 智云课迹，让普通课堂结束后仍能被看懂、被检验，并持续成为下一次学习的依据。

---

## 3. 用户痛点与产品机会

学生在课程结束后常见四个断点：

- **记不全**：信息密度高，边听边记容易遗漏。
- **理不清**：录音、课件和笔记无法自然形成知识结构。
- **验不了**：听懂不等于会做，缺少即时、低负担的学习验证。
- **接不上**：这次不会的内容没有长期留痕，下一次仍然从头开始。

传统录音产品主要回答“课堂讲了什么”，传统题库主要回答“这道题做对没有”。智云课迹要连接二者：

> 老师怎样讲 → 学生怎样答 → 哪里反复不稳 → 下一步应该怎样学。

首版以单学生、数学学科、两节相关课程为可控演示范围；产品表达覆盖学校课堂等普遍场景，不以付费补课作为惠民主叙事。

---

## 4. 真实技术与数据基线

### 4.1 已核验的源数据主表

#### `user_meeting_info`：课程主记录

前端将一条 meeting 映射为一条“课程记录”，API 对外统一使用 `course_id = str(user_meeting_info.id)`。

| 实际字段 | 课程页面用途 |
|---|---|
| `id` | 课程唯一标识，同时作为 Ingest 的 `meeting_id`、派生表的 `recording_id` |
| `phone`、`user_id` | 用户隔离与现有 MCP Key 映射 |
| `meeting_name`、`title` | 课程名称，展示优先级为 `title` 后 `meeting_name` |
| `create_time`、`update_time` | 上课时间、更新时间 |
| `during` | 课程时长，当前单位按毫秒处理 |
| `content` | 整篇转写文本的兼容回退 |
| `abstract_text`、`abstract_content` | 课程摘要，优先使用 `abstract_content` |
| `record_url`、`asr_url` | 音频与 ASR 资源地址 |
| `file_type`、`device_id`、`oper_source` | 来源设备与文件类型展示 |
| `status`、`del_flag`、`rebuild_status` | 可见性、软删除和重建状态 |
| `participants`、`speakers_info_id` | 参与者/说话人辅助信息 |
| `data_json` | 只作上游兼容扩展，不承载新的权威教育状态 |

现有列表逻辑只返回 `status='2' AND del_flag='0'` 的记录，课程管理页必须沿用此口径。

#### `user_meeting_content`：课程逐字稿分段

| 实际字段 | 逐字稿页面用途 |
|---|---|
| `id` | 原文证据片段标识 |
| `meet_id` | 关联 `user_meeting_info.id` |
| `begin_time`、`end_time` | 时间轴定位，毫秒 |
| `speaker` | 说话人标签 |
| `content` | 片段正文 |
| `code` | 上游顺序码 |
| `type` | 当前读取优先级：`1` → `0` → 空值 |
| `create_time` | 片段写入时间 |

知识点、题目、报告和跨课结论必须尽量引用这些片段 ID，而不是只保存一段脱离来源的 AI 文本。

### 4.2 已有派生表与用途

| 表 | 当前职责 | 教育平台复用方式 |
|---|---|---|
| `ingest_jobs` | 接收通知、幂等处理、重试与错误 | 课程导入进度与失败原因 |
| `recordings` | 派生处理状态及 chunk/fact/todo 数量 | 课程“内容已就绪”状态 |
| `chunks` | transcript/summary 分块及向量引用 | 跨课程原文检索 |
| `facts` | entity/preference/relationship/decision/insight 等蒸馏事实 | 通用 Memory 与教育候选事实，不直接替代掌握状态 |
| `todos` | 待办 | 可暂用于 TeleAgent 的通用提醒；正式续学计划使用教育表 |
| `mcp_api_keys` | API Key 哈希到 phone 的映射 | MCP 只读租户隔离 |
| `schema_migrations` | 迁移记录 | 开发启动前的版本门禁 |

### 4.3 当前必须先解决的迁移门禁

2026-08-13 对本地运行库的只读核验显示：`recordings/chunks/facts/todos` 仍有 `user_id`，尚无最新源码所使用的 `phone` 字段；而复制后的 MCP 源码和 `007_use_phone_tenant.sql` 已按 phone 查询与写入。数据库中仅看到 4 条迁移记录。

因此开发前必须执行以下门禁，但本次创建 PRD 不直接改库：

1. 备份现有数据库；
2. 记录 `schema_migrations` 当前版本；
3. 在测试库执行 `005`、`006`、`007` 的幂等迁移或运行项目迁移器；
4. 验证四张派生表的 `phone` 回填量与空值数；
5. 跑现有 MCP 和 Ingest 测试；
6. 验证同一 `recording_id` 不会被其他 phone 读取；
7. 通过后再新增 `edu_` 表。

禁止为了赶 Demo 在前端写死 phone 绕过隔离。

### 4.4 现有模拟录入工具的真实链路

已将 `E:\AI公众\meeting_assistant_demo_tools` 的安全副本放入 `tools/meeting-data-injector`。工具支持：

1. 在表单中输入课程标题、摘要和自然逐字稿；
2. 自动统一说话人、估算时间轴；
3. 事务性写入 `user_meeting_info` 与 `user_meeting_content`；
4. 返回 `meeting_id` 和分段数量；
5. 再使用相同 `phone + meeting_id` 调用 Ingest notification；
6. Ingest 完成后由 Bridge 通知 TeleAgent。

这就是比赛版上传页的后端原型。前端只需为它增加上传/转写进度外壳和任务状态编排，不要另造一套课程存储。

---

## 5. 平台信息架构

一级导航控制为三项。平台不是录音产品，也不是另一套 AI 学习应用；它是 TeleAgent 学习场景的可信内容与长期状态管理平台：

1. **学习台**：今天最值得做什么。
2. **课程库**：课程导入、列表、详情和跨课检索。
3. **成长中心**：长期成长时间轴、掌握地图、学习档案、学习计划和阶段报告。

课程复盘、讲解、思维导图、出题和答题交互均在 TeleAgent 中进行。平台在课程详情和成长中心提供“发送到 TeleAgent”情境按钮，通过 Bridge 创建/路由会话并置前 TeleAgent 窗口。平台只回看结果、错题证据和状态变化，不建设独立答题模块。

比赛版固定一个演示学生，不开发登录、注册、账号切换、角色权限或监护人账号。现有 MCP Key 与 phone 映射继续作为底层既有配置，不新增用户鉴权产品功能。

### 5.1 路由建议

| 路由 | 页面 |
|---|---|
| `/home` | 学习台 |
| `/courses` | 课程库 |
| `/courses/import` | 导入课程 |
| `/courses/:courseId` | 课程详情 |
| `/growth` | 学习成长中心 |
| `/growth/knowledge/:kpId` | 知识点证据抽屉/详情 |
| `/interactions/:runId` | TeleAgent 任务状态与回流结果（次级页面） |

---

## 6. 平台功能详细设计

### 6.1 学习台

目标不是做数据大屏，而是明确告诉学生“下一步做什么”。

#### 页面区块

1. **顶部行动卡**
   - 文案示例：“昨天的二次函数课程还有 1 个知识点待验证，预计 6 分钟。”
   - 主按钮：“发送到 TeleAgent 检测”。
   - 来源：最近一条未完成 `edu_growth_plan_item`。

2. **最近课程**
   - 显示课程名、学科、时间、时长、来源设备、处理状态。
   - 数据来自 `user_meeting_info + recordings + ingest_jobs + edu_course_profile`。
   - 卡片主操作随状态变化：处理中、查看课程、发送到 TeleAgent、查看互动结果。

3. **本周闭环**
   - 只展示可核验的计数：已导入课程、已完成小测、已处理错题、已完成续学项。
   - 不展示无依据的“学习力 92 分”。

4. **最近成长变化**
   - 展示 1—3 条 `edu_learning_event`：例如“平移方向判断：待巩固 → 掌握中”。
   - 每条均可点击查看触发这次变化的题目与课程原文。

#### 空状态

没有课程时只显示一个主入口：“导入我的第一堂课”，并提供“使用演示课程”按钮。

### 6.2 课程导入页

#### 输入方式

- 拖入音频文件：比赛 Demo 使用模拟 ASR 结果；
- 粘贴逐字稿：调用现有 `/api/meetings/from-text` 原型；
- 选择演示样例：快速加载两节相互关联的数学课程。

#### 表单字段

- 课程名称：写入 `title` 与 `meeting_name`；
- 上课时间：写入 `create_time`；
- 学科、年级、场景、来源设备：写入 `edu_course_profile`；
- 摘要与逐字稿：写入两张主表；
- `phone/user_id`：比赛 Demo 使用服务端固定配置，不设计用户填写和登录流程。

#### 可视化处理状态

```text
已接收文件 → 正在转写 → 正在区分说话人 → 已写入课程库
→ 正在理解课程 → 已生成课后入口 → TeleAgent 已收到
```

状态映射：

| 前端阶段 | 真实依据 | Demo 方式 |
|---|---|---|
| 已接收文件 | 前端 upload task | 真实 |
| 正在转写 | `edu_import_task.stage=transcribing` | 定时模拟 |
| 已写入课程库 | 两张主表事务提交成功 | 真实 |
| 正在理解课程 | `ingest_jobs.status=processing/retry` | 真实 |
| 内容已就绪 | `recordings.ingestion_status=done` | 真实 |
| TeleAgent 已收到 | Bridge 返回成功/`edu_agent_run` 状态 | 真实 |

页面必须标注“演示环境使用预置转写结果”，不宣称自研 ASR。

#### 异常处理

- 主表写入失败：整体失败，不调用 Ingest；
- Ingest 失败：课程仍可打开逐字稿，展示“内容理解失败，可重试”；
- Bridge 失败：不影响平台课程和练习，展示“稍后重发 TeleAgent”；
- 重复 `meeting_id`：默认拒绝覆盖；仅开发工具允许显式 replace。

### 6.3 课程库

#### 列表样式

桌面端使用卡片列表而非表格。单卡显示：

- 课程名称：`title || meeting_name`；
- 日期：`create_time`；
- 时长：`during`；
- 学科/年级：`edu_course_profile`；
- 来源图标：`source_device`，缺失时由 `device_id/file_type` 回退；
- 内容状态：转写已就绪、理解中、可发送至 TeleAgent、需重试；
- 闭环状态：未复盘、待完成小测、存在待巩固项、已完成本课闭环。

筛选：学科、日期、课程场景、处理状态；搜索同时查询标题与向量内容。

#### 数据操作

- 编辑课程教育属性：只改 `edu_course_profile`，不改原文；
- 修改标题：同步更新 `user_meeting_info.title/meeting_name`；
- 归档：教育扩展表标记归档；
- 删除：调用平台受控删除流程，软删源记录并使派生教育事件失效；
- 重新理解：复用 `reingest`，不得新增第二条课程。

### 6.4 课程详情

顶部展示课程名、时间、时长、学科、来源、处理状态，以及主按钮“发送到 TeleAgent”和带选项的任务菜单：课程复盘、生成思维导图、学习检测、跨课回顾。

五个页签：

1. **本课回顾**
   - 课程摘要：`abstract_content || abstract_text`；
   - 本课目标、知识点、易错点、例题：教育提取结果；
   - 每项带“查看原文”按钮。

2. **知识导图**
   - 用 JSON Tree/Mermaid 渲染，不做自由画布；
   - 节点颜色表示“课堂关系”，不能表示掌握；
   - 点击叶节点打开原文片段抽屉。

3. **逐字稿**
   - 按 `begin_time` 排序；
   - 显示时间、说话人、文本；
   - 支持关键词高亮和定位；
   - Demo 首版不做复杂多人声纹编辑。

4. **互动结果**
   - 展示该课程已发起的 TeleAgent 任务；
   - 展示复盘、导图、学习检测的完成状态；
   - 学习检测只显示回流后的题目、答案、解析、错题和状态变化；
   - 再次练习按钮继续发送到 TeleAgent，由 TeleAgent 承接后续交互。

5. **证据与关联**
   - 展示本课知识点引用的原文；
   - 展示跨课程找到的相似片段；
   - 显示向量召回相似度仅供参考，不直接写成“同一知识点”。

### 6.5 TeleAgent 学习任务

#### 平台可发起的任务

1. 复盘本课；
2. 生成思维导图；
3. 发起三题学习检测；
4. 查找跨课程相关讲解；
5. 根据当前状态生成十分钟学习建议。

#### 点击后的真实流程

```text
选择任务 → 平台准备课程范围与任务参数 → Bridge 接收教育任务
→ 展示端接收器创建/路由 TeleAgent 会话 → 置前 TeleAgent 窗口
→ TeleAgent 调用教育 Skill 与 MCP → 学生在 TeleAgent 中继续交互
→ 结构化结果受控回流平台 → 成长中心更新
```

现有 Bridge 和展示端接收器已具备事件转发、幂等任务、结果查询、TeleAgent 会话注入和窗口置前能力；比赛开发只泛化其当前固定的 PPT Prompt 与事件名称，不重写底层传输机制。

#### 学习检测边界

- 出题和答题过程均在 TeleAgent 中完成；
- P0 限单选、判断、数值填空；
- TeleAgent 每次只呈现一题或一组简短题目，并提供解释；
- 完成后由教育 Skill 调用受控结果回流能力，提交题目、用户答案、标准答案、正确性、解析、课程引用和幂等键；
- 平台验证结构后记录结果、错题和学习事件；
- 主观题可以讨论，但不进入自动掌握状态。

### 6.6 平台互动结果页

平台只展示已完成或进行中的 TeleAgent 任务：

- 发起时间、课程范围、任务类型、状态；
- Bridge 投递状态：准备中、已发送、TeleAgent 处理中、已完成、失败；
- 复盘、思维导图、跨课讲解或检测结果；
- 学习检测的题目、答案、解析、课程依据与状态变化；
- “再次发送到 TeleAgent”“回到课程”“查看成长变化”；
- 失败原因和重试。

---

## 7. 核心功能二：学习成长中心

### 7.1 功能定义

“学习成长中心”不是一份静态周报，也不是 AI 对学生贴标签。它是平台保存的、可追溯、可更正的学习状态账本，并把历史证据转换为下一步行动。“云续成长迹”只作为这一价值的品牌口号。

“成长迹”回答：

- 我学过什么；
- 我在哪次作答中暴露了问题；
- 哪个状态为什么发生变化；
- 哪些方法对我有效。

“云续”回答：

- 接下来最值得做什么；
- 为什么安排这项练习；
- 需要多久；
- 完成后验证了什么；
- 下一堂课如何继续。

### 7.2 页面整体布局

`/growth` 使用五个页签：**总览 / 知识掌握 / 成长轨迹 / 学习计划 / 学习档案**。阶段报告放在“学习档案”内，通过二级切换查看。

#### A. 总览

顶部不是总分，而是一句有证据的阶段判断：

> “本周你完成了 2 堂数学课程的复盘；‘平移方向判断’已从待巩固进入掌握中，‘负号处理’仍建议在下一次练习中复测。”

下方展示四个可验证指标：

- 已闭环课程数；
- 有效作答次数；
- 待巩固知识点数；
- 已完成续学项数。

主体采用“知识成长河流”：按时间从左至右放置课程节点，课程之间以相同知识点连线。点击知识点，右侧抽屉展示：

- 首次出现在哪堂课；
- 讲过几次；
- 做过哪些题；
- 最近状态变化；
- 当前计划；
- 所有原文和作答证据。

#### B. 知识掌握

按学科展示知识点状态，支持“知识地图/列表”切换。每个知识点显示当前等级、有效作答数、最近验证时间和下一步行动。点击后打开证据抽屉。

#### C. 成长轨迹

时间轴只展示真实事件，不直接展示 LLM 生成的空泛结论。事件卡类型：

- 课程已录入；
- 课程已复盘；
- 知识点已接触；
- 小测已完成；
- 错题已产生；
- 间隔重做通过；
- 掌握状态变化；
- 跨课关联被确认；
- 续学计划已完成；
- 用户更正/撤销。

状态变化卡必须同时显示“之前 → 现在”“触发证据”“计算规则版本”。点击可回到题目和课程原文。

#### D. 学习计划

使用“今天 / 接下来 / 已完成”三列任务板，每项计划包含：

- 行动：例如“重做 2 道平移方向判断题”；
- 原因：例如“昨天本课小测第 2 题答错”；
- 来源：课程、题目、知识点深链；
- 预计用时：3/5/10 分钟；
- 建议时间：立即、次日、3 日后、7 日后；
- 状态：AI 建议、已接受、进行中、完成、跳过、过期；
- 操作：接受、调整时间、开始、跳过并说明原因。

计划不是 AI 一次性写死。每次完成都会追加一条学习事件，再决定是否升级状态、延后复测或继续巩固。

#### E. 学习档案

回答“平台究竟记住了我什么”。按四类展示：

- 明确目标：如“本月完成二次函数基础复习”；
- 学习偏好：如“优先看原题再看解析”；
- 持续困难：必须由多次证据支持；
- 有效策略：必须经后续作答验证。

每条记忆展示内容、来源、证据数、首次发现、最近验证、状态和置信等级，并提供“更正、暂停使用、忘记”操作。页面内提供“学习记忆/阶段报告”二级切换。

### 7.3 掌握状态机

前端使用五档文本，不显示虚假精确百分比：

```text
已接触 → 待验证 → 待巩固 → 掌握中 → 较稳固
```

转换规则：

- 课程中出现知识点：只能进入“已接触/待验证”，不能判定掌握；
- 首次独立答错：进入“待巩固”；
- 看过解析后的立即重做正确：仍保持“待巩固”，只记录已纠正；
- 不同题、独立作答正确：可进入“掌握中”；
- 至少跨两次尝试且有间隔复测正确：可进入“较稳固”；
- 新错误可以降级；
- 有歧义题、被删除题或用户申诉成功：撤销该证据并重算。

内部可以保存 `score_internal` 便于 reducer 运算，但用户界面只显示等级、证据数量和更新时间。

### 7.4 “学习成长中心”的最小演示镜头

1. 演示前，“平移方向判断”为“待验证”；
2. 学生在本课小测中答错；
3. 结果页显示原文证据和跨课相似讲解；
4. 提交后时间轴新增“错题产生”和“状态变化”；
5. 右侧计划立即新增“今晚 5 分钟纠错”；
6. 学生完成一道不同题型的复测；
7. 状态由“待巩固”进入“掌握中”；
8. TeleAgent 再次询问时读取的是更新后的平台状态。

这段镜头比单独展示思维导图、摘要或报告更能体现产品差异。

---

## 8. 新增教育数据模型

所有教育表使用 `edu_` 前缀，复用同一个 MySQL 实例；不直接把教育字段塞进上游主表。字段为逻辑设计，开发时需形成单独幂等迁移文件。

### 8.1 用户与课程扩展

#### `edu_learner`

| 字段 | 说明 |
|---|---|
| `learner_id` BIGINT PK | 学生 ID |
| `phone` VARCHAR(32) INDEX | 与现有租户入口关联 |
| `display_name` VARCHAR(64) | 昵称，Demo 可用“小林” |
| `grade` VARCHAR(32) | 年级 |
| `created_at/updated_at` | 时间戳 |

P0 可固定一个 phone 一个 learner，但所有新接口保留 `learner_id`，避免未来家庭多学生时重做。

#### `edu_course_profile`

| 字段 | 说明 |
|---|---|
| `meeting_id` BIGINT PK | 逻辑关联 `user_meeting_info.id` |
| `phone` VARCHAR(32) INDEX | 冗余租户键，便于强制隔离 |
| `learner_id` BIGINT INDEX | 课程归属学生 |
| `subject`、`grade` | 学科、年级 |
| `course_scene` | school/after_school/family/community/tutoring/other |
| `source_device` | card/headset/watch/upload/text/demo |
| `import_mode` | audio/text/demo_fixture |
| `archive_status` | active/archived |
| `created_at/updated_at` | 时间戳 |

### 8.2 内容理解与生成物

#### `edu_knowledge_point`

`kp_id, subject, grade_scope, canonical_name, aliases_json, parent_id, status, created_at, updated_at`。

P0 不建设全量国家课程知识图谱，只维护 Demo 所需的 10—20 个知识点和父子关系。

#### `edu_course_knowledge`

`id, phone, learner_id, meeting_id, kp_id, relation_type, evidence_segment_ids_json, evidence_quote, source_fact_id, confidence_level, review_status, generator_version, created_at`。

- `relation_type`：explained/example/error_hint/homework；
- `review_status`：candidate/confirmed/rejected；
- `evidence_segment_ids_json` 必须引用 `user_meeting_content.id`。

#### `edu_artifact`

`artifact_id, phone, learner_id, meeting_id, kind, payload_json, source_refs_json, status, generator_version, content_hash, created_at, updated_at`。

`kind` 支持 `review/mindmap/quiz_draft/report`。同一课程和 kind 可保留版本，当前版本由状态标识，避免覆盖后无法解释旧题来源。

### 8.3 试卷、作答与错题

这些表用于保存 TeleAgent 中已经发生的学习检测及其回流结果，不对应平台内的独立答题页面。

#### `edu_quiz`

`quiz_id, phone, learner_id, meeting_id, purpose, title, status, artifact_id, published_at, created_at`。

#### `edu_question`

`question_id, quiz_id, type, stem, options_json, answer_key_json, grading_rule_json, explanation, source_refs_json, status, sort_order`。

标准答案只在服务端判分接口使用，未提交前不随普通试卷响应下发。

#### `edu_question_knowledge`

`question_id, kp_id, weight, relation_type`。一题可以关联多个知识点，P0 主知识点权重为 1。

#### `edu_attempt`

`attempt_id, phone, learner_id, quiz_id, status, started_at, submitted_at, idempotency_key UNIQUE, correct_count, question_count, grading_version`。

#### `edu_answer`

`answer_id, attempt_id, question_id, raw_answer_json, normalized_answer_json, correctness, feedback_json, answered_at`，并对 `(attempt_id, question_id)` 建唯一键。

#### `edu_wrong_case`

`wrong_case_id, phone, learner_id, kp_id, first_question_id, latest_question_id, status, ai_reason, user_reason, first_wrong_at, last_wrong_at, next_review_at, resolved_at`。

错题不是简单复制题目，而是对同一学生同一知识点错误轨迹的聚合入口；原始作答仍以 `edu_answer` 为准。

### 8.4 学习成长中心

#### `edu_learning_event`：不可变事件账本

`event_id, phone, learner_id, event_type, meeting_id, kp_id, object_type, object_id, payload_json, evidence_refs_json, occurred_at, idempotency_key UNIQUE, valid_flag, reversed_by_event_id, rule_version`。

业务事件只能追加，不原地改写。撤销通过反向事件和 `valid_flag` 完成，保证报告和状态可重算。

#### `edu_mastery_state`：事件派生快照

`learner_id, kp_id, level, score_internal, evidence_count, last_event_id, rule_version, calculated_at`，主键为 `(learner_id, kp_id)`。

它是可重算快照，不是不可变事实；权威依据是有效学习事件和作答。

#### `edu_memory_item`：教育领域可治理记忆

`memory_id, phone, learner_id, memory_type, content_json, evidence_refs_json, confidence_level, status, first_observed_at, last_verified_at, expires_at, created_by, updated_at`。

`status`：candidate/active/paused/forgotten/rejected。单次 AI 推断只能进入 candidate。

#### `edu_growth_plan_item`：续学行动

`plan_item_id, phone, learner_id, kp_id, action_type, title, reason_code, reason_text, evidence_refs_json, estimated_minutes, suggested_at, due_at, status, priority, source, completed_at, outcome_event_id, created_at, updated_at`。

`reason_code` 使用枚举，如 `WRONG_ANSWER/NEEDS_SPACED_REVIEW/GOAL/UPCOMING_COURSE/USER_REQUEST`，便于前端解释“为什么推荐”。

### 8.5 TeleAgent 运行与安全回流

#### `edu_agent_run`

`run_id, phone, learner_id, action, meeting_scope_json, skill_name, skill_version, request_json, response_json, source_refs_json, status, idempotency_key UNIQUE, created_at, finished_at, error_code`。

TeleAgent 生成内容先记录为 run 或 artifact 草稿，不能直接修改 `edu_mastery_state`。

### 8.6 P0 最少建表组合

若工期极紧，第一批只建以下 12 张：

1. `edu_learner`
2. `edu_course_profile`
3. `edu_knowledge_point`
4. `edu_course_knowledge`
5. `edu_artifact`
6. `edu_quiz`
7. `edu_question`
8. `edu_attempt`
9. `edu_answer`
10. `edu_learning_event`
11. `edu_mastery_state`
12. `edu_growth_plan_item`

`edu_wrong_case`、`edu_memory_item`、`edu_agent_run` 可在第二批补齐；第一批可由事件查询临时生成错题列表，但正式展示“我的学习记忆”前必须补 `edu_memory_item`。

---

## 9. 前端展示与数据库映射

| 前端组件 | 主查询/数据源 | 不可采用的做法 |
|---|---|---|
| 课程卡 | `user_meeting_info + recordings + ingest_jobs + edu_course_profile` | 仅凭前端计时假装 Ingest 完成 |
| 逐字稿时间轴 | `user_meeting_content` | 只显示 `content` 大文本而丢失片段引用 |
| 本课摘要 | `abstract_content/abstract_text` 或 `edu_artifact` | 覆盖原摘要且不保留版本 |
| 知识导图 | `edu_artifact.payload_json + edu_course_knowledge` | 用节点颜色冒充掌握度 |
| 试卷 | `edu_quiz + edu_question` | 在未提交响应中暴露 answer key |
| 判分结果 | `edu_attempt + edu_answer` | 让 LLM 自由判断客观题对错 |
| 错题轨迹 | `edu_answer + edu_wrong_case/learning_event` | 错一次即贴长期能力标签 |
| 成长时间轴 | `edu_learning_event` | 从当前快照倒推伪造历史 |
| 掌握地图 | `edu_mastery_state + learning_event` | 展示没有证据的精确百分比 |
| 续学计划 | `edu_growth_plan_item` | 生成一段建议文本后无法点击执行 |
| 我的学习记忆 | `edu_memory_item` | 把 TeleAgent 对话原文直接当教育事实 |

---

## 10. 接口清单

### 10.1 课程

- `GET /api/v1/courses`：分页、关键词、subject、status、date range；
- `POST /api/v1/courses/import-text`：适配模拟工具并写两张主表；
- `POST /api/v1/courses/import-demo`：载入固定样例并返回 import task；
- `GET /api/v1/courses/{courseId}`：课程主信息、教育属性、处理状态；
- `GET /api/v1/courses/{courseId}/transcript`：分段逐字稿；
- `GET /api/v1/courses/{courseId}/review`：摘要、知识点、易错点和证据；
- `POST /api/v1/courses/{courseId}/reingest`：重处理；
- `PATCH /api/v1/courses/{courseId}/profile`：教育属性；
- `DELETE /api/v1/courses/{courseId}`：受控软删除。

### 10.2 TeleAgent 学习任务与结果

- `POST /api/v1/teleagent/actions`：创建教育任务并投递 Bridge；
- `GET /api/v1/teleagent/actions/{runId}`：查询准备、投递、运行与完成状态；
- `POST /api/v1/teleagent/actions/{runId}/retry`：投递失败后重试；
- `POST /api/v1/teleagent/actions/{runId}/result`：教育 Skill 的受控结果回流；
- `GET /api/v1/teleagent/actions/{runId}/result`：平台查看回流结果、证据和状态变化。

`action` 只允许 `COURSE_REVIEW/MIND_MAP/LEARNING_CHECK/CROSS_COURSE_REVIEW/STUDY_PLAN`。服务端根据 action 选择内置 Prompt 模板，上游页面不能提交任意 Prompt。

### 10.3 学习成长中心

- `GET /api/v1/growth/overview`：阶段摘要、可验证指标、知识点状态；
- `GET /api/v1/growth/events`：时间轴分页；
- `GET /api/v1/growth/knowledge/{kpId}`：课程、作答、状态和计划证据；
- `GET /api/v1/growth/plans`：today/next/done；
- `PATCH /api/v1/growth/plans/{id}`：接受、改期、开始、完成、跳过；
- `GET /api/v1/growth/memories`：平台记住的内容；
- `PATCH /api/v1/growth/memories/{id}`：更正、暂停、忘记；
- `POST /api/v1/growth/recalculate`：管理员/开发环境重算状态。

### 10.4 比赛版身份范围

比赛版不建设登录鉴权接口。服务端使用固定 Demo 身份和现有 MCP Key 配置；所有 TeleAgent 任务和结果仍接受 `Idempotency-Key`，避免重复投递和重复记录。

---

## 11. MCP、Skill、TeleAgent 与平台职责

| 层 | 负责 | 不负责 |
|---|---|---|
| MySQL/Milvus | 原始课程、逐字稿、向量、教育事件和快照 | 组织自然语言交互 |
| MCP | 按 phone 读取课程、原文、摘要、跨课检索、教育状态 | 自由写入掌握状态 |
| 教育 Skill | 选择 MCP 工具、约束输出格式、组织复盘/出题/诊断流程 | 成为权威事实库 |
| TeleAgent | 自然交互、课程复盘、讲解、出题、答题与工具编排 | 独占学生长期教育状态 |
| 平台 AI | 结构化提取、受控出题、建议计划、报告生成 | 绕过证据直接贴标签 |
| 平台业务服务 | 验证 TeleAgent 回流结果、客观题规则复核、事件入账和状态 reducer | 替代 TeleAgent 的开放交互体验 |

为什么不能把长期 Memory 全交给 TeleAgent：TeleAgent 本身可以有持久化记忆，但学习掌握状态需要题目、作答、课程原文、规则版本、撤销记录和权限审计共同支撑。平台保存的是可重算的教育领域状态账本，TeleAgent 保存的是跨任务交互上下文；两者应协同而非互相否定。

### 11.1 受控回流规则

TeleAgent/Skill 只可提交：

- `CREATE_REVIEW_DRAFT`
- `CREATE_QUIZ_DRAFT`
- `CREATE_PLAN_SUGGESTION`
- `PROPOSE_MEMORY`

平台校验 schema、课程范围、来源片段、内容长度、Skill 版本和幂等键。复盘/检测结果保存为可追溯记录；Memory 保存为 candidate；掌握状态只能由 TeleAgent 中真实发生并成功回流的作答事件改变。

---

## 12. RAG、跨课程向量与 Memory 的用户可见场景

不要在演示中只说“我们用了向量数据库”。用户必须看到它解决了什么：

1. **错题找回原讲解**：答错后自动定位本课相关原文；
2. **跨课找相似讲解**：发现上周另一堂课讲过同类方向判断；
3. **发现重复薄弱点**：不同题目经结构化知识点确认后汇聚到同一成长轨迹；
4. **考前十分钟复习包**：按待巩固状态召回最相关的原讲解、错题和一道复测题；
5. **下一堂课前简报**：TeleAgent 读取近期课程、有效作答和未完成计划，生成简短提醒。

技术原则：MySQL 先按 `phone + learner + subject` 硬过滤，Milvus 做语义召回，结构化知识点/规则做确认，最终返回具体课程与片段。向量相似度不能直接升级或降级掌握状态。

---

## 13. P0、加分项与赛后范围

### 13.1 比赛 Demo 必做 P0

- 独立 Web 平台框架及三项主导航；
- 两张主表的课程列表和详情；
- 模拟上传/转写进度并真实写入主表；
- Ingest 状态展示和失败重试；
- 一门学科、两节相关课程；
- 本课回顾、简易知识导图、原文引用；
- 从平台点击后由 Bridge 唤起并置前 TeleAgent；
- 在 TeleAgent 中完成三道可交互客观题；
- 检测结果结构化回流平台并完成客观题规则复核；
- 一次错答写入学习事件并改变掌握状态；
- 学习成长中心总览、成长轨迹和学习计划；
- 一次跨课检索；
- TeleAgent 课程复盘、学习检测和跨课回顾联动；
- 固定 Demo 数据和现场降级方案。

### 13.2 加分项 P1

- 我的学习记忆完整治理；
- 错题间隔复测；
- 家长简版周报；
- 多录音终端入口视觉；
- 更多 TeleAgent 教育任务与更完整的结构化回流；
- 课程知识点人工确认；
- 原音频同步播放与逐字稿定位。

### 13.3 赛后再做 P2

- 全学科标准知识图谱；
- 复杂主观题自动评分；
- 教师/班级/校务系统；
- 真正的多硬件 SDK 与实时 ASR；
- 课程市场、支付、排课；
- 大规模推荐与模型训练平台。

---

## 14. 建议开发顺序

### D0：数据门禁

1. 备份测试库并对齐 007 phone 迁移；
2. 跑 MCP/Ingest 现有测试；
3. 固定两个脱敏数学课程样例；
4. 确认 `course_id = meeting_id = recording_id` 的字符串/整数转换规范。

### D1：课程底座

1. 初始化 Web；
2. 做课程列表、详情、逐字稿；
3. 接模拟录入工具；
4. 展示 Ingest 状态。

### D2：教育结构化与 TeleAgent 联动

1. 新增第一批 `edu_` 迁移；
2. 生成课程知识点和 artifact；
3. 将现有 Bridge 的固定 PPT 事件泛化为白名单教育任务；
4. 扩展教育 Skill，在 TeleAgent 内完成复盘、出题和答题；
5. 打通结构化结果回流并写学习事件。

### D3：学习成长中心

1. 实现 mastery reducer；
2. 时间轴；
3. 续学计划；
4. 知识点证据抽屉；
5. 状态重算与撤销测试。

### D4：演示稳定性

1. 复用 MCP 读能力并增加必要教育读工具；
2. 验证 Bridge 投递、窗口置前、任务查询和失败重试；
3. 固定演示数据、缓存生成结果、准备失败回退；
4. 录制 3—5 分钟视频。

---

## 15. 核心验收标准

### 15.1 数据与课程

- 模拟工具插入后，两张主表记录数量和逐字稿段数正确；
- 同一个 meeting_id 能贯穿主表、Ingest、MCP、教育表和前端 URL；
- Ingest 失败不影响查看源逐字稿。

### 15.2 TeleAgent 学习检测与回流

- 平台点击学习检测后，Bridge 能创建任务并置前 TeleAgent；
- 学生在 TeleAgent 中完成全部题目，平台不出现独立答题页；
- 回流结果包含题目、用户答案、标准答案、解析和课程引用；
- 同一 `Idempotency-Key` 重复回流不产生重复 answer/event/plan；
- 客观题正确性由平台按规则复核；
- 删除歧义题后能撤销其学习证据并重算。

### 15.3 学习成长中心

- 课程出现知识点不会直接显示“掌握”；
- 一次错答会产生可追溯事件、错题和续学项；
- 状态卡能打开原题、答案和课程原文；
- 完成复测后时间轴追加事件并更新快照；
- 用户可以跳过计划、纠正记忆、撤销错误证据；
- TeleAgent 重新查询时能读到平台更新后的状态。

### 15.4 比赛演示

- 5 分钟内不超过 8 个关键操作；
- 必须出现“一次错答 → 状态变化 → 计划变化 → 跨课关联 → 下一次服务”；
- 所有模型调用有超时、缓存或固定结果回退；
- 演示数据为脱敏/合成内容，并说明 ASR 为入口演示。

---

## 16. 风险与产品边界

| 风险 | 对策 |
|---|---|
| 被看成录音总结换皮 | 主镜头聚焦真实作答改变下一步计划 |
| “补课”叙事影响惠民表达 | 主场景用校内课堂/课后服务，产品不撮合培训 |
| 生成题有歧义 | P0 限客观题、来源约束、唯一答案校验、Demo 人工审核 |
| TeleAgent 与平台 Memory 重复 | 明确通用交互记忆与教育状态账本分工 |
| 源码与数据库迁移不一致 | D0 对齐 007 后才能开始教育表开发 |
| 向量相似被当成知识事实 | 向量只召回，结构化确认后才能形成关系 |
| 未成年人和课堂录音合规 | 脱敏 Demo、授权、最小采集、纯文本替代、可撤回删除 |
| 工期失控 | 单学生、单学科、两课程、三题、一次状态变化 |

---

## 17. 本版冻结决策

1. 工作名使用“智云课迹”。
2. “云续成长迹”只作为品牌口号；第二核心功能命名为“学习成长中心”，主导航简称“成长中心”。
3. 平台场景不局限一对一补课，优先表达校内课堂和普惠学习服务。
4. `user_meeting_info`、`user_meeting_content` 是课程源数据主表。
5. 现有模拟插入工具作为 Demo 课程入口原型。
6. MySQL 与 Milvus 基础设施复用，教育业务采用 `edu_` 表隔离。
7. MCP 以读取和检索为主，TeleAgent 的写回走平台白名单接口。
8. 首版开发以完整闭环为先，不以功能数量为目标。

需要产品方下一步确认的只有三项：前端技术栈、Demo 的两节课程文本、测试库执行迁移和新增 `edu_` 表的窗口。其余内容可以直接按本 PRD 进入技术设计。
