# Fleet Deployment & Auto-Proxy Resolver Guide

## 1. Subdomain Namespace Architecture

To prevent DNS collisions between 20+ servers, each VM gets its own dedicated subdomain namespace pointing to that specific VM's public IP:

| VM Name | DNS Wildcard Record | Points to | Example Service URL |
|---|---|---|---|
| **`vm1`** | `*.vm1.dev-server.suburban.ng` | `IP of VM 1` | `https://api.vm1.dev-server.suburban.ng` |
| **`vm2`** | `*.vm2.dev-server.suburban.ng` | `IP of VM 2` | `https://frontend.vm2.dev-server.suburban.ng` |
| **`auth-server`** | `*.auth-server.dev-server.suburban.ng` | `IP of VM 3` | `https://oauth.auth-server.dev-server.suburban.ng` |

---

## 2. Setting Up `inventory.ini` with IPs, Usernames & Passwords

In `infra/ansible/inventory.ini`, you define each VM's IP, name, and login credentials:

```ini
[fleet]
vm1          ansible_host=104.248.10.11  vm_domain="vm1.dev-server.suburban.ng"
vm2          ansible_host=104.248.10.12  vm_domain="vm2.dev-server.suburban.ng"
auth-server  ansible_host=104.248.10.13  vm_domain="auth-server.dev-server.suburban.ng"
billing-node ansible_host=104.248.10.14  vm_domain="billing-node.dev-server.suburban.ng"

[fleet:vars]
# Default login credentials for all VMs
ansible_user=root
ansible_password=YourServerPasswordHere
# If using SSH keys instead of passwords:
# ansible_ssh_private_key_file=~/.ssh/id_rsa

# Central Hub to report status back to:
central_hub_url="https://status.dev-server.suburban.ng/api/telemetry/ingest"
```

---

## 3. Auto-Resolving Existing Reverse Proxies (Nginx, Apache, or Caddy)

When the setup script runs on any VM, it automatically inspects ports `80` and `443` before starting anything:

### Case A: VM is clean (No Nginx/Apache running)
- Caddy binds directly to `80` and `443`.
- Everything works out of the box with zero configuration.

### Case B: VM already runs Nginx on host (`nginx` detected)
- Script detects Nginx listening on port `80/443`.
- Script configures Caddy to listen on internal port `8080`.
- Script automatically drops a proxy snippet into `/etc/nginx/conf.d/devctl-proxy.conf`:
  ```nginx
  server {
      listen 80;
      server_name *.<vm_domain>;
      location / {
          proxy_pass http://127.0.0.1:8080;
          proxy_set_header Host $host;
          proxy_set_header X-Real-IP $remote_addr;
      }
  }
  ```
- Runs `nginx -s reload`. Your existing Nginx websites stay 100% intact, and `devctl` traffic routes through seamlessly!

### Case C: VM already runs Apache on host (`apache2` / `httpd` detected)
- Script enables `proxy` and `proxy_http` modules: `a2enmod proxy proxy_http`.
- Drops a VirtualHost into `/etc/apache2/sites-available/devctl.conf`:
  ```apache
  <VirtualHost *:80>
      ServerAlias *.<vm_domain>
      ProxyPass / http://127.0.0.1:8080/
      ProxyPassReverse / http://127.0.0.1:8080/
  </VirtualHost>
  ```
- Runs `systemctl reload apache2`.

### Case D: VM already runs standalone Caddy
- Script mounts dynamic configuration into `/etc/caddy/conf.d/*.caddy` and runs `caddy reload`.
