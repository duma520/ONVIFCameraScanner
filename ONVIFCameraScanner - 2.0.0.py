import os
import socket
import threading
import re
from datetime import datetime
from time import sleep
from urllib.parse import urlparse

import cv2
import numpy as np
from onvif import ONVIFCamera
from zeep.exceptions import Fault

import tkinter as tk
from tkinter import ttk, messagebox, filedialog
from PIL import Image, ImageTk


class CameraScanner:
    def __init__(self):
        self.devices = []
        self.scanning = False
        self.local_ip = self.get_local_ip()
        self.network_prefix = '.'.join(self.local_ip.split('.')[:3]) + '.'
        self.common_ports = [80, 8000, 8080, 37777, 554]  # 常见摄像头端口
        self.common_credentials = [
            ('admin', 'admin'),
            ('admin', '12345'),
            ('admin', '123456'),
            ('admin', ''),
            ('', '')
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
                
            # 先检查常见端口是否开放
            open_ports = []
            for port in self.common_ports:
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
                
            # 检查ONVIF支持
            device_info = self.check_onvif(ip, open_ports)
            if device_info:
                self.devices.append(device_info)
                return
                
            # 检查RTSP支持
            device_info = self.check_rtsp(ip, open_ports)
            if device_info:
                self.devices.append(device_info)
                return
                
            # 检查HTTP MJPEG支持
            device_info = self.check_http(ip, open_ports)
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
        """检查设备是否支持ONVIF"""
        for port in ports:
            if port not in [80, 8000, 8080]:  # ONVIF常用端口
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
                            'stream_url': stream_uri.Uri
                        }
                except Exception:
                    continue
        return None

    def check_rtsp(self, ip, ports):
        """检查设备是否支持RTSP"""
        rtsp_ports = [554, 8554]  # RTSP常用端口
        rtsp_paths = [
            '/live.sdp',
            '/streaming/channels/1',
            '/cam/realmonitor?channel=1&subtype=0',
            '/11',
            '/1'
        ]
        
        for port in ports:
            if port not in rtsp_ports:
                continue
                
            for cred in self.common_credentials:
                for path in rtsp_paths:
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
        http_paths = [
            '/video',
            '/mjpg/video.mjpg',
            '/cgi-bin/mjpg/video.cgi',
            '/cameras/camera1/mjpeg',
            '/stream'
        ]
        
        for port in ports:
            if port not in [80, 8080, 8000]:
                continue
                
            for path in http_paths:
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


class CameraViewerApp:
    def __init__(self, root):
        self.root = root
        self.root.title("多功能摄像头检测与查看工具")
        self.root.geometry("1100x750")
        self.root.minsize(900, 650)
        
        # 初始化变量
        self.scanner = CameraScanner()
        self.current_camera = None
        self.camera_thread = None
        self.running = False
        self.video_frame = None
        self.photo = None
        self.cap = None
        
        # 设置样式
        self.setup_styles()
        
        # 创建界面
        self.setup_ui()
        
        # 绑定窗口关闭事件
        self.root.protocol("WM_DELETE_WINDOW", self.on_close)

    def setup_styles(self):
        """设置界面样式"""
        style = ttk.Style()
        style.configure('TFrame', background='#f0f0f0')
        style.configure('TLabel', background='#f0f0f0', font=('Microsoft YaHei', 10))
        style.configure('TButton', font=('Microsoft YaHei', 10), padding=5)
        style.configure('Header.TLabel', font=('Microsoft YaHei', 12, 'bold'))
        style.configure('Treeview', font=('Microsoft YaHei', 10), rowheight=25)
        style.configure('Treeview.Heading', font=('Microsoft YaHei', 10, 'bold'))
        style.map('TButton', background=[('active', '#e0e0e0')])

    def setup_ui(self):
        """设置用户界面"""
        # 主框架
        main_frame = ttk.Frame(self.root)
        main_frame.pack(fill=tk.BOTH, expand=True, padx=10, pady=10)
        
        # 左侧面板 - 设备列表和控制
        left_panel = ttk.Frame(main_frame, width=350)
        left_panel.pack(side=tk.LEFT, fill=tk.Y, padx=(0, 10))
        left_panel.pack_propagate(False)
        
        # 右侧面板 - 视频预览
        right_panel = ttk.Frame(main_frame)
        right_panel.pack(side=tk.RIGHT, fill=tk.BOTH, expand=True)
        
        # 设备扫描部分
        scan_frame = ttk.LabelFrame(left_panel, text="设备扫描", padding=10)
        scan_frame.pack(fill=tk.X, pady=(0, 10))
        
        ttk.Label(scan_frame, text="网络范围:").pack(anchor=tk.W)
        
        ip_frame = ttk.Frame(scan_frame)
        ip_frame.pack(fill=tk.X, pady=(0, 5))
        
        ttk.Label(ip_frame, text="起始IP:").pack(side=tk.LEFT)
        self.ip_start = ttk.Entry(ip_frame, width=8)
        self.ip_start.pack(side=tk.LEFT, padx=(0, 10))
        self.ip_start.insert(0, "1")
        
        ttk.Label(ip_frame, text="结束IP:").pack(side=tk.LEFT)
        self.ip_end = ttk.Entry(ip_frame, width=8)
        self.ip_end.pack(side=tk.LEFT)
        self.ip_end.insert(0, "255")
        
        # 高级选项
        adv_frame = ttk.Frame(scan_frame)
        adv_frame.pack(fill=tk.X, pady=(5, 10))
        
        self.scan_onvif = tk.BooleanVar(value=True)
        self.scan_rtsp = tk.BooleanVar(value=True)
        self.scan_http = tk.BooleanVar(value=True)
        
        ttk.Checkbutton(adv_frame, text="ONVIF", variable=self.scan_onvif).pack(side=tk.LEFT)
        ttk.Checkbutton(adv_frame, text="RTSP", variable=self.scan_rtsp).pack(side=tk.LEFT, padx=10)
        ttk.Checkbutton(adv_frame, text="HTTP", variable=self.scan_http).pack(side=tk.LEFT)
        
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
        
        self.device_tree.column('ip', width=100)
        self.device_tree.column('name', width=100)
        self.device_tree.column('protocol', width=80)
        self.device_tree.column('manufacturer', width=100)
        
        scrollbar = ttk.Scrollbar(device_frame, orient=tk.VERTICAL, command=self.device_tree.yview)
        self.device_tree.configure(yscrollcommand=scrollbar.set)
        
        self.device_tree.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)
        scrollbar.pack(side=tk.RIGHT, fill=tk.Y)
        
        self.device_tree.bind('<<TreeviewSelect>>', self.on_device_select)
        
        # 设备信息
        info_frame = ttk.LabelFrame(left_panel, text="设备信息", padding=10)
        info_frame.pack(fill=tk.X, pady=(10, 0))
        
        self.info_text = tk.Text(info_frame, height=8, font=('Microsoft YaHei', 9), wrap=tk.WORD)
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
        
        # 控制按钮
        control_frame = ttk.Frame(right_panel)
        control_frame.pack(fill=tk.X, pady=(10, 0))
        
        self.snapshot_btn = ttk.Button(control_frame, text="截图", command=self.take_snapshot, state=tk.DISABLED)
        self.snapshot_btn.pack(side=tk.LEFT, padx=(0, 5))
        
        self.record_btn = ttk.Button(control_frame, text="开始录制", command=self.toggle_recording, state=tk.DISABLED)
        self.record_btn.pack(side=tk.LEFT)
        
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
            
            # 设置扫描选项
            self.scanner.scan_onvif = self.scan_onvif.get()
            self.scanner.scan_rtsp = self.scan_rtsp.get()
            self.scanner.scan_http = self.scan_http.get()
            
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
            
        self.info_text.config(state=tk.DISABLED)
        
        self.connect_btn.config(state=tk.NORMAL)
        
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
            if self.current_camera['protocol'] == 'RTSP':
                # RTSP流
                self.cap = cv2.VideoCapture(stream_url)
                
            elif self.current_camera['protocol'] == 'HTTP':
                # HTTP MJPEG流
                self.cap = cv2.VideoCapture(stream_url)
                
            elif self.current_camera['protocol'] == 'ONVIF':
                # ONVIF流 (已经是RTSP URL)
                self.cap = cv2.VideoCapture(stream_url)
                
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
    app = CameraViewerApp(root)
    root.mainloop()