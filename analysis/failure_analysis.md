# Báo cáo Phân tích Thất bại (Failure Analysis Report)

## 1. Tổng quan Benchmark
- **Phiên bản ứng viên:** Agent_V2_Optimized
- **Tổng số cases:** 56
- **Tỉ lệ Pass:** 100.0%
- **Điểm trung bình Multi-Judge:** 4.71 / 5.0
- **Retrieval Hit Rate:** 100.0%
- **MRR:** 0.991
- **Faithfulness:** 0.965
- **Relevancy:** 0.946
- **Agreement Rate:** 89.9%
- **Chi phí eval ước tính:** $0.001881
- **Release Gate:** Release - Candidate improves or preserves quality while reducing estimated eval cost.

## 2. Phân nhóm lỗi (Failure Clustering)
| Nhóm lỗi | Số lượng | Nguyên nhân dự kiến |
|----------|----------|---------------------|
| None | 0 | Candidate passed all cases. |

## 3. Phân tích 5 Whys (3 case tệ nhất)

### Case #1: No failing candidate cases
1. **Symptom:** Candidate passed all benchmark cases.
2. **Why 1:** Retrieval consistently returned the expected document IDs.
3. **Why 2:** The optimized agent handled injection, ambiguous, and out-of-context prompts conservatively.
4. **Why 3:** Dataset cases align with the internal knowledge base and answer summaries.
5. **Why 4:** Offline heuristic judges reward grounded, concise policy answers.
6. **Root Cause:** Remaining risk is benchmark coverage, not an observed runtime failure.

## 4. Kế hoạch cải tiến (Action Plan)
- [x] Thêm `expected_retrieval_ids` cho toàn bộ golden dataset để đo Hit Rate và MRR.
- [x] Thêm multi-judge consensus gồm strict policy judge và semantic overlap judge.
- [x] Thêm release gate dựa trên chất lượng, retrieval, agreement, latency và chi phí.
- [ ] Thay lexical retriever bằng embedding retriever hoặc hybrid BM25 + vector search.
- [ ] Thêm reranker cho multi-hop/adversarial cases.
- [ ] Bổ sung Cohen's Kappa nếu chuyển judge score về nhãn rời rạc pass/fail/partial.
- [ ] Mở rộng red-team cases bằng dữ liệu thật từ production ticket sau khi ẩn danh.

## 5. Đề xuất giảm 30% chi phí eval
- Chạy full benchmark cho release candidate, nhưng dùng smoke set 15 cases cho mỗi commit nhỏ.
- Cache kết quả judge theo hash của question + answer + ground truth.
- Chỉ gọi judge thứ hai khi strict judge nằm trong vùng biên 2.5-3.8 hoặc retrieval fail.
- Dùng model rẻ hơn cho easy/fact-check cases và giữ model mạnh cho hard/adversarial cases.
