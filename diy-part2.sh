#!/bin/bash
#
# Copyright (c) 2019-2020 P3TERX <https://p3terx.com>
#
# This is free software, licensed under the MIT License.
# See /LICENSE for more information.
#
# https://github.com/P3TERX/Actions-OpenWrt
# File name: diy-part2.sh
# Description: OpenWrt DIY script part 2 (After Update feeds)

# FEEDS
grep "feeds.conf.default" "$GITHUB_WORKSPACE/diy-part1.sh" \
| sed "s/.*'\(.*\)'.*/\1/" \
| xargs -I{} sed -i "\|^{}$|d" feeds.conf.default

# ARGON
git clone https://github.com/jerrykuku/luci-theme-argon package/luci-theme-argon
git clone https://github.com/jerrykuku/luci-app-argon-config package/luci-app-argon-config

# V2RAY-GEODATA
find ./ | grep Makefile | grep v2ray-geodata | xargs rm -f
git clone https://github.com/sbwml/v2ray-geodata package/v2ray-geodata

# REPOSITORY INPUTS
python3 "$GITHUB_WORKSPACE/.github/scripts/repository-inputs.py" materialize --root "$PWD"

# BUILTDATE
version_id="${FIRMWARE_VERSION_ID:-$(date +%y.%m.%d)-${COMMIT_HASH}}"
sed -i "s/\(OPENWRT_RELEASE=\".*\)\"/\1 ${version_id}\"/" package/base-files/files/usr/lib/os-release
