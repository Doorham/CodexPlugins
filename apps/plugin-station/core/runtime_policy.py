"""Validate public install destinations before opening any source or state file."""
from pathlib import Path
from .tool_paths import TOOL_DATA_ROOT, USER_DATA_ROOT, expand_tool_path


def protected_paths(plugin: dict) -> list[Path]:
    paths = list(plugin.get('localDataPolicy', {}).get('paths', []))
    paths += list(plugin.get('customDataPolicy', {}).get('paths', []))
    paths += [plugin[key] for key in ('stateFolder', 'statusFile') if plugin.get(key)]
    return [expand_tool_path(value).resolve() for value in paths]


def overlaps(path: Path, protected: list[Path]) -> bool:
    path = path.resolve()
    return any(path == root or path.is_relative_to(root) for root in protected)


def validate_install_targets(plugin: dict, repo: Path) -> None:
    targets = [expand_tool_path(plugin.get('executable', ''))] if plugin.get('installSource') or plugin.get('bundle') else []
    for support in plugin.get('supportFiles', []):
        source = (repo / support['source']).resolve()
        if not source.is_relative_to(repo.resolve()) or '.runtime' in {part.casefold() for part in source.relative_to(repo.resolve()).parts} or ('artifacts' in source.relative_to(repo.resolve()).parts and not (source.parent == (repo / 'artifacts/helpers').resolve() and source.suffix.casefold() in {'.exe', '.dll'})):
            raise ValueError('支持文件只能来自版本化公共源码')
        targets.append(expand_tool_path(support['target']))
    protected = protected_paths(plugin)
    for target in targets:
        install_root = (repo / '.runtime/CompanyAIHelpers').resolve()
        if overlaps(target, protected) or target.resolve().is_relative_to(install_root / 'Users'):
            raise ValueError('公共安装文件与个人状态重叠，未进行复制')
        if not target.resolve().is_relative_to((repo / '.runtime/CompanyAIHelpers').resolve()):
            raise ValueError('公共安装目标必须位于工具箱程序目录')
