# 智云课迹教育 MCP 契约

MCP Server：`zhiyun-learning`，默认端口 `8768`。

## 课程与记忆工具

- `list_courses()`
- `get_course_summary(course_id)`
- `get_course_transcript(course_id)`
- `search_course_content(query, top_k, course_id)`
- `find_related_courses(query, top_k)`
- `get_learning_context(query, top_k)`

所有工具按 MCP Key 映射的 phone 隔离，不能使用对话中自报的 phone 绕过隔离。

## complete_learning_interaction

```json
{
  "run_id": "zyk_...",
  "course_id": "12345",
  "action": "course_review",
  "summary": "学生围绕函数平移提出问题，经坐标代入提示后完成自我纠正。",
  "dialogue_turns": [
    {"role": "student", "content": "x-2 为什么不是向左？"},
    {"role": "teleagent", "content": "先取图像上的一个点，代入后横坐标怎样变化？"},
    {"role": "student", "content": "我明白了，是向右移动。我刚才把符号直接当方向了。"}
  ],
  "key_claims": [
    {"knowledge_point": "函数图像平移", "claim": "提示后能使用坐标关系自我纠正"}
  ],
  "artifacts": []
}
```

平台保存原始对话，结合课程原文提炼问题、知识点、误区、提示依赖、自我纠正和待验证项，
再生成长期记忆候选。TeleAgent 不直接提交“已掌握”、人格或能力百分比。
