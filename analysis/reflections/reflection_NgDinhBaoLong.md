# Reflection - NgDinhBaoLong

## Vai trò và đóng góp
Tôi hoàn thiện hệ thống AI Evaluation Factory theo hướng có thể chạy offline và tái lập kết quả. Các phần chính gồm synthetic golden dataset 56 cases, retrieval evaluation, multi-judge consensus, async runner, regression release gate và báo cáo failure analysis.

## Kiến thức kỹ thuật đã áp dụng
- **Hit Rate:** đo xem tài liệu đúng có xuất hiện trong top-k retrieval hay không.
- **MRR:** đo vị trí tài liệu đúng đầu tiên; tài liệu đúng càng đứng đầu thì MRR càng cao.
- **Agreement Rate:** đo mức đồng thuận giữa strict policy judge và semantic overlap judge.
- **Position Bias:** được kiểm tra ở mức sanity check bằng đổi vị trí response; trong bản offline heuristic, judge không phụ thuộc thứ tự hiển thị.
- **Cost/Quality trade-off:** phiên bản V2 giảm chi phí ước tính nhờ token/cost profile thấp hơn, trong khi vẫn phải vượt ngưỡng avg score, hit rate, MRR và pass rate.

## Kết quả chính
- Candidate version: Agent_V2_Optimized
- Avg score: 4.71 / 5.0
- Hit Rate: 100.0%
- MRR: 0.991
- Agreement Rate: 89.9%
- Release decision: Release

## Bài học rút ra
Đánh giá generation mà bỏ qua retrieval sẽ không chỉ ra được nguyên nhân gốc của hallucination. Khi có expected retrieval IDs, hệ thống biết lỗi nằm ở truy xuất tài liệu hay ở phần sinh câu trả lời. Multi-judge cũng giúp tránh phụ thuộc vào một rubric duy nhất, đặc biệt với hard cases như prompt injection, ambiguous question và out-of-context question.
