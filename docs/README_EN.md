# Remnawave Node Installer

An interactive installer that deploys a Remnawave node and creates its Xray profile, panel node, host, and Internal Squad inbound assignment through the panel API.

**Language:** [Русский](../README.md) · [English](README_EN.md)

## What it installs

The installer runs Remnawave Node, an Nginx REALITY socket, a selected cover website, a Let’s Encrypt certificate, and Cloudflare WARP as a local SOCKS5 proxy. It uploads [the Xray profile](../profile.json) with a generated inbound TAG and REALITY private key. The entered node domain becomes `serverNames` and host SNI. The host listens on port 443.

The routing follows the supplied template. The block rule uses the defined `BLOCK` outbound, and the duplicate `beeline.ru` entry is removed. `.ru`, `.su`, `.рф`, and `geosite:google` traffic goes through WARP. Other traffic uses Xray's default `DIRECT` outbound.

## Requirements

- A fresh Ubuntu 22.04+ or Debian 12+ server with root access and `apt`.
- A working Remnawave panel on HTTPS and an API token allowed to create config profiles, nodes and hosts, and edit Internal Squads.
- A node domain whose A/AAAA record points to the server. TCP/80 must be reachable for initial certificate issuance; TCP/443 must be reachable by clients.
- Restrict TCP/2222 **to the panel's IP address** in the provider or host firewall. The installer leaves firewall rules alone to avoid disrupting nonstandard SSH configurations.
- Free TCP/443, TCP/80 during certificate issuance, and loopback TCP/8080.

## Install

```bash
git clone https://github.com/x1roko/node-setup.git
cd node-setup
sudo ./install.sh
```

Select `Русский` or `English`, then enter the panel URL and API token, node domain, certificate email, node name, country code, cover service, address reachable by the panel, and Internal Squad. The token is hidden during entry and is not saved. A retry with the same settings resumes from the local state file.

Existing certificates in `/etc/letsencrypt/live/<domain>/` are reused. Otherwise Certbot requests one through HTTP-01 on TCP/80. A deploy hook refreshes Nginx's certificate copies after renewal.

## Verify

```bash
sudo docker compose -f /opt/remnanode/docker-compose.yml ps
sudo docker compose -f /opt/remnanode/nginx/docker-compose.yml logs --tail=100
sudo curl --proxy socks5h://127.0.0.1:40000 https://www.cloudflare.com/cdn-cgi/trace
```

If the system installed `docker-compose` rather than the Compose plugin, replace `docker compose` in the verification commands with `docker-compose`.

Check node status, profile, host and Internal Squad in the panel. Verify the panel can reach the node address on TCP/2222. Routing rules apply on the **server**; they do not change client routing.

## Files and ports

| Path / port | Purpose |
| --- | --- |
| `/opt/remnanode/installer-state.json` | Created UUIDs and node secret; mode `600` |
| `/opt/remnanode/node.env` | Node secret; mode `600` |
| `/opt/remnanode/nginx/` | Nginx configuration and certificate copies |
| `/opt/remnanode/service/` | Cover service Compose file |
| `443/tcp` | VLESS REALITY |
| `2222/tcp` | Remnawave Node API, panel IP only |
| `40000/tcp` | Local WARP SOCKS5 |
| `8080/tcp` | Cover site on `127.0.0.1` |

## Recovery and limits

Fix any reported error and rerun `sudo ./install.sh` with the same values. Keep the state file private because it holds the node secret. The installer does not modify already created panel objects when the domain or service changes; use the panel and relevant Compose files for that. You remain responsible for DNS, firewall policy and panel availability. Geosite categories depend on the Xray data shipped in the node image.

API and deployment behavior are based on [Remnawave's node guide](https://docs.rw/install/remnawave-node/), [Config Profiles](https://docs.rw/learn-en/config-profiles/), [Hosts](https://docs.rw/learn-en/hosts/) and [Internal Squads](https://docs.rw/learn-en/squads/).
