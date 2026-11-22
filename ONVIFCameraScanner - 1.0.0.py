import os
import socket
import threading
from datetime import datetime
from time import sleep

import cv2
import numpy as np
from onvif import ONVIFCamera
from zeep.exceptions import Fault

import tkinter as tk
from tkinter import ttk, messagebox, filedialog
from PIL import Image, ImageTk


class ONVIFCameraScanner:
    def __init__(self):
        self.devices = []
        self.scanning = False
        self.local_ip = self.get_local_ip()
        print(self.local_ip)
        self.network_prefix = '.'.join(self.local_ip.split('.')[:3]) + '.'
        print(self.network_prefix)

    def get_local_ip(self):
        """获取本机IP地址"""
        try:
            s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
            s.connect(('8.8.8.8', 80))
            ip = s.getsockname()[0]
            print(ip)
            s.close()
            return ip
        except Exception:
            return '127.0.0.1'

    def scan_network(self, start=1, end=255, timeout=1):
        """扫描局域网内的ONVIF设备"""
        self.devices = []
        print("开始扫描...")
        self.scanning = True
        
        def check_device(ip):
            print(f"正在检查 {ip}...")
            if not self.scanning:
                print(f"停止扫描 {ip}")
                return
                
            try:
                # 尝试连接ONVIF端口
                sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
                print(f"正在检查 {ip} 的ONVIF端口...")
                sock.settimeout(timeout)
                result = sock.connect_ex((ip, 80))
                sock.close()
                
                if result == 0:  # 端口开放
                    try:
                        # 尝试创建ONVIF相机对象
                        cam = ONVIFCamera(ip, 80, '', '')
                        print(f"正在检查 {ip} 的ONVIF服务...")
                        media_service = cam.create_media_service()
                        print(f"正在检查 {ip} 的媒体配置文件...")
                        profiles = media_service.GetProfiles()
                        print(f"正在检查 {ip} 的视频流...")
                        
                        if profiles:
                            # 获取设备信息
                            dev_info = cam.devicemgmt.GetDeviceInformation()
                            print(f"发现ONVIF设备: {ip}")
                            device_data = {
                                'ip': ip,
                                'name': dev_info.Model if dev_info.Model else '未知设备',
                                'manufacturer': dev_info.Manufacturer if dev_info.Manufacturer else '未知厂商',
                                'hardware': dev_info.HardwareId if dev_info.HardwareId else '未知硬件',
                                'firmware': dev_info.FirmwareVersion if dev_info.FirmwareVersion else '未知固件'
                            }
                            print(device_data)
                            self.devices.append(device_data)
                    except Exception as e:
                        pass  # 不是ONVIF设备或其他错误
            except Exception:
                pass

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


class CameraViewerApp:
    def __init__(self, root):
        self.root = root
        self.root.title("ONVIF摄像头检测与查看工具")
        self.root.geometry("1000x700")
        self.root.minsize(800, 600)
        
        # 初始化变量
        self.scanner = ONVIFCameraScanner()
        self.current_camera = None
        self.camera_thread = None
        self.running = False
        self.video_frame = None
        self.photo = None
        
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
        left_panel = ttk.Frame(main_frame, width=300)
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
        ip_frame.pack(fill=tk.X, pady=(0, 10))
        
        self.ip_start = ttk.Entry(ip_frame, width=8)
        self.ip_start.pack(side=tk.LEFT)
        self.ip_start.insert(0, "1")
        
        ttk.Label(ip_frame, text="到").pack(side=tk.LEFT, padx=5)
        
        self.ip_end = ttk.Entry(ip_frame, width=8)
        self.ip_end.pack(side=tk.LEFT)
        self.ip_end.insert(0, "255")
        
        scan_btn = ttk.Button(scan_frame, text="开始扫描", command=self.start_scan)
        scan_btn.pack(fill=tk.X)
        
        # 设备列表
        device_frame = ttk.LabelFrame(left_panel, text="设备列表", padding=10)
        device_frame.pack(fill=tk.BOTH, expand=True)
        
        self.device_tree = ttk.Treeview(device_frame, columns=('ip', 'name', 'manufacturer'), show='headings')
        self.device_tree.heading('ip', text="IP地址")
        self.device_tree.heading('name', text="设备名称")
        self.device_tree.heading('manufacturer', text="制造商")
        
        self.device_tree.column('ip', width=100)
        self.device_tree.column('name', width=100)
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
        """开始扫描网络中的ONVIF设备"""
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
                device['manufacturer']
            ))
            
        self.info_text.config(state=tk.NORMAL)
        self.info_text.delete(1.0, tk.END)
        
        if devices:
            self.info_text.insert(tk.END, f"扫描完成，找到 {len(devices)} 个设备")
            self.status_var.set(f"扫描完成，找到 {len(devices)} 个设备")
        else:
            self.info_text.insert(tk.END, "扫描完成，未找到ONVIF设备")
            self.status_var.set("扫描完成，未找到ONVIF设备")
            
        self.info_text.config(state=tk.DISABLED)
        
    def on_device_select(self, event):
        """当选择设备时更新信息"""
        selected = self.device_tree.focus()
        if not selected:
            return
            
        device_data = self.device_tree.item(selected, 'values')
        if not device_data:
            return
            
        self.current_camera = {
            'ip': device_data[0],
            'name': device_data[1],
            'manufacturer': device_data[2]
        }
        
        self.info_text.config(state=tk.NORMAL)
        self.info_text.delete(1.0, tk.END)
        self.info_text.insert(tk.END, f"IP地址: {device_data[0]}\n")
        self.info_text.insert(tk.END, f"设备名称: {device_data[1]}\n")
        self.info_text.insert(tk.END, f"制造商: {device_data[2]}\n")
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
        threading.Thread(target=self.do_connect_camera, args=(ip,), daemon=True).start()
        
    def do_connect_camera(self, ip):
        """执行摄像头连接操作"""
        try:
            # 尝试连接ONVIF摄像头
            cam = ONVIFCamera(ip, 80, '', '')
            
            # 获取媒体服务
            media_service = cam.create_media_service()
            profiles = media_service.GetProfiles()
            
            if not profiles:
                self.root.after(0, self.show_error, "摄像头没有可用的配置")
                return
                
            # 获取第一个配置文件的流URI
            stream_uri = media_service.GetStreamUri({
                'StreamSetup': {'Stream': 'RTP-Unicast', 'Transport': {'Protocol': 'RTSP'}},
                'ProfileToken': profiles[0].token
            })
            
            rtsp_url = stream_uri.Uri
            
            # 更新UI
            self.root.after(0, self.on_camera_connected, rtsp_url)
            
        except Fault as e:
            self.root.after(0, self.show_error, f"ONVIF错误: {str(e)}")
        except Exception as e:
            self.root.after(0, self.show_error, f"连接错误: {str(e)}")
            
    def on_camera_connected(self, rtsp_url):
        """摄像头连接成功后的回调"""
        self.status_var.set(f"已连接到 {self.current_camera['ip']}")
        
        # 更新按钮状态
        self.connect_btn.config(state=tk.DISABLED)
        self.disconnect_btn.config(state=tk.NORMAL)
        self.snapshot_btn.config(state=tk.NORMAL)
        self.record_btn.config(state=tk.NORMAL)
        
        # 开始视频流
        self.running = True
        self.camera_thread = threading.Thread(target=self.update_video, args=(rtsp_url,), daemon=True)
        self.camera_thread.start()
        
    def update_video(self, rtsp_url):
        """更新视频帧"""
        cap = cv2.VideoCapture(rtsp_url)
        
        while self.running:
            ret, frame = cap.read()
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
            
        cap.release()
        
    def update_frame(self, photo):
        """更新视频帧显示"""
        self.video_label.config(image=photo)
        self.video_label.image = photo
        
    def disconnect_camera(self):
        """断开摄像头连接"""
        self.running = False
        if self.camera_thread and self.camera_thread.is_alive():
            self.camera_thread.join(timeout=1)
            
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
            filetypes=[("PNG 图片", "*.png"), ("所有文件", "*.*")]
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
            filetypes=[("AVI 视频", "*.avi"), ("所有文件", "*.*")]
        )
        
        if filepath:
            try:
                # 获取视频帧大小
                img = ImageTk.getimage(self.photo)
                width, height = img.size
                
                # 创建视频写入器
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
            
        if self.recording:
            self.stop_recording()
            
        self.root.destroy()


if __name__ == "__main__":
    root = tk.Tk()
    app = CameraViewerApp(root)
    root.mainloop()