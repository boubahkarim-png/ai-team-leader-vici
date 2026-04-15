#!/usr/bin/env python3.11
"""
AI Team Leader - Lightweight ViciBox Supervisor
Runs on-demand via cron, minimal resource usage.
"""

import mysql.connector
import requests
import os
import sys
import resource
from datetime import datetime
from typing import Dict, List, Optional

DB_CONFIG = {
    'host': os.getenv('VICIDIAL_DB_HOST', 'localhost'),
    'database': os.getenv('VICIDIAL_DB_NAME', 'asterisk'),
    'user': os.getenv('VICIDIAL_DB_USER', 'root'),
    'password': os.getenv('VICIDIAL_DB_PASS', 'Mypass123')
}

NVIDIA_API_KEY = os.getenv('NVIDIA_API_KEY', '')
NVIDIA_API_URL = 'https://integrate.api.nvidia.com/v1'
NVIDIA_MODEL = 'z-ai/glm5'

SUPERVISOR_USER = os.getenv('SUPERVISOR_USER', '6666')
ACTIVE_CAMPAIGNS = os.getenv('ACTIVE_CAMPAIGNS', '2002,1007,2000,2001').split(',')
IDLE_THRESHOLD = int(os.getenv('IDLE_ALERT_MINUTES', '5'))
HOPPER_LOW = int(os.getenv('HOPPER_LOW_THRESHOLD', '20'))
MAX_RUNTIME = int(os.getenv('MAX_RUN_TIME_SECONDS', '30'))

_log_file = '/var/log/ai-team-leader.log'

def log(msg: str):
    ts = datetime.now().strftime('%Y-%m-%d %H:%M:%S')
    with open(_log_file, 'a') as f:
        f.write(f"{ts} - {msg}\n")

def check_resources() -> bool:
    """Return False if resources are too high."""
    try:
        usage = resource.getrusage(resource.RUSAGE_SELF)
        mem_mb = usage.ru_maxrss / 1024
        if mem_mb > 500:
            log(f"WARNING: Memory usage {mem_mb:.1f}MB exceeds limit")
            return False
    except:
        pass
    return True

def get_conn():
    return mysql.connector.connect(**DB_CONFIG, connection_timeout=5)

def get_idle_agents() -> List[Dict]:
    """Get agents idle longer than threshold."""
    conn = get_conn()
    cur = conn.cursor(dictionary=True)
    cur.execute(f"""
        SELECT user, status, campaign_id,
               TIMESTAMPDIFF(MINUTE, last_update_time, NOW()) as idle_mins
        FROM vicidial_live_agents
        WHERE campaign_id IN ({','.join(['%s']*len(ACTIVE_CAMPAIGNS))})
        AND status IN ('READY','PAUSED')
        AND TIMESTAMPDIFF(MINUTE, last_update_time, NOW()) >= %s
    """, ACTIVE_CAMPAIGNS + [IDLE_THRESHOLD])
    agents = cur.fetchall()
    conn.close()
    return agents

def get_hopper() -> Dict[str, int]:
    """Get hopper counts."""
    conn = get_conn()
    cur = conn.cursor(dictionary=True)
    cur.execute(f"""
        SELECT campaign_id, COUNT(*) as cnt
        FROM vicidial_hopper
        WHERE campaign_id IN ({','.join(['%s']*len(ACTIVE_CAMPAIGNS))})
        AND status='READY'
        GROUP BY campaign_id
    """, ACTIVE_CAMPAIGNS)
    result = {r['campaign_id']: r['cnt'] for r in cur.fetchall()}
    conn.close()
    return result

def get_unread_messages() -> List[Dict]:
    """Get unread agent messages."""
    conn = get_conn()
    cur = conn.cursor(dictionary=True)
    cur.execute("""
        SELECT m.manager_chat_message_id, m.manager_chat_id,
               m.user, m.message
        FROM vicidial_manager_chat_log m
        JOIN vicidial_manager_chats c ON m.manager_chat_id = c.manager_chat_id
        WHERE m.message_viewed_date IS NULL
        AND m.user != %s
        AND m.message_posted_by = 'AGENT'
        ORDER BY m.message_date ASC LIMIT 10
    """, (SUPERVISOR_USER,))
    msgs = cur.fetchall()
    conn.close()
    return msgs

def send_chat(chat_id: int, user: str, msg: str) -> bool:
    """Send message to agent."""
    conn = get_conn()
    cur = conn.cursor()
    try:
        cur.execute("""
            INSERT INTO vicidial_manager_chat_log
            (manager_chat_id, manager, user, message, message_date, message_posted_by)
            VALUES (%s, %s, %s, %s, NOW(), 'MANAGER')
        """, (chat_id, SUPERVISOR_USER, user, msg))
        conn.commit()
        log(f"Sent to {user}: {msg[:40]}...")
        return True
    except Exception as e:
        log(f"ERROR sending chat: {e}")
        return False
    finally:
        conn.close()

def get_or_create_chat(user: str, camp: str) -> Optional[int]:
    """Get or create chat session."""
    conn = get_conn()
    cur = conn.cursor(dictionary=True)
    cur.execute("""
        SELECT manager_chat_id FROM vicidial_manager_chats
        WHERE selected_agents LIKE %s AND manager = %s
        ORDER BY chat_start_date DESC LIMIT 1
    """, (f'%{user}%', SUPERVISOR_USER))
    r = cur.fetchone()
    if r:
        conn.close()
        return r['manager_chat_id']
    try:
        cur.execute("""
            INSERT INTO vicidial_manager_chats
            (internal_chat_type, chat_start_date, manager, selected_agents, selected_campaigns, allow_replies)
            VALUES ('MANAGER', NOW(), %s, %s, %s, 'Y')
        """, (SUPERVISOR_USER, user, camp))
        conn.commit()
        return cur.lastrowid
    except:
        return None
    finally:
        conn.close()

def ai_answer(question: str) -> str:
    """Get AI response from NVIDIA NIM."""
    if not NVIDIA_API_KEY:
        return "I'm here to help. Please be specific."
    
    prompts = {
        'hours': "France: 10h-12h & 14h-20h Paris. Canada: 9h-21h local.",
        'heure': "France: 10h-12h & 14h-20h (Paris).",
        'script': "Check ViciDial admin for campaign scripts.",
        'lead': "Lead info is in your agent screen. What do you need?",
    }
    
    ql = question.lower()
    for k, v in prompts.items():
        if k in ql:
            return v
    
    try:
        r = requests.post(
            f"{NVIDIA_API_URL}/chat/completions",
            headers={"Authorization": f"Bearer {NVIDIA_API_KEY}", "Content-Type": "application/json"},
            json={
                "model": NVIDIA_MODEL,
                "messages": [
                    {"role": "system", "content": "You are a call center supervisor assistant. Be brief."},
                    {"role": "user", "content": question}
                ],
                "max_tokens": 80,
                "temperature": 0.7
            },
            timeout=10
        )
        if r.status_code == 200:
            return r.json()['choices'][0]['message']['content'].strip()[:150]
    except:
        pass
    return "Can you provide more details?"

def mark_read(msg_id: int):
    """Mark message as read."""
    conn = get_conn()
    cur = conn.cursor()
    cur.execute("UPDATE vicidial_manager_chat_log SET message_viewed_date=NOW() WHERE manager_chat_message_id=%s", (msg_id,))
    conn.commit()
    conn.close()

def run_monitor():
    """Main monitoring cycle."""
    log("=== Starting monitoring cycle ===")
    
    if not check_resources():
        log("ABORT: Resources too high")
        return
    
    # Check idle agents
    idle = get_idle_agents()
    for a in idle:
        chat_id = get_or_create_chat(a['user'], a['campaign_id'])
        if chat_id:
            mins = a['idle_mins']
            msg = f"⏰ You've been {a['status']} for {mins}min. Need help?"
            send_chat(chat_id, a['user'], msg)
    
    # Check hopper
    hoppers = get_hopper()
    for camp, cnt in hoppers.items():
        if cnt < HOPPER_LOW:
            log(f"ALERT: Campaign {camp} hopper low: {cnt}")
    
    # Answer questions
    msgs = get_unread_messages()
    for m in msgs:
        answer = ai_answer(m['message'])
        send_chat(m['manager_chat_id'], m['user'], answer)
        mark_read(m['manager_chat_message_id'])
    
    log(f"Done. Idle:{len(idle)} Msgs:{len(msgs)}")

def send_greeting(user: str, campaign: str):
    """Send greeting to new agent."""
    import random
    greetings = [
        f"👋 Welcome {user}! I'm your AI Team Leader.",
        f"Hello {user}! Ready to help you today.",
        f"Hi {user}! Ask me anything about leads or scripts."
    ]
    chat_id = get_or_create_chat(user, campaign)
    if chat_id:
        send_chat(chat_id, user, random.choice(greetings))

if __name__ == '__main__':
    if len(sys.argv) > 1:
        if sys.argv[1] == '--greeting' and len(sys.argv) >= 4:
            send_greeting(sys.argv[2], sys.argv[3])
        elif sys.argv[1] == '--status':
            print(f"Idle agents: {len(get_idle_agents())}")
            print(f"Hopper: {get_hopper()}")
    else:
        run_monitor()
