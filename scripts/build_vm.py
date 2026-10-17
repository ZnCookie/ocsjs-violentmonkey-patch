#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
OCS 网课助手 → 暴力猴（Violentmonkey）版本构建脚本

用法：
    python3 scripts/build_vm.py --src upstream/ocs.user.js --dst dist/ocs.violentmonkey.user.js

对上游产物的改动只有三处：
    1. 元数据：删除 @grant GM_getTab / @grant GM_saveTab / @antifeature，名称加后缀
    2. 脚本顶部注入 scripts/vm-compat.js（GM_getTab / GM_saveTab 兼容层）
    3. 可选写入 @updateURL / @downloadURL，让暴力猴能自动更新

上游若调整元数据的空白或顺序，脚本用正则匹配，不会因此失败。
任何一步不符合预期都以非 0 退出，便于 CI 立刻发现上游结构变更。
"""
import argparse
import io
import json
import os
import re
import subprocess
import sys

HEADER_START = '// ==UserScript=='
HEADER_END = '// ==/UserScript=='
PATCH_MARK = '[Violentmonkey Patch]'

# 暴力猴原生支持（或本兼容层已覆盖）的 API，用于上游变更体检
VM_SUPPORTED = {
    'GM_info', 'GM_getValue', 'GM_setValue', 'GM_deleteValue', 'GM_listValues',
    'GM_addValueChangeListener', 'GM_removeValueChangeListener',
    'GM_xmlhttpRequest', 'GM_notification', 'GM_getResourceText', 'GM_getResourceURL',
    'GM_addStyle', 'GM_openInTab', 'GM_setClipboard', 'GM_registerMenuCommand',
    'GM_unregisterMenuCommand', 'GM_download', 'GM_addElement', 'GM_cookie',
    'unsafeWindow',
    # 以下两个暴力猴没有，由兼容层提供
    'GM_getTab', 'GM_saveTab',
}


def die(msg):
    print('::error::' + msg, file=sys.stderr)
    print('构建失败：' + msg, file=sys.stderr)
    sys.exit(1)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--src', required=True, help='上游 ocs.user.js 路径')
    ap.add_argument('--dst', required=True, help='输出路径')
    ap.add_argument('--compat', default=None, help='兼容层源码，默认与本脚本同级 vm-compat.js')
    ap.add_argument('--name-suffix', default='（暴力猴兼容版）')
    ap.add_argument('--repo', default='', help='OWNER/NAME，自动生成固定更新链接')
    ap.add_argument('--cdn', default='release', choices=['release', 'jsdelivr'],
                    help='链接类型：release=GitHub Release（默认），jsdelivr=CDN')
    ap.add_argument('--cdn-branch', default='main', help='jsdelivr 模式下产物所在分支')
    ap.add_argument('--update-url', default='')
    ap.add_argument('--download-url', default='')
    ap.add_argument('--expect-version', default='', help='校验上游脚本 @version 是否匹配')
    ap.add_argument('--allow-missing-compat', action='store_true',
                    help='上游已原生支持时允许跳过兼容层注入')
    args = ap.parse_args()

    # 根据 --repo 自动生成固定链接（--update-url / --download-url 显式传入时优先）
    if args.repo:
        repo = args.repo.strip().strip('/')
        if repo.count('/') != 1:
            die('--repo 格式应为 OWNER/NAME，收到：' + repo)
        name = os.path.basename(args.dst) if args.dst else 'ocs.violentmonkey.user.js'
        if args.cdn == 'jsdelivr':
            url = 'https://cdn.jsdelivr.net/gh/%s@%s/dist/%s' % (repo, args.cdn_branch, name)
        else:
            url = 'https://github.com/%s/releases/latest/download/%s' % (repo, name)
        args.update_url = args.update_url or url
        args.download_url = args.download_url or url

    if not os.path.isfile(args.src):
        die('找不到上游脚本：' + args.src)
    src = io.open(args.src, encoding='utf-8').read()

    if not src.lstrip().startswith(HEADER_START):
        die('上游文件不是用户脚本（缺少 ==UserScript== 头），可能下载到了错误页面')
    if HEADER_END not in src:
        die('上游脚本缺少 ==/UserScript== 结束标记')

    head_end = src.index(HEADER_END) + len(HEADER_END)
    compat = ''
    header, body = src[:head_end], src[head_end:]

    # ---------- 校验版本 ----------
    m = re.search(r'^//\s*@version\s+(\S+)', header, re.M)
    if not m:
        die('上游脚本缺少 @version')
    version = m.group(1)
    if args.expect_version and version != args.expect_version:
        die('版本不一致：期望 %s，实际 %s' % (args.expect_version, version))

    # ---------- 1. 元数据 ----------
    before = header
    # 删除暴力猴不支持的 @grant（正则容忍空白/制表符差异）
    header = re.sub(r'^//\s*@grant\s+GM_(?:getTab|saveTab)\s*\r?\n', '', header, flags=re.M)
    # 删除暴力猴不认识的 @antifeature
    header = re.sub(r'^//\s*@antifeature\s+.*\r?\n', '', header, flags=re.M)

    # 名称追加后缀（幂等）
    if args.name_suffix and args.name_suffix not in header:
        header = re.sub(r'^(//\s*@name\s+)(.+?)\s*$',
                        lambda mm: mm.group(1) + mm.group(2) + args.name_suffix,
                        header, count=1, flags=re.M)

    # 更新地址（先清后加，保证幂等；未传入则保留原值）
    if args.update_url:
        header = re.sub(r'^//\s*@updateURL\s+.*\r?\n', '', header, flags=re.M)
    if args.download_url:
        header = re.sub(r'^//\s*@downloadURL\s+.*\r?\n', '', header, flags=re.M)
    extra = ''
    if args.update_url:
        extra += '// @updateURL   \t\t\t\t' + args.update_url + '\n'
    if args.download_url:
        extra += '// @downloadURL \t\t\t\t' + args.download_url + '\n'
    if extra:
        header = header.replace(HEADER_END, extra + HEADER_END)

    # ---------- 2. 兼容层 ----------
    if PATCH_MARK in src:
        print('检测到兼容层已存在，跳过注入')
    else:
        compat_path = args.compat or os.path.join(os.path.dirname(os.path.abspath(__file__)), 'vm-compat.js')
        if not os.path.isfile(compat_path):
            if args.allow_missing_compat:
                print('::warning::未找到兼容层 %s，跳过注入' % compat_path)
                compat = ''
            else:
                die('找不到兼容层文件：' + compat_path)
        else:
            compat = io.open(compat_path, encoding='utf-8').read().strip() + '\n\n'
        if compat:
            header = header + '\n' + compat

    out = header + body

    # ---------- 3. 自检 ----------
    problems = []
    meta = out[:out.index(HEADER_END)]
    if re.search(r'^//\s*@grant\s+GM_(getTab|saveTab)\s*$', meta, re.M):
        problems.append('元数据仍残留 GM_getTab / GM_saveTab 的 @grant')
    if PATCH_MARK not in out:
        problems.append('兼容层未写入')
    if not re.search(r'^//\s*@version\s+' + re.escape(version) + r'\s*$', meta, re.M):
        problems.append('@version 被破坏')
    if args.update_url and '@updateURL' not in meta:
        problems.append('@updateURL 未写入')
    if len(out.encode('utf-8')) < 300 * 1024:
        problems.append('产物体积异常（%.1f KB），疑似上游内容不完整' % (len(out.encode('utf-8')) / 1024))
    if problems:
        die('；'.join(problems))

    # 上游 API 体检：元数据里出现兼容层未覆盖的 grant 时给出告警
    grants = set(re.findall(r'^//\s*@grant\s+(\S+)', meta, re.M))
    unknown = sorted(grants - VM_SUPPORTED)
    if unknown:
        print('::warning::上游使用了未经验证的 API：' + ', '.join(unknown))

    # 语法检查（有 node 时执行）
    os.makedirs(os.path.dirname(os.path.abspath(args.dst)) or '.', exist_ok=True)
    tmp = args.dst + '.syntax.js'
    io.open(tmp, 'w', encoding='utf-8').write(out)
    try:
        r = subprocess.run(['node', '--check', tmp], capture_output=True, text=True)
        if r.returncode != 0:
            die('产物语法检查失败：' + (r.stderr or '').strip()[:500])
    except FileNotFoundError:
        print('未安装 node，跳过语法检查')
    finally:
        if os.path.exists(tmp):
            os.remove(tmp)

    io.open(args.dst, 'w', encoding='utf-8').write(out)

    size = len(out.encode('utf-8')) / 1024
    print('上游版本 : %s' % version)
    print('输出文件 : %s (%.1f KB)' % (args.dst, size))
    removed = len(re.findall(r'^//\s*@(?:grant\s+GM_(?:getTab|saveTab)|antifeature)\s',
                             before, re.M))
    print('元数据改动: 移除 %d 项冗余声明，注入兼容层 %d 字符' % (removed, len(compat)))
    print('grant 列表: ' + ', '.join(sorted(grants)))

    summary = os.environ.get('GITHUB_STEP_SUMMARY')
    if summary:
        with io.open(summary, 'a', encoding='utf-8') as f:
            f.write('### 构建结果\n\n')
            f.write('| 项目 | 值 |\n| --- | --- |\n')
            f.write('| 上游版本 | `%s` |\n' % version)
            f.write('| 产物大小 | %.1f KB |\n' % size)
            f.write('| 语法检查 | 通过 |\n')
            f.write('| grant | %s |\n' % ', '.join('`%s`' % g for g in sorted(grants)))
            if unknown:
                f.write('\n> ⚠️ 上游新增了未经验证的 API：%s，请人工确认暴力猴是否支持。\n'
                        % ', '.join('`%s`' % u for u in unknown))
    return 0


if __name__ == '__main__':
    sys.exit(main())
