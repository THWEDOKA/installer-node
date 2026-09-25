#!/usr/bin/env python3
"""Interactive Remnawave node installer. Requires Python 3.9+ and root."""
import getpass
import ipaddress
import json
import os
from pathlib import Path
import re
import secrets
import shutil
import subprocess
import sys
import urllib.error
import urllib.request
from urllib.parse import urlsplit

ROOT = Path('/opt/remnanode')
STATE = ROOT / 'installer-state.json'
TEMPLATE = Path(__file__).with_name('profile.json')
SERVICES = {
    'filebrowser': ('filebrowser/filebrowser:latest', 80),
    'memos': ('neosmemo/memos:stable', 5230),
    'excalidraw': ('excalidraw/excalidraw:latest', 80),
    'navidrome': ('deluan/navidrome:latest', 4533),
}
MESSAGES = {
    'ru': {
        'title': 'Установка ноды Remnawave', 'root': 'Запустите установщик от root (sudo ./install.sh).',
        'os': 'Поддерживаются Ubuntu 22.04+ и Debian 12+.',
        'panel': 'HTTPS-адрес панели (например, https://panel.example.com): ',
        'token': 'API-токен панели (ввод скрыт): ', 'domain': 'Домен ноды и SNI: ',
        'email': 'Email для сертификата Let’s Encrypt: ', 'name': 'Имя ноды в панели',
        'country': 'Код страны из двух букв (например, DE): ',
        'service': 'Веб-сервис за REALITY', 'choice': 'Номер сервиса [1]: ',
        'port': 'Адрес или IP ноды для подключения панели [домен]: ',
        'existing': 'Найдена прежняя установка для этого домена; продолжение.',
        'preflight': 'Проверка панели и параметров...', 'packages': 'Установка системных пакетов...',
        'certificate': 'Подготовка сертификата...', 'warp': 'Настройка WARP...',
        'profile': 'Создание профиля в панели...', 'node': 'Создание ноды в панели...',
        'host': 'Создание хоста в панели...', 'done': 'Установка завершена.',
        'panel_access': 'Откройте TCP/2222 только для IP панели в сетевом firewall; TCP/443 для клиентов.',
        'squad': 'Добавление inbound в Internal Squad...', 'squad_choice': 'Номер Internal Squad',
        'error': 'Ошибка',
    },
    'en': {
        'title': 'Remnawave node installer', 'root': 'Run this installer as root (sudo ./install.sh).',
        'os': 'Ubuntu 22.04+ and Debian 12+ are supported.',
        'panel': 'Panel HTTPS URL (for example, https://panel.example.com): ',
        'token': 'Panel API token (hidden): ', 'domain': 'Node domain and SNI: ',
        'email': 'Email for Let’s Encrypt certificate: ', 'name': 'Node name in panel',
        'country': 'Two-letter country code (for example, DE): ',
        'service': 'Web service behind REALITY', 'choice': 'Service number [1]: ',
        'port': 'Node address or IP reachable by panel [domain]: ',
        'existing': 'Existing installation for this domain found; resuming.',
        'preflight': 'Checking panel and input...', 'packages': 'Installing system packages...',
        'certificate': 'Preparing certificate...', 'warp': 'Configuring WARP...',
        'profile': 'Creating panel profile...', 'node': 'Creating panel node...',
        'host': 'Creating panel host...', 'done': 'Installation complete.',
        'panel_access': 'Allow TCP/2222 only from the panel IP in your network firewall; allow TCP/443 for clients.',
        'squad': 'Adding inbound to Internal Squad...', 'squad_choice': 'Internal Squad number',
        'error': 'Error',
    },
}


def fail(message):
    raise RuntimeError(message)


def run(*args, input_data=None):
    return subprocess.run(args, input=input_data, text=True, check=True)


def compose(*args):
    if subprocess.run(['docker', 'compose', 'version'], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL).returncode == 0:
        run('docker', 'compose', *args)
    else:
        run('docker-compose', *args)


def ask(prompt, default=''):
    suffix = f' [{default}]' if default else ''
    return input(f'{prompt}{suffix}: ').strip() or default


def valid_domain(value):
    return bool(len(value) <= 253 and re.fullmatch(r'(?=.{1,253}$)(?:[a-zA-Z0-9](?:[a-zA-Z0-9-]{0,61}[a-zA-Z0-9])?\.)+[a-zA-Z]{2,63}', value))


def atomic_json(path, data, mode=0o600):
    path.parent.mkdir(parents=True, exist_ok=True)
    temp = path.with_name(path.name + '.tmp')
    with open(temp, 'w', encoding='utf-8') as stream:
        json.dump(data, stream, indent=2, ensure_ascii=False)
        stream.write('\n')
    os.chmod(temp, mode)
    os.replace(temp, path)


def write_private(path, value):
    path.parent.mkdir(parents=True, exist_ok=True)
    temp = path.with_name(path.name + '.tmp')
    temp.write_text(value, encoding='utf-8')
    os.chmod(temp, 0o600)
    os.replace(temp, path)


class API:
    def __init__(self, base, token):
        self.base = base.rstrip('/')
        self.token = token

    def request(self, method, path, data=None):
        body = json.dumps(data).encode() if data is not None else None
        request = urllib.request.Request(
            self.base + '/api' + path, data=body, method=method,
            headers={'Authorization': 'Bearer ' + self.token, 'Content-Type': 'application/json', 'Accept': 'application/json'},
        )
        try:
            with urllib.request.urlopen(request, timeout=25) as response:
                raw = response.read()
                return json.loads(raw) if raw else {}
        except urllib.error.HTTPError as exc:
            detail = exc.read(2048).decode(errors='replace')
            fail(f'Panel API {method} {path}: HTTP {exc.code}: {detail}')
        except urllib.error.URLError as exc:
            fail(f'Panel API {method} {path}: {exc.reason}')


def response(data):
    if not isinstance(data, dict) or 'errorCode' in data:
        fail(f'Invalid panel response: {data}')
    return data.get('response', data)


def profile_for(domain, tag, private_key):
    config = json.loads(TEMPLATE.read_text(encoding='utf-8'))
    inbound = config['inbounds'][0]
    inbound['tag'] = tag
    reality = inbound['streamSettings']['realitySettings']
    reality['privateKey'] = private_key
    reality['serverNames'] = [domain]
    if config['routing']['rules'][0]['outboundTag'] != 'BLOCK':
        fail('Invalid outbound tag in profile template')
    return config


def choose_service(locale, saved=None):
    names = list(SERVICES)
    print(MESSAGES[locale]['service'] + ':')
    for index, name in enumerate(names, 1):
        print(f'  {index}. {name}')
    default = str(names.index(saved) + 1) if saved in names else '1'
    choice = input(MESSAGES[locale]['choice'].replace('[1]', f'[{default}]')).strip() or default
    if not choice.isdigit() or not 1 <= int(choice) <= len(names):
        fail('Invalid service number / Неверный номер сервиса')
    return names[int(choice) - 1]


def check_os(locale):
    info = Path('/etc/os-release').read_text()
    match_id = re.search(r'^ID="?([^"\n]+)', info, re.M)
    match_ver = re.search(r'^VERSION_ID="?([0-9]+)', info, re.M)
    distro, version = (match_id.group(1), int(match_ver.group(1))) if match_id and match_ver else ('', 0)
    if not ((distro == 'ubuntu' and version >= 22) or (distro == 'debian' and version >= 12)):
        fail(MESSAGES[locale]['os'])


def ensure_packages():
    run('apt-get', 'update')
    run('apt-get', 'install', '-y', 'ca-certificates', 'curl', 'gnupg', 'certbot', 'python3', 'docker.io')
    if subprocess.run(['docker', 'compose', 'version'], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL).returncode != 0 and not shutil.which('docker-compose'):
        attempt = subprocess.run(['apt-get', 'install', '-y', 'docker-compose-plugin'])
        if attempt.returncode != 0:
            run('apt-get', 'install', '-y', 'docker-compose')
    run('systemctl', 'enable', '--now', 'docker')
    compose('version')


def renewal_hook(domain):
    return '''#!/bin/sh
set -eu
case " $RENEWED_DOMAINS " in
  *" __NODE_DOMAIN__ "*)
    cp -L "/etc/letsencrypt/live/__NODE_DOMAIN__/fullchain.pem" "/opt/remnanode/nginx/fullchain.pem"
    cp -L "/etc/letsencrypt/live/__NODE_DOMAIN__/privkey.pem" "/opt/remnanode/nginx/privkey.key"
    chmod 600 "/opt/remnanode/nginx/privkey.key"
    if docker compose version >/dev/null 2>&1; then
      docker compose -f /opt/remnanode/nginx/docker-compose.yml restart
    else
      docker-compose -f /opt/remnanode/nginx/docker-compose.yml restart
    fi
    ;;
esac
'''.replace('__NODE_DOMAIN__', domain)


def ensure_certificate(domain, email):
    live = Path('/etc/letsencrypt/live') / domain
    if not ((live / 'fullchain.pem').exists() and (live / 'privkey.pem').exists()):
        run('certbot', 'certonly', '--standalone', '--non-interactive', '--agree-tos', '--preferred-challenges', 'http', '-m', email, '-d', domain)
    certs = ROOT / 'nginx'
    certs.mkdir(parents=True, exist_ok=True)
    shutil.copyfile(live / 'fullchain.pem', certs / 'fullchain.pem')
    shutil.copyfile(live / 'privkey.pem', certs / 'privkey.key')
    os.chmod(certs / 'privkey.key', 0o600)
    hook = Path('/etc/letsencrypt/renewal-hooks/deploy/remnanode-sync')
    write_private(hook, renewal_hook(domain))
    os.chmod(hook, 0o700)
    run('systemctl', 'enable', '--now', 'certbot.timer')


def start_containers(state):
    domain, service = state['domain'], state['service']
    image, port = SERVICES[service]
    service_dir = ROOT / 'service'
    service_dir.mkdir(parents=True, exist_ok=True)
    service_volumes = {
        'filebrowser': ['      - ./files:/srv', '      - ./database:/database'],
        'memos': ['      - ./data:/var/opt/memos'],
        'excalidraw': [],
        'navidrome': ['      - ./data:/data', '      - ./music:/music:ro'],
    }[service]
    volume_section = '\n    volumes:\n' + '\n'.join(service_volumes) if service_volumes else ''
    write_private(service_dir / 'docker-compose.yml', f'''services:
  web:
    image: {image}
    restart: unless-stopped
    ports:
      - "127.0.0.1:8080:{port}"
{volume_section}
''')
    compose('-f', str(service_dir / 'docker-compose.yml'), 'up', '-d')
    nginx = f'''server {{
    listen unix:/dev/shm/nginx.sock ssl proxy_protocol;
    server_name {domain};
    ssl_certificate /etc/nginx/certs/fullchain.pem;
    ssl_certificate_key /etc/nginx/certs/privkey.key;
    location / {{
        proxy_pass http://127.0.0.1:8080;
        proxy_set_header Host $host;
        proxy_set_header X-Real-IP $proxy_protocol_addr;
        proxy_set_header X-Forwarded-For $proxy_protocol_addr;
        proxy_set_header X-Forwarded-Proto https;
    }}
}}
'''
    write_private(ROOT / 'nginx/nginx.conf', nginx)
    write_private(ROOT / 'nginx/docker-compose.yml', '''services:
  nginx:
    image: nginx:stable
    restart: unless-stopped
    network_mode: host
    volumes:
      - ./nginx.conf:/etc/nginx/conf.d/default.conf:ro
      - ./fullchain.pem:/etc/nginx/certs/fullchain.pem:ro
      - ./privkey.key:/etc/nginx/certs/privkey.key:ro
      - /dev/shm:/dev/shm
    command: ["sh", "-c", "rm -f /dev/shm/nginx.sock && exec nginx -g 'daemon off;'"]
''')
    compose('-f', str(ROOT / 'nginx/docker-compose.yml'), 'up', '-d')
    write_private(ROOT / 'node.env', 'NODE_PORT=2222\nSECRET_KEY=' + state['secret_key'] + '\n')
    write_private(ROOT / 'docker-compose.yml', '''services:
  remnanode:
    image: remnawave/node:latest
    container_name: remnanode
    restart: unless-stopped
    network_mode: host
    env_file: ./node.env
    volumes:
      - /dev/shm:/dev/shm
''')
    compose('-f', str(ROOT / 'docker-compose.yml'), 'up', '-d')


def configure_squad(api, state, locale):
    if state.get('squad_uuid'):
        return
    squads = response(api.request('GET', '/internal-squads')).get('internalSquads', [])
    if not squads:
        fail('Create an Internal Squad in the panel first / Сначала создайте Internal Squad в панели')
    for index, squad in enumerate(squads, 1):
        print(f"  {index}. {squad.get('name', squad['uuid'])}")
    choice = ask(MESSAGES[locale]['squad_choice'], '1')
    if not choice.isdigit() or not 1 <= int(choice) <= len(squads):
        fail('Invalid squad number / Неверный номер группы')
    squad = squads[int(choice) - 1]
    inbound_uuids = [item['uuid'] for item in squad.get('inbounds', [])]
    if state['inbound_uuid'] not in inbound_uuids:
        inbound_uuids.append(state['inbound_uuid'])
        updated = response(api.request('PATCH', '/internal-squads', {'uuid': squad['uuid'], 'inbounds': inbound_uuids}))
        if updated.get('uuid') != squad['uuid']:
            fail('Panel did not confirm Internal Squad update')
    state['squad_uuid'] = squad['uuid']
    atomic_json(STATE, state)


def main():
    print('Language / Язык: 1) Русский  2) English')
    locale = 'ru' if (input('> ').strip() or '1') == '1' else 'en'
    msg = MESSAGES[locale]
    print('\n' + msg['title'])
    if os.geteuid() != 0:
        fail(msg['root'])
    check_os(locale)
    saved = json.loads(STATE.read_text()) if STATE.exists() else {}
    print(msg['existing'] if saved else msg['preflight'])
    panel = input(msg['panel']).strip().rstrip('/')
    parsed = urlsplit(panel)
    if parsed.scheme != 'https' or not parsed.hostname or parsed.path or parsed.query or parsed.fragment:
        fail('Panel URL must be an HTTPS origin / Адрес панели должен быть HTTPS origin')
    token = getpass.getpass(msg['token']).strip()
    if not token:
        fail('API token is required / Нужен API-токен')
    api = API(panel, token)
    response(api.request('GET', '/config-profiles'))
    domain = input(msg['domain']).strip().lower()
    if not valid_domain(domain):
        fail('Invalid domain / Неверный домен')
    if saved and (saved.get('domain') != domain or saved.get('panel') != panel):
        fail('Existing state belongs to another domain or panel / Найдена установка другого домена или панели')
    email = input(msg['email']).strip()
    if not re.fullmatch(r'[^\s@]+@[^\s@]+\.[^\s@]+', email):
        fail('Invalid email / Неверный email')
    name = ask(msg['name'], saved.get('name', f'Node-{domain}'))
    if not re.fullmatch(r'[\w .-]{1,64}', name):
        fail('Invalid node name / Неверное имя ноды')
    country = input(msg['country']).strip().upper()
    if not re.fullmatch(r'[A-Z]{2}', country):
        fail('Invalid country code / Неверный код страны')
    service = choose_service(locale, saved.get('service'))
    address = input(msg['port']).strip() or domain
    try:
        ipaddress.ip_address(address)
    except ValueError:
        if not valid_domain(address):
            fail('Invalid node address / Неверный адрес ноды')
    if saved and (saved.get('name') != name or saved.get('service') != service or saved.get('address') != address or saved.get('country') != country):
        fail('Saved node settings differ; use the original values / Параметры отличаются от сохранённых')
    state = saved or {'panel': panel, 'domain': domain, 'name': name, 'country': country, 'service': service, 'address': address}
    ROOT.mkdir(parents=True, exist_ok=True)
    os.chmod(ROOT, 0o700)
    if 'secret_key' not in state:
        generated = response(api.request('GET', '/keygen'))
        state['secret_key'] = generated.get('secretKey') or generated.get('pubKey')
        if not state['secret_key']:
            fail('Panel did not return node SECRET_KEY')
        atomic_json(STATE, state)
    print(msg['packages'])
    ensure_packages()
    print(msg['certificate'])
    ensure_certificate(domain, email)
    print(msg['warp'])
    subprocess.run(['bash', str(Path(__file__).with_name('warp.sh'))], env={**os.environ, 'LANGUAGE_CHOICE': locale}, check=True)
    print(msg['profile'])
    if 'profile_uuid' not in state:
        key_data = response(api.request('GET', '/system/tools/x25519/generate'))
        keypair = key_data.get('keypairs', [{}])[0]
        private_key = keypair.get('privateKey')
        if not private_key:
            fail('Panel did not return REALITY private key')
        tag = 'VLESS-' + secrets.token_hex(5).upper()
        profile_name = 'Node-' + domain
        config = profile_for(domain, tag, private_key)
        created = response(api.request('POST', '/config-profiles', {'name': profile_name, 'config': config}))
        inbound = (created.get('inbounds') or [{}])[0]
        if not created.get('uuid') or not inbound.get('uuid'):
            fail('Panel did not return profile and inbound UUIDs')
        state.update(profile_uuid=created['uuid'], inbound_uuid=inbound['uuid'], tag=tag)
        atomic_json(STATE, state)
    start_containers(state)
    print(msg['node'])
    if 'node_uuid' not in state:
        node = response(api.request('POST', '/nodes', {
            'name': name, 'address': address, 'port': 2222, 'countryCode': country,
            'configProfile': {'activeConfigProfileUuid': state['profile_uuid'], 'activeInbounds': [state['inbound_uuid']]},
            'isTrafficTrackingActive': False, 'trafficLimitBytes': 0,
            'notifyPercent': 0, 'trafficResetDay': 31, 'consumptionMultiplier': 1.0,
        }))
        if not node.get('uuid'):
            fail('Panel did not return node UUID')
        state['node_uuid'] = node['uuid']
        atomic_json(STATE, state)
    print(msg['host'])
    if 'host_uuid' not in state:
        host = response(api.request('POST', '/hosts', {
            'inbound': {'configProfileUuid': state['profile_uuid'], 'configProfileInboundUuid': state['inbound_uuid']},
            'remark': name, 'address': domain, 'port': 443, 'path': '', 'sni': domain,
            'host': '', 'alpn': None, 'fingerprint': 'firefox', 'isDisabled': False,
            'securityLayer': 'DEFAULT',
        }))
        if not host.get('uuid'):
            fail('Panel did not return host UUID')
        state['host_uuid'] = host['uuid']
        atomic_json(STATE, state)
    print(msg['squad'])
    configure_squad(api, state, locale)
    print('\n' + msg['done'])
    print(f"Profile: {state['profile_uuid']}  Node: {state['node_uuid']}  Host: {state['host_uuid']}")
    print(msg['panel_access'])


if __name__ == '__main__':
    try:
        main()
    except (RuntimeError, subprocess.CalledProcessError, KeyboardInterrupt, OSError, ValueError) as exc:
        print(f'\nInstallation failed / Ошибка установки: {exc}', file=sys.stderr)
        sys.exit(1)
