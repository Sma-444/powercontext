# records/qoder —— Qoder 开发记录归档

这个目录用来放**你在 Qoder 里真实做开发时**留下的证据。仓库里现在只有这份说明，
截图与录屏需要你在 Qoder 里做完后自己放进来（见 `docs/Qoder开发记录.md` 的清单）。

## 建议的文件命名

| 文件 | 内容 |
| --- | --- |
| `01-架构理解.png` | 让 Qoder 说明一次提问经过哪些函数，它的回答截图 |
| `02-docx.png` | 新增 `.docx` 支持的对话 + 代码 diff + pytest 结果 |
| `03-export.png` | `duban export` 命令的输出与导出的 Markdown |
| `04-filter.png` | 前端按文档过滤生效的截图（引用全部来自同一篇） |
| `05-fix.png` | 引用偏移缺陷的原因分析与修复后的测试 |
| `06-sites.png` | Qoder Sites 的发布界面 + 公开链接 + 无痕窗口访问 |
| `07-git-log.png` | `git log --oneline` 与 `git diff --stat` |
| `qoder-uid.txt` | Qoder 账号 UID（一行文本） |
| `demo.mp4`（可选） | 2–3 分钟录屏：提问 → 引用 → 标记 → 重启后仍在 |

## 提交前自查

- [ ] 截图里能看到提示词（不只是结果）
- [ ] 每张截图能对应到 `docs/Qoder开发记录.md` 的某个任务编号
- [ ] 至少保留一次「失败 → 修正」的对话
- [ ] `qoder-uid.txt` 已填
- [ ] 站点用无痕窗口打开过一次
