import os
import random
import time
from telethon.sync import TelegramClient
from telethon.errors import (
    SessionPasswordNeededError,
    PhoneNumberInvalidError,
    FloodWaitError
)
from bs4 import BeautifulSoup
import requests
import re

# Configuration
ACCOUNTS_FILE = "accounts.txt"  # Format: phone:api_id:api_hash:password(optional)
MESSAGE_FILE = "message.txt"
TARGETS_FILE = "targets.txt"  # Can be usernames or chat IDs
PROXY_FILE = "proxies.txt"
SLEEP_BETWEEN_ACCOUNTS = 60  # seconds
MAX_ATTEMPTS = 3
MESSAGE_DELAY = 10  # seconds between messages

def scrape_proxies():
    """Scrape SOCKS5 proxies suitable for Telegram"""
    print("Scraping proxies...")
    proxy_urls = [
        "https://www.proxy-list.download/SOCKS5",
        "https://api.proxyscrape.com/v2/?request=getproxies&protocol=socks5",
        "https://www.socks-proxy.net/"
    ]
    
    proxies = []
    
    for url in proxy_urls:
        try:
            headers = {
                'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36'
            }
            response = requests.get(url, headers=headers)
            
            # Different parsing for different sites
            if "proxy-list.download" in url:
                # CSV format
                for line in response.text.split('\n'):
                    if ':' in line:
                        ip, port = line.strip().split(':')
                        proxies.append(f"socks5://{ip}:{port}")
            elif "proxyscrape.com" in url:
                # Plain text IP:PORT format
                for line in response.text.split('\n'):
                    if ':' in line.strip():
                        ip, port = line.strip().split(':')
                        proxies.append(f"socks5://{ip}:{port}")
            elif "socks-proxy.net" in url:
                # HTML table
                soup = BeautifulSoup(response.text, 'html.parser')
                table = soup.find('table', {'id': 'proxylisttable'})
                if table:
                    rows = table.find_all('tr')[1:11]  # First 10 proxies
                    for row in rows:
                        cols = row.find_all('td')
                        if len(cols) >= 2:
                            ip = cols[0].text.strip()
                            port = cols[1].text.strip()
                            proxies.append(f"socks5://{ip}:{port}")
        except Exception as e:
            print(f"Error scraping proxies from {url}: {e}")
    
    # Save proxies to file
    with open(PROXY_FILE, 'w') as f:
        f.write('\n'.join(proxies))
    
    return proxies

def load_proxies():
    """Load proxies from file or scrape new ones if file doesn't exist"""
    if os.path.exists(PROXY_FILE):
        with open(PROXY_FILE, 'r') as f:
            proxies = [line.strip() for line in f.readlines() if line.strip()]
    else:
        proxies = scrape_proxies()
    return proxies

def load_accounts():
    """Load Telegram accounts from file"""
    if not os.path.exists(ACCOUNTS_FILE):
        raise FileNotFoundError(f"{ACCOUNTS_FILE} not found")
    
    accounts = []
    with open(ACCOUNTS_FILE, 'r') as f:
        for line in f.readlines():
            if line.strip():
                parts = line.strip().split(':')
                if len(parts) >= 3:
                    account = {
                        'phone': parts[0],
                        'api_id': parts[1],
                        'api_hash': parts[2],
                        'password': parts[3] if len(parts) > 3 else None
                    }
                    accounts.append(account)
    return accounts

def load_message():
    """Load message from file"""
    if not os.path.exists(MESSAGE_FILE):
        raise FileNotFoundError(f"{MESSAGE_FILE} not found")
    
    with open(MESSAGE_FILE, 'r') as f:
        message = f.read().strip()
    return message

def load_targets():
    """Load target users/chats from file"""
    if not os.path.exists(TARGETS_FILE):
        raise FileNotFoundError(f"{TARGETS_FILE} not found")
    
    with open(TARGETS_FILE, 'r') as f:
        targets = [line.strip() for line in f.readlines() if line.strip()]
    return targets

async def send_telegram_message(client, target, message):
    """Send message to target user/chat"""
    try:
        # Try to get entity (user or chat)
        entity = await client.get_entity(target)
        
        # Send message
        await client.send_message(entity, message)
        print(f"Message sent to {target}")
        return True
    except ValueError as e:
        print(f"Target {target} not found: {e}")
    except FloodWaitError as e:
        print(f"Flood wait for {target}: {e.seconds} seconds")
        time.sleep(e.seconds + 5)  # Wait the required time plus buffer
        return False
    except Exception as e:
        print(f"Failed to send to {target}: {str(e)}")
    return False

async def process_account(account, proxies, targets, message):
    """Process one Telegram account"""
    phone = account['phone']
    print(f"\nProcessing account: {phone}")
    
    # Select proxy if available
    proxy = None
    if proxies:
        proxy = random.choice(proxies)
        print(f"Using proxy: {proxy}")
    
    # Proxy config for Telethon
    proxy_config = None
    if proxy:
        from telethon.network.connection.tcpabridged import ConnectionTcpAbridged
        proxy_config = {
            'proxy_type': 'socks5',  # (or 'http', 'mtproto')
            'addr': proxy.split('://')[1].split(':')[0],
            'port': int(proxy.split(':')[-1]),
            'rdns': True,
            'username': None,
            'password': None,
        }
    
    client = TelegramClient(
        f"sessions/{phone}",
        account['api_id'],
        account['api_hash'],
        proxy=proxy_config
    )
    
    await client.start(
        phone=phone,
        password=account['password']
    )
    
    successful_sends = 0
    for target in targets:
        attempts = 0
        while attempts < MAX_ATTEMPTS:
            if await send_telegram_message(client, target, message):
                successful_sends += 1
                break
            attempts += 1
            time.sleep(MESSAGE_DELAY)
        
        # Delay between messages
        if successful_sends > 0 and successful_sends < len(targets):
            time.sleep(MESSAGE_DELAY)
    
    print(f"Account {phone} sent {successful_sends}/{len(targets)} messages successfully")
    await client.disconnect()
    return successful_sends

def main():
    # Create sessions directory if not exists
    if not os.path.exists('sessions'):
        os.makedirs('sessions')
    
    # Load data
    accounts = load_accounts()
    message = load_message()
    targets = load_targets()
    proxies = load_proxies()
    
    if not accounts:
        print("No accounts found")
        return
    
    if not targets:
        print("No targets found")
        return
    
    if not message:
        print("No message found")
        return
    
    # Process each account
    for i, account in enumerate(accounts):
        # Run async function
        import asyncio
        successful_sends = asyncio.run(process_account(account, proxies, targets, message))
        
        # Sleep between accounts if not last account
        if i < len(accounts) - 1:
            print(f"Waiting {SLEEP_BETWEEN_ACCOUNTS} seconds before next account...")
            time.sleep(SLEEP_BETWEEN_ACCOUNTS)

if __name__ == "__main__":
    main()