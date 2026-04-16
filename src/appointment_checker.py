#!/usr/bin/env python3.11
"""
AI Supervisor - Appointment Checker
Checks upcoming callbacks/appointments and verifies status.
"""

import pymysql.cursors
import os
import sys
import requests
from datetime import datetime, timedelta
from typing import Dict, List, Optional

DB_CONFIG = {
    'database': os.getenv('VICIDIAL_DB_NAME', 'asterisk'),
    'user': os.getenv('VICIDIAL_DB_USER', 'root'),
    'unix_socket': '/var/run/mysql/mysql.sock',
    'connect_timeout': 5
}

NVIDIA_API_KEY = os.getenv('NVIDIA_API_KEY', '')
NVIDIA_API_URL = 'https://integrate.api.nvidia.com/v1'
NVIDIA_MODEL = 'z-ai/glm5'

SUPERVISOR_USER = os.getenv('SUPERVISOR_USER', '6666')

_log_file = '/var/log/ai-team-leader.log'

def log(msg: str):
    ts = datetime.now().strftime('%Y-%m-%d %H:%M:%S')
    with open(_log_file, 'a') as f:
        f.write(f"{ts} - {msg}\n")

def get_conn():
    return pymysql.connect(cursorclass=pymysql.cursors.DictCursor, **DB_CONFIG)

def get_upcoming_callbacks(hours_ahead: int = 24) -> List[Dict]:
    """Get callbacks scheduled in the next N hours."""
    conn = get_conn()
    cur = conn.cursor()

    cur.execute("""
        SELECT c.callback_id, c.lead_id, c.campaign_id, c.status,
               c.callback_time, c.user, c.recipient, c.comments,
               l.first_name, l.last_name, l.phone_number, l.status as lead_status,
               l.comments as lead_comments
        FROM vicidial_callbacks c
        LEFT JOIN vicidial_list l ON c.lead_id = l.lead_id
        WHERE c.status = 'LIVE'
        AND c.callback_time BETWEEN NOW() AND DATE_ADD(NOW(), INTERVAL %s HOUR)
        ORDER BY c.callback_time ASC
    """, (hours_ahead,))

    callbacks = cur.fetchall()
    conn.close()
    return callbacks

def get_lead_details(lead_id: int) -> Optional[Dict]:
    """Get full lead details."""
    conn = get_conn()
    cur = conn.cursor()
    cur.execute("SELECT * FROM vicidial_list WHERE lead_id = %s", (lead_id,))
    lead = cur.fetchone()
    conn.close()
    return lead

def get_lead_call_history(lead_id: int, limit: int = 5) -> List[Dict]:
    """Get recent call history for a lead."""
    conn = get_conn()
    cur = conn.cursor()
    cur.execute("""
        SELECT uniqueid, call_date, length_in_sec, status, term_reason, user
        FROM vicidial_log
        WHERE lead_id = %s
        ORDER BY call_date DESC
        LIMIT %s
    """, (lead_id, limit))
    calls = cur.fetchall()
    conn.close()
    return calls

def check_appointment_status(callback: Dict) -> Dict:
    """Check if appointment/callback is likely valid."""
    result = {
        'callback_id': callback['callback_id'],
        'lead_id': callback['lead_id'],
        'scheduled_time': callback['callback_time'],
        'campaign_id': callback['campaign_id'],
        'issues': [],
        'score': 100,
        'recommendation': 'PROCEED'
    }

    # Check 1: Lead status
    if callback.get('lead_status') in ['DNC', 'DNCL', 'N']:
        result['issues'].append(f"Lead status is {callback['lead_status']}")
        result['score'] -= 50

    # Check 2: Phone number exists
    if not callback.get('phone_number'):
        result['issues'].append("No phone number")
        result['score'] -= 30

    # Check 3: Callback time reasonable
    callback_time = callback['callback_time']
    if isinstance(callback_time, str):
        callback_time = datetime.strptime(callback_time, '%Y-%m-%d %H:%M:%S')

    now = datetime.now()
    if callback_time < now:
        result['issues'].append("Callback time has passed")
        result['score'] -= 20

    # Check 4: Assigned user
    if callback.get('user') and callback['user'] not in ['ADMIN', 'ANYONE']:
        result['assigned_user'] = callback['user']
    else:
        result['assigned_user'] = 'Unassigned'

    # Check 5: Comments indicate type
    comments = callback.get('comments', '') or ''
    if 'CALLBK' in comments:
        result['type'] = 'Callback'
    elif 'RPerso' in comments:
        result['type'] = 'Rendez-vous personnel'

    # Calculate recommendation
    if result['score'] < 50:
        result['recommendation'] = 'REVIEW_NEEDED'
    elif result['score'] < 70:
        result['recommendation'] = 'PROCEED_WITH_CAUTION'

    return result

def ai_analyze_appointment(callback: Dict) -> Optional[str]:
    """Use AI to analyze appointment and suggest actions."""
    if not NVIDIA_API_KEY:
        return None

    prompt = f"""Analyse ce rendez-vous/callback pour un call center:

Lead: {callback.get('first_name', '')} {callback.get('last_name', '')}
Téléphone: {callback.get('phone_number', '')}
Statut lead: {callback.get('lead_status', 'Unknown')}
Campagne: {callback.get('campaign_id', '')}
Prévu le: {callback.get('callback_time', '')}
Commentaires: {callback.get('lead_comments', '')}

Donne une recommandation courte (1-2 lignes) pour l'agent qui doit rappeler."""

    try:
        r = requests.post(
            f"{NVIDIA_API_URL}/chat/completions",
            headers={
                "Authorization": f"Bearer {NVIDIA_API_KEY}",
                "Content-Type": "application/json"
            },
            json={
                "model": NVIDIA_MODEL,
                "messages": [
                    {"role": "system", "content": "Tu es un superviseur de call center. Réponds de façon concise."},
                    {"role": "user", "content": prompt}
                ],
                "max_tokens": 100,
                "temperature": 0.5
            },
            timeout=15
        )

        if r.status_code == 200:
            return r.json()['choices'][0]['message']['content'].strip()
    except Exception as e:
        log(f"AI analysis error: {e}")

    return None

def send_supervisor_alert(callbacks: List[Dict], issues: List[Dict]):
    """Send alert to supervisor about appointment issues."""
    if not issues:
        return

    conn = get_conn()
    cur = conn.cursor()

    message = f"⚠️ {len(issues)} rendez-vous à vérifier:\n"
    for issue in issues[:5]:
        message += f"- Lead {issue['lead_id']}: {', '.join(issue['issues'])}\n"

    # Send via manager chat (broadcast to supervisor)
    try:
        cur.execute("""
            INSERT INTO vicidial_manager_chat_log
            (manager_chat_id, manager, user, message, message_date, message_posted_by)
            VALUES (0, %s, %s, %s, NOW(), 'MANAGER')
        """, (SUPERVISOR_USER, SUPERVISOR_USER, message[:255]))
        conn.commit()
        log(f"Sent supervisor alert: {len(issues)} issues")
    except Exception as e:
        log(f"Error sending alert: {e}")
    finally:
        conn.close()

def run_appointment_check():
    """Main appointment check cycle."""
    log("=== Checking upcoming appointments ===")

    callbacks = get_upcoming_callbacks(24)
    log(f"Found {len(callbacks)} upcoming callbacks")

    if not callbacks:
        log("No callbacks to check")
        return []

    issues = []
    for cb in callbacks:
        status = check_appointment_status(cb)
        if status['score'] < 70:
            issues.append(status)
            log(f"Issue: Lead {cb['lead_id']} - Score {status['score']} - {status['issues']}")

        # AI analysis for each
        if cb.get('lead_id'):
            ai_rec = ai_analyze_appointment(cb)
            if ai_rec:
                log(f"AI rec for lead {cb['lead_id']}: {ai_rec}")

    # Alert supervisor if issues found
    if issues:
        send_supervisor_alert(callbacks, issues)

    log(f"Appointment check done. {len(issues)} need review")
    return issues

def check_specific_lead(lead_id: int) -> Dict:
    """Check a specific lead's appointment status."""
    lead = get_lead_details(lead_id)
    if not lead:
        return {'error': 'Lead not found', 'lead_id': lead_id}

    calls = get_lead_call_history(lead_id)
    callbacks = []

    conn = get_conn()
    cur = conn.cursor()
    cur.execute("""
        SELECT * FROM vicidial_callbacks
        WHERE lead_id = %s AND status = 'LIVE'
        ORDER BY callback_time ASC
    """, (lead_id,))
    callbacks = cur.fetchall()
    conn.close()

    result = {
        'lead_id': lead_id,
        'lead': lead,
        'calls': calls,
        'callbacks': callbacks,
        'has_appointment': len(callbacks) > 0,
        'appointment_status': None
    }

    if callbacks:
        result['appointment_status'] = check_appointment_status(callbacks[0])

    return result

if __name__ == '__main__':
    if len(sys.argv) > 1:
        if sys.argv[1] == '--lead' and len(sys.argv) > 2:
            lead_id = int(sys.argv[2])
            import json
            result = check_specific_lead(lead_id)
            print(json.dumps(result, indent=2, default=str, ensure_ascii=False))
        elif sys.argv[1] == '--check':
            run_appointment_check()
    else:
        run_appointment_check()
