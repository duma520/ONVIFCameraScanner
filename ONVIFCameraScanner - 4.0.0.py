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
        
        # 扩展的端口和协议配置
        self.protocol_config = {
            'ONVIF': {'ports': [80, 8000, 8080], 'enabled': True},
            'GB/T 28181': {'ports': [5060, 5061], 'enabled': True},
            'RTSP': {'ports': [554, 8554], 'enabled': True},
            'HTTP': {'ports': [80, 8080, 8000], 'enabled': True},
            'RTMP': {'ports': [1935], 'enabled': False},
            'P2P': {'ports': [], 'enabled': False},  # P2P通常不需要端口扫描
            'GigE Vision': {'ports': [3956], 'enabled': False},
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
        """获取本机IP地址"""
        try:
            s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
            s.connect(('8.8.8.8', 80))
            ip = s.getsockname()[0]
            s.close()
            return ip
        except Exception:
            return '127.0.0.1'

    def scan_network(self, start=1, end=255, timeout=1):
        """扫描局域网内的摄像头设备"""
        self.devices = []
        self.scanning = True
        
        def check_device(ip):
            if not self.scanning:
                return
                
            # 收集所有需要扫描的端口
            ports_to_scan = set()
            for protocol, config in self.protocol_config.items():
                if config['enabled']:
                    ports_to_scan.update(config['ports'])
            
            # 先检查常见端口是否开放
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
                
            # 按协议优先级检查
            if self.protocol_config['ONVIF']['enabled']:
                device_info = self.check_onvif(ip, open_ports)
                if device_info:
                    self.devices.append(device_info)
                    return
                    
            if self.protocol_config['GB/T 28181']['enabled']:
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
                    
            # 其他协议检查...

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
        """检查设备是否支持ONVIF"""
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
                            'name': dev_info.Model if dev_info.Model else '未知设备',
                            'manufacturer': dev_info.Manufacturer if dev_info.Manufacturer else '未知厂商',
                            'hardware': dev_info.HardwareId if dev_info.HardwareId else '未知硬件',
                            'firmware': dev_info.FirmwareVersion if dev_info.FirmwareVersion else '未知固件',
                            'protocol': 'ONVIF',
                            'stream_url': stream_uri.Uri,
                            'capabilities': self.get_onvif_capabilities(cam)
                        }
                except Exception:
                    continue
        return None

    def get_onvif_capabilities(self, cam):
        """获取ONVIF设备能力"""
        capabilities = {}
        try:
            devicemgmt = cam.devicemgmt
            capabilities['device'] = devicemgmt.GetDeviceInformation()
            capabilities['network'] = devicemgmt.GetNetworkInterfaces()
            capabilities['ptz'] = cam.create_ptz_service().GetConfigurations() if cam.has_ptz else None
            return capabilities
        except:
            return None

    def check_gb28181(self, ip, ports):
        """检查设备是否支持GB/T 28181"""
        for port in ports:
            if port not in self.protocol_config['GB/T 28181']['ports']:
                continue
                
            # 尝试发送OPTIONS请求
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
                    # 获取设备信息
                    try:
                        catalog_url = f"http://{ip}:80/cgi-bin/gb28181.cgi?cmd=query&type=catalog"
                        response = requests.get(catalog_url, timeout=3)
                        if response.status_code == 200:
                            root = ET.fromstring(response.text)
                            device_id = root.find(".//DeviceID").text
                            device_name = root.find(".//Name").text if root.find(".//Name") is not None else "GB/T 28181设备"
                            
                            # 获取流地址
                            stream_url = f"rtsp://{ip}:554/Streaming/Channels/101?transportmode=unicast&profile=Profile_1"
                            
                            return {
                                'ip': ip,
                                'port': port,
                                'username': 'admin',
                                'password': 'admin',
                                'name': device_name,
                                'manufacturer': 'GB/T 28181兼容设备',
                                'protocol': 'GB/T 28181',
                                'stream_url': stream_url,
                                'device_id': device_id
                            }
                    except:
                        # 如果无法获取详细信息，至少我们知道它支持GB/T 28181
                        return {
                            'ip': ip,
                            'port': port,
                            'username': 'admin',
                            'password': 'admin',
                            'name': 'GB/T 28181设备',
                            'manufacturer': '未知厂商',
                            'protocol': 'GB/T 28181',
                            'stream_url': f"rtsp://{ip}:554/Streaming/Channels/101"
                        }
            except:
                continue
        return None

    def check_rtsp(self, ip, ports):
        """检查设备是否支持RTSP"""
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
                            'name': 'RTSP摄像头',
                            'manufacturer': '未知厂商',
                            'protocol': 'RTSP',
                            'stream_url': rtsp_url
                        }
        return None

    def check_http(self, ip, ports):
        """检查设备是否支持HTTP MJPEG"""
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
                        'name': 'HTTP摄像头',
                        'manufacturer': '未知厂商',
                        'protocol': 'HTTP',
                        'stream_url': http_url
                    }
        return None

    def check_genican(self, ip, ports):
        """检查设备是否支持GenICam/GigE Vision"""
        for port in ports:
            if port not in self.protocol_config['GenICam']['ports']:
                continue
                
            try:
                # 尝试通过GigE Vision协议发现设备
                discovery_cmd = ['gev-discovery', '-n', ip]
                result = subprocess.run(discovery_cmd, capture_output=True, text=True, timeout=5)
                if result.returncode == 0:
                    # 解析发现结果
                    device_info = {
                        'ip': ip,
                        'port': port,
                        'name': 'GenICam/GigE Vision设备',
                        'manufacturer': '工业相机',
                        'protocol': 'GenICam/GigE Vision',
                        'stream_url': f"gev://{ip}"
                    }
                    return device_info
            except:
                continue
        return None


class UniversalCameraViewerApp:
    def __init__(self, root):
        self.root = root
        self.root.title("全协议摄像头管理系统")
        self.root.geometry("1200x800")
        self.root.minsize(1000, 700)
        
        # 初始化变量
        self.scanner = UniversalCameraScanner()
        self.current_camera = None
        self.camera_thread = None
        self.running = False
        self.video_frame = None
        self.photo = None
        self.cap = None
        self.protocol_vars = {}  # 存储协议选择状态
        
        # 设置样式
        self.setup_styles()
        
        # 创建界面
        self.setup_ui()
        
        # 绑定窗口关闭事件
        self.root.protocol("WM_DELETE_WINDOW", self.on_close)

    def setup_styles(self):
        """设置界面样式"""
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
        """设置用户界面"""
        # 主框架
        main_frame = ttk.Frame(self.root)
        main_frame.pack(fill=tk.BOTH, expand=True, padx=10, pady=10)
        
        # 左侧面板 - 设备列表和控制
        left_panel = ttk.Frame(main_frame, width=400)
        left_panel.pack(side=tk.LEFT, fill=tk.Y, padx=(0, 10))
        left_panel.pack_propagate(False)
        
        # 右侧面板 - 视频预览和高级控制
        right_panel = ttk.Frame(main_frame)
        right_panel.pack(side=tk.RIGHT, fill=tk.BOTH, expand=True)
        
        # 设备扫描部分
        scan_frame = ttk.LabelFrame(left_panel, text="设备扫描配置", padding=10)
        scan_frame.pack(fill=tk.X, pady=(0, 10))
        
        # IP范围设置
        ip_range_frame = ttk.Frame(scan_frame)
        ip_range_frame.pack(fill=tk.X, pady=(0, 10))
        
        ttk.Label(ip_range_frame, text="IP范围:").pack(side=tk.LEFT)
        self.ip_start = ttk.Entry(ip_range_frame, width=8)
        self.ip_start.pack(side=tk.LEFT, padx=(0, 10))
        self.ip_start.insert(0, "1")
        
        ttk.Label(ip_range_frame, text="到").pack(side=tk.LEFT, padx=5)
        
        self.ip_end = ttk.Entry(ip_range_frame, width=8)
        self.ip_end.pack(side=tk.LEFT)
        self.ip_end.insert(0, "255")
        
        # 协议选择
        protocol_frame = ttk.LabelFrame(scan_frame, text="选择扫描协议", padding=5)
        protocol_frame.pack(fill=tk.X, pady=(0, 10))
        
        protocol_col1 = ttk.Frame(protocol_frame)
        protocol_col1.pack(side=tk.LEFT, fill=tk.X, expand=True)
        
        protocol_col2 = ttk.Frame(protocol_frame)
        protocol_col2.pack(side=tk.LEFT, fill=tk.X, expand=True)
        
        # 创建协议选择复选框
        protocols = [
            ('ONVIF', protocol_col1),
            ('GB/T 28181', protocol_col1),
            ('RTSP', protocol_col1),
            ('HTTP', protocol_col1),
            ('GenICam/GigE Vision', protocol_col2),
            ('RTMP', protocol_col2),
            ('P2P', protocol_col2),
            ('WebRTC', protocol_col2)
        ]
        
        for protocol, parent in protocols:
            var = tk.BooleanVar(value=protocol in ['ONVIF', 'GB/T 28181', 'RTSP', 'HTTP'])
            self.protocol_vars[protocol] = var
            cb = ttk.Checkbutton(parent, text=protocol, variable=var)
            cb.pack(anchor=tk.W)
        
        scan_btn = ttk.Button(scan_frame, text="开始扫描", command=self.start_scan)
        scan_btn.pack(fill=tk.X)
        
        # 设备列表
        device_frame = ttk.LabelFrame(left_panel, text="设备列表", padding=10)
        device_frame.pack(fill=tk.BOTH, expand=True)
        
        self.device_tree = ttk.Treeview(device_frame, columns=('ip', 'name', 'protocol', 'manufacturer'), show='headings')
        self.device_tree.heading('ip', text="IP地址")
        self.device_tree.heading('name', text="设备名称")
        self.device_tree.heading('protocol', text="协议")
        self.device_tree.heading('manufacturer', text="制造商")
        
        self.device_tree.column('ip', width=120)
        self.device_tree.column('name', width=120)
        self.device_tree.column('protocol', width=100)
        self.device_tree.column('manufacturer', width=120)
        
        scrollbar = ttk.Scrollbar(device_frame, orient=tk.VERTICAL, command=self.device_tree.yview)
        self.device_tree.configure(yscrollcommand=scrollbar.set)
        
        self.device_tree.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)
        scrollbar.pack(side=tk.RIGHT, fill=tk.Y)
        
        self.device_tree.bind('<<TreeviewSelect>>', self.on_device_select)
        
        # 设备信息
        info_frame = ttk.LabelFrame(left_panel, text="设备详细信息", padding=10)
        info_frame.pack(fill=tk.X, pady=(10, 0))
        
        self.info_text = tk.Text(info_frame, height=10, font=('Microsoft YaHei', 9), wrap=tk.WORD)
        self.info_text.pack(fill=tk.BOTH)
        self.info_text.config(state=tk.DISABLED)
        
        # 控制按钮
        btn_frame = ttk.Frame(left_panel)
        btn_frame.pack(fill=tk.X, pady=(10, 0))
        
        self.connect_btn = ttk.Button(btn_frame, text="连接", command=self.connect_camera, state=tk.DISABLED)
        self.connect_btn.pack(side=tk.LEFT, fill=tk.X, expand=True, padx=(0, 5))
        
        self.disconnect_btn = ttk.Button(btn_frame, text="断开", command=self.disconnect_camera, state=tk.DISABLED)
        self.disconnect_btn.pack(side=tk.LEFT, fill=tk.X, expand=True)
        
        # 视频预览部分
        preview_frame = ttk.LabelFrame(right_panel, text="视频预览", padding=10)
        preview_frame.pack(fill=tk.BOTH, expand=True)
        
        self.video_label = ttk.Label(preview_frame, text="未连接摄像头", anchor=tk.CENTER)
        self.video_label.pack(fill=tk.BOTH, expand=True)
        
        # 视频控制按钮
        control_frame = ttk.Frame(right_panel)
        control_frame.pack(fill=tk.X, pady=(10, 0))
        
        self.snapshot_btn = ttk.Button(control_frame, text="截图", command=self.take_snapshot, state=tk.DISABLED)
        self.snapshot_btn.pack(side=tk.LEFT, padx=(0, 5))
        
        self.record_btn = ttk.Button(control_frame, text="开始录制", command=self.toggle_recording, state=tk.DISABLED)
        self.record_btn.pack(side=tk.LEFT, padx=(0, 5))
        
        self.ptz_btn = ttk.Button(control_frame, text="PTZ控制", command=self.show_ptz_control, state=tk.DISABLED)
        self.ptz_btn.pack(side=tk.LEFT)
        
        # 高级功能选项卡
        notebook = ttk.Notebook(right_panel)
        notebook.pack(fill=tk.BOTH, expand=True, pady=(10, 0))
        
        # 流信息标签
        stream_tab = ttk.Frame(notebook)
        notebook.add(stream_tab, text="流信息")
        
        self.stream_info = tk.Text(stream_tab, font=('Microsoft YaHei', 9), wrap=tk.WORD)
        self.stream_info.pack(fill=tk.BOTH, expand=True)
        self.stream_info.config(state=tk.DISABLED)
        
        # 设备配置标签
        config_tab = ttk.Frame(notebook)
        notebook.add(config_tab, text="设备配置")
        
        self.config_info = tk.Text(config_tab, font=('Microsoft YaHei', 9), wrap=tk.WORD)
        self.config_info.pack(fill=tk.BOTH, expand=True)
        self.config_info.config(state=tk.DISABLED)
        
        # 状态栏
        self.status_var = tk.StringVar()
        self.status_var.set("就绪")
        
        status_bar = ttk.Frame(right_panel, height=20)
        status_bar.pack(fill=tk.X, pady=(10, 0))
        
        ttk.Label(status_bar, textvariable=self.status_var, relief=tk.SUNKEN, anchor=tk.W).pack(fill=tk.X)
        
        # 初始化变量
        self.recording = False
        self.video_writer = None
        self.record_start_time = None

    def start_scan(self):
        """开始扫描网络中的摄像头设备"""
        try:
            start = int(self.ip_start.get())
            end = int(self.ip_end.get())
            
            if start < 1 or end > 255 or start > end:
                messagebox.showerror("错误", "IP范围无效，请输入1-255之间的数字")
                return
                
            # 清空设备列表
            for item in self.device_tree.get_children():
                self.device_tree.delete(item)
                
            self.info_text.config(state=tk.NORMAL)
            self.info_text.delete(1.0, tk.END)
            self.info_text.insert(tk.END, "正在扫描网络...")
            self.info_text.config(state=tk.DISABLED)
            
            self.status_var.set("正在扫描网络...")
            self.connect_btn.config(state=tk.DISABLED)
            
            # 设置扫描协议
            for protocol, var in self.protocol_vars.items():
                self.scanner.protocol_config[protocol]['enabled'] = var.get()
            
            # 在新线程中执行扫描
            threading.Thread(target=self.do_scan, args=(start, end), daemon=True).start()
            
        except ValueError:
            messagebox.showerror("错误", "请输入有效的数字")

    def do_scan(self, start, end):
        """执行扫描操作"""
        devices = self.scanner.scan_network(start, end)
        
        self.root.after(0, self.update_device_list, devices)
        
    def update_device_list(self, devices):
        """更新设备列表"""
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
            self.info_text.insert(tk.END, f"扫描完成，找到 {len(devices)} 个设备")
            self.status_var.set(f"扫描完成，找到 {len(devices)} 个设备")
        else:
            self.info_text.insert(tk.END, "扫描完成，未找到摄像头设备")
            self.status_var.set("扫描完成，未找到摄像头设备")
            
        self.info_text.config(state=tk.DISABLED)
        
    def on_device_select(self, event):
        """当选择设备时更新信息"""
        selected = self.device_tree.focus()
        if not selected:
            return
            
        device_data = self.device_tree.item(selected, 'values')
        if not device_data:
            return
            
        # 从扫描结果中找到对应的设备信息
        for device in self.scanner.devices:
            if device['ip'] == device_data[0]:
                self.current_camera = device
                break
                
        if not self.current_camera:
            return
            
        self.info_text.config(state=tk.NORMAL)
        self.info_text.delete(1.0, tk.END)
        self.info_text.insert(tk.END, f"IP地址: {self.current_camera['ip']}\n")
        self.info_text.insert(tk.END, f"设备名称: {self.current_camera['name']}\n")
        self.info_text.insert(tk.END, f"制造商: {self.current_camera['manufacturer']}\n")
        self.info_text.insert(tk.END, f"协议: {self.current_camera['protocol']}\n")
        
        if 'port' in self.current_camera:
            self.info_text.insert(tk.END, f"端口: {self.current_camera['port']}\n")
            
        if 'username' in self.current_camera:
            self.info_text.insert(tk.END, f"用户名: {self.current_camera['username']}\n")
            
        if 'password' in self.current_camera:
            self.info_text.insert(tk.END, f"密码: {'*' * len(self.current_camera['password'])}\n")
            
        if 'stream_url' in self.current_camera:
            self.info_text.insert(tk.END, f"流地址: {self.current_camera['stream_url']}\n")
            
        # 更新流信息标签
        self.stream_info.config(state=tk.NORMAL)
        self.stream_info.delete(1.0, tk.END)
        if 'stream_url' in self.current_camera:
            self.stream_info.insert(tk.END, f"视频流地址:\n{self.current_camera['stream_url']}\n\n")
            
            # 尝试获取流信息
            if self.current_camera['protocol'] in ['RTSP', 'ONVIF', 'GB/T 28181']:
                try:
                    cap = cv2.VideoCapture(self.current_camera['stream_url'])
                    if cap.isOpened():
                        width = int(cap.get(cv2.CAP_PROP_FRAME_WIDTH))
                        height = int(cap.get(cv2.CAP_PROP_FRAME_HEIGHT))
                        fps = cap.get(cv2.CAP_PROP_FPS)
                        codec = int(cap.get(cv2.CAP_PROP_FOURCC))
                        codec_str = "".join([chr((codec >> 8 * i) & 0xFF) for i in range(4)])
                        cap.release()
                        
                        self.stream_info.insert(tk.END, f"分辨率: {width}x{height}\n")
                        self.stream_info.insert(tk.END, f"帧率: {fps:.2f}\n")
                        self.stream_info.insert(tk.END, f"编码格式: {codec_str}\n")
                except:
                    pass
                    
        # 更新设备配置标签
        self.config_info.config(state=tk.NORMAL)
        self.config_info.delete(1.0, tk.END)
        if 'capabilities' in self.current_camera and self.current_camera['capabilities']:
            try:
                caps = self.current_camera['capabilities']
                if caps.get('device'):
                    self.config_info.insert(tk.END, "设备信息:\n")
                    self.config_info.insert(tk.END, f"型号: {caps['device'].Model}\n")
                    self.config_info.insert(tk.END, f"固件版本: {caps['device'].FirmwareVersion}\n")
                    self.config_info.insert(tk.END, f"序列号: {caps['device'].SerialNumber}\n\n")
                
                if caps.get('ptz'):
                    self.config_info.insert(tk.END, "PTZ能力:\n")
                    self.config_info.insert(tk.END, f"支持PTZ: 是\n")
                    self.config_info.insert(tk.END, f"最大速度: {caps['ptz'][0].PTZSpeed.PanTilt._x} (水平), {caps['ptz'][0].PTZSpeed.PanTilt._y} (垂直)\n")
            except:
                pass
                
        self.info_text.config(state=tk.DISABLED)
        self.stream_info.config(state=tk.DISABLED)
        self.config_info.config(state=tk.DISABLED)
        
        self.connect_btn.config(state=tk.NORMAL)
        self.ptz_btn.config(state=tk.NORMAL if self.current_camera['protocol'] == 'ONVIF' else tk.DISABLED)
        
    def connect_camera(self):
        """连接选中的摄像头"""
        if not self.current_camera:
            return
            
        ip = self.current_camera['ip']
        
        self.status_var.set(f"正在连接 {ip}...")
        self.connect_btn.config(state=tk.DISABLED)
        
        # 在新线程中连接摄像头
        threading.Thread(target=self.do_connect_camera, daemon=True).start()
        
    def do_connect_camera(self):
        """执行摄像头连接操作"""
        try:
            stream_url = self.current_camera.get('stream_url', '')
            
            if not stream_url:
                self.root.after(0, self.show_error, "无法获取视频流URL")
                return
                
            # 根据协议类型处理
            if self.current_camera['protocol'] in ['ONVIF', 'RTSP', 'GB/T 28181']:
                # RTSP流
                if 'username' in self.current_camera and 'password' in self.current_camera:
                    # 如果URL中不包含凭据，但设备信息中有，则添加
                    if f"{self.current_camera['username']}:{self.current_camera['password']}@" not in stream_url:
                        parsed = urlparse(stream_url)
                        stream_url = f"{parsed.scheme}://{self.current_camera['username']}:{self.current_camera['password']}@{parsed.netloc}{parsed.path}"
                
                self.cap = cv2.VideoCapture(stream_url)
                
            elif self.current_camera['protocol'] == 'HTTP':
                # HTTP MJPEG流
                self.cap = cv2.VideoCapture(stream_url)
                
            elif self.current_camera['protocol'] == 'GenICam/GigE Vision':
                # 工业相机流
                try:
                    # 使用Aravis或其他GigE Vision库
                    # 这里简化处理，实际需要安装相应库
                    self.cap = cv2.VideoCapture(stream_url)
                except:
                    self.root.after(0, self.show_error, "需要安装GenICam/GigE Vision支持库")
                    return
                
            if not self.cap.isOpened():
                self.root.after(0, self.show_error, "无法打开视频流")
                return
                
            # 更新UI
            self.root.after(0, self.on_camera_connected)
            
        except Exception as e:
            self.root.after(0, self.show_error, f"连接错误: {str(e)}")
            
    def on_camera_connected(self):
        """摄像头连接成功后的回调"""
        self.status_var.set(f"已连接到 {self.current_camera['ip']}")
        
        # 更新按钮状态
        self.connect_btn.config(state=tk.DISABLED)
        self.disconnect_btn.config(state=tk.NORMAL)
        self.snapshot_btn.config(state=tk.NORMAL)
        self.record_btn.config(state=tk.NORMAL)
        
        # 开始视频流
        self.running = True
        self.camera_thread = threading.Thread(target=self.update_video, daemon=True)
        self.camera_thread.start()
        
    def update_video(self):
        """更新视频帧"""
        while self.running and self.cap.isOpened():
            ret, frame = self.cap.read()
            if not ret:
                self.root.after(0, self.show_error, "无法获取视频流")
                break
                
            # 转换颜色空间
            frame = cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)
            
            # 调整大小以适应窗口
            height, width = frame.shape[:2]
            max_size = 800
            if width > max_size or height > max_size:
                ratio = min(max_size/width, max_size/height)
                frame = cv2.resize(frame, (int(width*ratio), int(height*ratio)))
            
            # 转换为PhotoImage
            img = Image.fromarray(frame)
            self.photo = ImageTk.PhotoImage(image=img)
            
            # 更新UI
            self.root.after(0, self.update_frame, self.photo)
            
            # 如果正在录制，写入视频
            if self.recording and self.video_writer:
                frame_bgr = cv2.cvtColor(frame, cv2.COLOR_RGB2BGR)
                self.video_writer.write(frame_bgr)
            
    def update_frame(self, photo):
        """更新视频帧显示"""
        self.video_label.config(image=photo)
        self.video_label.image = photo
        
    def disconnect_camera(self):
        """断开摄像头连接"""
        self.running = False
        if self.camera_thread and self.camera_thread.is_alive():
            self.camera_thread.join(timeout=1)
            
        if self.cap:
            self.cap.release()
            self.cap = None
            
        if self.recording:
            self.stop_recording()
            
        self.video_label.config(image=None, text="未连接摄像头")
        
        # 更新按钮状态
        self.connect_btn.config(state=tk.NORMAL)
        self.disconnect_btn.config(state=tk.DISABLED)
        self.snapshot_btn.config(state=tk.DISABLED)
        self.record_btn.config(state=tk.DISABLED)
        self.record_btn.config(text="开始录制")
        self.ptz_btn.config(state=tk.DISABLED)
        
        self.status_var.set("已断开连接")
        
    def take_snapshot(self):
        """截图"""
        if not self.photo:
            return
            
        # 获取当前时间作为文件名
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        filename = f"snapshot_{timestamp}.png"
        
        # 让用户选择保存位置
        filepath = filedialog.asksaveasfilename(
            initialfile=filename,
            defaultextension=".png",
            filetypes=[("PNG 图片", "*.png"), ("JPEG 图片", "*.jpg"), ("所有文件", "*.*")]
        )
        
        if filepath:
            try:
                # 保存图片
                img = ImageTk.getimage(self.photo)
                img.save(filepath)
                self.status_var.set(f"截图已保存到 {filepath}")
            except Exception as e:
                messagebox.showerror("错误", f"保存截图失败: {str(e)}")
                
    def toggle_recording(self):
        """开始/停止录制"""
        if self.recording:
            self.stop_recording()
        else:
            self.start_recording()
            
    def start_recording(self):
        """开始录制视频"""
        # 获取当前时间作为文件名
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        filename = f"recording_{timestamp}.avi"
        
        # 让用户选择保存位置
        filepath = filedialog.asksaveasfilename(
            initialfile=filename,
            defaultextension=".avi",
            filetypes=[("AVI 视频", "*.avi"), ("MP4 视频", "*.mp4"), ("所有文件", "*.*")]
        )
        
        if filepath:
            try:
                # 获取视频帧大小
                img = ImageTk.getimage(self.photo)
                width, height = img.size
                
                # 根据文件扩展名选择编码器
                ext = os.path.splitext(filepath)[1].lower()
                if ext == '.mp4':
                    fourcc = cv2.VideoWriter_fourcc(*'mp4v')
                else:
                    fourcc = cv2.VideoWriter_fourcc(*'XVID')
                
                self.video_writer = cv2.VideoWriter(filepath, fourcc, 20.0, (width, height))
                
                self.recording = True
                self.record_start_time = datetime.now()
                self.record_btn.config(text="停止录制")
                self.status_var.set(f"正在录制到 {filepath}")
            except Exception as e:
                messagebox.showerror("错误", f"开始录制失败: {str(e)}")
                
    def stop_recording(self):
        """停止录制视频"""
        if self.video_writer:
            self.video_writer.release()
            self.video_writer = None
            
        self.recording = False
        duration = datetime.now() - self.record_start_time
        self.record_btn.config(text="开始录制")
        self.status_var.set(f"录制已停止，时长: {duration.seconds}秒")
        
    def show_ptz_control(self):
        """显示PTZ控制面板"""
        if not self.current_camera or self.current_camera['protocol'] != 'ONVIF':
            return
            
        ptz_window = tk.Toplevel(self.root)
        ptz_window.title("PTZ控制")
        ptz_window.geometry("300x300")
        
        # 创建控制按钮
        control_frame = ttk.Frame(ptz_window)
        control_frame.pack(pady=10)
        
        # 上
        btn_up = ttk.Button(control_frame, text="↑", command=lambda: self.ptz_move('up'))
        btn_up.grid(row=0, column=1, padx=5, pady=5)
        
        # 左
        btn_left = ttk.Button(control_frame, text="←", command=lambda: self.ptz_move('left'))
        btn_left.grid(row=1, column=0, padx=5, pady=5)
        
        # 右
        btn_right = ttk.Button(control_frame, text="→", command=lambda: self.ptz_move('right'))
        btn_right.grid(row=1, column=2, padx=5, pady=5)
        
        # 下
        btn_down = ttk.Button(control_frame, text="↓", command=lambda: self.ptz_move('down'))
        btn_down.grid(row=2, column=1, padx=5, pady=5)
        
        # 停止
        btn_stop = ttk.Button(control_frame, text="停止", command=lambda: self.ptz_move('stop'))
        btn_stop.grid(row=1, column=1, padx=5, pady=5)
        
        # 变焦控制
        zoom_frame = ttk.Frame(ptz_window)
        zoom_frame.pack(pady=10)
        
        btn_zoom_in = ttk.Button(zoom_frame, text="放大", command=lambda: self.ptz_zoom('in'))
        btn_zoom_in.pack(side=tk.LEFT, padx=5)
        
        btn_zoom_out = ttk.Button(zoom_frame, text="缩小", command=lambda: self.ptz_zoom('out'))
        btn_zoom_out.pack(side=tk.LEFT, padx=5)
        
        btn_zoom_stop = ttk.Button(zoom_frame, text="停止", command=lambda: self.ptz_zoom('stop'))
        btn_zoom_stop.pack(side=tk.LEFT, padx=5)
        
    def ptz_move(self, direction):
        """控制PTZ移动"""
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
            
            # 获取当前PTZ状态
            status = ptz.GetStatus({'ProfileToken': cam.media.GetProfiles()[0]._token})
            
            # 设置移动速度
            speed = 0.5  # 中等速度
            
            # 创建移动请求
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
            messagebox.showerror("错误", f"PTZ控制失败: {str(e)}")
            
    def ptz_zoom(self, action):
        """控制PTZ变焦"""
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
            
            # 设置变焦速度
            speed = 0.5  # 中等速度
            
            # 创建变焦请求
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
            messagebox.showerror("错误", f"变焦控制失败: {str(e)}")
        
    def show_error(self, message):
        """显示错误消息"""
        messagebox.showerror("错误", message)
        self.status_var.set(message)
        
    def on_close(self):
        """窗口关闭时的清理工作"""
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