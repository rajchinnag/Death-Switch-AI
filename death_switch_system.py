#!/usr/bin/env python3
"""
Digital Death Switch AI - Life-Trigger Automation System
A personal automation system that activates when user is presumed inactive/dead
"""

import json
import os
import time
import hashlib
import secrets
import smtplib
import requests
from datetime import datetime, timedelta
from email.mime.text import MimeText
from email.mime.multipart import MimeMultipart
from email.mime.base import MimeBase
from email import encoders
import sqlite3
import logging
from typing import List, Dict, Optional
from dataclasses import dataclass
import schedule
import threading

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s',
    handlers=[
        logging.FileHandler('death_switch.log'),
        logging.StreamHandler()
    ]
)
logger = logging.getLogger(__name__)

@dataclass
class Recipient:
    """Data class for document recipients"""
    name: str
    phone: str
    whatsapp: str
    email: str
    preferred_language: str = 'english'  # Default language

@dataclass
class Document:
    """Data class for important documents"""
    name: str
    file_path: str
    cloud_url: str
    description: str

class SecurityManager:
    """Handles all security operations including OTP generation and kill switch"""
    
    def __init__(self):
        self.otp_expiry_minutes = 30
    
    def generate_otp(self) -> str:
        """Generate a 6-digit OTP"""
        return f"{secrets.randbelow(1000000):06d}"
    
    def hash_kill_switch(self, kill_code: str) -> str:
        """Hash the kill switch code for secure storage"""
        salt = secrets.token_hex(16)
        return hashlib.pbkdf2_hmac('sha256', kill_code.encode(), salt.encode(), 100000).hex() + ':' + salt
    
    def verify_kill_switch(self, kill_code: str, stored_hash: str) -> bool:
        """Verify kill switch code against stored hash"""
        try:
            hash_part, salt = stored_hash.split(':')
            return hashlib.pbkdf2_hmac('sha256', kill_code.encode(), salt.encode(), 100000).hex() == hash_part
        except:
            return False

class DatabaseManager:
    """Manages SQLite database operations"""
    
    def __init__(self, db_path: str = "death_switch.db"):
        self.db_path = db_path
        self.init_database()
    
    def init_database(self):
        """Initialize the database with required tables"""
        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()
        
        # Activity tracking table
        cursor.execute('''
            CREATE TABLE IF NOT EXISTS activity_log (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                timestamp DATETIME DEFAULT CURRENT_TIMESTAMP,
                activity_type TEXT NOT NULL,
                device_id TEXT,
                notes TEXT
            )
        ''')
        
        # OTP tracking table
        cursor.execute('''
            CREATE TABLE IF NOT EXISTS otp_log (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                otp_code TEXT NOT NULL,
                generated_at DATETIME DEFAULT CURRENT_TIMESTAMP,
                expires_at DATETIME NOT NULL,
                used BOOLEAN DEFAULT FALSE,
                purpose TEXT
            )
        ''')
        
        # Delivery log table
        cursor.execute('''
            CREATE TABLE IF NOT EXISTS delivery_log (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                recipient_name TEXT NOT NULL,
                delivery_method TEXT NOT NULL,
                status TEXT NOT NULL,
                timestamp DATETIME DEFAULT CURRENT_TIMESTAMP,
                message_id TEXT,
                error_details TEXT
            )
        ''')
        
        # System settings table
        cursor.execute('''
            CREATE TABLE IF NOT EXISTS settings (
                key TEXT PRIMARY KEY,
                value TEXT NOT NULL,
                updated_at DATETIME DEFAULT CURRENT_TIMESTAMP
            )
        ''')
        
        conn.commit()
        conn.close()
    
    def log_activity(self, activity_type: str, device_id: str = None, notes: str = None):
        """Log user activity"""
        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()
        cursor.execute(
            "INSERT INTO activity_log (activity_type, device_id, notes) VALUES (?, ?, ?)",
            (activity_type, device_id, notes)
        )
        conn.commit()
        conn.close()
        logger.info(f"Activity logged: {activity_type}")
    
    def get_last_activity(self) -> Optional[datetime]:
        """Get the timestamp of the last recorded activity"""
        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()
        cursor.execute("SELECT MAX(timestamp) FROM activity_log")
        result = cursor.fetchone()[0]
        conn.close()
        
        if result:
            return datetime.fromisoformat(result)
        return None
    
    def store_otp(self, otp: str, purpose: str, expiry_minutes: int = 30):
        """Store OTP with expiration"""
        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()
        expires_at = datetime.now() + timedelta(minutes=expiry_minutes)
        cursor.execute(
            "INSERT INTO otp_log (otp_code, expires_at, purpose) VALUES (?, ?, ?)",
            (otp, expires_at.isoformat(), purpose)
        )
        conn.commit()
        conn.close()
    
    def verify_otp(self, otp: str, purpose: str) -> bool:
        """Verify OTP and mark as used"""
        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()
        
        cursor.execute('''
            SELECT id FROM otp_log 
            WHERE otp_code = ? AND purpose = ? AND used = FALSE 
            AND expires_at > datetime('now')
        ''', (otp, purpose))
        
        result = cursor.fetchone()
        if result:
            cursor.execute("UPDATE otp_log SET used = TRUE WHERE id = ?", (result[0],))
            conn.commit()
            conn.close()
            return True
        
        conn.close()
        return False

class NotificationManager:
    """Handles email and SMS notifications"""
    
    def __init__(self, config: Dict):
        self.smtp_server = config.get('smtp_server', 'smtp.gmail.com')
        self.smtp_port = config.get('smtp_port', 587)
        self.email = config['email']
        self.email_password = config['email_password']
        self.twilio_sid = config.get('twilio_sid')
        self.twilio_token = config.get('twilio_token')
        self.twilio_phone = config.get('twilio_phone')
    
    def send_email(self, to_email: str, subject: str, body: str, attachments: List[str] = None) -> bool:
        """Send email with optional attachments"""
        try:
            msg = MimeMultipart()
            msg['From'] = self.email
            msg['To'] = to_email
            msg['Subject'] = subject
            
            msg.attach(MimeText(body, 'plain'))
            
            # Add attachments if provided
            if attachments:
                for file_path in attachments:
                    if os.path.exists(file_path):
                        with open(file_path, "rb") as attachment:
                            part = MimeBase('application', 'octet-stream')
                            part.set_payload(attachment.read())
                        
                        encoders.encode_base64(part)
                        part.add_header(
                            'Content-Disposition',
                            f'attachment; filename= {os.path.basename(file_path)}'
                        )
                        msg.attach(part)
            
            server = smtplib.SMTP(self.smtp_server, self.smtp_port)
            server.starttls()
            server.login(self.email, self.email_password)
            text = msg.as_string()
            server.sendmail(self.email, to_email, text)
            server.quit()
            
            logger.info(f"Email sent successfully to {to_email}")
            return True
            
        except Exception as e:
            logger.error(f"Failed to send email to {to_email}: {str(e)}")
            return False
    
    def send_sms(self, phone_number: str, message: str) -> bool:
        """Send SMS using Twilio"""
        if not all([self.twilio_sid, self.twilio_token, self.twilio_phone]):
            logger.warning("Twilio credentials not configured, skipping SMS")
            return False
        
        try:
            from twilio.rest import Client
            client = Client(self.twilio_sid, self.twilio_token)
            
            message = client.messages.create(
                body=message,
                from_=self.twilio_phone,
                to=phone_number
            )
            
            logger.info(f"SMS sent successfully to {phone_number}, SID: {message.sid}")
            return True
            
        except Exception as e:
            logger.error(f"Failed to send SMS to {phone_number}: {str(e)}")
            return False

class DeathSwitchAI:
    """Main Death Switch AI system"""
    
    def __init__(self, config_file: str = "config.json"):
        self.load_config(config_file)
        self.db = DatabaseManager()
        self.security = SecurityManager()
        self.notifications = NotificationManager(self.config)
        self.is_running = True
        self.trigger_activated = False
        
        # Default settings
        self.inactivity_days = self.config.get('inactivity_days', 10)
        self.verification_hours = self.config.get('verification_hours', 48)
    
    def load_config(self, config_file: str):
        """Load configuration from JSON file"""
        try:
            with open(config_file, 'r') as f:
                self.config = json.load(f)
            
            # Validate required config
            required_keys = ['email', 'email_password', 'recipients', 'documents']
            for key in required_keys:
                if key not in self.config:
                    raise ValueError(f"Missing required config key: {key}")
            
            # Load recipients
            self.recipients = [Recipient(**r) for r in self.config['recipients']]
            self.documents = [Document(**d) for d in self.config['documents']]
            
        except FileNotFoundError:
            logger.error(f"Config file {config_file} not found")
            self.create_sample_config(config_file)
            raise
        
        except Exception as e:
            logger.error(f"Failed to load config: {str(e)}")
            raise
    
    def create_sample_config(self, config_file: str):
        """Create a sample configuration file"""
        sample_config = {
            "email": "your_email@gmail.com",
            "email_password": "your_app_password",
            "smtp_server": "smtp.gmail.com",
            "smtp_port": 587,
            "twilio_sid": "your_twilio_sid",
            "twilio_token": "your_twilio_token",
            "twilio_phone": "+1234567890",
            "inactivity_days": 10,
            "verification_hours": 48,
            "kill_switch_hash": "",
            "recipients": [
                {
                    "name": "John Doe",
                    "phone": "+1234567890",
                    "whatsapp": "+1234567890",
                    "email": "john@example.com",
                    "preferred_language": "english"
                },
                {
                    "name": "Jane Smith", 
                    "phone": "+9876543210",
                    "whatsapp": "+9876543210",
                    "email": "jane@example.com",
                    "preferred_language": "hindi"
                }
            ],
            "documents": [
                {
                    "name": "Insurance Policy",
                    "file_path": "/path/to/insurance.pdf",
                    "cloud_url": "https://drive.google.com/file/d/xyz",
                    "description": "Life insurance policy documents"
                }
            ]
        }
        
        with open(config_file, 'w') as f:
            json.dump(sample_config, f, indent=2)
        
        logger.info(f"Sample config created at {config_file}")
    
    def record_activity(self, activity_type: str = "app_usage", device_id: str = None):
        """Record user activity to reset the death timer"""
        self.db.log_activity(activity_type, device_id)
        logger.info("User activity recorded - death timer reset")
    
    def check_inactivity(self) -> bool:
        """Check if user has been inactive for the configured period"""
        last_activity = self.db.get_last_activity()
        
        if not last_activity:
            logger.warning("No previous activity found - considering as first run")
            self.record_activity("first_run")
            return False
        
        days_inactive = (datetime.now() - last_activity).days
        logger.info(f"Days since last activity: {days_inactive}")
        
        return days_inactive >= self.inactivity_days
    
    def send_life_verification(self) -> str:
        """Send OTP for life verification"""
        otp = self.security.generate_otp()
        self.db.store_otp(otp, "life_verification", expiry_minutes=60)
        
        subject = "🚨 Digital Death Switch - Life Verification Required"
        body = f"""
URGENT: Your Digital Death Switch has been triggered due to {self.inactivity_days} days of inactivity.

If you are alive and well, please enter this verification code in your app within 1 hour:

VERIFICATION CODE: {otp}

If this was triggered in error, you can also use your kill switch code to permanently disable the system.

If you do not respond within {self.verification_hours} hours, your emergency documents will be automatically sent to your designated recipients.

This is an automated message from your Digital Death Switch AI system.
        """
        
        # Send to user's email
        success = self.notifications.send_email(self.config['email'], subject, body)
        
        if success:
            logger.info("Life verification OTP sent successfully")
        else:
            logger.error("Failed to send life verification OTP")
        
        return otp
    
    def verify_life_response(self, user_input: str) -> bool:
        """Verify user's life confirmation (OTP or kill switch)"""
        # Check if it's a valid OTP
        if self.db.verify_otp(user_input, "life_verification"):
            logger.info("Life verification successful via OTP")
            self.record_activity("life_verified")
            return True
        
        # Check if it's the kill switch
        kill_switch_hash = self.config.get('kill_switch_hash', '')
        if kill_switch_hash and self.security.verify_kill_switch(user_input, kill_switch_hash):
            logger.info("Kill switch activated - system disabled")
            self.is_running = False
            return True
        
        logger.warning("Invalid verification code or kill switch")
        return False
    
    def create_secure_document_viewer(self, document: Document, recipient: Recipient) -> str:
        """Create a secure HTML viewer for document access"""
        viewer_otp = self.security.generate_otp()
        self.db.store_otp(viewer_otp, f"document_access_{recipient.name}", expiry_minutes=1440)  # 24 hours
        
        html_content = f"""
<!DOCTYPE html>
<html>
<head>
    <title>Secure Document Access - {document.name}</title>
    <style>
        body {{ font-family: Arial, sans-serif; max-width: 600px; margin: 50px auto; padding: 20px; }}
        .security-notice {{ background: #fff3cd; border: 1px solid #ffeeba; padding: 15px; margin: 20px 0; }}
        .document-info {{ background: #f8f9fa; padding: 15px; margin: 20px 0; }}
        input {{ padding: 10px; width: 200px; margin: 10px 0; }}
        button {{ padding: 10px 20px; background: #007bff; color: white; border: none; cursor: pointer; }}
    </style>
</head>
<body>
    <h2>🔒 Secure Document Access</h2>
    
    <div class="security-notice">
        <strong>IMPORTANT:</strong> This document was automatically sent by the Digital Death Switch AI system.
        Access requires OTP verification sent to your registered contact methods.
    </div>
    
    <div class="document-info">
        <h3>{document.name}</h3>
        <p><strong>Description:</strong> {document.description}</p>
        <p><strong>Intended for:</strong> {recipient.name}</p>
        <p><strong>Generated:</strong> {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}</p>
    </div>
    
    <div id="access-form">
        <h4>Enter Access Code:</h4>
        <input type="password" id="otp-input" placeholder="Enter 6-digit access code">
        <button onclick="verifyAccess()">Access Document</button>
        <p><small>Access code: {viewer_otp} (This would normally be sent separately)</small></p>
    </div>
    
    <div id="document-content" style="display: none;">
        <h4>Document Access Granted</h4>
        <p><a href="{document.cloud_url}" target="_blank">Click here to access: {document.name}</a></p>
    </div>
    
    <script>
        function verifyAccess() {{
            const input = document.getElementById('otp-input').value;
            if (input === '{viewer_otp}') {{
                document.getElementById('access-form').style.display = 'none';
                document.getElementById('document-content').style.display = 'block';
            }} else {{
                alert('Invalid access code. Please check your email/SMS for the correct code.');
            }}
        }}
    </script>
</body>
</html>
        """
        
        # Save HTML file
        filename = f"secure_access_{recipient.name.replace(' ', '_')}_{int(time.time())}.html"
        with open(filename, 'w') as f:
            f.write(html_content)
        
        return filename
    
    def get_message_in_language(self, language: str, recipient_name: str) -> dict:
        """Get personalized message in specified language"""
        messages = {
            'english': {
                'subject': '💙 Important Documents - A Final Gift of Security',
                'greeting': f'My dear {recipient_name},',
                'main_message': 'For your security I have made sure that you are not left in debt or financial stress. Please find the important documents that will secure you financially.',
                'closing': 'Thanks for your love',
                'technical_info': 'The documents are secured and require an access code sent to your phone for your protection.',
                'generated': f'Generated with love: {datetime.now().strftime("%Y-%m-%d %H:%M:%S")}'
            },
            'hindi': {
                'subject': '💙 महत्वपूर्ण दस्तावेज़ - सुरक्षा का अंतिम उपहार',
                'greeting': f'मेरे प्रिय {recipient_name},',
                'main_message': 'आपकी सुरक्षा के लिए मैंने यह सुनिश्चित किया है कि आप कर्ज़ या वित्तीय तनाव में न रहें। कृपया इन महत्वपूर्ण दस्तावेज़ों को देखें जो आपको आर्थिक रूप से सुरक्षित रखेंगे।',
                'closing': 'आपके प्रेम के लिए धन्यवाद',
                'technical_info': 'दस्तावेज़ सुरक्षित हैं और आपकी सुरक्षा के लिए आपके फ़ोन पर भेजे गए एक्सेस कोड की आवश्यकता है।',
                'generated': f'प्रेम के साथ बनाया गया: {datetime.now().strftime("%Y-%m-%d %H:%M:%S")}'
            },
            'telugu': {
                'subject': '💙 ముఖ్యమైన పత్రాలు - భద్రత యొక్క చివరి బహుమతి',
                'greeting': f'నా ప్రియమైన {recipient_name},',
                'main_message': 'మీ భద్రత కోసం నేను మిమ్మల్ని అప్పుల్లో లేదా ఆర్థిక ఒత్తిడిలో వదిలిపెట్టకుండా చూసుకున్నాను. దయచేసి మిమ్మల్ని ఆర్థికంగా భద్రపరిచే ఈ ముఖ్యమైన పత్రాలను చూడండి.',
                'closing': 'మీ ప్రేమకు ధన్యవాదాలు',
                'technical_info': 'పత్రాలు భద్రంగా ఉన్నాయి మరియు మీ రక్షణ కోసం మీ ఫోన్‌కు పంపిన యాక్సెస్ కోడ్ అవసరం.',
                'generated': f'ప్రేమతో సృష్టించబడింది: {datetime.now().strftime("%Y-%m-%d %H:%M:%S")}'
            },
            'tamil': {
                'subject': '💙 முக்கிய ஆவணங்கள் - பாதுகாப்பின் இறுதி பரிசு',
                'greeting': f'என் அன்பான {recipient_name},',
                'main_message': 'உங்கள் பாதுகாப்பிற்காக நான் உங்களை கடன் அல்லது நிதி அழுத்தத்தில் விடாமல் பார்த்துக்கொண்டேன். உங்களை நிதி ரீதியாக பாதுகாக்கும் இந்த முக்கியமான ஆவணங்களைப் பார்க்கவும்.',
                'closing': 'உங்கள் அன்பிற்கு நன்றி',
                'technical_info': 'ஆவணங்கள் பாதுகாக்கப்பட்டுள்ளன மற்றும் உங்கள் பாதுகாப்பிற்காக உங்கள் தொலைபேசிக்கு அனுப்பப்பட்ட அணுகல் குறியீடு தேவை.',
                'generated': f'அன்புடன் உருவாக்கப்பட்டது: {datetime.now().strftime("%Y-%m-%d %H:%M:%S")}'
            },
            'kannada': {
                'subject': '💙 ಪ್ರಮುಖ ದಾಖಲೆಗಳು - ಭದ್ರತೆಯ ಅಂತಿಮ ಉಡುಗೊರೆ',
                'greeting': f'ನನ್ನ ಪ್ರಿಯ {recipient_name},',
                'main_message': 'ನಿಮ್ಮ ಭದ್ರತೆಗಾಗಿ ನಾನು ನಿಮ್ಮನ್ನು ಸಾಲ ಅಥವಾ ಆರ್ಥಿಕ ಒತ್ತಡದಲ್ಲಿ ಬಿಡದಂತೆ ನೋಡಿಕೊಂಡಿದ್ದೇನೆ. ದಯವಿಟ್ಟು ನಿಮ್ಮನ್ನು ಆರ್ಥಿಕವಾಗಿ ಭದ್ರಪಡಿಸುವ ಈ ಪ್ರಮುಖ ದಾಖಲೆಗಳನ್ನು ನೋಡಿ.',
                'closing': 'ನಿಮ್ಮ ಪ್ರೀತಿಗೆ ಧನ್ಯವಾದಗಳು',
                'technical_info': 'ದಾಖಲೆಗಳು ಭದ್ರವಾಗಿವೆ ಮತ್ತು ನಿಮ್ಮ ರಕ್ಷಣೆಗಾಗಿ ನಿಮ್ಮ ಫೋನ್‌ಗೆ ಕಳುಹಿಸಲಾದ ಪ್ರವೇಶ ಕೋಡ್ ಅಗತ್ಯವಿದೆ.',
                'generated': f'ಪ್ರೀತಿಯಿಂದ ರಚಿಸಲಾಗಿದೆ: {datetime.now().strftime("%Y-%m-%d %H:%M:%S")}'
            },
            'malayalam': {
                'subject': '💙 പ്രധാന രേഖകൾ - സുരക്ഷയുടെ അന്തിമ സമ്മാനം',
                'greeting': f'എന്റെ പ്രിയ {recipient_name},',
                'main_message': 'നിങ്ങളുടെ സുരക്ഷയ്ക്കായി നിങ്ങളെ കടബാധ്യതയിലോ സാമ്പത്തിക സമ്മർദ്ദത്തിലോ വിടാതിരിക്കാൻ ഞാൻ ശ്രദ്ധിച്ചിട്ടുണ്ട്. നിങ്ങളെ സാമ്പത്തികമായി സുരക്ഷിതമാക്കുന്ന ഈ പ്രധാന രേഖകൾ കാണുക.',
                'closing': 'നിങ്ങളുടെ സ്നേഹത്തിനു നന്ദി',
                'technical_info': 'രേഖകൾ സുരക്ഷിതമാണ്, നിങ്ങളുടെ സംരക്ഷണത്തിനായി നിങ്ങളുടെ ഫോണിലേക്ക് അയച്ച ആക്സസ് കോഡ് ആവശ്യമാണ്.',
                'generated': f'സ്നേഹത്തോടെ സൃഷ്ടിച്ചത്: {datetime.now().strftime("%Y-%m-%d %H:%M:%S")}'
            },
            'spanish': {
                'subject': '💙 Documentos Importantes - Un Regalo Final de Seguridad',
                'greeting': f'Mi querido/a {recipient_name},',
                'main_message': 'Para tu seguridad me he asegurado de que no quedes en deudas o estrés financiero. Por favor encuentra los documentos importantes que te asegurarán financieramente.',
                'closing': 'Gracias por tu amor',
                'technical_info': 'Los documentos están seguros y requieren un código de acceso enviado a tu teléfono para tu protección.',
                'generated': f'Generado con amor: {datetime.now().strftime("%Y-%m-%d %H:%M:%S")}'
            },
            'french': {
                'subject': '💙 Documents Importants - Un Dernier Cadeau de Sécurité',
                'greeting': f'Mon cher/Ma chère {recipient_name},',
                'main_message': 'Pour votre sécurité, j\'ai veillé à ce que vous ne soyez pas laissé dans les dettes ou le stress financier. Veuillez trouver les documents importants qui vous sécuriseront financièrement.',
                'closing': 'Merci pour votre amour',
                'technical_info': 'Les documents sont sécurisés et nécessitent un code d\'accès envoyé à votre téléphone pour votre protection.',
                'generated': f'Généré avec amour: {datetime.now().strftime("%Y-%m-%d %H:%M:%S")}'
            }
        }
        
        return messages.get(language.lower(), messages['english'])

    def execute_death_protocol(self):
        """Execute the death protocol - send documents to recipients"""
        logger.info("Executing death protocol - sending documents to recipients")
        
        for recipient in self.recipients:
            logger.info(f"Processing recipient: {recipient.name} (Language: {recipient.preferred_language})")
            
            # Get personalized message in recipient's preferred language
            message_content = self.get_message_in_language(recipient.preferred_language, recipient.name)
            
            # Create secure document package
            for document in self.documents:
                try:
                    # Create secure viewer
                    secure_file = self.create_secure_document_viewer(document, recipient)
                    
                    # Send via email with personalized message
                    subject = message_content['subject']
                    body = f"""
{message_content['greeting']}

{message_content['main_message']}

📄 Document: {document.name}
📝 Description: {document.description}

{message_content['technical_info']}

{message_content['closing']}

---
{message_content['generated']}
                    """
                    
                    email_success = self.notifications.send_email(
                        recipient.email, 
                        subject, 
                        body, 
                        [secure_file]
                    )
                    
                    # Send access code via SMS in recipient's preferred language
                    viewer_otp = self.security.generate_otp()  # This should match the one in HTML
                    
                    # SMS messages in different languages
                    sms_messages = {
                        'english': f"💙 Access code for {document.name}: {viewer_otp}. Check your email for the secure document. Thanks for your love.",
                        'hindi': f"💙 {document.name} के लिए एक्सेस कोड: {viewer_otp}. सुरक्षित दस्तावेज़ के लिए अपना ईमेल देखें। आपके प्रेम के लिए धन्यवाद।",
                        'telugu': f"💙 {document.name} కోసం యాక్సెస్ కোడ్: {viewer_otp}. భద్రమైన పత్రం కోసం మీ ఇమెయిల్ చూడండి. మీ ప్రేమకు ధన్యవాదాలు।",
                        'tamil': f"💙 {document.name} க்கான அணுகல் குறியீடு: {viewer_otp}. பாதுகாப்பான ஆவணத்திற்கு உங்கள் மின்னஞ்சலைப் பார்க்கவும். உங்கள் அன்பிற்கு நன்றி।",
                        'kannada': f"💙 {document.name} ಗಾಗಿ ಪ್ರವೇಶ ಕೋಡ್: {viewer_otp}. ಭದ್ರ ದಾಖಲೆಗಾಗಿ ನಿಮ್ಮ ಇಮೇಲ್ ಅನ್ನು ಪರಿಶೀಲಿಸಿ। ನಿಮ್ಮ ಪ್ರೀತಿಗೆ ಧನ್ಯವಾದಗಳು।",
                        'malayalam': f"💙 {document.name} നുള്ള ആക്സസ് കോഡ്: {viewer_otp}. സുരക്ഷിത രേഖയ്ക്കായി നിങ്ങളുടെ ഇമെയിൽ പരിശോധിക്കുക. നിങ്ങളുടെ സ്നേഹത്തിനു നന്ദി।",
                        'spanish': f"💙 Código de acceso para {document.name}: {viewer_otp}. Revisa tu email para el documento seguro. Gracias por tu amor.",
                        'french': f"💙 Code d'accès pour {document.name}: {viewer_otp}. Vérifiez votre email pour le document sécurisé. Merci pour votre amour."
                    }
                    
                    sms_message = sms_messages.get(recipient.preferred_language, sms_messages['english'])
                    sms_success = self.notifications.send_sms(recipient.phone, sms_message)
                    
                    # Log delivery attempts
                    self.db.log_delivery(recipient.name, "email", "success" if email_success else "failed")
                    self.db.log_delivery(recipient.name, "sms", "success" if sms_success else "failed")
                    
                except Exception as e:
                    logger.error(f"Failed to process document {document.name} for {recipient.name}: {str(e)}")
        
        logger.info("Death protocol execution completed")
    
    def setup_recipients_with_languages(self):
        """Interactive setup for recipients with language preferences"""
        print("👥 RECIPIENT SETUP WITH LANGUAGE PREFERENCES")
        print("=" * 60)
        
        recipients = []
        
        while True:
            print(f"\n📝 Adding Recipient #{len(recipients) + 1}")
            print("-" * 30)
            
            name = input("👤 Full Name: ").strip()
            if not name:
                print("❌ Name cannot be empty!")
                continue
                
            email = input("📧 Email: ").strip()
            if not email or '@' not in email:
                print("❌ Please enter a valid email!")
                continue
                
            phone = input("📱 Phone (with country code, e.g. +91xxxxxxxxxx): ").strip()
            if not phone:
                print("❌ Phone cannot be empty!")
                continue
                
            whatsapp = input("📱 WhatsApp (press Enter if same as phone): ").strip()
            if not whatsapp:
                whatsapp = phone
            
            # Language selection for this recipient
            print(f"\n🌍 Select preferred language for {name}:")
            print("1. English")
            print("2. Hindi (हिंदी)")
            print("3. Telugu (తెలుగు)")
            print("4. Tamil (தமிழ்)")
            print("5. Kannada (ಕನ್ನಡ)")
            print("6. Malayalam (മലയാളം)")
            print("7. Spanish (Español)")
            print("8. French (Français)")
            
            language_map = {
                '1': 'english', '2': 'hindi', '3': 'telugu', '4': 'tamil',
                '5': 'kannada', '6': 'malayalam', '7': 'spanish', '8': 'french'
            }
            
            while True:
                lang_choice = input("Enter choice (1-8): ").strip()
                if lang_choice in language_map:
                    preferred_language = language_map[lang_choice]
                    break
                print("❌ Invalid choice. Please enter 1-8.")
            
            # Preview message for this recipient
            print(f"\n🔍 MESSAGE PREVIEW for {name} in {preferred_language.upper()}:")
            self.preview_message(preferred_language, name)
            
            confirm = input(f"\n✅ Add {name} with {preferred_language} language? (yes/no): ").strip().lower()
            if confirm in ['yes', 'y']:
                recipient_data = {
                    "name": name,
                    "email": email,
                    "phone": phone,
                    "whatsapp": whatsapp,
                    "preferred_language": preferred_language
                }
                recipients.append(recipient_data)
                print(f"✅ {name} added successfully!")
            else:
                print("❌ Recipient not added.")
            
            # Ask if user wants to add more recipients
            if len(recipients) > 0:
                more = input(f"\n➕ Add another recipient? (yes/no): ").strip().lower()
                if more not in ['yes', 'y']:
                    break
            
        if recipients:
            # Update config file
            self.config['recipients'] = recipients
            with open('config.json', 'w') as f:
                json.dump(self.config, f, indent=2)
            
            # Reload recipients
            self.recipients = [Recipient(**r) for r in recipients]
            
            print(f"\n🎉 Successfully configured {len(recipients)} recipient(s)!")
            print("\n📋 SUMMARY:")
            for i, recipient in enumerate(recipients, 1):
                print(f"{i}. {recipient['name']} - {recipient['preferred_language'].title()}")
        else:
            print("❌ No recipients were added.")
        
        return len(recipients) > 0
        """Prompt user to select language for messages"""
        available_languages = {
            '1': 'english',
            '2': 'hindi', 
            '3': 'telugu',
            '4': 'tamil',
            '5': 'kannada',
            '6': 'malayalam',
            '7': 'spanish',
            '8': 'french'
        }
        
        print("\n🌍 Select language for recipient messages:")
        print("1. English")
        print("2. Hindi (हिंदी)")
        print("3. Telugu (తెలుగు)")
        print("4. Tamil (தமிழ்)")
        print("5. Kannada (ಕನ್ನಡ)")
        print("6. Malayalam (മലയാളം)")
        print("7. Spanish (Español)")
        print("8. French (Français)")
        
        while True:
            choice = input("\nEnter your choice (1-8): ").strip()
            if choice in available_languages:
                selected_language = available_languages[choice]
                print(f"✅ Selected language: {selected_language.title()}")
                return selected_language
            else:
                print("❌ Invalid choice. Please enter 1-8.")

    def preview_message(self, language: str, recipient_name: str = "Example Person"):
        """Preview the message that will be sent in selected language"""
        message_content = self.get_message_in_language(language, recipient_name)
        
        print(f"\n📧 EMAIL PREVIEW ({language.upper()}):")
        print("=" * 50)
        print(f"Subject: {message_content['subject']}")
        print(f"\n{message_content['greeting']}")
        print(f"\n{message_content['main_message']}")
        print(f"\n{message_content['closing']}")
        print("\n" + "=" * 50)
        
        # SMS Preview
        sms_messages = {
            'english': f"💙 Access code for [Document]: [CODE]. Check your email for the secure document. Thanks for your love.",
            'hindi': f"💙 [Document] के लिए एक्सेस कोड: [CODE]. सुरक्षित दस्तावेज़ के लिए अपना ईमेल देखें। आपके प्रेम के लिए धन्यवाद।",
            'telugu': f"💙 [Document] కోసం యాక్సెస్ కोड్: [CODE]. భద్రమైన పత్రం కోసం మీ ఇమెయిల్ చూడండి. మీ ప్రేమకు ధన్యవాదాలు।",
            'spanish': f"💙 Código de acceso para [Document]: [CODE]. Revisa tu email para el documento seguro. Gracias por tu amor.",
            'french': f"💙 Code d'accès pour [Document]: [CODE]. Vérifiez votre email pour le document sécurisé. Merci pour votre amour."
        }
        
        print(f"\n📱 SMS PREVIEW ({language.upper()}):")
        print("=" * 50)
        print(sms_messages.get(language, sms_messages['english']))
        print("=" * 50)
        """Run a single monitoring cycle"""
        if not self.is_running:
            logger.info("System disabled by kill switch")
            return
        
        # Check for inactivity
        if self.check_inactivity():
            if not self.trigger_activated:
                logger.warning("Inactivity threshold reached - activating trigger")
                self.trigger_activated = True
                self.send_life_verification()
                
                # Set a timer for verification period
                verification_deadline = datetime.now() + timedelta(hours=self.verification_hours)
                logger.info(f"Life verification deadline: {verification_deadline}")
                
                # This would typically be handled by a separate thread or scheduler
                # For now, we'll check it in the next cycle
            
            else:
                # Check if verification period has expired
                # In a real implementation, this would be more sophisticated
                logger.info("Trigger already activated - checking verification status")
                
                # If no verification received and deadline passed, execute death protocol
                # This is simplified - in practice you'd track the verification deadline
                self.execute_death_protocol()
                self.is_running = False
    
    def start_monitoring(self):
        """Start the continuous monitoring system"""
        logger.info("Starting Digital Death Switch AI monitoring system")
        
        # Schedule regular checks (every hour)
        schedule.every().hour.do(self.run_monitoring_cycle)
        
        while self.is_running:
            schedule.run_pending()
            time.sleep(60)  # Check every minute for scheduled tasks
    
    def set_kill_switch(self, kill_code: str):
        """Set or update the kill switch code"""
        hashed_code = self.security.hash_kill_switch(kill_code)
        
        # Update config
        self.config['kill_switch_hash'] = hashed_code
        
        # Save to config file
        with open('config.json', 'w') as f:
            json.dump(self.config, f, indent=2)
        
        logger.info("Kill switch code updated successfully")

    def test_message_languages(self):
        """Test function to preview messages in all languages"""
        print("🌍 TESTING ALL LANGUAGE MESSAGES")
        print("=" * 60)
        
        languages = ['english', 'hindi', 'telugu', 'tamil', 'kannada', 'malayalam', 'spanish', 'french']
        test_recipient = "Your Loved One"
        
        for lang in languages:
            print(f"\n🔤 LANGUAGE: {lang.upper()}")
            self.preview_message(lang, test_recipient)
            print("\n" + "-" * 60)

def main():
    """Main function to demonstrate the system"""
    try:
        # Initialize the Death Switch AI
        death_switch = DeathSwitchAI()
        
        print("💙 Digital Death Switch AI initialized successfully")
        
        # Interactive menu
        while True:
            print("\n🔧 DIGITAL DEATH SWITCH - MAIN MENU")
            print("=" * 50)
            print("1. 👥 Setup Recipients (with language preferences)")
            print("2. 🔒 Set Kill Switch Code")
            print("3. 📱 Record Activity (reset death timer)")
            print("4. ℹ️  Check System Status")
            print("5. 🌍 Test All Language Messages")
            print("6. 🔍 Preview Message for Specific Language")
            print("7. 🚀 Start Monitoring System")
            print("8. ❌ Exit")
            
            choice = input("\nEnter your choice (1-8): ").strip()
            
            if choice == '1':
                death_switch.setup_recipients_with_languages()
                
            elif choice == '2':
                kill_code = input("🔐 Enter your kill switch code (keep it secret!): ").strip()
                if kill_code:
                    death_switch.set_kill_switch(kill_code)
                    print("✅ Kill switch code set successfully!")
                else:
                    print("❌ Kill switch code cannot be empty!")
                    
            elif choice == '3':
                death_switch.record_activity("manual_checkin")
                print("✅ Activity recorded - death timer reset!")
                
            elif choice == '4':
                last_activity = death_switch.db.get_last_activity()
                if last_activity:
                    days_since = (datetime.now() - last_activity).days
                    print(f"📊 Last activity: {last_activity}")
                    print(f"📅 Days since last activity: {days_since}")
                    print(f"⏰ Trigger threshold: {death_switch.inactivity_days} days")
                    if days_since >= death_switch.inactivity_days:
                        print("🚨 WARNING: Inactivity threshold reached!")
                    else:
                        print(f"✅ System active ({death_switch.inactivity_days - days_since} days remaining)")
                else:
                    print("📊 No activity recorded yet")
                    
            elif choice == '5':
                death_switch.test_message_languages()
                
            elif choice == '6':
                languages = ['english', 'hindi', 'telugu', 'tamil', 'kannada', 'malayalam', 'spanish', 'french']
                print("🌍 Available languages:")
                for i, lang in enumerate(languages, 1):
                    print(f"{i}. {lang.title()}")
                
                try:
                    lang_choice = int(input("Select language (1-8): ").strip()) - 1
                    if 0 <= lang_choice < len(languages):
                        recipient_name = input("Enter recipient name for preview: ").strip() or "Sample Person"
                        death_switch.preview_message(languages[lang_choice], recipient_name)
                    else:
                        print("❌ Invalid choice!")
                except ValueError:
                    print("❌ Please enter a valid number!")
                    
            elif choice == '7':
                print("🚀 Starting monitoring system...")
                print("💡 Press Ctrl+C to stop monitoring")
                try:
                    death_switch.start_monitoring()
                except KeyboardInterrupt:
                    print("\n⏹️  Monitoring stopped by user")
                    
            elif choice == '8':
                print("👋 Goodbye! Your Digital Death Switch is configured and ready.")
                break
                
            else:
                print("❌ Invalid choice. Please enter 1-8.")
        
        print(f"\n💝 Remember: Your personalized loving message will be sent to recipients:")
        print("'For your security I have made sure that you are not left in debt or financial stress.'")
        print("'Thanks for your love'")
        
    except Exception as e:
        logger.error(f"Failed to initialize system: {str(e)}")
        print(f"❌ Error: {str(e)}")
        print("Please check the configuration and try again.")

if __name__ == "__main__":
    main()
