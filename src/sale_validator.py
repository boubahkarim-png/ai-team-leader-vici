#!/usr/bin/env python3.11
"""
Sale Recording Validator
Checks if a sale call recording follows the script.
"""

import pymysql.cursors
import os
import sys
import json
from datetime import datetime
from typing import Dict, List, Optional

DB_CONFIG = {
    'database': os.getenv('VICIDIAL_DB_NAME', 'asterisk'),
    'user': os.getenv('VICIDIAL_DB_USER', 'root'),
    'unix_socket': '/var/run/mysql/mysql.sock',
    'connect_timeout': 5
}

RECORDING_PATHS = [
    '/var/spool/asterisk/monitorDONE/MP3/',
    '/var/spool/asterisk/monitorDONE/',
    '/var/spool/asterisk/monitor/',
]

_log_file = '/var/log/ai-team-leader.log'

def log(msg: str):
    ts = datetime.now().strftime('%Y-%m-%d %H:%M:%S')
    with open(_log_file, 'a') as f:
        f.write(f"{ts} - {msg}\n")

def get_conn():
    return pymysql.connect(cursorclass=pymysql.cursors.DictCursor, **DB_CONFIG)

SCRIPT_RULES = {
    '1001': {
        'name': 'Assurance B2C',
        'steps': {
            'ACCROCHE': {
                'required': ['bonjour', 'je suis'],
                'optional': ['groupe financier', 'industrielle alliance']
            },
            'SEGMENTATION': {
                'required': ['propriétaire'],
                'optional': ['locataire', 'age', '65']
            },
            'PROPOSITION': {
                'required': ['consultation', 'gratuit', 'comparatif'],
                'optional': ['assurance', 'conseiller', 'avantageux']
            },
            'RDV': {
                'required': ['disponible'],
                'optional': ['lundi', 'mardi', 'mercredi', 'jeudi', 'vendredi', 'matin', 'courriel']
            },
            'ENGAGEMENT': {
                'required': [],
                'optional': ['merci', 'compter', 'présence']
            }
        }
    },
    '10003': {
        'name': 'Prospection Combles',
        'steps': {
            'PRESENTATION': {
                'required': ['bonjour', 'avenir home'],
                'optional': ['combles', 'intervention']
            },
            'INTRODUCTION': {
                'required': ['combles', 'technicien'],
                'optional': ['reglette', 'epaisseur', 'isolation']
            },
            'PROPOSITION': {
                'required': ['gratuit', 'pris en charge'],
                'optional': ['fournisseurs', 'energie', '35 cm']
            },
            'CLOSE': {
                'required': ['planning', 'disponible'],
                'optional': ['matin', 'après-midi', 'semaine']
            }
        }
    },
    '10007': {
        'name': 'Prospection Reception Quebec',
        'steps': {
            'ACCROCHE': {
                'required': ['bonjour', 'restaurant'],
                'optional': ['québec', 'reception']
            },
            'PROPOSITION': {
                'required': ['rendez-vous'],
                'optional': ['gratuit', 'visite', 'démonstration']
            },
            'CLOSE': {
                'required': ['disponible'],
                'optional': ['merci', 'confirmation']
            }
        }
    }
}

_whisper_model = None

def get_whisper_model():
    global _whisper_model
    if _whisper_model is None:
        from faster_whisper import WhisperModel
        _whisper_model = WhisperModel("small", device="cpu", compute_type="int8")
    return _whisper_model

def transcribe_file(file_path: str) -> Optional[str]:
    try:
        model = get_whisper_model()
        segments, info = model.transcribe(file_path, language="fr")
        return " ".join([s.text.strip() for s in segments])[:2000]
    except Exception as e:
        log(f"Transcription error: {e}")
        return None

def find_recording(lead_id: int) -> Optional[Dict]:
    conn = get_conn()
    cur = conn.cursor()

    cur.execute("""
        SELECT r.recording_id, r.filename, r.length_in_sec, r.start_time,
               v.campaign_id, v.user, v.lead_id
        FROM recording_log r
        JOIN vicidial_log v ON v.uniqueid = r.vicidial_id
        WHERE v.lead_id = %s
        AND v.status = 'SALE'
        AND r.length_in_sec > 30
        ORDER BY r.start_time DESC
        LIMIT 1
    """, (lead_id,))

    rec = cur.fetchone()
    conn.close()

    if not rec:
        return None

    for path in RECORDING_PATHS:
        for ext in ['.mp3', '.wav', '']:
            full_path = os.path.join(path, rec['filename'] + ext)
            if os.path.exists(full_path):
                rec['file_path'] = full_path
                return rec

    return rec

def validate_sale_recording(lead_id: int) -> Dict:
    result = {
        'lead_id': lead_id,
        'recording': None,
        'transcript': None,
        'script_check': None,
        'verdict': 'UNKNOWN',
        'score': 0
    }

    rec = find_recording(lead_id)
    if not rec:
        result['error'] = 'No sale recording found'
        return result

    result['recording'] = {
        'filename': rec['filename'],
        'duration': rec['length_in_sec'],
        'campaign_id': rec['campaign_id'],
        'agent': rec['user']
    }

    file_path = rec.get('file_path')
    if not file_path:
        result['error'] = 'Recording file not found'
        return result

    transcript = transcribe_file(file_path)
    if not transcript:
        result['error'] = 'Transcription failed'
        return result

    result['transcript'] = transcript[:500]

    campaign_id = rec['campaign_id']
    script_rules = SCRIPT_RULES.get(campaign_id)

    if not script_rules:
        result['script_check'] = {'note': 'No script rules for this campaign'}
        result['verdict'] = 'NO_SCRIPT'
        return result

    script_result = check_script_conformity(transcript, script_rules)
    result['script_check'] = script_result
    result['score'] = script_result['score']
    result['verdict'] = script_result['verdict']

    log(f"Lead {lead_id}: Score {result['score']} - {result['verdict']}")
    return result

def check_script_conformity(transcript: str, script: Dict) -> Dict:
    text = transcript.lower()
    result = {
        'script_name': script['name'],
        'steps': {},
        'score': 0,
        'max_score': 100,
        'missing': [],
        'verdict': 'NON CONFORME'
    }

    step_count = len(script['steps'])
    points_per_step = 100 / step_count

    for step_name, step_rules in script['steps'].items():
        step_result = {
            'required_found': [],
            'required_missing': [],
            'optional_found': [],
            'score': 0
        }

        for kw in step_rules['required']:
            if kw in text:
                step_result['required_found'].append(kw)
            else:
                step_result['required_missing'].append(kw)

        for kw in step_rules.get('optional', []):
            if kw in text:
                step_result['optional_found'].append(kw)

        if len(step_result['required_found']) >= len(step_rules['required']):
            step_result['score'] = points_per_step
        elif len(step_result['required_found']) > 0:
            step_result['score'] = points_per_step / 2

        result['steps'][step_name] = step_result
        result['score'] += step_result['score']

        if step_result['required_missing']:
            result['missing'].extend(step_result['required_missing'])

    if result['score'] >= 80:
        result['verdict'] = 'CONFORME'
    elif result['score'] >= 50:
        result['verdict'] = 'PARTIELLEMENT CONFORME'
    else:
        result['verdict'] = 'NON CONFORME'

    return result

def get_recent_sales(limit: int = 10) -> List[Dict]:
    conn = get_conn()
    cur = conn.cursor()
    cur.execute("""
        SELECT DISTINCT v.lead_id, v.campaign_id, v.user, v.call_date
        FROM vicidial_log v
        WHERE v.status = 'SALE'
        AND v.call_date >= DATE_SUB(NOW(), INTERVAL 30 DAY)
        ORDER BY v.call_date DESC
        LIMIT %s
    """, (limit,))
    sales = cur.fetchall()
    conn.close()
    return sales

def validate_recent_sales():
    log("=== Validating recent sale recordings ===")
    sales = get_recent_sales(10)
    log(f"Found {len(sales)} recent sales")

    results = []
    for sale in sales:
        result = validate_sale_recording(sale['lead_id'])
        results.append(result)

        if result['verdict'] not in ['CONFORME', 'NO_SCRIPT']:
            log(f"ALERT: Lead {sale['lead_id']} - {result['verdict']} (Score: {result['score']})")

    return results

if __name__ == '__main__':
    if len(sys.argv) > 1:
        if sys.argv[1] == '--lead' and len(sys.argv) > 2:
            lead_id = int(sys.argv[2])
            result = validate_sale_recording(lead_id)
            print(json.dumps(result, indent=2, ensure_ascii=False, default=str))
        elif sys.argv[1] == '--recent':
            results = validate_recent_sales()
            print(json.dumps(results, indent=2, ensure_ascii=False, default=str))
    else:
        results = validate_recent_sales()
        for r in results:
            print(f"Lead {r['lead_id']}: {r['verdict']} ({r.get('score', 0):.0f}%)")
