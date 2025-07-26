#!/usr/bin/env python3
"""
Device Activity Monitor for Digital Death Switch AI
Monitors actual device usage across platforms
"""

import os
import sys
import time
import psutil
import sqlite3
from datetime import datetime
import platform
import subprocess
import json
import requests
from pathlib import Path

class DeviceMonitor:
    """Multi-platform device activity monitor"""
    
    def __init__(self, db_path="death_switch.db"):
        self.db_path = db_path
        self.platform = platform.system().lower()
        self.last_activity = None
        self.monitoring_interval = 60  # Check every minute
        
    def detect_user_activity(self):
        """Detect various forms of user activity"""
        activities = []
        
        if self.platform == "windows":
            activities.extend(self._windows_activity())
        elif self.platform == "darwin":  # macOS
            activities.extend(self._macos_activity())
        elif self.platform == "linux":
            activities.extend(self._linux_activity())
        
        # Cross-platform activities
        activities.extend(self._network_activity())
        activities.extend(self._process_activity())
        activities.extend(self._file_activity())
        
        return activities
    
    def _windows_activity(self):
        """Windows-specific activity detection"""
        activities = []
        
        try:
            # Check if user is logged in and active
            import win32gui
            import win32process
            import win32api
            
            # Get foreground window
            hwnd = win32gui.GetForegroundWindow()
            if hwnd:
                _, pid = win32process.GetWindowThreadProcessId(hwnd)
                if pid:
                    activities.append({
                        'type': 'foreground_app',
                        'details': f'Active window PID: {pid}',
                        'timestamp': datetime.now()
                    })
            
            # Check for mouse/keyboard activity using GetLastInputInfo
            import ctypes
            from ctypes import wintypes
            
            class LASTINPUTINFO(ctypes.Structure):
                _fields_ = [('cbSize', wintypes.UINT), ('dwTime', wintypes.DWORD)]
            
            lastInputInfo = LASTINPUTINFO()
            lastInputInfo.cbSize = ctypes.sizeof(lastInputInfo)
            ctypes.windll.user32.GetLastInputInfo(ctypes.byref(lastInputInfo))
            
            millis = ctypes.windll.kernel32.GetTickCount() - lastInputInfo.dwTime
            seconds_since_input = millis / 1000.0
            
            if seconds_since_input < 300:  # Active within last 5 minutes
                activities.append({
                    'type': 'user_input',
                    'details': f'Input {seconds_since_input:.1f}s ago',
                    'timestamp': datetime.now()
                })
                
        except ImportError:
            # Fallback: Check for active processes
            pass
        
        return activities
    
    def _macos_activity(self):
        """macOS-specific activity detection"""
        activities = []
        
        try:
            # Check screen lock status
            result = subprocess.run(['pmset', '-g', 'ps'], capture_output=True, text=True)
            if 'AC Power' in result.stdout or 'Battery Power' in result.stdout:
                activities.append({
                    'type': 'power_status',
                    'details': 'System powered on',
                    'timestamp': datetime.now()
                })
            
            # Check for recent app usage
            result = subprocess.run(['ps', 'aux'], capture_output=True, text=True)
            user_processes = [line for line in result.stdout.split('\n') 
                            if os.getenv('USER', 'user') in line and 'loginwindow' not in line]
            
            if len(user_processes) > 10:  # Arbitrary threshold for "active" session
                activities.append({
                    'type': 'active_session',
                    'details': f'{len(user_processes)} user processes',
                    'timestamp': datetime.now()
                })
                
        except Exception:
            pass
        
        return activities
    
    def _linux_activity(self):
        """Linux-specific activity detection"""
        activities = []
        
        try:
            # Check if X11 or Wayland session is active
            if os.environ.get('DISPLAY') or os.environ.get('WAYLAND_DISPLAY'):
                activities.append({
                    'type': 'gui_session',
                    'details': 'Graphical session active',
                    'timestamp': datetime.now()
                })
            
            # Check for user processes
            current_user = os.getenv('USER', 'user')
            user_processes = []
            for proc in psutil.process_iter(['pid', 'name', 'username']):
                try:
                    if proc.info['username'] == current_user:
                        user_processes.append(proc.info['name'])
                except (psutil.NoSuchProcess, psutil.AccessDenied):
                    continue
            
            if user_processes:
                activities.append({
                    'type': 'user_processes',
                    'details': f'{len(user_processes)} processes running',
                    'timestamp': datetime.now()
                })
                
        except Exception:
            pass
        
        return activities
    
    def _network_activity(self):
        """Detect network activity indicating user presence"""
        activities = []
        
        try:
            # Get network connections
            connections = psutil.net_connections()
            active_connections = [c for c in connections if c.status == 'ESTABLISHED']
            
            if active_connections:
                activities.append({
                    'type': 'network_activity',
                    'details': f'{len(active_connections)} active connections',
                    'timestamp': datetime.now()
                })
                
        except Exception:
            pass
        
        return activities
    
    def _process_activity(self):
        """Monitor process activity"""
        activities = []
        
        try:
            # Check CPU usage
            cpu_percent = psutil.cpu_percent(interval=1)
            if cpu_percent > 20:  # Above idle threshold
                activities.append({
                    'type': 'cpu_activity',
                    'details': f'CPU usage: {cpu_percent}%',
                    'timestamp': datetime.now()
                })
            
            # Check memory usage changes
            memory = psutil.virtual_memory()
            if memory.percent > 50:  # Moderate memory usage
                activities.append({
                    'type': 'memory_activity',
                    'details': f'Memory usage: {memory.percent}%',
                    'timestamp': datetime.now()
                })
                
        except Exception:
            pass
        
        return activities
    
    def _file_activity(self):
        """Monitor recent file system activity"""
        activities = []
        
        try:
            # Check common user directories for recent modifications
            user_dirs = [
                os.path.expanduser('~/Documents'),
                os.path.expanduser('~/Downloads'),
                os.path.expanduser('~/Desktop'),
                os.path.expanduser('~/Pictures')
            ]
            
            recent_files = []
            cutoff_time = time.time() - (24 * 3600)  # Last 24 hours
            
            for directory in user_dirs:
                if os.path.exists(directory):
                    for root, dirs, files in os.walk(directory):
                        for file in files[:50]:  # Limit to avoid performance issues
                            file_path = os.path.join(root, file)
                            try:
                                if os.path.getmtime(file_path) > cutoff_time:
                                    recent_files.append(file_path)
                            except OSError:
                                continue
                        
                        # Don't recurse too deep
                        if root.count(os.sep) - directory.count(os.sep) >= 2:
                            dirs.clear()
            
            if recent_files:
                activities.append({
                    'type': 'file_activity',
                    'details': f'{len(recent_files)} files modified in last 24h',
                    'timestamp': datetime.now()
                })
                
        except Exception:
            pass
        
        return activities
    
    def log_activity(self, activities):
        """Log detected activities to database"""
        if not activities:
            return
        
        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()
        
        for activity in activities:
            cursor.execute('''
                INSERT INTO activity_log (activity_type, device_id, notes)
                VALUES (?, ?, ?)
            ''', (
                activity['type'],
                platform.node(),  # Computer name as device ID
                activity['details']
            ))
        
        conn.commit()
        conn.close()
        
        print(f"✅ Logged {len(activities)} activities")
    
    def start_monitoring(self):
        """Start continuous monitoring"""
        print(f"🔍 Starting device monitoring on {self.platform}...")
        
        while True:
            try:
                activities = self.detect_user_activity()
                
                if activities:
                    self.log_activity(activities)
                    self.last_activity = datetime.now()
                    
                    # Send heartbeat to main system
                    self.send_heartbeat()
                else:
                    print("🔇 No user activity detected")
                
            except KeyboardInterrupt:
                print("\n⏹️  Monitoring stopped by user")
                break
            except Exception as e:
                print(f"❌ Error during monitoring: {e}")
                
            time.sleep(self.monitoring_interval)
    
    def send_heartbeat(self):
        """Send activity heartbeat to main Death Switch system"""
        try:
            # Import the main system
            from death_switch_system import DeathSwitchAI
            
            # Create instance and record activity
            death_switch = DeathSwitchAI()
            death_switch.record_activity("device_activity", platform.node())
            
        except Exception as e:
            print(f"❌ Failed to send heartbeat: {e}")
    
    def install_startup(self):
        """Install monitor to run at startup"""
        script_path = os.path.abspath(__file__)
        
        if self.platform == "windows":
            # Add to Windows startup folder
            startup_folder = os.path.join(os.getenv('APPDATA'), 
                                        'Microsoft', 'Windows', 'Start Menu', 
                                        'Programs', 'Startup')
            bat_path = os.path.join(startup_folder, 'death_switch_monitor.bat')
            
            with open(bat_path, 'w') as f:
                f.write(f'@echo off\n')
                f.write(f'cd /d "{os.path.dirname(script_path)}"\n')
                f.write(f'python "{script_path}" monitor\n')
            
            print(f"✅ Windows startup script created: {bat_path}")
            
        elif self.platform == "darwin":  # macOS
            # Create launchd plist
            plist_path = os.path.expanduser('~/Library/LaunchAgents/com.deathswitch.monitor.plist')
            plist_content = f'''<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
    <key>Label</key>
    <string>com.deathswitch.monitor</string>
    <key>ProgramArguments</key>
    <array>
        <string>{sys.executable}</string>
        <string>{script_path}</string>
        <string>monitor</string>
    </array>
    <key>RunAtLoad</key>
    <true/>
    <key>KeepAlive</key>
    <true/>
</dict>
</plist>'''
            
            with open(plist_path, 'w') as f:
                f.write(plist_content)
            
            # Load the service
            subprocess.run(['launchctl', 'load', plist_path])
            print(f"✅ macOS launch agent installed: {plist_path}")
            
        elif self.platform == "linux":
            # Create systemd user service
            systemd_dir = os.path.expanduser('~/.config/systemd/user')
            os.makedirs(systemd_dir, exist_ok=True)
            
            service_path = os.path.join(systemd_dir, 'death-switch-monitor.service')
            service_content = f'''[Unit]
Description=Digital Death Switch Activity Monitor
After=graphical-session.target

[Service]
Type=simple
ExecStart={sys.executable} {script_path} monitor
Restart=always
RestartSec=10

[Install]
WantedBy=default.target
'''
            
            with open(service_path, 'w') as f:
                f.write(service_content)
            
            # Enable and start service
            subprocess.run(['systemctl', '--user', 'daemon-reload'])
            subprocess.run(['systemctl', '--user', 'enable', 'death-switch-monitor'])
            subprocess.run(['systemctl', '--user', 'start', 'death-switch-monitor'])
            
            print(f"✅ Linux user service installed: {service_path}")

def main():
    monitor = DeviceMonitor()
    
    if len(sys.argv) > 1:
        command = sys.argv[1]
        
        if command == "monitor":
            monitor.start_monitoring()
        elif command == "install":
            monitor.install_startup()
        elif command == "test":
            activities = monitor.detect_user_activity()
            print("🔍 Detected activities:")
            for activity in activities:
                print(f"  • {activity['type']}: {activity['details']}")
        else:
            print("Usage: python device_monitor.py {monitor|install|test}")
    else:
        print("📱 Digital Death Switch - Device Activity Monitor")
        print("Commands:")
        print("  monitor  - Start continuous monitoring")
        print("  install  - Install to run at startup")
        print("  test     - Test activity detection")

if __name__ == "__main__":
    main()
