# WeChat Mini Program: Requirements and Payment

> Notes from a Q&A session. Rules change, so check the current requirements in the WeChat MP console before committing.

## Part 1. What you need to develop and run a WeChat Mini Program

### 1. Accounts
- **A WeChat account**, used to scan QR codes to log in.
- **A Mini Program account** (registered at mp.weixin.qq.com → Mini Program). It gives you an **AppID**, required for real-device preview, upload and publishing.
  - **Test account** (sandbox AppID): free and instant. Enough for learning and local development.
  - **Individual vs. enterprise registration**: an individual account is fine for personal projects. Many features need an enterprise account, including payments, e-commerce and some content categories. In mainland China, registration needs real-name verification. Overseas entities can register too, but need extra documents and a verification fee.

### 2. Tools
- **WeChat DevTools** (微信开发者工具): the official IDE for macOS, Windows and Linux. Includes a simulator, debugger, real-device preview and upload.
- An optional external editor such as VS Code. You still need DevTools to build, preview and upload.
- **Node.js**, only if you use npm packages (DevTools' "Build npm" step) or frameworks such as Taro, uni-app or Remax.

### 3. Skills and project structure
A native mini program has these files:
- `app.js`, `app.json`, `app.wxss`: global logic, config and styles.
- Per page: `.wxml` (markup, like HTML), `.wxss` (styles, like CSS), `.js` (logic) and `.json` (page config).
- You write JavaScript or TypeScript. The framework is similar to Vue or React in spirit, but has its own syntax and component set.
- Cross-platform frameworks (**uni-app**, **Taro**) let you share code across platforms.

### 4. Backend
- A mini program can only call **HTTPS** domains that you whitelist in the MP console (Development → Development Settings → server domain).
- **Cloud Development (云开发)** is WeChat's built-in serverless option: cloud functions, database and storage, with no domain or server needed.
- **Domain with ICP filing (备案)**: required for your own backend serving users in mainland China.

### 5. Typical workflow
1. Register and get an AppID (or use a test account).
2. Install DevTools, create a project, enter the AppID, pick a template.
3. Develop and debug in the simulator.
4. Click **Preview** to scan a QR code and run on your phone. Add yourself as a developer under MP → Management → Members.
5. Click **Upload**, submit for review in the MP console, and release after approval.

### 6. Common pitfalls
- Review rules are strict. Categories such as content, tools and e-commerce need specific qualifications.
- A privacy policy and user-privacy declaration are required.
- Package size limit: 2 MB per main package, 20 MB total with subpackages.
- Payment (WeChat Pay) needs an enterprise-type account and a merchant ID.

## Part 2. Getting paid: do you need an enterprise account?

Mostly yes. A **personal (individual) Mini Program account can't use WeChat Pay**. Payment needs a mini program account with a **merchant (商户) account** bound to it, and WeChat only lets non-individual subjects do that.

### Ways to get paid

| Route | Needs a company? | Notes |
|---|---|---|
| **Individual business (个体工商户)** | No, only a business license | The usual workaround. Register a 个体工商户 license (cheap or free, often online), register the mini program under it, then apply for WeChat Pay. Most solo developers in China do this. |
| **Enterprise (company)** | Yes | Full features, but more cost and paperwork. |
| **Personal account + WeChat Pay** | n/a | Not supported. |
| **Mini program ads (流量主)** | No | Individual accounts can enable ad revenue once they reach a traffic threshold (roughly 1,000 users). Income is small and depends on traffic. |
| **Third-party aggregator / service provider (服务商) payments** | Varies | Can sometimes work for small merchants, but adds fees and compliance risk. |
| **Take payment outside the mini program** | No | Sell redemption codes or subscriptions through Taobao, Xianyu or your own site. A gray area for in-app digital goods that can violate review rules. |

### Other things to know
- **Category limits:** individual accounts can only publish in some categories, and many "service" and "tool" categories need a company or business license anyway.
- **Digital goods on iOS:** WeChat has special rules for selling virtual items to iPhone users. Check them if you plan to sell credits or subscriptions.
- **Overseas:** WeChat Pay also needs an overseas enterprise entity and a verification fee, so a personal account won't work there either.

## Suggestion for the book translator
To charge per book or per page, the simplest path is to register a **个体工商户**, register the mini program under it, and bind WeChat Pay. To test the idea first, start with a personal or test account for development and add payment later.

**Open question:** are you based in mainland China? Eligibility for a 个体工商户 depends on that.
