### 🤖 Assistant

摄像头除了ONVIF协议外，常见的通信和控制协议还包括以下几种：

---

### **1. 厂商私有协议**
- **海康威视（Hikvision）**：私有协议（如`ISAPI`、`SDK`），需使用厂商提供的工具或SDK集成。
- **大华（Dahua）**：私有协议（如`DH-SDK`），部分功能需通过厂商API实现。
- **其他品牌**：如Axis、Bosch等均有自己的协议和接口。

---

### **2. 通用网络协议**
- **RTSP**（Real Time Streaming Protocol）  
  - 用于实时视频流传输（如`rtsp://ip:port/stream`）。
  - 支持大多数摄像头，但仅提供视频流，不涉及设备控制。
- **RTMP**（Real-Time Messaging Protocol）  
  - 常用于直播推流（如与Flash播放器兼容）。
- **HTTP/HTTPS**  
  - 通过RESTful API或网页接口管理摄像头（部分厂商支持）。
- **RTP/RTCP**（Real-time Transport Protocol）  
  - 与RTSP配合使用，传输音视频数据。

---

### **3. 监控行业协议**
- **PSIA**（Physical Security Interoperability Alliance）  
  - 类似ONVIF的开放标准，但普及度较低。
- **CGI**（Common Gateway Interface）  
  - 部分摄像头通过CGI接口提供控制（如海康的`/cgi-bin`路径）。
- **GB/T 28181**  
  - 中国国家标准，用于公安/政府领域的视频监控联网（国内常用）。

---

### **4. 物联网/智能家居协议**
- **MQTT**  
  - 轻量级IoT协议，部分智能摄像头支持（如推送报警消息）。
- **HomeKit**（Apple）  
  - 苹果生态的智能家居协议，兼容HomeKit的摄像头可直接接入iOS。
- **WeMo**、**Tuya**等  
  - 智能家居平台私有协议。

---

### **5. 其他协议**
- **FTP/SFTP**  
  - 用于录像文件上传或存储。
- **SNMP**（Simple Network Management Protocol）  
  - 监控设备状态（如网络故障、温度等）。
- **UPnP**（Universal Plug and Play）  
  - 部分摄像头支持自动发现和端口映射。

---

### **选择建议**
- **标准化场景**：优先选择ONVIF或GB/T 28181（国内）。  
- **深度集成**：需使用厂商SDK或私有协议（如海康ISAPI）。  
- **视频流获取**：RTSP最通用，兼容VLC、FFmpeg等工具。  

如果需要具体型号的协议支持，建议查阅摄像头的官方文档或开发者手册。