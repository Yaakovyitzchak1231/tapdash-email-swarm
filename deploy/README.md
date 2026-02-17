# TapDash Email Swarm Production Deploy

This deployment guide implements the active roadmap defined in `PLAN_EMAIL_SWARM.md`.

This folder provisions an always-on host for:

- `email_work_order_service.py` (`127.0.0.1:8080`)
- `review_actions_service.py` (`127.0.0.1:8090`)
- `pipeline_daemon.py` (background worker)
- `cloudflared` tunnel (public HTTPS -> local `8080`)

## 1. Prepare VM (Ubuntu 22.04+)

Run as root once:

```bash
apt-get update
apt-get install -y python3 python3-venv curl ca-certificates
```

## 2. Copy project to host

Project should live at `/opt/tapdash-swarm` and run under the system user `tapdash`.

## 3. Configure environment

Create:

```text
/etc/tapdash/swarm.env
```

Use `deploy/swarm.env.example` as the template.

## 4. Install services

From project root on the VM:

```bash
sudo bash deploy/install_services.sh
```

This installs and enables:

- `tapdash-email-intake.service`
- `tapdash-review-actions.service`
- `tapdash-pipeline-daemon.service`

## 5. Setup Cloudflare tunnel

### Quick public URL (ephemeral)

```bash
cloudflared tunnel --url http://127.0.0.1:8080
```

### Persistent named tunnel (recommended)

1. Login and create tunnel:

```bash
cloudflared tunnel login
cloudflared tunnel create tapdash-email-intake
cloudflared tunnel route dns tapdash-email-intake webhook.tapdash.co
```

2. Create config:

```bash
mkdir -p /etc/cloudflared
cp deploy/cloudflared/config.yml.example /etc/cloudflared/config.yml
```

3. Update `/etc/cloudflared/config.yml`:

- set `tunnel` name or UUID
- set `credentials-file`
- set `hostname`

4. Install + start service:

```bash
sudo cp deploy/systemd/cloudflared-tapdash.service /etc/systemd/system/cloudflared-tapdash.service
sudo systemctl daemon-reload
sudo systemctl enable --now cloudflared-tapdash.service
```

## 6. Health checks

```bash
curl -sS http://127.0.0.1:8080/health
curl -sS http://127.0.0.1:8090/health
sudo systemctl status tapdash-email-intake.service --no-pager
sudo systemctl status tapdash-review-actions.service --no-pager
sudo systemctl status tapdash-pipeline-daemon.service --no-pager
```

## 7. Zapier target URL

Use:

```text
https://<your-public-host>/zapier/email-forward
```

Required header:

```text
X-Webhook-Secret: <ZAPIER_SHARED_SECRET>
```

## Security baseline

- Keep services bound to `127.0.0.1` only.
- Expose only via Cloudflare tunnel.
- Keep `ZAPIER_SHARED_SECRET` enabled.
- Rotate any token shared in chat.
- Use Cloudflare Access service token in Zapier for an additional layer.
