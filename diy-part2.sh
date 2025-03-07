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

#
#sed -i 's/192.168.1.1/10.0.0.2/g' package/base-files/files/bin/config_generate

# FEEDS
sed -i '/small-package/d' feeds.conf.default

# GOLANG
rm -rf feeds/packages/lang/golang
git clone https://github.com/sbwml/packages_lang_golang feeds/packages/lang/golang

# MOSDNS
find ./ | grep Makefile | grep mosdns | xargs rm -f
find ./ | grep Makefile | grep v2ray-geodata | xargs rm -f
git clone https://github.com/sbwml/luci-app-mosdns package/mosdns
git clone https://github.com/sbwml/v2ray-geodata package/v2ray-geodata

# BUILTDATE
sed -i "s/\(OPENWRT_RELEASE=\".*\)\"/\1 built-$(date +%y.%m.%d)\"/" package/base-files/files/usr/lib/os-release
