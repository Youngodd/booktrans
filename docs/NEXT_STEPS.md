# Next steps: from local test to a live WeChat mini program

Status: the mini program (`miniprogram/`) and the server work locally in WeChat DevTools.
The remaining work is to put the server online and release. Release needs the Cloud Hosting
route (微信云托管), which avoids owning a domain. Some Cloud Hosting details are unverified
(see "Open questions"), so the order below is: set up the environment first, test, then build.

Wording of menu names may differ slightly from the current console; follow what you see.

---

## Step 1. Make sure the mini program account is ready

1. Log in at https://mp.weixin.qq.com with your mini program account.
2. Check **Settings -> Basic settings**: your AppID is shown there (yours is already in
   `miniprogram/project.config.json`).
3. Finish any real-name verification the console asks for. Without it you can't release.
4. Open **Settings -> Basic settings -> Service categories** and add a category that fits
   (a "Tools" category is the closest). Some categories need a business license; the console
   tells you which. Pick one your account type allows.

## Step 2. Create the Cloud Hosting environment

1. In the console, open **Development -> Cloud Development (云开发)** or **Cloud Hosting
   (微信云托管)** and activate it. You may be asked to link a Tencent Cloud account (it can be
   created with the same WeChat) and to agree to the terms.
2. Create an **environment** and write down its **environment ID**
   (looks like `prod-xxxxxxxx`).
3. Check the pricing page. Cloud Hosting usually has a free trial and then per-use billing
   (CPU, memory, traffic). Set a budget alert if the console offers one.
4. Create a **service** (服务) and write down its **service name**.

Send me the environment ID and service name when you have them (they are not secrets).

## Step 3. Deploy this repo's container as a test

The repo already has a `Dockerfile`.

1. In the Cloud Hosting console, open your service and create a new **version** from code:
   upload the repo (or connect the GitHub repo), and choose the `Dockerfile`.
2. Container port: `8000`. Start command: the Dockerfile default.
3. Memory: at least 2 GB (a translation job can use 1-2 GB). Use 1 worker
   (`BOOKTRANS_WORKERS=1`) on a small instance.
4. Set these environment variables in the console (see `.env.example`):
   - `BOOKTRANS_SECRET`: a long random string
   - `SMTP_HOST`, `SMTP_PORT`, `SMTP_USER`, `SMTP_PASSWORD`, `SMTP_FROM`: only if you want
     email delivery (a QQ or 163 mailbox with an SMTP authorization code works)
5. Wait for the build to finish and for the version to show as running.
6. Open the service's health check path `/healthz`. You should see `{"ok": true}`.

## Step 4. Test the connection from the mini program

Before I change the app, check that the mini program can reach the container:

1. In DevTools, open the console panel and run:
   ```js
   wx.cloud.init()
   wx.cloud.callContainer({
     config: { env: 'YOUR_ENV_ID' },
     path: '/healthz',
     method: 'GET',
     header: { 'X-WX-SERVICE': 'YOUR_SERVICE_NAME' },
   }).then(console.log)
   ```
2. Expected: a response with `{ ok: true }`. If you get an error, send me the full text.

## Step 5. Tell me the result so I can build the Cloud Hosting version

I will then:

1. Add a small test route that prints the request headers, to confirm whether the container
   receives the user's identity directly (this may remove the need for the AppSecret login).
2. Test how the container downloads a book uploaded with `wx.cloud.uploadFile`, and how it
   returns the finished PDF.
3. Change `miniprogram/utils/api.js` to use `wx.cloud.callContainer` and Cloud Storage, keeping
   the current HTTP mode for local testing.

## Step 6. Test on your phone

1. In DevTools click **Preview** and scan the QR code with WeChat on your phone.
   (Add your WeChat as a developer under **Management -> Members** first.)
2. Send a small PDF to "File Transfer" (文件传输助手), open the mini program, choose it, and
   run a **3-page preview** with your own Qwen or DeepSeek key.
3. Check: progress updates, the PDF opens, sharing to a chat works, and the email arrives.

## Step 7. Prepare for review

1. **Privacy**: in the console, open **Settings -> Service content declaration** (or User privacy
   protection guidelines) and declare what you collect: uploaded files, API key (used only for
   the job, not stored), email address, and openid. Add a privacy policy page.
2. **Copyright**: reviewers may ask about translating uploaded books. See
   `docs/LEGAL_DISCUSSION.md`. A short in-app notice such as "only upload books you have the
   right to translate" helps.
3. **Icon and name**: use one of the icons in `docs/` (the console wants a 144x144 or larger
   square image) and a name that doesn't clash with existing mini programs.
4. Update `miniprogram/project.config.json` so `urlCheck` and local-only settings are not
   needed in the release build.

## Step 8. Upload and submit

1. In DevTools, click **Upload** and enter a version number and notes.
2. In the console, open **Management -> Version management**, choose the uploaded version as
   the **review version**, and submit.
3. Review usually takes from hours to a few days. If rejected, the reason is shown; send it to
   me and I'll help fix it.
4. After approval, click **Release**.

## Step 9. After release

- Check cost daily for the first week (Cloud Hosting usage and your users' API keys are
  separate: users pay their own model costs).
- Keep `BOOKTRANS_RETENTION_HOURS` low so books are deleted soon after translation.
- Consider charging later: WeChat Pay needs a business account (see
  `docs/WECHAT_MINIPROGRAM.md`).

---

## Open questions (I could not confirm these in the docs)

| Question | Why it matters | How we find out |
| --- | --- | --- |
| Request size and timeout limits of `callContainer` | Decides whether uploads can go through it | Step 4/5 tests |
| How the container reads a `fileID` and writes the PDF back | Needed for big books | Step 5 test route |
| Whether the container gets the user's openid automatically | Could drop the AppSecret login | Step 5 test route |
| Cloud Hosting price for a 2 GB instance | Your running cost | Console pricing page |
| Whether your account type may use your chosen category | Affects review | Step 1 |

## If Cloud Hosting turns out not to fit

Fallback: rent any server, point a domain at it, add the domain to the whitelist in the
console, and set `BASE_URL` in `miniprogram/utils/api.js`. Mainland China servers need ICP
filing; the console says whether an overseas domain is accepted. The code in the repo already
supports this route.
