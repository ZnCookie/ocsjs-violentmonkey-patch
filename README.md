# OCS 网课助手 · 暴力猴兼容版

把 [ocsjs/ocsjs](https://github.com/ocsjs/ocsjs) 官方脚本移植到**暴力猴（Violentmonkey）**，业务逻辑零改动，改动只有 3 处：

1. 移除暴力猴不支持的 `@grant GM_getTab` / `@grant GM_saveTab`、`@antifeature`
2. 脚本顶部注入约 130 行兼容层，用 `GM_setValue` 模拟「标签页级」存储
3. 写入指向本仓库的 `@updateURL` / `@downloadURL`，安装后可自动更新

## 直接安装

**[点此安装](https://github.com/ZnCooie/ocsjs-violentmonkey-patch/releases/latest/download/ocs.violentmonkey.user.js)**

或下载本仓库的 `ocs.violentmonkey.user.js` 拖进浏览器窗口。安装前请卸载官方原版，避免两个悬浮窗同时出现。

## 文件说明

| 文件 | 用途 |
| --- | --- |
| `ocs.violentmonkey.user.js` | 成品，直接安装 |
| `.github/workflows/sync-upstream.yml` | 每 6 小时检查上游，自动打补丁并发 Release |
| `scripts/build_vm.py` | 构建脚本，带自检与幂等保护 |
| `scripts/vm-compat.js` | 兼容层源码（`GM_getTab` / `GM_saveTab`） |
| `patches/violentmonkey-support.patch` | 源码补丁，可打在 `5.0` 分支上自行构建 |
| `暴力猴移植说明.md` | 为什么原版跑不起来、改了什么、已知限制 |
| `自动更新与发布.md` | 工作流原理、固定更新链接选型、部署步骤 |

## 自行构建

```bash
python3 scripts/build_vm.py \
  --src upstream/ocs.user.js \
  --dst dist/ocs.violentmonkey.user.js \
  --repo ZnCooie/ocsjs-violentmonkey-patch
```

## 已知限制

只影响标签页级**临时数据**（面板页签、答题结果面板、章节计数），不影响配置与答案提交：

- **同时开多个网课标签页**时，跨域 iframe 可能串临时数据。单标签页使用无影响。
- 关闭标签页后 `__ocs_vm_tab_data__*` 不会自动清理，长期可手动清理。
- 面板里「显示 Tab 存储」按钮无效（调试功能）。

详见 [暴力猴移植说明.md](./暴力猴移植说明.md)。

## 许可

原始脚本版权归原作者 [enncy](https://github.com/ocsjs/ocsjs) 所有，遵循 MIT License。
本仓库为**非官方修改版**，同样以 MIT License 分发，保留原始版权声明。
