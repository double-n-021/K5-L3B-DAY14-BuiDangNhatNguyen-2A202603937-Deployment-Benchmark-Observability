# Deployment Information

## Public URL
https://k5-l3b-day14-buidangnhatnguyen.onrender.com

## Platform
Render (Web Service chạy Docker từ `06-lab-complete/` + Render Key Value / Redis Free)

## Test Commands

Đặt biến môi trường trước khi chạy (không ghi key thật vào tài liệu hay mã nguồn):

```bash
export BASE="https://k5-l3b-day14-buidangnhatnguyen.onrender.com"
export AGENT_API_KEY="YOUR_AGENT_API_KEY"
```

### 4 lệnh kiểm tra chuẩn CP6
```bash
# 1. Health Check (Liveness) -> 200
curl -sS -o /dev/null -w '/health         -> %{http_code}\n' "$BASE/health"

# 2. Readiness Check (Redis connected) -> 200
curl -sS -o /dev/null -w '/ready          -> %{http_code}\n' "$BASE/ready"

# 3. API Test không có key -> 401
curl -sS -o /dev/null -w '/ask (no key)   -> %{http_code}\n' \
  -X POST "$BASE/ask" -H 'Content-Type: application/json' -d '{"question":"Hello"}'

# 4. API Test có X-API-Key hợp lệ -> 200
curl -sS -o /dev/null -w '/ask (with key) -> %{http_code}\n' \
  -X POST "$BASE/ask" -H 'Content-Type: application/json' \
  -H "X-API-Key: $AGENT_API_KEY" -d '{"question":"Hello"}'
```

**Kết quả kiểm tra thực tế:**
```text
/health         -> 200
/ready          -> 200
/ask (no key)   -> 401
/ask (with key) -> 200
```

## Environment Variables Set (trên Render Dashboard — không lưu trong Git)
- `PORT` (Render tự cấp động, ví dụ `10000`)
- `ENVIRONMENT` (`production`)
- `REDIS_URL` (Internal URL của Render Key Value / Redis Free)
- `AGENT_API_KEY` (Secret API key)
- `RATE_LIMIT_PER_MINUTE` (`10`)
- `DAILY_BUDGET_USD` (`1.0`)

## Screenshots
- [Deployment dashboard](screenshots/dashboard.png)
- [Service running](screenshots/running.png)
- [Test results](screenshots/test.png)
