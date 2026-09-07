<div align="center">
    <h1>AutoCheckBJMF 班级魔方自动签到</h1>
    <img src="https://img.shields.io/github/license/JasonYANG170/AutoCheckBJMF?label=License&style=for-the-badge">
    <img src="https://img.shields.io/github/commit-activity/w/JasonYANG170/AutoCheckBJMF?style=for-the-badge">
<img src="https://img.shields.io/github/languages/count/JasonYANG170/AutoCheckBJMF?logo=python&style=for-the-badge">
	<br>
    	<a href="https://discord.com/invite/az3ceRmgVe"><img alt="Discord" src="https://img.shields.io/discord/978108215499816980?style=social&logo=discord&label=echosec"></a>
  <br>
<img src="https://github.com/JasonYANG170/AutoCheckBJMF/assets/39414350/7400a5d2-1031-4e31-b189-4cbfa2df51e6">
	
这是一项基于Python语言的班级魔方GPS自动签到Script

<br>

</div>

严禁将本程序用于违法用途，请遵守地区法规，另如有违背平台利益请与我联系撤销平台支持
## 支持平台
**Windows、Mac、Linux**
## 支持的签到模式  
- ✅ 二维码签到    （验证通过）
- ✅ GPS签到      （验证通过）
- ✅ GPS+拍照签到 （验证通过）
- 🚧 密码签到      

## 功能
- ✅ 支持定时开启签到
- ✅ 支持24小时无人值守
- ✅ 支持msi安装包一键式安装
- ✅ 支持自定义经纬度完成定位签到
- ✅ 支持循环检测GPS及扫码签到任务
- ✅ 支持自动导入data.json配置文件 
- ✅ 支持自动保存信息到data.json文件
- ✅ 支持连续签到，无需重复抓取Cookie值 


如遇问题，请向我提出issues

## 云端账号状态保护

- `cloud_check.py` 使用服务端成功卡片或独立的本人签到状态标签判断“已签到”；人数统计、否定句、隐藏标签和模板不算成功证据。
- 冷却只作用于对应账号，不会停止其他账号。记录按稳定账号标识的 SHA-256 摘要索引，不保存 Cookie 或令牌；变更账号顺序、续期 Cookie 不会绕过已有期限。
- 发现冷却后立即写入 `bjmf-cooldowns.json`，包括提交后复核阶段遇到的冷却。两份签到工作流在同一个并发锁下恢复/保存共享缓存，工作流失败也会执行保存步骤。
- 平台明确写出等待时长时，按该时长再加 1 分钟余量；未给出时长时，使用 `BJMF_COOLDOWN_BACKOFF_MINUTES`（默认 30 分钟）。这是脚本退避策略，不是平台解禁承诺。等待时不访问账号，也不会因每轮跳过而延长期限。
- 强制检查和直接签到链接也遵守账号冷却。期限届满后，在下一次原定检查时恢复访问；不会额外启动定时器。日志的 `cooldown_until_china` 给出最早重试时间，账号结果 `cooldown_wait` 表示本轮未访问平台，并不表示签到成功。
- 本地状态文件损坏时停止访问并报错。云端持久化依赖 GitHub Actions 缓存；首次部署、缓存被清除或不可用时无法恢复旧期限，必须关注缓存恢复/保存日志，不能把缓存当成平台状态数据库。首次部署不会凭空还原旧版未保存的冷却期限。
- 离线工作流使用独立的合成账号和缓存命名空间验证保存/恢复，不使用签到凭据或访问签到平台。

这两处修复不改变账号配置、班级、定位和原有检查时段，也不解决缺少有效静态码签到链接的问题。

## 使用教程
维基Wiki https://github.com/JasonYANG170/AutoCheckBJMF/wiki

## 自行打包
`pyinstaller main.spec`

## 喜欢这个项目，请为我点个Star ⭐ 

[![Star History Chart](https://api.star-history.com/svg?repos=JasonYANG170/AutoCheckBJMF&type=Date)](https://star-history.com/#star-history/star-history&Date)
