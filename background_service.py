#!/usr/bin/env python3
"""
Background Service Setup for Digital Death Switch AI
Converts the interactive system into a background daemon
"""

import sys
import os
import time
import signal
import logging
from pathlib import Path
import subprocess
import json

class DeathSwitchDaemon:
    """Background daemon service for Digital Death Switch"""
    
    def __init__(self, pidfile='/tmp/death_switch.pid'):
        self.pidfile = pidfile
        self.config_file = 'config.json'
        
    def daemonize(self):
        """Convert process to daemon"""
        try:
            # Fork first child
            pid = os.fork()
            if pid > 0:
                sys.exit(0)  # Exit parent
        except OSError as e:
            sys.stderr.write(f"Fork #1 failed: {e}\n")
            sys.exit(1)
            
        # Decouple from parent environment
        os.chdir("/")
        os.setsid()
        os.umask(0)
        
        # Fork second child
        try:
            pid = os.fork()
            if pid > 0:
                sys.exit(0)  # Exit second parent
        except OSError as e:
            sys.stderr.write(f"Fork #2 failed: {e}\n")
            sys.exit(1)
            
        # Redirect standard file descriptors
        sys.stdout.flush()
        sys.stderr.flush()
        
        with open('/dev/null', 'r') as si:
            os.dup2(si.fileno(), sys.stdin.fileno())
        with open('/tmp/death_switch_daemon.log', 'a+') as so:
            os.dup2(so.fileno(), sys.stdout.fileno())
        with open('/tmp/death_switch_daemon.log', 'a+') as se:
            os.dup2(se.fileno(), sys.stderr.fileno())
            
        # Write pidfile
        with open(self.pidfile, 'w') as f:
            f.write(f"{os.getpid()}\n")
            
        # Register signal handlers
        signal.signal(signal.SIGTERM, self.signal_handler)
        signal.signal(signal.SIGINT, self.signal_handler)
    
    def signal_handler(self, signum, frame):
        """Handle shutdown signals"""
        logging.info(f"Received signal {signum}, shutting down...")
        self.cleanup()
        sys.exit(0)
    
    def cleanup(self):
        """Cleanup daemon resources"""
        try:
            os.remove(self.pidfile)
        except:
            pass
    
    def start(self):
        """Start the daemon"""
        # Check if already running
        if os.path.exists(self.pidfile):
            with open(self.pidfile, 'r') as f:
                pid = int(f.read().strip())
            try:
                os.kill(pid, 0)  # Check if process exists
                print("Daemon already running!")
                return
            except OSError:
                os.remove(self.pidfile)
        
        print("Starting Digital Death Switch daemon...")
        self.daemonize()
        self.run_daemon()
    
    def stop(self):
        """Stop the daemon"""
        if not os.path.exists(self.pidfile):
            print("Daemon not running!")
            return
            
        with open(self.pidfile, 'r') as f:
            pid = int(f.read().strip())
            
        try:
            os.kill(pid, signal.SIGTERM)
            time.sleep(1)
            os.kill(pid, 0)  # Check if still running
            os.kill(pid, signal.SIGKILL)  # Force kill
        except OSError:
            pass
        
        try:
            os.remove(self.pidfile)
        except:
            pass
        
        print("Digital Death Switch daemon stopped.")
    
    def restart(self):
        """Restart the daemon"""
        self.stop()
        time.sleep(2)
        self.start()
    
    def status(self):
        """Check daemon status"""
        if not os.path.exists(self.pidfile):
            print("Daemon is not running")
            return False
            
        with open(self.pidfile, 'r') as f:
            pid = int(f.read().strip())
            
        try:
            os.kill(pid, 0)
            print(f"Daemon is running (PID: {pid})")
            return True
        except OSError:
            print("Daemon is not running (stale pidfile)")
            os.remove(self.pidfile)
            return False
    
    def run_daemon(self):
        """Main daemon loop"""
        from death_switch_system import DeathSwitchAI
        
        # Setup logging for daemon
        logging.basicConfig(
            level=logging.INFO,
            format='%(asctime)s - %(levelname)s - %(message)s',
            handlers=[
                logging.FileHandler('/tmp/death_switch_daemon.log'),
            ]
        )
        
        try:
            death_switch = DeathSwitchAI(self.config_file)
            logging.info("Digital Death Switch daemon started successfully")
            
            while True:
                try:
                    death_switch.run_monitoring_cycle()
                    time.sleep(3600)  # Check every hour
                except Exception as e:
                    logging.error(f"Error in monitoring cycle: {e}")
                    time.sleep(300)  # Wait 5 minutes before retry
                    
        except Exception as e:
            logging.error(f"Failed to start daemon: {e}")
            sys.exit(1)

# System service installation functions
def install_systemd_service():
    """Install as systemd service on Linux"""
    service_content = f"""[Unit]
Description=Digital Death Switch AI
After=network.target

[Service]
Type=forking
User={os.getenv('USER', 'root')}
WorkingDirectory={os.getcwd()}
ExecStart={sys.executable} {__file__} start
ExecStop={sys.executable} {__file__} stop
PIDFile=/tmp/death_switch.pid
Restart=always
RestartSec=10

[Install]
WantedBy=multi-user.target
"""
    
    service_path = '/etc/systemd/system/death-switch.service'
    try:
        with open(service_path, 'w') as f:
            f.write(service_content)
        
        # Enable and start service
        subprocess.run(['sudo', 'systemctl', 'daemon-reload'])
        subprocess.run(['sudo', 'systemctl', 'enable', 'death-switch'])
        subprocess.run(['sudo', 'systemctl', 'start', 'death-switch'])
        
        print("✅ Systemd service installed and started!")
        print("Use: sudo systemctl status death-switch")
        
    except Exception as e:
        print(f"❌ Failed to install systemd service: {e}")

def install_windows_service():
    """Install as Windows service"""
    try:
        import win32serviceutil
        import win32service
        import win32event
        import servicemanager
        
        class DeathSwitchWindowsService(win32serviceutil.ServiceFramework):
            _svc_name_ = "DeathSwitchAI"
            _svc_display_name_ = "Digital Death Switch AI"
            _svc_description_ = "Monitors user activity and triggers emergency protocols"
            
            def __init__(self, args):
                win32serviceutil.ServiceFramework.__init__(self, args)
                self.hWaitStop = win32event.CreateEvent(None, 0, 0, None)
                self.daemon = DeathSwitchDaemon()
            
            def SvcStop(self):
                self.ReportServiceStatus(win32service.SERVICE_STOP_PENDING)
                win32event.SetEvent(self.hWaitStop)
                
            def SvcDoRun(self):
                servicemanager.LogMsg(servicemanager.EVENTLOG_INFORMATION_TYPE,
                                    servicemanager.PYS_SERVICE_STARTED,
                                    (self._svc_name_, ''))
                self.daemon.run_daemon()
        
        if len(sys.argv) == 1:
            servicemanager.Initialize()
            servicemanager.PrepareToHostSingle(DeathSwitchWindowsService)
            servicemanager.StartServiceCtrlDispatcher()
        else:
            win32serviceutil.HandleCommandLine(DeathSwitchWindowsService)
            
    except ImportError:
        print("❌ Windows service installation requires pywin32")
        print("Install with: pip install pywin32")

def install_launchd_service():
    """Install as macOS launchd service"""
    plist_content = f"""<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
    <key>Label</key>
    <string>com.deathswitch.ai</string>
    <key>ProgramArguments</key>
    <array>
        <string>{sys.executable}</string>
        <string>{__file__}</string>
        <string>start</string>
    </array>
    <key>WorkingDirectory</key>
    <string>{os.getcwd()}</string>
    <key>RunAtLoad</key>
    <true/>
    <key>KeepAlive</key>
    <true/>
    <key>StandardOutPath</key>
    <string>/tmp/death_switch.log</string>
    <key>StandardErrorPath</key>
    <string>/tmp/death_switch_error.log</string>
</dict>
</plist>
"""
    
    plist_path = f"{os.path.expanduser('~')}/Library/LaunchAgents/com.deathswitch.ai.plist"
    
    try:
        with open(plist_path, 'w') as f:
            f.write(plist_content)
        
        subprocess.run(['launchctl', 'load', plist_path])
        subprocess.run(['launchctl', 'start', 'com.deathswitch.ai'])
        
        print("✅ macOS launchd service installed and started!")
        print(f"Service file: {plist_path}")
        
    except Exception as e:
        print(f"❌ Failed to install launchd service: {e}")

if __name__ == "__main__":
    daemon = DeathSwitchDaemon()
    
    if len(sys.argv) == 2:
        command = sys.argv[1]
        
        if command == 'start':
            daemon.start()
        elif command == 'stop':
            daemon.stop()
        elif command == 'restart':
            daemon.restart()
        elif command == 'status':
            daemon.status()
        elif command == 'install-systemd':
            install_systemd_service()
        elif command == 'install-windows':
            install_windows_service()
        elif command == 'install-macos':
            install_launchd_service()
        else:
            print("Usage: python daemon_service.py {start|stop|restart|status|install-systemd|install-windows|install-macos}")
    else:
        print("Digital Death Switch AI - Background Service")
        print("Usage: python daemon_service.py {start|stop|restart|status}")
        print("\nInstallation commands:")
        print("  install-systemd  - Install as Linux systemd service")
        print("  install-windows  - Install as Windows service")
        print("  install-macos    - Install as macOS launchd service")
