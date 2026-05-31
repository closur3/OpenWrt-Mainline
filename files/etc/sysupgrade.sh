#!/bin/sh
set -eu

###############################################################################
# OpenWrt 一键升级脚本
# 位置: /etc/config/sysupgrade.sh (随固件分发)
# 用法: sysupgrade.sh [选项]
###############################################################################

SCRIPT_URL="https://raw.githubusercontent.com/closur3/OpenWrt-Mainline/main/files/etc/sysupgrade.sh"
DOWNLOAD_URL="https://github.com/closur3/OpenWrt-Mainline/releases/latest/download/openwrt-x86-64-generic-squashfs-combined.img.gz"

KEEP_CONFIG=1
DRY_RUN=0
UPDATE_ONLY=0
FORCE_UPGRADE=0
SCRIPT_ABS_PATH=""
GITHUB_REPO="closur3/OpenWrt-Mainline"

# ================= 基础函数 =================

log() {
    echo "[$(date +'%Y-%m-%d %H:%M:%S')] $*"
}

die() {
    log "错误: $*"
    exit 1
}

show_help() {
    cat << 'EOF'
OpenWrt 一键升级脚本

用法:
  sysupgrade.sh [选项]

选项:
  -n, --no-backup      升级时丢弃配置 (不备份)
  -k, --keep-config    升级后保留配置 (默认)
  -d, --dry-run        仅检查，不执行升级
  -u, --update         仅更新脚本本身，然后退出
  -f, --force          强制升级，跳过版本检查
  -h, --help           显示帮助
EOF
}

require_cmd() {
    command -v "$1" >/dev/null 2>&1 || die "缺少命令: $1"
}

# ================= 参数解析 =================

parse_args() {
    while [ $# -gt 0 ]; do
        case "$1" in
            -n|--no-backup)    KEEP_CONFIG=0 ;;
            -k|--keep-config)  KEEP_CONFIG=1 ;;
            -d|--dry-run)      DRY_RUN=1 ;;
            -u|--update)       UPDATE_ONLY=1 ;;
            -f|--force)        FORCE_UPGRADE=1 ;;
            -h|--help)         show_help; exit 0 ;;
            *)                 log "未知选项: $1"; show_help; exit 1 ;;
        esac
        shift
    done
}

# ================= 脚本自更新 =================

self_update() {
    if [ "$DRY_RUN" -eq 1 ] && [ "$UPDATE_ONLY" -ne 1 ]; then
        log "dry-run: 跳过脚本自更新"
        return 0
    fi

    log "检查脚本更新..."
    local temp_file="/tmp/sysupgrade_remote.sh"
    rm -f "$temp_file"

    if ! wget -q -T 10 -O "$temp_file" "$SCRIPT_URL"; then
        rm -f "$temp_file"
        if [ "$UPDATE_ONLY" -eq 1 ]; then
            die "下载更新脚本失败"
        fi
        log "检查更新失败，继续使用当前版本"
        return 0
    fi

    if ! grep -q "^#!/bin/sh" "$temp_file" 2>/dev/null && ! grep -q "^#!/bin/bash" "$temp_file" 2>/dev/null; then
        rm -f "$temp_file"
        log "下载的脚本验证失败，跳过更新"
        return 0
    fi

    if [ -f "$SCRIPT_ABS_PATH" ]; then
        local local_md5 remote_md5
        local_md5=$(md5sum "$SCRIPT_ABS_PATH" 2>/dev/null | awk '{print $1}' || echo "none")
        remote_md5=$(md5sum "$temp_file" 2>/dev/null | awk '{print $1}' || echo "none")
        if [ "$local_md5" = "$remote_md5" ]; then
            rm -f "$temp_file"
            log "已是最新版本"
            return 0
        fi
    fi

    log "发现新版本，正在更新..."
    cat "$temp_file" > "$SCRIPT_ABS_PATH"
    chmod +x "$SCRIPT_ABS_PATH"
    rm -f "$temp_file"
    log "更新完成，重启脚本..."
    exec "$SCRIPT_ABS_PATH" "$@"
}

# ================= 环境检查 =================

init_environment() {
    [ "$(id -u)" -eq 0 ] || die "请使用 root 权限运行"
    [ -f /etc/openwrt_release ] || die "未检测到 OpenWrt 系统"

    for cmd in wget sysupgrade md5sum; do
        require_cmd "$cmd"
    done

    log "OpenWrt 版本: $(cat /etc/openwrt_release | grep PRETTY_NAME | cut -d"'" -f2 || echo '未知')"
    log "内核版本: $(uname -r)"
}

# ================= 版本检查 =================

check_version() {
    if [ "$FORCE_UPGRADE" -eq 1 ]; then
        log "强制升级模式，跳过版本检查"
        return 0
    fi

    local local_release local_ver local_hash
    local_release=$(grep "^OPENWRT_RELEASE=" /etc/os-release 2>/dev/null | head -1 | cut -d'"' -f2)
    if [ -z "$local_release" ]; then
        log "无法读取本地版本信息，继续下载"
        return 0
    fi
    local_ver=$(echo "$local_release" | awk '{print $2}')
    local_hash=$(echo "$local_release" | awk '{print $NF}' | cut -d'-' -f2)

    log "本地版本: $local_ver  hash: $local_hash"

    local remote_body remote_hash
    remote_body=$(wget -q -T 10 -O - \
        "https://github.com/${GITHUB_REPO}/releases/latest/download/version.buildinfo" 2>/dev/null)
    if [ -z "$remote_body" ]; then
        log "获取远程版本信息失败，继续下载"
        return 0
    fi

    remote_hash=$(echo "$remote_body" | tail -1 | tr -d '[:space:]')

    if [ -z "$remote_hash" ]; then
        log "远程版本信息格式异常，继续下载"
        return 0
    fi

    log "远程 hash: $remote_hash"

    if [ "$local_hash" = "$remote_hash" ]; then
        log "已是最新版本，无需升级"
        return 1
    fi

    log "发现新版本 (hash: $local_hash -> $remote_hash)"
    return 0
}

# ================= 固件下载 =================

download_firmware() {
    local filename
    filename=$(basename "$DOWNLOAD_URL")
    local firmware_file="/tmp/${filename}"
    local temp_file="${firmware_file}.tmp"

    if [ "$DRY_RUN" -eq 1 ]; then
        log "dry-run: 跳过下载"
        return 0
    fi

    log "正在下载固件..."
    rm -f "$temp_file"
    if wget -q --tries=2 --timeout=30 -O "$temp_file" "$DOWNLOAD_URL"; then
        if gzip -t "$temp_file" 2>/dev/null; then
            mv -f "$temp_file" "$firmware_file"
            log "下载成功，固件校验通过"
            return 0
        fi
        rm -f "$temp_file"
        die "固件文件损坏"
    fi

    rm -f "$temp_file"
    die "固件下载失败"
}

# ================= 执行升级 =================

do_upgrade() {
    local filename
    filename=$(basename "$DOWNLOAD_URL")
    local firmware_file="/tmp/${filename}"
    local keep_arg=""

    [ "$KEEP_CONFIG" -eq 0 ] && keep_arg="-n"

    if [ "$DRY_RUN" -eq 1 ]; then
        log "dry-run: 将执行 sysupgrade $keep_arg $firmware_file"
        log "dry-run 检查完成，未执行实际升级"
        return 0
    fi

    log "开始升级系统..."
    log "  固件: $firmware_file"
    log "  保留配置: $([ "$KEEP_CONFIG" -eq 1 ] && echo '是' || echo '否')"
    echo ""
    echo "=========================================="
    echo "  系统即将重启并升级，请勿断电！"
    echo "=========================================="
    echo ""

    if [ -t 0 ] && [ -t 1 ]; then
        printf "确认执行升级？[y/N]: "
        read -r choice || choice="n"
        case "$choice" in
            y|Y) ;;
            *) log "已取消升级"; exit 0 ;;
        esac
    fi

    sysupgrade $keep_arg "$firmware_file"
}

# ================= 主流程 =================

main() {
    local script_dir script_name
    script_dir=$(cd "$(dirname "$0")" && pwd)
    script_name=$(basename "$0")
    SCRIPT_ABS_PATH="${script_dir}/${script_name}"

    parse_args "$@"

    self_update "$@"
    if [ "${UPDATE_ONLY:-0}" -eq 1 ]; then
        log "脚本自更新完成"
        exit 0
    fi

    init_environment

    if ! check_version; then
        exit 0
    fi

    download_firmware
    do_upgrade
}

main "$@"
