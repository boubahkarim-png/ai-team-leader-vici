#!/usr/bin/env python3.11
"""
Recording Conformity Checker
Transcribes recordings and checks call structure.
"""

import os
import sys
import json
import pymysql.cursors
from datetime import datetime, timedelta
from typing import Dict, List, Optional, Tuple
import subprocess
import requests

# Database config
DB_CONFIG = {
    'database': os.getenv('VICIDIAL_DB_NAME', 'asterisk'),
    'user': os.getenv('VICIDIAL_DB_USER', 'root'),
    'unix_socket': '/var/run/mysql/mysql.sock',
    'connect_timeout': 5
}

# NVIDIA NIM for AI analysis
NVIDIA_API_KEY = os.getenv('NVIDIA_API_KEY', '')
NVIDIA_API_URL = 'https://integrate.api.nvidia.com/v1'
NVIDIA_MODEL = 'z-ai/glm5'

# Recording paths
RECORDING_PATHS = [
    '/var/spool/asterisk/monitorDONE/',
    '/var/spool/asterisk/monitor/',
]

# Call structure phases (French)
CALL_STRUCTURE = {
    'greeting': ['bonjour', 'bonsoir', 'hello', 'allo', 'bonjour madame', 'bonjour monsieur'],
    'identification': ['entreprise', 'société', 'nom', 'appelle', 'ici'],
    'pitch': ['offre', 'propose', 'service', 'produit', 'spécial', 'opportunité', 'avantage'],
    'handling': ['question', 'compris', 'effectivement', 'certainement', 'bien sûr'],
    'closing': ['merci', 'au revoir', 'bonne journée', 'à bientôt', 'cordialement']
}

# Campaign-specific rules
CAMPAIGN_RULES = {
    '2002': {  # Home_energie_combles
        'name': 'Home Énergie Combles',
        'required_keywords': ['isolation', 'combles', 'énergie', 'économies', 'prime'],
        'min_duration': 60,
        'max_duration': 600,
    },
    '1007': {  # Prospection_reception_quebec
        'name': 'Prospection Réception Québec',
        'required_keywords': ['rendez-vous', 'réception', 'québec', 'restaurant'],
        'min_duration': 30,
        'max_duration': 300,
    },
    '2000': {  # Assur_fatma
        'name': 'Assurance Fatma',
        'required_keywords': ['assurance', 'devis', 'couverture', 'tarif'],
        'min_duration': 90,
        'max_duration': 480,
    },
    '2001': {  # Assu_Alexandre
        'name': 'Assurance Alexandre',
        'required_keywords': ['assurance', 'devis', 'couverture', 'protection'],
        'min_duration': 90,
        'max_duration': 480,
    },
}

_log_file = '/var/log/ai-team-leader.log'

def log(msg: str):
    ts = datetime.now().strftime('%Y-%m-%d %H:%M:%S')
    with open(_log_file, 'a') as f:
        f.write(f"{ts} - {msg}\n")

def get_conn():
    return pymysql.connect(cursorclass=pymysql.cursors.DictCursor, **DB_CONFIG)

def get_unchecked_recordings(limit: int = 10) -> List[Dict]:
    """Get recent recordings that haven't been checked."""
    conn = get_conn()
    cur = conn.cursor()
    
    # Get recordings from last 24h with valid length
    cur.execute("""
        SELECT r.recording_id, r.filename, r.location, r.lead_id, r.user,
               r.vicidial_id, r.length_in_sec, r.start_time
        FROM recording_log r
        JOIN vicidial_log v ON v.uniqueid = r.vicidial_id
        WHERE r.start_time >= DATE_SUB(NOW(), INTERVAL 24 HOUR)
        AND r.length_in_sec > 30
        AND v.campaign_id IN ('2002', '1007', '2000', '2001')
        ORDER BY r.start_time DESC
        LIMIT %s
    """, (limit,))
    
    recordings = cur.fetchall()
    conn.close()
    return recordings

def find_recording_file(filename: str) -> Optional[str]:
    """Find the actual recording file."""
    for path in RECORDING_PATHS:
        # Try different extensions
        for ext in ['.wav', '.mp3', '.gsm', '']:
            full_path = os.path.join(path, filename + ext)
            if os.path.exists(full_path):
                return full_path
            # Check subdirs (YYYYMMDD format)
            if len(filename) >= 8:
                date_dir = filename[:8]
                full_path = os.path.join(path, date_dir, filename + ext)
                if os.path.exists(full_path):
                    return full_path
    return None

_whisper_model = None

def get_whisper_model():
    """Lazy load Whisper model."""
    global _whisper_model
    if _whisper_model is None:
        from faster_whisper import WhisperModel
        _whisper_model = WhisperModel("small", device="cpu", compute_type="int8")
    return _whisper_model

def transcribe_recording(file_path: str) -> Optional[str]:
    """Transcribe audio file using faster-whisper."""
    try:
        model = get_whisper_model()
        segments, info = model.transcribe(file_path, language="fr")

        transcript_parts = []
        for segment in segments:
            transcript_parts.append(segment.text.strip())

        transcript = " ".join(transcript_parts)
        log(f"Transcribed {file_path}: {len(transcript)} chars")
        return transcript[:2000]

    except Exception as e:
        log(f"Transcription error: {e}")
        return None
        
    except subprocess.TimeoutExpired:
        log(f"Transcription timeout: {file_path}")
        return None
    except Exception as e:
        log(f"Transcription error: {e}")
        return None

def check_call_structure(transcript: str) -> Dict:
    """Check if call follows proper structure."""
    text_lower = transcript.lower()
    
    result = {
        'phases_found': {},
        'score': 0,
        'missing': [],
        'feedback': []
    }
    
    # Check each phase
    for phase, keywords in CALL_STRUCTURE.items():
        found = [kw for kw in keywords if kw in text_lower]
        result['phases_found'][phase] = {
            'found': len(found) > 0,
            'keywords_matched': found
        }
        if found:
            result['score'] += 20  # 5 phases x 20 = 100 max
    
    # Identify missing phases
    for phase, data in result['phases_found'].items():
        if not data['found']:
            result['missing'].append(phase)
    
    # Generate feedback
    if result['missing']:
        result['feedback'].append(f"Missing phases: {', '.join(result['missing'])}")
    
    return result

def check_campaign_keywords(transcript: str, campaign_id: str) -> Dict:
    """Check campaign-specific keywords."""
    text_lower = transcript.lower()
    
    if campaign_id not in CAMPAIGN_RULES:
        return {'applicable': False}
    
    rules = CAMPAIGN_RULES[campaign_id]
    found_keywords = [kw for kw in rules['required_keywords'] if kw in text_lower]
    
    return {
        'applicable': True,
        'campaign_name': rules['name'],
        'keywords_found': found_keywords,
        'keywords_missing': [kw for kw in rules['required_keywords'] if kw not in found_keywords],
        'keyword_score': len(found_keywords) / len(rules['required_keywords']) * 100
    }

def ai_analyze_call(transcript: str, campaign_id: str) -> Optional[Dict]:
    """Use AI to analyze call quality and conformity."""
    if not NVIDIA_API_KEY:
        return None
    
    campaign_name = CAMPAIGN_RULES.get(campaign_id, {}).get('name', 'Unknown')
    
    prompt = f"""Analyse cet appel téléphonique pour un call center.

Campagne: {campaign_name}
Transcription: {transcript[:1000]}

Évalue:
1. Structure de l'appel (salutation → présentation → argumentation → conclusion)
2. Tono professionnel
3. Clarté du message
4. Points à améliorer

Réponds en JSON avec: {{"score": 0-100, "structure": "ok/partial/missing", "tone": "professional/neutral/unprofessional", "clarity": "clear/unclear", "improvements": ["point1", "point2"]}}"""

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
                    {"role": "system", "content": "Tu es un superviseur de call center expert. Réponds uniquement en JSON."},
                    {"role": "user", "content": prompt}
                ],
                "max_tokens": 500,
                "temperature": 0.3
            },
            timeout=30
        )
        
        if r.status_code == 200:
            content = r.json()['choices'][0]['message']['content']
            # Try to extract JSON
            import re
            json_match = re.search(r'\{.*\}', content, re.DOTALL)
            if json_match:
                return json.loads(json_match.group())
    except Exception as e:
        log(f"AI analysis error: {e}")
    
    return None

def save_conformity_result(recording_id: int, user: str, result: Dict):
    """Save conformity check result."""
    conn = get_conn()
    cur = conn.cursor()
    
    try:
        # Create table if not exists
        cur.execute("""
            CREATE TABLE IF NOT EXISTS recording_conformity (
                id INT AUTO_INCREMENT PRIMARY KEY,
                recording_id INT,
                user VARCHAR(20),
                structure_score INT,
                keyword_score DECIMAL(5,2),
                ai_score INT,
                feedback TEXT,
                checked_at DATETIME DEFAULT CURRENT_TIMESTAMP,
                INDEX idx_recording (recording_id),
                INDEX idx_user (user)
            )
        """)
        
        cur.execute("""
            INSERT INTO recording_conformity 
            (recording_id, user, structure_score, keyword_score, ai_score, feedback)
            VALUES (%s, %s, %s, %s, %s, %s)
        """, (
            recording_id,
            user,
            result.get('structure_score', 0),
            result.get('keyword_score', 0),
            result.get('ai_score', 0),
            json.dumps(result.get('feedback', []))
        ))
        conn.commit()
    except Exception as e:
        log(f"Error saving conformity: {e}")
    finally:
        conn.close()

def check_recording_conformity(recording: Dict) -> Dict:
    """Full conformity check for a recording."""
    result = {
        'recording_id': recording['recording_id'],
        'user': recording['user'],
        'filename': recording['filename'],
        'duration': recording['length_in_sec'],
        'transcript': None,
        'structure': None,
        'keywords': None,
        'ai_analysis': None,
        'overall_score': 0,
        'passed': False
    }
    
    # Find and transcribe recording
    file_path = find_recording_file(recording['filename'])
    if not file_path:
        result['error'] = 'Recording file not found'
        return result
    
    log(f"Transcribing: {recording['filename']}")
    transcript = transcribe_recording(file_path)
    if not transcript:
        result['error'] = 'Transcription failed'
        return result
    
    result['transcript'] = transcript[:500]  # Store first 500 chars
    
    # Get campaign from vicidial_log
    conn = get_conn()
    cur = conn.cursor()
    cur.execute("SELECT campaign_id FROM vicidial_log WHERE uniqueid = %s", (recording['vicidial_id'],))
    row = cur.fetchone()
    campaign_id = row['campaign_id'] if row else None
    conn.close()
    
    # Check call structure
    result['structure'] = check_call_structure(transcript)
    
    # Check campaign keywords
    if campaign_id:
        result['keywords'] = check_campaign_keywords(transcript, campaign_id)
    
    # AI analysis
    if campaign_id:
        result['ai_analysis'] = ai_analyze_call(transcript, campaign_id)
    
    # Calculate overall score
    scores = []
    if result['structure']:
        scores.append(result['structure']['score'])
    if result['keywords'] and result['keywords'].get('applicable'):
        scores.append(result['keywords']['keyword_score'])
    if result['ai_analysis'] and 'score' in result['ai_analysis']:
        scores.append(result['ai_analysis']['score'])
    
    if scores:
        result['overall_score'] = sum(scores) / len(scores)
        result['passed'] = result['overall_score'] >= 60
    
    # Save result
    save_conformity_result(
        recording['recording_id'],
        recording['user'],
        result
    )
    
    return result

def run_conformity_check(limit: int = 10):
    """Run conformity check on recent recordings."""
    log("=== Starting conformity check ===")
    
    recordings = get_unchecked_recordings(limit)
    log(f"Found {len(recordings)} recordings to check")
    
    results = []
    for rec in recordings:
        try:
            result = check_recording_conformity(rec)
            results.append(result)
            
            # Notify agent if conformity failed
            if not result.get('passed', False):
                log(f"FAIL: {rec['user']} - Score: {result['overall_score']:.0f}%")
        except Exception as e:
            log(f"Error checking {rec['recording_id']}: {e}")
    
    # Summary
    passed = sum(1 for r in results if r.get('passed', False))
    failed = len(results) - passed
    log(f"Conformity check done. Passed: {passed}, Failed: {failed}")
    
    return results

if __name__ == '__main__':
    if len(sys.argv) > 1:
        if sys.argv[1] == '--test':
            # Test with one recording
            recordings = get_unchecked_recordings(1)
            if recordings:
                result = check_recording_conformity(recordings[0])
                print(json.dumps(result, indent=2, ensure_ascii=False))
        elif sys.argv[1] == '--run':
            limit = int(sys.argv[2]) if len(sys.argv) > 2 else 10
            run_conformity_check(limit)
    else:
        run_conformity_check(5)
