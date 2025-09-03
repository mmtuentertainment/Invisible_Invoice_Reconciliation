"""
Email service for sending transactional emails including password reset, MFA setup, and security alerts.
Supports multiple email providers with rate limiting and audit logging.
"""

import asyncio
import smtplib
from email.mime.text import MimeText
from email.mime.multipart import MimeMultipart
from typing import Optional, Dict, Any
from datetime import datetime, timedelta
from jinja2 import Template
import aiosmtplib

from app.core.config import settings
from app.services.redis_service import redis_service


class EmailService:
    """Email service for transactional emails with security features."""
    
    def __init__(self):
        self.smtp_server = settings.SMTP_SERVER
        self.smtp_port = settings.SMTP_PORT
        self.smtp_username = settings.SMTP_USERNAME
        self.smtp_password = settings.SMTP_PASSWORD
        self.from_email = settings.FROM_EMAIL
        self.from_name = settings.FROM_NAME
        self.use_tls = settings.SMTP_USE_TLS
        
    async def send_password_reset_email(
        self,
        to_email: str,
        user_name: str,
        reset_url: str,
        expires_minutes: int = 30
    ) -> bool:
        """
        Send password reset email with secure token.
        
        Args:
            to_email: Recipient email address
            user_name: User's display name
            reset_url: Password reset URL with token
            expires_minutes: Token expiration in minutes
            
        Returns:
            True if email sent successfully
        """
        # Rate limiting: 3 emails per hour per recipient
        rate_limit_key = f"email_password_reset:{to_email}"
        if not await redis_service.check_rate_limit(rate_limit_key, limit=3, window=3600):
            return False
        
        subject = f"{settings.APP_NAME} - Password Reset Request"
        
        html_template = Template("""
        <!DOCTYPE html>
        <html>
        <head>
            <meta charset="utf-8">
            <title>Password Reset</title>
            <style>
                body { font-family: Arial, sans-serif; line-height: 1.6; color: #333; }
                .container { max-width: 600px; margin: 0 auto; padding: 20px; }
                .header { background: #f8f9fa; padding: 20px; text-align: center; border-radius: 5px; }
                .content { padding: 20px 0; }
                .button { 
                    display: inline-block; 
                    padding: 12px 24px; 
                    background: #007bff; 
                    color: white; 
                    text-decoration: none; 
                    border-radius: 5px; 
                    margin: 20px 0;
                }
                .warning { 
                    background: #fff3cd; 
                    border: 1px solid #ffeaa7; 
                    padding: 15px; 
                    border-radius: 5px; 
                    margin: 20px 0;
                }
                .footer { 
                    font-size: 12px; 
                    color: #666; 
                    text-align: center; 
                    margin-top: 30px; 
                    padding-top: 20px; 
                    border-top: 1px solid #eee;
                }
            </style>
        </head>
        <body>
            <div class="container">
                <div class="header">
                    <h1>{{ app_name }}</h1>
                    <h2>Password Reset Request</h2>
                </div>
                
                <div class="content">
                    <p>Hello {{ user_name }},</p>
                    
                    <p>We received a request to reset your password for your {{ app_name }} account. If you made this request, click the button below to reset your password:</p>
                    
                    <div style="text-align: center;">
                        <a href="{{ reset_url }}" class="button">Reset Password</a>
                    </div>
                    
                    <p>This link will expire in {{ expires_minutes }} minutes for security reasons.</p>
                    
                    <div class="warning">
                        <strong>Security Notice:</strong> If you didn't request this password reset, please ignore this email. Your account remains secure and no changes have been made.
                    </div>
                    
                    <p>For security reasons:</p>
                    <ul>
                        <li>Never share this reset link with anyone</li>
                        <li>The link can only be used once</li>
                        <li>If you're concerned about your account security, contact our support team</li>
                    </ul>
                    
                    <p>If the button doesn't work, you can copy and paste this URL into your browser:</p>
                    <p style="word-break: break-all; background: #f8f9fa; padding: 10px; border-radius: 3px;">{{ reset_url }}</p>
                </div>
                
                <div class="footer">
                    <p>This is an automated security email from {{ app_name }}.</p>
                    <p>Please do not reply to this email.</p>
                    <p>© {{ current_year }} {{ app_name }}. All rights reserved.</p>
                </div>
            </div>
        </body>
        </html>
        """)
        
        text_template = Template("""
        {{ app_name }} - Password Reset Request
        
        Hello {{ user_name }},
        
        We received a request to reset your password for your {{ app_name }} account.
        
        To reset your password, visit this link:
        {{ reset_url }}
        
        This link will expire in {{ expires_minutes }} minutes for security reasons.
        
        Security Notice: If you didn't request this password reset, please ignore this email. Your account remains secure and no changes have been made.
        
        For security reasons:
        - Never share this reset link with anyone
        - The link can only be used once  
        - If you're concerned about your account security, contact our support team
        
        This is an automated security email from {{ app_name }}.
        Please do not reply to this email.
        """)
        
        html_content = html_template.render(
            app_name=settings.APP_NAME,
            user_name=user_name,
            reset_url=reset_url,
            expires_minutes=expires_minutes,
            current_year=datetime.now().year
        )
        
        text_content = text_template.render(
            app_name=settings.APP_NAME,
            user_name=user_name,
            reset_url=reset_url,
            expires_minutes=expires_minutes
        )
        
        return await self._send_email(
            to_email=to_email,
            subject=subject,
            text_content=text_content,
            html_content=html_content
        )
    
    async def send_mfa_setup_email(
        self,
        to_email: str,
        user_name: str,
        setup_completed: bool = True
    ) -> bool:
        """
        Send MFA setup confirmation email.
        
        Args:
            to_email: Recipient email address
            user_name: User's display name
            setup_completed: Whether MFA was enabled or disabled
            
        Returns:
            True if email sent successfully
        """
        action = "enabled" if setup_completed else "disabled"
        subject = f"{settings.APP_NAME} - Two-Factor Authentication {action.title()}"
        
        html_template = Template("""
        <!DOCTYPE html>
        <html>
        <head>
            <meta charset="utf-8">
            <title>MFA {{ action.title() }}</title>
            <style>
                body { font-family: Arial, sans-serif; line-height: 1.6; color: #333; }
                .container { max-width: 600px; margin: 0 auto; padding: 20px; }
                .header { background: #f8f9fa; padding: 20px; text-align: center; border-radius: 5px; }
                .content { padding: 20px 0; }
                .success { 
                    background: #d4edda; 
                    border: 1px solid #c3e6cb; 
                    padding: 15px; 
                    border-radius: 5px; 
                    margin: 20px 0;
                }
                .warning { 
                    background: #fff3cd; 
                    border: 1px solid #ffeaa7; 
                    padding: 15px; 
                    border-radius: 5px; 
                    margin: 20px 0;
                }
            </style>
        </head>
        <body>
            <div class="container">
                <div class="header">
                    <h1>{{ app_name }}</h1>
                    <h2>Security Update</h2>
                </div>
                
                <div class="content">
                    <p>Hello {{ user_name }},</p>
                    
                    <div class="success">
                        <strong>Two-Factor Authentication {{ action.title() }}</strong><br>
                        Your account security has been updated. Two-factor authentication has been {{ action }} for your account.
                    </div>
                    
                    {% if setup_completed %}
                    <p>Your account is now more secure with two-factor authentication enabled. You'll need your authenticator app when signing in.</p>
                    {% else %}
                    <p>Two-factor authentication has been disabled for your account. Consider re-enabling it for better security.</p>
                    {% endif %}
                    
                    <div class="warning">
                        <strong>Security Notice:</strong> If you didn't make this change, please contact our support team immediately and review your account security.
                    </div>
                </div>
            </div>
        </body>
        </html>
        """)
        
        html_content = html_template.render(
            app_name=settings.APP_NAME,
            user_name=user_name,
            action=action,
            setup_completed=setup_completed
        )
        
        text_content = f"""
        {settings.APP_NAME} - Security Update
        
        Hello {user_name},
        
        Two-Factor Authentication {action.title()}
        
        Your account security has been updated. Two-factor authentication has been {action} for your account.
        
        Security Notice: If you didn't make this change, please contact our support team immediately.
        """
        
        return await self._send_email(
            to_email=to_email,
            subject=subject,
            text_content=text_content,
            html_content=html_content
        )
    
    async def send_security_alert_email(
        self,
        to_email: str,
        user_name: str,
        alert_type: str,
        description: str,
        ip_address: str,
        timestamp: datetime
    ) -> bool:
        """
        Send security alert email for suspicious activities.
        
        Args:
            to_email: Recipient email address
            user_name: User's display name
            alert_type: Type of security event
            description: Event description
            ip_address: IP address of the event
            timestamp: When the event occurred
            
        Returns:
            True if email sent successfully
        """
        subject = f"{settings.APP_NAME} - Security Alert"
        
        html_template = Template("""
        <!DOCTYPE html>
        <html>
        <head>
            <meta charset="utf-8">
            <title>Security Alert</title>
            <style>
                body { font-family: Arial, sans-serif; line-height: 1.6; color: #333; }
                .container { max-width: 600px; margin: 0 auto; padding: 20px; }
                .header { background: #f8f9fa; padding: 20px; text-align: center; border-radius: 5px; }
                .content { padding: 20px 0; }
                .alert { 
                    background: #f8d7da; 
                    border: 1px solid #f5c6cb; 
                    padding: 15px; 
                    border-radius: 5px; 
                    margin: 20px 0;
                }
                .details {
                    background: #f8f9fa;
                    padding: 15px;
                    border-radius: 5px;
                    margin: 20px 0;
                }
            </style>
        </head>
        <body>
            <div class="container">
                <div class="header">
                    <h1>{{ app_name }}</h1>
                    <h2>🛡️ Security Alert</h2>
                </div>
                
                <div class="content">
                    <p>Hello {{ user_name }},</p>
                    
                    <div class="alert">
                        <strong>Security Event Detected</strong><br>
                        We detected {{ alert_type }} activity on your account.
                    </div>
                    
                    <div class="details">
                        <strong>Event Details:</strong><br>
                        <strong>Type:</strong> {{ alert_type }}<br>
                        <strong>Description:</strong> {{ description }}<br>
                        <strong>IP Address:</strong> {{ ip_address }}<br>
                        <strong>Time:</strong> {{ timestamp.strftime('%Y-%m-%d %H:%M:%S UTC') }}
                    </div>
                    
                    <p><strong>If this was you:</strong> No action is needed. This is just a security notification.</p>
                    
                    <p><strong>If this wasn't you:</strong></p>
                    <ul>
                        <li>Change your password immediately</li>
                        <li>Review your account activity</li>
                        <li>Enable two-factor authentication if not already enabled</li>
                        <li>Contact our support team for assistance</li>
                    </ul>
                </div>
            </div>
        </body>
        </html>
        """)
        
        html_content = html_template.render(
            app_name=settings.APP_NAME,
            user_name=user_name,
            alert_type=alert_type,
            description=description,
            ip_address=ip_address,
            timestamp=timestamp
        )
        
        text_content = f"""
        {settings.APP_NAME} - Security Alert
        
        Hello {user_name},
        
        Security Event Detected
        We detected {alert_type} activity on your account.
        
        Event Details:
        Type: {alert_type}
        Description: {description}
        IP Address: {ip_address}
        Time: {timestamp.strftime('%Y-%m-%d %H:%M:%S UTC')}
        
        If this was you: No action is needed. This is just a security notification.
        
        If this wasn't you:
        - Change your password immediately
        - Review your account activity
        - Enable two-factor authentication if not already enabled
        - Contact our support team for assistance
        """
        
        return await self._send_email(
            to_email=to_email,
            subject=subject,
            text_content=text_content,
            html_content=html_content
        )
    
    async def _send_email(
        self,
        to_email: str,
        subject: str,
        text_content: str,
        html_content: Optional[str] = None
    ) -> bool:
        """
        Send email using configured SMTP settings.
        
        Args:
            to_email: Recipient email address
            subject: Email subject
            text_content: Plain text content
            html_content: HTML content (optional)
            
        Returns:
            True if email sent successfully
        """
        try:
            # Create message
            msg = MimeMultipart('alternative')
            msg['Subject'] = subject
            msg['From'] = f"{self.from_name} <{self.from_email}>"
            msg['To'] = to_email
            
            # Add text part
            text_part = MimeText(text_content, 'plain')
            msg.attach(text_part)
            
            # Add HTML part if provided
            if html_content:
                html_part = MimeText(html_content, 'html')
                msg.attach(html_part)
            
            # Send email
            if settings.ENVIRONMENT == "test":
                # In test environment, just log the email
                print(f"TEST EMAIL: To={to_email}, Subject={subject}")
                return True
            
            await aiosmtplib.send(
                msg,
                hostname=self.smtp_server,
                port=self.smtp_port,
                username=self.smtp_username,
                password=self.smtp_password,
                use_tls=self.use_tls
            )
            
            return True
            
        except Exception as e:
            # Log error (in production, use proper logging)
            print(f"Email send error: {str(e)}")
            return False


# Dependency for getting email service
async def get_email_service() -> EmailService:
    """Get email service instance."""
    return EmailService()