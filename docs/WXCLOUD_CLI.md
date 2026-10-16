# 用 wxcloud 命令行部署到微信云托管

目的：以后部署不用在网页控制台手动上传压缩包，改成“提交代码 → 一条命令部署”。
Claude 可以替你运行命令，但**登录和私钥要你自己输入**。

> 状态说明：标“已确认”的内容，是我在命令行 `--help` 里看到的，或在本项目里实际跑通的；
> 标“未确认”的内容还没有验证，第一次用时要留意。

## 0. 一次性准备

1. 安装（已装过，版本 `@wxcloud/cli 1.1.8`，已确认）：
   ```
   npm install -g @wxcloud/cli
   wxcloud help
   ```
2. 在小程序后台生成“微信云服务私钥”（未确认菜单位置，可能在 开发管理 → 开发设置 一带；
   找不到就把你看到的菜单发给 Claude）。
3. 登录。**私钥是密钥，不要发进聊天，也不要写进文件或提交到 git。**
   在 Claude Code 的输入框里用 `!` 前缀自己运行，输出会直接显示在会话里：
   ```
   ! wxcloud login -a wx607ed45f29b150d5 -k <私钥>
   ```
   （`wx607ed45f29b150d5` 是本项目的 AppID。登录是否要设 IP 白名单：未确认。）

## 1. 先看一眼，确认连得上（只读，安全）

```
wxcloud env:list
wxcloud service:list -e <环境ID>
wxcloud version:list -e <环境ID> -s book-translator
```
- 本项目：环境 ID 是 `book-translator-d8fiwkctd17eb186`，服务名 `book-translator`。
- 地域默认是上海 `ap-shanghai`；如果列表是空的，加 `--region=ap-guangzhou` 等试试。
- 加 `--json` 可以输出便于 Claude 读取的格式。

## 2. 发布前检查

1. 测试通过：`.venv/bin/python -m pytest -q`
2. 代码已提交：`git status` 应该是干净的。
3. 仓库根目录有 `Dockerfile`，容器监听 8000 端口，有 `/healthz` 接口。
4. 准备好**完整**的环境变量清单（见第 3 步）。

## 3. 部署（会让新版本上线，务必先确认）

```
wxcloud run:deploy . \
  -e book-translator-d8fiwkctd17eb186 \
  -s book-translator \
  --containerPort 8000 \
  --dockerfile Dockerfile \
  --remark "说明这次改了什么" \
  --envParams "BOOKTRANS_SECRET=<密钥>&BOOKTRANS_WORKERS=1&BOOKTRANS_TRUST_WX_HEADERS=1&WX_CLOUD_ENV=book-translator-d8fiwkctd17eb186"
```

要点：
- `--envParams` 的格式是 `名称=值&名称=值`（已确认），说明里写着“同步到服务设置”。
- **它很可能会替换原有的全部环境变量**（未确认）。所以每次都要把完整清单带上，尤其是
  `BOOKTRANS_SECRET`；或者加 `--override`，让没写的参数沿用旧版本配置。第一次用后，
  到网页 服务设置 → 环境变量 核对一遍。
- 密钥里的 `&`、`=` 会被当成分隔符；用 `openssl rand -hex 32` 生成的密钥是安全的。
- 不要用 `--noConfirm`，让命令在发布前停下来等你确认。
- `--releaseType=GRAY` 是灰度发布；想先小范围试，可以用它。
- 部署日志会实时显示；`--detach` 则不显示日志直接返回。

## 4. 部署后验证

1. `wxcloud version:list -e <环境ID> -s book-translator`，新版本应该出现在列表里。
2. 看服务是否正常（网页 部署发布 页面显示“服务正常”，或看 运行日志）。
3. 在微信开发者工具的 Console 里测连通（一行）：
   ```js
   wx.cloud.init(); wx.cloud.callContainer({config:{env:'book-translator-d8fiwkctd17eb186'},path:'/healthz',method:'GET',header:{'X-WX-SERVICE':'book-translator'}}).then(console.log).catch(console.error)
   ```
   期望 `statusCode: 200` 和 `data: {ok: true}`。
4. 在手机上预览，跑一个 3 页的试译。

## 5. 出问题时回退

```
wxcloud run:rollback
```
（具体参数：先运行 `wxcloud run:rollback --help` 看，我还没有看过。）
也可以在网页 部署发布 页面点“回退”。

## 6. 仍然要在网页上做的事（命令行里没有看到对应命令）

| 事项 | 位置 | 本项目现状 |
| --- | --- | --- |
| 云调用白名单：`http://api.weixin.qq.com/tcb/uploadfile`、`/tcb/batchdownloadfile`、`/tcb/batchdeletefile` | 云托管控制台 → 服务管理 → 云调用 → 微信令牌 | 已加好，不用重复 |
| 关闭服务的公网访问（信任 `x-wx-openid` 的前提） | 服务设置 | 需要确认已关闭 |
| 云存储权限设为“所有用户可读，仅创建者可写” | 云存储权限设置 | 已设置 |
| 体验版、提交审核、发布小程序 | 小程序后台 管理 → 版本管理；DevTools 的“上传” | 发布前再做 |

## 7. 其他有用的命令

- `wxcloud service:create -e <环境ID> -s <服务名> [--isPublic]`：创建服务（`--isPublic` 是开通外网访问；
  我们要保持关闭）。
- `wxcloud storage:upload <目录> -e <环境ID> -r <远程目录>`：上传文件到对象存储。
- `wxcloud logout`：退出登录。

## 8. 没有命令行时的备用做法（网页）

1. `git archive --format=zip -o ~/Desktop/book-translator.zip HEAD`
2. 网页：部署发布 → 发布 → 手动上传代码包 → 选压缩包 → 端口 8000。
3. 环境变量在 服务设置 里改。

## 9. 安全提醒

- 私钥、`BOOKTRANS_SECRET`、API 密钥都不要提交到 git，不要发截图（截图里的密钥要换掉）。
- 每次部署前让 Claude 把完整命令列出来，你确认后再运行。
- `BOOKTRANS_SECRET` 要换成新的（`openssl rand -hex 32`），旧的出现在过截图里。
