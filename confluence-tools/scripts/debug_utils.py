"""
调试日志自动清理工具

扫描 debug/ 目录，超过阈值时自动删除最旧的时间戳子目录。
供 md_import / math_upgrade 共用。
"""

import os
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
    """返回 debug_root 下所有子目录，按名称排序（时间戳格式 YYYYMMDD_HHMMSS）"""
    dirs = []
    if not os.path.isdir(debug_root):
        return dirs
    for name in os.listdir(debug_root):
        full = os.path.join(debug_root, name)
        if os.path.isdir(full):
            dirs.append(full)
    dirs.sort()  # 按名称升序 = 旧的在前
    return dirs


def cleanup_debug(debug_root: str = 'debug',
                  max_size_mb: int = 50,
                  keep_recent: int = 20):
    """清理调试目录：总大小超过 max_size_mb 则删除最旧的目录

    Args:
        debug_root:   调试根目录路径
        max_size_mb:  触发清理的阈值（MB）
        keep_recent:  至少保留最近 N 个子目录
    """
    if not os.path.isdir(debug_root):
        return

    total_mb = _get_dir_size_mb(debug_root)
    if total_mb <= max_size_mb:
        return  # 未超阈值，无需清理

    all_dirs = _get_timestamp_dirs(debug_root)
    if len(all_dirs) <= keep_recent:
        return  # 数量不足，不清理

    # 目标：保留最近 keep_recent 个
    dirs_to_delete = all_dirs[:-keep_recent]
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
