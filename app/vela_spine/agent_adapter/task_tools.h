/* 官方 ai_agent 的三个业务工具（只读查询 / 提交计划 / 请求停止）。
 *
 * 边界：工具只接受 name + JSON 参数，不接受 shell、文件路径、速度或任意 URL。
 * 参数校验由板端账本（native/task.c）完成，这里只做外层形状检查与结果封装，
 * 保证模型拿到的是“工具执行结果”而不是解释文本。
 */
#ifndef SP_TASK_TOOLS_H
#define SP_TASK_TOOLS_H

const char *sp_task_tool_prompt(void);
int sp_task_tool_call(const char *root,const char *endpoint,const char *name,
                      const char *args_json,char **reply);

#endif
