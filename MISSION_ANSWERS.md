# Day 14 Lab — Mission Answers

## Part 1: Localhost vs Production

### Exercise 1.1: Anti-patterns phát hiện trong `01-localhost-vs-production/develop/app.py`
1. **Hardcode secrets trong source code (dòng 17–18):** `OPENAI_API_KEY = "sk-hardcoded-fake-key-never-do-this"` và `DATABASE_URL = "postgresql://admin:password123@localhost:5432/mydb"`. Nếu push lên GitHub public, bot quét tự động sẽ thu thập ngay và secret nằm vĩnh viễn trong git history kể cả khi xóa ở commit sau.
2. **Không quản lý cấu hình qua biến môi trường (dòng 21–22):** `DEBUG = True`, `MAX_TOKENS = 500` viết cứng trong code, không tách biệt cấu hình giữa dev/staging/production.
3. **Dùng `print()` thay vì structured logging và log trực tiếp secret (dòng 33–38):** Đặc biệt dòng 34 `print(f"[DEBUG] Using key: {OPENAI_API_KEY}")` làm lộ API key ra log hệ thống.
4. **Không có endpoint health check & readiness check (dòng 42–43):** Không có `/health` và `/ready`, nền tảng cloud/load balancer không phát hiện được app chết hay chưa sẵn sàng.
5. **Bind cứng `host="localhost"` và `port=8000` (dòng 51–52):** Trong container, bind `localhost` chặn mọi kết nối từ bên ngoài container; cứng port `8000` làm lỗi trên PaaS (Railway/Render) vốn cấp động biến `PORT`.
6. **Bật `reload=True` trong code chạy chính (dòng 53):** Tốn tài nguyên theo dõi file và dễ gây rớt kết nối trên production.
7. **Không xử lý Graceful Shutdown:** Không có `lifespan` hay xử lý `SIGTERM` để hoàn thành các request đang chạy trước khi dừng.

**Đối chiếu sửa lỗi với `production/app.py` & `production/config.py`:**
- `develop/app.py:17–18` hardcode secret → `production/config.py:15–50` đọc toàn bộ cấu hình qua `os.getenv(...)` và có hàm `validate()` fail-fast (khi chạy `ENVIRONMENT=production python app.py` thiếu `AGENT_API_KEY` → ném `ValueError: AGENT_API_KEY must be set in production!`).
- `develop/app.py:34` log lộ key → `production/app.py:111–122` chỉ log metadata (`question_length`, `client_ip`, `response_length`), tuyệt đối không log secret.

### Exercise 1.2: Kết quả chạy bản `develop`
- Gửi JSON body (`POST /ask`) trả `422 Unprocessable Entity` (do bản `develop` nhận `question` qua query param).
- Gửi đúng query param (`POST /ask?question=Hello`) trả `200 OK`, đồng thời log in ra secret:
```text
INFO:     127.0.0.1:46874 - "POST /ask HTTP/1.1" 422 Unprocessable Entity
[DEBUG] Got question: Hello
[DEBUG] Using key: sk-hardcoded-fake-key-never-do-this
[DEBUG] Response: Đây là câu trả lời từ AI agent (mock). Trong production, đây sẽ là response từ OpenAI/Anthropic.
INFO:     127.0.0.1:46886 - "POST /ask?question=Hello HTTP/1.1" 200 OK
```

### Exercise 1.3: Bảng so sánh Develop vs Production

| Feature | Develop (`develop/app.py`) | Production (`production/app.py` + `config.py`) | Tại sao quan trọng? |
|---|---|---|---|
| Config & Secrets | Hardcode API key, DB URL, port, debug trong code | Đọc từ biến môi trường (`os.getenv`), có `validate()` fail-fast | Áp dụng 12-Factor: 1 bản build chạy mọi môi trường, không lộ secret vào Git, phát hiện thiếu cấu hình ngay lúc khởi động |
| Health & Readiness | Không có | `GET /health` (liveness) trả `200` + uptime; `GET /ready` (readiness) trả `200`/`503` | Tách biệt kiểm tra "process còn sống" (để orchestrator restart) với "sẵn sàng nhận traffic" (để LB tạm ngừng route khi chưa sẵn sàng, tránh restart storm) |
| Logging | `print()` plain text, in cả `OPENAI_API_KEY` | Dùng `logging` chuẩn, log metadata (không log secret) | Hệ thống thu thập log tập trung (Loki/Datadog) cần log có cấu trúc để tìm kiếm/alert và không bao giờ được làm lộ credentials |
| Network Binding | `host="localhost"`, `port=8000`, `reload=True` | `host` mặc định `0.0.0.0`, đọc `PORT` từ env, `reload=settings.debug` | Container cần `0.0.0.0` để nhận traffic từ bên ngoài namespace; cloud PaaS inject `PORT` động; tắt reload để ổn định |
| Shutdown | Tắt đột ngột, không có lifecycle hook | `lifespan` quản lý startup/shutdown, chuyển `is_ready = False`, hoàn thành in-flight requests trước khi thoát | Đảm bảo zero-downtime deployment và không cắt ngang request của người dùng khi nhận `SIGTERM` |

---

## Part 2: Docker

### Exercise 2.1: Trả lời 4 câu hỏi về Dockerfile (`02-docker/develop/Dockerfile`)
1. **Base image:** `python:3.11` (bản Debian đầy đủ có sẵn Python 3.11 và nhiều công cụ hệ thống, kích thước rất lớn).
2. **Working directory:** `/app` (`WORKDIR /app`), là thư mục làm việc mặc định cho các lệnh `COPY`, `RUN`, `CMD` phía sau bên trong container.
3. **Tại sao `COPY requirements.txt` đứng trước `COPY . .` (hoặc copy source code)?** Để tận dụng **Docker layer cache**. Docker cache theo từng layer từ trên xuống; nếu `requirements.txt` không đổi thì layer `pip install` được tái sử dụng (`CACHED`), không phải cài lại toàn bộ thư viện mỗi lần chỉ sửa file `.py`. *(Lưu ý: `--no-cache-dir` của `pip` chỉ tắt cache tải wheel của pip để giảm dung lượng image, không tắt Docker layer cache).*
4. **Khác nhau giữa `CMD` và `ENTRYPOINT`:** `ENTRYPOINT` cố định chương trình chính sẽ luôn chạy khi khởi động container (chỉ đổi được bằng `--entrypoint`); `CMD` chỉ định lệnh mặc định (hoặc tham số mặc định cho `ENTRYPOINT`) và dễ dàng ghi đè khi chạy `docker run <image> <cmd>`. Dùng exec form (`["python", "app.py"]`) giúp app là PID 1 và nhận trực tiếp `SIGTERM`.

### Exercise 2.2: Kết quả build & chạy container `my-agent:develop`
```text
GET /health -> {"status":"ok","uptime_seconds":5.4,"container":true}
POST /ask?question=What%20is%20Docker%3F -> {"answer":"Container là cách đóng gói app để chạy ở mọi nơi. Build once, run anywhere!"}
```

### Exercise 2.3: So sánh kích thước image (`docker images my-agent` đo thực tế trên VPS)
- **Develop (`my-agent:develop` — single-stage `python:3.11`):** **1.67 GB** (1,670 MB disk usage · 426 MB content size)
- **Production (`my-agent:advanced` — multi-stage `python:3.11-slim`):** **240 MB** (57.4 MB content size)
- **Chênh lệch:** Giảm **85.6%** dung lượng đĩa (`(1670 - 240) / 1670 = 85.6%`).
- **Giải thích:** Stage 1 (`builder`) cài `gcc`, `libpq-dev` và `pip install --user` vào `/root/.local`; Stage 2 (`runtime`) bắt đầu từ `python:3.11-slim` sạch, chỉ `COPY --from=builder` các gói đã cài và source code, loại bỏ toàn bộ build tools, đồng thời chạy dưới user non-root `appuser` và có `HEALTHCHECK`.

### Exercise 2.4: Docker Compose stack (`02-docker/production/`)

**Kiến trúc 4 service trong mạng nội bộ `internal`:**
```text
Client --> Nginx (Reverse Proxy, Rate Limit 10r/s, Security Headers)
              |
              v (Docker internal DNS: agent:8000)
           Agent (FastAPI, 2 uvicorn workers, không mở port ra ngoài)
              |--> Redis  (redis:6379  — session cache & rate limit, volume redis_data)
              |--> Qdrant (qdrant:6333 — vector database, volume qdrant_data)
```
*(Chạy trên VPS với `-p k5-day14-docker` và override port host `127.0.0.1:18080:80` để tránh xung đột port 80/443 của Nginx hệ thống).*

**Kết quả test qua Nginx:**
```http
HTTP/1.1 200 OK
Server: nginx
X-Frame-Options: DENY
X-Content-Type-Options: nosniff
X-XSS-Protection: 1; mode=block

{"status":"ok","uptime_seconds":10.5,"version":"2.0.0","timestamp":"2026-11-26T07:41:35.751625"}
```
```http
HTTP/1.1 200 OK
Server: nginx
X-Frame-Options: DENY
X-Content-Type-Options: nosniff
X-XSS-Protection: 1; mode=block

{"answer":"Tôi là AI agent được deploy lên cloud. Câu hỏi của bạn đã được nhận."}
```

---

## Part 3: Cloud Deployment

### Exercise 3.1 / 3.2: Deploy Agent Part 6 (`06-lab-complete/`) lên Render
- **Nền tảng chính:** Render (Docker Web Service với `Root Directory: 06-lab-complete/` + Render Key Value / Redis Free).
- **Public URL:** https://k5-l3b-day14-buidangnhatnguyen.onrender.com
- **Screenshots:** `screenshots/dashboard.png`, `screenshots/running.png`, `screenshots/test.png` (chi tiết xem `DEPLOYMENT.md`).
- **Kết quả 4 lệnh tự kiểm chuẩn CP6:**
```text
/health         -> 200
/ready          -> 200
/ask (no key)   -> 401
/ask (with key) -> 200
```

### So sánh `railway.toml` vs `render.yaml`
| Tiêu chí | `railway.toml` (Railway) | `render.yaml` (Render Blueprint) |
|---|---|---|
| Định dạng & phạm vi | TOML — cấu hình **1 service** (build & deploy settings cho thư mục hiện tại) | YAML (Infrastructure as Code) — khai báo được **cả stack nhiều service** (`services:`, `databases:`) trong 1 file |
| Khai báo build/runtime | `[build] builder = "DOCKERFILE"`, `dockerfilePath = "Dockerfile"` | `type: web`, `runtime: docker`, `plan: free` |
| Quản lý biến môi trường & secret | Biến môi trường & secret thường đặt trên Dashboard/CLI (`railway variables set`) hoặc tham chiếu biến giữa các service (`${{Redis.REDIS_URL}}`) | Khai báo trực tiếp `envVars:` trong YAML; secret bắt buộc tách khỏi git bằng `generateValue: true` (Render tự sinh) hoặc `sync: false` (nhập tay trên dashboard) |
| Health check & Restart | `[deploy] healthcheckPath = "/health"`, `healthcheckTimeout`, `restartPolicyType = "ON_FAILURE"` | `healthCheckPath: /health` (Render tự kiểm tra trong quá trình zero-downtime deploy) |
| Mục đích sử dụng | Nhanh gọn cho từng service riêng lẻ, mạnh về trải nghiệm CLI/UI | Chuẩn IaC: đồng bộ hạ tầng đa dịch vụ tái lập được qua Git (Blueprint) |

### Exercise 3.3: Mô tả CI/CD Pipeline GCP Cloud Run (`03-cloud-deployment/production-cloud-run/`)
Pipeline trong `cloudbuild.yaml` kết hợp `service.yaml` gồm 4 bước tuần tự (dùng `waitFor` để chặn nếu bước trước lỗi):
1. **Test (`test`):** Chạy `pytest tests/` trên `python:3.11-slim` để đảm bảo code qua unit test trước khi đóng gói.
2. **Build (`build`):** Build Docker image gắn cả tag `$COMMIT_SHA` (bất biến để rollback) và `latest`, tận dụng `--cache-from` để tăng tốc build.
3. **Push (`push`):** Đẩy các tag image lên Google Container Registry (`gcr.io/$PROJECT_ID/ai-agent`).
4. **Deploy (`deploy`):** Gọi `gcloud run deploy` triển khai image `$COMMIT_SHA` lên Cloud Run vùng `asia-southeast1`, cấu hình autoscale `min-instances=1` (tránh cold start) đến `max-instances=10`, giới hạn `1 CPU / 512Mi RAM`, `containerConcurrency: 80`, lấy secret từ Secret Manager (`--set-secrets` / `secretKeyRef`) và gắn `livenessProbe` (`/health`) + `startupProbe` (`/ready`) theo `service.yaml`.

---

## Part 4: API Security

### Exercise 4.1: API Key Authentication (`04-api-gateway/develop`, `AGENT_API_KEY=secret-key-123`)
- API key được kiểm tra tại dependency `verify_api_key` dùng `APIKeyHeader(name="X-API-Key", auto_error=False)`.
- Thiếu key trả `401 Unauthorized`, sai key trả `403 Forbidden`, đúng key trả `200 OK`.
- Để rotate key an toàn không downtime: hỗ trợ tạm thời cả key cũ và key mới qua biến môi trường (dual-key window), chuyển client sang key mới, sau đó gỡ key cũ.

**Output `curl -i` thực tế:**
```http
# 1) Không có key -> 401
HTTP/1.1 401 Unauthorized
content-type: application/json

{"detail":"Missing API key. Include header: X-API-Key: <your-key>"}

# 2) Sai key -> 403
HTTP/1.1 403 Forbidden
content-type: application/json

{"detail":"Invalid API key."}

# 3) Đúng key -> 200
HTTP/1.1 200 OK
content-type: application/json

{"question":"Hello","answer":"Đây là câu trả lời từ AI agent (mock). Trong production, đây sẽ là response từ OpenAI/Anthropic."}
```

### Exercise 4.2 & 4.3: JWT Authentication + Rate Limiting (`04-api-gateway/production`)
- Lấy JWT tại `POST /auth/token` với tài khoản `student` / `demo123` (role `user`, giới hạn **10 req/phút**). Token đã che: `eyJhbGciOiJIUzI1NiIs...[REDACTED]`.
- `rate_limiter.py` dùng thuật toán **Sliding Window** (lưu timestamp trong `deque` theo cửa sổ 60s), phân tách hạn mức theo role (`rate_limiter_user` = 10 req/phút, `rate_limiter_admin` = 100 req/phút).

**Output `curl -i` thực tế (401 / 200 / vòng lặp / 429):**
```http
# Không có JWT -> 401
HTTP/1.1 401 Unauthorized
www-authenticate: Bearer
x-content-type-options: nosniff
x-frame-options: DENY
x-xss-protection: 1; mode=block
referrer-policy: strict-origin-when-cross-origin

{"detail":"Authentication required. Include: Authorization: Bearer <token>"}

# Request #1 có JWT (đã che token) -> 200
HTTP/1.1 200 OK
x-content-type-options: nosniff
x-frame-options: DENY

{"question":"Explain JWT","answer":"Đây là câu trả lời từ AI agent (mock). Trong production, đây sẽ là response từ OpenAI/Anthropic.","usage":{"requests_remaining":9,"budget_remaining_usd":2.1e-05}}

# Vòng lặp Request 2..12:
Request 2 -> HTTP 200
Request 3 -> HTTP 200
Request 4 -> HTTP 200
Request 5 -> HTTP 200
Request 6 -> HTTP 200
Request 7 -> HTTP 200
Request 8 -> HTTP 200
Request 9 -> HTTP 200
Request 10 -> HTTP 200
Request 11 -> HTTP 429
Request 12 -> HTTP 429

# Chi tiết Request vượt giới hạn -> 429
HTTP/1.1 429 Too Many Requests
x-ratelimit-limit: 10
x-ratelimit-remaining: 0
x-ratelimit-reset: 1795679484
retry-after: 59
x-content-type-options: nosniff
x-frame-options: DENY

{"detail":{"error":"Rate limit exceeded","limit":10,"window_seconds":60,"retry_after_seconds":59}}
```

### Exercise 4.4: Cost Guard
- **Vai trò:** Rate limit chỉ chặn *tần suất gọi* (req/phút), nhưng không chặn được user gửi đều đặn các prompt rất dài làm cháy ngân sách LLM. Cost guard chặn theo **chi phí USD thực tế** tính từ `input_tokens` và `output_tokens`.
- **Cách triển khai chuẩn production (dùng Redis):**
  - Tạo key theo chu kỳ ngày/tháng (vd `budget:{user_id}:{YYYY-MM-DD}` hoặc global `cost:daily:{YYYY-MM-DD}`) đặt TTL tự động hết hạn.
  - **Trước khi gọi LLM (`check_budget`):** đọc tổng chi phí hiện tại trong Redis; nếu `>= budget` -> trả `HTTP 402 Payment Required` (trả `503` nếu chạm ngân sách toàn hệ thống).
  - **Sau khi gọi LLM (`record_cost`):** tính `cost = (input_tokens/1000)*price_in + (output_tokens/1000)*price_out`, cộng nguyên tử bằng `INCRBYFLOAT` vào Redis và set `EXPIRE`.
  - Lưu trong Redis thay vì RAM giúp dùng chung giữa nhiều worker/instance và không mất dữ liệu khi restart.
- **Kết quả `/me/usage` sau 10 request của `student`:**
```json
{"user_id":"student","date":"2026-11-26","requests":10,"input_tokens":40,"output_tokens":312,"cost_usd":0.000193,"budget_usd":1.0,"budget_remaining_usd":0.999807,"budget_used_pct":0.0}
```

---

## Part 5: Scaling & Reliability

### Exercise 5.1 & 5.2: Health Check, Readiness Check & Graceful Shutdown (`05-scaling-reliability/develop`)
- **`GET /health` (Liveness probe):** Kiểm tra process còn sống (`status`, `uptime_seconds`, memory check `used_percent: 28.8%`). Nếu fail -> orchestrator restart container.
- **`GET /ready` (Readiness probe):** Kiểm tra app đã sẵn sàng nhận traffic chưa (`{"ready": true, "in_flight_requests": 1}`). Khi startup chưa xong, đang shutdown (`_is_ready = False`) hoặc mất kết nối dependency -> trả `503` để Load Balancer tạm ngừng gửi traffic mới mà không kill container.
- **Kết quả test Graceful Shutdown (gửi 2 request song song rồi `kill -SIGTERM` sau 0.5s):**
  - Cả 2 request đều hoàn tất với **`[HTTP 200]`** (không bị cắt ngang).
  - Server log ghi nhận đúng thứ tự: `Shutting down` -> 2x `POST /ask ... 200 OK` -> `Waiting for connections to close` -> `Graceful shutdown initiated...` -> `Shutdown complete` -> `Finished server process`.

### Exercise 5.3 – 5.5: Stateless Architecture, Nginx Load Balancing & Redis (`05-scaling-reliability/production`)
- **Tại sao không lưu state trong RAM khi scale?** Khi chạy 3 instance sau Load Balancer (round-robin), request 1 vào instance A còn request 2 vào instance B; nếu session nằm trong RAM của A thì B không có lịch sử hội thoại. Đưa state sang **Redis** giúp mọi instance đều stateless và thay thế được cho nhau.
- **Triển khai:** Chạy `docker compose -p k5-day14-scaling up -d --build --scale agent=3` (kèm override port `127.0.0.1:18080:80` trên VPS để tránh xung đột port 8080 hiện có) -> 5 container đều `Up (healthy)` (3 agent, 1 redis, 1 nginx).
- **Kết quả `test_stateless.py` thực tế:**
```text
Session ID: 6280eaa2-ee68-4149-ac82-ea38f9b33df3
Request 1: [instance-60cc91]
Request 2: [instance-0e5dbb]
Request 3: [instance-4fd8f5]
Request 4: [instance-60cc91]
Request 5: [instance-0e5dbb]
Total requests: 5
Instances used: {'instance-60cc91', 'instance-4fd8f5', 'instance-0e5dbb'}
All requests served despite different instances!
Conversation History: Total messages: 10 (5 user + 5 assistant)
Session history preserved across all instances via Redis!
```

---

## Part 6: Final Project — `check_production_ready.py` Checklist Deliverable

Chạy đầy đủ trên VPS Linux Ubuntu 24.04 (`os.name = posix`, Docker `29.5.1`) trong thư mục `06-lab-complete/` bằng lệnh `python check_production_ready.py`:

```text
================================================================
  📋 Checklist Deliverable
     ✅ Dockerfile (multi-stage, < 500 MB)
     ✅ docker-compose.yml (agent + redis)
     ✅ .dockerignore
     ✅ Health check endpoint (GET /health)
     ✅ Readiness endpoint (GET /ready)
     ✅ API Key authentication
     ✅ Rate limiting
     ✅ Cost guard
     ✅ Config từ environment variables
     ✅ Structured logging
     ✅ Graceful shutdown
     ✅ Public URL ready (Railway / Render config)
----------------------------------------------------------------
  Result: 12/12 tiêu chí đạt · 43/43 checks passed
  🎉 PASS 12/12 — PRODUCTION READY! Deploy nào!
================================================================
```

**Thông số đo thực tế:**
- Thời gian build Docker image: `27s` · Kích thước image: **`63 MB`** (< 500 MB).
- Structured logging: `17` dòng JSON hợp lệ.
- Rate limit stateless: `429` sau 5 request thành công (`RATE_LIMIT_PER_MINUTE=5`), sau restart agent vẫn trả `429`.
- Graceful shutdown: `SIGTERM` runtime -> request in-flight vẫn `200`, `exit code 0`; `docker stop` -> `exit code 0` trong **`0.7s`** (< 10s).

---

## AI log
- **CP0–CP3 (Setup VPS & Part 1, 2, 4):**
  - *Hỏi gì:* Audit cấu trúc repo K5 Day 14, kiểm tra xung đột port/tài nguyên trên VPS Linux, giải thích các khái niệm (12-Factor, PEP 668, multi-stage Docker, layer cache, JWT/rate limit/cost guard) và hướng dẫn lệnh kiểm thử an toàn không ảnh hưởng dịch vụ sẵn có trên VPS.
  - *Nhận gì:* Phân tích rubric K5, phương án cô lập port bằng Docker Compose override file ngoài repo (`/tmp`), các lệnh chạy kiểm thử và khung tổng hợp `MISSION_ANSWERS.md`.
  - *Tự sửa & tự kiểm tra:* Tự fork/đổi tên repo, tự chạy toàn bộ lệnh trên VPS Linux, tự đo kích thước image (`1.67 GB` vs `240 MB`), tự kiểm chứng các mã HTTP (`422`, `401`, `403`, `200`, `429`), và đối chiếu lại toàn bộ số liệu trong `MISSION_ANSWERS.md` khớp 100% với output thực tế.
- **CP4 (Part 5 — Scaling & Reliability):**
  - *Hỏi gì:* Cơ chế liveness vs readiness, graceful shutdown với `SIGTERM`, cấu hình Nginx `resolver 127.0.0.11` và cách test stateless 3 instance an toàn trên VPS tránh xung đột port 8080.
  - *Nhận gì:* Giải thích luồng shutdown/stateless và lệnh chạy `docker compose -p k5-day14-scaling` kèm override port loopback.
  - *Tự sửa & tự kiểm tra:* Tự chạy test `SIGTERM` (2/2 request trả `200 OK`) và `test_stateless.py` (5 request đi qua đủ 3 instance `60cc91`, `0e5dbb`, `4fd8f5`, giữ trọn 10 messages trong Redis), dọn sạch stack sau khi hoàn thành.
- **CP5 (Part 6 — Final Project `06-lab-complete/`):**
  - *Hỏi gì:* Kiến trúc 6 module Python (`config`, `redis_client`, `auth`, `rate_limiter`, `cost_guard`, `main`), cách viết `JsonFormatter` độc lập, Redis Sorted Set sliding window, `Dockerfile` multi-stage với `/opt/venv` và `exec uvicorn` làm PID 1 để `docker stop` trả exit code 0.
  - *Nhận gì:* Phân tích chi tiết từng tiêu chí chấm điểm và khung thiết kế 6 module + 5 file hạ tầng (`Dockerfile`, `docker-compose.yml`, `.dockerignore`, `railway.toml`, `render.yaml`).
  - *Tự sửa & tự kiểm tra:* Tự kiểm tra baseline (`0/12`), triển khai Chặng 5A và xác minh bằng `--skip-docker` (pass toàn bộ runtime), triển khai Chặng 5B và chạy đầy đủ `python check_production_ready.py` đạt **`PASS 12/12` (43/43 checks, image 63 MB, docker stop 0.7s)** mà không chỉnh sửa `check_production_ready.py`.
- **CP6 (Part 3 — Cloud Deployment trên Render):**
  - *Hỏi gì:* Quy trình tạo nhánh feature, mở PR đúng vào repo fork thay vì repo gốc, cấu hình Root Directory + Redis + Environment Variables trên Render, cách kiểm thử 4 endpoint và so sánh `railway.toml` / `render.yaml` / Cloud Run CI/CD.
  - *Nhận gì:* Hướng dẫn chuẩn GitHub Flow, checklist cấu hình Render, khung `DEPLOYMENT.md` và đối chiếu kỹ thuật `railway.toml` vs `render.yaml` và `cloudbuild.yaml`/`service.yaml`.
  - *Tự sửa & tự kiểm tra:* Tự tạo nhánh `feat/cp1-cp5-production-agent`, mở và merge PR #1 vào `main`, tạo Render Key Value (Redis) và đặt biến môi trường trên dashboard, kích hoạt deploy bản mới `027fdf5` lên `Live`, tự chạy 4 lệnh `curl` xác nhận `200 / 200 / 401 / 200`.
- **CP7 & CP8 (Part 7 — Benchmark, Eval & Observability Stack):**
  - *Hỏi gì:* Quy trình chạy load test 4 mức concurrency và 3 mức `MOCK_SLOW_RATE`, sửa `KNOWLEDGE_BASE` (không sửa `golden_dataset.jsonl`), khắc phục 3 lỗi thực chiến khi chạy CP8 trên VPS (`PYTHONUSERBASE` cho non-root agent container, quyền ghi `benchmark-results/` cho Locust UID 1000, cờ `--no-deps` giữ đúng `--scale agent=1/3`), SSH port forwarding xem UI an toàn và đồng bộ số liệu thật vào `BENCHMARK_REPORT.md`.
  - *Nhận gì:* Phân tích nguyên nhân từng lỗi Docker/Linux, hướng dẫn cô lập port qua `/tmp/day14-cp8-override.yml`, script đối chiếu Prometheus Alerts API và script trích xuất trực tiếp số liệu từ JSON/CSV vào `BENCHMARK_REPORT.md`.
  - *Tự sửa & tự kiểm tra:* Tự chạy lại sạch 3 mức `MOCK_SLOW_RATE` sau khi dọn cổng `8001/8002`, tự đạt eval `23/23 (100%)` không regression, tự chạy `promtool` PASS, xuất đủ `scale_1_stats.csv` & `scale_3_stats.csv`, tự chụp đủ 4 ảnh Grafana/Jaeger/Prometheus (2 alert cùng `FIRING`), đối chiếu khớp 100% số liệu giữa `BENCHMARK_REPORT.md` với JSON/CSV thật và dọn sạch stack sau khi hoàn thành.
