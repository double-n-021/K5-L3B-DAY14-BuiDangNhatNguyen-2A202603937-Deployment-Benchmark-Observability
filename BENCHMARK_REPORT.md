# Benchmark & Observability Report — Day 14

**Họ tên:** Bui Dang Nhat Nguyen — MSSV: 2A202603937
**Ngày chạy:** 2026-11-26
**Môi trường:** VPS Linux Ubuntu 24.04.4 LTS (x86_64), 6 vCPU Xeon E5-2696 v4, 7.8 GiB RAM, Python 3.12.3, Docker 29.5.1, Docker Compose v5.1.3

---

## 1. SLO của agent

| SLI | SLO | Lý do chọn ngưỡng này |
|---|---|---|
| p95 latency `/ask` | < 500 ms | Với mock LLM latency cơ bản ~120–180ms + retrieval ~20ms, p95 < 500ms đảm bảo 95% người dùng nhận phản hồi mượt mà; nếu > 500ms nghĩa là hệ thống đã bị nghẽn hàng đợi hoặc tail latency tăng bất thường |
| Error rate `/ask` | < 2.0 % | Mock LLM có tỷ lệ lỗi upstream mặc định ~1% (`MOCK_ERROR_RATE=0.01`), nên chọn ngưỡng SLO 2% (Error budget = 2%) để chấp nhận nhiễu nhẹ nhưng phát hiện ngay lỗi bất thường |
| Accuracy trên golden dataset | ≥ 85 % (mục tiêu sau sửa KB: 100%) | Đảm bảo agent trả lời chính xác phần lớn câu hỏi cốt lõi và chặn mọi bản phát hành gây regression |

---

## 2. Benchmark hiệu năng (develop, `load_test.py`)

### 2.1 Concurrency vs latency (agent v2, `requests=300`)

| Concurrency | RPS | p50 (ms) | p95 (ms) | p99 (ms) | Error rate | SLO |
|---|---|---|---|---|---|---|
| 1 | 4.49 | 188.1 | 216.4 | 1676.7 | 0.00% | PASS |
| 10 | 40.17 | 190.9 | 220.5 | 1685.7 | 0.33% | PASS |
| 50 | 132.33 | 205.3 | 267.0 | 1685.2 | 1.67% | PASS |
| 100 | 49.59 | 798.1 | 4954.1 | 5289.2 | 0.67% | FAIL |

**Nhận xét:** RPS **không** tăng tuyến tính mãi theo concurrency. Từ `c=1` đến `c=50`, RPS tăng mạnh từ `4.49` → `40.17` → `132.33 req/s` trong khi `p95` vẫn giữ dưới `267.0 ms` (PASS SLO) vì FastAPI/uvicorn xử lý I/O bất đồng bộ (`async/await`) tốt. Tuy nhiên đến `c=100`, 1 process uvicorn chạm điểm bão hòa (saturation) và tranh chấp hàng đợi/CPU/connection → RPS tụt mạnh xuống `49.59 req/s` và `p95` nhảy vọt lên `4954.1 ms` (**FAIL SLO**).

### 2.2 Tail latency (`requests=300`, `concurrency=20`)

| `MOCK_SLOW_RATE` | avg (ms) | p95 (ms) | p99 (ms) |
|---|---|---|---|
| 0 | 193.2 | 223.6 | 243.3 |
| 0.03 (mặc định) | 223.4 | 225.8 | 1679.9 |
| 0.1 | 331.6 | 1692.0 | 1723.4 |

**Nhận xét:** **`p99` và `p95`** nhạy nhất với request chậm:
- Khi tăng `MOCK_SLOW_RATE` từ `0` lên `0.03` (3% request chậm), `avg` chỉ nhích nhẹ `+30.2 ms` (`193.2` → `223.4 ms`) nhưng `p99` đã tăng gần **7 lần** (`243.3` → `1679.9 ms`).
- Khi tăng lên `0.1` (10% request chậm > ngưỡng 5%), `avg` chỉ là `331.6 ms` (nhìn qua tưởng vẫn đạt < 500ms!), nhưng **`p95` vọt lên `1692.0 ms`** (FAIL SLO).
- Vì giá trị trung bình (`avg`) bị chi phối bởi số đông request nhanh và **che giấu hoàn toàn trải nghiệm tệ của nhóm user rơi vào tail latency**, SLO bắt buộc phải đặt theo **percentile (`p95`/`p99`)**.

---

## 3. Benchmark chất lượng (develop, `eval/run_eval.py`)

| Chỉ số | Agent v1 | Agent v2 | Agent v2 (sau khi sửa KB) |
|---|---|---|---|
| Accuracy | 4.3% (1/23) | 91.3% (21/23) | 100.0% (23/23) |
| Avg tokens / câu | 57.8 | 109.0 | 113.7 |
| Tổng cost (USD) | $0.000414 | $0.000760 | $0.000790 |
| Cost / câu đúng (USD) | $0.00041355 | $0.00003619 | $0.00003436 |
| Quality gate | FAIL | PASS | PASS |

**Những câu v2 trả lời sai ban đầu và cách bạn sửa (`develop/utils/mock_llm.py`, giữ nguyên `golden_dataset.jsonl`):**

| ID | Keyword bị thiếu | Bạn đã sửa gì |
|---|---|---|
| `security-02` | `token`, `hết hạn`, `chữ ký` | Thêm tài liệu về so sánh API Key và JWT (`["jwt"]`) vào `KNOWLEDGE_BASE` trong `utils/mock_llm.py` |
| `scaling-03` | `cpu`, `memory`, `custom metrics` | Thêm tài liệu về Kubernetes HPA (`["hpa", "kubernetes", "autoscal"]`) vào `KNOWLEDGE_BASE` trong `utils/mock_llm.py` |

*(Sau khi sửa `KNOWLEDGE_BASE` và khởi động lại agent v2, eval đạt **23/23 = 100.0%** với **0 câu regression** so với `eval_v2.json`.)*

**Nhận xét về trade-off chất lượng / chi phí / latency giữa v1 và v2:**
- **v2** thêm bước retrieval (RAG) nên prompt dài hơn (~2 lần token/câu: `57.8` → `113.7`) và latency tăng thêm ~20ms cho retrieval, tổng chi phí tăng gần gấp đôi (`$0.000414` → `$0.000790`).
- Tuy nhiên độ chính xác tăng vọt từ **`4.3%`** lên **`100.0%`**, giúp **cost trên mỗi câu trả lời đúng giảm hơn 12 lần** (`$0.00041355` → `$0.00003436`). Điều này chứng minh `cost / câu đúng` phản ánh hiệu quả kinh tế thực chất tốt hơn `cost / câu`.

**Quality gate trong CI/CD (Exercise 7.3):**
`run_eval.py` trả về **exit code `0`** khi đạt `accuracy >= --min-accuracy` và **0 regression** so với `--baseline`, ngược lại trả **exit code `1`** để CI tự động đánh fail bước check và chặn merge PR:

```yaml
name: agent-quality-gate
on: [pull_request]
jobs:
  eval:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4
      - uses: actions/setup-python@v5
        with:
          python-version: "3.11"
      - name: Run agent v2 & eval quality gate
        working-directory: 06-lab-complete/benchmark-observability/develop
        run: |
          pip install -r requirements.txt
          AGENT_VERSION=v2 MOCK_ERROR_RATE=0 python app.py &
          sleep 3
          python eval/run_eval.py --url http://localhost:8000 --min-accuracy 0.85
```

---

## 4. Observability stack (production)

### 4.1 Screenshot & Câu hỏi Exercise 7.4
- [x] Dashboard Grafana khi đang có tải: [`screenshots/grafana-dashboard.png`](screenshots/grafana-dashboard.png) *(hiển thị Traffic `62.4 req/s`, Error rate `1.14%`, Latency p95 `293.91 ms`, In-flight `15`, Instances up `3`, LLM cost 1h `$0.5011`; biểu đồ Latency `p99=1.85s`, `p95=295ms`, `avg=240ms`, `p50=178ms`)*
- [x] Một trace chậm trong Jaeger: [`screenshots/jaeger-slow-trace.png`](screenshots/jaeger-slow-trace.png)
- [x] Một trace lỗi trong Jaeger (có event `exception`): [`screenshots/jaeger-error-trace.png`](screenshots/jaeger-error-trace.png)
- [x] Trang Alerts của Prometheus với 2 alert đang **firing**: [`screenshots/prometheus-alert-firing.png`](screenshots/prometheus-alert-firing.png)

**Trả lời nhanh Exercise 7.4:**
1. **Khoảng cách `avg` (240ms) vs `p95` (295ms) vs `p99` (1.85s):** Cho thấy phân phối latency bị lệch phải (right-skewed tail latency do ~3% request chậm +1.5s).
2. **Traffic theo instance:** Nginx dùng Docker internal DNS round-robin phân phối đều request giữa các instance agent.
3. **Vì sao `input tokens/s` > `output tokens/s`:** Ở agent v2 (RAG), mỗi prompt gửi vào LLM phải ghép thêm `SYSTEM_PROMPT` + tài liệu context đã retrieve + câu hỏi người dùng nên input luôn dài hơn câu trả lời ngắn gọn ở output.
4. **`curl http://localhost:8080/metrics` (hoặc `:18080` qua override trên VPS) trả `HTTP 404`:** Nginx cố tình chặn `/metrics` từ bên ngoài để tránh lộ thông tin nội bộ hệ thống (số instance, error rate, cost, lưu lượng); chỉ Prometheus bên trong mạng nội bộ `obs_net` mới được scrape trực tiếp `agent:8000/metrics`.

### 4.2 Thí nghiệm "phá hệ thống" & Alert unit test (`promtool test rules` -> `SUCCESS`)

| # | Thay đổi | Alert nào firing | Thời gian từ lúc đổi → firing | Panel nào phản ánh rõ nhất |
|---|---|---|---|---|
| A | `MOCK_ERROR_RATE=0.2` (kèm Locust 30 users) | `AgentHighErrorRate` (`for: 1m`, giá trị đo `19.6%` > `5%`) | `pending` lúc `t=18s` → **`FIRING` lúc `t=78s`** (~1 phút 18 giây) | Panel **Error rate** chuyển đỏ (~20%), **Requests/s theo status code** tăng mạnh `503` |
| D | `docker pause k5-day14-observability-agent-2` (ở `t=5s`) | `AgentInstanceDown` (`for: 30s`, `up == 0` tại `172.18.0.8:8000`) | `pending` lúc `t=8s` → **`FIRING` lúc `t=58s`** (~53 giây sau lúc pause) | Panel **Instances up** giảm đi 1 instance; Nginx timeout có thể sinh lỗi `504` (không xuất hiện trên metric error của agent vì request không hoàn tất trong agent) |
| E | `AGENT_VERSION=v1` (phân tích lý thuyết từ kết quả eval CP7) | **Không có alert nào firing** | Không firing | Panel **Retrieval hit ratio** mất và **Tokens/s** giảm, nhưng Error rate & Latency vẫn xanh |

**Thí nghiệm E không làm alert nào firing. Bạn sẽ phát hiện loại sự cố này trong production bằng cách nào?**
Observability hạ tầng (4 Golden Signals) chỉ đo được *tốc độ và tính sẵn sàng*, không đánh giá được *nội dung câu trả lời có đúng hay không*. Để phát hiện suy giảm chất lượng trên production cần kết hợp:
1. **Offline Quality Gate trong CI/CD:** Chạy `eval/run_eval.py` trên golden dataset + so sánh `--baseline` trước mỗi lần deploy (chặn PR nếu tụt accuracy hoặc có regression).
2. **Online Quality Monitoring:** Lấy mẫu traffic thật (vd 5–10%) để chấm tự động bằng **LLM-as-a-Judge** (groundedness, faithfulness, relevance) và theo dõi metric `retrieval_hit_ratio` (tụt về 0 là dấu hiệu RAG hỏng).
3. **User feedback loop:** Ghi nhận tín hiệu người dùng (thumbs up/down, tỷ lệ hỏi lại/thoát phiên) và đặt alert khi tỷ lệ phản hồi tiêu cực tăng đột biến.

### 4.3 Debug bằng trace

Chọn 1 trace chậm nhất tìm được trong Jaeger (khớp `trace_id` với JSON log của container `agent`):

- `trace_id`: `a82cc782020fadaaa3e089cb50f4abf1`
- Tổng thời gian: **`1.7 s`** (~`1665–1670 ms` trên Jaeger UI)
- Span chiếm nhiều thời gian nhất: **`chat mock-llm-small`** (**`1640.8 ms`**, chiếm **~98.3%** tổng thời gian request; trong khi `agent.retrieve_context` chỉ mất `24.8 ms` ~1.5% → chứng tỏ nút thắt đến từ upstream LLM, không phải code retrieval hay FastAPI).
- Dòng log JSON tương ứng (grep từ `docker compose -p k5-day14-observability logs agent` theo `trace_id`):

```json
{"ts": "2026-11-26T09:15:13.583061+00:00", "level": "INFO", "service": "observable-agent", "instance": "741b6b13626b", "event": "llm_call", "trace_id": "a82cc782020fadaaa3e089cb50f4abf1", "span_id": "c881d22b23ca78b4", "request_id": "280ae449112a", "model": "mock-llm-small", "agent_version": "v2", "input_tokens": 74, "output_tokens": 37, "cost_usd": 3.3e-05, "llm_ms": 1640.8}
```

*(Ngoài ra đã đối chiếu trace lỗi `trace_id: 1f006ee0e9d3ffb85d2e21c5195d00aa` khớp dòng log `llm_error`: `Upstream LLM error: 503 Service Unavailable (mock)` với `Events (1)` hiển thị `exception.type = utils.mock_llm.LLMError`.)*

---

## 5. Benchmark scaling (production, Locust headless, 100 users, 2 phút, endpoint `POST /ask`)

| Số instance | RPS | p50 (ms) | p95 (ms) | p99 (ms) | Failures |
|---|---|---|---|---|---|
| 1 | 59.27 | 200 | 380 | 1700 | 79/7063 (1.12%) |
| 3 | 60.25 | 200 | 250 | 1700 | 72/7179 (1.00%) |

**Giải thích kết quả:**
- Khi scale từ 1 lên 3 instance agent (mỗi container giới hạn `0.5 CPU`), **`p95` cải thiện rõ rệt từ `380 ms` xuống `250 ms`** (-34%) và `max` giảm từ `2106.5 ms` xuống `1758.9 ms` nhờ giảm tranh chấp CPU và hàng đợi trên mỗi container.
- Tuy nhiên **`p50` (`200 ms`) và `p99` (`1700 ms`) gần như không đổi**, và RPS chỉ tăng nhẹ (`59.27` → `60.25 req/s`) vì **hai nút thắt ngoài tầng agent**:
  1. **Upstream LLM latency (I/O bound):** Mock LLM tốn cố định ~120–180ms (và 3% slow ~1.7s); tăng thêm container agent không thể làm LLM trả lời nhanh hơn.
  2. **Giới hạn nguồn tải Locust:** 100 user có `wait_time = between(0.5, 2)` (trung bình nghỉ 1.25s + 0.25s xử lý = 1.5s/vòng) nên trần tải sinh ra của 100 user chỉ quanh ~60–66 req/s.

---

## 6. Kết luận

- **3 điều học được về benchmark & observability:**
  1. **Đừng tin latency trung bình (`avg`):** Luôn đo `p95`/`p99` vì một tỷ lệ nhỏ tail latency (3–10%) đủ phá vỡ trải nghiệm người dùng dù `avg` trông vẫn đẹp.
  2. **Metrics – Traces – Logs phải liên kết với nhau qua `trace_id`:** Metric/Alert báo *khi nào* hệ thống bất thường, Trace chỉ ra *chậm hay lỗi ở span nào* (`chat mock-llm-small` vs retrieval), và JSON Log cho chi tiết ngữ cảnh sự kiện.
  3. **Hạ tầng xanh không đồng nghĩa chất lượng tốt:** Phải kết hợp cả benchmark hiệu năng (load test), observability hạ tầng và eval chất lượng tự động (quality gate + `cost / câu đúng`) trong CI/CD.
- **Nếu đưa agent này lên production thật, các metric / alert cần bổ sung thêm:**
  - **Metrics & Alerts phía Load Balancer/API Gateway (Nginx/Ingress):** Đo `502`/`504` timeout và latency end-to-end từ góc nhìn client (khắc phục điểm mù của thí nghiệm D).
  - **LLM-specific metrics:** Time-to-First-Token (`TTFT`), token/giây streaming, tỷ lệ cache hit (semantic/Redis cache), tỷ lệ bị chặn bởi Rate Limiter (`429`) và Cost Guard (`402`).
  - **Quality & Safety alerts:** Tỷ lệ `retrieval_hit_ratio` tụt ngưỡng, điểm LLM-as-a-Judge trung bình giảm, hoặc tỷ lệ guardrail trigger tăng đột biến, đẩy cảnh báo qua Alertmanager tới Slack/PagerDuty.
