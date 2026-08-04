"""
调试日志自动清理工具

扫描 debug/ 目录，总大小或时间戳目录数超标时自动删除最旧的时间戳子目录
（大小/数量二选一即清理，至少保留最近 keep_recent 个）。
供 md_import / math_upgrade / md_export 共用。
"""

import os
import re
import shutil


def _get_dir_size_mb(dir_path: str) -> float:
    """递归计算目录总大小（MB）"""
    total = 0
    for root, dirs, files in os.walk(dir_path):
        for f in files:
            fp = os.path.join(root, f)
            if os.path.exists(fp):
                total += os.path.getsize(fp)
    return total / (1024 * 1024)


def _get_timestamp_dirs(debug_root: str) -> list:
    """返回 debug_root 下所有时间戳子目录（递归，名称匹配 YYYYMMDD_HHMMSS），按名称排序

    时间戳目录嵌套在功能子目录（import/ / upgrade/ / export/）之下，
    必须递归扫描才能真正统计到；功能子目录本身非时间戳格式，不会误入。
    """
    dirs = []
    if not os.path.isdir(debug_root):
        return dirs
    for root, subdirs, _files in os.walk(debug_root):
        for name in subdirs:
            if re.fullmatch(r'\d{8}_\d{6}', name):
                dirs.append(os.path.join(root, name))
    dirs.sort(key=lambda d: os.path.basename(d))  # 按时间戳名升序 = 旧的在前
    return dirs


def cleanup_debug(debug_root: str = 'debug',
                  max_size_mb: int = 50,
                  keep_recent: int = 20):
    """清理调试目录：总大小超过 max_size_mb **或** 子目录数超过 keep_recent 即清理

    触发条件为"二选一"（任一超标即清理）：
    - 从最旧的目录开始删，直到大小与数量都达标；
    - 下限保护：最多删到只剩最近 keep_recent 个（数量少于 keep_recent 时即使
      大小超标也不删，保证"至少保留最近 N 个"语义）。

    Args:
        debug_root:   调试根目录路径
        max_size_mb:  大小触发阈值（MB）
        keep_recent:  数量触发上限（子目录数超过即清理）；也是保留下限
    """
    if not os.path.isdir(debug_root):
        return

    all_dirs = _get_timestamp_dirs(debug_root)
    if not all_dirs:
        return

    total_mb = _get_dir_size_mb(debug_root)
    if total_mb <= max_size_mb and len(all_dirs) <= keep_recent:
        return  # 大小与数量都未超，无需清理

    # 从最旧开始删，直到大小与数量都达标，或已到保留下限（剩 keep_recent 个）
    dirs_to_delete = []
    remaining_mb = total_mb
    excess_count = len(all_dirs) - keep_recent  # 数量需删的最少个数（≤0 表示数量未超）
    max_deletable = len(all_dirs) - keep_recent  # 保留下限：最多删到剩 keep_recent 个
    for d in all_dirs:
        if excess_count <= 0 and remaining_mb <= max_size_mb:
            break  # 数量与大小都达标
        if len(dirs_to_delete) >= max_deletable:
            break  # 已到保留下限
        dirs_to_delete.append(d)
        remaining_mb -= _get_dir_size_mb(d)
        excess_count -= 1

    deleted = 0
    freed_mb = 0.0
    for d in dirs_to_delete:
        size_mb = _get_dir_size_mb(d)
        shutil.rmtree(d, ignore_errors=True)
        deleted += 1
        freed_mb += size_mb

    if deleted > 0:
        remaining_mb = _get_dir_size_mb(debug_root)
        print(f"🗑️  调试日志清理: 删除 {deleted} 个旧目录, "
              f"释放 {freed_mb:.1f}MB, 剩余 {remaining_mb:.1f}MB")
