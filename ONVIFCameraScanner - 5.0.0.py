import os
import socket
import threading
import re
import time
from datetime import datetime
from urllib.parse import urlparse, urlencode
import xml.etree.ElementTree as ET
import requests
from requests.auth import HTTPDigestAuth
import subprocess
import json

import cv2
import numpy as np
from onvif import ONVIFCamera
from zeep.exceptions import Fault

import tkinter as tk
from tkinter import ttk, messagebox, filedialog
from PIL import Image, ImageTk


class UniversalCameraScanner:
    def __init__(self):
        self.devices = []
        self.scanning = False
        self.local_ip = self.get_local_ip()
        self.network_prefix = '.'.join(self.local_ip.split('.')[:3]) + '.'
        
        # Extended protocol and port configuration
        self.protocol_config = {
            'ONVIF': {'ports': [80, 8000, 8080], 'enabled': True},
            'GB28181': {'ports': [5060, 5061], 'enabled': True},
            'RTSP': {'ports': [554, 8554], 'enabled': True},
            'HTTP': {'ports': [80, 8080, 8000], 'enabled': True},
            'RTMP': {'ports': [1935], 'enabled': False},
            'P2P': {'ports': [], 'enabled': False},
            'GigE': {'ports': [3956], 'enabled': False},
            'WebRTC': {'ports': [3478, 5349], 'enabled': False},
            'SIP': {'ports': [5060], 'enabled': False},
            'GenICam': {'ports': [3956], 'enabled': False}
        }
        
        self.common_credentials = [
            ('admin', 'admin'),
            ('admin', '12345'),
            ('admin', '123456'),
            ('admin', ''),
            ('', '')
        ]
        
        self.rtsp_paths = [
            '/live.sdp',
            '/streaming/channels/1',
            '/cam/realmonitor?channel=1&subtype=0',
            '/11',
            '/1',
            '/Streaming/Channels/101'
        ]
        
        self.http_paths = [
            '/video',
            '/mjpg/video.mjpg',
            '/cgi-bin/mjpg/video.cgi',
            '/cameras/camera1/mjpeg',
            '/stream',
            '/cgi-bin/gb28181.cgi'
        ]

    def get_local_ip(self):
        """Get local IP address"""
        try:
            s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
            s.connect(('8.8.8.8', 80))
            ip = s.getsockname()[0]
            s.close()
            return ip
        except Exception:
            return '127.0.0.1'

    def scan_network(self, start=1, end=255, timeout=1):
        """Scan for camera devices on the network"""
        self.devices = []
        self.scanning = True
        
        def check_device(ip):
            if not self.scanning:
                return
                
            # Collect all ports to scan
            ports_to_scan = set()
            for protocol, config in self.protocol_config.items():
                if config['enabled']:
                    ports_to_scan.update(config['ports'])
            
            # First check if any ports are open
            open_ports = []
            for port in ports_to_scan:
                try:
                    sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
                    sock.settimeout(timeout)
                    result = sock.connect_ex((ip, port))
                    sock.close()
                    if result == 0:
                        open_ports.append(port)
                except:
                    continue
            
            if not open_ports:
                return
                
            # Check protocols in priority order
            if self.protocol_config['ONVIF']['enabled']:
                device_info = self.check_onvif(ip, open_ports)
                if device_info:
                    self.devices.append(device_info)
                    return
                    
            if self.protocol_config['GB28181']['enabled']:
                device_info = self.check_gb28181(ip, open_ports)
                if device_info:
                    self.devices.append(device_info)
                    return
                    
            if self.protocol_config['RTSP']['enabled']:
                device_info = self.check_rtsp(ip, open_ports)
                if device_info:
                    self.devices.append(device_info)
                    return
                    
            if self.protocol_config['HTTP']['enabled']:
                device_info = self.check_http(ip, open_ports)
                if device_info:
                    self.devices.append(device_info)
                    return
                    
            if self.protocol_config['GenICam']['enabled']:
                device_info = self.check_genican(ip, open_ports)
                if device_info:
                    self.devices.append(device_info)
                    return

        threads = []
        for i in range(start, end + 1):
            ip = f"{self.network_prefix}{i}"
            t = threading.Thread(target=check_device, args=(ip,))
            t.start()
            threads.append(t)
            
        for t in threads:
            t.join(timeout + 1)
            
        self.scanning = False
        return self.devices

    def check_onvif(self, ip, ports):
        """Check if device supports ONVIF"""
        for port in ports:
            if port not in self.protocol_config['ONVIF']['ports']:
                continue
                
            for cred in self.common_credentials:
                try:
                    cam = ONVIFCamera(ip, port, cred[0], cred[1])
                    media_service = cam.create_media_service()
                    profiles = media_service.GetProfiles()
                    
                    if profiles:
                        dev_info = cam.devicemgmt.GetDeviceInformation()
                        stream_uri = media_service.GetStreamUri({
                            'StreamSetup': {'Stream': 'RTP-Unicast', 'Transport': {'Protocol': 'RTSP'}},
                            'ProfileToken': profiles[0].token
                        })
                        
                        return {
                            'ip': ip,
                            'port': port,
                            'username': cred[0],
                            'password': cred[1],
                            'name': dev_info.Model if dev_info.Model else 'Unknown Device',
                            'manufacturer': dev_info.Manufacturer if dev_info.Manufacturer else 'Unknown',
                            'hardware': dev_info.HardwareId if dev_info.HardwareId else 'Unknown',
                            'firmware': dev_info.FirmwareVersion if dev_info.FirmwareVersion else 'Unknown',
                            'protocol': 'ONVIF',
                            'stream_url': stream_uri.Uri,
                            'capabilities': self.get_onvif_capabilities(cam)
                        }
                except Exception as e:
                    continue
        return None

    def get_onvif_capabilities(self, cam):
        """Get ONVIF device capabilities"""
        capabilities = {}
        try:
            devicemgmt = cam.devicemgmt
            capabilities['device'] = devicemgmt.GetDeviceInformation()
            capabilities['network'] = devicemgmt.GetNetworkInterfaces()
            if cam.has_ptz:
                capabilities['ptz'] = cam.create_ptz_service().GetConfigurations()
            return capabilities
        except Exception as e:
            return None

    def check_gb28181(self, ip, ports):
        """Check if device supports GB/T 28181"""
        for port in ports:
            if port not in self.protocol_config['GB28181']['ports']:
                continue
                
            # Try sending OPTIONS request
            try:
                sip_options = f"OPTIONS sip:{ip} SIP/2.0\r\n" \
                             f"Via: SIP/2.0/UDP {self.local_ip}:5060;branch=z9hG4bK123456\r\n" \
                             f"From: <sip:admin@{self.local_ip}>;tag=12345\r\n" \
                             f"To: <sip:admin@{ip}>\r\n" \
                             f"Call-ID: 123456@{self.local_ip}\r\n" \
                             f"CSeq: 1 OPTIONS\r\n" \
                             f"Contact: <sip:admin@{self.local_ip}:5060>\r\n" \
                             f"Max-Forwards: 70\r\n" \
                             f"User-Agent: CameraScanner\r\n" \
                             f"Content-Length: 0\r\n\r\n"
                
                sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
                sock.settimeout(2)
                sock.sendto(sip_options.encode(), (ip, port))
                data, addr = sock.recvfrom(1024)
                sock.close()
                
                if b"SIP/2.0 200 OK" in data:
                    # Try to get device info
                    try:
                        catalog_url = f"http://{ip}:80/cgi-bin/gb28181.cgi?cmd=query&type=catalog"
                        response = requests.get(catalog_url, timeout=3)
                        if response.status_code == 200:
                            root = ET.fromstring(response.text)
                            device_id = root.find(".//DeviceID").text
                            device_name = root.find(".//Name").text if root.find(".//Name") is not None else "GB/T 28181 Device"
                            
                            # Get stream URL
                            stream_url = f"rtsp://{ip}:554/Streaming/Channels/101?transportmode=unicast&profile=Profile_1"
                            
                            return {
                                'ip': ip,
                                'port': port,
                                'username': 'admin',
                                'password': 'admin',
                                'name': device_name,
                                'manufacturer': 'GB/T 28181 Device',
                                'protocol': 'GB28181',
                                'stream_url': stream_url,
                                'device_id': device_id
                            }
                    except:
                        # If we can't get details, at least we know it supports GB/T 28181
                        return {
                            'ip': ip,
                            'port': port,
                            'username': 'admin',
                            'password': 'admin',
                            'name': 'GB/T 28181 Device',
                            'manufacturer': 'Unknown',
                            'protocol': 'GB28181',
                            'stream_url': f"rtsp://{ip}:554/Streaming/Channels/101"
                        }
            except:
                continue
        return None

    def check_rtsp(self, ip, ports):
        """Check if device supports RTSP"""
        for port in ports:
            if port not in self.protocol_config['RTSP']['ports']:
                continue
                
            for cred in self.common_credentials:
                for path in self.rtsp_paths:
                    rtsp_url = f"rtsp://{ip}:{port}{path}"
                    if cred[0] or cred[1]:
                        rtsp_url = f"rtsp://{cred[0]}:{cred[1]}@{ip}:{port}{path}"
                    
                    cap = cv2.VideoCapture(rtsp_url)
                    if cap.isOpened():
                        cap.release()
                        return {
                            'ip': ip,
                            'port': port,
                            'username': cred[0],
                            'password': cred[1],
                            'name': 'RTSP Camera',
                            'manufacturer': 'Unknown',
                            'protocol': 'RTSP',
                            'stream_url': rtsp_url
                        }
        return None

    def check_http(self, ip, ports):
        """Check if device supports HTTP MJPEG"""
        for port in ports:
            if port not in self.protocol_config['HTTP']['ports']:
                continue
                
            for path in self.http_paths:
                http_url = f"http://{ip}:{port}{path}"
                cap = cv2.VideoCapture(http_url)
                if cap.isOpened():
                    cap.release()
                    return {
                        'ip': ip,
                        'port': port,
                        'username': '',
                        'password': '',
                        'name': 'HTTP Camera',
                        'manufacturer': 'Unknown',
                        'protocol': 'HTTP',
                        'stream_url': http_url
                    }
        return None

    def check_genican(self, ip, ports):
        """Check if device supports GenICam/GigE Vision"""
        for port in ports:
            if port not in self.protocol_config['GenICam']['ports']:
                continue
                
            try:
                # Try to discover device via GigE Vision protocol
                discovery_cmd = ['gev-discovery', '-n', ip]
                result = subprocess.run(discovery_cmd, capture_output=True, text=True, timeout=5)
                if result.returncode == 0:
                    # Parse discovery result
                    device_info = {
                        'ip': ip,
                        'port': port,
                        'name': 'GenICam/GigE Vision Device',
                        'manufacturer': 'Industrial Camera',
                        'protocol': 'GenICam',
                        'stream_url': f"gev://{ip}"
                    }
                    return device_info
            except:
                continue
        return None


class UniversalCameraViewerApp:
    def __init__(self, root):
        self.root = root
        self.root.title("Universal Camera Management System")
        self.root.geometry("1200x800")
        self.root.minsize(1000, 700)
        
        # Initialize variables
        self.scanner = UniversalCameraScanner()
        self.current_camera = None
        self.camera_thread = None
        self.running = False
        self.video_frame = None
        self.photo = None
        self.cap = None
        self.protocol_vars = {}  # Store protocol selection states
        
        # Setup styles
        self.setup_styles()
        
        # Create UI
        self.setup_ui()
        
        # Bind window close event
        self.root.protocol("WM_DELETE_WINDOW", self.on_close)

    def setup_styles(self):
        """Setup UI styles"""
        style = ttk.Style()
        style.theme_use('clam')
        style.configure('.', font=('Microsoft YaHei', 10))
        style.configure('TFrame', background='#f0f0f0')
        style.configure('TLabel', background='#f0f0f0')
        style.configure('TButton', padding=5)
        style.configure('Header.TLabel', font=('Microsoft YaHei', 12, 'bold'))
        style.configure('Treeview', rowheight=25)
        style.configure('Treeview.Heading', font=('Microsoft YaHei', 10, 'bold'))
        style.map('TButton', background=[('active', '#e0e0e0')])

    def setup_ui(self):
        """Setup user interface"""
        # Main frame
        main_frame = ttk.Frame(self.root)
        main_frame.pack(fill=tk.BOTH, expand=True, padx=10, pady=10)
        
        # Left panel - device list and controls
        left_panel = ttk.Frame(main_frame, width=400)
        left_panel.pack(side=tk.LEFT, fill=tk.Y, padx=(0, 10))
        left_panel.pack_propagate(False)
        
        # Right panel - video preview and advanced controls
        right_panel = ttk.Frame(main_frame)
        right_panel.pack(side=tk.RIGHT, fill=tk.BOTH, expand=True)
        
        # Device scanning section
        scan_frame = ttk.LabelFrame(left_panel, text="Device Scanning Configuration", padding=10)
        scan_frame.pack(fill=tk.X, pady=(0, 10))
        
        # IP range settings
        ip_range_frame = ttk.Frame(scan_frame)
        ip_range_frame.pack(fill=tk.X, pady=(0, 10))
        
        ttk.Label(ip_range_frame, text="IP Range:").pack(side=tk.LEFT)
        self.ip_start = ttk.Entry(ip_range_frame, width=8)
        self.ip_start.pack(side=tk.LEFT, padx=(0, 10))
        self.ip_start.insert(0, "1")
        
        ttk.Label(ip_range_frame, text="to").pack(side=tk.LEFT, padx=5)
        
        self.ip_end = ttk.Entry(ip_range_frame, width=8)
        self.ip_end.pack(side=tk.LEFT)
        self.ip_end.insert(0, "255")
        
        # Protocol selection
        protocol_frame = ttk.LabelFrame(scan_frame, text="Select Protocols to Scan", padding=5)
        protocol_frame.pack(fill=tk.X, pady=(0, 10))
        
        protocol_col1 = ttk.Frame(protocol_frame)
        protocol_col1.pack(side=tk.LEFT, fill=tk.X, expand=True)
        
        protocol_col2 = ttk.Frame(protocol_frame)
        protocol_col2.pack(side=tk.LEFT, fill=tk.X, expand=True)
        
        # Create protocol checkboxes
        protocols = [
            ('ONVIF', protocol_col1),
            ('GB28181', protocol_col1),
            ('RTSP', protocol_col1),
            ('HTTP', protocol_col1),
            ('GenICam', protocol_col2),
            ('RTMP', protocol_col2),
            ('P2P', protocol_col2),
            ('WebRTC', protocol_col2)
        ]
        
        for protocol, parent in protocols:
            var = tk.BooleanVar(value=protocol in ['ONVIF', 'GB28181', 'RTSP', 'HTTP'])
            self.protocol_vars[protocol] = var
            cb = ttk.Checkbutton(parent, text=protocol, variable=var)
            cb.pack(anchor=tk.W)
        
        scan_btn = ttk.Button(scan_frame, text="Start Scan", command=self.start_scan)
        scan_btn.pack(fill=tk.X)
        
        # Device list
        device_frame = ttk.LabelFrame(left_panel, text="Device List", padding=10)
        device_frame.pack(fill=tk.BOTH, expand=True)
        
        self.device_tree = ttk.Treeview(device_frame, columns=('ip', 'name', 'protocol', 'manufacturer'), show='headings')
        self.device_tree.heading('ip', text="IP Address")
        self.device_tree.heading('name', text="Device Name")
        self.device_tree.heading('protocol', text="Protocol")
        self.device_tree.heading('manufacturer', text="Manufacturer")
        
        self.device_tree.column('ip', width=120)
        self.device_tree.column('name', width=120)
        self.device_tree.column('protocol', width=100)
        self.device_tree.column('manufacturer', width=120)
        
        scrollbar = ttk.Scrollbar(device_frame, orient=tk.VERTICAL, command=self.device_tree.yview)
        self.device_tree.configure(yscrollcommand=scrollbar.set)
        
        self.device_tree.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)
        scrollbar.pack(side=tk.RIGHT, fill=tk.Y)
        
        self.device_tree.bind('<<TreeviewSelect>>', self.on_device_select)
        
        # Device info
        info_frame = ttk.LabelFrame(left_panel, text="Device Details", padding=10)
        info_frame.pack(fill=tk.X, pady=(10, 0))
        
        self.info_text = tk.Text(info_frame, height=10, font=('Microsoft YaHei', 9), wrap=tk.WORD)
        self.info_text.pack(fill=tk.BOTH)
        self.info_text.config(state=tk.DISABLED)
        
        # Control buttons
        btn_frame = ttk.Frame(left_panel)
        btn_frame.pack(fill=tk.X, pady=(10, 0))
        
        self.connect_btn = ttk.Button(btn_frame, text="Connect", command=self.connect_camera, state=tk.DISABLED)
        self.connect_btn.pack(side=tk.LEFT, fill=tk.X, expand=True, padx=(0, 5))
        
        self.disconnect_btn = ttk.Button(btn_frame, text="Disconnect", command=self.disconnect_camera, state=tk.DISABLED)
        self.disconnect_btn.pack(side=tk.LEFT, fill=tk.X, expand=True)
        
        # Video preview section
        preview_frame = ttk.LabelFrame(right_panel, text="Video Preview", padding=10)
        preview_frame.pack(fill=tk.BOTH, expand=True)
        
        self.video_label = ttk.Label(preview_frame, text="No camera connected", anchor=tk.CENTER)
        self.video_label.pack(fill=tk.BOTH, expand=True)
        
        # Video control buttons
        control_frame = ttk.Frame(right_panel)
        control_frame.pack(fill=tk.X, pady=(10, 0))
        
        self.snapshot_btn = ttk.Button(control_frame, text="Snapshot", command=self.take_snapshot, state=tk.DISABLED)
        self.snapshot_btn.pack(side=tk.LEFT, padx=(0, 5))
        
        self.record_btn = ttk.Button(control_frame, text="Start Recording", command=self.toggle_recording, state=tk.DISABLED)
        self.record_btn.pack(side=tk.LEFT, padx=(0, 5))
        
        self.ptz_btn = ttk.Button(control_frame, text="PTZ Control", command=self.show_ptz_control, state=tk.DISABLED)
        self.ptz_btn.pack(side=tk.LEFT)
        
        # Advanced features tabs
        notebook = ttk.Notebook(right_panel)
        notebook.pack(fill=tk.BOTH, expand=True, pady=(10, 0))
        
        # Stream info tab
        stream_tab = ttk.Frame(notebook)
        notebook.add(stream_tab, text="Stream Info")
        
        self.stream_info = tk.Text(stream_tab, font=('Microsoft YaHei', 9), wrap=tk.WORD)
        self.stream_info.pack(fill=tk.BOTH, expand=True)
        self.stream_info.config(state=tk.DISABLED)
        
        # Device config tab
        config_tab = ttk.Frame(notebook)
        notebook.add(config_tab, text="Device Config")
        
        self.config_info = tk.Text(config_tab, font=('Microsoft YaHei', 9), wrap=tk.WORD)
        self.config_info.pack(fill=tk.BOTH, expand=True)
        self.config_info.config(state=tk.DISABLED)
        
        # Status bar
        self.status_var = tk.StringVar()
        self.status_var.set("Ready")
        
        status_bar = ttk.Frame(right_panel, height=20)
        status_bar.pack(fill=tk.X, pady=(10, 0))
        
        ttk.Label(status_bar, textvariable=self.status_var, relief=tk.SUNKEN, anchor=tk.W).pack(fill=tk.X)
        
        # Initialize variables
        self.recording = False
        self.video_writer = None
        self.record_start_time = None

    def start_scan(self):
        """Start scanning for camera devices on the network"""
        try:
            start = int(self.ip_start.get())
            end = int(self.ip_end.get())
            
            if start < 1 or end > 255 or start > end:
                messagebox.showerror("Error", "Invalid IP range, please enter numbers between 1-255")
                return
                
            # Clear device list
            for item in self.device_tree.get_children():
                self.device_tree.delete(item)
                
            self.info_text.config(state=tk.NORMAL)
            self.info_text.delete(1.0, tk.END)
            self.info_text.insert(tk.END, "Scanning network...")
            self.info_text.config(state=tk.DISABLED)
            
            self.status_var.set("Scanning network...")
            self.connect_btn.config(state=tk.DISABLED)
            
            # Set scanning protocols
            for protocol, var in self.protocol_vars.items():
                if protocol in self.scanner.protocol_config:
                    self.scanner.protocol_config[protocol]['enabled'] = var.get()
            
            # Execute scan in new thread
            threading.Thread(target=self.do_scan, args=(start, end), daemon=True).start()
            
        except ValueError:
            messagebox.showerror("Error", "Please enter valid numbers")

    def do_scan(self, start, end):
        """Perform the scan operation"""
        devices = self.scanner.scan_network(start, end)
        
        self.root.after(0, self.update_device_list, devices)
        
    def update_device_list(self, devices):
        """Update the device list"""
        for item in self.device_tree.get_children():
            self.device_tree.delete(item)
            
        for device in devices:
            self.device_tree.insert('', tk.END, values=(
                device['ip'],
                device['name'],
                device['protocol'],
                device['manufacturer']
            ))
            
        self.info_text.config(state=tk.NORMAL)
        self.info_text.delete(1.0, tk.END)
        
        if devices:
            self.info_text.insert(tk.END, f"Scan complete, found {len(devices)} devices")
            self.status_var.set(f"Scan complete, found {len(devices)} devices")
        else:
            self.info_text.insert(tk.END, "Scan complete, no cameras found")
            self.status_var.set("Scan complete, no cameras found")
            
        self.info_text.config(state=tk.DISABLED)
        
    def on_device_select(self, event):
        """Update info when device is selected"""
        selected = self.device_tree.focus()
        if not selected:
            return
            
        device_data = self.device_tree.item(selected, 'values')
        if not device_data:
            return
            
        # Find corresponding device info from scan results
        for device in self.scanner.devices:
            if device['ip'] == device_data[0]:
                self.current_camera = device
                break
                
        if not self.current_camera:
            return
            
        self.info_text.config(state=tk.NORMAL)
        self.info_text.delete(1.0, tk.END)
        self.info_text.insert(tk.END, f"IP Address: {self.current_camera['ip']}\n")
        self.info_text.insert(tk.END, f"Device Name: {self.current_camera['name']}\n")
        self.info_text.insert(tk.END, f"Manufacturer: {self.current_camera['manufacturer']}\n")
        self.info_text.insert(tk.END, f"Protocol: {self.current_camera['protocol']}\n")
        
        if 'port' in self.current_camera:
            self.info_text.insert(tk.END, f"Port: {self.current_camera['port']}\n")
            
        if 'username' in self.current_camera:
            self.info_text.insert(tk.END, f"Username: {self.current_camera['username']}\n")
            
        if 'password' in self.current_camera:
            self.info_text.insert(tk.END, f"Password: {'*' * len(self.current_camera['password'])}\n")
            
        if 'stream_url' in self.current_camera:
            self.info_text.insert(tk.END, f"Stream URL: {self.current_camera['stream_url']}\n")
            
        # Update stream info tab
        self.stream_info.config(state=tk.NORMAL)
        self.stream_info.delete(1.0, tk.END)
        if 'stream_url' in self.current_camera:
            self.stream_info.insert(tk.END, f"Stream URL:\n{self.current_camera['stream_url']}\n\n")
            
            # Try to get stream info
            if self.current_camera['protocol'] in ['RTSP', 'ONVIF', 'GB28181']:
                try:
                    cap = cv2.VideoCapture(self.current_camera['stream_url'])
                    if cap.isOpened():
                        width = int(cap.get(cv2.CAP_PROP_FRAME_WIDTH))
                        height = int(cap.get(cv2.CAP_PROP_FRAME_HEIGHT))
                        fps = cap.get(cv2.CAP_PROP_FPS)
                        codec = int(cap.get(cv2.CAP_PROP_FOURCC))
                        codec_str = "".join([chr((codec >> 8 * i) & 0xFF) for i in range(4)])
                        cap.release()
                        
                        self.stream_info.insert(tk.END, f"Resolution: {width}x{height}\n")
                        self.stream_info.insert(tk.END, f"Frame Rate: {fps:.2f}\n")
                        self.stream_info.insert(tk.END, f"Codec: {codec_str}\n")
                except:
                    pass
                    
        # Update device config tab
        self.config_info.config(state=tk.NORMAL)
        self.config_info.delete(1.0, tk.END)
        if 'capabilities' in self.current_camera and self.current_camera['capabilities']:
            try:
                caps = self.current_camera['capabilities']
                if caps.get('device'):
                    self.config_info.insert(tk.END, "Device Info:\n")
                    self.config_info.insert(tk.END, f"Model: {caps['device'].Model}\n")
                    self.config_info.insert(tk.END, f"Firmware: {caps['device'].FirmwareVersion}\n")
                    self.config_info.insert(tk.END, f"Serial: {caps['device'].SerialNumber}\n\n")
                
                if caps.get('ptz'):
                    self.config_info.insert(tk.END, "PTZ Capabilities:\n")
                    self.config_info.insert(tk.END, f"PTZ Supported: Yes\n")
                    self.config_info.insert(tk.END, f"Max Speed: {caps['ptz'][0].PTZSpeed.PanTilt._x} (Pan), {caps['ptz'][0].PTZSpeed.PanTilt._y} (Tilt)\n")
            except:
                pass
                
        self.info_text.config(state=tk.DISABLED)
        self.stream_info.config(state=tk.DISABLED)
        self.config_info.config(state=tk.DISABLED)
        
        self.connect_btn.config(state=tk.NORMAL)
        self.ptz_btn.config(state=tk.NORMAL if self.current_camera['protocol'] == 'ONVIF' else tk.DISABLED)
        
    def connect_camera(self):
        """Connect to selected camera"""
        if not self.current_camera:
            return
            
        ip = self.current_camera['ip']
        
        self.status_var.set(f"Connecting to {ip}...")
        self.connect_btn.config(state=tk.DISABLED)
        
        # Connect camera in new thread
        threading.Thread(target=self.do_connect_camera, daemon=True).start()
        
    def do_connect_camera(self):
        """Perform camera connection"""
        try:
            stream_url = self.current_camera.get('stream_url', '')
            
            if not stream_url:
                self.root.after(0, self.show_error, "Cannot get stream URL")
                return
                
            # Handle different protocol types
            if self.current_camera['protocol'] in ['ONVIF', 'RTSP', 'GB28181']:
                # RTSP stream
                if 'username' in self.current_camera and 'password' in self.current_camera:
                    # If URL doesn't contain credentials but device info does, add them
                    if f"{self.current_camera['username']}:{self.current_camera['password']}@" not in stream_url:
                        parsed = urlparse(stream_url)
                        stream_url = f"{parsed.scheme}://{self.current_camera['username']}:{self.current_camera['password']}@{parsed.netloc}{parsed.path}"
                
                self.cap = cv2.VideoCapture(stream_url)
                
            elif self.current_camera['protocol'] == 'HTTP':
                # HTTP MJPEG stream
                self.cap = cv2.VideoCapture(stream_url)
                
            elif self.current_camera['protocol'] == 'GenICam':
                # Industrial camera stream
                try:
                    self.cap = cv2.VideoCapture(stream_url)
                except:
                    self.root.after(0, self.show_error, "GenICam/GigE Vision libraries required")
                    return
                
            if not self.cap.isOpened():
                self.root.after(0, self.show_error, "Cannot open video stream")
                return
                
            # Update UI
            self.root.after(0, self.on_camera_connected)
            
        except Exception as e:
            self.root.after(0, self.show_error, f"Connection error: {str(e)}")
            
    def on_camera_connected(self):
        """Callback when camera is successfully connected"""
        self.status_var.set(f"Connected to {self.current_camera['ip']}")
        
        # Update button states
        self.connect_btn.config(state=tk.DISABLED)
        self.disconnect_btn.config(state=tk.NORMAL)
        self.snapshot_btn.config(state=tk.NORMAL)
        self.record_btn.config(state=tk.NORMAL)
        
        # Start video stream
        self.running = True
        self.camera_thread = threading.Thread(target=self.update_video, daemon=True)
        self.camera_thread.start()
        
    def update_video(self):
        """Update video frames"""
        while self.running and self.cap.isOpened():
            ret, frame = self.cap.read()
            if not ret:
                self.root.after(0, self.show_error, "Cannot get video stream")
                break
                
            # Convert color space
            frame = cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)
            
            # Resize to fit window
            height, width = frame.shape[:2]
            max_size = 800
            if width > max_size or height > max_size:
                ratio = min(max_size/width, max_size/height)
                frame = cv2.resize(frame, (int(width*ratio), int(height*ratio)))
            
            # Convert to PhotoImage
            img = Image.fromarray(frame)
            self.photo = ImageTk.PhotoImage(image=img)
            
            # Update UI
            self.root.after(0, self.update_frame, self.photo)
            
            # If recording, write to video
            if self.recording and self.video_writer:
                frame_bgr = cv2.cvtColor(frame, cv2.COLOR_RGB2BGR)
                self.video_writer.write(frame_bgr)
            
    def update_frame(self, photo):
        """Update video frame display"""
        self.video_label.config(image=photo)
        self.video_label.image = photo
        
    def disconnect_camera(self):
        """Disconnect from camera"""
        self.running = False
        if self.camera_thread and self.camera_thread.is_alive():
            self.camera_thread.join(timeout=1)
            
        if self.cap:
            self.cap.release()
            self.cap = None
            
        if self.recording:
            self.stop_recording()
            
        self.video_label.config(image=None, text="No camera connected")
        
        # Update button states
        self.connect_btn.config(state=tk.NORMAL)
        self.disconnect_btn.config(state=tk.DISABLED)
        self.snapshot_btn.config(state=tk.DISABLED)
        self.record_btn.config(state=tk.DISABLED)
        self.record_btn.config(text="Start Recording")
        self.ptz_btn.config(state=tk.DISABLED)
        
        self.status_var.set("Disconnected")
        
    def take_snapshot(self):
        """Take snapshot"""
        if not self.photo:
            return
            
        # Get current time for filename
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        filename = f"snapshot_{timestamp}.png"
        
        # Let user choose save location
        filepath = filedialog.asksaveasfilename(
            initialfile=filename,
            defaultextension=".png",
            filetypes=[("PNG Image", "*.png"), ("JPEG Image", "*.jpg"), ("All Files", "*.*")]
        )
        
        if filepath:
            try:
                # Save image
                img = ImageTk.getimage(self.photo)
                img.save(filepath)
                self.status_var.set(f"Snapshot saved to {filepath}")
            except Exception as e:
                messagebox.showerror("Error", f"Failed to save snapshot: {str(e)}")
                
    def toggle_recording(self):
        """Start/stop recording"""
        if self.recording:
            self.stop_recording()
        else:
            self.start_recording()
            
    def start_recording(self):
        """Start video recording"""
        # Get current time for filename
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        filename = f"recording_{timestamp}.avi"
        
        # Let user choose save location
        filepath = filedialog.asksaveasfilename(
            initialfile=filename,
            defaultextension=".avi",
            filetypes=[("AVI Video", "*.avi"), ("MP4 Video", "*.mp4"), ("All Files", "*.*")]
        )
        
        if filepath:
            try:
                # Get video frame size
                img = ImageTk.getimage(self.photo)
                width, height = img.size
                
                # Choose codec based on file extension
                ext = os.path.splitext(filepath)[1].lower()
                if ext == '.mp4':
                    fourcc = cv2.VideoWriter_fourcc(*'mp4v')
                else:
                    fourcc = cv2.VideoWriter_fourcc(*'XVID')
                
                self.video_writer = cv2.VideoWriter(filepath, fourcc, 20.0, (width, height))
                
                self.recording = True
                self.record_start_time = datetime.now()
                self.record_btn.config(text="Stop Recording")
                self.status_var.set(f"Recording to {filepath}")
            except Exception as e:
                messagebox.showerror("Error", f"Failed to start recording: {str(e)}")
                
    def stop_recording(self):
        """Stop video recording"""
        if self.video_writer:
            self.video_writer.release()
            self.video_writer = None
            
        self.recording = False
        duration = datetime.now() - self.record_start_time
        self.record_btn.config(text="Start Recording")
        self.status_var.set(f"Recording stopped, duration: {duration.seconds} seconds")
        
    def show_ptz_control(self):
        """Show PTZ control panel"""
        if not self.current_camera or self.current_camera['protocol'] != 'ONVIF':
            return
            
        ptz_window = tk.Toplevel(self.root)
        ptz_window.title("PTZ Control")
        ptz_window.geometry("300x300")
        
        # Create control buttons
        control_frame = ttk.Frame(ptz_window)
        control_frame.pack(pady=10)
        
        # Up
        btn_up = ttk.Button(control_frame, text="↑", command=lambda: self.ptz_move('up'))
        btn_up.grid(row=0, column=1, padx=5, pady=5)
        
        # Left
        btn_left = ttk.Button(control_frame, text="←", command=lambda: self.ptz_move('left'))
        btn_left.grid(row=1, column=0, padx=5, pady=5)
        
        # Right
        btn_right = ttk.Button(control_frame, text="→", command=lambda: self.ptz_move('right'))
        btn_right.grid(row=1, column=2, padx=5, pady=5)
        
        # Down
        btn_down = ttk.Button(control_frame, text="↓", command=lambda: self.ptz_move('down'))
        btn_down.grid(row=2, column=1, padx=5, pady=5)
        
        # Stop
        btn_stop = ttk.Button(control_frame, text="Stop", command=lambda: self.ptz_move('stop'))
        btn_stop.grid(row=1, column=1, padx=5, pady=5)
        
        # Zoom control
        zoom_frame = ttk.Frame(ptz_window)
        zoom_frame.pack(pady=10)
        
        btn_zoom_in = ttk.Button(zoom_frame, text="Zoom In", command=lambda: self.ptz_zoom('in'))
        btn_zoom_in.pack(side=tk.LEFT, padx=5)
        
        btn_zoom_out = ttk.Button(zoom_frame, text="Zoom Out", command=lambda: self.ptz_zoom('out'))
        btn_zoom_out.pack(side=tk.LEFT, padx=5)
        
        btn_zoom_stop = ttk.Button(zoom_frame, text="Stop", command=lambda: self.ptz_zoom('stop'))
        btn_zoom_stop.pack(side=tk.LEFT, padx=5)
        
    def ptz_move(self, direction):
        """Control PTZ movement"""
        if not self.current_camera or self.current_camera['protocol'] != 'ONVIF':
            return
            
        try:
            cam = ONVIFCamera(
                self.current_camera['ip'],
                self.current_camera['port'],
                self.current_camera['username'],
                self.current_camera['password']
            )
            ptz = cam.create_ptz_service()
            
            # Get current PTZ status
            status = ptz.GetStatus({'ProfileToken': cam.media.GetProfiles()[0]._token})
            
            # Set movement speed
            speed = 0.5  # Medium speed
            
            # Create move request
            move_request = {
                'ProfileToken': cam.media.GetProfiles()[0]._token,
                'Velocity': {
                    'PanTilt': {
                        '_x': 0,
                        '_y': 0
                    }
                }
            }
            
            if direction == 'up':
                move_request['Velocity']['PanTilt']['_y'] = speed
            elif direction == 'down':
                move_request['Velocity']['PanTilt']['_y'] = -speed
            elif direction == 'left':
                move_request['Velocity']['PanTilt']['_x'] = -speed
            elif direction == 'right':
                move_request['Velocity']['PanTilt']['_x'] = speed
            elif direction == 'stop':
                move_request['Velocity']['PanTilt']['_x'] = 0
                move_request['Velocity']['PanTilt']['_y'] = 0
            
            ptz.ContinuousMove(move_request)
            
        except Exception as e:
            messagebox.showerror("Error", f"PTZ control failed: {str(e)}")
            
    def ptz_zoom(self, action):
        """Control PTZ zoom"""
        if not self.current_camera or self.current_camera['protocol'] != 'ONVIF':
            return
            
        try:
            cam = ONVIFCamera(
                self.current_camera['ip'],
                self.current_camera['port'],
                self.current_camera['username'],
                self.current_camera['password']
            )
            ptz = cam.create_ptz_service()
            
            # Set zoom speed
            speed = 0.5  # Medium speed
            
            # Create zoom request
            zoom_request = {
                'ProfileToken': cam.media.GetProfiles()[0]._token,
                'Velocity': {
                    'Zoom': {
                        '_x': 0
                    }
                }
            }
            
            if action == 'in':
                zoom_request['Velocity']['Zoom']['_x'] = speed
            elif action == 'out':
                zoom_request['Velocity']['Zoom']['_x'] = -speed
            elif action == 'stop':
                zoom_request['Velocity']['Zoom']['_x'] = 0
            
            ptz.ContinuousMove(zoom_request)
            
        except Exception as e:
            messagebox.showerror("Error", f"Zoom control failed: {str(e)}")
        
    def show_error(self, message):
        """Show error message"""
        messagebox.showerror("Error", message)
        self.status_var.set(message)
        
    def on_close(self):
        """Cleanup when window is closed"""
        self.running = False
        if self.camera_thread and self.camera_thread.is_alive():
            self.camera_thread.join(timeout=1)
            
        if self.cap:
            self.cap.release()
            
        if self.recording:
            self.stop_recording()
            
        self.root.destroy()


if __name__ == "__main__":
    root = tk.Tk()
    app = UniversalCameraViewerApp(root)
    root.mainloop()