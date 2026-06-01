# Actions-OpenWrt

Build OpenWrt using GitHub Actions

## Configuration

```
cd openwrt && make menuconfig
```
```
make defconfig && \
./scripts/diffconfig.sh > seed.config && \
cat seed.config
```

## LXC OpenWrt Upgrade

```
wget -O lxc.sh https://raw.githubusercontent.com/closur3/OpenWrt-Mainline/main/lxc.sh && \
chmod +x lxc.sh && bash lxc.sh
```

## Acknowledgments

- [Microsoft Azure](https://azure.microsoft.com)
- [GitHub Actions](https://github.com/features/actions)
- [OpenWrt](https://github.com/openwrt/openwrt)
- [Lean's OpenWrt](https://github.com/coolsnowwolf/lede)
- [ImmortalWrt](https://github.com/immortalwrt/immortalwrt)
- [CacheWrtBuild](https://github.com/stupidloud/cachewrtbuild)
- [tmate](https://github.com/tmate-io/tmate)
- [mxschmitt/action-tmate](https://github.com/mxschmitt/action-tmate)
- [csexton/debugger-action](https://github.com/csexton/debugger-action)
- [softprops/action-gh-release](https://github.com/softprops/action-gh-release)
- [Mattraks/delete-workflow-runs](https://github.com/Mattraks/delete-workflow-runs)
- [dev-drprasad/delete-older-releases](https://github.com/dev-drprasad/delete-older-releases)
- [peter-evans/repository-dispatch](https://github.com/peter-evans/repository-dispatch)

## License

[MIT](https://github.com/P3TERX/Actions-OpenWrt/blob/main/LICENSE) © P3TERX
