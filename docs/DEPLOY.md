# Deploy the web service on a cloud server (Alibaba Cloud / Tencent Cloud)

部署到阿里云 / 腾讯云（国际站）的云服务器。Everything runs in Docker on one Linux server.

## Why an overseas region, not mainland China

- Anthropic's API is not offered in mainland China, and Hong Kong may not be on its
  supported list either (check the live page: https://www.anthropic.com/supported-countries).
  The translation worker calls that API, so the server should be in a supported region:
  **Singapore or Tokyo** are good choices.
- An overseas server needs **no ICP filing (备案)**, and it can usually be reached from
  mainland China, with moderate speed.
- Use the **international** sites (alibabacloud.com, tencentcloud.com), not aliyun.com or
  cloud.tencent.com: those sell mainland servers, which would need the filing.

## 1. Create the server

1. Sign up at Alibaba Cloud International or Tencent Cloud International. You will need an
   email address and a payment method that the international site accepts (check which).
2. Create a **lightweight / simple application server**:
   - Region: Singapore (or Tokyo). Not Hong Kong, not mainland.
   - Image: Ubuntu 22.04 or 24.04 (plain OS, not a prebuilt app).
   - Size: **2 vCPU / 4 GB RAM / 40 GB disk or more** (use 1 vCPU / 2 GB only with
     `BOOKTRANS_WORKERS=1`). Check the current price on the sign-up page.
3. In the server's **firewall / security group**, allow inbound TCP **22** (SSH), **80** and **443**.
   Do not open 8000: the app is only reachable through the web server in front of it.
4. Note the server's public IP address.

## 2. Install Docker

```
ssh root@SERVER_IP
curl -fsSL https://get.docker.com | sh
```

## 3. Copy the project to the server

From your own computer, in the project folder:

```
rsync -av --exclude .venv --exclude data --exclude '*.pdf' --exclude '*.cache.json' \
  ./ root@SERVER_IP:/opt/book-translator/
```

(If the project is on GitHub, `git clone` it on the server instead.)

## 4. Start it

```
ssh root@SERVER_IP
cd /opt/book-translator
cp .env.example .env          # leave DOMAIN empty for the first test
docker compose up -d --build
docker compose ps             # both services should be "running"
```

Open `http://SERVER_IP/`. The first build downloads packages and takes a few minutes. If the
build is slow, use a nearer PyPI mirror:
`docker compose build --build-arg PIP_INDEX_URL=https://pypi.tuna.tsinghua.edu.cn/simple`.

**Over plain HTTP the page warns you not to type a real API key.** Test with the preview of
a small file using a key you can revoke, or go straight to step 5.

## 5. Add a domain and HTTPS

1. Buy a domain (any registrar: Cloudflare, Namecheap, Alibaba Cloud domains...).
2. Create a DNS **A record**: `books.yourdomain.com` → `SERVER_IP`. Wait a few minutes.
3. Edit `.env`: `DOMAIN=books.yourdomain.com`, then `docker compose up -d`.
4. Caddy gets a free certificate automatically (ports 80 and 443 must be open). Open
   `https://books.yourdomain.com/`.

## Day to day

| Task | Command |
| --- | --- |
| Logs | `docker compose logs -f app` |
| Restart | `docker compose restart` |
| Update after changing the code | copy the files again (step 3), then `docker compose up -d --build` |
| Stop | `docker compose down` (uploads and results stay in the `data` volume) |

Uploaded books and results are deleted automatically after `BOOKTRANS_RETENTION_HOURS` (default 24).
The cleanup runs at start and then every hour.

## Safety checklist

- Use SSH keys and disable password login (`PasswordAuthentication no` in `/etc/ssh/sshd_config`).
- Keep the system updated: `apt update && apt upgrade`, and consider `unattended-upgrades`.
- Never run the public site without HTTPS: the API key is sent in the request body.
- The server keeps no API keys on disk, but anyone with server access could read process memory
  while a job runs. Keep the server to yourself.
- Add a terms-of-use page and a takedown contact before inviting the public. You are hosting
  files that others upload.

## Not tested yet

These files were written without a Docker installation on the development machine, so the first
`docker compose up --build` is the real test. Report any error text and it can be fixed quickly.
