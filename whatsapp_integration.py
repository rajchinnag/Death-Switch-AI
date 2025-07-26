#!/usr/bin/env python3
"""
WhatsApp Integration for Digital Death Switch AI
Supports multiple WhatsApp APIs and fallback methods
"""

import json
import requests
import time
import os
import logging
from typing import List, Dict, Optional
import base64
from datetime import datetime

logger = logging.getLogger(__name__)

class WhatsAppManager:
    """Handles WhatsApp message sending via multiple providers"""
    
    def __init__(self, config: Dict):
        self.config = config
        self.setup_providers()
    
    def setup_providers(self):
        """Setup available WhatsApp providers"""
        self.providers = {}
        
        # Twilio WhatsApp Business API
        if all(key in self.config for key in ['twilio_sid', 'twilio_token', 'twilio_whatsapp_number']):
            self.providers['twilio'] = TwilioWhatsApp(self.config)
        
        # WhatsApp Business API (Official)
        if 'whatsapp_business_token' in self.config:
            self.providers['business_api'] = WhatsAppBusinessAPI(self.config)
        
        # WhatsApp Web API (Third-party)
        if 'whatsapp_web_api_url' in self.config:
            self.providers['web_api'] = WhatsAppWebAPI(self.config)
        
        # Baileys (JavaScript WhatsApp Web)
        if 'baileys_api_url' in self.config:
            self.providers['baileys'] = BaileysAPI(self.config)
        
        logger.info(f"Initialized {len(self.providers)} WhatsApp providers: {list(self.providers.keys())}")
    
    def send_message(self, phone_number: str, message: str, attachments: List[str] = None) -> bool:
        """Send WhatsApp message using available providers (with fallback)"""
        
        # Clean phone number
        phone_number = self.clean_phone_number(phone_number)
        
        # Try providers in order of reliability
        provider_order = ['business_api', 'twilio', 'web_api', 'baileys']
        
        for provider_name in provider_order:
            if provider_name in self.providers:
                try:
                    logger.info(f"Attempting WhatsApp send via {provider_name}")
                    provider = self.providers[provider_name]
                    
                    if attachments:
                        success = provider.send_message_with_attachments(phone_number, message, attachments)
                    else:
                        success = provider.send_message(phone_number, message)
                    
                    if success:
                        logger.info(f"✅ WhatsApp message sent successfully via {provider_name}")
                        return True
                    else:
                        logger.warning(f"❌ Failed to send via {provider_name}")
                        
                except Exception as e:
                    logger.error(f"❌ Error with {provider_name}: {e}")
                    continue
        
        logger.error("❌ All WhatsApp providers failed")
        return False
    
    def clean_phone_number(self, phone: str) -> str:
        """Clean and format phone number for WhatsApp"""
        # Remove all non-digits except +
        cleaned = ''.join(c for c in phone if c.isdigit() or c == '+')
        
        # Ensure it starts with +
        if not cleaned.startswith('+'):
            # Assume Indian number if no country code
            if len(cleaned) == 10:
                cleaned = '+91' + cleaned
            else:
                cleaned = '+' + cleaned
        
        return cleaned

class TwilioWhatsApp:
    """Twilio WhatsApp Business API integration"""
    
    def __init__(self, config: Dict):
        self.account_sid = config['twilio_sid']
        self.auth_token = config['twilio_token']
        self.whatsapp_number = config['twilio_whatsapp_number']
        
        try:
            from twilio.rest import Client
            self.client = Client(self.account_sid, self.auth_token)
        except ImportError:
            raise ImportError("Twilio library not installed. Run: pip install twilio")
    
    def send_message(self, to_number: str, message: str) -> bool:
        """Send text message via Twilio WhatsApp"""
        try:
            message = self.client.messages.create(
                body=message,
                from_=f'whatsapp:{self.whatsapp_number}',
                to=f'whatsapp:{to_number}'
            )
            
            logger.info(f"Twilio WhatsApp message sent: {message.sid}")
            return True
            
        except Exception as e:
            logger.error(f"Twilio WhatsApp error: {e}")
            return False
    
    def send_message_with_attachments(self, to_number: str, message: str, attachments: List[str]) -> bool:
        """Send message with media attachments"""
        try:
            # Send text message first
            text_success = self.send_message(to_number, message)
            
            # Send each attachment
            for attachment in attachments:
                if os.path.exists(attachment):
                    # Upload to temporary hosting (you'd need to implement this)
                    media_url = self.upload_media(attachment)
                    
                    if media_url:
                        message = self.client.messages.create(
                            media_url=[media_url],
                            from_=f'whatsapp:{self.whatsapp_number}',
                            to=f'whatsapp:{to_number}'
                        )
                        logger.info(f"Twilio WhatsApp media sent: {message.sid}")
            
            return text_success
            
        except Exception as e:
            logger.error(f"Twilio WhatsApp media error: {e}")
            return False
    
    def upload_media(self, file_path: str) -> Optional[str]:
        """Upload media to accessible URL (implement based on your hosting)"""
        # This would typically upload to AWS S3, Google Cloud, etc.
        # For now, return None to skip media
        logger.warning("Media upload not implemented for Twilio WhatsApp")
        return None

class WhatsAppBusinessAPI:
    """Official WhatsApp Business API integration"""
    
    def __init__(self, config: Dict):
        self.access_token = config['whatsapp_business_token']
        self.phone_number_id = config.get('whatsapp_phone_number_id')
        self.api_url = "https://graph.facebook.com/v17.0"
    
    def send_message(self, to_number: str, message: str) -> bool:
        """Send text message via WhatsApp Business API"""
        try:
            url = f"{self.api_url}/{self.phone_number_id}/messages"
            
            headers = {
                'Authorization': f'Bearer {self.access_token}',
                'Content-Type': 'application/json'
            }
            
            data = {
                'messaging_product': 'whatsapp',
                'to': to_number.replace('+', ''),
                'type': 'text',
                'text': {'body': message}
            }
            
            response = requests.post(url, headers=headers, json=data)
            response.raise_for_status()
            
            logger.info(f"WhatsApp Business API message sent: {response.json()}")
            return True
            
        except Exception as e:
            logger.error(f"WhatsApp Business API error: {e}")
            return False
    
    def send_message_with_attachments(self, to_number: str, message: str, attachments: List[str]) -> bool:
        """Send message with document attachments"""
        try:
            # Send text message first
            text_success = self.send_message(to_number, message)
            
            # Send documents
            for attachment in attachments:
                if os.path.exists(attachment):
                    success = self.send_document(to_number, attachment)
                    if not success:
                        logger.warning(f"Failed to send attachment: {attachment}")
            
            return text_success
            
        except Exception as e:
            logger.error(f"WhatsApp Business API media error: {e}")
            return False
    
    def send_document(self, to_number: str, file_path: str) -> bool:
        """Send document via WhatsApp Business API"""
        try:
            # First upload the media
            media_id = self.upload_media(file_path)
            if not media_id:
                return False
            
            # Then send the document
            url = f"{self.api_url}/{self.phone_number_id}/messages"
            
            headers = {
                'Authorization': f'Bearer {self.access_token}',
                'Content-Type': 'application/json'
            }
            
            data = {
                'messaging_product': 'whatsapp',
                'to': to_number.replace('+', ''),
                'type': 'document',
                'document': {
                    'id': media_id,
                    'filename': os.path.basename(file_path)
                }
            }
            
            response = requests.post(url, headers=headers, json=data)
            response.raise_for_status()
            
            logger.info(f"WhatsApp document sent: {response.json()}")
            return True
            
        except Exception as e:
            logger.error(f"WhatsApp document send error: {e}")
            return False
    
    def upload_media(self, file_path: str) -> Optional[str]:
        """Upload media to WhatsApp and get media ID"""
        try:
            url = f"{self.api_url}/{self.phone_number_id}/media"
            
            headers = {
                'Authorization': f'Bearer {self.access_token}'
            }
            
            with open(file_path, 'rb') as f:
                files = {
                    'file': (os.path.basename(file_path), f, 'application/octet-stream'),
                    'messaging_product': (None, 'whatsapp')
                }
                
                response = requests.post(url, headers=headers, files=files)
                response.raise_for_status()
                
                media_id = response.json().get('id')
                logger.info(f"Media uploaded with ID: {media_id}")
                return media_id
                
        except Exception as e:
            logger.error(f"Media upload error: {e}")
            return None

class WhatsAppWebAPI:
    """Third-party WhatsApp Web API integration"""
    
    def __init__(self, config: Dict):
        self.api_url = config['whatsapp_web_api_url']
        self.api_key = config.get('whatsapp_web_api_key', '')
    
    def send_message(self, to_number: str, message: str) -> bool:
        """Send message via WhatsApp Web API"""
        try:
            headers = {'Content-Type': 'application/json'}
            if self.api_key:
                headers['Authorization'] = f'Bearer {self.api_key}'
            
            data = {
                'phone': to_number,
                'message': message
            }
            
            response = requests.post(f"{self.api_url}/send-message", 
                                   headers=headers, json=data)
            response.raise_for_status()
            
            logger.info(f"WhatsApp Web API message sent: {response.json()}")
            return True
            
        except Exception as e:
            logger.error(f"WhatsApp Web API error: {e}")
            return False
    
    def send_message_with_attachments(self, to_number: str, message: str, attachments: List[str]) -> bool:
        """Send message with attachments via Web API"""
        try:
            # Send text first
            text_success = self.send_message(to_number, message)
            
            # Send files
            for attachment in attachments:
                if os.path.exists(attachment):
                    self.send_file(to_number, attachment)
            
            return text_success
            
        except Exception as e:
            logger.error(f"WhatsApp Web API media error: {e}")
            return False
    
    def send_file(self, to_number: str, file_path: str) -> bool:
        """Send file via WhatsApp Web API"""
        try:
            headers = {}
            if self.api_key:
                headers['Authorization'] = f'Bearer {self.api_key}'
            
            with open(file_path, 'rb') as f:
                files = {
                    'file': (os.path.basename(file_path), f),
                    'phone': (None, to_number)
                }
                
                response = requests.post(f"{self.api_url}/send-file", 
                                       headers=headers, files=files)
                response.raise_for_status()
                
                logger.info(f"WhatsApp file sent: {response.json()}")
                return True
                
        except Exception as e:
            logger.error(f"WhatsApp file send error: {e}")
            return False

class BaileysAPI:
    """Baileys (JavaScript WhatsApp Web) API integration"""
    
    def __init__(self, config: Dict):
        self.api_url = config['baileys_api_url']
        self.session_id = config.get('baileys_session_id', 'death_switch')
    
    def send_message(self, to_number: str, message: str) -> bool:
        """Send message via Baileys API"""
        try:
            data = {
                'sessionId': self.session_id,
                'to': to_number,
                'text': message
            }
            
            response = requests.post(f"{self.api_url}/send-text", json=data)
            response.raise_for_status()
            
            logger.info(f"Baileys API message sent: {response.json()}")
            return True
            
        except Exception as e:
            logger.error(f"Baileys API error: {e}")
            return False
    
    def send_message_with_attachments(self, to_number: str, message: str, attachments: List[str]) -> bool:
        """Send message with attachments via Baileys"""
        try:
            # Send text first
            text_success = self.send_message(to_number, message)
            
            # Send files
            for attachment in attachments:
                if os.path.exists(attachment):
                    with open(attachment, 'rb') as f:
                        file_data = base64.b64encode(f.read()).decode()
                    
                    data = {
                        'sessionId': self.session_id,
                        'to': to_number,
                        'filename': os.path.basename(attachment),
                        'data': file_data
                    }
                    
                    response = requests.post(f"{self.api_url}/send-file", json=data)
                    if response.status_code == 200:
                        logger.info(f"Baileys file sent: {attachment}")
                    else:
                        logger.error(f"Baileys file send failed: {response.text}")
            
            return text_success
            
        except Exception as e:
            logger.error(f"Baileys API media error: {e}")
            return False

# Integration with main Death Switch system
def enhance_notification_manager():
    """Enhancement for the existing NotificationManager class"""
    
    enhancement_code = '''
    def __init__(self, config: Dict):
        # ... existing code ...
        
        # Add WhatsApp manager
        self.whatsapp = WhatsAppManager(config)
    
    def send_whatsapp(self, phone_number: str, message: str, attachments: List[str] = None) -> bool:
        """Send WhatsApp message with fallback to SMS"""
        # Try WhatsApp first
        whatsapp_success = self.whatsapp.send_message(phone_number, message, attachments)
        
        if whatsapp_success:
            return True
        
        # Fallback to SMS if WhatsApp fails
        logger.warning("WhatsApp failed, falling back to SMS")
        return self.send_sms(phone_number, message)
    '''
    
    return enhancement_code

# Example configuration for different providers
def create_sample_whatsapp_config():
    """Create sample WhatsApp configuration"""
    
    sample_config = {
        # Twilio WhatsApp (Easiest to set up)
        "twilio_sid": "your_twilio_account_sid",
        "twilio_token": "your_twilio_auth_token", 
        "twilio_whatsapp_number": "+14155238886",  # Twilio Sandbox number
        
        # WhatsApp Business API (Most reliable)
        "whatsapp_business_token": "your_business_api_token",
        "whatsapp_phone_number_id": "your_phone_number_id",
        
        # Third-party Web API (Alternative)
        "whatsapp_web_api_url": "http://localhost:3000",
        "whatsapp_web_api_key": "your_api_key",
        
        # Baileys API (Self-hosted)
        "baileys_api_url": "http://localhost:8000",
        "baileys_session_id": "death_switch_session"
    }
    
    return sample_config

def setup_whatsapp_providers():
    """Interactive setup for WhatsApp providers"""
    print("🔧 WHATSAPP PROVIDER SETUP")
    print("=" * 50)
    
    config = {}
    
    # Twilio setup
    print("\n1️⃣  TWILIO WHATSAPP (Recommended for beginners)")
    print("   • Easy to set up")
    print("   • Reliable delivery")
    print("   • Uses Twilio Sandbox initially")
    
    use_twilio = input("Set up Twilio WhatsApp? (y/n): ").lower() == 'y'
    if use_twilio:
        config['twilio_sid'] = input("Enter Twilio Account SID: ")
        config['twilio_token'] = input("Enter Twilio Auth Token: ")
        config['twilio_whatsapp_number'] = input("Enter Twilio WhatsApp Number (default: +14155238886): ") or "+14155238886"
        print("✅ Twilio WhatsApp configured!")
    
    # Business API setup
    print("\n2️⃣  WHATSAPP BUSINESS API (Most reliable)")
    print("   • Official WhatsApp API")
    print("   • Requires business verification")
    print("   • Best for production use")
    
    use_business = input("Set up WhatsApp Business API? (y/n): ").lower() == 'y'
    if use_business:
        config['whatsapp_business_token'] = input("Enter Business API Token: ")
        config['whatsapp_phone_number_id'] = input("Enter Phone Number ID: ")
        print("✅ WhatsApp Business API configured!")
    
    # Save config
    config_file = 'whatsapp_config.json'
    with open(config_file, 'w') as f:
        json.dump(config, f, indent=2)
    
    print(f"\n📁 Configuration saved to {config_file}")
    print("🔗 Integration: Add this config to your main config.json")
    
    return config

if __name__ == "__main__":
    print("📱 WhatsApp Integration for Digital Death Switch AI")
    print("=" * 60)
    
    # Interactive setup
    if len(os.sys.argv) > 1 and os.sys.argv[1] == 'setup':
        setup_whatsapp_providers()
    else:
        print("Commands:")
        print("  python whatsapp_integration.py setup  - Interactive setup")
        print("\nThis module provides WhatsApp integration with multiple providers:")
        print("• Twilio WhatsApp Business API")
        print("• Official WhatsApp Business API") 
        print("• Third-party WhatsApp Web APIs")
        print("• Baileys (JavaScript WhatsApp Web)")
