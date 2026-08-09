/* ====================================================================
 * firmware/esp32_firmware.ino — Code cho ESP32 thật nhận lệnh từ Flask
 *
 * PHẦN B: Code chạy trực tiếp trên kit ESP32 khi kết nối thiết bị thật.
 * 
 * Các chức năng chính:
 * 1. Kết nối WiFi cục bộ của phòng máy.
 * 2. Khởi tạo một HTTP Server lắng nghe cổng 80 để nhận lệnh JSON điều khiển:
 *    POST http://<IP_ESP32>/control -> Bật/tắt LED, Relay, Buzzer (còi kêu có hẹn giờ).
 * 3. Gửi Heartbeat định kỳ mỗi 10 giây báo Online cho Flask server.
 * 4. Xử lý tắt Buzzer/LED không đồng bộ (non-blocking) dùng millis() thay vì delay().
 * ==================================================================== */

#include <WiFi.h>
#include <WebServer.h>
#include <HTTPClient.h>
#include <ArduinoJson.h>

// ── CẤU HÌNH WIFI (THAY ĐỔI THEO WIFI PHÒNG MÁY CỦA BẠN) ────────
const char* ssid     = "YOUR_WIFI_SSID";     // Nhập tên WiFi
const char* password = "YOUR_WIFI_PASSWORD"; // Nhập mật khẩu WiFi

// ── CẤU HÌNH FLASK SERVER IP (ĐỂ GỬI HEARTBEAT) ──────────────────
const char* flask_server_url = "http://192.168.1.10:5000/api/iot/heartbeat"; // Đổi 192.168.1.10 thành IP máy tính chạy Flask

// ── CẤU HÌNH CHÂN GPIO KẾT NỐI LINH KIỆN ─────────────────────────
const int LED_PIN    = 2;   // Đèn LED báo động (thường chân số 2 là LED onboard của ESP32)
const int BUZZER_PIN = 4;   // Còi Buzzer (ví dụ nối chân GPIO4)
const int RELAY_PIN  = 5;   // Relay bật thiết bị ngoại vi (ví dụ nối chân GPIO5)

// Khởi tạo Web Server cổng 80
WebServer server(80);

// Thời gian tự tắt Buzzer và LED (hẹn giờ)
unsigned long buzzer_off_time = 0;
unsigned long led_off_time    = 0;
bool buzzer_active = false;
bool led_active    = false;

// Lưu thời gian gửi heartbeat cuối cùng
unsigned long last_heartbeat_time = 0;
const unsigned long heartbeat_interval = 10000; // 10 giây gửi 1 lần

void setup() {
  Serial.begin(115200);
  
  // Khởi tạo các chân Output
  pinMode(LED_PIN, OUTPUT);
  pinMode(BUZZER_PIN, OUTPUT);
  pinMode(RELAY_PIN, OUTPUT);
  
  // Trạng thái ban đầu tắt hết
  digitalWrite(LED_PIN, LOW);
  digitalWrite(BUZZER_PIN, LOW);
  digitalWrite(RELAY_PIN, LOW);

  // Kết nối WiFi
  Serial.println("\n--- DONG BO WIFI ---");
  Serial.print("Dang ket noi den ");
  Serial.println(ssid);
  WiFi.begin(ssid, password);
  
  while (WiFi.status() != WL_CONNECTED) {
    delay(500);
    Serial.print(".");
  }
  
  Serial.println("\nWiFi da ket noi thanh cong!");
  Serial.print("Dia chi IP cua ESP32: ");
  Serial.println(WiFi.localIP());

  // ── ĐỊNH NGHĨA CÁC ROUTE TRÊN WEB SERVER ───────────────────────
  
  // Route chính: xử lý lệnh điều khiển
  server.on("/control", HTTP_POST, handleControl);
  
  // Route 404
  server.onNotFound(handleNotFound);

  // Khởi động HTTP Server
  server.begin();
  Serial.println("ESP32 HTTP Server da khoi dong!");
}

void loop() {
  // Lắng nghe các request HTTP gửi đến ESP32
  server.handleClient();

  // Đọc mốc thời gian hiện tại
  unsigned long now = millis();

  // ── XỬ LÝ HẸN GIỜ TỰ TẮT BUZZER (NON-BLOCKING) ──────────────────
  if (buzzer_active && now >= buzzer_off_time) {
    digitalWrite(BUZZER_PIN, LOW);
    buzzer_active = false;
    Serial.println("[ESP32] Coi Buzzer tu dong tat.");
  }

  // ── XỬ LÝ HẸN GIỜ TỰ TẮT LED (NON-BLOCKING) ─────────────────────
  if (led_active && now >= led_off_time) {
    digitalWrite(LED_PIN, LOW);
    led_active = false;
    Serial.println("[ESP32] Den LED tu dong tat.");
  }

  // ── GỬI HEARTBEAT BÁO ONLINE CHO FLASK SERVER ──────────────────
  if (now - last_heartbeat_time >= heartbeat_interval) {
    last_heartbeat_time = now;
    sendHeartbeat();
  }
}

// ── HÀM XỬ LÝ LỆNH ĐIỀU KHIỂN (HTTP POST /control) ───────────────
void handleControl() {
  if (server.hasArg("plain") == false) {
    server.send(400, "application/json", "{\"error\":\"Missing body\"}");
    return;
  }

  String body = server.arg("plain");
  StaticJsonDocument<200> doc;
  DeserializationError error = deserializeJson(doc, body);

  if (error) {
    server.send(400, "application/json", "{\"error\":\"JSON parsing failed\"}");
    return;
  }

  const char* device = doc["device"]; // "led", "buzzer", "relay"
  int status = doc["status"];         // 1: bật, 0: tắt
  int duration = doc["duration"];     // Thời gian tự tắt (giây)

  if (strcmp(device, "led") == 0) {
    digitalWrite(LED_PIN, status ? HIGH : LOW);
    if (status == 1 && duration > 0) {
      led_active = true;
      led_off_time = millis() + (duration * 1000);
    } else {
      led_active = false;
    }
    Serial.printf("[ESP32] LED = %d (Duration: %ds)\n", status, duration);
  } 
  else if (strcmp(device, "buzzer") == 0) {
    digitalWrite(BUZZER_PIN, status ? HIGH : LOW);
    if (status == 1 && duration > 0) {
      buzzer_active = true;
      buzzer_off_time = millis() + (duration * 1000);
    } else {
      buzzer_active = false;
    }
    Serial.printf("[ESP32] BUZZER = %d (Duration: %ds)\n", status, duration);
  } 
  else if (strcmp(device, "relay") == 0) {
    digitalWrite(RELAY_PIN, status ? HIGH : LOW);
    Serial.printf("[ESP32] RELAY = %d\n", status);
  } 
  else {
    server.send(400, "application/json", "{\"error\":\"Unknown device\"}");
    return;
  }

  // Trả về JSON thành công cho Flask
  String response = "{\"status\":\"success\",\"device\":\"" + String(device) + "\",\"state\":" + String(status) + "}";
  server.send(200, "application/json", response);
}

// ── HÀM GỬI HEARTBEAT LÊN FLASK SERVER ───────────────────────────
void sendHeartbeat() {
  if (WiFi.status() == WL_CONNECTED) {
    HTTPClient http;
    http.begin(flask_server_url);
    http.addHeader("Content-Type", "application/json");

    // Tạo payload JSON chứa trạng thái pin hiện tại
    StaticJsonDocument<200> doc;
    doc["ip"] = WiFi.localIP().toString();
    
    JsonObject devices = doc.createNestedObject("devices");
    devices["led"] = digitalRead(LED_PIN);
    devices["buzzer"] = digitalRead(BUZZER_PIN);
    devices["relay"] = digitalRead(RELAY_PIN);

    String requestBody;
    serializeJson(doc, requestBody);

    int httpResponseCode = http.POST(requestBody);

    if (httpResponseCode > 0) {
      Serial.printf("[Heartbeat] Gui thanh cong, response code: %d\n", httpResponseCode);
    } else {
      Serial.printf("[Heartbeat] Loi gui: %s\n", http.errorToString(httpResponseCode).c_str());
    }
    http.end();
  } else {
    Serial.println("[Heartbeat] Mat ket noi WiFi, khong the gui!");
  }
}

void handleNotFound() {
  server.send(404, "text/plain", "Not Found");
}
