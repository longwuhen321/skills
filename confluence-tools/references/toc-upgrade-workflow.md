# 目录宏双向转换流程

## 强制读取条件

执行 `toc_upgrade.py` 的单页、完整页面树、空间转换或 `--confirm` 前，必须完整读取本文件。
读取后先向用户说明：“已读取 `references/toc-upgrade-workflow.md`，将按目录宏冲突、
范围和过期确认保护规则执行。”

## 命令入口

```bash
"<python_path>" -X utf8 "<SKILL_DIR>/scripts/toc_upgrade.py" --page-id <ID> --no-recursive [--target easy_heading|toc]
"<python_path>" -X utf8 "<SKILL_DIR>/scripts/toc_upgrade.py" --page-id <ID> --recursive [--target easy_heading|toc]
"<python_path>" -X utf8 "<SKILL_DIR>/scripts/toc_upgrade.py" --space <KEY> [--target easy_heading|toc]
"<python_path>" -X utf8 "<SKILL_DIR>/scripts/toc_upgrade.py" --confirm <debug目录|latest>
```

## 范围与配置

- `--page-id --no-recursive`：只处理指定页面。
- `--page-id --recursive`：处理根页面及全部后代，不提供最大层级限制。
- `--space`：处理空间内所有页面，每个 page ID 只处理一次。
- 默认目标来自导入与升级共用的 `common_config.toc_target_macro`；
  `--target easy_heading|toc` 仅覆盖本次目录升级。
- `--no-auto-update`、`--ai-verify`、`--confirm` 和 `--stop-on-error` 的提交保护
  与数学升级一致；确认时必须复查源版本和源正文 SHA256。

## 页面转换矩阵

| 页面状态 | 目标 `easy_heading` | 目标 `toc` |
|---|---|---|
| 只有一个 `toc` | 在原位置替换为新 Easy 宏 | 不修改 |
| 只有一个 Easy | 不修改，保留全部原参数 | 在原位置替换为新 `toc` |
| 两类各一个 | 删除 `toc`，保留原 Easy | 删除 Easy，保留原 `toc` |
| 两类都没有 | 跳过，不注入 | 跳过，不注入 |
| 任一类型超过一个 | 拒绝修改该页面 | 拒绝修改该页面 |

## Easy Heading 规则

- 插件版本目标为 Easy Heading Macro 3.6.3，固定宏名 `easy-heading-free`、schema `1`。
- 新建 Easy 宏生成新的 UUID，不复制参考页的 `macro-id`。
- 创建参数来自严格校验的 `toc_upgrade_config.macro_parameters`，导入新建 Easy Heading
  时也使用同一组参数；未知键、非法枚举、
  非字符串或非法布尔值在写入前失败。
- 页面已有 Easy 宏时保持其原始文本和参数，不用配置覆盖。
- 转换只替换或删除目标宏的原始 storage 跨度，不重序列化整个页面；
  CDATA 和注释里的宏样本文本不计数。

## 验证和提交

- 写入前检查 XHTML 配对以及转换后的 `toc` / Easy 宏数量。
- 无变化不生成 PUT，不增加页面版本。
- debug 保存 before、after、源版本、源 SHA256、after SHA256、目标和参数。
- `--confirm` 重新验证 after 哈希、XHTML、目标宏数量和当前源页面；任一变化即拒绝。
- 批量页面存在歧义时默认继续其他页面，最终汇总失败并返回非零；
  `--stop-on-error` 可立即停止。
- 真实验证仅创建唯一命名测试页，记录精确 ID；完成后只删除这些 ID。
