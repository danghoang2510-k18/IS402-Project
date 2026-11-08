import { useEffect, useState } from "react";
import type { FormEvent, ReactNode } from "react";

type IconName =
  | "forest"
  | "grid"
  | "activity"
  | "chart"
  | "arrow"
  | "cloud"
  | "shield"
  | "info"
  | "server"
  | "branch"
  | "check"
  | "code"
  | "refresh"
  | "close"
  | "chevron"
  | "flask"
  | "external";
function Icon({
  name,
  size = 20,
  className = "",
}: {
  name: IconName;
  size?: number;
  className?: string;
}) {
  const paths: Record<IconName, ReactNode> = {
    forest: (
      <>
        <path d="m8 3-5 8h3l-4 6h12l-4-6h3L8 3Z" />
        <path d="M8 17v4m8-17 5 8h-3l4 6h-6m0 0v3" />
      </>
    ),
    grid: (
      <>
        <rect x="3" y="3" width="7" height="7" rx="1.5" />
        <rect x="14" y="3" width="7" height="7" rx="1.5" />
        <rect x="3" y="14" width="7" height="7" rx="1.5" />
        <rect x="14" y="14" width="7" height="7" rx="1.5" />
      </>
    ),
    activity: <path d="M3 12h4l3-8 4 16 3-8h4" />,
    chart: (
      <>
        <path d="M4 3v17h17M8 15v-4m5 4V7m5 8V4" />
      </>
    ),
    arrow: <path d="M4 12h16m-6-6 6 6-6 6" />,
    cloud: <path d="M7 18a5 5 0 0 1-1-9 6 6 0 0 1 11-2 5.5 5.5 0 0 1 1 11H7Z" />,
    shield: (
      <>
        <path d="m12 3 8 3v6c0 5-8 9-8 9s-8-4-8-9V6l8-3Z" />
        <path d="m8 12 3 3 5-6" />
      </>
    ),
    info: (
      <>
        <circle cx="12" cy="12" r="9" />
        <path d="M12 11v6m0-10v1" />
      </>
    ),
    server: (
      <>
        <rect x="3" y="3" width="18" height="7" rx="2" />
        <rect x="3" y="14" width="18" height="7" rx="2" />
        <path d="M7 6.5h.01M7 17.5h.01m9-11h2m-2 11h2" />
      </>
    ),
    branch: (
      <>
        <circle cx="6" cy="5" r="2" />
        <circle cx="18" cy="6" r="2" />
        <circle cx="6" cy="19" r="2" />
        <path d="M6 7v10m0-5h6a6 6 0 0 0 6-4" />
      </>
    ),
    check: <path d="m5 12 4 4L19 6" />,
    code: (
      <>
        <path d="m8 7-5 5 5 5m8-10 5 5-5 5m-8 2 2-14" />
      </>
    ),
    refresh: (
      <>
        <path d="M20 7v5h-5M4 17v-5h5" />
        <path d="M6 6a8 8 0 0 1 13 3M5 15a8 8 0 0 0 13 3" />
      </>
    ),
    close: <path d="m6 6 12 12M6 18 18 6" />,
    chevron: <path d="m9 5 7 7-7 7" />,
    flask: (
      <>
        <path d="M9 3h6m-5 0v7L4 19a1 1 0 0 0 1 2h14a1 1 0 0 0 1-2l-6-9V3M7 15h10" />
      </>
    ),
    external: (
      <>
        <path d="M14 3h7v7m0-7L10 14" />
        <path d="M10 3H5a2 2 0 0 0-2 2v14a2 2 0 0 0 2 2h14a2 2 0 0 0 2-2v-5" />
      </>
    ),
  };
  return (
    <svg
      className={className}
      width={size}
      height={size}
      viewBox="0 0 24 24"
      fill="none"
      stroke="currentColor"
      strokeWidth="1.65"
      strokeLinecap="round"
      strokeLinejoin="round"
      aria-hidden="true"
    >
      {paths[name]}
    </svg>
  );
}
type Page = "overview" | "predict" | "compare";
type ModelMetrics = {
  roc_auc: number;
  average_precision: number;
  f1: number;
  precision: number;
  recall: number;
  threshold: number;
  total_trees: number;
  test_rows: number;
  confusion_matrix: { tn: number; fp: number; fn: number; tp: number };
  mode?: string;
  num_clients?: number;
  run_id?: number;
  model_matches_loaded_artifact?: boolean;
};
type DashboardData = { fl: ModelMetrics | null; central: ModelMetrics | null; missing: string[] };
type HealthData = { status: string; run_id: number; mode: string };
const nav: { id: Page; label: string; icon: IconName }[] = [
  { id: "overview", label: "Tổng quan", icon: "grid" },
  { id: "predict", label: "Dự đoán", icon: "activity" },
  { id: "compare", label: "So sánh mô hình", icon: "chart" },
];
function Tooltip({ text }: { text: string }) {
  return (
    <span className="tooltip" tabIndex={0} aria-label={text}>
      <Icon name="info" size={15} />
      <span role="tooltip">{text}</span>
    </span>
  );
}
function Badge({ children, tone = "" }: { children: ReactNode; tone?: string }) {
  return <span className={`badge ${tone}`}>{children}</span>;
}
const metricDefinitions = [
  {
    name: "ROC-AUC",
    short: "Khả năng phân biệt rủi ro",
    desc: "Đo khả năng phân biệt hai lớp trên mọi ngưỡng. Càng gần 1 càng tốt.",
    key: "roc_auc",
  },
  {
    name: "Average Precision",
    short: "Chất lượng xếp hạng lớp rủi ro",
    desc: "Tóm tắt đường Precision–Recall, phù hợp khi dữ liệu mất cân bằng.",
    key: "average_precision",
  },
  {
    name: "F1",
    short: "Cân bằng Precision và Recall",
    desc: "Trung bình điều hòa của Precision và Recall tại ngưỡng đã chọn.",
    key: "f1",
  },
  {
    name: "Precision",
    short: "",
    desc: "Tỷ lệ thực sự rủi ro trong các dự đoán rủi ro.",
    key: "precision",
  },
  {
    name: "Recall",
    short: "",
    desc: "Tỷ lệ hồ sơ rủi ro thực tế được mô hình phát hiện.",
    key: "recall",
  },
  {
    name: "Ngưỡng dự đoán",
    short: "",
    desc: "Xác suất tối thiểu để dự đoán nhãn 1; được chọn trên validation.",
    key: "threshold",
  },
  {
    name: "Số cây",
    short: "",
    desc: "Tổng số cây quyết định trong mô hình.",
    key: "total_trees",
  },
 ] as const;
function metricValue(model: ModelMetrics | null, key: keyof ModelMetrics): number | null {
  const value = model?.[key];
  return typeof value === "number" && Number.isFinite(value) ? value : null;
}
function displayNumber(value: number | null, digits = 4): string {
  return value === null ? "Chưa có" : value.toFixed(digits);
}
function MetricCard({ index, model }: { index: number; model: ModelMetrics | null }) {
  const m = metricDefinitions[index];
  return (
    <article className="metric-card">
      <div className="metric-top">
        <span>{m.name}</span>
        <Tooltip text={m.desc} />
      </div>
      <div className="metric-value">
        {displayNumber(metricValue(model, m.key))}
      </div>
      <div className="metric-bottom">
        <span>{m.short}</span>
        <span className="tiny-tag">TEST</span>
      </div>
    </article>
  );
}
function Architecture() {
  return (
    <section className="panel architecture">
      <div className="panel-heading">
        <div>
          <h2>Học phân tán. Tri thức tập trung.</h2>
          <p>Dữ liệu ở lại client. Chỉ các cây đã huấn luyện được gửi đi.</p>
        </div>
        <Badge>
          <Icon name="branch" size={13} /> Federated Learning
        </Badge>
      </div>
      <div className="flow">
        <div className="clients">
          <div className="region">
            <div className="region-label">
              <span className="region-dot" /> EAST ASIA <span>2 client</span>
            </div>
            <div className="client-row">
              {[1, 2].map((n) => (
                <div className="client" key={n}>
                  <Icon name="server" size={18} />
                  <span>Client {n}</span>
                  <small>20 cây</small>
                </div>
              ))}
            </div>
          </div>
          <div className="region">
            <div className="region-label">
              <span className="region-dot purple" /> KOREA CENTRAL <span>3 client</span>
            </div>
            <div className="client-row">
              {[3, 4, 5].map((n) => (
                <div className="client" key={n}>
                  <Icon name="server" size={18} />
                  <span>Client {n}</span>
                  <small>20 cây</small>
                </div>
              ))}
            </div>
          </div>
        </div>
        <div className="flow-connector">
          <span>
            Cây đã
            <br />
            huấn luyện
          </span>
          <div className="connector-line">
            <Icon name="arrow" size={19} />
          </div>
        </div>
        <div className="server-node">
          <div className="node-icon">
            <Icon name="forest" size={29} />
          </div>
          <strong>FL Server</strong>
          <span>Tổng hợp 100 cây</span>
          <Badge tone="blue">Random Forest</Badge>
        </div>
        <div className="flow-connector short">
          <div className="connector-line">
            <Icon name="arrow" size={19} />
          </div>
        </div>
        <div className="api-node">
          <div className="api-icon">
            <Icon name="code" size={24} />
          </div>
          <strong>Prediction API</strong>
          <span>Phục vụ dự đoán</span>
          <code>POST /api/predict</code>
        </div>
      </div>
      <div className="diagram-foot">
        <Icon name="shield" size={15} />
        <span>Không chia sẻ dữ liệu gốc giữa các client</span>
        <span className="azure-caption">
          <Icon name="cloud" size={15} /> Hạ tầng Microsoft Azure
        </span>
      </div>
    </section>
  );
}
function Method({ expanded = false }: { expanded?: boolean }) {
  return (
    <section className={`panel method ${expanded ? "expanded" : ""}`}>
      <div className="panel-heading">
        <h2>Thiết lập thực nghiệm</h2>
        <Icon name="flask" size={18} />
      </div>
      <p className="muted">Quy trình nhất quán, kết quả có thể tái lập.</p>
      <div className="split-bar">
        <span>60%</span>
        <span>20%</span>
        <span>20%</span>
      </div>
      <div className="split-labels">
        <span>
          <i />
          Train
        </span>
        <span>
          <i />
          Validation
        </span>
        <span>
          <i />
          Test
        </span>
      </div>
      <div className="method-row">
        <span>Random seed</span>
        <code>42</code>
      </div>
      <div className="method-row">
        <span>Chia dữ liệu client</span>
        <strong>IID · 5 client</strong>
      </div>
      <div className="method-note">
        <Icon name="info" size={16} />
        <span>
          Ngưỡng dự đoán được chọn trên tập <strong>validation</strong>, trước khi đánh giá test.
        </span>
      </div>
      {expanded && (
        <p className="muted">
          Mô hình tập trung học trên toàn bộ tập train. IID là phương pháp phân chia tập train cho 5
          client, không phải một tập test khác.
        </p>
      )}
    </section>
  );
}
function Overview({ go, dashboard, health }: { go: (p: Page) => void; dashboard: DashboardData | null; health: HealthData | null }) {
  const model = dashboard?.fl ?? null;
  return (
    <>
      <div className="page-eyebrow">
        <span className="eyebrow">KHÔNG GIAN NGHIÊN CỨU</span>
        <span className="research-label">
          <Icon name="flask" size={14} /> Đồ án học thuật
        </span>
      </div>
      <section className="hero">
        <div className="hero-copy">
          <Badge tone="blue">
            <span className="dot" /> FEDERATED MACHINE LEARNING
          </Badge>
          <h1>
            Dữ liệu phân tán.
            <br />
            <span>Dự đoán đáng tin cậy.</span>
          </h1>
          <p>
            Khám phá mô hình <strong>Federated Random Forest</strong> trong dự đoán rủi ro tín dụng.
            Huấn luyện cộng tác trên Azure, không tập trung dữ liệu.
          </p>
          <div className="hero-actions">
            <button className="button primary" onClick={() => go("predict")}>
              Thử dự đoán <Icon name="arrow" size={17} />
            </button>
            <button className="button secondary" onClick={() => go("compare")}>
              <Icon name="chart" size={17} /> Xem so sánh
            </button>
          </div>
          <div className="hero-detail">
            <span>
              <Icon name="server" size={15} /> 1 server
            </span>
            <span>
              <Icon name="branch" size={15} /> 5 client
            </span>
            <span>
              <Icon name="cloud" size={16} /> 2 khu vực Azure
            </span>
          </div>
        </div>
        <aside className="deployment-card">
          <div className="deployment-heading">
            <span className="square-icon">
              <Icon name="cloud" size={21} />
            </span>
            <div>
              <strong>Môi trường triển khai</strong>
              <p>Microsoft Azure Infrastructure</p>
            </div>
            <span className="deployment-ellipsis">···</span>
          </div>
          <div className="status-row">
            <span>Trạng thái API</span>
            <Badge tone={health ? "green" : "amber"}>
              <span className="dot" /> {health ? "Sẵn sàng" : "Chưa kết nối"}
            </Badge>
          </div>
          <div className="status-row">
            <span>Phiên bản mô hình</span>
            <Badge tone={health ? "green" : "amber"}>
              <span className="dot" /> {health ? "Đã tải mô hình" : "Chưa có mô hình"}
            </Badge>
          </div>
          <div className="run-box">
            <span>MODEL RUN ID</span>
            <code>
              {health?.run_id ?? "Chưa có"} <Icon name="branch" size={14} />
            </code>
          </div>
          <div className="deployment-stats">
            <div>
              <span>Chế độ huấn luyện</span>
              <strong>
                {model?.mode?.toUpperCase() ?? "Chưa có"} <span className="mini-label">{model?.num_clients ?? "?"} CLIENT</span>
              </strong>
            </div>
            <div>
              <span>Tổng số cây</span>
              <strong>
                {model?.total_trees ?? "Chưa có"} <small>cây quyết định</small>
              </strong>
            </div>
          </div>
          <div className="deployment-foot">
            <Icon name="shield" size={14} /> Không thu thập thông tin cá nhân
          </div>
        </aside>
      </section>
      <section className="metrics-section">
        <div className="section-heading">
          <div>
            <h2>Hiệu năng mô hình</h2>
            <p>Kết quả trên tập test · Không phải kết quả của hồ sơ đang nhập</p>
          </div>
          <Badge>
            {model?.test_rows?.toLocaleString("vi-VN") ?? "Chưa có"} mẫu test <span className="badge-divider" /> Kết quả FL
          </Badge>
        </div>
        <div className="metric-grid">
          {[0, 1, 2].map((i) => (
            <MetricCard key={i} index={i} model={model} />
          ))}
        </div>
      </section>
      <div className="bottom-grid">
        <Architecture />
        <Method />
      </div>
      <div className="research-notice">
        <Icon name="info" size={17} />
        <p>
          <strong>Nghiên cứu, không phải quyết định tín dụng.</strong> Kết quả chỉ phục vụ mục đích
          học thuật, không dùng để duyệt hoặc từ chối khoản vay.
        </p>
        <span>MINH BẠCH & CÓ TRÁCH NHIỆM</span>
      </div>
    </>
  );
}
const fields = [
  {
    key: "RevolvingUtilizationOfUnsecuredLines",
    label: "Tỷ lệ sử dụng tín dụng không bảo đảm",
    unit: "tỷ lệ",
    sample: "0.35",
    help: "Ví dụ: 0,35 tương đương 35%.",
    optional: false,
  },
  {
    key: "age",
    label: "Tuổi",
    unit: "năm",
    sample: "42",
    help: "Số tuổi, là số nguyên từ 18 đến 120.",
    optional: false,
  },
  {
    key: "NumberOfTime30-59DaysPastDueNotWorse",
    label: "Số lần quá hạn 30–59 ngày",
    unit: "lần",
    sample: "0",
    help: "Số lần quá hạn trong lịch sử tín dụng.",
    optional: false,
  },
  {
    key: "DebtRatio",
    label: "Tỷ lệ nợ trên thu nhập",
    unit: "tỷ lệ",
    sample: "0.28",
    help: "Tổng chi trả nợ hàng tháng / thu nhập.",
    optional: false,
  },
  {
    key: "MonthlyIncome",
    label: "Thu nhập hàng tháng",
    unit: "USD / tháng",
    sample: "5000",
    help: "Có thể bỏ trống để API điền median huấn luyện.",
    optional: true,
  },
  {
    key: "NumberOfOpenCreditLinesAndLoans",
    label: "Số khoản vay và hạn mức tín dụng",
    unit: "khoản",
    sample: "6",
    help: "Tổng số khoản vay và hạn mức đang mở.",
    optional: false,
  },
  {
    key: "NumberOfTimes90DaysLate",
    label: "Số lần quá hạn từ 90 ngày",
    unit: "lần",
    sample: "0",
    help: "Số lần quá hạn ít nhất 90 ngày.",
    optional: false,
  },
  {
    key: "NumberRealEstateLoansOrLines",
    label: "Số khoản vay bất động sản",
    unit: "khoản",
    sample: "1",
    help: "Bao gồm khoản vay và hạn mức bất động sản.",
    optional: false,
  },
  {
    key: "NumberOfTime60-89DaysPastDueNotWorse",
    label: "Số lần quá hạn 60–89 ngày",
    unit: "lần",
    sample: "0",
    help: "Số lần quá hạn từ 60 đến 89 ngày.",
    optional: false,
  },
  {
    key: "NumberOfDependents",
    label: "Số người phụ thuộc",
    unit: "người",
    sample: "2",
    help: "Có thể bỏ trống để API điền median huấn luyện.",
    optional: true,
  },
];
type Result = {
  risk_probability: number;
  predicted_label: 0 | 1;
  threshold: number;
  imputed_features: string[];
  model_run_id: string | number;
  mode: string;
};
type FormValues = Record<string, string>;
const emptyValues = () => Object.fromEntries(fields.map((f) => [f.key, ""]));
function validate(values: FormValues) {
  const errors: Record<string, string> = {};
  fields.forEach((f) => {
    const v = values[f.key].trim();
    if (!v) {
      if (!f.optional) errors[f.key] = "Vui lòng nhập giá trị cho trường này.";
      return;
    }
    const n = Number(v);
    if (!Number.isFinite(n) || n < 0) errors[f.key] = "Giá trị phải là số không âm.";
    else if (f.key === "age" && (!Number.isInteger(n) || n < 18 || n > 120))
      errors[f.key] = "Tuổi phải là số nguyên từ 18 đến 120.";
    else if (f.key.startsWith("Number") && !Number.isInteger(n))
      errors[f.key] = "Vui lòng nhập số nguyên không âm.";
  });
  return errors;
}
function isResult(data: unknown): data is Result {
  if (!data || typeof data !== "object") return false;
  const d = data as Result;
  return (
    Number.isFinite(d.risk_probability) &&
    d.risk_probability >= 0 &&
    d.risk_probability <= 1 &&
    (d.predicted_label === 0 || d.predicted_label === 1) &&
    Number.isFinite(d.threshold) &&
    d.threshold >= 0 &&
    d.threshold <= 1 &&
    Array.isArray(d.imputed_features) &&
    d.imputed_features.every((v) => typeof v === "string") &&
    (typeof d.model_run_id === "string" || typeof d.model_run_id === "number") &&
    typeof d.mode === "string"
  );
}
function Prediction() {
  const [values, setValues] = useState<FormValues>(emptyValues);
  const [errors, setErrors] = useState<Record<string, string>>({});
  const [state, setState] = useState<"empty" | "loading" | "error" | "success">("empty");
  const [result, setResult] = useState<Result | null>(null);
  const [errorText, setErrorText] = useState("");
  async function submit(e: FormEvent) {
    e.preventDefault();
    const nextErrors = validate(values);
    setErrors(nextErrors);
    if (Object.keys(nextErrors).length) {
      document.getElementById(Object.keys(nextErrors)[0])?.focus();
      return;
    }
    setState("loading");
    setResult(null);
    try {
      const response = await fetch("/api/predict", {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({
            features: Object.fromEntries(
              fields.map((f) => [
                f.key,
                values[f.key].trim() === "" ? null : Number(values[f.key]),
              ]),
            ),
          }),
          signal: AbortSignal.timeout(15000),
        });
      if (!response.ok)
          throw new Error(
            `API chưa khả dụng (HTTP ${response.status}). Vui lòng kiểm tra kết nối hoặc thử lại sau.`,
          );
      if (!response.headers.get("content-type")?.includes("application/json"))
          throw new Error("Chưa kết nối API mô hình. Máy chủ chưa trả về kết quả JSON.");
      const data: unknown = await response.json();
      if (!isResult(data))
        throw new Error("Phản hồi API không đúng định dạng. Vui lòng kiểm tra cấu hình mô hình.");
      setResult(data);
      setState("success");
    } catch (error) {
      setErrorText(
        error instanceof Error ? error.message : "Không thể kết nối API. Vui lòng thử lại.",
      );
      setState("error");
    }
  }
  const reset = () => {
    setValues(emptyValues());
    setErrors({});
    setResult(null);
    setState("empty");
  };
  return (
    <>
      <PageHeading
        eyebrow="SUY LUẬN MÔ HÌNH"
        title="Dự đoán rủi ro tín dụng"
        description="Nhập 10 đặc trưng tài chính để ước tính xác suất rủi ro bằng Federated Random Forest."
      />
      <div className="prediction-grid">
        <section className="panel form-panel">
          <div className="panel-heading">
            <div>
              <h2>Đặc trưng đầu vào</h2>
              <p>Không nhập tên, số tài khoản hoặc thông tin định danh.</p>
            </div>
            <Badge>10 đặc trưng</Badge>
          </div>
          <form onSubmit={submit} noValidate>
            <fieldset disabled={state === "loading"}>
              <div className="fields-grid">
                {fields.map((f, i) => (
                  <div className="number-field" key={f.key}>
                    <label htmlFor={f.key}>
                      <span className="field-index">{String(i + 1).padStart(2, "0")}</span>
                      {f.label}
                      {f.optional && <span className="optional">Tùy chọn</span>}
                    </label>
                    <div className={`input-wrap ${errors[f.key] ? "invalid" : ""}`}>
                      <input
                        id={f.key}
                        type="number"
                        min={f.key === "age" ? 18 : 0}
                        max={f.key === "age" ? 120 : undefined}
                        step={f.key.startsWith("Number") || f.key === "age" ? 1 : "any"}
                        value={values[f.key]}
                        placeholder={f.optional ? "Để trống → median" : `Ví dụ: ${f.sample}`}
                        onChange={(e) => {
                          setValues((v) => ({ ...v, [f.key]: e.target.value }));
                          setErrors((prev) => ({ ...prev, [f.key]: "" }));
                          setState("empty");
                          setResult(null);
                        }}
                        aria-invalid={!!errors[f.key]}
                        aria-describedby={`${f.key}-help`}
                        required={!f.optional}
                      />
                      <span>{f.unit}</span>
                    </div>
                    <div id={`${f.key}-help`} className="field-help">
                      {errors[f.key] ? (
                        <span className="field-error">{errors[f.key]}</span>
                      ) : (
                        f.help
                      )}
                      <code>{f.key}</code>
                    </div>
                  </div>
                ))}
              </div>
              <div className="form-note">
                <Icon name="info" size={17} />
                <span>
                  Thu nhập và số người phụ thuộc có thể để trống. API sẽ dùng median từ tập train và
                  trả lại danh sách trường đã điền.
                </span>
              </div>
              <div className="form-actions">
                <button
                  type="button"
                  className="button secondary"
                  onClick={() => {
                    setValues(Object.fromEntries(fields.map((f) => [f.key, f.sample])));
                    setErrors({});
                    setState("empty");
                    setResult(null);
                  }}
                >
                  <Icon name="flask" size={16} /> Dùng dữ liệu mẫu
                </button>
                <button type="button" className="text-button" onClick={reset}>
                  Xóa form
                </button>
                <button type="submit" className="button primary">
                  {state === "loading" ? (
                    <>
                      <span className="spinner" /> Đang dự đoán
                    </>
                  ) : (
                    <>
                      Dự đoán <Icon name="arrow" size={17} />
                    </>
                  )}
                </button>
              </div>
            </fieldset>
          </form>
        </section>
        <aside className="result-column">
          <section
            className="panel result-panel"
            aria-live="polite"
            aria-busy={state === "loading"}
          >
            <div className="panel-heading">
              <h2>Kết quả dự đoán</h2>
              <Icon name="activity" size={18} />
            </div>
            {state === "empty" && (
              <div className="empty-state">
                <span className="empty-icon">
                  <Icon name="activity" size={32} />
                </span>
                <h3>Sẵn sàng phân tích</h3>
                <p>Điền thông tin và chọn “Dự đoán” để xem xác suất rủi ro của hồ sơ.</p>
                <Badge>Không lưu lịch sử hồ sơ</Badge>
              </div>
            )}
            {state === "loading" && (
              <div className="empty-state">
                <span className="spinner large" />
                <h3>Đang phân tích đặc trưng</h3>
                <p>Đang gửi yêu cầu đến API mô hình…</p>
              </div>
            )}
            {state === "error" && (
              <div className="empty-state error-state">
                <span className="empty-icon">
                  <Icon name="cloud" size={30} />
                </span>
                <h3>Không thể nhận dự đoán</h3>
                <p>{errorText}</p>
                <button className="button secondary" onClick={() => setState("empty")}>
                  <Icon name="refresh" size={16} /> Kiểm tra và thử lại
                </button>
              </div>
            )}
            {state === "success" && result && (
              <div className="success-result">
                <p className="result-label">XÁC SUẤT RỦI RO</p>
                <div className={`probability ${result.predicted_label ? "high" : ""}`}>
                  {(result.risk_probability * 100).toFixed(2)}
                  <span>%</span>
                </div>
                <div className="risk-track">
                  <span style={{ width: `${result.risk_probability * 100}%` }} />
                  <i
                    style={{ left: `${result.threshold * 100}%` }}
                    title={`Ngưỡng: ${result.threshold}`}
                  />
                </div>
                <div className="risk-labels">
                  <span>0%</span>
                  <span>100%</span>
                </div>
                <Badge tone={result.predicted_label ? "amber" : "green"}>
                  <Icon name="check" size={14} /> Nhãn {result.predicted_label} ·{" "}
                  {result.predicted_label ? "Có rủi ro" : "Không thuộc lớp rủi ro"}
                </Badge>
                <div className="result-details">
                  <div>
                    <span>Ngưỡng mô hình</span>
                    <strong>{result.threshold.toFixed(4)}</strong>
                  </div>
                  <div>
                    <span>Chế độ</span>
                    <strong>{result.mode}</strong>
                  </div>
                  <div>
                    <span>Run ID</span>
                    <code>{result.model_run_id}</code>
                  </div>
                </div>
                <div className="imputed">
                  <h3>Trường được điền median</h3>
                  {result.imputed_features.length ? (
                    <ul>
                      {result.imputed_features.map((key) => (
                        <li key={key}>{fields.find((f) => f.key === key)?.label || key}</li>
                      ))}
                    </ul>
                  ) : (
                    <p>Không có. Tất cả đặc trưng đã được cung cấp.</p>
                  )}
                </div>
              </div>
            )}
          </section>
          <div className="safety-note">
            <Icon name="shield" size={21} />
            <div>
              <strong>Chỉ phục vụ nghiên cứu</strong>
              <p>
                Kết quả không phải quyết định duyệt hoặc từ chối khoản vay. Không lưu trữ dữ liệu
                hoặc lịch sử hồ sơ.
              </p>
            </div>
          </div>
        </aside>
      </div>
    </>
  );
}
function PageHeading({
  eyebrow,
  title,
  description,
}: {
  eyebrow: string;
  title: string;
  description: string;
}) {
  return (
    <div className="page-heading">
      <span className="eyebrow">{eyebrow}</span>
      <h1>{title}</h1>
      <p>{description}</p>
    </div>
  );
}
function ConfusionMatrix({ federated, model }: { federated: boolean; model: ModelMetrics | null }) {
  const matrix = model?.confusion_matrix;
  const cells = matrix ? [
    ["TN", matrix.tn],
    ["FP", matrix.fp],
    ["FN", matrix.fn],
    ["TP", matrix.tp],
  ] as const : [];
  return (
    <section className="panel matrix-panel">
      <div className="panel-heading">
        <h2>{federated ? "Federated Random Forest – IID" : "Random Forest tập trung"}</h2>
        <Badge tone={federated ? "blue" : ""}>{federated ? "FL · IID" : "Tập trung"}</Badge>
      </div>
      {!matrix ? <p className="matrix-note">Chưa có ma trận nhầm lẫn từ kết quả chạy.</p> : <>
      <div className="matrix-axis">Nhãn dự đoán</div>
      <div className="matrix-layout">
        <div className="vertical-axis">Nhãn thực tế</div>
        <div className="matrix-content">
          <div className="matrix-col-labels">
            <span>0 · Không rủi ro</span>
            <span>1 · Có rủi ro</span>
          </div>
          <div className="matrix-cells">
            {cells.map(([label, value], i) => (
              <div key={label} className={`matrix-cell ${i === 0 || i === 3 ? "correct" : ""}`}>
                <span>
                  {label} <small>{i < 2 ? "Thực tế 0" : "Thực tế 1"}</small>
                </span>
                <strong>{Number(value).toLocaleString("vi-VN")}</strong>
                <small>
                  {
                    (
                      {
                        TN: "Âm tính đúng",
                        FP: "Dương tính giả",
                        FN: "Âm tính giả",
                        TP: "Dương tính đúng",
                      } as Record<string, string>
                    )[label]
                  }
                </small>
              </div>
            ))}
          </div>
        </div>
      </div>
      <p className="matrix-note">{model?.test_rows?.toLocaleString("vi-VN")} hàng test · Kết quả thí nghiệm</p>
      </>}
    </section>
  );
}
function Comparison({ dashboard }: { dashboard: DashboardData | null }) {
  const [selected, setSelected] = useState(0);
  const metric = metricDefinitions[selected];
  const central = dashboard?.central ?? null;
  const fl = dashboard?.fl ?? null;
  const values = [metricValue(central, metric.key), metricValue(fl, metric.key)];
  const max = selected === 6 ? Math.max(100, ...(values.filter((v): v is number => v !== null))) : 1;
  const testRows = fl?.test_rows ?? central?.test_rows;
  return (
    <>
      <PageHeading
        eyebrow="ĐÁNH GIÁ THỰC NGHIỆM"
        title="Hai cách học. Cùng một thước đo."
        description={`So sánh Random Forest tập trung và Federated Random Forest – IID trên cùng tập test${testRows ? ` ${testRows.toLocaleString("vi-VN")} hàng` : ""}.`}
      />
      <div className="comparison-banner">
        <Icon name="info" size={19} />
        <p>
          {central && fl
            ? fl.model_matches_loaded_artifact
              ? "Hai mô hình được đánh giá theo cùng giao thức và tập test. Kết quả FL khớp mô hình đang phục vụ."
              : "Hai mô hình được đánh giá theo cùng giao thức và tập test. Kết quả FL chưa được xác nhận khớp mô hình đang phục vụ."
            : "Chưa có đủ kết quả hai mô hình. Hãy cung cấp file metrics tập trung và FL cho API."}
        </p>
        <Badge tone={central && fl ? "green" : "amber"}>{central && fl ? "KẾT QUẢ THỰC NGHIỆM" : "THIẾU DỮ LIỆU"}</Badge>
      </div>
      <div className="comparison-top">
        <section className="panel chart-panel">
          <div className="panel-heading">
            <div>
              <h2>
                So sánh theo chỉ số <Tooltip text={metric.desc} />
              </h2>
              <p>{metric.desc}</p>
            </div>
            <select
              aria-label="Chọn chỉ số biểu đồ"
              value={selected}
              onChange={(e) => setSelected(Number(e.target.value))}
            >
              {metricDefinitions.map((m, i) => (
                <option value={i} key={m.name}>
                  {m.name}
                </option>
              ))}
            </select>
          </div>
          <div className="chart-legend">
            <span>
              <i />
              Random Forest tập trung
            </span>
            <span>
              <i />
              Federated Random Forest – IID
            </span>
          </div>
          <div className="bar-chart">
            <div className="chart-grid">
              {[0, 1, 2, 3, 4].map((n) => (
                <div key={n}>
                  <span>{((max * n) / 4).toLocaleString("vi-VN")}</span>
                </div>
              ))}
            </div>
            <div className="bars">
              {values.map((v, i) => (
                <div className="bar-row" key={i}>
                  <span>{i ? "Federated · IID" : "RF tập trung"}</span>
                  <div className="bar-track">
                    {v === null ? <span>Chưa có dữ liệu</span> : <div
                      className={`bar bar-${i}`}
                      style={{ width: `${Math.max(8, (v / max) * 100)}%` }}
                      tabIndex={0}
                      aria-label={`${i ? "Federated" : "Tập trung"}: ${v}`}
                    >
                      <span>{selected === 6 ? v : v.toFixed(4)}</span>
                      <div className="bar-tooltip">
                        {metric.name}: {v}
                        <br />
                        {metric.desc}
                      </div>
                    </div>}
                  </div>
                </div>
              ))}
            </div>
          </div>
          <div className="chart-foot">
            <Icon name="info" size={14} /> Di chuột hoặc focus thanh biểu đồ để xem chi tiết · Số
            liệu thực nghiệm
          </div>
        </section>
        <Method expanded />
      </div>
      <section className="panel table-panel">
        <div className="panel-heading">
          <div>
            <h2>Bảng chỉ số chi tiết</h2>
            <p>Ngưỡng được chọn độc lập trên validation cho từng mô hình.</p>
          </div>
          <Badge>Test · {testRows?.toLocaleString("vi-VN") ?? "Chưa có"} hàng</Badge>
        </div>
        <p className="scroll-hint">Vuốt ngang để xem đầy đủ bảng →</p>
        <div
          className="table-scroll"
          tabIndex={0}
          role="region"
          aria-label="Bảng so sánh mô hình, có thể cuộn ngang"
        >
          <table>
            <thead>
              <tr>
                <th>Chỉ số</th>
                <th>Random Forest tập trung</th>
                <th>
                  Federated Random Forest <Badge tone="blue">IID</Badge>
                </th>
              </tr>
            </thead>
            <tbody>
              {metricDefinitions.map((m) => (
                <tr key={m.name}>
                  <td>
                    {m.name} <Tooltip text={m.desc} />
                  </td>
                  <td>{displayNumber(metricValue(central, m.key), m.key === "total_trees" ? 0 : 4)}</td>
                  <td>{displayNumber(metricValue(fl, m.key), m.key === "total_trees" ? 0 : 4)}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </section>
      <div className="section-heading matrix-section-heading">
        <div>
          <h2>Ma trận nhầm lẫn</h2>
          <p>Phân bố nhãn dự đoán so với nhãn thực tế trên tập test.</p>
        </div>
        <Badge>Số lượng mẫu · Test</Badge>
      </div>
      <div className="matrix-grid">
        <ConfusionMatrix federated={false} model={central} />
        <ConfusionMatrix federated model={fl} />
      </div>
      <div className="comparison-bottom">
        <section className="panel limitations">
          <h2>
            <Icon name="info" size={18} /> Giới hạn so sánh
          </h2>
          <ul>
            <li>
              Một lần chạy chưa chứng minh sự khác biệt có ý nghĩa thống kê. Cần lặp lại thực nghiệm
              với nhiều seed và khoảng tin cậy.
            </li>
            <li>
              Số byte payload của mảng cây không đại diện cho tổng lưu lượng mạng; chưa bao gồm giao
              thức, metadata và truyền lại.
            </li>
          </ul>
        </section>
        <section className="non-iid">
          <Icon name="branch" size={22} />
          <div>
            <h3>Federated · non-IID</h3>
            <p>
              Chưa có kết quả chạy thật. Mô hình này chỉ được đưa vào so sánh khi có dữ liệu thực
              nghiệm.
            </p>
          </div>
          <Badge>Chưa đánh giá</Badge>
        </section>
      </div>
    </>
  );
}
export default function App() {
  const [dashboard, setDashboard] = useState<DashboardData | null>(null);
  const [health, setHealth] = useState<HealthData | null>(null);
  useEffect(() => {
    let active = true;
    fetch("/api/dashboard", { signal: AbortSignal.timeout(10000) })
      .then((response) => response.ok ? response.json() : Promise.reject(new Error("Dashboard unavailable")))
      .then((data: DashboardData) => { if (active) setDashboard(data); })
      .catch(() => { if (active) setDashboard(null); });
    fetch("/api/healthz", { signal: AbortSignal.timeout(10000) })
      .then((response) => response.ok ? response.json() : Promise.reject(new Error("Model unavailable")))
      .then((data: HealthData) => { if (active && data.status === "ready") setHealth(data); })
      .catch(() => { if (active) setHealth(null); });
    return () => { active = false; };
  }, []);
  const initialPage = () =>
    nav.some((n) => n.id === window.location.hash.slice(1))
      ? (window.location.hash.slice(1) as Page)
      : "overview";
  const [page, setPage] = useState<Page>(initialPage);
  useEffect(() => {
    const onHash = () => setPage(initialPage());
    window.addEventListener("hashchange", onHash);
    return () => window.removeEventListener("hashchange", onHash);
  }, []);
  const go = (p: Page) => {
    window.location.hash = p;
    setPage(p);
    window.scrollTo({ top: 0, behavior: "instant" });
  };
  return (
    <div className="app">
      <header className="site-header">
        <div className="header-inner">
          <a
            className="brand"
            href="#overview"
            onClick={() => go("overview")}
            aria-label="FRF Lab - Tổng quan"
          >
            <span className="brand-mark">
              <Icon name="forest" size={28} />
            </span>
            <span className="brand-word">
              FRF<span>Lab</span>
              <small>FEDERATED RANDOM FOREST</small>
            </span>
          </a>
          <nav aria-label="Điều hướng chính">
            {nav.map((n) => (
              <a
                href={`#${n.id}`}
                className={page === n.id ? "active" : ""}
                aria-current={page === n.id ? "page" : undefined}
                key={n.id}
                onClick={() => go(n.id)}
              >
                <Icon name={n.icon} size={17} />
                {n.label}
              </a>
            ))}
          </nav>
          <div className="header-meta">
            <Icon name="cloud" size={19} />
            <span>
              Powered by <strong>Azure</strong>
            </span>
            <span className="header-divider" />
            <span className="version">v1.0</span>
          </div>
        </div>
      </header>
      <div className="context-bar">
        <div>
          <span>Federated Random Forest</span>
          <Icon name="chevron" size={12} />
          <strong>{nav.find((n) => n.id === page)?.label}</strong>
          <span className="preview-label"><span className="dot" /> {health ? "Mô hình sẵn sàng" : "Mô hình chưa kết nối"}</span>
        </div>
      </div>
      <main key={page}>
        {page === "overview" ? (
          <Overview go={go} dashboard={dashboard} health={health} />
        ) : page === "predict" ? (
          <Prediction />
        ) : (
          <Comparison dashboard={dashboard} />
        )}
      </main>
      <footer>
        <div>
          <span className="footer-brand">
            <Icon name="forest" size={18} /> FRF Lab
          </span>
          <span>Federated Random Forest · Dự đoán rủi ro tín dụng</span>
        </div>
        <span>
          Đồ án nghiên cứu <span className="footer-separator">/</span> Xây dựng trên Microsoft Azure
        </span>
      </footer>
    </div>
  );
}
